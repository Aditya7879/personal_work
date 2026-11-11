from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from threading import Lock
from typing import Any, Literal

import requests
from cachecontrol import CacheControl
from fastapi import HTTPException, Request
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token

from .config import settings
from .access_repository import get_access_grant

UserRole = Literal["reporter", "reviewer"]

if settings.auth_mode == "mock" and (
    settings.app_env not in {"development", "dev", "local", "test"}
    or bool(os.getenv("K_SERVICE"))
):
    raise RuntimeError("Mock feedback authentication is development-only; configure company SSO before deployment.")

if settings.auth_mode == "private_demo" and settings.app_env not in {"sandbox", "development", "dev", "local", "test"}:
    raise RuntimeError("Presenter role previews are sandbox-only")

if settings.auth_mode == 'demo_admin':
    raise RuntimeError('Standalone demo password login is retired; use the Demo Admin role in the IAP app')

_TOKEN_SECRET = (settings.auth_secret or secrets.token_urlsafe(48)).encode("utf-8")
_GOOGLE_VERIFY_LOCK = Lock()
_GOOGLE_CERT_REQUEST = GoogleRequest(session=CacheControl(requests.Session()))

_DEFAULT_MOCK_USERS: list[dict[str, str]] = [
    {"email": "alex.requester@example.test", "displayName": "Alex Requester", "role": "reporter"},
    {"email": "sam.requester@example.test", "displayName": "Sam Requester", "role": "reporter"},
    {"email": "quality.reviewer@example.test", "displayName": "Quality Reviewer", "role": "reviewer"},
]


@dataclass(frozen=True)
class AuthenticatedUser:
    email: str
    display_name: str
    role: UserRole
    feedback_owner_email: str | None = None
    presenter_email: str | None = None
    demo_session_scope: str | None = None
    access_role: str | None = None

    @property
    def audit_email(self) -> str:
        return self.presenter_email or self.email

    @property
    def feedback_emails(self) -> list[str]:
        return list(dict.fromkeys([self.email, self.feedback_owner_email or self.email]))

    def public_dict(self) -> dict[str, Any]:
        values = [self.email, self.role, sorted(self.feedback_emails), self.presenter_email]
        if self.demo_session_scope:values.append(self.demo_session_scope)
        if self.access_role:values.append(self.access_role)
        scope = json.dumps(values, separators=(",", ":"))
        scope_id = hmac.new(_TOKEN_SECRET, scope.encode(), hashlib.sha256).hexdigest()[:24]
        result = {"email": self.email, "displayName": self.display_name, "role": self.role, "cacheScope": scope_id}
        if self.presenter_email:
            result["demoMode"] = 'demo_admin' if self.demo_session_scope else 'private_demo'
        if self.access_role=='demo_admin':
            result.update(accessRole='demo_admin',canSwitchDemoViews=bool(settings.role_demo_enabled and settings.auth_mode=='google_iam'))
        return result


def _mock_user_records() -> list[dict[str, str]]:
    configured = {user["email"]: dict(user) for user in _DEFAULT_MOCK_USERS}
    if settings.mock_users_json.strip():
        try:
            rows = json.loads(settings.mock_users_json)
        except json.JSONDecodeError as exc:
            raise RuntimeError("FEEDBACK_MOCK_USERS_JSON must contain a JSON array") from exc
        if not isinstance(rows, list):
            raise RuntimeError("FEEDBACK_MOCK_USERS_JSON must contain a JSON array")
    else:
        rows = []
    users: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        email = str(row.get("email") or "").strip().lower()
        display_name = str(row.get("displayName") or row.get("display_name") or email).strip()
        role = str(row.get("role") or "reporter").strip().lower()
        if email and display_name and role in {"reporter", "reviewer"}:
            configured[email] = {
                "email": email,
                "displayName": display_name,
                "role": role,
                "feedbackOwnerEmail": str(row.get("feedbackOwnerEmail") or row.get("feedback_owner_email") or email).strip().lower(),
            }
    return list(configured.values())


def list_mock_users(presenter: AuthenticatedUser | None = None) -> list[dict[str, str]]:
    if settings.auth_mode == "private_demo":
        _require_presenter(presenter)
    elif settings.auth_mode != "mock":
        raise HTTPException(status_code=404, detail="Mock sign-in is disabled")
    return [
        {key: user[key] for key in ("email", "displayName", "role")}
        for user in _mock_user_records()
    ]


def _user_for_email(email: str) -> AuthenticatedUser | None:
    normalized = email.strip().lower()
    for user in _mock_user_records():
        if user["email"] == normalized:
            return AuthenticatedUser(
                email=user["email"],
                display_name=user["displayName"],
                role=user["role"],  # type: ignore[arg-type]
                feedback_owner_email=user.get("feedbackOwnerEmail") or user["email"],
            )
    return None


def _encode_segment(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode_segment(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def issue_mock_token(email: str, presenter: AuthenticatedUser | None = None) -> tuple[str, AuthenticatedUser, int]:
    if settings.auth_mode == "private_demo":
        _require_presenter(presenter)
    elif settings.auth_mode != "mock":
        raise HTTPException(status_code=404, detail="Mock sign-in is disabled")
    user = _user_for_email(email)
    if not user:
        raise HTTPException(status_code=401, detail="Choose a configured development test identity")
    expires_in = max(300, settings.auth_token_ttl_seconds)
    payload = {
        "sub": user.email,
        "name": user.display_name,
        "role": user.role,
        "exp": int(time.time()) + expires_in,
    }
    if presenter:
        payload.update(aud="private-demo", actor=_presenter_binding(presenter.email))
        user = AuthenticatedUser(user.email, user.display_name, user.role, user.feedback_owner_email, presenter.email)
    encoded = _encode_segment(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = _encode_segment(hmac.new(_TOKEN_SECRET, encoded.encode("ascii"), hashlib.sha256).digest())
    return f"{encoded}.{signature}", user, expires_in


def decode_access_token(token: str, presenter: AuthenticatedUser | None = None) -> AuthenticatedUser:
    try:
        encoded, signature = token.split(".", 1)
        expected = hmac.new(_TOKEN_SECRET, encoded.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _decode_segment(signature)):
            raise ValueError("Invalid token signature")
        payload: dict[str, Any] = json.loads(_decode_segment(encoded))
        if int(payload.get("exp", 0)) <= int(time.time()):
            raise ValueError("Token expired")
        user = _user_for_email(str(payload.get("sub") or ""))
        if not user or payload.get("role") != user.role:
            raise ValueError("Unknown or changed identity")
        if presenter:
            if payload.get("aud") != "private-demo" or not hmac.compare_digest(str(payload.get("actor") or ""), _presenter_binding(presenter.email)):
                raise ValueError("The demo session belongs to another presenter")
            return AuthenticatedUser(user.email, user.display_name, user.role, user.feedback_owner_email, presenter.email)
        if payload.get("aud") == "private-demo":
            raise ValueError("A verified presenter is required")
        return user
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired sign-in token") from exc


def decode_google_iam_token(token: str) -> AuthenticatedUser:
    """Verify the complete end-user JWT, independently of Cloud Run's workload IAM.

    The frontend uses X-Serverless-Authorization for its own backend invocation
    and preserves this separate Authorization token. Never trust stripped JWTs,
    plain identity headers, service-account names, or browser-supplied roles.
    """
    try:
        audiences = json.loads(settings.google_iam_audiences_json)
        if not isinstance(audiences, list) or not audiences or any(not isinstance(value, str) or not value for value in audiences):
            raise ValueError("Missing permitted audiences")
    except (ValueError, TypeError):
        raise HTTPException(status_code=503, detail="Private Google IAM sign-in is not configured") from None
    try:
        if len(token) > 16384 or len(token.split(".")) != 3 or not token.split(".")[-1]:
            raise ValueError("A complete signed identity token is required")
        with _GOOGLE_VERIFY_LOCK:
            claims = id_token.verify_oauth2_token(token, _GOOGLE_CERT_REQUEST, audience=None, clock_skew_in_seconds=30)
        if claims.get("aud") not in audiences or claims.get("email_verified") is not True:
            raise ValueError("Wrong audience or unverified email")
        email = str(claims.get("email") or "").strip().lower()
        if "@" not in email or email.rsplit("@", 1)[1] not in settings.google_iam_domains:
            raise ValueError("A permitted company identity is required")
    except Exception:
        raise HTTPException(status_code=401, detail="A valid, signed company Google identity token is required") from None
    return _google_user(email, claims)


def _google_user(email: str, claims: dict) -> AuthenticatedUser:
    grant = get_access_grant(email)
    if not grant:
        raise HTTPException(status_code=403, detail="Your identity has no active application access grant")
    display_name = grant.get("displayName") or str(claims.get("name") or email)[:200]
    stored=grant['role']
    return AuthenticatedUser(email=email,display_name=display_name,role='reviewer'if stored=='demo_admin'else stored,
        access_role='demo_admin'if stored=='demo_admin'else None)  # type: ignore[arg-type]


def decode_google_iap_token(token: str) -> AuthenticatedUser:
    """Verify Google's signed IAP assertion, not plain proxy identity headers."""
    audience = settings.google_iap_audience
    if not audience:
        raise HTTPException(401, 'Browser IAP authentication is not configured')
    try:
        if len(token) > 16384 or len(token.split('.')) != 3 or not token.split('.')[-1]:
            raise ValueError('A complete signed IAP assertion is required')
        with _GOOGLE_VERIFY_LOCK:
            claims = id_token.verify_token(token, _GOOGLE_CERT_REQUEST, audience=audience,
                certs_url='https://www.gstatic.com/iap/verify/public_key', clock_skew_in_seconds=30)
        email = str(claims.get('email') or '').strip().lower()
        if (claims.get('iss') != 'https://cloud.google.com/iap'
                or not str(claims.get('sub') or '').startswith('accounts.google.com:')
                or '@' not in email or email.rsplit('@', 1)[1] not in settings.google_iam_domains):
            raise ValueError('A permitted Google user identity is required')
    except Exception:
        raise HTTPException(401, 'A valid signed company IAP identity is required') from None
    return _google_user(email, claims)


def _presenter_binding(email: str) -> str:
    return hmac.new(_TOKEN_SECRET, ("private-demo:" + email.strip().lower()).encode(), hashlib.sha256).hexdigest()


def _require_presenter(presenter: AuthenticatedUser | None) -> None:
    if (settings.app_env not in {"sandbox", "development", "dev", "local", "test"}
            or not presenter or presenter.role != "reviewer" or presenter.email not in settings.private_demo_presenters):
        raise HTTPException(status_code=403, detail="Private demo access requires an explicitly authorized presenter")


def private_demo_presenter(request: Request) -> AuthenticatedUser:
    authorization = request.headers.get("X-Feedback-User-Authorization") or request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="An authenticated private presenter connection is required")
    presenter = decode_google_iam_token(token)
    _require_presenter(presenter)
    return presenter


def get_request_user(request: Request) -> AuthenticatedUser:
    if settings.auth_mode == "private_demo":
        presenter = private_demo_presenter(request)
        scheme, _, token = request.headers.get("X-Feedback-Demo-Authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(status_code=401, detail="Choose a reviewer or reporter demo account")
        return decode_access_token(token, presenter)
    authorization = request.headers.get("Authorization", "")
    if settings.auth_mode == "google_iam":
        if request.headers.get('X-Feedback-IAP-Assertion') is not None:
            return decode_google_iap_token(request.headers['X-Feedback-IAP-Assertion'])
        # A complete duplicate survives Cloud Run's IAM-header signature removal.
        # It is a credential, not a trusted identity claim: verify its signature.
        authorization = request.headers.get("X-Feedback-User-Authorization") or authorization
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Sign in to continue")
    if settings.auth_mode == "google_iam":
        return decode_google_iam_token(token)
    if settings.auth_mode == "mock":
        return decode_access_token(token)
    raise HTTPException(status_code=503, detail="The configured identity provider is unavailable")
