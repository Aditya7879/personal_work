from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app.bigquery import BigQueryRepository
from app.config import settings
from app.feedback_ownership import owner_scope
from app.main import app, repository
from app.models import PromotionSelection
from test_agent_environments import login


def source_row(index=1):
    return {'feedback_id':f'FDB-{index}','agent_id':settings.default_agent_id,'question':'Original question',
        'answer':'Original Non-prod answer','environment':'nonprod','revision':1,'state':'Submitted',
        'public_status':'Received','run_context_json':'{"environment_id":"neo-nonprod","environment_kind":"nonprod","environment_label":"Non-production"}'}


def repo_with_rows(total=20, rows=None):
    db=Mock();count=Mock();count.result.return_value=[SimpleNamespace(total=total)]
    page=Mock();page.result.return_value=rows if rows is not None else [source_row()]
    db.query.side_effect=[count,page]
    return BigQueryRepository(client=db),db


def test_production_kind_matches_original_or_linked_checks_and_uses_same_predicate_for_count_and_page():
    row=source_row();before=deepcopy(row);repo,db=repo_with_rows(rows=[row])
    records,total=repo.list_feedback(environment='prod',page=3,page_size=7)
    assert total==20 and len(records)==1
    assert records[0].environment=='nonprod' and records[0].environmentId=='neo-nonprod'
    assert records[0].generatedAnswer=='Original Non-prod answer' and row==before
    count_sql,page_sql=[call.args[0]for call in db.query.call_args_list]
    for sql in(count_sql,page_sql):
        assert "OR feedback_id IN (" in sql and "j.kind='retest'" in sql
        assert repo._job_environment_kind('j')+' = @environment' in sql
        assert "$.target.environment" in sql
        assert 'j.status =' not in sql  # Failed/queued attempts still establish membership.
        assert not any(word in sql for word in('UPDATE `','INSERT INTO','DELETE FROM'))
    assert count_sql.split(' WHERE ',1)[1] == page_sql.split(' WHERE ',1)[1].split(' ORDER BY ',1)[0]
    params={value.name:value.value for value in db.query.call_args.kwargs['job_config'].query_parameters}
    assert params['environment']=='prod' and params['limit']==7 and params['offset']==14
    assert 'ORDER BY f.updated_at DESC,f.feedback_id DESC LIMIT @limit OFFSET @offset' in page_sql


def test_owner_scope_remains_outside_the_linked_environment_or_condition():
    repo,db=repo_with_rows()
    repo.list_feedback(environment='prod',reporter=['Owner@example.test'])
    sql=db.query.call_args.args[0]
    assert f"AND {owner_scope(repo, 'f')} AND (" in sql
    params=db.query.call_args.kwargs['job_config'].query_parameters
    assert next(value for value in params if value.name=='reporters').values==['owner@example.test']


def test_unknown_filter_remains_a_missing_original_source_not_an_inferred_target():
    repo,db=repo_with_rows(total=0,rows=[])
    repo.list_feedback(environment='unknown')
    sql=db.query.call_args.args[0]
    assert 'feedback_workflow_jobs' not in sql
    assert repo._source_environment_kind() in sql


def test_named_id_scope_does_not_collapse_same_kind_environments_and_keeps_source_metadata():
    repo,db=repo_with_rows()
    target={'id':'uat','agent_id':settings.default_agent_id,'kind':'nonprod','name':'UAT'}
    result={'FDB-1':{'id':'JOB-UAT','environmentId':'uat','environment':'nonprod','status':'completed','revision':1}}
    with patch.object(repo,'get_agent_environment',return_value=target),patch.object(repo,'environment_results',return_value=result):
        records,total=repo.list_feedback(environment_id='uat')
    sql=db.query.call_args.args[0]
    params={value.name:value.value for value in db.query.call_args.kwargs['job_config'].query_parameters}
    assert params['environment_id']=='uat' and params['legacy_kind']=='__not_legacy__'
    assert 'j.target_id=@environment_id' in sql
    assert records[0].environmentId=='neo-nonprod' and records[0].environmentResult['environmentId']=='uat'


def test_exact_header_scope_and_legacy_kind_filter_can_be_combined_without_excluding_links():
    repo,db=repo_with_rows()
    target={'id':'neo-prod','agent_id':settings.default_agent_id,'kind':'prod','name':'Production'}
    with patch.object(repo,'get_agent_environment',return_value=target),patch.object(repo,'environment_results',return_value={}):
        records,total=repo.list_feedback(environment_id='neo-prod',environment='prod')
    sql=db.query.call_args.args[0]
    assert 'j.target_id=@environment_id' in sql and repo._job_environment_kind('j')+' = @environment' in sql
    assert records[0].environment=='nonprod' and total==20


def test_all_matching_preview_reuses_the_membership_filter_without_copying_or_dispatching():
    rows=[source_row(index)for index in range(1,21)];repo,db=repo_with_rows(total=20,rows=rows)
    selection=PromotionSelection(all_matching=True,filters={'environment':'prod'})
    with patch.object(repo,'enqueue_feedback_job')as enqueue:
        preview=repo.promotion_preview(selection)
    assert preview['count']==20 and len(preview['selectionToken'])==64
    enqueue.assert_not_called()
    assert "j.kind='retest'" in db.query.call_args.args[0]


def test_api_kind_and_named_filters_are_forwarded_while_reporters_keep_their_own_scope():
    fake=Mock();fake.list_feedback.return_value=([],20);fake.list_my_feedback.return_value=([],0)
    app.dependency_overrides[repository]=lambda:fake
    try:
        client=TestClient(app);reviewer=login(client)
        response=client.get('/api/feedback?environment=prod&environment_id=neo-prod',headers=reviewer)
        assert response.status_code==200 and response.json()['total']==20
        assert fake.list_feedback.call_args.kwargs['environment']=='prod'
        assert fake.list_feedback.call_args.kwargs['environment_id']=='neo-prod'
        reporter=login(client,'reporter')
        assert client.get('/api/feedback?environment=prod',headers=reporter).status_code==403
        assert client.get('/api/my/feedback?environment=prod',headers=reporter).status_code==200
        assert fake.list_my_feedback.call_args.args[0]==['alex.requester@example.test']
    finally:app.dependency_overrides.pop(repository,None)
