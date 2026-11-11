"""Server-owned invocation targets. Browser input can never supply an endpoint."""
from __future__ import annotations

import json
import ipaddress
import re
import os
import time
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

import google.auth
from google.auth import impersonated_credentials
from google.auth.transport.requests import Request
from google.oauth2 import id_token
import httpx

from .auth import AuthenticatedUser
from .agent_errors import AgentInvocationError
from .config import settings
from .demo_context import is_demo
from .neo_companion import parse_companion_response, validate_answer


@dataclass(frozen=True)
class AgentTarget:
    id: str
    agent_id: str
    environment: str
    label: str
    url: str = ""
    auth: str = "none"
    token_env: str = ""
    audience: str = ""
    version: str | None = None
    protocol: str = "quality_json"
    timeout_seconds: int = 120
    enabled: bool = True
    configuration_version: int | None = None

    def blocked_reason(self, user: AuthenticatedUser) -> str | None:
        if not self.enabled:
            return "This environment is disabled"
        if not self.url:
            return "Agent connection is not configured"
        if self.auth == "bearer_env" and (not self.token_env or not os.getenv(self.token_env)):
            return "Agent authentication secret is not configured"
        if user.role != "reviewer":
            return "Reviewer access is required to run the agent"
        return None

    def public_dict(self, user: AuthenticatedUser) -> dict:
        reason = self.blocked_reason(user)
        return {"id": self.id, "agentId": self.agent_id, "environment": self.environment, "label": self.label,
                "configured": bool(self.url), "canRetest": reason is None, "reason": reason, "agentVersion": self.version,
                 "protocol": self.protocol, "timeoutSeconds": self.timeout_seconds}


def legacy_environment_id(agent_id: str, kind: str) -> str | None:
    """Only map a legacy kind when the original configuration identifies one target."""
    if kind not in {"nonprod", "prod"}:
        return None
    try:
        matches = [target.id for target in agent_targets() if target.agent_id == agent_id and target.environment == kind]
    except (ValueError, KeyError):
        return None
    return matches[0] if len(matches) == 1 else None


def stored_environment_kind(agent_id: str, kind: str, environment_id: str | None) -> str:
    """Old deployed clients must treat custom named environments as unassigned.

    Canonical kind/identity is retained in versioned context/snapshots. This fences
    older kind-only confirmation APIs that share the same BigQuery dataset.
    """
    return kind if not environment_id or environment_id == legacy_environment_id(agent_id, kind) else "unknown"


def validate_environment_target(target: AgentTarget) -> None:
    """A reviewer must never turn an environment URL into a token-exfiltration/SSRF endpoint."""
    if not target.url:
        if target.enabled:
            raise ValueError("Add an endpoint URL before enabling this environment")
        return
    url = urlsplit(target.url)
    local = settings.app_env in {"dev", "development", "local", "test"} and not os.getenv("K_SERVICE") and url.hostname in {"localhost", "127.0.0.1", "::1"}
    if url.username or url.password or url.query or url.fragment or not url.hostname:
        raise ValueError("Endpoint URLs cannot contain credentials, query strings or fragments")
    if url.scheme != "https" and not (local and url.scheme == "http"):
        raise ValueError("Endpoint URLs must use HTTPS")
    if not local and (url.hostname.lower() in {"localhost", "metadata.google.internal", "metadata"} or url.hostname.lower().endswith((".localhost", ".internal"))):
        raise ValueError("Local and metadata-service hosts are not permitted for remote environments")
    allowed = set(settings.agent_allowed_hosts)
    allowed.update(urlsplit(item.url).hostname for item in agent_targets() if item.url)
    if not local and url.hostname.lower() not in allowed:
        raise ValueError("Endpoint host is not approved. Ask the operator to allow it in FEEDBACK_AGENT_ALLOWED_HOSTS")
    if not local:
        try:
            ipaddress.ip_address(url.hostname)
        except ValueError:
            pass
        else:
            raise ValueError("IP-address endpoints are not permitted")
        if url.port not in {None, 443}:
            raise ValueError("Remote endpoints must use the standard HTTPS port")
    elif url.port is None or url.port < 1024:
        raise ValueError("Local test endpoints must use an explicit unprivileged port")
    canonical_path = unquote(url.path)
    if "btdp-genaiengine/v1/contexts/" in canonical_path.lower() and target.protocol != "neo_companion":
        raise ValueError("A NEO Companion endpoint must use the Companion response format")
    if target.protocol == "neo_companion":
        parts = canonical_path.strip("/").split("/")
        if len(parts) < 7 or parts[-7:-4] != ["btdp-genaiengine", "v1", "contexts"] or parts[-3] != "configs" or parts[-1] != "generations" or not parts[-4] or not parts[-2]:
            raise ValueError("Use a NEO contexts/{context}/configs/{config}/generations URL")
        if target.auth != "google_access_token":
            raise ValueError("NEO Companion requires runtime Google OAuth authentication")
        if parts[-4].lower().endswith("-np") != (target.environment == "nonprod"):
            raise ValueError("The context's production/non-production scope does not match the environment type")
    if target.auth not in {"google_access_token", "google_id_token", "none"}:
        raise ValueError("New environments must use a supported runtime authentication method")


def agent_targets() -> list[AgentTarget]:
    if is_demo():
        from .demo_simulation import targets
        return targets()
    targets = [AgentTarget("neo-nonprod", settings.default_agent_id, "nonprod", "NEO · Non-production"),
               AgentTarget("neo-prod", settings.default_agent_id, "prod", "NEO · Production")]
    if settings.neo_agent_api_url:
        targets[0] = AgentTarget("neo-nonprod", settings.default_agent_id, "nonprod", "NEO · Non-production",
                                 settings.neo_agent_api_url + "/api/agent/runs")
    if settings.agent_targets_json.strip():
        rows = json.loads(settings.agent_targets_json)
        if not isinstance(rows, list):
            raise ValueError("FEEDBACK_AGENT_TARGETS_JSON must be a JSON array")
        targets = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("Each agent target must be an object")
            if row.get("environment") not in {"nonprod", "prod"}:
                raise ValueError("Agent target environment must be nonprod or prod")
            protocol = str(row.get("protocol") or "quality_json")
            timeout = row.get("timeout_seconds", 300 if protocol == "neo_companion" else 120)
            if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 600:
                raise ValueError("Agent timeout_seconds must be an integer between 1 and 600")
            target = AgentTarget(id=str(row["id"]), agent_id=str(row.get("agent_id") or settings.default_agent_id),
                                 environment=row["environment"], label=str(row.get("label") or row["id"]),
                                 url=str(row.get("url") or ""), auth=str(row.get("auth") or "none"),
                                 token_env=str(row.get("token_env") or ""), audience=str(row.get("audience") or ""),
                                 version=row.get("version"), protocol=protocol, timeout_seconds=timeout)
            if target.url:
                parsed = urlsplit(target.url)
                local = parsed.hostname in {"localhost", "127.0.0.1", "::1"} and settings.app_env in {"dev", "development", "local", "test"}
                if parsed.scheme != "https" and not (parsed.scheme == "http" and local):
                    raise ValueError("Agent target URLs must use HTTPS, except explicitly configured local development targets")
                if parsed.username or parsed.password or parsed.fragment or parsed.query:
                    raise ValueError("Do not put credentials or fragments in agent target URLs")
            if target.auth not in {"none", "bearer_env", "google_id_token", "google_access_token"}:
                raise ValueError("Unsupported agent target authentication")
            if target.protocol not in {"quality_json", "neo_companion"}:
                raise ValueError("Unsupported agent target protocol")
            if target.protocol == "neo_companion" and target.url:
                path = urlsplit(target.url).path.strip("/").split("/")
                if (len(path) < 7 or path[-7:-4] != ["btdp-genaiengine", "v1", "contexts"]
                        or path[-3] != "configs" or path[-1] != "generations" or not path[-4] or not path[-2]):
                    raise ValueError("NEO Companion targets must use a contexts/{id}/configs/{id}/generations URL")
                if path[-4].casefold().endswith("-np") and target.environment != "nonprod":
                    raise ValueError("A non-production Companion context cannot be labelled production")
                if target.auth not in {"google_access_token", "bearer_env"}:
                    raise ValueError("NEO Companion requires Google OAuth access-token authentication")
            targets.append(target)
    if len({target.id for target in targets}) != len(targets):
        raise ValueError("Agent target IDs must be unique")
    for target in targets:
        if target.url:
            parsed = urlsplit(target.url)
            local = parsed.hostname in {"localhost", "127.0.0.1", "::1"} and settings.app_env in {"development", "dev", "local", "test"}
            if not parsed.hostname or parsed.username or parsed.password or parsed.fragment or parsed.query or (parsed.scheme != "https" and not (local and parsed.scheme == "http")):
                raise ValueError("Invalid agent target URL")
    return targets


def get_target(target_id: str) -> AgentTarget:
    target = next((value for value in agent_targets() if value.id == target_id), None)
    if target is None:
        raise ValueError("Choose a configured agent target")
    return target


def diagnostic_preview(text: str, headers: dict) -> str:
    value = text
    for header in headers.values():
        if isinstance(header, str) and header.startswith("Bearer "):
            value = value.replace(header[7:], "[REDACTED]")
    value = re.sub(r"(?i)\bBearer\s+\S+", "Bearer [REDACTED]", value)
    value = re.sub(r"\b(?:ya29\.[A-Za-z0-9._~-]+|eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)\b", "[REDACTED]", value)
    value = re.sub(r"(?i)(password|api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret)\s*[:=]\s*[^\s,;]+", r"\1=[REDACTED]", value)
    return value[:2000]


def invoke_agent(target: AgentTarget, question: str, attempt_id: str, context: dict | None = None, *, diagnostics: dict | None = None) -> dict:
    if is_demo():
        from .demo_simulation import generated_answer
        return generated_answer(target,question)
    if not target.url:
        raise ValueError("Agent connection is not configured")
    headers = {"Idempotency-Key": attempt_id, "Cache-Control": "no-cache"}
    if diagnostics is not None:
        diagnostics.update(authMode=target.auth, runtimeIdentity={"label": "No authentication (no credentials sent)" if target.auth == 'none' else "Cloud Run runtime credentials" if os.getenv("K_SERVICE") else "Local backend credentials", "principal": None})
    if target.auth == "bearer_env":
        token = os.getenv(target.token_env, "")
        if not token:
            raise AgentInvocationError("authentication")
        headers["Authorization"] = f"Bearer {token}"
    elif target.auth == "google_id_token":
        try:
            headers["Authorization"] = "Bearer " + id_token.fetch_id_token(Request(), target.audience or target.url)
        except Exception as exc:
            raise AgentInvocationError("authentication") from exc
    elif target.auth == "google_access_token":
        try:
            scopes = ["https://www.googleapis.com/auth/cloud-platform", "https://www.googleapis.com/auth/userinfo.email"]
            source_credentials, _ = google.auth.default(scopes=scopes)
            impersonated_principal = settings.neo_companion_prod_service_account if (
                target.id == "neo-prod" and target.environment == "prod" and target.protocol == "neo_companion") else ""
            credentials = impersonated_credentials.Credentials(
                source_credentials=source_credentials,
                target_principal=impersonated_principal,
                target_scopes=scopes,
                lifetime=600,
            ) if impersonated_principal else source_credentials
            credentials.refresh(Request())
            if not credentials.token:
                raise RuntimeError("No Google access token returned")
            headers["Authorization"] = f"Bearer {credentials.token}"
            if diagnostics is not None:
                principal = impersonated_principal or getattr(credentials, "service_account_email", None) or getattr(credentials, "account", None)
                if impersonated_principal:
                    diagnostics["runtimeIdentity"]["label"] = "Cloud Run impersonated target service account" if os.getenv("K_SERVICE") else "Local impersonated target service account"
                diagnostics["runtimeIdentity"].update(credentialType=type(credentials).__module__ + "." + type(credentials).__name__,
                    principal=principal if isinstance(principal, str) and "@" in principal else None,
                    impersonated=bool(impersonated_principal))
        except Exception as exc:
            raise AgentInvocationError("authentication") from exc
    if target.protocol not in {"quality_json", "neo_companion"}:
        raise ValueError("Unsupported agent target protocol")
    # Companion creates the conversation. Never reuse a report's old session or
    # invent a conversation ID that the provider has not issued.
    payload = {"message": question} if target.protocol == "neo_companion" else {
        "question": question, "conversation_id": f"feedback-retest-{attempt_id}",
        "context": context or {}, "environment": target.environment,
    }
    started = time.monotonic()
    response = None
    try:
        with httpx.Client(timeout=httpx.Timeout(target.timeout_seconds, connect=15), follow_redirects=False) as client:
            if diagnostics is not None:
                diagnostics["requestStarted"] = True
            response = client.post(target.url, headers=headers, json=payload)
            if diagnostics is not None:
                diagnostics["httpStatus"] = response.status_code
            response.raise_for_status()
            result = response.json()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        code = {401: "authentication", 403: "permission", 408: "timeout", 429: "rate_limit", 504: "timeout"}.get(status)
        if code is None:
            code = "unavailable" if status >= 500 else "redirect" if 300 <= status < 400 else "request"
        raise AgentInvocationError(code, http_status=status) from exc
    except httpx.TimeoutException as exc:
        # The upstream may already have generated an answer. Do not silently
        # replay a generation POST without a verified idempotency guarantee.
        raise AgentInvocationError("timeout") from exc
    except httpx.RequestError as exc:
        raise AgentInvocationError("network") from exc
    except ValueError as exc:
        raise AgentInvocationError("response", http_status=getattr(response, "status_code", None)) from exc
    if not isinstance(result, dict):
        raise AgentInvocationError("response", http_status=response.status_code)
    try:
        if target.protocol == "neo_companion":
            answer = parse_companion_response(result)
            answer["agentVersion"] = answer.get("agentVersion") or target.version
        else:
            answer = {"answer": validate_answer(result.get("answer")), "runId": result.get("run_id"),
                      "conversationId": result.get("conversation_id"), "agentVersion": result.get("agent_version") or target.version,
                      "modelVersion": result.get("model_version"), "corpusVersion": result.get("corpus_version"),
                      "sources": result.get("sources") if isinstance(result.get("sources"), list) else []}
    except AgentInvocationError as error:
        error.http_status = response.status_code
        raise
    if diagnostics is not None:
        diagnostics["answerPreview"] = diagnostic_preview(answer["answer"], headers)
    return {**answer, "latencyMs": round((time.monotonic() - started) * 1000), "protocol": target.protocol}
