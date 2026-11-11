"""Deploy an IAM-private sandbox UI/API using the default compute identity.

Build contexts are explicit allowlists. Credentials travel to Secret Manager on
stdin, never to images, build sources, command arguments or console logs. This
does not initialize BigQuery, ingest documents, enqueue work, or invoke an agent.
"""
from __future__ import annotations

import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request

from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parents[1]
PROJECT = "oa-apmena-techsandbox-ap-dv"
SERVICE_ACCOUNT = "411502743425-compute@developer.gserviceaccount.com"
API = "neo-feedback-api"
UI = "neo-feedback-ui"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default="europe-west1")
    parser.add_argument("--neo4j-env-file", type=Path, default=Path("/home/dhruv/loreal-neo/llm-graph-builder/backend/.env"))
    parser.add_argument("--manifest", type=Path, default=Path("/home/dhruv/loreal-neo/llm-graph-builder/output/rca_markdown_gcs_visual_analysis/manifest.json"))
    access = parser.add_mutually_exclusive_group(required=True)
    access.add_argument("--grant-current-deployer", action="store_true", help="Explicitly grant only the active company gcloud identity reviewer access")
    access.add_argument("--reviewer", action="append", help="Explicit company reviewer email; repeat for additional grants")
    parser.add_argument("--enable-worker", action="store_true", help="After smoke checks, keep one always-CPU backend instance for persisted jobs (incurs idle billing)")
    parser.add_argument("--rotate-owned-secrets", action="store_true", help="Explicitly add new versions to this app's existing secrets")
    parser.add_argument("--private-demo", action="store_true", help="Keep the original account picker behind verified, explicitly granted presenter access")
    parser.add_argument("--demo-users-file", type=Path, default=Path("/tmp/opencode/feedback-app-runtime/mock-users.json"), help="Private server-side original demo profile mapping; never uploaded to a build")
    args = parser.parse_args()
    artifacts = Path(tempfile.mkdtemp(prefix="feedback-cloudrun-deploy-", dir="/tmp/opencode"))
    os.chmod(artifacts, 0o700)
    print("Private deployment artifacts: " + str(artifacts), flush=True)
    step = 0

    def cloud(arguments: list[str], *, data: str | None = None, allow_failure: bool = False, label: str = "cloud", sensitive_output: bool = False):
        nonlocal step
        step += 1
        result = subprocess.run(["gcloud", *arguments, "--project=" + PROJECT, "--quiet"], input=data,
                                capture_output=True, text=True)
        # Only metadata/status is logged. Secret payloads are stdin, not echoed.
        log = artifacts / f"{step:03d}-{label}.log"
        log.write_text("Credential output intentionally not logged.\n" if sensitive_output else result.stdout + "\n" + result.stderr)
        if result.returncode and not allow_failure:
            raise RuntimeError(f"Cloud operation failed ({label}); inspect private log {log}")
        return result

    def value(arguments: list[str], **kwargs) -> str:
        return cloud(arguments, **kwargs).stdout.strip()

    account = value(["config", "get-value", "account"], label="deployer-account").lower()
    if not account.endswith("@loreal.com"):
        raise RuntimeError("Use the intended company gcloud identity for this sandbox deployment")
    reviewers = [account] if args.grant_current_deployer else list(dict.fromkeys(email.strip().lower() for email in args.reviewer))
    if any(not email.endswith("@loreal.com") for email in reviewers):
        raise RuntimeError("Only explicit company reviewer grants are supported by this private preview deployer")
    token = value(["auth", "print-identity-token", "--account=" + account], label="identity-bootstrap", sensitive_output=True)
    part = token.split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    if claims.get("email", "").lower() != account or claims.get("email_verified") is not True or not claims.get("aud"):
        raise RuntimeError("The active Google identity could not be verified for bootstrap configuration")

    for service in (API, UI):
        existing = cloud(["run", "services", "describe", service, "--region=" + args.region, "--format=json"], allow_failure=True, label="inspect-" + service)
        if existing.returncode == 0 and json.loads(existing.stdout).get("metadata", {}).get("labels", {}).get("app") != "neo-feedback":
            raise RuntimeError("Refusing to overwrite an existing service not owned by this app")
        if existing.returncode and not any(word in existing.stderr.lower() for word in ("not found", "not_found", "cannot find")):
            raise RuntimeError("Cannot safely inspect the target service before deployment")

    graph = dotenv_values(args.neo4j_env_file)
    required = ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD", "OPENAI_API_KEY")
    if any(not graph.get(key) for key in required) or (graph.get("EMBEDDING_PROVIDER") or "openai").lower() != "openai":
        raise RuntimeError("The selected Neo4j/embedding configuration is incomplete or unsupported")
    manifest_bytes = args.manifest.read_bytes()
    manifest = json.loads(manifest_bytes)
    expected_documents = sum(len(document.get("markdown_files", [])) for document in manifest["documents"])
    corpus_version = "neo-rca-visual-" + hashlib.sha256(manifest_bytes).hexdigest()[:20]

    def ensure_secret(name: str, payload: str) -> str:
        existing = cloud(["secrets", "describe", name, "--format=json"], allow_failure=True, label="inspect-" + name)
        if existing.returncode == 0:
            if json.loads(existing.stdout).get("labels", {}).get("app") != "neo-feedback":
                raise RuntimeError("Refusing to replace another application's secret")
            if args.rotate_owned_secrets:
                cloud(["secrets", "versions", "add", name, "--data-file=-"], data=payload, label="rotate-" + name)
        else:
            if not any(word in existing.stderr.lower() for word in ("not found", "not_found")):
                raise RuntimeError("Cannot safely inspect a deployment secret")
            cloud(["secrets", "create", name, "--replication-policy=automatic", "--labels=app=neo-feedback,environment=sandbox", "--data-file=-"],
                  data=payload, label="create-" + name)
        versions = json.loads(value(["secrets", "versions", "list", name, "--sort-by=~createTime", "--format=json"], label="versions-" + name))
        enabled = next((version for version in versions if str(version.get("state", "")).upper() == "ENABLED"), None)
        if not enabled:
            raise RuntimeError("No enabled version is available for an application secret")
        return name + ":" + enabled["name"].rsplit("/", 1)[-1]

    secret_refs = {
        "FEEDBACK_NEO4J_URI": ensure_secret("neo-feedback-neo4j-uri", graph["NEO4J_URI"]),
        "FEEDBACK_NEO4J_USERNAME": ensure_secret("neo-feedback-neo4j-user", graph["NEO4J_USERNAME"]),
        "FEEDBACK_NEO4J_PASSWORD": ensure_secret("neo-feedback-neo4j-password", graph["NEO4J_PASSWORD"]),
        "FEEDBACK_EVIDENCE_EMBEDDING_API_KEY": ensure_secret("neo-feedback-embedding-key", graph["OPENAI_API_KEY"]),
        "FEEDBACK_AUTH_SECRET": ensure_secret("neo-feedback-auth-secret", secrets.token_urlsafe(48)),
    }
    if args.private_demo:
        profiles = args.demo_users_file.read_text()
        if not isinstance(json.loads(profiles), list):
            raise RuntimeError("The private demo profile mapping must be a JSON array")
        secret_refs["FEEDBACK_MOCK_USERS_JSON"] = ensure_secret("neo-feedback-demo-profiles", profiles)
    print("Secret Manager references prepared; no credentials are in the build contexts.", flush=True)

    backend = artifacts / "backend-source"
    frontend = artifacts / "frontend-source"
    backend.mkdir(); frontend.mkdir()
    for name in ("Dockerfile", ".dockerignore", "requirements.txt"):
        shutil.copy2(ROOT / "backend" / name, backend / name)
    shutil.copytree(ROOT / "backend/app", backend / "app", ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".env", ".env.*"))
    (backend / "evidence-manifest.json").write_bytes(manifest_bytes)
    for name in ("Dockerfile", ".dockerignore", "package.json", "package-lock.json", "server.mjs", "index.html", "vite.config.ts", "tsconfig.json"):
        shutil.copy2(ROOT / "agent-quality-console" / name, frontend / name)
    shutil.copytree(ROOT / "agent-quality-console/src", frontend / "src")
    for directory in (backend, frontend):
        (directory / ".gcloudignore").write_text(".git\n.env\n.env.*\n.venv\nnode_modules\n__pycache__\n*.pyc\n")
        if any(path.name == ".env" or path.name.startswith(".env.") for path in directory.rglob("*")):
            raise RuntimeError("A private environment file entered a build context")

    import datetime
    tag = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
    registry = f"{args.region}-docker.pkg.dev/{PROJECT}/cloud-run-source-deploy"

    def build(service: str, source: Path) -> tuple[str, str]:
        image = f"{registry}/{service}:{tag}"
        docker_args = ["build"] + (["--build-arg", "VITE_AUTH_MODE=private_demo"] if args.private_demo and service == UI else []) + ["-t", image, "."]
        config = {"steps": [{"name": "gcr.io/cloud-builders/docker", "args": docker_args}], "images": [image],
                  "serviceAccount": f"projects/{PROJECT}/serviceAccounts/{SERVICE_ACCOUNT}", "options": {"logging": "CLOUD_LOGGING_ONLY"}, "timeout": "1200s"}
        config_file = artifacts / (service + "-build.json")
        config_file.write_text(json.dumps(config, indent=2))
        # Separate logs avoid sharing the CLI helper's status counter across threads.
        result = subprocess.run(["gcloud", "builds", "submit", str(source), "--config=" + str(config_file), "--project=" + PROJECT,
            "--region=" + args.region, "--suppress-logs", "--format=json", "--quiet"], capture_output=True, text=True)
        (artifacts / (service + "-build.log")).write_text(result.stdout + "\n" + result.stderr)
        if result.returncode:
            raise RuntimeError("Image build failed for " + service + "; inspect its private build log")
        build_record = json.loads(result.stdout)
        (artifacts / (service + "-build-result.json")).write_text(json.dumps(build_record, indent=2))
        digest = build_record["results"]["images"][0]["digest"]
        return service, image.rsplit(":", 1)[0] + "@" + digest

    print("Building the UI and API images with the default compute build identity…", flush=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(build, API, backend), pool.submit(build, UI, frontend)]
        images = dict(future.result() for future in futures)
    local = dotenv_values(ROOT / "backend/.env")
    targets = json.loads(local.get("FEEDBACK_AGENT_TARGETS_JSON") or "[]")
    # Never activate a production target or the separate golden-evaluation adapter.
    targets = [target for target in targets if target.get("environment") != "prod"]
    if any(target.get("auth") not in {"google_access_token", "google_id_token"} for target in targets):
        raise RuntimeError("Cloud deployment only supports server-owned runtime Google credentials")
    backend_env = {"FEEDBACK_APP_ENV": "sandbox", "FEEDBACK_AUTH_MODE": "google_iam", "FEEDBACK_MOCK_USERS_JSON": "",
        "FEEDBACK_GOOGLE_IAM_AUDIENCES_JSON": json.dumps([claims["aud"]]), "FEEDBACK_GOOGLE_IAM_USERS_JSON": json.dumps([
            {"email": email, "displayName": "Sandbox reviewer", "role": "reviewer", "active": True} for email in reviewers]),
        "FEEDBACK_GOOGLE_IAM_DOMAINS": "loreal.com", "GCP_PROJECT_ID": PROJECT, "BIGQUERY_DATASET": "agent_quality", "BIGQUERY_LOCATION": "europe-west1",
        "FEEDBACK_ALLOW_ALL_ORIGINS": "false", "FEEDBACK_CORS_ORIGINS": "", "FEEDBACK_WORKER_ENABLED": "false", "FEEDBACK_WORKER_POLL_SECONDS": "15",
        "FEEDBACK_EVIDENCE_BACKEND": "neo4j", "FEEDBACK_NEO4J_ENV_FILE": "", "FEEDBACK_NEO4J_DATABASE": graph.get("NEO4J_DATABASE") or "neo4j",
        "FEEDBACK_NEO4J_DOCUMENT_PREFIX": "NEO_RCA-VisualAnalysis__", "FEEDBACK_NEO4J_VECTOR_INDEX": "vector", "FEEDBACK_NEO4J_FULLTEXT_INDEX": "keyword",
        "FEEDBACK_NEO4J_SOURCE_MANIFEST": "/app/data/evidence-manifest.json", "FEEDBACK_NEO4J_CORPUS_VERSION": corpus_version,
        "FEEDBACK_EVIDENCE_EMBEDDING_MODEL": graph.get("EMBEDDING_MODEL") or "text-embedding-3-small",
        "FEEDBACK_EVIDENCE_EMBEDDING_BASE_URL": graph.get("OPENAI_BASE_URL") or "https://api.openai.com/v1", "FEEDBACK_EVIDENCE_QUERY_TIMEOUT_SECONDS": "20",
        "FEEDBACK_AGENT_TARGETS_JSON": json.dumps(targets), "FEEDBACK_PROD_RETEST_REVIEWERS": "", "NEO_AGENT_API_URL": "",
        "BTAP_GATEWAY_URL": local.get("BTAP_GATEWAY_URL") or "https://x-np.api.loreal.net/global/it4it/btapgateways-aigateway/v1", "BTAP_MODEL": "claude-sonnet-4-6"}
    if args.private_demo:
        backend_env["FEEDBACK_AUTH_MODE"] = "private_demo"
        backend_env["FEEDBACK_PRIVATE_DEMO_PRESENTERS"] = ",".join(reviewers)
        backend_env.pop("FEEDBACK_MOCK_USERS_JSON")
    backend_config = artifacts / "backend-env.json"
    backend_config.write_text(json.dumps(backend_env, indent=2))

    def deploy(service: str, config: Path, extra: list[str]) -> str:
        print("Deploying IAM-private " + service + "…", flush=True)
        cloud(["run", "deploy", service, "--image=" + images[service], "--region=" + args.region,
            "--service-account=" + SERVICE_ACCOUNT, "--no-allow-unauthenticated", "--invoker-iam-check", "--ingress=all",
            "--labels=app=neo-feedback,environment=sandbox", "--port=8080", "--timeout=600", "--max-instances=1", "--min-instances=0",
            "--env-vars-file=" + str(config), *extra], label="deploy-" + service)
        return value(["run", "services", "describe", service, "--region=" + args.region, "--format=value(status.url)"], label="url-" + service)

    backend_url = deploy(API, backend_config, ["--memory=1Gi", "--cpu=1", "--concurrency=16", "--set-secrets=" + ",".join(name + "=" + ref for name, ref in secret_refs.items())])
    cloud(["run", "services", "add-iam-policy-binding", API, "--region=" + args.region,
           "--member=serviceAccount:" + SERVICE_ACCOUNT, "--role=roles/run.invoker"], label="backend-workload-invoker")
    frontend_config = artifacts / "frontend-env.json"
    frontend_config.write_text(json.dumps({"FEEDBACK_BACKEND_URL": backend_url}, indent=2))
    frontend_url = deploy(UI, frontend_config, ["--memory=512Mi", "--cpu=1", "--concurrency=40"])
    for email in reviewers:
        cloud(["run", "services", "add-iam-policy-binding", UI, "--region=" + args.region,
               "--member=user:" + email, "--role=roles/run.invoker"], label="frontend-developer-invoker")

    def status(url: str, authenticated: bool = False, demo_token: str | None = None, payload: dict | None = None):
        headers = {"Cache-Control": "no-cache"}
        if authenticated:
            headers.update({"Authorization": "Bearer " + token, "X-Feedback-User-Authorization": "Bearer " + token})
        if demo_token:
            headers["X-Feedback-Demo-Authorization"] = "Bearer " + demo_token
        if payload is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, headers=headers, data=json.dumps(payload).encode() if payload is not None else None)
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    policies = {}
    code, _ = status(frontend_url + "/", True)
    if code != 200:
        raise RuntimeError("Authenticated frontend routing check failed (HTTP " + str(code) + "). Both services remain private and the cloud worker remains disabled. Diagnose routing/network access, then run deploy/verify.py without rebuilding.")
    for service, url in ((API, backend_url), (UI, frontend_url)):
        policy = json.loads(value(["run", "services", "get-iam-policy", service, "--region=" + args.region, "--format=json"], label="policy-" + service))
        if any(member in {"allUsers", "allAuthenticatedUsers"} for binding in policy.get("bindings", []) for member in binding.get("members", [])):
            raise RuntimeError("Anonymous or blanket authenticated access was unexpectedly present")
        code, _ = status(url + ("/docs" if service == API else "/"))
        if code not in {401, 403}:
            raise RuntimeError("An unauthenticated service invocation was not blocked")
        policies[service] = {"anonymousHttpStatus": code, "noPublicIamBindings": True}
    demo_token = None
    expected_identity = account
    if args.private_demo:
        code, data = status(frontend_url + "/api/auth/mock-users", True)
        if code != 200 or not any(profile.get("role") == "reviewer" for profile in json.loads(data)):
            raise RuntimeError("The original private demo picker did not return its reviewer/reporter profiles")
        expected_identity = "quality.reviewer@example.test"
        code, data = status(frontend_url + "/api/auth/mock-login", True, payload={"email": expected_identity})
        if code != 200:
            raise RuntimeError("The verified presenter could not select the demo reviewer")
        demo_token = json.loads(data)["accessToken"]
    code, data = status(frontend_url + "/api/auth/me", True, demo_token)
    if code != 200 or json.loads(data).get("email", "").lower() != expected_identity:
        raise RuntimeError("The private frontend/backend user identity smoke check failed (HTTP " + str(code) + ")")
    code, data = status(frontend_url + "/api/overview", True, demo_token)
    if code != 200:
        raise RuntimeError("The runtime BigQuery check failed (HTTP " + str(code) + ")")
    overview = json.loads(data)
    code, data = status(frontend_url + "/api/evidence/status", True, demo_token)
    evidence = json.loads(data)
    if code != 200 or evidence.get("documents") != expected_documents or evidence.get("backend") != "neo4j" or not evidence.get("connected") or evidence.get("localFallbackEnabled") is not False:
        raise RuntimeError("The runtime Neo4j manifest/index check failed")
    code, _ = status(frontend_url + "/api/auth/mock-users", True)
    if code != (200 if args.private_demo else 404):
        raise RuntimeError("Development identity selection was not disabled")
    if args.enable_worker:
        cloud(["run", "services", "update", API, "--region=" + args.region, "--update-env-vars=FEEDBACK_WORKER_ENABLED=true",
               "--min-instances=1", "--no-cpu-throttling"], label="enable-persisted-worker")
        backend_env["FEEDBACK_WORKER_ENABLED"] = "true"
        backend_config.write_text(json.dumps(backend_env, indent=2))
    summary = {"project": PROJECT, "region": args.region, "serviceAccount": SERVICE_ACCOUNT,
        "backend": {"service": API, "url": backend_url, "image": images[API], "workerEnabled": args.enable_worker},
        "frontend": {"service": UI, "url": frontend_url, "image": images[UI]}, "iam": policies,
        "mockSignInEnabled": args.private_demo, "verifiedPresenterRequired": args.private_demo, "explicitReviewerGrants": len(reviewers), "bigqueryFeedbackCount": overview.get("feedback_total"),
        "neo4j": {key: evidence.get(key) for key in ("documents", "completed_documents", "chunks", "embedded_chunks", "corpusVersion", "localFallbackEnabled")},
        "agentInvoked": False, "feedbackSchemaInitialized": False, "documentsReingested": False,
        "localProxyCommand": "python3 deploy/proxy.py --port 8080", "artifacts": str(artifacts)}
    (artifacts / "deployment-result.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
