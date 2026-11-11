import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import json
import os
import subprocess
import sys
from threading import Barrier
from unittest.mock import Mock, patch

from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.testclient import TestClient
import pytest

from app import access_repository as access_storage, auth, role_demo
from app.access_repository import AccessGrantRepository, access_table_ref
from app.access_routes import AccessGrantUpdate
from app.bigquery import BigQueryRepository
from app.config import settings
from app.demo_context import demo_scope, is_demo
from app.main import app, repository
from test_feedback_portal_api import _public_record
from test_google_iam_auth import iam
from test_google_iap_auth import iap
from test_workflow import record


ORIGIN = 'https://feedback-ui.example.test'
ACTOR = 'reviewer@company.example'
ACTION = {'Origin': ORIGIN, 'X-Feedback-CSRF': '1', 'X-Requested-With': 'XMLHttpRequest'}
MARKER = {'X-Feedback-Demo-View': '1'}


@pytest.fixture
def demo(iap, monkeypatch):
    monkeypatch.delenv('K_SERVICE', raising=False)
    for key, value in {'role_demo_enabled': True, 'demo_frontend_origin': ORIGIN,
            'dataset': 'agent_quality', 'authz_table': '', 'workflow_worker_enabled': False}.items():
        monkeypatch.setitem(settings.__dict__, key, value)
    iap.grants[ACTOR]['role'] = 'demo_admin'
    fresh = Mock()
    fresh.grant.side_effect = lambda email, **_kwargs: iap.grants.get(email)
    original_access_repository = access_storage.access_repository
    monkeypatch.setattr(access_storage, 'access_repository', lambda: fresh)
    live, sample = Mock(), Mock()
    for repo, dataset in [(live, 'agent_quality'), (sample, 'agent_quality_demo')]:
        repo.dataset_ref = f'{settings.project_id}.{dataset}'
        repo.workflow_query.return_value = []
        repo.list_feedback.return_value = ([], 0)
        repo.list_my_feedback.return_value = ([], 0)
        repo.get_my_feedback.return_value = None
        repo.get_feedback.return_value = None
    app.dependency_overrides[repository] = lambda: sample if is_demo() else live
    app.dependency_overrides[original_access_repository] = lambda: fresh
    client = TestClient(app, base_url=ORIGIN, headers={'X-Feedback-IAP-Assertion': iap()})
    try:
        yield client, iap, live, sample, fresh
    finally:
        app.dependency_overrides.pop(repository, None)
        app.dependency_overrides.pop(original_access_repository, None)


def select(demo, email='alex.requester@example.test'):
    client = demo[0]
    response = client.post('/api/demo-admin/persona', headers=ACTION, json={'email': email})
    assert response.status_code == 200, response.text
    return response


def signed_cookie(**changes):
    user = auth.AuthenticatedUser(ACTOR, 'Reviewer', 'reviewer', access_role='demo_admin')
    token = role_demo.issue_view(user, 'alex.requester@example.test')
    encoded = token.split('.')[0]
    value = json.loads(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))
    value.update(changes)
    encoded = base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip('=')
    signature = base64.urlsafe_b64encode(hmac.new(auth._TOKEN_SECRET, (role_demo.AUDIENCE + ':' + encoded).encode(), hashlib.sha256).digest()).decode().rstrip('=')
    return encoded + '.' + signature


def test_stored_demo_admin_is_effective_reviewer_with_an_extra_capability_not_a_new_workflow_role(demo):
    client, _, live, _, _ = demo
    user = client.get('/api/auth/me').json()
    assert user['role'] == 'reviewer' and user['accessRole'] == 'demo_admin' and user['canSwitchDemoViews'] is True
    assert 'demoMode' not in user
    assert client.get('/api/feedback').status_code == 200
    live.list_feedback.assert_called_once()
    status = client.get('/api/demo-admin/session')
    assert status.status_code == 200 and status.json()['active'] is False
    assert status.json()['realUser']['email'] == ACTOR and len(status.json()['personas']) == 3


def test_real_demo_admin_retains_access_management_but_a_demo_reviewer_does_not(demo):
    client, _, _, _, fresh = demo
    fresh.list_grants.return_value = {'items': [], 'total': 0}
    assert client.get('/api/access-grants').status_code == 200
    fresh.list_grants.assert_called_once()
    select(demo, 'quality.reviewer@example.test')
    assert client.get('/api/access-grants', headers=MARKER).status_code == 403
    fresh.list_grants.assert_called_once()


@pytest.mark.parametrize('stored_role', ['reporter', 'reviewer'])
def test_ordinary_roles_keep_their_permissions_but_cannot_select_or_reset_demo_views(demo, stored_role):
    client, token, live, sample, _ = demo
    token.grants[ACTOR]['role'] = stored_role
    user = client.get('/api/auth/me').json()
    assert user['role'] == stored_role and not user.get('canSwitchDemoViews')
    assert client.get('/api/feedback').status_code == (200 if stored_role == 'reviewer' else 403)
    assert client.get('/api/demo-admin/session').status_code == 403
    assert client.post('/api/demo-admin/persona', headers=ACTION, json={'email': 'quality.reviewer@example.test'}).status_code == 403
    assert client.post('/api/demo-admin/reset', headers=ACTION, json={'confirmation': 'RESET DEMO'}).status_code == 403
    sample.workflow_query.assert_not_called()


def test_primary_iap_signature_and_application_grant_are_required_before_a_demo_cookie_is_considered(demo):
    client, token, live, sample, _ = demo
    select(demo)
    client.headers.clear()
    for value in [None, 'forged', 'unsigned.payload.']:
        headers = {**MARKER, **({'X-Feedback-IAP-Assertion': value} if value is not None else {})}
        assert client.get('/api/my/feedback', headers=headers).status_code == 401
    token.grants.clear()
    assert client.get('/api/my/feedback', headers={**MARKER, 'X-Feedback-IAP-Assertion': token()}).status_code == 403
    live.list_my_feedback.assert_not_called(); sample.list_my_feedback.assert_not_called()


def test_demo_cookie_is_actor_bound_http_only_secure_and_never_a_browser_credential(demo):
    client, token, _, _, _ = demo
    response = select(demo)
    cookie = response.headers['set-cookie']
    assert cookie.startswith('neo_role_demo=') and 'HttpOnly' in cookie and 'Secure' in cookie and 'SameSite=strict' in cookie
    assert 'accessToken' not in response.text and 'password' not in response.text
    assert response.json()['realUser']['email'] == ACTOR
    assert response.json()['user']['email'] == 'alex.requester@example.test'
    assert response.json()['user']['role'] == 'reporter' and response.json()['user']['demoMode'] == 'demo_admin'
    assert response.json()['user']['cacheScope'] != response.json()['realUser']['cacheScope']
    token.grants['other@company.example'] = {'role': 'demo_admin', 'displayName': 'Other'}
    assert client.get('/api/my/feedback', headers={**MARKER, 'X-Feedback-IAP-Assertion': token(email='other@company.example')}).status_code == 401


def test_marker_and_valid_cookie_are_both_required_and_no_missing_marker_or_expired_cookie_falls_back_to_live(demo):
    client, _, live, sample, _ = demo
    payload = {'feedback_text': 'Demo only', 'user_verdict': 'Incorrect'}
    assert client.post('/api/my/feedback', headers={**ACTION, **MARKER}, json=payload).status_code == 401
    select(demo)
    assert client.post('/api/my/feedback', headers=ACTION, json=payload).status_code == 409
    assert client.get('/api/my/feedback').status_code == 409
    client.cookies.clear()
    assert client.post('/api/my/feedback', headers={**ACTION, **MARKER}, json=payload).status_code == 401
    client.cookies.set(role_demo.COOKIE, signed_cookie(exp=1))
    assert client.post('/api/my/feedback', headers={**ACTION, **MARKER}, json=payload).status_code == 401
    live.create_feedback.assert_not_called(); sample.create_feedback.assert_not_called()


@pytest.mark.parametrize('marker', ['0', 'true', 'reviewer', ''])
def test_invalid_demo_markers_are_rejected_not_ignored(demo, marker):
    client, _, live, _, _ = demo
    assert client.post('/api/my/feedback', headers={**ACTION, 'X-Feedback-Demo-View': marker}, json={}).status_code == 400
    live.create_feedback.assert_not_called()


@pytest.mark.parametrize('changes', [{'persona': 'real-employee@company.example'}, {'aud': 'private-demo'},
    {'actor': 'wrong'}, {'nonce': ''}, {'exp': 'not-an-expiry'}, {'role': 'reviewer'}])
def test_forged_persona_role_purpose_actor_and_expiry_fail_closed(demo, changes):
    client, _, live, sample, _ = demo
    client.cookies.set(role_demo.COOKIE, signed_cookie(**changes))
    assert client.get('/api/my/feedback', headers=MARKER).status_code == 401
    live.list_my_feedback.assert_not_called(); sample.list_my_feedback.assert_not_called()


def test_tampered_signature_cannot_open_sample_or_live_storage(demo):
    client, _, live, sample, _ = demo
    cookie = signed_cookie()
    client.cookies.set(role_demo.COOKIE, cookie[:-1] + ('B' if cookie[-1] == 'A' else 'A'))
    assert client.get('/api/my/feedback', headers=MARKER).status_code == 401
    live.list_my_feedback.assert_not_called(); sample.list_my_feedback.assert_not_called()


def test_controller_persona_allowlist_ignores_no_browser_role_or_extra_fields(demo):
    client, _, _, sample, _ = demo
    for payload, expected in [({'email': 'real-employee@company.example'}, 422),
        ({'email': 'alex.requester@example.test', 'role': 'reviewer'}, 400), ({'email': None}, 400), ({'email': ACTOR}, 422)]:
        assert client.post('/api/demo-admin/persona', headers={**ACTION, 'X-Feedback-Role': 'reviewer'}, json=payload).status_code == expected
    sample.workflow_query.assert_not_called()


def test_role_switch_uses_only_demo_repository_and_original_primary_actor_for_audits(demo):
    client, _, live, sample, fresh = demo
    first = select(demo).json()['user']['cacheScope']
    assert client.get('/api/my/feedback', headers=MARKER).status_code == 200
    sample.list_my_feedback.assert_called_once()
    assert sample.list_my_feedback.call_args.args[0] == ['alex.requester@example.test']
    assert client.get('/api/feedback', headers={**MARKER, 'X-Feedback-Role': 'reviewer'}).status_code == 403
    second = select(demo, 'quality.reviewer@example.test').json()['user']['cacheScope']
    assert first != second
    assert client.get('/api/feedback', headers=MARKER).status_code == 200
    sample.list_feedback.assert_called_once(); live.list_feedback.assert_not_called()
    for call in sample.workflow_query.call_args_list:
        sql, params = call.args
        assert '.agent_quality_demo.demo_admin_events' in sql
        assert next(value.value for value in params if value.name == 'actor') == ACTOR
    assert all(call.kwargs.get('refresh') is True for call in fresh.grant.call_args_list)


def test_fresh_demo_role_is_checked_even_before_a_demo_read_cache_hit(demo):
    client, _, live, sample, fresh = demo
    select(demo)
    assert client.get('/api/my/feedback', headers=MARKER).status_code == 200
    assert client.get('/api/my/feedback', headers=MARKER).headers['X-Feedback-Cache'] == 'HIT'
    fresh.grant.side_effect = None; fresh.grant.return_value = {'role': 'reviewer'}
    assert client.get('/api/my/feedback', headers=MARKER).status_code == 403
    assert client.post('/api/demo-admin/persona', headers=ACTION, json={'email': 'quality.reviewer@example.test'}).status_code == 403
    sample.list_my_feedback.assert_called_once(); live.list_my_feedback.assert_not_called()


def test_authorization_storage_outage_does_not_restore_live_for_a_demo_marked_request_or_hide_the_outage(demo):
    client, _, live, sample, fresh = demo
    select(demo)
    fresh.grant.side_effect = HTTPException(503, 'Application authorization is temporarily unavailable')
    assert client.get('/api/my/feedback', headers=MARKER).status_code == 503
    assert client.get('/api/auth/me').status_code == 503
    live.list_my_feedback.assert_not_called(); sample.list_my_feedback.assert_not_called()


def test_exit_restores_actual_google_user_and_stays_available_after_demo_role_revocation(demo):
    client, token, live, sample, _ = demo
    select(demo)
    token.grants[ACTOR]['role'] = 'reporter'
    assert client.get('/api/my/feedback', headers=MARKER).status_code == 403
    response = client.post('/api/demo-admin/logout', headers=ACTION, json={})
    assert response.status_code == 200 and response.json()['realUser']['email'] == ACTOR
    assert response.json()['realUser']['role'] == 'reporter' and not response.json()['realUser'].get('demoMode')
    assert 'Max-Age=0' in response.headers['set-cookie']
    client.cookies.clear()
    assert client.get('/api/my/feedback').status_code == 200
    live.list_my_feedback.assert_called_once(); sample.list_my_feedback.assert_not_called()


def test_explicit_unmarked_auth_refresh_can_clear_an_expired_cookie_but_data_requests_cannot(demo):
    client, _, live, _, _ = demo
    client.cookies.set(role_demo.COOKIE, signed_cookie(exp=1))
    assert client.get('/api/my/feedback', headers=MARKER).status_code == 401
    response = client.get('/api/auth/me')
    assert response.status_code == 200 and response.json()['email'] == ACTOR and not response.json().get('demoMode')
    assert 'Max-Age=0' in response.headers['set-cookie']
    live.list_my_feedback.assert_not_called()


@pytest.mark.parametrize('headers', [{}, {**ACTION, 'Origin': 'https://evil.example'},
    {'Origin': ORIGIN, 'X-Feedback-CSRF': '1'}, {**ACTION, 'Sec-Fetch-Site': 'cross-site'}])
def test_demo_mutations_require_exact_origin_and_action_headers(demo, headers):
    client, _, _, sample, _ = demo
    assert client.post('/api/demo-admin/persona', headers=headers, json={'email': 'alex.requester@example.test'}).status_code == 403
    sample.workflow_query.assert_not_called()


def test_demo_personas_cannot_administer_real_grants_or_real_connections_or_evaluations(demo):
    client, _, live, sample, fresh = demo
    select(demo, 'quality.reviewer@example.test')
    assert client.get('/api/access-grants', headers=MARKER).status_code == 403
    for path in ['/api/agent-environments', '/api/agent-environments/neo-nonprod/test', '/api/admin/bigquery/init', '/api/evaluations']:
        assert client.post(path, headers={**ACTION, **MARKER}, json={}).status_code == 409
    fresh.list_grants.assert_not_called(); sample.create_evaluation.assert_not_called(); live.ensure_schema.assert_not_called()


def test_demo_promotion_uses_fixed_sample_target_without_live_endpoint_validation(demo,monkeypatch):
    client,_,_,sample,_=demo
    select(demo,'quality.reviewer@example.test')
    row={'id':'neo-prod','agent_id':'neo-rules-agent','name':'Production','kind':'prod','url':'https://demo.invalid/prod',
        'auth':'none','protocol':'quality_json','enabled':True,'revision':1}
    sample.get_agent_environment.return_value=row
    sample.create_promotion.return_value={'id':'PROM-DEMO','requestedBy':ACTOR,'counts':{'queued':0}}
    sample.get_promotion.return_value={'id':'PROM-DEMO','requestedBy':ACTOR,'counts':{'queued':0}}
    monkeypatch.setattr('app.agent_targets.validate_environment_target',lambda *_args: (_ for _ in ()).throw(AssertionError('No real endpoint is validated')))
    monkeypatch.setattr('app.demo_simulation.drain',lambda _repo:None)
    response=client.post('/api/promotions',headers={**ACTION,**MARKER},json={'feedback_ids':['FDB-DEMO'],
        'filters':{'environment_id':'neo-nonprod'},'target_id':'neo-prod','selection_token':'x'*64,'idempotency_key':'demo-promotion-1'})
    assert response.status_code==202,response.text
    sample.create_promotion.assert_called_once()
    assert sample.create_promotion.call_args.args[0].target_id=='neo-prod'


def test_demo_cannot_edit_or_confirm_a_real_feedback_id_and_demo_reporters_are_owner_scoped(demo):
    client, _, live, sample, _ = demo
    select(demo)
    assert client.get('/api/my/feedback/FDB-REAL', headers=MARKER).status_code == 404
    assert client.patch('/api/my/feedback/FDB-REAL', headers={**ACTION, **MARKER}, json={'title': 'Forged owner'}).status_code == 404
    assert client.post('/api/my/feedback/FDB-REAL/retests/REAL-JOB/confirmation', headers={**ACTION, **MARKER}, json={'verdict': 'fixed'}).status_code == 404
    live.get_feedback.assert_not_called(); live.confirm_retest.assert_not_called(); sample.confirm_retest.assert_not_called()


def test_demo_own_confirmation_keeps_auditor_and_owner_separate(demo, monkeypatch):
    client, _, _, sample, _ = demo
    select(demo)
    sample.get_my_feedback.return_value = _public_record('FDB-DEMO', 'Alex')
    sample.get_feedback.return_value = record(id='FDB-DEMO', reporter='alex.requester@example.test')
    sample.confirm_retest.return_value = _public_record('FDB-DEMO', 'Alex')
    monkeypatch.setattr('app.main.finish_demo_work', lambda _repo: None)
    response = client.post('/api/my/feedback/FDB-DEMO/retests/DEMO-JOB/confirmation', headers={**ACTION, **MARKER}, json={'verdict': 'fixed'})
    assert response.status_code == 200
    args = sample.confirm_retest.call_args.args
    assert args[2] == ['alex.requester@example.test'] and args[3] == ACTOR


def test_reset_requires_a_valid_cookie_before_it_changes_only_demo_data(demo, monkeypatch):
    client, _, live, sample, _ = demo
    reset = Mock(return_value={'reset': True, 'dataset': 'agent_quality_demo', 'simulatedAi': True, 'seededFeedback': 3})
    monkeypatch.setattr('app.demo_simulation.reset_demo', reset)
    assert client.post('/api/demo-admin/reset', headers=ACTION, json={'confirmation': 'RESET DEMO'}).status_code == 401
    select(demo)
    assert client.post('/api/demo-admin/reset', headers=ACTION, json={'confirmation': 'yes'}).status_code == 400
    reset.assert_not_called()
    response = client.post('/api/demo-admin/reset', headers=ACTION, json={'confirmation': 'RESET DEMO'})
    assert response.status_code == 200 and response.json()['dataset'] == 'agent_quality_demo'
    assert response.json()['session']['user']['email'] == 'alex.requester@example.test'
    reset.assert_called_once_with(sample, ACTOR); live.workflow_query.assert_not_called()
    client.cookies.clear(); client.cookies.set(role_demo.COOKIE, signed_cookie(exp=1))
    assert client.post('/api/demo-admin/reset', headers=ACTION, json={'confirmation': 'RESET DEMO'}).status_code == 401
    reset.assert_called_once()


def test_repository_and_primary_access_lookup_use_different_scopes_without_settings_mutation(demo):
    before = dict(settings.__dict__)
    live = BigQueryRepository(client=Mock())
    primary = access_table_ref()
    with demo_scope():
        sample = BigQueryRepository(client=Mock())
        assert sample.dataset_ref.endswith('.agent_quality_demo')
        assert access_table_ref() == primary and primary.endswith('.agent_quality.application_access_grants')
    assert live.dataset_ref.endswith('.agent_quality') and settings.__dict__ == before and not is_demo()


def test_context_isolated_across_concurrent_tasks_nested_scopes_and_threadpool_calls(demo):
    async def inspect(want_demo):
        async def values():
            await asyncio.sleep(0)
            value = await run_in_threadpool(lambda: BigQueryRepository(client=Mock()).dataset_ref)
            assert is_demo() is want_demo
            return value
        if want_demo:
            with demo_scope():
                with demo_scope(): assert is_demo()
                return await values()
        return await values()
    async def run(): return await asyncio.gather(*(inspect(index % 2 == 0) for index in range(20)))
    values = asyncio.run(run())
    assert all(value.endswith('.agent_quality_demo' if index % 2 == 0 else '.agent_quality') for index, value in enumerate(values))
    assert not is_demo()
    with pytest.raises(ValueError):
        with demo_scope(): raise ValueError('scope cleanup')
    assert not is_demo()


def test_concurrent_api_requests_never_share_demo_context_or_cache(demo):
    client, token, live, sample, _ = demo
    select(demo, 'quality.reviewer@example.test')
    barrier = Barrier(2)
    def metric(want_demo):
        def result():
            barrier.wait(timeout=10)
            assert is_demo() is want_demo
            return {'feedback_total': 3 if want_demo else 156}
        return result
    live.overview.side_effect = metric(False); sample.overview.side_effect = metric(True)
    real = TestClient(app, base_url=ORIGIN, headers={'X-Feedback-IAP-Assertion': token()})
    with ThreadPoolExecutor(max_workers=2) as pool:
        simulated = pool.submit(client.get, '/api/overview', headers=MARKER)
        actual = pool.submit(real.get, '/api/overview')
        assert simulated.result().json()['feedback_total'] == 3
        assert actual.result().json()['feedback_total'] == 156
    assert not is_demo()


def test_simulation_factories_never_call_real_models_agents_embeddings_graph_or_evaluation(demo):
    from app.agent_targets import agent_targets, invoke_agent
    from app.document_evidence import get_document_evidence_index
    from app.evaluation import run_evaluation
    from app.root_cause import _gateway_token, assess_correction, suggest_root_cause
    with patch('app.agent_targets.httpx.Client', side_effect=AssertionError('No real agent')), \
        patch('app.root_cause.httpx.post', side_effect=AssertionError('No real model')), \
        patch('app.document_evidence._cached_document_evidence_index', side_effect=AssertionError('No real graph')):
        with demo_scope():
            answer = invoke_agent(agent_targets()[0], 'Sample question', 'DEMO-1')
            assert answer['modelVersion'] == 'demo-simulated' and 'SIMULATED' in answer['answer']
            assert get_document_evidence_index().stats()['simulated'] is True
            rca = suggest_root_cause({'prompt': 'Sample'})
            assert rca['rca_review_required'] and not rca['rca_auto_accepted'] and 'SIMULATION' in rca['rca_rationale']
            assert assess_correction({'prompt': 'Q', 'generatedAnswer': 'old'}, {'prompt': 'Q', 'generatedAnswer': 'new'}, [])['reviewRequired']
            with pytest.raises(RuntimeError): _gateway_token()
            with pytest.raises(RuntimeError): run_evaluation('DEMO-EVALUATION')


def test_simulation_requires_the_demo_repository_and_never_starts_a_worker_or_toggles_the_flag(demo):
    from app.demo_simulation import drain, reset_demo
    _, _, live, sample, _ = demo
    with demo_scope():
        for action in [lambda: drain(live), lambda: reset_demo(live, ACTOR)]:
            with pytest.raises(RuntimeError): action()
        sample.claim_feedback_job.side_effect = [{'id': 'DEMO-JOB'}, None]
        with patch('app.workflow_worker.process_feedback_job') as process:
            drain(sample)
            process.assert_called_once_with(sample, {'id': 'DEMO-JOB'})
    with patch('app.main.feedback_worker.start') as start:
        with TestClient(app): pass
        start.assert_not_called()
    assert settings.workflow_worker_enabled is False


@pytest.mark.parametrize('field,value', [('role_demo_enabled', False), ('auth_mode', 'mock'), ('dataset', 'agent_quality_demo'),
    ('demo_frontend_origin', 'https://user:password@evil.example')])
def test_invalid_feature_configuration_fails_closed(demo, monkeypatch, field, value):
    monkeypatch.setitem(settings.__dict__, field, value)
    with pytest.raises(HTTPException): role_demo.require_enabled()


def test_obsolete_public_password_auth_mode_is_retired_and_never_enabled_on_cloud_run():
    result = subprocess.run([sys.executable, '-c', 'import app.auth'], capture_output=True, text=True,
        env={**os.environ, 'K_SERVICE': 'neo-feedback-demo-api', 'FEEDBACK_APP_ENV': 'sandbox', 'FEEDBACK_AUTH_MODE': 'demo_admin'})
    assert result.returncode != 0 and 'retired' in result.stderr


def test_self_role_change_protection_still_applies_to_demo_admin(demo):
    from datetime import datetime, timezone
    db = Mock(); repo = AccessGrantRepository(db)
    with pytest.raises(HTTPException) as error:
        repo.save_grant(ACTOR, AccessGrantUpdate(role='demo_admin', expected_updated_at=datetime.now(timezone.utc)), ACTOR, create=False)
    assert error.value.status_code == 409; db.query.assert_not_called()
