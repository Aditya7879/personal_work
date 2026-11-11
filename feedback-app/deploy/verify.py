"""Recheck an existing private deployment without rebuilding or exposing services.

Only --enable-worker changes a service, and only after authenticated app/data
checks pass. HTTP 404 is a routing failure, not accepted as proof of private IAM.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import urllib.error
import urllib.request


PROJECT = "oa-apmena-techsandbox-ap-dv"
SERVICE_ACCOUNT = "411502743425-compute@developer.gserviceaccount.com"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default="europe-west1")
    parser.add_argument("--enable-worker", action="store_true")
    args = parser.parse_args()
    artifacts = Path(tempfile.mkdtemp(prefix="feedback-cloudrun-verify-", dir="/tmp/opencode"))
    summary = {"project": PROJECT, "region": args.region, "ready": False, "checks": {}, "artifacts": str(artifacts)}

    def cloud(*arguments: str) -> str:
        result = subprocess.run(["gcloud", *arguments, "--project=" + PROJECT, "--quiet"], capture_output=True, text=True, check=True)
        return result.stdout.strip()

    token = cloud("auth", "print-identity-token")  # Credential stays in memory.
    account = cloud("config", "get-value", "account").lower()
    opener = urllib.request.build_opener(NoRedirect())

    demo_token = None

    def get(url: str, signed: bool = False, payload: dict | None = None):
        headers = {"Cache-Control": "no-cache"}
        if signed:
            headers.update({"Authorization": "Bearer " + token, "X-Feedback-User-Authorization": "Bearer " + token})
            if demo_token:
                headers["X-Feedback-Demo-Authorization"] = "Bearer " + demo_token
        if payload is not None:
            headers["Content-Type"] = "application/json"
        try:
            with opener.open(urllib.request.Request(url, headers=headers, data=json.dumps(payload).encode() if payload is not None else None), timeout=120) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    try:
        services = {}
        for name in ("neo-feedback-api", "neo-feedback-ui"):
            service = json.loads(cloud("run", "services", "describe", name, "--region=" + args.region, "--format=json"))
            if service["metadata"].get("labels", {}).get("app") != "neo-feedback":
                raise RuntimeError("The target service is not owned by this application")
            account_name = service["spec"]["template"]["spec"].get("serviceAccountName")
            if account_name != SERVICE_ACCOUNT:
                raise RuntimeError("A service is not using the requested default compute account")
            if service["metadata"].get("annotations", {}).get("run.googleapis.com/invoker-iam-disabled") == "true":
                raise RuntimeError("The invoker IAM check was unexpectedly disabled")
            policy = json.loads(cloud("run", "services", "get-iam-policy", name, "--region=" + args.region, "--format=json"))
            if any(member in {"allUsers", "allAuthenticatedUsers"} for binding in policy.get("bindings", []) for member in binding.get("members", [])):
                raise RuntimeError("An unexpected public/blanket IAM binding is present")
            services[name] = service
            summary["checks"][name] = {"url": service["status"]["url"], "defaultComputeIdentity": True, "invokerIamEnabled": True, "noPublicBindings": True}
        frontend = services["neo-feedback-ui"]["status"]["url"]
        api_env = {value["name"]: value.get("value") for value in services["neo-feedback-api"]["spec"]["template"]["spec"]["containers"][0].get("env", []) if "value" in value}
        private_demo = api_env.get("FEEDBACK_AUTH_MODE") == "private_demo"
        summary["privateDemoPicker"] = private_demo
        status, _ = get(frontend + "/", True)
        summary["checks"]["authenticatedFrontendHttpStatus"] = status
        if status != 200:
            raise RuntimeError(f"Authenticated frontend request returned HTTP {status} before app verification. Check routing/network access; IAM has not been weakened.")
        for name, service in services.items():
            status, _ = get(service["status"]["url"] + ("/docs" if name == "neo-feedback-api" else "/"))
            summary["checks"][name]["anonymousHttpStatus"] = status
            if status not in {401, 403}:
                raise RuntimeError(f"Anonymous access check is inconclusive or failed for {name} (HTTP {status})")
        expected_identity = account
        if private_demo:
            status, data = get(frontend + "/api/auth/mock-users", True)
            if status != 200 or not any(profile.get("role") == "reviewer" for profile in json.loads(data)):
                raise RuntimeError("The verified presenter could not load the original account picker")
            expected_identity = "quality.reviewer@example.test"
            status, data = get(frontend + "/api/auth/mock-login", True, {"email": expected_identity})
            if status != 200:
                raise RuntimeError("The verified presenter could not select the demo reviewer")
            demo_token = json.loads(data)["accessToken"]
        for path, label in (("/api/auth/me", "identity"), ("/api/overview", "bigquery"), ("/api/evidence/status", "neo4j")):
            status, data = get(frontend + path, True)
            summary["checks"][label + "HttpStatus"] = status
            if status != 200:
                raise RuntimeError(f"Authenticated {label} check returned HTTP {status}")
            payload = json.loads(data)
            if label == "identity" and (payload.get("email", "").lower() != expected_identity or payload.get("role") != "reviewer"):
                raise RuntimeError("The explicit reviewer identity check failed")
            if label == "bigquery":
                summary["checks"]["feedbackCount"] = payload.get("feedback_total")
            if label == "neo4j":
                if not payload.get("connected") or payload.get("backend") != "neo4j" or payload.get("localFallbackEnabled") is not False:
                    raise RuntimeError("Neo4j is not available with the configured no-fallback policy")
                summary["checks"]["neo4j"] = {key: payload.get(key) for key in ("documents", "completed_documents", "chunks", "embedded_chunks", "corpusVersion")}
        status, _ = get(frontend + "/api/auth/mock-users", True)
        if status != (200 if private_demo else 404):
            raise RuntimeError("Development mock sign-in was not disabled")
        summary["checks"]["mockSignInDisabled"] = not private_demo
        if args.enable_worker:
            cloud("run", "services", "update", "neo-feedback-api", "--region=" + args.region,
                  "--update-env-vars=FEEDBACK_WORKER_ENABLED=true", "--min-instances=1", "--no-cpu-throttling")
            summary["workerEnabled"] = True
        summary["ready"] = True
    except Exception as error:
        summary["failure"] = str(error) if isinstance(error, RuntimeError) else "Cloud metadata/connection verification failed; no worker was enabled"
    finally:
        (artifacts / "verification-result.json").write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary, indent=2))
    if not summary["ready"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
