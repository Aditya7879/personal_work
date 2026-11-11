from datetime import datetime, timedelta, timezone
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.agent_errors import AgentInvocationError
from app.agent_targets import invoke_agent
from app.auth import AuthenticatedUser
from app.config import settings
from app.endpoint_tests import get_endpoint_test, run_endpoint_test, test_result as format_test_result
from app.environment_repository import environment_target, public_environment
from app.main import app, repository
from app.models import EndpointTestInput
from google.api_core.exceptions import NotFound
from test_agent_environments import BATCH, ENV, URL, login


PROD = {**ENV, 'id': 'prod', 'name': 'Production', 'kind': 'prod', 'enabled': False,
        'url': URL.replace('test-neo-np', 'test-neo-prod')}


@pytest.fixture(autouse=True)
def clean_dependency():
    yield
    app.dependency_overrides.pop(repository, None)


@pytest.mark.parametrize('enabled', [False, True])
def test_production_settings_and_endpoint_testing_have_no_extra_permission_gate(enabled):
    user = AuthenticatedUser('quality.reviewer@example.test', 'Reviewer', 'reviewer')
    with patch.dict(settings.__dict__, {'auth_mode': 'mock'}):
        value = public_environment({**PROD, 'enabled': enabled}, user, True)
    assert value['canManage'] and value['canActivate'] and value['canTest']
    assert value['activationReason'] is None and value['manageReason'] is None and value['testReason'] is None


def test_disabled_np_can_be_tested_while_worker_is_disabled():
    user = AuthenticatedUser('quality.reviewer@example.test', 'Reviewer', 'reviewer')
    with patch.dict(settings.__dict__, {'workflow_worker_enabled': False}):
        value = public_environment({**ENV, 'enabled': False}, user, True)
    assert value['canManage'] and value['canTest'] and not value['canRetest']


def test_reviewer_can_save_disabled_production_draft_without_invoking_any_agent():
    fake = Mock(); fake.get_agent_environment.return_value = PROD; fake.save_agent_environment.return_value = PROD
    app.dependency_overrides[repository] = lambda: fake; client = TestClient(app)
    with patch('app.workflow_worker.invoke_agent') as invoke:
        response = client.patch('/api/agent-environments/prod', headers=login(client), json={'name': 'Production',
            'kind': 'prod', 'enabled': False, 'url': PROD['url'], 'expected_revision': 2})
    assert response.status_code == 200 and response.json()['canManage']
    assert response.json()['canActivate']
    fake.save_agent_environment.assert_called_once(); invoke.assert_not_called()


def test_reviewer_can_enable_and_edit_production_configuration_like_other_environments():
    fake = Mock(); fake.get_agent_environment.return_value = PROD; fake.save_agent_environment.return_value = {**PROD, 'enabled': True}
    app.dependency_overrides[repository] = lambda: fake; client = TestClient(app); headers = login(client)
    body = {'name': 'Production', 'kind': 'prod', 'enabled': True, 'url': PROD['url'], 'expected_revision': 2}
    assert client.patch('/api/agent-environments/prod', headers=headers, json=body).status_code == 200
    fake.get_agent_environment.return_value = {**PROD, 'enabled': True}
    assert client.patch('/api/agent-environments/prod', headers=headers, json={**body, 'enabled': False}).status_code == 200
    assert fake.save_agent_environment.call_count == 2


def test_environment_edit_still_rejects_a_stale_or_guessed_revision():
    fake = Mock(); fake.get_agent_environment.return_value = PROD
    app.dependency_overrides[repository] = lambda: fake; client = TestClient(app)
    response = client.patch('/api/agent-environments/prod', headers=login(client), json={
        'name': 'Production', 'kind': 'prod', 'enabled': False, 'url': PROD['url'], 'expected_revision': 3})
    assert response.status_code == 409
    fake.save_agent_environment.assert_not_called()


@pytest.mark.parametrize('environment_id', ['prod', 'uat'])
def test_reporter_endpoint_testing_is_forbidden_for_every_environment(environment_id):
    fake = Mock(); fake.get_agent_environment.return_value = PROD
    app.dependency_overrides[repository] = lambda: fake; client = TestClient(app)
    body = {'expected_revision': 2, 'idempotency_key': 'explicit-test-key'}
    with patch('app.endpoint_tests.run_endpoint_test') as run:
        assert client.post(f'/api/agent-environments/{environment_id}/test', headers=login(client, 'reporter'), json=body).status_code == 403
    run.assert_not_called()


@pytest.mark.parametrize('environment', [ENV, PROD])
@pytest.mark.parametrize('enabled', [False, True])
def test_endpoint_test_uses_the_same_request_for_every_environment_without_sso(environment, enabled):
    fake = Mock(); fake.get_agent_environment.return_value = {**environment, 'enabled': enabled}
    app.dependency_overrides[repository] = lambda: fake; client = TestClient(app)
    body = {'expected_revision': 2, 'idempotency_key': 'explicit-test-key'}
    with patch.dict(settings.__dict__, {'auth_mode': 'mock', 'prod_retest_reviewers': (), 'workflow_worker_enabled': False}), patch('app.endpoint_tests.run_endpoint_test', return_value={'status': 'succeeded'}) as run:
        assert client.post(f"/api/agent-environments/{environment['id']}/test", headers=login(client), json=body).status_code == 200
    run.assert_called_once()
    fake.enqueue_feedback_job.assert_not_called()


def test_reviewer_can_create_a_production_environment_without_a_special_grant():
    fake = Mock(); fake.save_agent_environment.return_value = {**PROD, 'enabled': True}
    app.dependency_overrides[repository] = lambda: fake; client = TestClient(app)
    with patch('app.endpoint_tests.invoke_agent') as invoke:
        response = client.post('/api/agent-environments', headers=login(client), json={
            'name': 'Production', 'kind': 'prod', 'url': PROD['url'], 'enabled': True})
    assert response.status_code == 201 and response.json()['canTest'] and response.json()['canManage']
    fake.save_agent_environment.assert_called_once(); invoke.assert_not_called()


@pytest.mark.parametrize('environment', [ENV, PROD])
def test_bulk_retests_use_the_same_reviewer_permissions_for_every_environment(environment):
    fake = Mock(); fake.get_agent_environment.return_value = {**environment, 'enabled': True}
    fake.create_promotion.return_value = {**BATCH, 'targetId': environment['id'], 'targetName': environment['name']}
    app.dependency_overrides[repository] = lambda: fake; client = TestClient(app)
    with patch.dict(settings.__dict__, {'auth_mode': 'mock', 'workflow_worker_enabled': True}), patch('app.workflow_worker.invoke_agent') as invoke:
        response = client.post('/api/promotions', headers=login(client), json={'feedback_ids': ['FDB-1'], 'target_id': environment['id'],
            'idempotency_key': 'explicit-batch-key', 'selection_token': 'a' * 24})
    assert response.status_code == 202
    fake.create_promotion.assert_called_once(); invoke.assert_not_called()


def test_endpoint_test_is_independent_of_worker_and_returns_failure_details():
    fake = Mock(); fake.get_agent_environment.return_value = {**ENV, 'enabled': False}
    app.dependency_overrides[repository] = lambda: fake; client = TestClient(app)
    with patch.dict(settings.__dict__, {'workflow_worker_enabled': False}), patch('app.endpoint_tests.run_endpoint_test', return_value={'status': 'failed', 'httpStatus': 403, 'error': 'Permission denied'}) as run:
        response = client.post('/api/agent-environments/uat/test', headers=login(client), json={'expected_revision': 2, 'idempotency_key': 'explicit-test-key'})
    assert response.status_code == 200 and response.json()['httpStatus'] == 403
    run.assert_called_once(); fake.enqueue_feedback_job.assert_not_called()


@pytest.mark.parametrize('code,status', [('permission', 403), ('authentication', 401), ('response', 200), ('timeout', None), ('redirect', 302)])
def test_one_shot_diagnostic_records_safe_error_and_never_enqueues_work(code, status):
    repo = Mock(); repo.workflow_table.side_effect = lambda name: 'project.dataset.' + name
    repo.workflow_query.return_value = [{'made': True}]
    payload = EndpointTestInput(expected_revision=2, idempotency_key='explicit-test-key')
    diagnostic_result = {'status': 'outcome_unknown' if code == 'timeout' else 'failed'}
    with patch('app.endpoint_tests.get_endpoint_test', side_effect=[KeyError(), diagnostic_result]), patch('app.endpoint_tests.invoke_agent', side_effect=AgentInvocationError(code, http_status=status)) as invoke:
        result = run_endpoint_test(repo, ENV, payload, 'reviewer@example.test')
    assert result == diagnostic_result
    invoke.assert_called_once(); assert invoke.call_args.args[0].timeout_seconds == 60
    params = {value.name: value.value for value in repo.workflow_query.call_args.args[1]}
    saved = json.loads(params['result'])
    assert saved['httpStatus'] == status and saved['errorCode'] == code and saved['automaticRetries'] == 0
    assert saved['feedbackCreated'] is False and saved['rcaRun'] is False
    for call in repo.workflow_query.call_args_list:
        assert 'feedback_items' not in call.args[0] and 'feedback_workflow_jobs' not in call.args[0]
    repo.enqueue_feedback_job.assert_not_called()


def test_completed_test_key_is_recovered_after_config_edit_without_another_call():
    payload = EndpointTestInput(expected_revision=1, idempotency_key='same-key-recovery')
    previous = {'status': 'succeeded', 'questionHash': hashlib.sha256(payload.question.encode()).hexdigest()}
    repo = Mock()
    with patch('app.endpoint_tests.get_endpoint_test', return_value=previous), patch('app.endpoint_tests.invoke_agent') as invoke:
        assert run_endpoint_test(repo, ENV, payload, 'reviewer@example.test') == previous
    invoke.assert_not_called(); repo.workflow_query.assert_not_called()


def test_simultaneous_lost_response_recovery_does_not_replay_generation():
    payload = EndpointTestInput(expected_revision=2, idempotency_key='same-key-recovery')
    previous = {'status': 'running', 'questionHash': hashlib.sha256(payload.question.encode()).hexdigest()}
    repo = Mock(); repo.workflow_query.return_value = [{'made': False}]
    with patch('app.endpoint_tests.get_endpoint_test', side_effect=[KeyError(), previous]), patch('app.endpoint_tests.invoke_agent') as invoke:
        assert run_endpoint_test(repo, ENV, payload, 'reviewer@example.test') == previous
    invoke.assert_not_called(); assert repo.workflow_query.call_count == 1


def test_reusing_a_key_with_a_different_question_is_rejected_even_after_reservation_race():
    payload = EndpointTestInput(expected_revision=2, idempotency_key='same-key-recovery')
    repo = Mock(); repo.workflow_query.return_value = [{'made': False}]
    with patch('app.endpoint_tests.get_endpoint_test', side_effect=[KeyError(), {'questionHash': 'another-question'}]), patch('app.endpoint_tests.invoke_agent') as invoke:
        with pytest.raises(ValueError, match='another question'):
            run_endpoint_test(repo, ENV, payload, 'reviewer@example.test')
    invoke.assert_not_called()


def test_missing_endpoint_test_storage_is_a_not_found_read_not_an_implicit_mutation():
    repo = Mock(); repo.workflow_query.side_effect = NotFound('No endpoint tests exist')
    with pytest.raises(KeyError, match='Endpoint test not found'):
        get_endpoint_test(repo, 'uat', 'TEST-1')
    repo.ensure_environment_schema.assert_not_called()


def test_reporter_environment_metadata_omits_endpoint_answers_and_runtime_identity():
    user = AuthenticatedUser('reporter@example.test', 'Reporter', 'reporter')
    value = public_environment({**ENV, 'last_test': {'status': 'succeeded', 'answerPreview': 'private-test-answer',
        'runtimeIdentity': {'principal': 'private-runtime@example.iam.gserviceaccount.com'}}}, user)
    assert not value['canManage'] and not value['canTest']
    assert 'lastTest' not in value and 'url' not in value
    assert 'private-test-answer' not in json.dumps(value) and 'private-runtime' not in json.dumps(value)


def test_interrupted_running_test_becomes_unknown_without_replaying_it():
    row = {'id': 'TEST-1', 'environment_id': 'uat', 'configuration_revision': 1, 'status': 'running',
           'created_at': datetime.now(timezone.utc) - timedelta(minutes=3), 'result_json': '{}'}
    value = format_test_result(row)
    assert value['status'] == 'outcome_unknown' and value['outcomeUnknown']
    assert row['status'] == 'running'


def test_diagnostic_preview_redacts_runtime_credentials_and_does_not_return_traces():
    credentials = SimpleNamespace(token='fixture-secret-access-token', refresh=Mock(), service_account_email='runtime@example.iam.gserviceaccount.com')
    response = httpx.Response(200, request=httpx.Request('POST', URL), json={'messages': [{'type': 'ai', 'data': {'content': 'Hello Bearer fixture-secret-access-token password=fixture-password'}}]})
    transport = Mock(); transport.__enter__ = Mock(return_value=transport); transport.__exit__ = Mock(return_value=False); transport.post.return_value = response
    diagnostic = {}
    with patch('app.agent_targets.google.auth.default', return_value=(credentials, 'project')), patch('app.agent_targets.httpx.Client', return_value=transport):
        invoke_agent(environment_target(ENV), 'Hello', 'TEST-1', diagnostics=diagnostic)
    text = json.dumps(diagnostic)
    assert 'fixture-secret-access-token' not in text and 'fixture-password' not in text
    assert diagnostic['httpStatus'] == 200 and '[REDACTED]' in diagnostic['answerPreview']
    assert not {'privateTrace', 'headers', 'token'} & diagnostic.keys()


def test_http_200_without_a_final_answer_is_a_failed_test_not_a_success():
    response = httpx.Response(200, request=httpx.Request('POST', URL), json={'messages': [{'type': 'ai', 'data': {'content': '', 'tool_calls': [{'name': 'search'}]}}]})
    transport = Mock(); transport.__enter__ = Mock(return_value=transport); transport.__exit__ = Mock(return_value=False); transport.post.return_value = response
    credentials = SimpleNamespace(token='fixture-token', refresh=Mock())
    with patch('app.agent_targets.google.auth.default', return_value=(credentials, 'project')), patch('app.agent_targets.httpx.Client', return_value=transport):
        with pytest.raises(AgentInvocationError) as caught:
            invoke_agent(environment_target(ENV), 'Hello', 'TEST-1', diagnostics={})
    assert caught.value.http_status == 200 and caught.value.code == 'incomplete'
