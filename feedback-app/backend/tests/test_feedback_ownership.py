import hashlib
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from app.bigquery import BigQueryRepository
from app.config import settings
from app.feedback_ownership import ensure_ownership_tables, owner_scope
from app.models import AnswerConfirmation, MyFeedbackUpdate
from scripts.link_feedback_owners import apply_links, build_preview, validated_approval
from test_reporter_edit import saved_row


def approval():
    value = {'mode': 'user_reviewed_legacy_ownership_links',
        'approvedLinks': [{'feedback_id': 'FDB-EDIT', 'agent_id': settings.default_agent_id,
            'source_reporter': 'legacy owner', 'owner_email': 'owner@company.example',
            'verification_method': 'user_supplied_owner_email'}], 'newReporterEmails': ['owner@company.example']}
    return {**value, 'approvalHash': hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()}


@pytest.fixture
def company(monkeypatch):
    monkeypatch.setitem(settings.__dict__, 'google_iam_domains', ('company.example',))


def test_link_scope_requires_one_verified_active_exact_record_source_and_agent():
    repo = BigQueryRepository(client=Mock())
    sql = owner_scope(repo, 'f')
    assert 'LOWER(TRIM(f.reporter)) IN UNNEST(@reporters)' in sql
    assert 'o.owner_email IN UNNEST(@reporters)' in sql
    assert 'o.feedback_id=f.feedback_id AND o.agent_id=f.agent_id' in sql
    assert 'o.source_reporter=LOWER(TRIM(f.reporter))' in sql
    assert 'COUNT(*) OVER(PARTITION BY feedback_id)' in sql and 'o.owner_link_count=1' in sql
    assert 'o.active IS TRUE AND o.verified IS TRUE' in sql
    assert "NULLIF(TRIM(f.reporter), '') IS NOT NULL" in sql
    assert "STRPOS(f.reporter, '@')=0" in sql
    assert 'feedback_owner_links' in sql


def test_internal_sql_identifiers_cannot_be_supplied_as_arbitrary_text():
    repo = BigQueryRepository(client=Mock())
    for alias, parameter in [('f; DELETE', 'reporters'), ('f', 'user) OR TRUE')]:
        with pytest.raises(ValueError):
            owner_scope(repo, alias, parameter=parameter)


def test_storage_initialization_only_adds_link_and_identity_audit_tables():
    client = Mock()
    ensure_ownership_tables(client, 'project.dataset')
    assert [call.args[0].table_id for call in client.create_table.call_args_list] == ['feedback_owner_links', 'feedback_owner_events']
    assert all(call.kwargs == {'exists_ok': True} for call in client.create_table.call_args_list)
    client.query.assert_not_called()


def test_count_and_page_share_the_full_owner_guard_and_keep_names_in_the_source():
    client = Mock(); count = Mock(); count.result.return_value = [SimpleNamespace(total=1)]
    row = {**saved_row(), 'reporter': 'Legacy Owner'}
    page = Mock(); page.result.return_value = [row]
    client.query.side_effect = [count, page]
    repo = BigQueryRepository(client=client)
    records, total = repo.list_feedback(reporter=['owner@company.example'])
    assert total == 1 and records[0].reporter == 'Legacy Owner'
    assert row['reporter'] == 'Legacy Owner'
    assert all(owner_scope(repo, 'f') in call.args[0] for call in client.query.call_args_list)
    params = client.query.call_args.kwargs['job_config'].query_parameters
    assert next(param for param in params if param.name == 'reporters').values == ['owner@company.example']


def test_details_and_edit_read_write_guards_use_the_same_verified_link_without_editing_reporter():
    client = Mock(); client.query.return_value.result.return_value = []
    repo = BigQueryRepository(client=client)
    repo.get_my_feedback('FDB-EDIT', ['owner@company.example'])
    assert owner_scope(repo, 'f') in client.query.call_args.args[0]
    first = Mock(); first.result.return_value = [{**saved_row(), 'reporter': 'Legacy Owner'}]
    second = Mock(); second.result.return_value = []
    client.query.side_effect = [first, second]
    with patch.object(repo, 'get_my_feedback', return_value={'id': 'FDB-EDIT'}):
        repo.update_my_feedback('FDB-EDIT', ['owner@company.example'], MyFeedbackUpdate(expected_revision=4,
            expected_updated_at=saved_row()['updated_at'], title='Corrected title'), 'owner@company.example')
    for call in client.query.call_args_list[-2:]:
        assert owner_scope(repo, 'f') in call.args[0]
    sql = client.query.call_args.args[0]
    assert 'reporter =' not in sql and 'owner_email =' not in sql
    assert 'COALESCE(revision,1)=@expected_revision' in sql and 'IS NOT DISTINCT FROM @expected_updated_at' in sql


def test_history_and_notification_read_and_read_marker_all_use_owner_links():
    client = Mock(); client.query.return_value.result.return_value = [{'allowed_count': 1}]
    repo = BigQueryRepository(client=client)
    repo.feedback_history('FDB-EDIT', ['owner@company.example'])
    assert owner_scope(repo, 'f') in client.query.call_args.args[0]
    client.query.return_value.result.return_value = []
    repo.list_notifications(['owner@company.example'])
    assert owner_scope(repo, 'f') in client.query.call_args.args[0]
    repo.mark_notification_read('notification', ['owner@company.example'])
    assert owner_scope(repo, 'f') in client.query.call_args.args[0]


def test_confirmation_transaction_links_owner_but_keeps_all_existing_resolution_fences():
    repo = BigQueryRepository(client=Mock())
    owned = {'revision': 1, 'environment': 'nonprod', 'environmentId': 'neo-nonprod'}
    job = {'id': 'JOB-1', 'feedback_id': 'FDB-EDIT', 'kind': 'retest', 'status': 'completed', 'revision': 1,
        'environment': 'nonprod', 'target_id': 'neo-nonprod', 'confirmation': None}
    with patch.object(repo, 'get_my_feedback', return_value=owned), patch.object(repo, 'get_feedback_job', return_value=job), \
            patch.object(repo, 'latest_confirmable_retest', return_value='JOB-1'), patch.object(repo, 'get_version', return_value={'answer': 'Saved answer'}), \
            patch.object(repo, 'workflow_query', return_value=[]) as query, patch.object(repo, '_insert_event'):
        repo.confirm_retest('FDB-EDIT', 'JOB-1', ['owner@company.example'], 'owner@company.example', AnswerConfirmation(verdict='fixed'))
    sql = query.call_args.args[0]
    assert owner_scope(repo, 'f') in sql
    assert "current_job.status = 'completed'" in sql and 'current_job.revision = @revision' in sql
    assert 'NOT EXISTS' in sql and 'newer' in sql and 'ASSERT @@row_count = 1' in sql
    assert repo._same_environment('owner_context', 'current_job') in sql
    assert "confirmation IS NULL" in sql


def test_promotion_main_environment_makes_only_the_latest_exact_target_confirmable_for_the_owner():
    repo = BigQueryRepository(client=Mock())
    owned = {'revision': 1, 'environment': 'nonprod', 'environmentId': 'neo-nonprod',
        'mainEnvironmentKind': 'prod', 'mainEnvironmentId': 'neo-prod'}
    job = {'id': 'JOB-PROD', 'feedback_id': 'FDB-EDIT', 'kind': 'retest', 'status': 'completed', 'revision': 1,
        'environment': 'prod', 'target_id': 'neo-prod', 'confirmation': None}
    with patch.object(repo, 'get_my_feedback', return_value=owned), patch.object(repo, 'get_feedback_job', return_value=job), \
            patch.object(repo, 'latest_confirmable_retest', return_value='JOB-PROD') as latest, \
            patch.object(repo, 'get_version', return_value={'answer': 'Saved Production answer'}), \
            patch.object(repo, 'workflow_query', return_value=[]) as query, patch.object(repo, '_insert_event'):
        result = repo.confirm_retest('FDB-EDIT', 'JOB-PROD', ['owner@example.test'], 'owner@example.test', AnswerConfirmation(verdict='fixed'))
    assert result == owned
    latest.assert_called_once_with('FDB-EDIT', 1, 'prod')
    sql = query.call_args.args[0]
    assert "current_job.target_id" in sql and "@environment" in sql
    assert repo._current_environment_kind('owner_context') + ' = @environment' in sql
    assert repo._same_environment('owner_context', 'current_job') in sql
    params = query.call_args.args[1]
    assert next(item.value for item in params if item.name == 'environment') == 'prod'
    assert "confirmation IS NULL" in sql and 'ASSERT @@row_count = 1' in sql


def test_unpromoted_feedback_keeps_original_source_as_main_and_rejects_cross_environment_confirmation():
    repo = BigQueryRepository(client=Mock())
    source_only = {'revision': 1, 'environment': 'nonprod', 'environmentId': 'neo-nonprod',
        'mainEnvironmentKind': None, 'mainEnvironmentId': None}
    job = {'id': 'JOB-PROD', 'feedback_id': 'FDB-EDIT', 'kind': 'retest', 'status': 'completed', 'revision': 1,
        'environment': 'prod', 'target_id': 'neo-prod'}
    with patch.object(repo, 'get_my_feedback', return_value=source_only), patch.object(repo, 'get_feedback_job', return_value=job), \
            patch.object(repo, 'workflow_query') as query:
        with pytest.raises(ValueError, match='different'):
            repo.confirm_retest('FDB-EDIT', 'JOB-PROD', ['owner@example.test'], 'owner@example.test', AnswerConfirmation(verdict='fixed'))
    query.assert_not_called()


def test_reviewed_mapping_is_hash_fenced_and_never_guesses_blank_or_email_owners(company):
    value = approval(); assert validated_approval(value) == value
    for field, replacement in [('source_reporter', ''), ('source_reporter', 'other@company.example'), ('owner_email', 'outside@outside.example')]:
        changed = json.loads(json.dumps(value)); changed['approvedLinks'][0][field] = replacement
        changed['approvalHash'] = hashlib.sha256(json.dumps({key:item for key,item in changed.items() if key != 'approvalHash'}, sort_keys=True).encode()).hexdigest()
        with pytest.raises(ValueError): validated_approval(changed)
    value['approvedLinks'][0]['owner_email'] = 'another@company.example'
    with pytest.raises(ValueError, match='changed'): validated_approval(value)


def test_bulk_linking_only_adds_reviewed_links_new_reporters_and_audits(company):
    client = Mock()
    client.query.return_value.result.side_effect = [[{'feedback_id':'FDB-EDIT','agent_id':settings.default_agent_id,'reporter':'Legacy Owner'}],
        [{'email':'reviewer@company.example','role':'reviewer','active':True,'expires_at':None,'fingerprint':123}]]
    preview = build_preview(client, approval())
    assert preview['counts']['links'] == 1 and preview['counts']['newReporters'] == 1
    client.query.return_value.result.side_effect = None
    client.query.return_value.result.return_value = [{'linked':1,'added':1}]
    result = apply_links(client, preview, 'reviewer@company.example', 1, 1)
    assert result['feedbackOrHistoryRowsRewritten'] == 0
    sql = client.query.call_args.args[0]
    assert 'BEGIN TRANSACTION' in sql and 'COMMIT TRANSACTION' in sql
    assert 'OWNERSHIP_SOURCE_CHANGED' in sql and 'OWNERSHIP_REVIEWER_REQUIRED' in sql
    assert 'OWNERSHIP_ACCESS_PREVIEW_STALE' in sql and 'OWNERSHIP_TARGET_ACCESS_INVALID' in sql
    assert 'UPDATE `' + settings.project_id + '.' + settings.dataset + '.feedback_items`' not in sql
    assert 'feedback_workflow_jobs' not in sql and 'feedback_answer_versions' not in sql
    assert client.query.call_args.kwargs['job_retry'] is None
    assert 'owner@company.example' not in sql
