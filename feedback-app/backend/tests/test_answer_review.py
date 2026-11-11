import json
from unittest.mock import Mock, patch

import pytest

from app.answer_review import review_summary
from app.bigquery import BigQueryRepository
from app.feedback_ownership import owner_scope
from test_main_environment import source_row


CONTEXT = {'revision': 2, 'environmentId': 'neo-prod', 'environmentKind': 'prod', 'environmentLabel': 'Production'}
COMPLETED = {'id': 'JOB-CURRENT', 'revision': 2, 'environmentId': 'neo-prod', 'environmentKind': 'prod',
    'status': 'completed', 'confirmation': None}


def test_current_completed_saved_answer_is_available_even_without_a_successful_rca_verdict():
    value = review_summary(CONTEXT, COMPLETED, COMPLETED)
    assert value == {**CONTEXT, 'state': 'available', 'attemptId': 'JOB-CURRENT',
        'answerId': 'answer:JOB-CURRENT', 'confirmation': None, 'displayAnswerId': 'answer:JOB-CURRENT',
        'displayAnswerRevision': 2, 'userVerdict': None}


@pytest.mark.parametrize('confirmation', ['fixed', 'partially_fixed', 'still_incorrect'])
def test_recorded_response_cannot_be_submitted_again_from_the_verdict_badge(confirmation):
    value = review_summary(CONTEXT, {**COMPLETED, 'confirmation': confirmation}, COMPLETED)
    assert value['state'] == 'already_responded' and value['confirmation'] == confirmation


@pytest.mark.parametrize(('latest', 'state'), [
    (None, 'no_fresh_answer'),
    ({**COMPLETED, 'status': 'running'}, 'processing'),
    ({**COMPLETED, 'status': 'queued'}, 'processing'),
    ({**COMPLETED, 'revision': 1}, 'outdated_revision'),
    ({**COMPLETED, 'environmentId': 'another-prod'}, 'different_environment'),
    ({**COMPLETED, 'environmentKind': 'nonprod'}, 'different_environment'),
    ({**COMPLETED, 'status': 'failed'}, 'unavailable'),
    ({**COMPLETED, 'status': 'cancelled'}, 'unavailable'),
    (COMPLETED, 'no_fresh_answer'),  # No eligible saved answer: completed status alone is not enough.
])
def test_missing_or_ineligible_answer_has_an_explanation_not_an_edit_permission(latest, state):
    value = review_summary(CONTEXT, None, latest)
    assert value['state'] == state and value['attemptId'] is None


def test_a_new_running_retest_does_not_hide_the_latest_completed_current_result():
    value = review_summary(CONTEXT, COMPLETED, {**COMPLETED, 'id': 'JOB-NEW', 'status': 'running'})
    assert value['state'] == 'available' and value['attemptId'] == 'JOB-CURRENT'


def test_unknown_main_environment_is_not_guessed_from_a_visible_answer():
    value = review_summary({**CONTEXT, 'environmentKind': 'unknown'}, COMPLETED, COMPLETED)
    assert value['state'] == 'environment_unknown' and value['attemptId'] is None


def test_review_page_query_is_batched_owner_scoped_exact_revision_and_environment_and_read_only():
    repo = BigQueryRepository(client=Mock())
    row = {'feedback_id': 'FDB-A', 'revision': 2, 'environment_id': 'neo-prod', 'environment_kind': 'prod',
        'environment_label': 'Production', 'completed_json': json.dumps(COMPLETED), 'latest_json': json.dumps(COMPLETED)}
    with patch.object(repo, 'workflow_query', return_value=[row]) as query:
        value = repo.feedback_answer_reviews(['FDB-A', 'FDB-B'], ['owner@example.test'])
    query.assert_called_once()
    sql, params = query.call_args.args
    assert owner_scope(repo, 'f') in sql and 'f.feedback_id IN UNNEST(@ids)' in sql
    assert repo._same_environment('c', 'j') in sql and 'j.revision=c.revision' in sql
    assert "status='completed' AND current_input AND current_environment AND saved_answer" in sql
    assert "NULLIF(TRIM(JSON_VALUE(av.payload_json,'$.answer')),'') IS NOT NULL" in sql
    assert 'rca_versions' not in sql  # RCA success is not a correctness/confirmation prerequisite.
    assert not any(word in sql for word in ('UPDATE ', 'INSERT ', 'DELETE ', 'MERGE '))
    assert next(param.values for param in params if param.name == 'ids') == ['FDB-A', 'FDB-B']
    assert value['FDB-A']['state'] == 'available' and 'FDB-B' not in value


def test_empty_page_never_reads_or_leaks_another_reporters_review():
    repo = BigQueryRepository(client=Mock())
    with patch.object(repo, 'workflow_query') as query:
        assert repo.feedback_answer_reviews([], ['owner@example.test']) == {}
    query.assert_not_called()


def test_reporter_list_adds_one_small_review_summary_for_the_page_without_full_history_reads():
    repo = BigQueryRepository(client=Mock())
    records = [repo._record({**source_row(), 'feedback_id': fid}) for fid in ['FDB-A', 'FDB-B']]
    with patch.object(repo, 'list_feedback', return_value=(records, 2)), \
            patch.object(repo, 'feedback_answer_reviews', return_value={'FDB-A': review_summary(CONTEXT, COMPLETED, COMPLETED)}) as reviews, \
            patch.object(repo, 'feedback_history') as history:
        rows, total = repo.list_my_feedback(['owner@example.test'])
    reviews.assert_called_once_with(['FDB-A', 'FDB-B'], ['owner@example.test'])
    history.assert_not_called()
    assert total == 2 and rows[0]['answerReview']['state'] == 'available'
    assert rows[1]['answerReview'] is None and rows[0]['question'] is None


def test_fresh_history_returns_its_own_current_review_context_not_a_stale_drawer_context():
    client = Mock()
    job = {'id': 'JOB-CURRENT', 'feedback_id': 'FDB-A', 'kind': 'retest', 'status': 'completed',
        'revision': 2, 'environment': 'prod', 'target_id': 'neo-prod'}
    answer = {'id': 'answer:JOB-CURRENT', 'attempt_id': 'JOB-CURRENT',
        'payload_json': json.dumps({'kind': 'retest', 'answer': 'Saved current answer', 'environmentId': 'neo-prod', 'revision': 2})}
    client.query.return_value.result.return_value = [{'allowed_count': 1, 'review_context_json': json.dumps(CONTEXT),
        'latest_confirmable_id': 'JOB-CURRENT', 'jobs_json': [json.dumps(job)], 'answers_json': [json.dumps(answer)]}]
    repo = BigQueryRepository(client=client)
    value = repo.feedback_history('FDB-A', ['owner@example.test'])
    assert value['answerReview']['state'] == 'available'
    assert value['answerReview']['revision'] == 2 and value['answerReview']['environmentId'] == 'neo-prod'
    sql = client.query.call_args.args[0]
    assert 'v.attempt_id IN (SELECT id FROM confirmable_job)' in sql  # Current review survives the recent-history limit.
    assert owner_scope(repo, 'f') in sql
