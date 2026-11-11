import json
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
import pytest

from app.bigquery import BigQueryRepository
from app.main import app, repository
from app.rca_progress import RCA_TRIAGE_MESSAGE, completed_rca, current_source_answer_id, source_answer_id_sql, source_triage_guard
from app.workflow_worker import process_feedback_job
from test_workflow import login, record


SUGGESTION = {'suggested_rca':'retrieval_failure','suggested_rca_confidence':0.62,'rca_subcategory':'Relevant passage not used',
    'rca_rationale':'A cited source passage was not reflected in the answer.','rca_suggestion_status':'sonnet_suggested',
    'rca_evidence':[{'evidence_id':'D1','source':'training.pdf','context':'Private passage'}],
    'rca_retrieval_status':'available','rca_review_required':True,'rca_auto_accepted':False}


def test_successful_low_confidence_rca_is_processing_progress_not_human_verification():
    assert completed_rca(SUGGESTION)
    assert SUGGESTION['rca_review_required'] and not SUGGESTION['rca_auto_accepted']
    assert 'not verified' in RCA_TRIAGE_MESSAGE and 'not resolved' in RCA_TRIAGE_MESSAGE


@pytest.mark.parametrize('changes', [{'rca_suggestion_status':'evidence_unavailable'}, {'rca_suggestion_status':'fallback_TimeoutError'},
    {'rca_suggestion_status':'needs_original_answer'}, {'suggested_rca':'insufficient_evidence'}, {'suggested_rca':'unknown'},
    {'rca_retrieval_status':'unavailable'}, {'rca_retrieval_status':'no_matches'}, {'rca_evidence':[]}, {'rca_rationale':'  '}])
def test_failed_inconclusive_or_uncited_analysis_never_auto_triages(changes):
    assert not completed_rca({**SUGGESTION, **changes})


def test_source_ids_cannot_be_forged_to_point_at_a_target_environment_answer():
    assert current_source_answer_id(record(runContext={'submission_answer_id':'answer:OTHER'})) == 'original:FDB-1'
    assert current_source_answer_id(record(runContext={'submission_answer_id':'submission:FDB-1:r3'})) == 'submission:FDB-1:r3'
    for function in (source_answer_id_sql, source_triage_guard):
        with pytest.raises(ValueError): function('f; DROP TABLE data')


def test_source_rca_state_public_progress_and_audit_commit_atomically_with_exact_input_guards():
    client = Mock(); client.query.return_value.result.return_value = [{'applied':1}]
    repo = BigQueryRepository(client=client)
    with patch.object(repo,'get_feedback',return_value=record(state='Triaged')):
        updated = repo.update_rca_suggestion('FDB-1', SUGGESTION, expected_revision=3,
            source_answer_id='submission:FDB-1:r3', source_question='Exact question', source_answer='Exact source answer')
    assert updated.state == 'Triaged'
    sql = client.query.call_args.args[0]
    params = {value.name:value.value for value in client.query.call_args.kwargs['job_config'].query_parameters}
    assert params['triage_ready'] is True and params['review_required'] is True
    assert params['source_question'] == 'Exact question' and params['source_answer'] == 'Exact source answer'
    assert 'BEGIN TRANSACTION' in sql and 'COMMIT TRANSACTION' in sql and 'IF applied = 1 THEN' in sql
    assert 'rca_auto_triaged' in sql and 'IF advanced THEN' in sql
    assert 'COALESCE(revision, 1) = @expected_revision' in sql and '= @source_answer_id' in sql
    assert 'COALESCE(question,\'\') = @source_question' in sql and 'COALESCE(answer,\'\') = @source_answer' in sql
    assert source_triage_guard() in sql
    assert "'In review', public_status" in sql and "'Triaged', state" in sql
    assert 'confirmed_rca =' not in sql and 'expected_behavior_verified =' not in sql and 'latest_published_attempt_id =' not in sql
    assert 'answer =' not in sql and 'resolution_summary =' not in sql
    assert client.query.call_args.kwargs['job_retry'] is None
    client.query.return_value.result.assert_called_once_with(job_retry=None)


def test_stale_input_does_not_emit_a_separate_event_or_report_a_successful_update():
    client = Mock(); client.query.return_value.result.return_value = [{'applied':0}]
    repo = BigQueryRepository(client=client)
    with patch.object(repo,'get_feedback') as get, patch.object(repo,'_insert_event') as event:
        assert repo.update_rca_suggestion('FDB-1', SUGGESTION, expected_revision=1,
            source_answer_id='original:FDB-1', source_question='Old question', source_answer='Old answer') is None
    get.assert_not_called(); event.assert_not_called()


def test_unversioned_legacy_calls_cannot_auto_advance_state():
    client = Mock(); client.query.return_value.result.return_value = [{'applied':1}]
    repo = BigQueryRepository(client=client)
    with patch.object(repo,'get_feedback',return_value=record()): repo.update_rca_suggestion('FDB-1', SUGGESTION)
    values = {value.name:value.value for value in client.query.call_args.kwargs['job_config'].query_parameters}
    assert values['triage_ready'] is False


def worker_repo(current):
    repo = Mock(); repo._json_object.side_effect = json.loads
    repo.get_version.return_value = {'question':record().prompt,'answer':record().generatedAnswer,'kind':'original'}
    repo.get_feedback.return_value = current
    return repo


def test_completed_source_rca_updates_only_current_source_and_keeps_saved_rca_unverified():
    current = record(state='Submitted', expectedBehaviorVerified=False)
    repo = worker_repo(current)
    job = {'id':'JOB-SOURCE','kind':'enrich','payload_json':current.model_dump_json()}
    with patch('app.workflow_worker.evidence_for',return_value=SUGGESTION['rca_evidence']), patch('app.workflow_worker.suggest_root_cause',return_value=SUGGESTION), patch('app.workflow_worker.invoke_agent') as invoke:
        process_feedback_job(repo,job)
    invoke.assert_not_called()
    repo.update_rca_suggestion.assert_called_once_with(current.id,SUGGESTION,expected_revision=current.revision,
        source_answer_id='original:FDB-1',source_question=current.prompt,source_answer=current.generatedAnswer)
    saved = repo.save_version.call_args.args[3]
    assert saved['verified'] is False and saved['revision'] == current.revision
    assert saved['answerId'] == 'original:FDB-1'


def test_selected_current_source_rca_can_triage_but_selected_target_or_old_revision_cannot():
    for answer_id, revision, expected in [('original:FDB-1',1,True),('answer:TARGET',1,False),('original:FDB-1',2,False)]:
        source = record(state='Submitted',runContext={'analysis_answer_id':answer_id})
        repo = worker_repo(record(state='Submitted',revision=revision))
        job = {'id':'JOB-RCA','kind':'rca','payload_json':source.model_dump_json()}
        with patch('app.workflow_worker.evidence_for',return_value=SUGGESTION['rca_evidence']),patch('app.workflow_worker.suggest_root_cause',return_value=SUGGESTION):
            process_feedback_job(repo,job)
        assert repo.update_rca_suggestion.called is expected
        assert repo.save_version.call_args.args[3]['verified'] is False


def test_changed_capture_is_not_misdiagnosed_as_the_original_answer():
    source = record(state='Submitted',generatedAnswer='Edited without a matching capture')
    repo = worker_repo(source)
    with patch('app.workflow_worker.evidence_for',return_value=SUGGESTION['rca_evidence']),patch('app.workflow_worker.suggest_root_cause') as model:
        process_feedback_job(repo,{'id':'JOB-OLD-CAPTURE','kind':'enrich','payload_json':source.model_dump_json()})
    model.assert_not_called()
    assert repo.save_version.call_args.args[3]['suggestionStatus'] == 'needs_original_answer'


def test_auto_triage_timeline_exposes_only_the_safe_public_message():
    client = Mock(); client.query.return_value.result.return_value = [{'feedback_id':'FDB-1','event_id':'EV-1',
        'event_type':'rca_auto_triaged','created_at':'now','payload_json':json.dumps({'public_status':'In review',
            'public_message':RCA_TRIAGE_MESSAGE,'evidence':[{'context':'Private source passage'}]})}]
    result = BigQueryRepository(client=client)._public_event_map(['FDB-1'])
    assert result['FDB-1'][0]['status'] == 'In review'
    assert result['FDB-1'][0]['message'] == RCA_TRIAGE_MESSAGE
    assert 'Private source passage' not in json.dumps(result)


def test_direct_rca_that_loses_its_revision_guard_retains_the_snapshot_and_returns_conflict():
    fake = Mock(); fake.get_feedback.return_value = record(state='Submitted'); fake.update_rca_suggestion.return_value = None
    app.dependency_overrides[repository] = lambda: fake
    try:
        client = TestClient(app); headers = login(client,'quality.reviewer@example.test')
        with patch('app.main.suggest_root_cause',return_value=SUGGESTION) as model:
            response = client.post('/api/feedback/FDB-1/root-cause/suggest',headers=headers)
        assert response.status_code == 409 and 'retained in history' in response.json()['detail']
        model.assert_called_once(); fake.save_version.assert_called_once()
        assert fake.save_version.call_args.args[3]['verified'] is False
    finally: app.dependency_overrides.pop(repository,None)
