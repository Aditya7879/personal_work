import json
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from app.bigquery import BigQueryRepository
from app.business_domain import business_taxonomy_options
from app.main import app, repository
from app.models import FeedbackCreate, MyFeedbackUpdate, TriageUpdate
from test_workflow import login


def submission(**fields):
    return FeedbackCreate(user_verdict='Incorrect', feedback_text='A rule is missing.', **fields)


def test_submission_saves_custom_context_without_reclassifying_or_trimming_the_captured_answer():
    repo = BigQueryRepository(client=Mock())
    payload = submission(question='  exact question\n', answer='  exact captured answer\n',
        business_domain='  Custom   Operations ', business_subdomain='  多语言\t业务 ')
    row = repo._feedback_row(payload)
    assert row['business_domain'] == 'Custom Operations'
    assert row['business_subdomain'] == '多语言 业务'
    assert row['domain_source'] == 'user_submitted' and row['domain_verified'] is False
    assert 'not been independently verified' in row['domain_reason']
    assert row['question'] == payload.question and row['answer'] == payload.answer
    assert row['state'] == 'Submitted' and row['expected_behavior_verified'] is False
    record = repo._record(row)
    assert record.businessDomain == 'Custom Operations' and record.businessSubdomain == '多语言 业务'


@pytest.mark.parametrize('value,expected', [('otc', 'O2C'), (' f2s ', 'F2S'), ('Tax Operations', 'Tax Operations'), ('  ', None)])
def test_only_exact_standard_codes_are_normalized_and_custom_domains_remain_custom(value, expected):
    assert submission(business_domain=value).business_domain == expected


def test_subdomain_can_be_supplied_without_guessing_its_domain():
    row = BigQueryRepository(client=Mock())._feedback_row(submission(business_subdomain='Catalogue Management'))
    assert row['business_domain'] == 'Unspecified'
    assert row['business_subdomain'] == 'Catalogue Management' and row['domain_source'] == 'user_submitted'


def test_new_explicit_fields_take_precedence_without_claiming_workbook_provenance():
    row = BigQueryRepository(client=Mock())._feedback_row(submission(business_domain='Custom Operations',
        run_context={'domain':'F2S','sub_domain':'Old label','classification_source':'workbook_import'}, source='legacy_xlsx_import'))
    assert row['business_domain'] == 'Custom Operations' and row['business_subdomain'] is None
    assert row['domain_source'] == 'user_submitted'
    assert row['run_context_json'] and 'Old label' in row['run_context_json']
    record = BigQueryRepository(client=Mock())._record(row)
    assert record.businessSubdomain is None


def test_authoritative_workbook_import_path_and_labels_are_unchanged():
    row = BigQueryRepository(client=Mock())._feedback_row(submission(source='legacy_xlsx_import',
        run_context={'domain':'F2S','business_subdomain':'Lifecycle Management','sub_domain':'F2S - Lifecycle Management','classification_source':'workbook_import'}))
    assert row['business_domain'] == 'F2S'
    assert row['business_subdomain'] == 'Lifecycle Management' and row['domain_source'] == 'workbook_import'
    assert row['domain_verified'] is False


@pytest.mark.parametrize('fields', [{'business_domain': 'x' * 101}, {'business_subdomain': 'x' * 301},
    {'business_domain': 'bad\x00label'}, {'business_subdomain': 'hidden\u202elabel'},
    {'business_domain': ['not text']}, {'domain_source':'workbook_import'}, {'domain_verified':True}])
def test_invalid_or_forged_taxonomy_fields_are_rejected(fields):
    with pytest.raises(ValidationError): submission(**fields)


def test_owner_and_reviewer_updates_use_the_same_label_validation():
    for model in (MyFeedbackUpdate, TriageUpdate):
        assert model(business_domain=' otc ', business_subdomain='  Custom  area ').business_domain == 'O2C'
        assert model(business_subdomain='  Custom  area ').business_subdomain == 'Custom area'
        with pytest.raises(ValidationError): model(business_subdomain='bad\x00label')


def test_cleared_user_classification_does_not_resurface_from_immutable_legacy_metadata():
    repo = BigQueryRepository(client=Mock())
    record = repo._record({'feedback_id':'FDB-1','business_domain':None,'business_subdomain':'',
        'domain_source':'user_confirmed','run_context_json':json.dumps({'domain':'F2S','sub_domain':'Old topic'})})
    assert record.businessDomain == 'Unspecified' and record.businessSubdomain is None
    assert record.runContext['sub_domain'] == 'Old topic'


def test_automatic_document_suggestions_cannot_overwrite_submitted_confirmed_or_workbook_context():
    repo = BigQueryRepository(client=Mock())
    with patch.object(repo, 'workflow_query') as query:
        repo.save_domain_suggestion('FDB-1', 1, {'domain':'F2S','source':'document_inferred','reason':'Document hint'})
    sql = query.call_args.args[0]
    assert 'NOT COALESCE(domain_verified, FALSE)' in sql
    for source in ['workbook_import','user_submitted','user_confirmed','reviewer_confirmed','submitted','legacy_submitted']:
        assert "'" + source + "'" in sql


def test_taxonomy_suggestions_include_standards_and_authorized_custom_labels_without_assigning_unknowns():
    options = business_taxonomy_options([{'business_domain':'Custom Operations','business_subdomain':'My area'},
        {'business_domain':'Unspecified','business_subdomain':'Catalogue Management'}])
    assert options['domains'][:4] == ['O2C','F2S','P2P','R2R']
    assert 'Custom Operations' in options['domains'] and options['allowCustom']
    assert options['subdomains']['Custom Operations'] == ['My area']
    assert 'Catalogue Management' in options['subdomains']['Unspecified']
    assert 'Catalogue Management' not in options['subdomains']['O2C']
    assert 'Lifecycle Management' in options['subdomains']['F2S']


def test_saved_choices_are_parameterized_bounded_and_owner_scoped():
    client = Mock(); client.query.return_value.result.return_value = [{'business_domain':'My domain','business_subdomain':'My area'}]
    repo = BigQueryRepository(client=client)
    options = repo.list_business_taxonomy([' Owner@example.test '])
    sql = client.query.call_args.args[0]
    assert 'LOWER(TRIM(f.reporter)) IN UNNEST(@reporters)' in sql and 'LIMIT 1000' in sql
    assert 'Owner@example.test' not in sql
    params = client.query.call_args.kwargs['job_config'].query_parameters
    assert params[0].values == ['owner@example.test']
    assert options['subdomains']['My domain'] == ['My area']


def test_taxonomy_api_uses_authenticated_scope_and_does_not_accept_a_reporter_override():
    fake = Mock(); fake.list_business_taxonomy.return_value = business_taxonomy_options([])
    app.dependency_overrides[repository] = lambda: fake
    try:
        client = TestClient(app)
        assert client.get('/api/my/business-taxonomy').status_code == 401
        headers = login(client)
        response = client.get('/api/my/business-taxonomy?reporter=someone-else@example.test', headers=headers)
        assert response.status_code == 200 and 'F2S' in response.json()['domains']
        fake.list_business_taxonomy.assert_called_once_with(reporter=['alex.requester@example.test'])
        fake.reset_mock()
        headers = login(client, 'quality.reviewer@example.test')
        assert client.get('/api/my/business-taxonomy', headers=headers).status_code == 200
        fake.list_business_taxonomy.assert_called_once_with(reporter=None)
    finally: app.dependency_overrides.pop(repository, None)


def test_submitter_api_round_trips_classification_and_retains_real_owner_identity():
    repo = BigQueryRepository(client=Mock())
    repo._insert_rows = Mock(); repo._insert_event = Mock(); repo.enqueue_feedback_job = Mock()
    app.dependency_overrides[repository] = lambda: repo
    try:
        client = TestClient(app); headers = login(client)
        response = client.post('/api/my/feedback', headers=headers, json={'user_verdict':'Incorrect','feedback_text':'Missing rule',
            'business_domain':'Custom Operations','business_subdomain':'My area','reporter':'spoofed@example.test'})
        assert response.status_code == 201
        body = response.json()
        assert body['businessDomain'] == 'Custom Operations' and body['businessSubdomain'] == 'My area'
        assert body['domainSource'] == 'user_submitted' and body['domainVerified'] is False
        row = repo._insert_rows.call_args.args[1][0]
        assert row['reporter'] == 'alex.requester@example.test'
        repo.enqueue_feedback_job.assert_called_once()
    finally: app.dependency_overrides.pop(repository, None)
