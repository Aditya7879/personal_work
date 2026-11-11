from datetime import datetime, timezone
import json
from unittest.mock import Mock, patch

import pytest

from app.bigquery import BigQueryRepository
from app.models import AnswerConfirmation, MyFeedbackUpdate
from app.submission_edits import REVISION_FIELDS, meaningful_updates, timestamp
from test_reporter_edit import edit_repo, saved_row


@pytest.mark.parametrize('changes', [
    {'user_verdict': 'Correct'}, {'title': 'A clearer title'}, {'impact': 'High'},
    {'issue_categories': ['Missing information']}, {'business_domain': 'F2S'},
])
def test_metadata_and_opinion_edits_are_audited_without_new_input_versions_or_provider_work(changes):
    row={**saved_row(), 'user_verdict':'Incorrect','latest_published_attempt_id':'JOB-SAVED',
        'confirmed_rca':'retrieval_failure','rca_rationale':'Immutable assessment context'}
    repo,client=edit_repo(row)
    with patch.object(repo,'get_my_feedback',return_value={'id':'FDB-EDIT'}):
        repo.update_my_feedback('FDB-EDIT',['owner@example.test'],MyFeedbackUpdate(expected_revision=4,
            expected_updated_at=row['updated_at'],**changes),'owner@example.test')
    sql=client.query.call_args.args[0]
    assert 'submitter_updated' in sql and 'IS NOT DISTINCT FROM @expected_updated_at' in sql
    assert 'revision = @next_revision' not in sql and 'latest_published_attempt_id = NULL' not in sql
    assert 'confirmed_rca = NULL' not in sql and 'rca_rationale = NULL' not in sql
    assert 'feedback_answer_versions' not in sql and 'feedback_workflow_jobs' not in sql
    params={p.name:p.value for p in client.query.call_args.kwargs['job_config'].query_parameters if hasattr(p,'value')}
    audit=json.loads(params['event_payload'])
    assert audit['revision']==4 and audit['revision_changed'] is False
    if 'user_verdict' in changes:
        context=json.loads(params['run_context_json'])
        assert context['answer_user_verdicts']['original:FDB-EDIT']=='Correct'


@pytest.mark.parametrize('field,value', [('question','New question'),('answer','New captured answer'),
    ('expected_behavior','A corrected expected answer'),('language','French'),('follow_up','A substantive new criterion')])
def test_real_input_or_criteria_changes_still_create_guarded_revisions(field,value):
    row=saved_row();repo,client=edit_repo(row)
    with patch.object(repo,'get_my_feedback',return_value={'id':'FDB-EDIT'}):
        repo.update_my_feedback('FDB-EDIT',['owner@example.test'],MyFeedbackUpdate(expected_revision=4,
            expected_updated_at=row['updated_at'],**{field:value}),'owner@example.test')
    sql=client.query.call_args.args[0]
    assert 'revision = @next_revision' in sql and 'latest_published_attempt_id = NULL' in sql
    assert 'feedback_answer_versions' in sql and 'feedback_workflow_jobs' in sql
    params={p.name:p.value for p in client.query.call_args.kwargs['job_config'].query_parameters if hasattr(p,'value')}
    assert params['next_revision']==5


def test_sending_unchanged_values_does_not_create_versions_or_clear_results():
    row={**saved_row(),'user_verdict':'Incorrect'};repo,client=edit_repo(row)
    with patch.object(repo,'get_my_feedback',return_value={'id':'FDB-EDIT','revision':4}):
        result=repo.update_my_feedback('FDB-EDIT',['owner@example.test'],MyFeedbackUpdate(
            expected_revision=4,question='  Original question  ',user_verdict='Incorrect'),'owner@example.test')
    assert result['revision']==4 and client.query.call_count==1


def test_stale_metadata_edit_is_rejected_even_when_input_revision_has_not_changed():
    repo,client=edit_repo(saved_row())
    with pytest.raises(ValueError,match='changed while you were editing'):
        repo.update_my_feedback('FDB-EDIT',['owner@example.test'],MyFeedbackUpdate(expected_revision=4,
            expected_updated_at='2026-10-13T00:00:00Z',user_verdict='Correct'),'owner@example.test')
    assert client.query.call_count==1


def test_metadata_edits_from_an_old_client_without_an_edit_version_fail_safely():
    repo,client=edit_repo(saved_row())
    with pytest.raises(ValueError,match='edit version'):
        repo.update_my_feedback('FDB-EDIT',['owner@example.test'],MyFeedbackUpdate(expected_revision=4,
            user_verdict='Correct'),'owner@example.test')
    assert client.query.call_count==1


def test_equivalent_edit_timestamps_accept_iso_and_bigquery_formats():
    value = datetime(2026, 10, 14, tzinfo=timezone.utc)
    assert timestamp('2026-10-14 00:00:00+00:00') == timestamp('2026-10-14T05:30:00+05:30') == value
    assert timestamp('2026-10-14T00:00:00Z') == timestamp(value) == value


def test_metadata_write_rechecks_timestamp_atomically_after_its_initial_read():
    repo, client = edit_repo(saved_row())
    read = Mock(); read.result.return_value = [saved_row()]
    changed = Mock(); changed.result.side_effect = RuntimeError('Submission changed or closed during editing')
    client.query.side_effect = [read, changed]
    with pytest.raises(ValueError, match='changed or its review closed'):
        repo.update_my_feedback('FDB-EDIT', ['owner@example.test'], MyFeedbackUpdate(expected_revision=4,
            expected_updated_at=saved_row()['updated_at'], user_verdict='Correct'), 'owner@example.test')
    sql = client.query.call_args.args[0]
    assert 'IS NOT DISTINCT FROM @expected_updated_at' in sql
    assert sql.index('ASSERT @@row_count=1') < sql.index('INSERT INTO')


def test_only_normalized_actual_changes_are_classified_as_new_inputs():
    row = {**saved_row(), 'user_verdict': 'Incorrect'}
    context = {'follow_up': None, 'environment_id': 'neo-nonprod'}
    assert meaningful_updates(row, context, {'question': ' Original question ', 'follow_up': '',
        'expected_behavior': 'Expected rule', 'environment_id': 'neo-nonprod', 'user_verdict': None}) == {}


def test_environment_and_agent_context_remain_revision_sensitive():
    assert {'environment','environment_id','agent_id','agent_version','run_id','conversation_id'} <= REVISION_FIELDS
    assert 'user_verdict' not in REVISION_FIELDS and 'impact' not in REVISION_FIELDS


def test_current_answer_verdict_can_be_explicitly_corrected_without_changing_machine_assessments():
    repo=BigQueryRepository(client=Mock())
    owned={'id':'FDB-EDIT','revision':4,'environment':'prod','environmentId':'neo-prod','publicStatus':'In review'}
    job={'id':'JOB-SAVED','feedback_id':'FDB-EDIT','revision':4,'kind':'retest','status':'completed',
        'environment':'prod','target_id':'neo-prod','confirmation':'still_incorrect','result_json':'{"assessment":"still_incorrect","reason":"Saved AI reasoning"}'}
    with patch.object(repo,'get_my_feedback',return_value=owned),patch.object(repo,'get_feedback_job',return_value=job),\
            patch.object(repo,'get_version',return_value={'answer':'Saved answer'}),\
            patch.object(repo,'latest_confirmable_retest',return_value='JOB-SAVED'),\
            patch.object(repo,'workflow_query')as query,patch.object(repo,'_insert_event'),patch.object(repo,'enqueue_feedback_job')as enqueue:
        repo.confirm_retest('FDB-EDIT','JOB-SAVED',['owner@example.test'],'owner@example.test',
            AnswerConfirmation(verdict='fixed',expected_confirmation='still_incorrect'))
    sql,params=query.call_args.args
    assert '@previous_confirmation' in sql and 'result_json =' not in sql and 'feedback_rca_versions' not in sql
    values={p.name:p.value for p in params if hasattr(p,'value')}
    assert values['previous_confirmation']=='still_incorrect' and values['verdict']=='fixed'
    assert json.loads(values['confirmation_payload'])['previous_verdict']=='still_incorrect'
    enqueue.assert_not_called()


def test_verdict_correction_requires_the_explicit_previous_value_to_prevent_stale_overwrites():
    repo=BigQueryRepository(client=Mock())
    owned={'revision':4,'environment':'prod','environmentId':'neo-prod'}
    job={'id':'JOB-SAVED','feedback_id':'FDB-EDIT','revision':4,'kind':'retest','status':'completed',
        'environment':'prod','target_id':'neo-prod','confirmation':'still_incorrect'}
    with patch.object(repo,'get_my_feedback',return_value=owned),patch.object(repo,'get_feedback_job',return_value=job),\
            patch.object(repo,'get_version',return_value={'answer':'Saved answer'}),\
            patch.object(repo,'latest_confirmable_retest',return_value='JOB-SAVED'),patch.object(repo,'workflow_query')as query:
        with pytest.raises(ValueError,match='already has a response'):
            repo.confirm_retest('FDB-EDIT','JOB-SAVED',['owner@example.test'],'owner@example.test',AnswerConfirmation(verdict='fixed'))
    query.assert_not_called()


def test_a_changed_confirmation_between_read_and_write_rolls_back_the_whole_transaction():
    repo = BigQueryRepository(client=Mock())
    job = {'id': 'JOB-SAVED', 'feedback_id': 'FDB-EDIT', 'revision': 4, 'kind': 'retest', 'status': 'completed',
        'environment': 'prod', 'target_id': 'neo-prod', 'confirmation': 'fixed'}
    with patch.object(repo, 'get_my_feedback', return_value={'revision': 4, 'environment': 'prod', 'environmentId': 'neo-prod'}), \
            patch.object(repo, 'get_feedback_job', return_value=job), patch.object(repo, 'get_version', return_value={'answer': 'Saved answer'}), \
            patch.object(repo, 'latest_confirmable_retest', return_value='JOB-SAVED'), \
            patch.object(repo, 'workflow_query', side_effect=RuntimeError('An answer response is already recorded')) as query, \
            patch.object(repo, '_insert_event') as event, patch.object(repo, 'enqueue_feedback_job') as enqueue:
        with pytest.raises(ValueError, match='Refresh history'):
            repo.confirm_retest('FDB-EDIT', 'JOB-SAVED', ['owner@example.test'], 'owner@example.test',
                AnswerConfirmation(verdict='still_incorrect', expected_confirmation='fixed', comment='A remaining defect.'))
    sql = query.call_args.args[0]
    assert 'BEGIN TRANSACTION' in sql and 'confirmation=@previous_confirmation' in sql
    assert sql.index("ASSERT @@row_count = 1 AS 'An answer response is already recorded'") < sql.index('INSERT INTO')
    event.assert_not_called(); enqueue.assert_not_called()


def test_history_projects_a_user_verdict_for_each_answer_without_relabelling_the_ai_result():
    client=Mock();repo=BigQueryRepository(client=client)
    job={'id':'JOB-SAVED','feedback_id':'FDB-EDIT','kind':'retest','status':'completed','revision':4,
        'environment':'prod','target_id':'neo-prod','confirmation':'fixed','result_json':'{"assessment":"still_incorrect","reason":"Saved AI reasoning"}'}
    answer={'id':'answer:JOB-SAVED','attempt_id':'JOB-SAVED','payload_json':'{"kind":"retest","answer":"Saved answer","revision":4}'}
    capture={'id':'submission:FDB-EDIT:r4','payload_json':'{"kind":"submission_edit","answer":"Captured response","userVerdict":"Incorrect"}'}
    context={'revision':4,'environmentId':'neo-prod','environmentKind':'prod','submissionAnswerId':'submission:FDB-EDIT:r4',
        'submittedUserVerdict':'Correct','submittedVerdictsJson':'{"submission:FDB-EDIT:r4":"Correct"}'}
    client.query.return_value.result.return_value=[{'allowed_count':1,'review_context_json':json.dumps(context),
        'latest_confirmable_id':'JOB-SAVED','jobs_json':[json.dumps(job)],'answers_json':[json.dumps(capture),json.dumps(answer)]}]
    history=repo.feedback_history('FDB-EDIT',['owner@example.test'])
    assert all(row['userVerdict']=='Correct'for row in history['answers'])
    assert history['attempts'][0]['assessment']=='still_incorrect'and history['attempts'][0]['reason']=='Saved AI reasoning'


def test_source_verdict_correction_never_fills_an_unrecorded_historical_original_verdict():
    client = Mock(); repo = BigQueryRepository(client=client)
    original = {'id': 'original:FDB-EDIT', 'payload_json': json.dumps({'kind': 'original', 'answer': 'Original capture', 'revision': 1})}
    previous = {'id': 'submission:FDB-EDIT:r2', 'payload_json': json.dumps({'kind': 'submission_edit', 'answer': 'Previous capture', 'userVerdict': 'Incorrect', 'revision': 2})}
    current = {'id': 'submission:FDB-EDIT:r3', 'payload_json': json.dumps({'kind': 'submission_edit', 'answer': 'Current capture', 'userVerdict': 'Incorrect', 'revision': 3})}
    context = {'revision': 3, 'environmentId': 'neo-prod', 'environmentKind': 'prod',
        'submissionAnswerId': current['id'], 'submittedUserVerdict': 'Correct',
        'submittedVerdictsJson': json.dumps({current['id']: 'Correct'})}
    client.query.return_value.result.return_value = [{'allowed_count': 1, 'review_context_json': json.dumps(context),
        'answers_json': [json.dumps(row) for row in (original, previous, current)]}]
    history = repo.feedback_history('FDB-EDIT', ['owner@example.test'])
    verdicts = {answer['id']: answer.get('userVerdict') for answer in history['answers']}
    assert verdicts == {original['id']: None, previous['id']: 'Incorrect', current['id']: 'Correct'}
    assert json.loads(current['payload_json'])['userVerdict'] == 'Incorrect'
    assert not any(word in client.query.call_args.args[0] for word in ('UPDATE ', 'INSERT ', 'MERGE '))
