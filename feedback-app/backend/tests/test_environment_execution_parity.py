from dataclasses import asdict
import json
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth import AuthenticatedUser
from app.config import settings
from app.environment_repository import environment_target, public_environment
from app.main import app, repository
from app.workflow_worker import process_feedback_job
from test_agent_environments import ENV, URL, login
from test_workflow import record


def target_row(kind, enabled=True):
    return {**ENV, 'id': 'neo-' + kind, 'name': 'Production' if kind == 'prod' else 'Non-production',
        'kind': kind, 'enabled': enabled, 'url': URL if kind == 'nonprod' else URL.replace('test-neo-np', 'test-neo-pd')}


@pytest.mark.parametrize('kind', ['nonprod', 'prod'])
def test_execution_capabilities_follow_reviewer_role_and_enabled_state_not_environment_kind(kind):
    reviewer = AuthenticatedUser('quality.reviewer@example.test', 'Reviewer', 'reviewer')
    reporter = AuthenticatedUser('alex.requester@example.test', 'Requester', 'reporter')
    with patch.dict(settings.__dict__, {'auth_mode': 'mock', 'workflow_worker_enabled': True}):
        assert public_environment(target_row(kind), reviewer)['canRetest']
        assert not public_environment(target_row(kind, False), reviewer)['canRetest']
        assert not public_environment(target_row(kind), reporter)['canRetest']


@pytest.mark.parametrize('kind', ['nonprod', 'prod'])
def test_disabled_single_retests_return_the_same_error_without_queueing(kind):
    fake = Mock(); fake.get_feedback.return_value = record()
    fake.get_agent_environment.return_value = target_row(kind, False)
    app.dependency_overrides[repository] = lambda: fake
    try:
        client = TestClient(app)
        response = client.post('/api/feedback/FDB-1/retests', headers=login(client), json={
            'target_id': 'neo-' + kind, 'idempotency_key': 'same-disabled-target-test'})
        assert response.status_code == 503 and 'disabled' in response.json()['detail']
        fake.enqueue_feedback_job.assert_not_called()
    finally:
        app.dependency_overrides.pop(repository, None)


@pytest.mark.parametrize('kind', ['nonprod', 'prod'])
def test_worker_generates_a_new_target_answer_and_rca_while_retaining_the_source_baseline(kind):
    source = record(environmentId='neo-nonprod')
    before = source.model_dump()
    row = target_row(kind); target = environment_target(row)
    baseline = {'id': 'original:FDB-1', 'kind': 'original', 'question': source.prompt,
        'answer': source.generatedAnswer, 'environment': 'nonprod', 'environmentId': 'neo-nonprod', 'revision': source.revision}
    saved = {('feedback_answer_versions', 'original:FDB-1'): dict(baseline)}
    repo = Mock(); repo._json_object.side_effect = json.loads
    repo.get_agent_environment.return_value = row
    repo.get_version.side_effect = lambda table, identity: saved.get((table, identity))
    repo.save_version.side_effect = lambda table, identity, feedback, payload, *args: saved.update({(table, identity): {'id': identity, **payload}})
    repo.mark_generation_started.return_value = True
    snapshot = {'target': asdict(target), 'environmentName': row['name'], 'sourceEnvironmentId': 'neo-nonprod', 'baseline': baseline}
    job = {'id': 'JOB-' + kind, 'kind': 'retest', 'target_id': target.id, 'environment': kind,
        'requested_by': 'quality.reviewer@example.test', 'revision': source.revision,
        'payload_json': source.model_dump_json(), 'target_snapshot_json': json.dumps(snapshot)}
    evidence = [{'evidence_id': 'D1', 'source': 'Reference.pdf', 'context': 'Document-backed rule.'}]
    diagnosis = {'suggested_rca': 'reasoning_error', 'rca_rationale': 'Fresh diagnosis of the new answer using D1.',
        'suggested_rca_confidence': 0.9, 'rca_evidence': evidence, 'rca_suggestion_status': 'sonnet_suggested'}
    with patch.dict(settings.__dict__, {'auth_mode': 'mock'}), \
        patch('app.workflow_worker.invoke_agent', return_value={'answer': 'Fresh ' + kind + ' response'}) as invoke, \
        patch('app.workflow_worker.evidence_for', return_value=evidence), \
        patch('app.workflow_worker.suggest_root_cause', return_value=diagnosis), \
        patch('app.workflow_worker.assess_correction', return_value={'assessment': 'still_incorrect', 'reviewRequired': True}) as compare:
        process_feedback_job(repo, job)
    invoke.assert_called_once()
    new_answer = saved[('feedback_answer_versions', 'answer:' + job['id'])]
    new_rca = saved[('feedback_rca_versions', 'rca:' + job['id'])]
    assert new_answer['answer'] == 'Fresh ' + kind + ' response'
    assert new_answer['environmentId'] == target.id and new_answer['baselineAnswerId'] == baseline['id']
    assert new_rca['answerId'] == new_answer['id'] and new_rca['environmentId'] == target.id and not new_rca['verified']
    assert compare.call_args.args[0]['generatedAnswer'] == baseline['answer']
    assert compare.call_args.args[1]['generatedAnswer'] == new_answer['answer']
    assert saved[('feedback_answer_versions', 'original:FDB-1')] == baseline and source.model_dump() == before
    repo.update_rca_suggestion.assert_not_called()
    repo.complete_feedback_job.assert_called_once()
