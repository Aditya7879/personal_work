import base64
import json
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.config import settings
from app.main import app, repository
from test_google_iam_auth import iam
from test_workflow import record


@pytest.fixture
def demo(iam, monkeypatch):
    monkeypatch.setitem(settings.__dict__, "auth_mode", "private_demo")
    monkeypatch.setitem(settings.__dict__, "app_env", "sandbox")
    monkeypatch.setitem(settings.__dict__, "private_demo_presenters", ("reviewer@company.example",))
    monkeypatch.setitem(settings.__dict__, "mock_users_json", json.dumps([{
        "email": "demo.requester@example.test", "displayName": "Sample requester (existing feedback)",
        "role": "reporter", "feedbackOwnerEmail": "private-owner@company.example"}]))
    return iam


def sign_in(client, demo, email="quality.reviewer@example.test"):
    google = {"X-Feedback-User-Authorization": "Bearer " + demo()}
    response = client.post("/api/auth/mock-login", headers=google, json={"email": email})
    assert response.status_code == 200
    return {**google, "X-Feedback-Demo-Authorization": "Bearer " + response.json()["accessToken"]}, response.json()


def public_record():
    return {"id": "FDB-1", "title": "Submitted question", "feedbackText": "An issue", "userVerdict": "Incorrect",
        "issueCategories": [], "publicStatus": "Received", "submittedAt": "2026-10-19", "updatedAt": "2026-10-19", "events": [], "canEdit": True}


def test_picker_requires_verified_explicit_presenter_not_just_cloud_invoker(demo):
    client = TestClient(app)
    assert client.get("/api/auth/mock-users").status_code == 401
    with patch.dict(settings.__dict__, {"private_demo_presenters": ()}):
        assert client.get("/api/auth/mock-users", headers={"Authorization": "Bearer " + demo()}).status_code == 403
    with patch.dict(demo.grants, {}, clear=True):
        assert client.get("/api/auth/mock-users", headers={"Authorization": "Bearer " + demo()}).status_code == 403


def test_actual_reporter_or_unsigned_identity_cannot_select_a_reviewer_persona(demo):
    client = TestClient(app)
    with patch.dict(demo.grants, {'reviewer@company.example': {'role': 'reporter', 'displayName': 'Reporter'}}):
        response = client.post("/api/auth/mock-login", headers={"Authorization": "Bearer " + demo()}, json={"email": "quality.reviewer@example.test"})
    assert response.status_code == 403
    assert client.post("/api/auth/mock-login", headers={"X-Feedback-Role": "reviewer"}, json={"email": "quality.reviewer@example.test"}).status_code == 401


def test_private_picker_preserves_original_profiles_without_exposing_private_owner(demo):
    client = TestClient(app)
    response = client.get("/api/auth/mock-users", headers={"Authorization": "Bearer " + demo()})
    assert response.status_code == 200 and len(response.json()) == 4
    assert {row['role'] for row in response.json()} == {'reporter', 'reviewer'}
    assert "private-owner" not in response.text and "feedbackOwnerEmail" not in response.text


def test_demo_session_requires_google_proof_and_is_bound_to_its_presenter(demo):
    client = TestClient(app)
    headers, login = sign_in(client, demo)
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200 and me.json()['role'] == 'reviewer' and me.json()['demoMode'] == 'private_demo'
    assert login['mode'] == 'private_demo'
    assert client.get("/api/auth/me", headers={"X-Feedback-Demo-Authorization": headers['X-Feedback-Demo-Authorization']}).status_code == 401
    grants={'reviewer@company.example': {'role': 'reviewer', 'displayName': 'Reviewer'}, 'other@company.example': {'role': 'reviewer', 'displayName': 'Other'}}
    with patch.dict(demo.grants, grants), patch.dict(settings.__dict__, {"private_demo_presenters":('reviewer@company.example','other@company.example')}):
        other = {**headers, "X-Feedback-User-Authorization": "Bearer " + demo(email='other@company.example')}
        assert client.get("/api/auth/me", headers=other).status_code == 401


def test_google_proof_alone_does_not_auto_skip_the_original_picker(demo):
    response = TestClient(app).get("/api/auth/me", headers={"Authorization": "Bearer " + demo()})
    assert response.status_code == 401 and "Choose" in response.json()['detail']


def test_session_claims_never_contain_the_private_owner_mapping(demo):
    _, login = sign_in(TestClient(app), demo, "demo.requester@example.test")
    part=login['accessToken'].split('.')[0]
    claims=json.loads(base64.urlsafe_b64decode(part+'='*(-len(part)%4)))
    assert claims['aud']=='private-demo' and claims['sub']=='demo.requester@example.test'
    assert 'private-owner' not in json.dumps(claims) and 'reviewer@company.example' not in json.dumps(claims)


def test_existing_local_mock_token_is_not_accepted_as_a_presenter_bound_session(demo):
    with patch.dict(settings.__dict__, {'auth_mode':'mock'}):
        local_token,_,_=auth.issue_mock_token('quality.reviewer@example.test')
    response=TestClient(app).get('/api/auth/me',headers={'X-Feedback-User-Authorization':'Bearer '+demo(),'X-Feedback-Demo-Authorization':'Bearer '+local_token})
    assert response.status_code==401


def test_presenter_demo_mode_is_never_enabled_for_production(demo):
    with patch.dict(settings.__dict__, {'app_env':'production'}):
        response=TestClient(app).get('/api/auth/mock-users',headers={'Authorization':'Bearer '+demo()})
    assert response.status_code==403


def test_reporter_view_keeps_scope_and_cannot_reach_reviewer_apis(demo):
    client=TestClient(app);headers,_=sign_in(client,demo,'demo.requester@example.test')
    fake=Mock();fake.list_my_feedback.return_value=([public_record()],1)
    app.dependency_overrides[repository]=lambda:fake
    try:
        response=client.get('/api/my/feedback',headers=headers)
        assert response.status_code==200
        assert fake.list_my_feedback.call_args.args[0]==['demo.requester@example.test','private-owner@company.example']
        assert not response.json()['items'][0]['canEdit']
        assert client.get('/api/feedback',headers=headers).status_code==403
    finally:app.dependency_overrides.pop(repository,None)


@pytest.mark.parametrize('operation',['edit','confirmation'])
def test_a_presenter_cannot_submit_a_real_employees_owner_action(demo,operation):
    client=TestClient(app);headers,_=sign_in(client,demo,'demo.requester@example.test')
    fake=Mock();fake.get_my_feedback.return_value=public_record();fake.get_feedback.return_value=record(reporter='private-owner@company.example')
    app.dependency_overrides[repository]=lambda:fake
    try:
        response=client.patch('/api/my/feedback/FDB-1',headers=headers,json={'feedback_text':'Changed'}) if operation=='edit' else client.post('/api/my/feedback/FDB-1/retests/JOB-1/confirmation',headers=headers,json={'verdict':'fixed'})
        assert response.status_code==403
        fake.update_my_feedback.assert_not_called();fake.confirm_retest.assert_not_called()
    finally:app.dependency_overrides.pop(repository,None)


def test_own_synthetic_demo_feedback_still_supports_the_original_edit_flow(demo):
    client=TestClient(app);headers,_=sign_in(client,demo,'alex.requester@example.test')
    fake=Mock();fake.get_my_feedback.return_value=public_record();fake.get_feedback.return_value=record(reporter='alex.requester@example.test');fake.update_my_feedback.return_value=public_record()
    app.dependency_overrides[repository]=lambda:fake
    try:
        response=client.patch('/api/my/feedback/FDB-1',headers=headers,json={'feedback_text':'Demo edit'})
        assert response.status_code==200
        assert fake.update_my_feedback.call_args.kwargs['actor']=='reviewer@company.example'
    finally:app.dependency_overrides.pop(repository,None)


def test_reviewer_demo_actions_keep_real_presenter_audit_identity_and_are_not_blanket_readonly(demo):
    client=TestClient(app);headers,_=sign_in(client,demo)
    fake=Mock();fake.update_triage.return_value=record()
    app.dependency_overrides[repository]=lambda:fake
    try:
        response=client.patch('/api/feedback/FDB-1/triage',headers=headers,json={'reviewer_notes':'Demo review'})
        assert response.status_code==200
        assert fake.update_triage.call_args.kwargs['actor']=='reviewer@company.example'
    finally:app.dependency_overrides.pop(repository,None)


def test_demo_reporter_creation_keeps_profile_ownership_and_actual_presenter_context(demo):
    client=TestClient(app);headers,_=sign_in(client,demo,'alex.requester@example.test')
    fake=Mock();fake.create_feedback.return_value=record();fake._my_feedback_record.return_value=public_record()
    app.dependency_overrides[repository]=lambda:fake
    try:
        response=client.post('/api/my/feedback',headers=headers,json={'user_verdict':'Incorrect','feedback_text':'Demo submission','reporter':'spoofed@company.example','run_context':{'private_demo_presenter':'spoofed@company.example'}})
        assert response.status_code==201
        payload=fake.create_feedback.call_args.args[0]
        assert payload.reporter=='alex.requester@example.test'
        assert payload.run_context['private_demo_presenter']=='reviewer@company.example'
        assert fake.enqueue_feedback_job.call_args.args[2]=='reviewer@company.example'
    finally:app.dependency_overrides.pop(repository,None)
