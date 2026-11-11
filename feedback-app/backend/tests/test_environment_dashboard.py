import json
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app.bigquery import BigQueryRepository
from app.main import app, repository
from test_agent_environments import ENV, login


def test_dashboard_api_passes_environment_scope_and_rejects_invalid_scope():
    fake = Mock(); fake.overview.return_value = {'feedback_total': 20}
    app.dependency_overrides[repository] = lambda: fake
    try:
        client = TestClient(app); headers = login(client)
        assert client.get('/api/overview?environment_id=uat', headers=headers).json()['feedback_total'] == 20
        fake.overview.assert_called_once_with('uat')
        fake.overview.side_effect = KeyError('Unknown')
        assert client.get('/api/overview?environment_id=missing', headers=headers).status_code == 422
    finally:
        app.dependency_overrides.pop(repository, None)


def test_scoped_overview_uses_membership_latest_answers_and_matching_rca():
    client = Mock(); client.query.return_value.result.return_value = [{'feedback_total': 20, 'evaluation_trend_json': '[]'}]
    repo = BigQueryRepository(client=client)
    with patch.object(repo, 'get_agent_environment', return_value=ENV):
        result = repo.overview('uat')
    sql = client.query.call_args.args[0]
    params = {value.name: value.value for value in client.query.call_args.kwargs['job_config'].query_parameters}
    assert params['environment_id'] == 'uat'
    assert 'UNION DISTINCT' in sql and 'origin_environment_id=@environment_id' in sql
    assert "j.target_id=@environment_id" in sql
    assert "PARTITION BY v.feedback_id,j.target_id" in sql and 'v.answer_id=a.id' in sql
    assert 'CASE WHEN a.id IS NOT NULL THEN JSON_VALUE(v.payload_json' in sql
    assert 'c.environment_id IS NOT DISTINCT FROM f.origin_environment_id' in sql
    assert result['scope']['environmentId'] == 'uat' and result['scope']['assets'] == 'agent_wide'
    assert result['scope']['reviewProgress'] == 'source_report_workflow'


def test_all_environments_counts_distinct_source_records_not_summed_memberships():
    client = Mock(); client.query.return_value.result.return_value = [{'feedback_total': 156}]
    repo = BigQueryRepository(client=client)
    result = repo.overview()
    sql = client.query.call_args.args[0]
    assert '(SELECT COUNT(*) FROM scoped_feedback) AS feedback_total' in sql
    assert 'FROM source_feedback f WHERE @environment_id IS NULL' in sql
    assert result['feedback_total'] == 156 and result['scope']['environmentId'] is None
    assert result['assessment_breakdown'] == []


def test_incoming_promotions_are_not_counted_as_new_source_submissions():
    client = Mock(); client.query.return_value.result.return_value = [{}]
    repo = BigQueryRepository(client=client)
    with patch.object(repo, 'get_agent_environment', return_value=ENV):
        repo.overview('uat')
    sql = client.query.call_args.args[0]
    assert 'AND (@environment_id IS NULL OR f.origin_environment_id=@environment_id) GROUP BY days.day' in sql
    assert 'origin_environment_id IS DISTINCT FROM @environment_id' in sql
    assert "JSON_VALUE(a.result_json,'$.assessment') AS verdict" in sql
    assert 'NoSource' not in sql
