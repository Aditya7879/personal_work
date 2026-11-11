from types import SimpleNamespace
from unittest.mock import Mock

from fastapi.testclient import TestClient

from app import auth
from app.config import settings
from app.main import app, repository


def _public_record(feedback_id: str, reporter: str) -> dict:
    return {
        "id": feedback_id,
        "title": "Incorrect NEO answer",
        "feedbackText": "The answer missed a required step.",
        "userVerdict": "Incorrect",
        "issueCategories": ["Missing information"],
        "publicStatus": "Received",
        "publicMessage": None,
        "submittedAt": "2026-10-09T10:00:00Z",
        "updatedAt": "2026-10-09T10:00:00Z",
        "resolutionSummary": None,
        "resolutionVersion": None,
        "resolvedAt": None,
        "events": [{
            "id": f"{feedback_id}-submitted",
            "status": "Received",
            "createdAt": "2026-10-09T10:00:00Z",
            "message": f"Feedback submitted by {reporter}.",
        }],
    }


def test_reporter_can_only_read_own_public_feedback_and_cannot_open_reviewer_api():
    fake = Mock()
    fake.list_my_feedback.return_value = ([_public_record("FDB-A", "alex.requester@example.test")], 1)
    fake.get_my_feedback.side_effect = lambda feedback_id, reporters: (
        _public_record(feedback_id, "alex.requester@example.test")
        if feedback_id == "FDB-A" and "alex.requester@example.test" in reporters else None
    )
    app.dependency_overrides[repository] = lambda: fake
    try:
        client = TestClient(app)
        login = client.post("/api/auth/mock-login", json={"email": "alex.requester@example.test"})
        token = login.json()["accessToken"]
        headers = {"Authorization": f"Bearer {token}"}

        listing = client.get("/api/my/feedback", headers=headers)
        own_item = client.get("/api/my/feedback/FDB-A", headers=headers)
        other_item = client.get("/api/my/feedback/FDB-B", headers=headers)
        reviewer_endpoint = client.get("/api/feedback", headers=headers)
    finally:
        app.dependency_overrides.pop(repository, None)

    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()["items"]] == ["FDB-A"]
    assert fake.list_my_feedback.call_args.args == (["alex.requester@example.test"],)
    assert own_item.status_code == 200
    assert own_item.json()["publicStatus"] == "Received"
    assert "reviewerNotes" not in own_item.json()
    assert "suggestedRcaEvidence" not in own_item.json()
    assert other_item.status_code == 404
    assert reviewer_endpoint.status_code == 403


def test_public_submission_reporter_is_taken_from_signed_in_user_not_request_body():
    fake = Mock()
    fake.create_feedback.return_value = SimpleNamespace(id="FDB-NEW")
    fake.get_my_feedback.return_value = _public_record("FDB-NEW", "alex.requester@example.test")
    fake._my_feedback_record.return_value = _public_record("FDB-NEW", "alex.requester@example.test")
    app.dependency_overrides[repository] = lambda: fake
    try:
        client = TestClient(app)
        token = client.post(
            "/api/auth/mock-login", json={"email": "alex.requester@example.test"}
        ).json()["accessToken"]
        response = client.post(
            "/api/my/feedback",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "question": "Incorrect NEO answer",
                "user_verdict": "Incorrect",
                "issue_categories": ["Missing information"],
                "feedback_text": "The answer missed a required step.",
                "reporter": "sam.requester@example.test",
                "impact": "Medium",
            },
        )
    finally:
        app.dependency_overrides.pop(repository, None)

    assert response.status_code == 201
    saved_payload = fake.create_feedback.call_args.args[0]
    assert saved_payload.reporter == "alex.requester@example.test"


def test_mock_auth_rejects_tampered_tokens():
    client = TestClient(app)
    token = client.post(
        "/api/auth/mock-login", json={"email": "alex.requester@example.test"}
    ).json()["accessToken"]
    response = client.get("/api/my/feedback", headers={"Authorization": f"Bearer {token}x"})
    assert response.status_code == 401


def test_mock_demo_scope_is_private_from_sign_in_profile():
    configured_users = '[{"email":"demo.requester@example.test","displayName":"Sample requester","role":"reporter","feedbackOwnerEmail":"employee@company.example"}]'
    old_value = settings.mock_users_json
    try:
        object.__setattr__(settings, "mock_users_json", configured_users)
        user = auth._user_for_email("demo.requester@example.test")
        visible_users = auth.list_mock_users()
    finally:
        object.__setattr__(settings, "mock_users_json", old_value)

    assert user is not None
    assert user.feedback_emails == ["demo.requester@example.test", "employee@company.example"]
    sample_user = next(user for user in visible_users if user["email"] == "demo.requester@example.test")
    assert sample_user == {"email": "demo.requester@example.test", "displayName": "Sample requester", "role": "reporter"}
    assert "employee@company.example" not in repr(visible_users)


def test_reporter_domain_status_and_search_filters_cannot_override_ownership():
    fake = Mock()
    record = {**_public_record("FDB-A", "alex.requester@example.test"), "domain": "F2S - Batch Management"}
    fake.list_my_feedback.return_value = ([record], 1)
    app.dependency_overrides[repository] = lambda: fake
    try:
        client = TestClient(app)
        token = client.post("/api/auth/mock-login", json={"email": "alex.requester@example.test"}).json()["accessToken"]
        response = client.get("/api/my/feedback", headers={"Authorization": f"Bearer {token}"}, params={
            "domain": "F2S - Batch Management", "public_status": "Received", "search": "batch",
            "page": 2, "page_size": 20, "reporter": "sam.requester@example.test",
        })
    finally:
        app.dependency_overrides.pop(repository, None)

    assert response.status_code == 200
    assert response.json()["items"][0]["domain"] == "F2S - Batch Management"
    fake.list_my_feedback.assert_called_once_with(
        ["alex.requester@example.test"], search="batch", domain="F2S - Batch Management",
        environment=None, public_status="Received", page=2, page_size=20,
    )


def test_reporter_filter_options_exclude_users_and_block_reviewer_options():
    fake = Mock()
    fake.list_feedback_filter_options.return_value = {"domains": ["F2S - Batch Management"], "reporters": ["private@company.example"]}
    app.dependency_overrides[repository] = lambda: fake
    try:
        client = TestClient(app)
        token = client.post("/api/auth/mock-login", json={"email": "alex.requester@example.test"}).json()["accessToken"]
        headers = {"Authorization": f"Bearer {token}"}
        response = client.get("/api/my/feedback/filters?reporter=sam.requester@example.test", headers=headers)
        reviewer_response = client.get("/api/feedback/filters", headers=headers)
    finally:
        app.dependency_overrides.pop(repository, None)

    assert response.status_code == 200
    assert response.json() == {"domains": ["F2S - Batch Management"]}
    assert reviewer_response.status_code == 403
    fake.list_feedback_filter_options.assert_called_once_with(reporter=["alex.requester@example.test"])
    fake.get_my_feedback.assert_not_called()
    assert "private@company.example" not in response.text


def test_demo_filter_options_preserve_the_private_existing_feedback_scope():
    configured = '[{"email":"demo.requester@example.test","displayName":"Sample requester","role":"reporter","feedbackOwnerEmail":"private@company.example"}]'
    old_value = settings.mock_users_json
    fake = Mock()
    fake.list_feedback_filter_options.return_value = {"domains": ["O2C - Credit Management"]}
    app.dependency_overrides[repository] = lambda: fake
    try:
        object.__setattr__(settings, "mock_users_json", configured)
        client = TestClient(app)
        login = client.post("/api/auth/mock-login", json={"email": "demo.requester@example.test"})
        response = client.get("/api/my/feedback/filters", headers={"Authorization": f"Bearer {login.json()['accessToken']}"})
    finally:
        object.__setattr__(settings, "mock_users_json", old_value)
        app.dependency_overrides.pop(repository, None)

    assert response.status_code == 200
    fake.list_feedback_filter_options.assert_called_once_with(reporter=["demo.requester@example.test", "private@company.example"])
    assert "private@company.example" not in login.text
    assert "private@company.example" not in response.text


def test_reviewer_can_combine_user_domain_public_status_and_review_state_filters():
    fake = Mock()
    fake.list_feedback.return_value = ([], 0)
    app.dependency_overrides[repository] = lambda: fake
    try:
        client = TestClient(app)
        token = client.post("/api/auth/mock-login", json={"email": "quality.reviewer@example.test"}).json()["accessToken"]
        response = client.get("/api/feedback", headers={"Authorization": f"Bearer {token}"}, params={
            "reporter": "alex.requester@example.test", "domain": "F2S - Batch Management",
            "public_status": "In review", "state": "Triaged", "page": 2,
        })
    finally:
        app.dependency_overrides.pop(repository, None)

    assert response.status_code == 200
    fake.list_feedback.assert_called_once_with(
        state="Triaged", severity=None, verdict=None, root_cause=None,
        reporter="alex.requester@example.test", domain="F2S - Batch Management", public_status="In review",
        environment=None, search=None, page=2, page_size=25,
    )


def test_reviewer_filter_options_are_not_misrouted_as_feedback_details():
    fake = Mock()
    fake.list_feedback_filter_options.return_value = {"domains": ["F2S"], "reporters": ["alex.requester@example.test", "sam.requester@example.test"]}
    app.dependency_overrides[repository] = lambda: fake
    try:
        client = TestClient(app)
        token = client.post("/api/auth/mock-login", json={"email": "quality.reviewer@example.test"}).json()["accessToken"]
        response = client.get("/api/feedback/filters", headers={"Authorization": f"Bearer {token}"})
    finally:
        app.dependency_overrides.pop(repository, None)

    assert response.status_code == 200
    assert len(response.json()["reporters"]) == 2
    fake.list_feedback_filter_options.assert_called_once_with(include_reporters=True)
    fake.get_feedback.assert_not_called()


def test_filter_options_require_sign_in():
    client = TestClient(app)
    assert client.get("/api/my/feedback/filters").status_code == 401
    assert client.get("/api/feedback/filters").status_code == 401


def test_invalid_filter_values_are_rejected_before_querying_bigquery():
    fake = Mock()
    app.dependency_overrides[repository] = lambda: fake
    try:
        client = TestClient(app)
        token = client.post("/api/auth/mock-login", json={"email": "quality.reviewer@example.test"}).json()["accessToken"]
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/feedback", headers=headers, params={"public_status": "invalid"}).status_code == 422
        assert client.get("/api/feedback", headers=headers, params={"domain": "x" * 301}).status_code == 422
        assert client.get("/api/feedback", headers=headers, params={"reporter": "x" * 321}).status_code == 422
    finally:
        app.dependency_overrides.pop(repository, None)
    fake.list_feedback.assert_not_called()
