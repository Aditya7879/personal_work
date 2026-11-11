import json
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient

from app.agent_targets import agent_targets, get_target
from app.auth import AuthenticatedUser
from app.bigquery import BigQueryRepository
from app.business_domain import infer_business_domain
from app.cache import ReadCache
from app.config import settings
from app.main import app, repository
from app.models import AnswerConfirmation, FeedbackCreate, FeedbackRecord
from app.root_cause import assess_correction
from app.workflow_worker import diagnosis_payload, evidence_for, process_feedback_job


def record(**updates):
    values = dict(id="FDB-1", agentName="neo-rules-agent", model="unknown", prompt="What is the order rule?",
                  generatedAnswer="Old answer", title="Wrong order rule", excerpt="Incorrect rule", fullQuote="Incorrect rule",
                  userVerdict="Incorrect", severity="High", state="Triaged", reportedTime="2026-10-14T00:00:00Z", impact="High",
                  environment="nonprod", groundTruthHint="The cited order rule", expectedBehaviorVerified=True)
    return FeedbackRecord(**{**values, **updates})


def login(client, email="alex.requester@example.test"):
    return {"Authorization": "Bearer " + client.post("/api/auth/mock-login", json={"email": email}).json()["accessToken"]}


def test_domain_is_a_document_backed_hint_not_a_defect_label():
    suggestion = infer_business_domain("How is an O2C order created?", [{"source": "ANZ_OTC_Order_Management.pptx", "page": 4, "score": 10, "evidence_id": "D1"}])
    assert suggestion["domain"] == "O2C"
    assert suggestion["subdomain"] == "Order management"
    assert suggestion["verified"] is False
    assert suggestion["evidence"][0]["source"] == "ANZ_OTC_Order_Management.pptx"


def test_conflicting_domains_and_absent_evidence_do_not_produce_a_confident_guess():
    sources = [{"source": "ANZ_O2C_Order_Management.pptx", "score": 10}, {"source": "GCN_F2S_Batch_Management.pdf", "score": 10}]
    assert infer_business_domain("A generic question", sources)["domain"] == "Unspecified"
    assert infer_business_domain("An F2S question", sources[:1])["domain"] == "Unspecified"
    assert infer_business_domain("No documents", [])["source"] == "insufficient_evidence"


def test_business_domain_can_come_from_chunk_content_without_a_filename_code():
    suggestion = infer_business_domain("What is the order rule?", [{"source": "training.pdf", "page": 2, "context": "Order to Cash: order management and validation", "score": 10}])
    assert suggestion["domain"] == "O2C"
    assert suggestion["evidence"][0]["method"] == "retrieved_document_content"
    assert suggestion["verified"] is False


def test_title_question_and_original_answer_are_separate():
    repo = BigQueryRepository(client=Mock())
    row = repo._feedback_row(FeedbackCreate(title="Short title", question="Exact long question", answer="Original answer", environment="prod", user_verdict="Incorrect", feedback_text="Missing rule"))
    assert row["title"] == "Short title"
    assert row["question"] == "Exact long question"
    assert row["answer"] == "Original answer"
    assert row["environment"] == "prod"


def test_default_agent_targets_have_no_fake_endpoint_and_all_kinds_use_reviewer_access():
    with patch.dict(settings.__dict__, {"agent_targets_json": "", "neo_agent_api_url": ""}):
        assert all(not target.url for target in agent_targets())
        assert get_target("neo-nonprod").blocked_reason(AuthenticatedUser("quality.reviewer@example.test", "Reviewer", "reviewer"))
    targets = '[{"id":"production","environment":"prod","url":"https://agent.example/runs"}]'
    with patch.dict(settings.__dict__, {"agent_targets_json": targets}):
        target = get_target("production")
        assert target.blocked_reason(AuthenticatedUser("quality.reviewer@example.test", "Reviewer", "reviewer")) is None
        assert "Reviewer" in target.blocked_reason(AuthenticatedUser("alex.requester@example.test", "Requester", "reporter"))
        assert "url" not in target.public_dict(AuthenticatedUser("quality.reviewer@example.test", "Reviewer", "reviewer"))


@pytest.mark.parametrize("url", ["file:///etc/passwd", "http://remote.example/runs", "https://name:secret@agent.example/runs"])
def test_target_urls_are_validated(url):
    with patch.dict(settings.__dict__, {"agent_targets_json": json.dumps([{"id": "test", "environment": "nonprod", "url": url}])}):
        with pytest.raises(ValueError):
            agent_targets()


def test_cache_is_bounded_and_mutation_does_not_reinsert_an_inflight_read():
    cache = ReadCache(max_entries=1, max_bytes=20)
    generation = cache.generation
    cache.put(("alex",), b"one", "application/json", 30, generation)
    cache.put(("sam",), b"two", "application/json", 30, generation)
    assert cache.get(("alex",)) is None
    assert cache.get(("sam",)).body == b"two"
    cache.invalidate()
    cache.put(("alex",), b"stale", "application/json", 30, generation)
    assert cache.get(("alex",)) is None


def test_read_cache_is_authenticated_owner_scoped_and_includes_cors_on_hits():
    fake = Mock()
    fake.list_my_feedback.return_value = ([], 0)
    app.dependency_overrides[repository] = lambda: fake
    try:
        client = TestClient(app)
        alex, sam = login(client), login(client, "sam.requester@example.test")
        first = client.get("/api/my/feedback", headers={**alex, "Origin": "http://localhost:3000"})
        cached = client.get("/api/my/feedback", headers={**alex, "Origin": "http://localhost:3000"})
        other = client.get("/api/my/feedback", headers=sam)
        assert first.headers["X-Feedback-Cache"] == "MISS"
        assert cached.headers["X-Feedback-Cache"] == "HIT"
        assert cached.headers["access-control-allow-origin"]
        assert other.headers["X-Feedback-Cache"] == "MISS"
        assert fake.list_my_feedback.call_count == 2
        assert client.get("/api/my/feedback").status_code == 401
    finally:
        app.dependency_overrides.pop(repository, None)


def test_reporter_cannot_request_retests_or_see_another_users_history():
    fake = Mock()
    fake.get_my_feedback.return_value = None
    fake.feedback_history.side_effect = KeyError("Not owned")
    app.dependency_overrides[repository] = lambda: fake
    try:
        client = TestClient(app)
        headers = login(client)
        assert client.get("/api/my/feedback/OTHER/history", headers=headers).status_code == 404
        assert client.post("/api/feedback/FDB-1/retests", headers=headers, json={"target_id": "neo-nonprod", "idempotency_key": "unique-key"}).status_code == 403
        fake.enqueue_feedback_job.assert_not_called()
        fake.feedback_history.assert_called_once_with("OTHER", ["alex.requester@example.test"])
    finally:
        app.dependency_overrides.pop(repository, None)


def test_unconfigured_retest_fails_without_enqueuing_or_calling_an_agent():
    fake = Mock()
    fake.get_feedback.return_value = record()
    fake.get_agent_environment.return_value = {"id": "neo-nonprod", "agent_id": "neo-rules-agent", "name": "Non-production", "kind": "nonprod", "url": "", "enabled": False}
    app.dependency_overrides[repository] = lambda: fake
    try:
        client = TestClient(app)
        headers = login(client, "quality.reviewer@example.test")
        with patch.dict(settings.__dict__, {"agent_targets_json": "", "neo_agent_api_url": ""}):
            response = client.post("/api/feedback/FDB-1/retests", headers=headers, json={"target_id": "neo-nonprod", "idempotency_key": "unique-key"})
        assert response.status_code == 503
        fake.enqueue_feedback_job.assert_not_called()
    finally:
        app.dependency_overrides.pop(repository, None)


def test_fresh_retest_saves_answer_before_rca_and_never_overwrites_original():
    repo = Mock()
    original = {"question": "What is the order rule?", "answer": "Old answer"}
    new = {"answer": "New answer", "environment": "nonprod", "question": original["question"]}
    repo._json_object.side_effect = lambda value: json.loads(value)
    repo.get_version.side_effect = [original, None, new, None]
    job = {"id": "JOB-1", "kind": "retest", "target_id": "neo-nonprod", "environment": "nonprod", "payload_json": record().model_dump_json()}
    diagnosis = {"suggested_rca": "correct_but_differently_worded", "rca_rationale": "Source agrees", "suggested_rca_confidence": 0.9}
    with patch("app.workflow_worker.invoke_agent", return_value=new) as invoke, patch("app.workflow_worker.evidence_for", return_value=[{"evidence_id": "D1", "source": "O2C.pdf", "context": "rule"}]), patch("app.workflow_worker.suggest_root_cause", return_value=diagnosis), patch("app.workflow_worker.assess_correction", return_value={"assessment": "appears_fixed", "reviewRequired": True}):
        process_feedback_job(repo, job)
    assert invoke.call_args.args[2] == "JOB-1"
    assert repo.save_version.call_args_list[0].args[0] == "feedback_answer_versions"
    assert repo.save_version.call_args_list[1].args[0] == "feedback_rca_versions"
    repo.update_rca_suggestion.assert_not_called()
    repo.complete_feedback_job.assert_called_once()


def test_correction_is_inconclusive_if_inputs_changed_and_model_cannot_resolve_feedback():
    with patch("app.root_cause.httpx.post") as post:
        decision = assess_correction({"prompt": "old question", "generatedAnswer": "old"}, {"prompt": "new question", "generatedAnswer": "new"}, [{"evidence_id": "D1"}])
        assert decision["assessment"] == "inconclusive"
        assert decision["reviewRequired"] is True
        post.assert_not_called()


def test_automatic_availability_does_not_require_a_reviewed_expectation_or_positive_verdict():
    repo = BigQueryRepository(client=Mock())
    with patch.object(repo, "workflow_query") as query:
        repo.complete_feedback_job({"id": "JOB-1", "kind": "retest", "lease_token": "lease-1"}, {"assessment": "still_incorrect", "reviewRequired": True})
    sql = query.call_args.args[0]
    assert "published_at = COALESCE" in sql
    assert "lease_token = @token" in sql
    assert "expected_behavior_verified" not in sql
    assert "public_status =" not in sql and "answer =" not in sql
    values = {parameter.name: parameter.value for parameter in query.call_args.args[1] if hasattr(parameter, "value")}
    assert json.loads(values["result"])["assessment"] == "still_incorrect"


def test_user_confirmation_is_version_and_owner_scoped_and_does_not_replace_answers():
    repo = BigQueryRepository(client=Mock())
    owned = {"id": "FDB-1", "latestPublishedAttemptId": "JOB-1", "revision": 1, "environment": "nonprod"}
    job = {"id": "JOB-1", "feedback_id": "FDB-1", "kind": "retest", "status": "completed", "published_at": None, "created_at": "2026-10-15T00:00:00Z", "revision": 1, "environment": "nonprod", "public_summary": "Corrected rule", "confirmation": None}
    with patch.object(repo, "get_my_feedback", return_value=owned), patch.object(repo, "get_feedback_job", return_value=job), patch.object(repo, "latest_confirmable_retest", return_value="JOB-1"), patch.object(repo, "get_version", return_value={"answer": "Updated answer"}), patch.object(repo, "workflow_query") as query, patch.object(repo, "_insert_event"):
        repo.confirm_retest("FDB-1", "JOB-1", ["alex@example.test"], "alex@example.test", AnswerConfirmation(verdict="fixed"))
    sql = query.call_args.args[0]
    assert "IN UNNEST(@reporters)" in sql
    assert "latest_published_attempt_id = @attempt" in sql
    assert "COALESCE(f.revision, 1) = @revision" in sql
    assert repo._current_environment_kind('owner_context') + " = @environment" in sql and "NOT EXISTS" in sql
    assert "confirmation IS NULL" in sql
    assert "answer =" not in sql
    values = {item.name: item.value for item in query.call_args.args[1] if hasattr(item, "value")}
    assert values["status"] == "Resolved"


def test_old_or_other_environment_answer_cannot_be_confirmed():
    repo = BigQueryRepository(client=Mock())
    job = {"feedback_id": "FDB-1", "kind": "retest", "status": "completed", "published_at": None, "revision": 1, "environment": "nonprod"}
    with patch.object(repo, "get_my_feedback", return_value={"latestPublishedAttemptId": "JOB-NEW", "revision": 1, "environment": "nonprod"}), patch.object(repo, "get_feedback_job", return_value=job), patch.object(repo, "latest_confirmable_retest", return_value="JOB-NEW"):
        with pytest.raises(ValueError, match="latest completed answer"):
            repo.confirm_retest("FDB-1", "JOB-OLD", ["owner"], "owner", AnswerConfirmation(verdict="fixed"))
    with patch.object(repo, "get_my_feedback", return_value={"latestPublishedAttemptId": "JOB-1", "revision": 1, "environment": "prod"}), patch.object(repo, "get_feedback_job", return_value=job):
        with pytest.raises(ValueError, match="unknown or different"):
            repo.confirm_retest("FDB-1", "JOB-1", ["owner"], "owner", AnswerConfirmation(verdict="fixed"))


def test_nonfixed_user_response_requires_explanation():
    with pytest.raises(ValueError):
        AnswerConfirmation(verdict="still_incorrect")


def test_rejection_records_only_user_opinion_and_does_not_rewrite_or_rerun_rca():
    repo = BigQueryRepository(client=Mock())
    owned = {"id": "FDB-1", "latestPublishedAttemptId": "JOB-1", "revision": 1, "environment": "nonprod"}
    job = {"id": "JOB-1", "feedback_id": "FDB-1", "kind": "retest", "status": "completed", "published_at": None, "created_at": "2026-10-15T00:00:00Z", "revision": 1, "environment": "nonprod", "public_summary": "New rule", "confirmation": None}
    with patch.object(repo, "get_my_feedback", return_value=owned), patch.object(repo, "get_feedback_job", return_value=job), patch.object(repo, "latest_confirmable_retest", return_value="JOB-1"), patch.object(repo, "workflow_query") as query, patch.object(repo, "_insert_event"), patch.object(repo, "get_feedback", return_value=record()), patch.object(repo, "get_version", return_value={"answer": "Updated answer still has a defect"}), patch.object(repo, "enqueue_feedback_job") as enqueue:
        repo.confirm_retest("FDB-1", "JOB-1", ["owner"], "owner", AnswerConfirmation(verdict="still_incorrect", comment="Delivery time is still missing"))
    enqueue.assert_not_called()
    assert "confirmation_payload" in query.call_args.args[0]
    assert 'result_json =' not in query.call_args.args[0] and 'feedback_rca_versions' not in query.call_args.args[0]


def test_rca_write_is_pinned_to_input_revision():
    repo = BigQueryRepository(client=Mock())
    repo.client.query.return_value.result.return_value = [{'applied': 1}]
    result = {"suggested_rca": "reasoning_error", "suggested_rca_confidence": 0.9, "rca_rationale": "Explanation", "rca_review_required": True, "rca_suggestion_status": "sonnet_suggested"}
    with patch.object(repo, "_insert_event"), patch.object(repo, "get_feedback", return_value=record()):
        repo.update_rca_suggestion("FDB-1", result, expected_revision=2)
    assert "COALESCE(revision, 1) = @expected_revision" in repo.client.query.call_args.args[0]


def test_immutable_version_merge_never_has_a_matched_update():
    repo = BigQueryRepository(client=Mock())
    repo.client.query.return_value.result.return_value = []
    repo.save_version("feedback_answer_versions", "original:FDB-1", "FDB-1", {"answer": "original"})
    sql = repo.client.query.call_args.args[0]
    assert "WHEN NOT MATCHED THEN INSERT" in sql
    assert "WHEN MATCHED" not in sql


def test_public_history_hides_raw_evidence_and_reviewer_notes_without_a_publish_filter():
    client = Mock()
    client.query.return_value.result.return_value = [{"allowed_count": 1, "jobs_json": [], "answers_json": [], "diagnoses_json": [json.dumps({"id": "RCA-1", "attempt_id": None, "payload_json": json.dumps({"category": "reasoning_error", "rationale": "Safe explanation", "verified": False, "evidence": [{"context": "raw private evidence"}], "reviewerNotes": "private notes"})})]}]
    repo = BigQueryRepository(client=client)
    history = repo.feedback_history("FDB-1", ["alex@example.test"])
    assert not history["attempts"]
    assert "raw private evidence" not in json.dumps(history)
    assert "private notes" not in json.dumps(history)
    assert "IN UNNEST(@reporters)" in client.query.call_args.args[0]
    assert "j.kind != 'retest' OR j.published_at IS NOT NULL" not in client.query.call_args.args[0]
    assert history["sharingPolicy"] == "automatic"
    client.query.assert_called_once()


def test_rca_uses_neo4j_retrieval_when_the_agent_did_not_supply_structured_sources():
    graph = Mock()
    graph.search.return_value = [{"evidence_id": "NEO-test", "source": "O2C.pdf", "origin": "neo4j", "context": "Order rule"}]
    with patch("app.workflow_worker.get_document_evidence_index", return_value=graph):
        assert evidence_for(record()) == graph.search.return_value
    graph.search.assert_called_once_with(record().prompt, record().groundTruthHint)


def test_actual_agent_source_passages_remain_distinct_from_independent_neo4j_retrieval():
    with patch("app.workflow_worker.get_document_evidence_index") as graph:
        evidence = evidence_for(record(), [{"source": "actual-agent-source.pdf", "page": 4, "context": "Captured passage", "chunk_id": "captured-1"}])
    assert evidence[0]["origin"] == "agent_retrieval" and evidence[0]["element_id"] == "captured-1"
    graph.assert_not_called()


def test_graph_retrieval_failure_keeps_the_new_answer_and_completes_with_an_explicit_inconclusive_result():
    repo = Mock()
    original = {"question": record().prompt, "answer": "Original answer"}
    generated = {"answer": "New saved answer", "environment": "nonprod", "question": record().prompt}
    repo._json_object.side_effect = json.loads
    repo.get_version.side_effect = [original, None, generated, None]
    job = {"id": "JOB-GRAPH-FAIL", "kind": "retest", "target_id": "neo-nonprod", "environment": "nonprod", "payload_json": record().model_dump_json()}
    with patch("app.workflow_worker.invoke_agent", return_value=generated), patch("app.workflow_worker.evidence_for", side_effect=RuntimeError("private graph-password")), patch("app.root_cause._judge") as judge, patch("app.root_cause.httpx.post") as post:
        process_feedback_job(repo, job)
    judge.assert_not_called()
    post.assert_not_called()
    saved_answer, saved_diagnosis = repo.save_version.call_args_list
    assert saved_answer.args[0] == "feedback_answer_versions" and saved_answer.args[3]["answer"] == "New saved answer"
    assert saved_diagnosis.args[3]["category"] == "insufficient_evidence"
    assert saved_diagnosis.args[3]["retrievalStatus"] == "unavailable" and saved_diagnosis.args[3]["verified"] is False
    assert saved_diagnosis.args[3]["answerId"] == "answer:JOB-GRAPH-FAIL"
    result = repo.complete_feedback_job.call_args.args[1]
    assert result["assessment"] == "inconclusive" and "unavailable" in result["reason"] and result["reviewRequired"] is True
    assert "private graph-password" not in json.dumps(result) and "private graph-password" not in json.dumps(saved_diagnosis.args[3])
    repo.update_rca_suggestion.assert_not_called()


def test_domain_is_not_erased_when_graph_evidence_is_temporarily_unavailable():
    repo = Mock()
    repo._json_object.side_effect = json.loads
    repo.get_version.return_value = {"question": record().prompt, "answer": record().generatedAnswer}
    repo.get_feedback.return_value = record()
    job = {"id": "JOB-ENRICH-FAIL", "kind": "enrich", "payload_json": record().model_dump_json()}
    with patch("app.workflow_worker.evidence_for", side_effect=RuntimeError("temporarily unavailable")), patch("app.root_cause._judge") as judge:
        process_feedback_job(repo, job)
    repo.save_domain_suggestion.assert_not_called()
    judge.assert_not_called()
    assert repo.save_version.call_args.args[3]["suggestionStatus"] == "evidence_unavailable"
    assert "unavailable" in repo.complete_feedback_job.call_args.args[1]["reason"]


def test_rca_versions_record_actual_graph_provenance_not_a_legacy_or_agent_corpus_version():
    evidence = [{"origin": "neo4j", "corpus_version": "manifest-version", "source": "O2C.pdf", "chunk_id": "chunk-1", "context": "Private source passage"}]
    result = {"suggested_rca": "reasoning_error", "suggested_rca_confidence": 0.9, "rca_rationale": "Unverified explanation", "rca_evidence": evidence}
    with patch.dict(settings.__dict__, {"evidence_version": "wrong-legacy-version"}):
        diagnosis = diagnosis_payload(result, record(), "answer:JOB-1")
    assert diagnosis["corpusVersion"] == "manifest-version" and diagnosis["evidenceBackend"] == "neo4j"
    assert diagnosis["verified"] is False and diagnosis["evidence"] == evidence
    agent_evidence = [{"origin": "agent_retrieval", "source": "actual.pdf"}]
    unknown = diagnosis_payload({**result, "rca_evidence": agent_evidence}, record(), "answer:JOB-1")
    assert unknown["corpusVersion"] is None and unknown["evidenceBackend"] == "agent_retrieval"


def test_neo4j_chunks_graph_hints_and_corpus_metadata_remain_private_in_reporter_history():
    payload = {"category": "insufficient_evidence", "rationale": "The answer needs review.", "confidence": 0, "verified": False,
        "evidenceBackend": "neo4j", "corpusVersion": "private-manifest-version", "retrievalStatus": "available",
        "evidence": [{"source": "private-document.pdf", "context": "private graph chunk text", "source_uris": ["gs://private/artifact.json"], "matched_entities": ["private graph entity"]}]}
    repo = BigQueryRepository(client=Mock())
    repo.client.query.return_value.result.return_value = [{"allowed_count": 1, "jobs_json": [], "answers_json": [], "diagnoses_json": [json.dumps({"id": "rca:JOB-1", "payload_json": json.dumps(payload)})]}]
    public = repo.feedback_history("FDB-1", ["owner@example.test"])
    assert public["diagnoses"][0]["rationale"] == "The answer needs review."
    assert public["diagnoses"][0]["verified"] is False
    for private in ("private-document.pdf", "private graph chunk text", "gs://private", "private graph entity", "private-manifest-version"):
        assert private not in json.dumps(public)
    reviewer = repo.feedback_history("FDB-1")
    assert reviewer["diagnoses"][0]["evidence"] == payload["evidence"]
