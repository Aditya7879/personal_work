import json
import os
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from fastapi import HTTPException
from google.auth import crypt, jwt

from app import auth, root_cause
from app.config import settings
from app.main import app, repository


@pytest.fixture
def iam(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    signer = crypt.RSASigner.from_string(private)
    monkeypatch.setattr(auth, "_GOOGLE_CERT_REQUEST", lambda *_args, **_kwargs: SimpleNamespace(status=200, data=json.dumps({"test-key": public}).encode()))
    monkeypatch.setitem(settings.__dict__, "auth_mode", "google_iam")
    monkeypatch.setitem(settings.__dict__, "google_iam_audiences_json", '["test-cloud-sdk-client"]')
    monkeypatch.setitem(settings.__dict__, "google_iam_domains", ("company.example",))
    grants = {'reviewer@company.example': {'displayName': 'Granted reviewer', 'role': 'reviewer'}}
    lookup = Mock(side_effect=lambda email: grants.get(email))
    monkeypatch.setattr(auth, 'get_access_grant', lookup)

    def token(**changes):
        now = int(time.time())
        claims = {"iss": "https://accounts.google.com", "aud": "test-cloud-sdk-client", "sub": "verified-subject",
                  "email": "reviewer@company.example", "email_verified": True, "iat": now, "exp": now + 3600, **changes}
        return jwt.encode(signer, claims, key_id="test-key").decode()
    token.grants = grants
    token.lookup = lookup
    return token


def test_real_signature_verified_identity_uses_only_its_explicit_grant(iam):
    response = TestClient(app).get("/api/auth/me", headers={"Authorization": "Bearer " + iam(role="reporter")})
    assert response.status_code == 200
    assert response.json()["email"] == "reviewer@company.example" and response.json()["role"] == "reviewer"
    assert "cacheScope" in response.json() and "feedbackOwnerEmail" not in response.json()


@pytest.mark.parametrize("changes", [
    {"aud": "unapproved-client"}, {"iss": "https://attacker.example"}, {"email_verified": False},
    {"email": "reviewer@outside.example"}, {"email": "runtime@project.iam.gserviceaccount.com"},
    {"exp": 1}, {"iat": 4102444800, "exp": 4102448400},
])
def test_invalid_google_identity_claims_fail_closed(iam, changes):
    response = TestClient(app).get("/api/auth/me", headers={"Authorization": "Bearer " + iam(**changes)})
    assert response.status_code == 401 and "identity token" in response.json()["detail"]


def test_missing_bigquery_grant_never_falls_back_to_environment_roles(iam):
    token = iam()
    iam.grants.clear()
    with patch.dict(settings.__dict__, {'google_iam_users_json': '[{"email":"reviewer@company.example","role":"reviewer"}]'}):
        response = TestClient(app).get("/api/auth/me", headers={"Authorization": "Bearer " + token})
    assert response.status_code == 403 and "no active" in response.json()["detail"]


def test_browser_identity_headers_and_google_role_claims_cannot_elevate_a_reporter(iam):
    fake = Mock()
    fake.list_feedback.return_value = ([], 0)
    app.dependency_overrides[repository] = lambda: fake
    try:
        with patch.dict(iam.grants, {'reviewer@company.example': {'role': 'reporter', 'displayName': 'Reporter'}}):
            response = TestClient(app).get("/api/feedback", headers={"Authorization": "Bearer " + iam(role="reviewer"),
                "X-Goog-Authenticated-User-Email": "accounts.google.com:admin@company.example", "X-Feedback-Role": "reviewer"})
        assert response.status_code == 403
        fake.list_feedback.assert_not_called()
    finally:
        app.dependency_overrides.pop(repository, None)


def test_full_user_credential_survives_a_stripped_workload_header_and_is_verified(iam):
    headers = {"Authorization": "Bearer stripped.jwt.", "X-Serverless-Authorization": "Bearer workload.jwt.",
               "X-Feedback-User-Authorization": "Bearer " + iam()}
    assert TestClient(app).get("/api/auth/me", headers=headers).status_code == 200
    for bad in ("Bearer arbitrary@example.test", "Bearer unsigned.jwt.", "Bearer a.b.c"):
        assert TestClient(app).get("/api/auth/me", headers={**headers, "X-Feedback-User-Authorization": bad}).status_code == 401


def test_tampered_signature_is_not_trusted_even_when_claims_name_a_granted_user(iam):
    token = iam()
    encoded, claims, signature = token.split(".")
    modified = encoded + "." + claims + "." + ("A" if signature[0] != "A" else "B") + signature[1:]
    assert TestClient(app).get("/api/auth/me", headers={"Authorization": "Bearer " + modified}).status_code == 401


@pytest.mark.parametrize("grants", ['{}', 'not-json', '[{"email":"reviewer@company.example","role":"admin"}]',
    '[{"email":"reviewer@company.example","role":"reviewer","feedbackOwnerEmail":"another@company.example"}]'])
def test_legacy_environment_grants_cannot_override_bigquery_roles_or_owner_identity(iam, grants):
    with patch.dict(settings.__dict__, {"google_iam_users_json": grants}):
        response = TestClient(app).get("/api/auth/me", headers={"Authorization": "Bearer " + iam()})
    assert response.status_code == 200 and response.json()['role'] == 'reviewer'
    assert 'feedbackOwnerEmail' not in response.json()


def test_authorization_outage_is_not_treated_as_an_authentication_or_default_role_success(iam):
    iam.lookup.side_effect = HTTPException(503, 'Application authorization is temporarily unavailable')
    response = TestClient(app).get('/api/auth/me', headers={'Authorization': 'Bearer ' + iam()})
    assert response.status_code == 503


def test_role_changes_are_checked_before_api_read_caches(iam):
    fake = Mock(); fake.list_feedback.return_value = ([], 0)
    app.dependency_overrides[repository] = lambda: fake
    try:
        client = TestClient(app); headers = {'Authorization': 'Bearer ' + iam()}
        before = client.get('/api/auth/me', headers=headers).json()
        assert client.get('/api/feedback', headers=headers).status_code == 200
        iam.grants['reviewer@company.example']['role'] = 'reporter'
        after = client.get('/api/auth/me', headers=headers).json()
        assert before['cacheScope'] != after['cacheScope'] and after['role'] == 'reporter'
        assert client.get('/api/feedback', headers=headers).status_code == 403
    finally:
        app.dependency_overrides.pop(repository, None)


def test_company_identity_alone_cannot_use_development_mock_login(iam):
    client = TestClient(app)
    assert client.get("/api/auth/mock-users").status_code == 404
    assert client.post("/api/auth/mock-login", json={"email": "quality.reviewer@example.test"}).status_code == 404


def test_mock_auth_still_refuses_cloud_run():
    result = subprocess.run([sys.executable, "-c", "import app.auth"], capture_output=True, text=True,
        env={**os.environ, "K_SERVICE": "neo-feedback-api", "FEEDBACK_APP_ENV": "sandbox", "FEEDBACK_AUTH_MODE": "mock"})
    assert result.returncode != 0 and "development-only" in result.stderr


def test_cloud_rca_uses_runtime_adc_and_never_a_developer_cli_token():
    credentials = SimpleNamespace(token="runtime-service-token", refresh=Mock())
    with patch.dict(os.environ, {"K_SERVICE": "neo-feedback-api"}), patch.dict(settings.__dict__, {"btap_access_token": ""}), patch.object(root_cause, "_GATEWAY_TOKEN", (0, "")), patch("app.root_cause.google.auth.default", return_value=(credentials, "sandbox")) as adc, patch("app.root_cause.subprocess.run") as cli:
        assert root_cause._gateway_token() == "runtime-service-token"
        adc.assert_called_once_with(scopes=["https://www.googleapis.com/auth/cloud-platform", "https://www.googleapis.com/auth/userinfo.email"])
        credentials.refresh.assert_called_once()
        cli.assert_not_called()


def test_cloud_rca_adc_failure_does_not_switch_principals_or_expose_secrets():
    with patch.dict(os.environ, {"K_SERVICE": "neo-feedback-api"}), patch.dict(settings.__dict__, {"btap_access_token": ""}), patch.object(root_cause, "_GATEWAY_TOKEN", (0, "")), patch("app.root_cause.google.auth.default", side_effect=RuntimeError("raw private details")), patch("app.root_cause.subprocess.run") as cli:
        with pytest.raises(RuntimeError, match="service identity") as caught:
            root_cause._gateway_token()
        assert "raw private" not in str(caught.value)
        cli.assert_not_called()
