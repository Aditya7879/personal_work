"""RCA credentials, one-shot transport, and safe failure diagnostics."""
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
import pytest

from app import root_cause
from app.config import settings
from app.demo_context import demo_scope
from app.rca_progress import completed_rca
from app.workflow_worker import diagnosis_payload
from test_workflow import record


TARGET = 'neo-sa-nasapmena-dv@oa-apmena-techsandbox-ap-dv.iam.gserviceaccount.com'
URL = 'https://x-np.api.loreal.net/global/it4it/btapgateways-aigateway/v1/chat/completions'
SCOPES = ['https://www.googleapis.com/auth/cloud-platform', 'https://www.googleapis.com/auth/userinfo.email']
EVIDENCE = [{'evidence_id': 'D1', 'source': 'approved-training.pdf', 'page': '17',
    'context': 'Plant: MOBA, Taiwan DC', 'excerpt': 'Plant: MOBA, Taiwan DC', 'origin': 'neo4j'}]
FEEDBACK = {'prompt': 'What is the Taiwan plant code?', 'generatedAnswer': 'Not documented.',
    'groundTruthHint': 'MOBA', 'userVerdict': 'Incorrect'}


@pytest.fixture(autouse=True)
def isolated_gateway_config():
    with patch.dict(settings.__dict__, {'btap_access_token': '', 'btap_service_account': '',
            'btap_gateway_url': URL.removesuffix('/chat/completions'), 'btap_model': 'claude-sonnet-4-6'}), \
            patch.object(root_cause, '_GATEWAY_TOKEN', (0.0, '')), patch.object(root_cause, '_GATEWAY_TOKEN_KEY', None):
        yield


def test_explicit_rca_service_account_uses_runtime_adc_to_mint_a_short_lived_token():
    source = SimpleNamespace(token='source-only', refresh=Mock())
    target = SimpleNamespace(token='target-only', refresh=Mock())
    with patch.dict(settings.__dict__, {'btap_service_account': TARGET}), \
            patch.dict('os.environ', {'K_SERVICE': 'neo-feedback-api'}), \
            patch('app.root_cause.google.auth.default', return_value=(source, 'project')) as adc, \
            patch('app.root_cause.impersonated_credentials.Credentials', return_value=target) as impersonate, \
            patch('app.root_cause.subprocess.run') as cli:
        assert root_cause._gateway_token() == 'target-only'
        assert root_cause._gateway_token() == 'target-only'
    adc.assert_called_once_with(scopes=SCOPES)
    impersonate.assert_called_once_with(source_credentials=source, target_principal=TARGET,
        target_scopes=SCOPES, lifetime=600)
    target.refresh.assert_called_once()
    source.refresh.assert_not_called()
    cli.assert_not_called()


def test_production_neo_identity_does_not_implicitly_change_rca_credentials():
    source = SimpleNamespace(token='source-only', refresh=Mock())
    with patch.dict(settings.__dict__, {'neo_companion_prod_service_account': TARGET}), \
            patch.dict('os.environ', {'K_SERVICE': 'neo-feedback-api'}), \
            patch('app.root_cause.google.auth.default', return_value=(source, 'project')), \
            patch('app.root_cause.impersonated_credentials.Credentials') as impersonate:
        assert root_cause._gateway_token() == 'source-only'
    impersonate.assert_not_called()


def test_token_cache_is_separated_when_explicit_gateway_identity_changes():
    source = SimpleNamespace(token='source-only', refresh=Mock())
    target = SimpleNamespace(token='target-only', refresh=Mock())
    with patch.dict('os.environ', {'K_SERVICE': 'neo-feedback-api'}), \
            patch('app.root_cause.google.auth.default', return_value=(source, 'project')), \
            patch('app.root_cause.impersonated_credentials.Credentials', return_value=target):
        assert root_cause._gateway_token() == 'source-only'
        with patch.dict(settings.__dict__, {'btap_service_account': TARGET}):
            assert root_cause._gateway_token() == 'target-only'
        assert root_cause._gateway_token() == 'source-only'
    assert source.refresh.call_count == 2
    target.refresh.assert_called_once()


def test_failed_impersonation_never_uses_source_token_or_personal_cli_credentials():
    source = SimpleNamespace(token='do-not-use-source', refresh=Mock())
    target = SimpleNamespace(token=None, refresh=Mock(side_effect=RuntimeError('sensitive raw IAM payload')))
    with patch.dict(settings.__dict__, {'btap_service_account': TARGET}), \
            patch('app.root_cause.google.auth.default', return_value=(source, 'project')), \
            patch('app.root_cause.impersonated_credentials.Credentials', return_value=target), \
            patch('app.root_cause.subprocess.run') as cli, patch('app.root_cause.httpx.post') as post:
        result = root_cause.suggest_root_cause(FEEDBACK, EVIDENCE)
    cli.assert_not_called()
    post.assert_not_called()
    assert result['rca_failure_code'] == 'authentication'
    assert result['rca_suggestion_status'] == 'fallback_gateway_authentication'
    assert 'sensitive' not in json.dumps(result) and 'do-not-use-source' not in json.dumps(result)


def test_ambiguous_static_and_impersonated_credentials_fail_closed():
    with patch.dict(settings.__dict__, {'btap_access_token': 'do-not-use-static', 'btap_service_account': TARGET}), \
            patch('app.root_cause.google.auth.default') as adc, patch('app.root_cause.subprocess.run') as cli:
        with pytest.raises(root_cause.RcaGatewayError, match='service identity'):
            root_cause._gateway_token()
    adc.assert_not_called()
    cli.assert_not_called()


@pytest.mark.parametrize('bad_principal', ['https://evil.example', 'user@loreal.com', 'projects/p/serviceAccounts/x', 'bad\nheader'])
def test_invalid_gateway_service_account_is_not_sent_to_iam(bad_principal):
    with patch.dict(settings.__dict__, {'btap_service_account': bad_principal}), \
            patch('app.root_cause.google.auth.default', return_value=(Mock(), 'project')), \
            patch('app.root_cause.impersonated_credentials.Credentials') as impersonate:
        with pytest.raises(root_cause.RcaGatewayError):
            root_cause._gateway_token()
    impersonate.assert_not_called()


def test_demo_mode_never_mints_an_rca_token_or_calls_the_gateway():
    with demo_scope(), patch.dict(settings.__dict__, {'btap_service_account': TARGET, 'role_demo_enabled': True,
            'auth_mode': 'google_iam', 'demo_frontend_origin': 'https://feedback.example',
            'auth_secret': 'test-only-signing-secret', 'dataset': 'agent_quality'}), \
            patch('app.root_cause.google.auth.default') as adc, \
            patch('app.root_cause.impersonated_credentials.Credentials') as impersonate, \
            patch('app.root_cause.httpx.post') as post:
        with pytest.raises(RuntimeError, match='disabled'):
            root_cause._gateway_token()
        assert root_cause.suggest_root_cause(FEEDBACK, EVIDENCE)['rca_review_required'] is True
        assert root_cause.assess_correction(FEEDBACK, FEEDBACK, EVIDENCE)['reviewRequired'] is True
    adc.assert_not_called()
    impersonate.assert_not_called()
    post.assert_not_called()


def response(status=200, **kwargs):
    return httpx.Response(status, request=httpx.Request('POST', URL), **kwargs)


def decision():
    return {'root_cause': 'missing_required_content', 'subcategory': 'Taiwan entry omitted',
        'rationale': 'The supplied source lists MOBA.', 'evidence_ids': ['D1'], 'confidence': .9, 'review_required': True}


def test_judge_keeps_the_gateway_contract_and_sends_exactly_one_post():
    reply = response(json={'choices': [{'message': {'content': json.dumps(decision())}}]})
    with patch('app.root_cause._gateway_token', return_value='do-not-expose-token'), \
            patch('app.root_cause.httpx.post', return_value=reply) as post:
        result = root_cause.suggest_root_cause(FEEDBACK, EVIDENCE)
    post.assert_called_once()
    assert post.call_args.args == (URL,)
    kwargs = post.call_args.kwargs
    assert kwargs['headers']['x-frontend-authorization'] == 'Bearer do-not-expose-token'
    assert kwargs['json']['model'] == 'claude-sonnet-4-6'
    assert kwargs['json']['temperature'] == 0 and kwargs['json']['max_tokens'] == 1800
    assert kwargs['follow_redirects'] is False
    assert kwargs['timeout'].read == 120 and kwargs['timeout'].connect == 15
    assert result['rca_suggestion_status'] == 'sonnet_suggested' and result['rca_failure_code'] is None
    assert result['rca_evidence'] == EVIDENCE
    assert 'do-not-expose-token' not in json.dumps(result)


@pytest.mark.parametrize(('status', 'code'), [(401, 'authentication'), (403, 'permission'),
    (429, 'rate_limit'), (500, 'unavailable'), (503, 'unavailable'), (504, 'timeout'), (302, 'redirect'), (400, 'request')])
def test_http_failures_keep_status_and_evidence_without_logging_upstream_content(status, code, caplog):
    reply = response(status, text='private-upstream-body do-not-expose-token SECRET-CONTEXT')
    with patch('app.root_cause._gateway_token', return_value='do-not-expose-token'), \
            patch('app.root_cause.httpx.post', return_value=reply) as post:
        result = root_cause.suggest_root_cause(FEEDBACK, EVIDENCE)
    post.assert_called_once()
    assert result['rca_failure_code'] == code and result['rca_failure_http_status'] == status
    assert result['rca_suggestion_status'] == 'fallback_gateway_' + code
    assert result['rca_retrieval_status'] == 'available' and result['rca_evidence'] == EVIDENCE
    assert result['rca_review_required'] is True and result['rca_auto_accepted'] is False
    assert completed_rca(result) is False
    assert f'HTTP {status}' in result['rca_rationale'] and 'No automatic retry' in result['rca_rationale']
    serialized = json.dumps(result) + caplog.text
    for private in ['private-upstream-body', 'do-not-expose-token', 'SECRET-CONTEXT']:
        assert private not in serialized
    assert f'code={code}' in caplog.text and f'http_status={status}' in caplog.text


@pytest.mark.parametrize(('exc', 'code'), [(httpx.ReadTimeout, 'timeout'), (httpx.ConnectError, 'network')])
def test_timeout_or_network_failure_is_not_replayed(exc, code):
    with patch('app.root_cause._gateway_token', return_value='token'), \
            patch('app.root_cause.httpx.post', side_effect=exc('private network details')) as post:
        result = root_cause.suggest_root_cause(FEEDBACK, EVIDENCE)
    post.assert_called_once()
    assert result['rca_failure_code'] == code and result['rca_failure_http_status'] is None
    assert 'private network details' not in json.dumps(result)


@pytest.mark.parametrize('body', [{}, {'choices': []}, {'choices': [{'message': {'content': None}}]},
    {'choices': [{'message': {'content': 'not assessment JSON'}}]}])
def test_invalid_assessment_response_is_not_a_permission_or_source_gap(body):
    with patch('app.root_cause._gateway_token', return_value='token'), \
            patch('app.root_cause.httpx.post', return_value=response(json=body)) as post:
        result = root_cause.suggest_root_cause(FEEDBACK, EVIDENCE)
    post.assert_called_once()
    assert result['rca_failure_code'] == 'response'
    assert result['suggested_rca'] == 'insufficient_evidence' and not result['rca_auto_accepted']


def test_comparison_uses_the_same_gateway_credentials_and_safe_permission_diagnostics():
    with patch('app.root_cause._gateway_token', return_value='do-not-expose-token') as token, \
            patch('app.root_cause.httpx.post', return_value=response(403, text='private upstream payload')) as post:
        result = root_cause.assess_correction(FEEDBACK, {**FEEDBACK, 'generatedAnswer': 'MOBA'}, EVIDENCE)
    token.assert_called_once()
    post.assert_called_once()
    assert post.call_args.kwargs['json']['max_tokens'] == 1600
    assert result['assessment'] == 'inconclusive' and result['reviewRequired'] is True
    assert result['errorCode'] == 'permission' and result['httpStatus'] == 403
    assert 'HTTP 403' in result['reason']
    assert 'private upstream payload' not in json.dumps(result)


def test_successful_comparison_does_not_resolve_feedback_automatically():
    reply = {'assessment': 'still_incorrect', 'reason': 'Taiwan entry still missing.', 'evidence_ids': ['D1'], 'confidence': .95}
    with patch('app.root_cause._gateway_token', return_value='token'), \
            patch('app.root_cause.httpx.post', return_value=response(json={'choices': [{'message': {'content': json.dumps(reply)}}]})):
        result = root_cause.assess_correction(FEEDBACK, {**FEEDBACK, 'generatedAnswer': 'Still not documented.'}, EVIDENCE)
    assert result['assessment'] == 'still_incorrect' and result['reviewRequired'] is True
    assert 'public_status' not in result and 'resolved' not in result


def test_saved_diagnosis_keeps_only_safe_gateway_error_fields_with_the_same_answer_context():
    with patch('app.root_cause._judge', side_effect=root_cause.RcaGatewayError('permission', 403)):
        suggestion = root_cause.suggest_root_cause(FEEDBACK, EVIDENCE)
    saved = diagnosis_payload(suggestion, record(), 'answer:JOB-PROD', 3)
    assert saved['failureCode'] == 'permission' and saved['httpStatus'] == 403
    assert saved['answerId'] == 'answer:JOB-PROD' and saved['configurationRevision'] == 3
    assert saved['evidence'] == EVIDENCE and saved['verified'] is False
