import json
import time
from types import SimpleNamespace

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from google.auth import crypt, jwt
import pytest

from app import auth
from app.config import settings
from app.main import app
from test_google_iam_auth import iam


AUDIENCE = '/projects/411502743425/locations/europe-west1/services/neo-feedback-ui'


@pytest.fixture
def iap(iam, monkeypatch):
    key = ec.generate_private_key(ec.SECP256R1())
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    signer = crypt.ES256Signer.from_string(private)
    monkeypatch.setattr(auth, '_GOOGLE_CERT_REQUEST', lambda *_args, **_kwargs: SimpleNamespace(status=200, data=json.dumps({'iap-test-key': public}).encode()))
    monkeypatch.setitem(settings.__dict__, 'google_iap_audience', AUDIENCE)

    def token(**changes):
        now = int(time.time())
        return jwt.encode(signer, {'iss': 'https://cloud.google.com/iap', 'aud': AUDIENCE,
            'sub': 'accounts.google.com:verified-subject', 'email': 'reviewer@company.example',
            'iat': now, 'exp': now + 600, **changes}, key_id='iap-test-key').decode()
    token.grants = iam.grants
    return token


def test_signed_iap_identity_uses_bigquery_role_not_plain_email_or_role_headers(iap):
    response = TestClient(app).get('/api/auth/me', headers={'X-Feedback-IAP-Assertion': iap(role='reporter'),
        'X-Goog-Authenticated-User-Email': 'accounts.google.com:someone-else@company.example', 'X-Feedback-Role': 'reporter'})
    assert response.status_code == 200
    assert response.json()['email'] == 'reviewer@company.example' and response.json()['role'] == 'reviewer'
    assert 'feedbackOwnerEmail' not in response.json()


@pytest.mark.parametrize('changes', [{'aud': '/projects/other/locations/elsewhere/services/attacker'},
    {'iss': 'https://attacker.example'}, {'email': 'person@outside.example'}, {'sub': 'service-account:runtime'},
    {'exp': 1}, {'iat': 4102444800, 'exp': 4102445400}])
def test_invalid_iap_assertions_fail_closed(iap, changes):
    response = TestClient(app).get('/api/auth/me', headers={'X-Feedback-IAP-Assertion': iap(**changes)})
    assert response.status_code == 401


def test_bad_signature_or_stripped_iap_token_never_falls_back_to_browser_identity_headers(iap):
    token = iap(); prefix, payload, signature = token.split('.')
    tampered = prefix + '.' + payload + '.' + ('A' if signature[0] != 'A' else 'B') + signature[1:]
    for value in [tampered, prefix + '.' + payload + '.', 'unsigned', '']:
        assert TestClient(app).get('/api/auth/me', headers={'X-Feedback-IAP-Assertion': value,
            'X-Goog-Authenticated-User-Email': 'accounts.google.com:reviewer@company.example'}).status_code == 401


def test_iap_identity_without_application_grant_is_denied(iap):
    iap.grants.clear()
    response = TestClient(app).get('/api/auth/me', headers={'X-Feedback-IAP-Assertion': iap()})
    assert response.status_code == 403


def test_iap_is_not_implicitly_enabled_without_an_exact_resource_audience(iap, monkeypatch):
    monkeypatch.setitem(settings.__dict__, 'google_iap_audience', '')
    response = TestClient(app).get('/api/auth/me', headers={'X-Feedback-IAP-Assertion': iap()})
    assert response.status_code == 401
