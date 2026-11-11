import json
from unittest.mock import Mock, patch

import httpx
import pytest

from app.agent_errors import AGENT_ERROR_MESSAGES, AgentInvocationError
from app.agent_targets import AgentTarget, agent_targets, invoke_agent
from app.auth import AuthenticatedUser
from app.bigquery import BigQueryRepository
from app.config import settings
from app.neo_companion import parse_companion_response, private_trace
from app.workflow_worker import FeedbackWorker, process_feedback_job
from test_workflow import record


URL = "https://companion.example/global/it4it/btdp-genaiengine/v1/contexts/neo-test-np/configs/default/generations"


def ai(content, **updates):
    return {"type": "ai", "data": {"content": content, **updates}}


def response_data():
    return {"conversation_id": "provider-issued-session", "messages": [
        {"type": "human", "data": {"content": "What is the rule?"}},
        ai([{"type": "text", "text": "I will look this up."}], tool_calls=[{"id": "tool-1", "name": "search", "args": {"query": "rule"}}]),
        {"type": "tool", "data": {"name": "search", "tool_call_id": "tool-1", "status": "success", "content": "private retrieved text"}},
        ai([{"type": "text", "text": "The final answer."}, {"type": "text", "text": "Its second paragraph."}]),
    ]}


def target(**updates):
    return AgentTarget(**{"id": "neo-nonprod", "agent_id": "neo-rules-agent", "environment": "nonprod", "label": "NEO nonprod",
                          "url": URL, "protocol": "neo_companion", "timeout_seconds": 300, **updates})


def invoke_with_transport(handler, **updates):
    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    with patch("app.agent_targets.httpx.Client", return_value=client) as constructor:
        result = invoke_agent(target(**updates), "Exact submitted question", "JOB-ONE", {"conversation_id": "old", "language": "English"})
    return result, constructor


def test_companion_uses_all_text_blocks_in_the_final_ai_message():
    result = parse_companion_response(response_data())
    assert result["answer"] == "The final answer.\n\nIts second paragraph."
    assert result["conversationId"] == "provider-issued-session"
    assert result["runId"] is None and result["agentVersion"] is None
    assert result["sources"] == []  # Raw tool text is not invented source provenance.
    trace = result["privateTrace"]
    assert trace["toolCallCount"] == trace["toolResultCount"] == 1
    assert trace["toolCalls"][0]["name"] == "search"
    assert trace["toolResults"][0]["content"] == "private retrieved text"
    assert trace["messageCount"] == 4 and trace["truncated"] is False


def test_companion_also_accepts_string_content_and_actual_optional_metadata():
    result = parse_companion_response({"messages": [ai("Actual response")], "agent_version": "release-2", "model_version": "model-2",
                                       "run_id": "real-run", "corpus_version": "docs-2", "sources": [{"source": "training.pdf"}]})
    assert result["answer"] == "Actual response"
    assert result["agentVersion"] == "release-2" and result["modelVersion"] == "model-2"
    assert result["runId"] == "real-run" and result["corpusVersion"] == "docs-2"
    assert result["conversationId"] is None


@pytest.mark.parametrize("messages", [[], [ai("  ")], [ai("Preliminary", tool_calls=[{"name": "search"}])],
    [ai("Old answer"), {"type": "tool", "data": {"content": "Not the final answer"}}],
    [ai("Old answer"), ai([])], [ai("Old answer"), {"type": "human", "data": {"content": "Follow up"}}],
    [ai("Invalid call", invalid_tool_calls=[{"name": "search"}])]])
def test_missing_or_incomplete_answers_never_fall_back_to_tool_output(messages):
    with pytest.raises(AgentInvocationError) as error:
        parse_companion_response({"messages": messages})
    assert error.value.code == "incomplete"


@pytest.mark.parametrize("data", [{}, {"messages": "not a list"}, {"messages": [None]}, {"messages": [{"type": "ai", "data": None}]},
                                 {"messages": [ai("Text", tool_calls="not a list")]}])
def test_invalid_companion_shapes_fail_without_creating_an_answer(data):
    with pytest.raises(AgentInvocationError) as error:
        parse_companion_response(data)
    assert error.value.code == "response"


def test_long_answers_are_not_silently_truncated():
    with pytest.raises(AgentInvocationError) as error:
        parse_companion_response({"messages": [ai("a" * 50001)]})
    assert error.value.code == "answer_length"


def test_private_diagnostics_are_bounded_and_structured_credentials_are_redacted():
    trace = private_trace([], [{"args": {"Authorization": "Bearer never-show", "access_token": "secret-value", "query": "rule"}}],
                          [{"content": "Bearer do-not-store " + "x" * 1000000}])
    serialized = json.dumps(trace)
    assert "never-show" not in serialized and "secret-value" not in serialized and "do-not-store" not in serialized
    assert trace["toolCalls"][0]["args"]["query"] == "rule"
    assert trace["truncated"] is True and len(serialized) < 250000


def test_invocation_sends_the_exact_message_and_lets_companion_create_a_fresh_session():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=response_data())

    result, constructor = invoke_with_transport(handler)
    assert json.loads(requests[0].content) == {"message": "Exact submitted question"}
    assert requests[0].headers["Idempotency-Key"] == "JOB-ONE"
    assert requests[0].headers["Cache-Control"] == "no-cache"
    assert len(requests) == 1
    assert result["conversationId"] == "provider-issued-session" and result["protocol"] == "neo_companion"
    assert result["latencyMs"] >= 0
    assert constructor.call_args.kwargs["timeout"].read == 300
    assert constructor.call_args.kwargs["follow_redirects"] is False


def test_google_oauth_is_refreshed_on_the_backend_and_not_added_to_the_payload():
    credentials = Mock(token="private-google-access-token")
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=response_data())

    with patch("app.agent_targets.google.auth.default", return_value=(credentials, "project")):
        result, _ = invoke_with_transport(handler, auth="google_access_token")
    credentials.refresh.assert_called_once()
    assert requests[0].headers["Authorization"] == "Bearer private-google-access-token"
    assert "private-google-access-token" not in json.dumps(result)
    assert "private-google-access-token" not in requests[0].content.decode()


def test_only_the_production_companion_target_impersonates_the_configured_service_account():
    target_sa = "neo-sa-nasapmena-dv@oa-apmena-techsandbox-ap-dv.iam.gserviceaccount.com"
    source_credentials = Mock(token="source-compute-token")
    target_credentials = Mock(token="impersonated-neo-token")
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=response_data())

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    prod_target = target(id="neo-prod", environment="prod",
        url="https://companion.example/global/it4it/btdp-genaiengine/v1/contexts/neo-test/configs/default/generations",
        auth="google_access_token")
    diagnostics = {}
    with patch.dict(settings.__dict__, {"neo_companion_prod_service_account": target_sa}), \
         patch("app.agent_targets.google.auth.default", return_value=(source_credentials, "project")), \
         patch("app.agent_targets.impersonated_credentials.Credentials", return_value=target_credentials) as impersonate, \
         patch("app.agent_targets.httpx.Client", return_value=client):
        result = invoke_agent(prod_target, "Synthetic Production access check", "JOB-PROD", diagnostics=diagnostics)

    scopes = ["https://www.googleapis.com/auth/cloud-platform", "https://www.googleapis.com/auth/userinfo.email"]
    impersonate.assert_called_once_with(source_credentials=source_credentials, target_principal=target_sa,
        target_scopes=scopes, lifetime=600)
    target_credentials.refresh.assert_called_once()
    source_credentials.refresh.assert_not_called()
    assert requests[0].headers["Authorization"] == "Bearer impersonated-neo-token"
    assert json.loads(requests[0].content) == {"message": "Synthetic Production access check"}
    assert diagnostics["runtimeIdentity"]["principal"] == target_sa
    assert diagnostics["runtimeIdentity"]["impersonated"] is True
    assert "impersonated-neo-token" not in json.dumps(result)


def test_nonproduction_companion_keeps_the_current_runtime_identity_even_when_prod_impersonation_is_configured():
    source_credentials = Mock(token="source-compute-token")
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=response_data())

    client = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)
    with patch.dict(settings.__dict__, {"neo_companion_prod_service_account": "neo-sa-nasapmena-dv@oa-apmena-techsandbox-ap-dv.iam.gserviceaccount.com"}), \
         patch("app.agent_targets.google.auth.default", return_value=(source_credentials, "project")), \
         patch("app.agent_targets.impersonated_credentials.Credentials") as impersonate, \
         patch("app.agent_targets.httpx.Client", return_value=client):
        result = invoke_agent(target(auth="google_access_token"), "Synthetic Non-production check", "JOB-NONPROD")

    source_credentials.refresh.assert_called_once()
    impersonate.assert_not_called()
    assert requests[0].headers["Authorization"] == "Bearer source-compute-token"
    assert result["answer"] == "The final answer.\n\nIts second paragraph."


def test_google_credential_errors_are_sanitized_and_do_not_call_the_agent():
    with patch("app.agent_targets.google.auth.default", side_effect=RuntimeError("sensitive credential detail")), patch("app.agent_targets.httpx.Client") as client:
        with pytest.raises(AgentInvocationError) as error:
            invoke_agent(target(auth="google_access_token"), "question", "JOB-ONE")
    assert error.value.code == "authentication"
    assert "sensitive" not in str(error.value)
    client.assert_not_called()


@pytest.mark.parametrize(("status", "code"), [(401, "authentication"), (403, "permission"), (429, "rate_limit"),
    (500, "unavailable"), (502, "unavailable"), (503, "unavailable"), (408, "timeout"), (504, "timeout"), (302, "redirect"), (400, "request")])
def test_upstream_failures_are_actionable_but_never_expose_the_response_body(status, code):
    count = 0

    def handler(request):
        nonlocal count
        count += 1
        return httpx.Response(status, text="private upstream payload", headers={"Location": "https://another.example/"})

    with pytest.raises(AgentInvocationError) as error:
        invoke_with_transport(handler)
    assert error.value.code == code and "private upstream payload" not in str(error.value)
    assert count == 1  # No unverified automatic generation replay or redirect.


@pytest.mark.parametrize(("exception", "code"), [(httpx.ReadTimeout, "timeout"), (httpx.ConnectError, "network")])
def test_transport_errors_are_not_automatically_replayed(exception, code):
    requests = []

    def handler(request):
        requests.append(request)
        raise exception("private transport details", request=request)

    with pytest.raises(AgentInvocationError) as error:
        invoke_with_transport(handler)
    assert error.value.code == code and len(requests) == 1


@pytest.mark.parametrize("body", ["not JSON", "[]", "null"])
def test_non_object_json_or_invalid_json_is_a_safe_protocol_failure(body):
    with pytest.raises(AgentInvocationError) as error:
        invoke_with_transport(lambda request: httpx.Response(200, text=body))
    assert error.value.code == "response"


def test_the_existing_quality_json_protocol_is_preserved():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"answer": "Generic agent answer", "run_id": "real-run"})

    result, _ = invoke_with_transport(handler, protocol="quality_json")
    payload = json.loads(requests[0].content)
    assert payload["question"] == "Exact submitted question" and payload["environment"] == "nonprod"
    assert payload["conversation_id"] == "feedback-retest-JOB-ONE"
    assert result["answer"] == "Generic agent answer" and result["runId"] == "real-run"


def test_target_protocol_and_nonprod_context_are_server_owned_and_validated():
    config = {"id": "neo-nonprod", "environment": "nonprod", "url": URL, "auth": "google_access_token", "protocol": "neo_companion"}
    with patch.dict(settings.__dict__, {"agent_targets_json": json.dumps([config])}):
        configured = agent_targets()[0]
        assert configured.timeout_seconds == 300
        safe = configured.public_dict(AuthenticatedUser("reviewer@example.test", "Reviewer", "reviewer"))
        assert safe["canRetest"] is True and "url" not in safe and "auth" not in safe
        assert safe["protocol"] == "neo_companion"
    for changes in ({"protocol": "unknown"}, {"auth": "none"}, {"environment": "prod"}, {"url": "https://companion.example/api/agent/runs"},
                    {"timeout_seconds": 0}, {"timeout_seconds": 601}, {"timeout_seconds": True}, {"timeout_seconds": "300"}):
        with patch.dict(settings.__dict__, {"agent_targets_json": json.dumps([{**config, **changes}])}):
            with pytest.raises(ValueError):
                agent_targets()


def test_private_companion_trace_is_available_to_reviewers_but_filtered_from_public_history():
    version = {"id": "answer:JOB-ONE", "attempt_id": "JOB-ONE", "payload_json": json.dumps({"kind": "retest", "answer": "Safe published answer",
        "conversationId": "real-session", "latencyMs": 1200, "protocol": "neo_companion", "privateTrace": {"messages": ["reviewer-only trace"]},
        "sources": [{"context": "private document text"}]})}
    repo = BigQueryRepository(client=Mock())
    repo.client.query.return_value.result.return_value = [{"allowed_count": 1, "jobs_json": [], "answers_json": [json.dumps(version)], "diagnoses_json": []}]
    private = repo.feedback_history("FDB-1")
    assert private["answers"][0]["privateTrace"]["messages"] == ["reviewer-only trace"]
    public = repo.feedback_history("FDB-1", ["owner@example.test"])
    assert "reviewer-only trace" not in json.dumps(public) and "private document text" not in json.dumps(public)
    assert public["answers"][0]["conversationId"] == "real-session" and public["answers"][0]["latencyMs"] == 1200


def test_recovering_an_attempt_reuses_the_saved_response_instead_of_calling_companion_again():
    repo = Mock()
    repo._json_object.side_effect = json.loads
    original = {"question": record().prompt, "answer": "Original"}
    saved = {"question": record().prompt, "answer": "Already saved", "privateTrace": {"messages": ["old trace"]}}
    repo.get_version.side_effect = [original, saved, {"verified": False}]
    job = {"id": "JOB-ONE", "kind": "retest", "target_id": "neo-nonprod", "environment": "nonprod", "payload_json": record().model_dump_json()}
    with patch("app.workflow_worker.get_target", return_value=target()), patch("app.workflow_worker.invoke_agent") as invoke, patch("app.workflow_worker.evidence_for", return_value=[]), patch("app.workflow_worker.assess_correction", return_value={"assessment": "inconclusive", "reviewRequired": True}):
        process_feedback_job(repo, job)
    invoke.assert_not_called()
    repo.save_version.assert_not_called()
    repo.complete_feedback_job.assert_called_once()


def test_worker_persists_only_the_safe_invocation_error():
    repo, worker = Mock(), FeedbackWorker()
    repo.reconcile_auto_shared_retest.return_value = False
    job = {"id": "JOB-ONE", "lease_token": "lease-one"}
    repo.claim_feedback_job.return_value = job

    def fail(*args):
        worker.stop_event.set()
        raise AgentInvocationError("permission")

    with patch("app.workflow_worker.BigQueryRepository", return_value=repo), patch("app.workflow_worker.process_feedback_job", side_effect=fail):
        worker.run()
    repo.complete_feedback_job.assert_called_once_with(job, error=AGENT_ERROR_MESSAGES["permission"])
    assert repo.renew_feedback_lease.call_count == 0
    assert BigQueryRepository.safe_job({**job, "status": "failed", "error": "raw secret detail"})["error"] != "raw secret detail"
    assert BigQueryRepository.safe_job({**job, "status": "failed", "error": AGENT_ERROR_MESSAGES["permission"]})["error"] == AGENT_ERROR_MESSAGES["permission"]
