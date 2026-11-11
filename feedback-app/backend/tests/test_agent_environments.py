import hashlib
import json
from dataclasses import asdict
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient
from google.api_core.exceptions import BadRequest, NotFound

from app.agent_targets import AgentTarget, stored_environment_kind, validate_environment_target
from app.auth import AuthenticatedUser
from app.bigquery import BigQueryRepository
from app.config import settings
from app.environment_repository import environment_target, public_environment
from app.main import app, repository
from app.models import AgentEnvironmentInput, AnswerConfirmation, FeedbackCreate, PromotionCreate, PromotionSelection
from app.agent_errors import AgentInvocationError
from app.workflow_worker import process_feedback_job
from test_workflow import record


URL = 'https://api.loreal.net/global/it4it/btdp-genaiengine/v1/contexts/test-neo-np/configs/default/generations'
ENV = {'id': 'uat', 'agent_id': 'neo-rules-agent', 'name': 'UAT', 'kind': 'nonprod', 'url': URL,
       'protocol': 'neo_companion', 'auth': 'google_access_token', 'enabled': True, 'revision': 2, 'timeout_seconds': 300}
BATCH = {'id': 'PROM-test', 'targetId': 'uat', 'targetName': 'UAT', 'sourceEnvironmentId': 'dev',
         'createdAt': '2026-10-23T00:00:00Z', 'requestedBy': 'quality.reviewer@example.test',
         'requestHash': 'internal', 'total': 1, 'finished': False,
         'counts': {'queued': 1, 'running': 0, 'completed': 0, 'failed': 0, 'cancelled': 0}, 'items': []}


def client_for(fake):
    app.dependency_overrides[repository] = lambda: fake
    return TestClient(app)


def login(client, role='reviewer'):
    email = 'quality.reviewer@example.test' if role == 'reviewer' else 'alex.requester@example.test'
    return {'Authorization': 'Bearer ' + client.post('/api/auth/mock-login', json={'email': email}).json()['accessToken']}


@pytest.fixture(autouse=True)
def dependencies():
    yield
    app.dependency_overrides.pop(repository, None)


@pytest.mark.parametrize('url', ['http://api.loreal.net/run', 'https://evil.example/run',
    'https://169.254.169.254/computeMetadata/v1/', 'https://metadata.google.internal/run',
    'https://user:password@api.loreal.net/run', 'https://api.loreal.net/run?token=secret',
    'https://api.loreal.net/run#secret', 'https://api.loreal.net:8443/run'])
def test_untrusted_endpoint_is_rejected_without_network_access(url):
    with pytest.raises(ValueError):
        validate_environment_target(AgentTarget('uat', 'neo-rules-agent', 'nonprod', 'UAT', url=url))


def test_neo_environment_type_must_match_context_and_runtime_auth():
    validate_environment_target(environment_target(ENV))
    with pytest.raises(ValueError, match='scope'):
        validate_environment_target(environment_target({**ENV, 'kind': 'prod'}))
    with pytest.raises(ValueError, match='OAuth'):
        validate_environment_target(environment_target({**ENV, 'auth': 'none'}))
    with pytest.raises(ValueError, match='Companion response format'):
        validate_environment_target(environment_target({**ENV, 'protocol': 'quality_json', 'url': URL.replace('test-neo-np', 'test-neo-prod')}))


def test_cloud_never_allows_a_local_metadata_endpoint_even_in_development():
    with patch.dict('os.environ', {'K_SERVICE': 'cloud-service'}), patch.dict(settings.__dict__, {'app_env': 'development'}):
        with pytest.raises(ValueError):
            validate_environment_target(AgentTarget('local', 'neo-rules-agent', 'nonprod', 'Local', url='http://127.0.0.1:8080/run'))


def test_operator_host_list_cannot_make_cloud_localhost_a_remote_endpoint():
    with patch.dict('os.environ', {'K_SERVICE': 'cloud-service'}), patch.dict(settings.__dict__, {'agent_allowed_hosts': ('localhost', 'metadata.google.internal')}):
        for url in ['https://localhost/run', 'https://metadata.google.internal/run']:
            with pytest.raises(ValueError, match='metadata-service'):
                validate_environment_target(AgentTarget('local', 'neo-rules-agent', 'nonprod', 'Local', url=url))


def test_disabling_without_an_endpoint_is_valid_and_has_no_retest_capability():
    value = environment_target({**ENV, 'url': '', 'enabled': False})
    validate_environment_target(value)
    assert value.blocked_reason(AuthenticatedUser('reviewer@example.test', 'Reviewer', 'reviewer'))


def test_reporter_environment_catalog_does_not_contain_endpoints_or_authentication():
    fake = Mock()
    fake.list_agent_environments.return_value = [ENV]
    client = client_for(fake)
    response = client.get('/api/my/agent-environments', headers=login(client, 'reporter'))
    assert response.status_code == 200
    value = response.json()[0]
    assert value['id'] == 'uat' and not value['canRetest'] and not value['canManage']
    assert not {'url', 'auth', 'audience', 'token_env'} & value.keys()
    assert URL not in response.text


@pytest.mark.parametrize('path,method,body', [
    ('/api/agent-environments', 'post', {'name': 'UAT', 'url': URL}),
    ('/api/agent-environments/uat', 'patch', {'name': 'UAT', 'url': URL}),
    ('/api/promotions/preview', 'post', {'feedback_ids': ['FDB-1']}),
    ('/api/promotions', 'post', {}), ('/api/promotions/PROM-1/cancel', 'post', {}),
    ('/api/feedback/FDB-1/answer-rca', 'post', {}),
])
def test_reporter_cannot_manage_environments_or_dispatch_work(path, method, body):
    fake = Mock()
    client = client_for(fake)
    assert getattr(client, method)(path, headers=login(client, 'reporter'), json=body).status_code == 403
    fake.save_agent_environment.assert_not_called()
    fake.create_promotion.assert_not_called()


def test_reviewer_can_save_an_environment_without_any_generation():
    fake = Mock()
    fake.save_agent_environment.return_value = ENV
    client = client_for(fake)
    with patch('app.workflow_worker.invoke_agent') as invoke:
        response = client.post('/api/agent-environments', headers=login(client), json={'name': 'UAT', 'url': URL})
    assert response.status_code == 201 and response.json()['name'] == 'UAT'
    fake.save_agent_environment.assert_called_once()
    fake.create_promotion.assert_not_called()
    invoke.assert_not_called()


def test_creating_an_agent_is_not_exposed_through_environment_settings():
    fake = Mock()
    client = client_for(fake)
    assert client.post('/api/agent-environments', headers=login(client), json={'agent_id': 'new-agent', 'name': 'UAT', 'url': URL}).status_code == 422
    fake.save_agent_environment.assert_not_called()


def test_environment_type_is_immutable_and_must_match_the_companion_context():
    fake = Mock()
    fake.get_agent_environment.return_value = {**ENV, 'kind': 'prod', 'name': 'Production'}
    client = client_for(fake)
    with patch.dict(settings.__dict__, {'auth_mode': 'mock'}):
        assert client.patch('/api/agent-environments/uat', headers=login(client), json={'name': 'DEV', 'kind': 'nonprod', 'url': URL, 'expected_revision': 2}).status_code == 409
        assert client.post('/api/agent-environments', headers=login(client), json={'name': 'DEV', 'kind': 'prod', 'url': URL}).status_code == 422
    fake.save_agent_environment.assert_not_called()


def test_forbidden_host_rejected_before_registry_mutation():
    fake = Mock(); client = client_for(fake)
    assert client.post('/api/agent-environments', headers=login(client), json={'name': 'UAT', 'url': 'https://evil.example/run'}).status_code == 422
    fake.save_agent_environment.assert_not_called()


def test_disabled_worker_does_not_silently_queue_a_batch():
    fake = Mock(); fake.get_agent_environment.return_value = ENV
    client = client_for(fake)
    with patch.dict(settings.__dict__, {'workflow_worker_enabled': False}):
        response = client.post('/api/promotions', headers=login(client), json={'feedback_ids': ['FDB-1'], 'target_id': 'uat', 'selection_token': 'a' * 64, 'idempotency_key': 'one-explicit-confirmation'})
    assert response.status_code == 503
    fake.create_promotion.assert_not_called()


def test_explicit_bulk_confirmation_only_enqueues_and_returns_safe_progress():
    fake = Mock(); fake.get_agent_environment.return_value = ENV; fake.create_promotion.return_value = BATCH
    client = client_for(fake)
    with patch.dict(settings.__dict__, {'workflow_worker_enabled': True}), patch('app.workflow_worker.invoke_agent') as invoke:
        response = client.post('/api/promotions', headers=login(client), json={'feedback_ids': ['FDB-1', 'FDB-2'], 'target_id': 'uat', 'selection_token': 'a' * 64, 'idempotency_key': 'one-explicit-confirmation'})
    assert response.status_code == 202
    assert response.json()['canCancel'] and 'requestHash' not in response.json()
    assert fake.create_promotion.call_args.args[0].feedback_ids == ['FDB-1', 'FDB-2']
    invoke.assert_not_called()


def test_selection_cannot_be_empty_or_ambiguous():
    with pytest.raises(ValueError): PromotionSelection()
    with pytest.raises(ValueError): PromotionSelection(feedback_ids=['FDB-1'], all_matching=True)
    assert PromotionSelection(feedback_ids=['FDB-2', 'FDB-1', 'FDB-1']).feedback_ids == ['FDB-1', 'FDB-2']


def test_unassigned_imports_and_unknown_named_environments_are_not_equated():
    repo = BigQueryRepository(client=Mock())
    source = record(environment='unknown')
    assert source.environmentId is None
    owned = {'id': 'FDB-1', 'environment': 'nonprod', 'environmentId': 'dev', 'revision': 1}
    job = {'id': 'JOB-UAT', 'feedback_id': 'FDB-1', 'kind': 'retest', 'status': 'completed', 'environment': 'nonprod', 'target_id': 'uat', 'revision': 1}
    with patch.object(repo, 'get_my_feedback', return_value=owned), patch.object(repo, 'get_feedback_job', return_value=job), patch.object(repo, 'workflow_query') as query:
        with pytest.raises(ValueError, match='different named environment'):
            repo.confirm_retest('FDB-1', 'JOB-UAT', ['owner@example.test'], 'owner@example.test', AnswerConfirmation(verdict='fixed'))
    query.assert_not_called()


def test_batch_snapshots_target_input_and_baseline_without_rewriting_feedback():
    repo = BigQueryRepository(client=Mock())
    original = record(environmentId='dev')
    before = original.model_dump()
    selection = PromotionCreate(feedback_ids=['FDB-1'], target_id='uat', idempotency_key='fixed-confirmation', selection_token='a' * 64)
    batch = {**BATCH, 'requestHash': hashlib.sha256(selection.model_dump_json().encode()).hexdigest(), 'requestedBy': 'reviewer@example.test'}
    with patch.object(repo, 'ensure_environment_schema'), patch.object(repo, 'get_promotion', side_effect=[None, batch]), \
         patch.object(repo, 'select_promotion_records', return_value=([original], selection.selection_token)), \
         patch.object(repo, '_promotion_baselines', return_value={'FDB-1': {'id': 'answer:dev', 'question': original.prompt, 'answer': 'DEV baseline'}}), \
         patch.object(repo, 'workflow_query') as query:
        assert repo.create_promotion(selection, ENV, 'reviewer@example.test')['id'] == 'PROM-test'
    sql, params = query.call_args.args
    assert 'BEGIN TRANSACTION' in sql and 'Target configuration changed' in sql and 'Feedback input changed' in sql
    assert 'A selected input already has an active target check' in sql
    assert 'INSERT INTO' in sql and "'retest','queued','queued'" in sql
    assert 'MERGE `oa-apmena-techsandbox-ap-dv.agent_quality.feedback_main_environments`' in sql
    assert "'main_environment_selected'" in sql and 'main_environment_id' in sql
    assert 'UPDATE `oa-apmena-techsandbox-ap-dv.agent_quality.feedback_items`' not in sql
    assert f'UPDATE `{repo.feedback_ref}`' not in sql and 'DELETE FROM' not in sql
    values = next(value for value in params if value.name == 'items').values
    snapshot = json.loads(values[0].struct_values['snapshot'])
    assert snapshot['target']['url'] == URL and snapshot['target']['configuration_version'] == 2
    assert next(value for value in params if value.name == 'environment').value == 'unknown'
    assert next(value for value in params if value.name == 'target_kind').value == 'nonprod'
    assert '@target_kind AS environment_kind' in sql
    assert snapshot['baseline']['id'] == 'answer:dev'
    assert original.model_dump() == before


def test_same_confirmation_does_not_create_another_batch_or_call():
    repo = BigQueryRepository(client=Mock())
    selection = PromotionCreate(feedback_ids=['FDB-1'], target_id='uat', idempotency_key='fixed-confirmation', selection_token='a' * 64)
    batch = {**BATCH, 'requestHash': hashlib.sha256(selection.model_dump_json().encode()).hexdigest()}
    with patch.object(repo, 'ensure_environment_schema'), patch.object(repo, 'get_promotion', return_value=batch), patch.object(repo, 'workflow_query') as query, patch.object(repo, 'select_promotion_records') as select:
        assert repo.create_promotion(selection, ENV, BATCH['requestedBy']) == batch
    query.assert_not_called(); select.assert_not_called()


def test_changed_selection_is_rejected_before_job_insertion():
    repo = BigQueryRepository(client=Mock())
    selection = PromotionCreate(feedback_ids=['FDB-1'], target_id='uat', idempotency_key='fixed-confirmation', selection_token='a' * 64)
    with patch.object(repo, 'ensure_environment_schema'), patch.object(repo, 'get_promotion', return_value=None), patch.object(repo, 'select_promotion_records', return_value=([record()], 'b' * 64)), patch.object(repo, 'workflow_query') as query:
        with pytest.raises(ValueError, match='selection or input revisions changed'):
            repo.create_promotion(selection, ENV, 'reviewer@example.test')
    query.assert_not_called()


def test_uncertain_generation_is_never_replayed():
    repo = Mock(); repo._json_object.side_effect = json.loads
    repo.get_version.side_effect = [{'question': 'What is the order rule?', 'answer': 'Original'}, None]
    repo.mark_generation_started.return_value = False
    job = {'id': 'JOB-1', 'kind': 'retest', 'target_id': 'neo-nonprod', 'environment': 'nonprod', 'payload_json': record().model_dump_json()}
    with patch('app.workflow_worker.invoke_agent') as invoke:
        with pytest.raises(AgentInvocationError, match='unknown'):
            process_feedback_job(repo, job)
    invoke.assert_not_called()


def test_worker_uses_confirmed_target_snapshot_and_saves_answer_before_rca():
    repo = Mock(); repo._json_object.side_effect = json.loads
    source = record(environmentId='dev')
    repo.get_agent_environment.return_value = {**ENV, 'url': URL.replace('test-neo-np', 'edited-target-np'), 'revision': 3}
    repo.get_version.side_effect = [{'question': source.prompt, 'answer': 'Original'}, None, None, None]
    repo.mark_generation_started.return_value = True
    snapshot = {'target': asdict(environment_target(ENV)), 'environmentName': 'UAT', 'baseline': {'id': 'answer:dev', 'question': source.prompt, 'answer': 'DEV baseline'}}
    job = {'id': 'JOB-1', 'kind': 'retest', 'target_id': 'uat', 'environment': 'nonprod', 'batch_id': 'PROM-1', 'payload_json': source.model_dump_json(), 'target_snapshot_json': json.dumps(snapshot)}
    diagnosis = {'suggested_rca': 'reasoning_error', 'rca_rationale': 'Rule differs', 'suggested_rca_confidence': 0.9}
    with patch('app.workflow_worker.invoke_agent', return_value={'answer': 'Fresh UAT answer'}) as invoke, patch('app.workflow_worker.evidence_for', return_value=[]), patch('app.workflow_worker.suggest_root_cause', return_value=diagnosis), patch('app.workflow_worker.assess_correction', return_value={'assessment': 'inconclusive'}):
        process_feedback_job(repo, job)
    assert invoke.call_args.args[0].url == URL
    saved = repo.save_version.call_args_list
    assert saved[0].args[0] == 'feedback_answer_versions' and saved[1].args[0] == 'feedback_rca_versions'
    assert saved[0].args[3]['environmentId'] == 'uat' and saved[1].args[3]['environmentId'] == 'uat'
    assert saved[0].args[3]['configurationRevision'] == 2 and saved[1].args[3]['configurationRevision'] == 2
    assert source.environmentId == 'dev' and source.generatedAnswer == 'Old answer'


def test_saved_answer_rca_retry_is_answer_scoped_and_does_not_request_a_retest():
    repo = BigQueryRepository(client=Mock())
    answer = {'question': 'Saved question', 'answer': 'Saved UAT answer', 'environment': 'nonprod', 'environmentId': 'uat', 'environmentLabel': 'UAT', 'revision': 2}
    with patch.object(repo, 'get_feedback', return_value=record()), patch.object(repo, 'workflow_query', return_value=[{'payload_json': json.dumps(answer)}]), patch.object(repo, 'enqueue_feedback_job', return_value={'id': 'RCA-1'}) as enqueue:
        repo.queue_saved_answer_rca('FDB-1', 'answer:saved', 'reviewer@example.test', 'explicit-rca-check')
    args = enqueue.call_args.args
    assert args[1] == 'rca' and args[0].runContext['analysis_answer_id'] == 'answer:saved'
    assert args[0].generatedAnswer == 'Saved UAT answer' and args[0].environmentId == 'uat'


def test_other_reviewers_cannot_cancel_someone_elses_batch():
    fake = Mock(); fake.get_promotion.return_value = {**BATCH, 'requestedBy': 'other@example.test'}
    client = client_for(fake)
    assert client.post('/api/promotions/PROM-test/cancel', headers=login(client)).status_code == 403
    fake.cancel_promotion.assert_not_called()


def test_missing_registry_reads_existing_targets_without_schema_writes():
    repo = BigQueryRepository(client=Mock())
    with patch.object(repo, 'workflow_query', side_effect=NotFound('not initialized')), patch.object(repo, 'ensure_environment_schema') as migrate:
        rows = repo.list_agent_environments()
    assert rows and all(not row['persisted'] for row in rows)
    migrate.assert_not_called()


def test_named_source_environment_is_readable_but_fenced_from_old_kind_only_confirmation():
    repo = BigQueryRepository(client=Mock())
    row = repo._feedback_row(FeedbackCreate(question='Question', answer='Answer', user_verdict='Incorrect', feedback_text='Issue',
        environment='nonprod', environment_id='uat', run_context={'environment_label': 'UAT'}))
    assert row['environment'] == 'unknown'  # Old API refuses owner confirmation for unknown origins.
    value = repo._record(row)
    assert value.environment == 'nonprod' and value.environmentId == 'uat'
    assert json.loads(row['run_context_json'])['environment_kind'] == 'nonprod'
    assert stored_environment_kind('neo-rules-agent', 'nonprod', 'neo-nonprod') == 'nonprod'


def test_custom_result_is_fenced_in_storage_but_has_canonical_public_metadata():
    repo = BigQueryRepository(client=Mock())
    job = {'id': 'JOB-UAT', 'environment': 'unknown', 'target_id': 'uat', 'kind': 'retest', 'status': 'completed',
           'target_snapshot_json': json.dumps({'target': {'environment': 'nonprod', 'url': URL}, 'environmentName': 'UAT'})}
    safe = repo.safe_job(job)
    assert safe['environment'] == 'nonprod' and safe['environmentId'] == 'uat'
    assert URL not in json.dumps(safe)


def test_capture_environment_does_not_trust_reserved_identity_fields_in_run_context():
    fake = Mock()
    fake.create_feedback.return_value = record()
    client = client_for(fake)
    response = client.post('/api/feedback', headers=login(client), json={'question': 'Question', 'answer': 'Answer',
        'user_verdict': 'Incorrect', 'feedback_text': 'Issue', 'environment': 'unknown',
        'run_context': {'environment_id': 'uat', 'environment_kind': 'prod', 'environment_label': 'Fake production'}})
    assert response.status_code == 201
    payload = fake.create_feedback.call_args.args[0]
    assert not {'environment_id', 'environment_kind', 'environment_label'} & payload.run_context.keys()


def test_matching_named_owner_confirmation_uses_canonical_kind_and_exact_id():
    repo = BigQueryRepository(client=Mock())
    owned = {'id': 'FDB-1', 'environment': 'nonprod', 'environmentId': 'uat', 'revision': 1}
    job = {'id': 'JOB-UAT', 'feedback_id': 'FDB-1', 'kind': 'retest', 'status': 'completed', 'environment': 'unknown',
           'target_id': 'uat', 'revision': 1, 'target_snapshot_json': json.dumps({'target': {'environment': 'nonprod'}})}
    with patch.object(repo, 'get_my_feedback', return_value=owned), patch.object(repo, 'get_feedback_job', return_value=job), \
         patch.object(repo, 'latest_confirmable_retest', return_value='JOB-UAT'), patch.object(repo, 'get_version', return_value={'answer': 'Fresh answer'}), \
         patch.object(repo, 'workflow_query') as query, patch.object(repo, '_insert_event'):
        repo.confirm_retest('FDB-1', 'JOB-UAT', ['owner@example.test'], 'owner@example.test', AnswerConfirmation(verdict='fixed'))
    assert "$.environment_kind" in query.call_args.args[0] and "$.environment_id" in query.call_args.args[0]


def test_expected_transaction_conflicts_are_safe_actionable_errors():
    repo = BigQueryRepository(client=Mock())
    with patch.object(repo, 'workflow_query', side_effect=BadRequest('A selected input already has an active target check')):
        with pytest.raises(ValueError, match='queued/running check'):
            repo.environment_transaction('fixture SQL', [])
    with patch.object(repo, 'workflow_query', side_effect=BadRequest('SQL syntax problem')):
        with pytest.raises(BadRequest):
            repo.environment_transaction('fixture SQL', [])
