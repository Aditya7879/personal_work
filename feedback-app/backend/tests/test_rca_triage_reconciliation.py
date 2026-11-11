from datetime import datetime, timezone
import json
from unittest.mock import Mock

import pytest

from app.bigquery import BigQueryRepository
from scripts.reconcile_rca_triage import apply_reconciliation, candidate_sql, preview


def approved_preview():
    return {'version':1,'action':'reconcile_current_source_rca_triage','cutoff':'2026-10-28T00:00:00+00:00','candidateCount':2,
        'items':[{'feedbackId':f'FDB-{index}','revision':1,'answerId':f'original:FDB-{index}',
            'diagnosisId':f'rca:JOB-{index}','rowFingerprint':str(index),'before':{'state':'Submitted','public_status':'Received'}} for index in (1,2)]}


def test_preview_is_read_only_scoped_and_preserves_exact_unicode_with_native_json():
    repo = BigQueryRepository(client=Mock()); repo.workflow_query = Mock(return_value=[{'feedback_id':'FDB-1','revision':1,
        'answer_id':'original:FDB-1','diagnosis_id':'rca:JOB-1','row_fingerprint':123,'before_json':'{"state":"Submitted"}'}])
    result = preview(repo,cutoff=datetime(2026,10,28,tzinfo=timezone.utc))
    assert result['candidateCount'] == 1 and result['modelCalls'] == 0 and result['databaseWrites'] == 0
    assert result['items'][0]['rowFingerprint'] == '123'
    sql = repo.workflow_query.call_args.args[0]
    assert 'SAFE.PARSE_JSON(a.payload_json)' in sql and 'SAFE.PARSE_JSON(j.payload_json)' in sql
    assert 'COALESCE(ARRAY_LENGTH(@feedback_ids),0)=0' in sql
    assert "JSON_VALUE(SAFE.PARSE_JSON(a.payload_json),'$.answer'),'')=COALESCE(f.answer,'')" in sql
    assert "j.kind IN ('enrich','rca')" in sql and "('original','submission_edit')" in sql
    assert 'ROW_NUMBER()' in sql and 'position=1' in sql and "job_status='completed'" in sql
    assert 'REGEXP_REPLACE' not in sql  # No fuzzy text matching or answer rewrite.


def test_exact_approved_repair_is_atomic_audited_fenced_and_never_touches_versions_or_jobs():
    client = Mock(); client.query.return_value.result.return_value = [{'changed':2}]
    repo = BigQueryRepository(client=client)
    result = apply_reconciliation(repo,approved_preview(),'reviewer@company.example',2)
    assert result['updated'] == 2 and result['modelCalls'] == 0 and result['jobsRetried'] == 0
    sql = client.query.call_args.args[0]
    assert 'BEGIN TRANSACTION' in sql and 'COMMIT TRANSACTION' in sql
    assert 'RCA_TRIAGE_PREVIEW_STALE' in sql and 'RCA_TRIAGE_CONCURRENT_CHANGE' in sql
    assert 'REVIEWER_REQUIRED' in sql and "'rca_auto_triaged'" in sql
    assert 'FARM_FINGERPRINT(TO_JSON_STRING(f))=c.row_fingerprint' in sql
    assert "SET state='Triaged',public_status='In review'" in sql
    for forbidden in ['SET answer=', 'SET question=', 'SET revision=', 'confirmed_rca=', 'expected_behavior_verified=',
        'UPDATE `' + repo.workflow_table('feedback_workflow_jobs'), 'UPDATE `' + repo.workflow_table('feedback_answer_versions'),
        'UPDATE `' + repo.workflow_table('feedback_rca_versions')]:
        assert forbidden not in sql
    assert 'reviewer@company.example' not in sql and 'FDB-1' not in sql
    assert client.query.call_args.kwargs['job_retry'] is None
    client.query.return_value.result.assert_called_once_with(job_retry=None)


@pytest.mark.parametrize('change', [{'version':2}, {'items':[]}, {'action':'unrelated'}, {'items':[approved_preview()['items'][0]]}])
def test_unapproved_or_expanded_selection_is_rejected_before_a_write(change):
    client = Mock(); repo = BigQueryRepository(client=client)
    with pytest.raises(ValueError): apply_reconciliation(repo,{**approved_preview(),**change},'reviewer@company.example',2)
    client.query.assert_not_called()
