from datetime import datetime, timedelta, timezone
import json
from unittest.mock import Mock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from google.api_core.exceptions import Aborted, BadRequest, Forbidden
import pytest

from app.access_repository import AccessGrantRepository, access_repository, normalize_principal
from app.access_routes import AccessGrantCreate, AccessGrantUpdate
from app.config import settings
from app.main import app
from scripts.init_access_grants import CONTROL_SCHEMA, EVENT_SCHEMA, initialize_management
from test_google_iam_auth import iam


ACTOR = 'reviewer@company.example'
EMAIL = 'person@company.example'
NOW = datetime(2026, 10, 27, tzinfo=timezone.utc)
ROW = {'email': EMAIL, 'display_name': 'Person', 'role': 'reporter', 'active': True,
    'expires_at': None, 'created_at': NOW, 'updated_at': NOW, 'updated_by': ACTOR}


@pytest.fixture
def manager(iam):
    fake = Mock()
    app.dependency_overrides[access_repository] = lambda: fake
    client = TestClient(app)
    yield client, {'Authorization': 'Bearer ' + iam()}, fake, iam
    app.dependency_overrides.pop(access_repository, None)


def test_real_reviewers_can_list_create_update_and_inspect_access_history(manager):
    client, headers, fake, _ = manager
    fake.list_grants.return_value = {'items': [], 'total': 0}
    fake.save_grant.return_value = {'email': EMAIL, 'role': 'reporter'}
    fake.grant_history.return_value = []
    assert client.get('/api/access-grants?search=person&page=2', headers=headers).status_code == 200
    fake.list_grants.assert_called_once_with(ACTOR, search='person', page=2, page_size=25)
    assert client.post('/api/access-grants', headers=headers, json={'email': EMAIL}).status_code == 201
    saved = fake.save_grant.call_args
    assert saved.args[0] == EMAIL and saved.args[1].role == 'reporter' and saved.args[2] == ACTOR
    assert saved.kwargs == {'create': True}
    assert client.patch('/api/access-grants/' + EMAIL, headers=headers,
        json={'role': 'reviewer', 'expected_updated_at': NOW.isoformat()}).status_code == 200
    assert fake.save_grant.call_args.kwargs == {'create': False}
    assert client.get('/api/access-grants/' + EMAIL + '/history', headers=headers).status_code == 200
    fake.grant_history.assert_called_once_with(EMAIL, ACTOR)


@pytest.mark.parametrize('method,path,payload', [
    ('get', '/api/access-grants', None), ('post', '/api/access-grants', {'email': EMAIL}),
    ('patch', '/api/access-grants/' + EMAIL, {'expected_updated_at': NOW.isoformat()}),
    ('get', '/api/access-grants/' + EMAIL + '/history', None),
])
def test_reporters_cannot_list_or_change_anyones_access(manager, method, path, payload):
    client, headers, fake, token = manager
    token.grants[ACTOR]['role'] = 'reporter'
    response = client.request(method, path, headers=headers, json=payload)
    assert response.status_code == 403
    assert fake.mock_calls == []


def test_demo_reviewers_cannot_administer_real_company_access(manager):
    from app.auth import issue_mock_token
    client, _, fake, _ = manager
    with patch.dict(settings.__dict__, {'auth_mode': 'mock'}):
        token, _, _ = issue_mock_token('quality.reviewer@example.test')
        response = client.get('/api/access-grants', headers={'Authorization': 'Bearer ' + token})
    assert response.status_code == 403 and 'real Google' in response.json()['detail']
    fake.list_grants.assert_not_called()


@pytest.mark.parametrize('changes', [
    {'email': 'outside@outside.example'}, {'role': 'admin'}, {'active': 'true'},
    {'feedbackOwnerEmail': ACTOR}, {'updated_by': 'forged@company.example'}, {'actor': 'forged@company.example'},
    {'expires_at': '2026-11-01T10:00:00'}, {'email': 'bad address@company.example'},
])
def test_browser_cannot_create_aliases_forge_auditors_or_send_invalid_grants(manager, changes):
    client, headers, fake, _ = manager
    response = client.post('/api/access-grants', headers=headers, json={'email': EMAIL, **changes})
    assert response.status_code == 422
    fake.save_grant.assert_not_called()


def test_updates_require_an_exact_version_and_cannot_change_the_principal(manager):
    client, headers, fake, _ = manager
    for payload in [{}, {'expected_updated_at': NOW.isoformat(), 'email': 'other@company.example'}]:
        assert client.patch('/api/access-grants/' + EMAIL, headers=headers, json=payload).status_code == 422
    fake.save_grant.assert_not_called()


def test_repository_lists_only_bounded_parameterized_company_grants_and_refreshes_manager_role(monkeypatch):
    monkeypatch.setitem(settings.__dict__, 'google_iam_domains', ('company.example',))
    db = Mock(); db.query.return_value.result.return_value = [{**ROW, 'principal_count': 1, 'total': 1}]
    repo = AccessGrantRepository(db, utcnow=lambda: NOW)
    repo.grant = Mock(return_value={'role': 'reviewer'})
    result = repo.list_grants(ACTOR, search="person' OR TRUE --", page=2, page_size=10)
    repo.grant.assert_called_once_with(ACTOR, refresh=True)
    sql = db.query.call_args.args[0]
    params = {value.name: value.value for value in db.query.call_args.kwargs['job_config'].query_parameters}
    assert "person'" not in sql and params['search'] == "person' or true --" and params['offset'] == 10
    assert result['items'][0]['status'] == 'active' and result['items'][0]['canEdit']
    assert result['propagationSeconds'] == 30


def test_revoked_manager_cannot_read_access_directory_even_with_cached_api_role():
    repo = AccessGrantRepository(Mock()); repo.grant = Mock(return_value=None)
    with pytest.raises(HTTPException) as error: repo.list_grants(ACTOR)
    assert error.value.status_code == 403
    repo._client.query.assert_not_called()


@pytest.mark.parametrize('row', [{**ROW, 'role': 'admin', 'principal_count': 1},
    {**ROW, 'principal_count': 2}, {**ROW, 'updated_at': None, 'principal_count': 1}])
def test_malformed_or_duplicate_access_rows_are_never_silently_editable(row, monkeypatch):
    monkeypatch.setitem(settings.__dict__, 'google_iam_domains', ('company.example',))
    db = Mock(); db.query.return_value.result.return_value = [{**row, 'total': 1}]
    repo = AccessGrantRepository(db); repo.grant = Mock(return_value={'role': 'reviewer'})
    with pytest.raises(HTTPException) as error: repo.list_grants(ACTOR)
    assert error.value.status_code == 503


def test_write_is_one_atomic_serialized_audited_transaction_with_live_actor_and_exact_version(monkeypatch):
    monkeypatch.setitem(settings.__dict__, 'google_iam_domains', ('company.example',))
    db = Mock(); db.query.return_value.result.return_value = [{'grant_json': json.dumps({**ROW,
        'created_at': NOW.isoformat(), 'updated_at': NOW.isoformat()})}]
    repo = AccessGrantRepository(db, utcnow=lambda: NOW)
    payload = AccessGrantUpdate(role='reporter', expected_updated_at=NOW)
    assert repo.save_grant(EMAIL, payload, ACTOR, create=False)['email'] == EMAIL
    db.query.assert_called_once()
    sql = db.query.call_args.args[0]
    assert 'BEGIN TRANSACTION' in sql and 'COMMIT TRANSACTION' in sql
    assert 'application_access_control` SET revision=revision+1' in sql
    assert 'ACCESS_REVIEWER_REQUIRED' in sql and 'ACCESS_DUPLICATE_GRANTS' in sql and 'ACCESS_STALE' in sql
    assert 'INSERT INTO' in sql and 'application_access_events' in sql
    assert EMAIL not in sql and ACTOR not in sql
    assert db.query.call_args.kwargs['job_retry'] is None
    assert db.query.call_args.kwargs['job_id'].startswith('access_grant_')
    db.query.return_value.result.assert_called_once_with(job_retry=None)
    assert 'feedback_items' not in sql and 'feedback_events' not in sql


@pytest.mark.parametrize('error,status', [
    (Aborted('private details'), 409), (BadRequest('Transaction is aborted due to concurrent update against table secret'), 409),
    (BadRequest('ACCESS_STALE private details'), 409), (BadRequest('ACCESS_ALREADY_EXISTS'), 409),
    (BadRequest('ACCESS_REVIEWER_REQUIRED'), 403), (Forbidden('private details'), 503),
])
def test_conflicting_or_revoked_admin_writes_fail_safely_without_automatic_replay(error, status, monkeypatch):
    monkeypatch.setitem(settings.__dict__, 'google_iam_domains', ('company.example',))
    db = Mock(); db.query.side_effect = error
    repo = AccessGrantRepository(db)
    with pytest.raises(HTTPException) as caught:
        repo.save_grant(EMAIL, AccessGrantCreate(email=EMAIL), ACTOR, create=True)
    assert caught.value.status_code == status and 'private details' not in caught.value.detail
    db.query.assert_called_once()


def test_reviewers_cannot_revoke_or_rewrite_their_own_grant(monkeypatch):
    monkeypatch.setitem(settings.__dict__, 'google_iam_domains', ('company.example',))
    db = Mock(); repo = AccessGrantRepository(db)
    with pytest.raises(HTTPException) as error:
        repo.save_grant(ACTOR, AccessGrantUpdate(active=False, expected_updated_at=NOW), ACTOR, create=False)
    assert error.value.status_code == 409
    db.query.assert_not_called()


def test_installation_adds_only_audit_and_guard_storage_without_editing_grants():
    db = Mock()
    db.get_table.side_effect = [Mock(schema=EVENT_SCHEMA), Mock(schema=CONTROL_SCHEMA)]
    db.query.return_value.result.return_value = [{'n': 1}]
    initialize_management(db)
    tables = [call.args[0].table_id for call in db.create_table.call_args_list]
    assert tables == ['application_access_events', 'application_access_control']
    assert all('application_access_grants' not in call.args[0] for call in db.query.call_args_list)
    assert not any('WHEN MATCHED' in call.args[0] for call in db.query.call_args_list)
