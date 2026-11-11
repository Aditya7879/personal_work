from types import SimpleNamespace
from unittest.mock import Mock, patch

from google.api_core.exceptions import NotFound
import pytest

from app.bigquery import BigQueryRepository
from app.config import settings
from scripts.prepare_main_environment_storage import prepare
from scripts.backfill_promoted_main_environments import METHOD, apply, preview


def source_row():
    return {'feedback_id':'FDB-MAIN','agent_id':settings.default_agent_id,'question':'Original question',
        'answer':'Original captured answer','environment':'nonprod','revision':1,'state':'Triaged','user_verdict':'Incorrect',
        'severity':'High','impact':'High','created_at':'2026-10-14T00:00:00Z','updated_at':'2026-10-14T00:00:00Z',
        'reporter':'Owner@example.test','run_context_json':'{"environment_id":"neo-nonprod","environment_kind":"nonprod","environment_label":"Non-production"}'}


def test_feedback_api_keeps_original_fields_and_exposes_a_separate_main_environment_pointer():
    row={**source_row(),'main_environment_id':'neo-prod','main_environment_kind':'prod','main_environment_label':'Production'}
    record=BigQueryRepository(client=Mock())._record(row)
    assert record.environment=='nonprod' and record.environmentId=='neo-nonprod' and record.environmentLabel=='Non-production'
    assert record.mainEnvironmentId=='neo-prod' and record.mainEnvironmentKind=='prod' and record.mainEnvironmentLabel=='Production'
    assert row['environment']=='nonprod' and row['run_context_json'].find('neo-nonprod')>=0
    public=BigQueryRepository._my_feedback_record(record,[])
    assert public['environmentId']=='neo-nonprod' and public['mainEnvironmentId']=='neo-prod'


def test_additive_main_environment_storage_initializer_adds_only_the_new_empty_pointer_table():
    client=Mock();client.get_table.side_effect=[NotFound('missing'),Mock(schema=[
        SimpleNamespace(name=name,field_type=kind) for name,kind in [
            ('feedback_id','STRING'),('agent_id','STRING'),('environment_id','STRING'),('environment_kind','STRING'),
            ('environment_label','STRING'),('source_environment_id','STRING'),('promotion_batch_id','STRING'),
            ('revision','INT64'),('selected_by','STRING'),('created_at','TIMESTAMP'),('updated_at','TIMESTAMP')]])]
    client.query.return_value.result.return_value=[{'n':0}]
    with patch.dict(settings.__dict__,{'project_id':'oa-apmena-techsandbox-ap-dv','dataset':'agent_quality'}):
        result=prepare(client)
    assert result['created'] and result['rowsBeforeBackfill']==0
    assert len(client.create_table.call_args_list)==1
    assert client.create_table.call_args.args[0].table_id=='feedback_main_environments'
    assert client.query.call_count==1 and 'feedback_items'not in client.query.call_args.args[0]


def test_feedback_listing_joins_current_main_environment_but_never_mutates_the_source_or_owner_filter():
    source=source_row();joined={**source,'main_environment_id':'neo-prod','main_environment_kind':'prod','main_environment_label':'Production'}
    client=Mock();count=Mock();count.result.return_value=[SimpleNamespace(total=1)]
    page=Mock();page.result.return_value=[joined]
    client.query.side_effect=[count,page]
    repo=BigQueryRepository(client=client)
    with patch.object(repo,'main_environment_results',return_value={}):
        records,total=repo.list_feedback(reporter=['owner@example.test'],page_size=20)
    assert total==1 and records[0].environmentId=='neo-nonprod' and records[0].mainEnvironmentId=='neo-prod'
    assert joined['run_context_json']==source['run_context_json'] and joined['environment']=='nonprod'
    sql=client.query.call_args.args[0]
    assert 'FROM `'+repo.dataset_ref+'.feedback_main_environments`) m' in sql
    assert 'm.main_feedback_id=f.feedback_id AND m.main_agent_id=f.agent_id' in sql
    assert "LOWER(TRIM(f.reporter)) IN UNNEST(@reporters)" in sql


def test_all_environment_rich_result_uses_only_the_main_exact_target_for_each_feedback():
    repo=BigQueryRepository(client=Mock())
    records=[repo._record({**source_row(),'main_environment_id':'neo-prod','main_environment_kind':'prod','main_environment_label':'Production'})]
    result={'feedback_id':'FDB-MAIN','id':'JOB-PROD','kind':'retest','status':'completed','target_id':'neo-prod','environment':'prod',
        'rca_category':'reasoning_error','rca_defect':'production-only diagnosis','result_json':'{}','target_snapshot_json':'{}'}
    job=Mock();job.result.return_value=[result];repo.client.query.return_value=job
    mapped=repo.main_environment_results(records)
    assert mapped['FDB-MAIN']['environmentId']=='neo-prod' and mapped['FDB-MAIN']['rcaCategory']=='reasoning_error'
    sql=repo.client.query.call_args.args[0]
    assert 'JOIN UNNEST(@selections) selected ON selected.feedback_id=j.feedback_id AND selected.environment_id=j.target_id' in sql
    assert 'selected.revision=j.revision' in sql
    selection=repo.client.query.call_args.kwargs['job_config'].query_parameters[0].values[0].struct_values
    assert selection['environment_id']=='neo-prod' and selection['revision']==1


def test_exact_environment_filter_keeps_original_linked_membership_and_adds_main_pointer_scope():
    client=Mock();count=Mock();count.result.return_value=[SimpleNamespace(total=1)]
    page=Mock();page.result.return_value=[{**source_row(),'main_environment_id':'neo-prod','main_environment_kind':'prod','main_environment_label':'Production'}]
    client.query.side_effect=[count,page]
    repo=BigQueryRepository(client=client)
    with patch.object(repo,'get_agent_environment',return_value={'id':'neo-prod','agent_id':settings.default_agent_id,'kind':'prod','name':'Production'}),patch.object(repo,'environment_results',return_value={}):
        records,total=repo.list_feedback(environment_id='neo-prod')
    assert total==1 and records[0].environmentId=='neo-nonprod' and records[0].mainEnvironmentId=='neo-prod'
    sql=client.query.call_args.args[0]
    assert '.feedback_main_environments` m' in sql and 'm.environment_id=@environment_id' in sql
    assert "j.kind='retest' AND j.target_id=@environment_id" in sql


def test_promotion_transaction_sets_the_exact_target_as_main_and_appends_an_audit_without_feedback_rewrite():
    from test_agent_environments import BATCH,ENV,record
    import hashlib
    from app.models import PromotionCreate
    repo=BigQueryRepository(client=Mock())
    original=record(environmentId='neo-nonprod');before=original.model_dump()
    selection=PromotionCreate(feedback_ids=[original.id],target_id='neo-prod',idempotency_key='promote-main-env-1',selection_token='a'*64)
    batch={**BATCH,'id':'PROM-MAIN','requestHash':hashlib.sha256(selection.model_dump_json().encode()).hexdigest(),'requestedBy':'reviewer@example.test'}
    with patch.object(repo,'ensure_environment_schema'),patch.object(repo,'get_promotion',side_effect=[None,batch]),\
         patch.object(repo,'select_promotion_records',return_value=([original],selection.selection_token)),\
         patch.object(repo,'_promotion_baselines',return_value={}),patch.object(repo,'workflow_query')as query:
        repo.create_promotion(selection,{**ENV,'id':'neo-prod','kind':'prod','name':'Production'},'reviewer@example.test')
    sql,parameters=query.call_args.args
    assert 'MERGE `'+repo.dataset_ref+'.feedback_main_environments`'in sql
    assert "'main_environment_selected'"in sql and 'Main environment selection failed'in sql
    assert 'promotion-main-environment' not in sql  # audit IDs are deterministic batch-main-environment IDs.
    assert 'main-environment:' in sql and 'main_environment_id' in sql
    assert 'UPDATE `'+repo.feedback_ref+'`'not in sql and 'DELETE FROM `'+repo.feedback_ref+'`'not in sql
    assert next(value.value for value in parameters if value.name=='target')=='neo-prod'
    assert next(value.value for value in parameters if value.name=='environment')=='prod'
    assert next(value.value for value in parameters if value.name=='target_kind')=='prod'
    assert original.model_dump()==before


def test_same_environment_uses_main_pointer_when_present_and_source_environment_as_fallback():
    repo=BigQueryRepository(client=Mock())
    sql=repo._same_environment('f','j')
    assert 'f.main_environment_kind' in sql and 'f.main_environment_id' in sql
    assert "JSON_VALUE(f.run_context_json,'$.environment_id')" in sql
    assert "COALESCE(j.target_id,CASE" in sql


def test_backfill_preview_uses_latest_explicit_promotion_per_feedback_without_owner_labels():
    client=Mock();client.query.return_value.result.side_effect=[
        [{'feedback_id':'FDB-A','agent_id':settings.default_agent_id,'environment_id':'neo-prod','environment_kind':'prod',
          'environment_label':'Production','source_environment_id':'neo-nonprod','promotion_batch_id':'PROM-NEW','selected_by':'reviewer@example.test','revision':1}],
        []]
    value=preview(client)
    assert value['method']==METHOD and value['counts']['latestPromotedFeedback']==1
    assert value['rows'][0]['promotion_batch_id']=='PROM-NEW' and value['rows'][0]['environment_id']=='neo-prod'
    assert 'reporter' not in value['rows'][0] and value['feedbackOrAnswerOrRcaRowsRewritten']==0
    assert 'ROW_NUMBER() OVER(PARTITION BY j.feedback_id ORDER BY b.created_at DESC' in client.query.call_args_list[0].args[0]
    assert 'feedback_items' in client.query.call_args_list[0].args[0]
    assert 'feedback_main_environments' in client.query.call_args_list[1].args[0]


def test_backfill_is_one_reviewed_pointer_merge_with_append_only_provenance_and_no_feedback_updates():
    candidate={'feedback_id':'FDB-A','agent_id':settings.default_agent_id,'environment_id':'neo-prod','environment_kind':'prod',
        'environment_label':'Production','source_environment_id':'neo-nonprod','promotion_batch_id':'PROM-NEW',
        'selected_by':'original-reviewer@example.test','revision':1}
    source=Mock();source.query.return_value.result.side_effect=[[candidate],[]]
    reviewed=preview(source);client=Mock();client.query.return_value.result.return_value=[{'updated':1}]
    result=apply(client,reviewed,'dhruv.chawla@loreal.com',reviewed['approvalHash'],1)
    sql=client.query.call_args.args[0]
    assert result['mainEnvironmentPointersAddedOrUpdated']==1 and result['originalFeedbackAndAnswerRcaRowsRewritten']==0
    assert 'BEGIN TRANSACTION' in sql and 'COMMIT TRANSACTION' in sql and 'MAIN_ENV_MANAGER_REQUIRED' in sql
    assert 'MAIN_ENV_PROMOTION_PREVIEW_STALE' in sql and 'MAIN_ENV_SOURCE_OR_PROMOTION_CHANGED' in sql
    assert '=COALESCE(ARRAY_LENGTH(@old),0) AS \'MAIN_ENV_PREVIEW_STALE\'' in sql
    assert 'MERGE `'+settings.project_id+'.'+settings.dataset+'.feedback_main_environments`' in sql
    assert "'main_environment_selected'" in sql and 'reviewed_hash' in sql
    assert 'UPDATE `'+settings.project_id+'.'+settings.dataset+'.feedback_items`' not in sql
    assert 'feedback_answer_versions' not in sql and 'feedback_rca_versions' not in sql and 'feedback_workflow_jobs` SET' not in sql
    assert 'original-reviewer@example.test' not in sql and 'dhruv.chawla@loreal.com' not in sql
    assert client.query.call_args.kwargs['job_retry'] is None
    assert client.query.return_value.result.assert_called_once_with(job_retry=None) is None


def test_backfill_keeps_an_already_current_latest_promotion_and_its_audit_unchanged():
    candidate={'feedback_id':'FDB-A','agent_id':settings.default_agent_id,'environment_id':'neo-prod','environment_kind':'prod',
        'environment_label':'Production','source_environment_id':'neo-nonprod','promotion_batch_id':'PROM-NEW',
        'selected_by':'reviewer@example.test','revision':1}
    # The source supplies a fingerprint for exactly the selected current pointer.
    preview_client=Mock();preview_client.query.return_value.result.side_effect=[[candidate],
        [{'feedback_id':'FDB-A','agent_id':settings.default_agent_id,'environment_id':'neo-prod','environment_kind':'prod',
          'environment_label':'Production','source_environment_id':'neo-nonprod','promotion_batch_id':'PROM-NEW',
          'revision':1,'selected_by':'reviewer@example.test','created_at':'now','updated_at':'now','fingerprint':123}]]
    reviewed=preview(preview_client)
    assert reviewed['rows']==[] and reviewed['counts']=={'latestPromotedFeedback':1,'mainEnvironmentPointersToAddOrUpdate':0,'alreadyCurrent':1}
    assert reviewed['existingRows']==[]
    client=Mock()
    with pytest.raises(ValueError,match='exact reviewed update count'):
        apply(client,reviewed,'dhruv.chawla@loreal.com',reviewed['approvalHash'],0)
    client.query.assert_not_called()


def test_backfill_preview_repairs_a_pointer_with_an_unknown_main_kind_without_touching_source_history():
    candidate={'feedback_id':'FDB-A','agent_id':settings.default_agent_id,'environment_id':'neo-prod','environment_kind':'prod',
        'environment_label':'Production','source_environment_id':'neo-nonprod','promotion_batch_id':'PROM-NEW',
        'selected_by':'reviewer@example.test','revision':1}
    preview_client=Mock();preview_client.query.return_value.result.side_effect=[[candidate],
        [{'feedback_id':'FDB-A','agent_id':settings.default_agent_id,'environment_id':'neo-prod','environment_kind':'unknown',
          'environment_label':'Production','source_environment_id':'neo-nonprod','promotion_batch_id':'PROM-NEW',
          'revision':1,'selected_by':'reviewer@example.test','created_at':'now','updated_at':'now','fingerprint':123}]]
    reviewed=preview(preview_client)
    assert reviewed['counts']=={'latestPromotedFeedback':1,'mainEnvironmentPointersToAddOrUpdate':1,'alreadyCurrent':0}
    assert reviewed['rows'][0]['environment_kind']=='prod'
    assert reviewed['existingRows']==[{'feedback_id':'FDB-A','fingerprint':123}]
