from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from fastapi import HTTPException
from google.api_core.exceptions import Forbidden, NotFound
import pytest

from app.access_repository import AccessGrantRepository, access_table_ref
from app.config import settings


EMAIL = 'reviewer@company.example'
NOW = datetime(2026, 10, 27, tzinfo=timezone.utc)
GRANT = {'email': EMAIL, 'display_name': 'Reviewer', 'role': 'reviewer', 'active': True, 'expires_at': None}


def repo_with(rows):
    client = Mock(); client.query.return_value.result.return_value = rows
    return AccessGrantRepository(client, utcnow=lambda: NOW), client


def test_lookup_uses_parameterized_verified_identity_and_only_returns_role_and_display_name():
    repo, client = repo_with([{**GRANT, 'feedback_owner_email': 'someone-else@company.example'}])
    assert repo.grant('  REVIEWER@company.example ') == {'role': 'reviewer', 'displayName': 'Reviewer'}
    sql = client.query.call_args.args[0]
    assert '@email' in sql and EMAIL not in sql and 'LIMIT 2' in sql
    assert client.query.call_args.kwargs['job_config'].query_parameters[0].value == EMAIL
    client.create_table.assert_not_called()


@pytest.mark.parametrize('rows', [[], [{**GRANT, 'active': False}], [{**GRANT, 'expires_at': NOW - timedelta(seconds=1)}]])
def test_missing_disabled_or_expired_grants_never_get_an_implicit_role(rows):
    repo, _ = repo_with(rows)
    assert repo.grant(EMAIL) is None


@pytest.mark.parametrize('rows', [[GRANT, GRANT], [{**GRANT, 'role': 'admin'}], [{**GRANT, 'active': 'true'}], [{**GRANT, 'expires_at': 'tomorrow'}]])
def test_duplicate_or_invalid_grants_fail_closed(rows):
    repo, _ = repo_with(rows)
    with pytest.raises(HTTPException) as error:
        repo.grant(EMAIL)
    assert error.value.status_code == 503


@pytest.mark.parametrize('error', [Forbidden('private detail'), NotFound('private detail'), RuntimeError('private detail')])
def test_storage_errors_are_safe_and_do_not_use_legacy_environment_fallback(error):
    repo, client = repo_with([]); client.query.side_effect = error
    with patch.dict(settings.__dict__, {'google_iam_users_json': '[{"email":"reviewer@company.example","role":"reviewer"}]'}):
        with pytest.raises(HTTPException) as caught:
            repo.grant(EMAIL)
    assert caught.value.status_code == 503 and 'private detail' not in caught.value.detail


def test_revocation_is_observed_after_at_most_30_seconds_and_an_outage_does_not_reuse_expired_role():
    seconds = [0]; client = Mock(); client.query.return_value.result.return_value = [dict(GRANT)]
    repo = AccessGrantRepository(client, clock=lambda: seconds[0], utcnow=lambda: NOW)
    with patch.dict(settings.__dict__, {'authz_cache_ttl_seconds': 999}):
        assert repo.grant(EMAIL)['role'] == 'reviewer'
        client.query.return_value.result.return_value = [{**GRANT, 'active': False}]
        seconds[0] = 29; assert repo.grant(EMAIL)['role'] == 'reviewer'
        seconds[0] = 31; assert repo.grant(EMAIL) is None
        client.query.side_effect = RuntimeError('storage outage')
        seconds[0] = 62
        with pytest.raises(HTTPException): repo.grant(EMAIL)


def test_role_cache_does_not_outlive_grant_expiration():
    seconds = [0]; rows = [{**GRANT, 'expires_at': NOW + timedelta(seconds=2)}]
    client = Mock(); client.query.return_value.result.return_value = rows
    repo = AccessGrantRepository(client, clock=lambda: seconds[0], utcnow=lambda: NOW + timedelta(seconds=seconds[0]))
    assert repo.grant(EMAIL)
    seconds[0] = 3
    assert repo.grant(EMAIL) is None


def test_invalid_table_configuration_is_rejected_before_a_query():
    repo, client = repo_with([])
    with patch.dict(settings.__dict__, {'authz_table': 'project.dataset.table`; DROP TABLE data;--'}):
        with pytest.raises(HTTPException): repo.grant(EMAIL)
    client.query.assert_not_called()


def test_default_table_is_the_existing_workflow_dataset_but_role_storage_is_separate():
    with patch.dict(settings.__dict__, {'authz_table': ''}):
        assert access_table_ref() == f'{settings.project_id}.{settings.dataset}.application_access_grants'
