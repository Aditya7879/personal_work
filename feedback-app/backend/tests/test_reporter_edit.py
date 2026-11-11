import json
from unittest.mock import Mock, patch

import pytest
from pydantic import ValidationError

from app.bigquery import BigQueryRepository
from app.models import MyFeedbackUpdate, FeedbackRecord
from app.workflow_worker import process_feedback_job


def saved_row():
    return {"feedback_id": "FDB-EDIT", "reporter": "owner@example.test", "state": "Evidence review", "public_status": "In review",
            "created_at": "2026-10-14T00:00:00Z", "updated_at": "2026-10-14T00:00:00Z", "revision": 4,
            "title": "Original title", "question": "Original question", "answer": "Original captured answer",
            "agent_id": "neo-rules-agent", "environment": "unknown", "full_quote": "Original feedback",
            "ground_truth_hint": "Expected rule", "expected_behavior_verified": True,
            "issue_categories_json": '["legacy_xlsx_import"]', "tags_json": '["legacy_xlsx_import"]', "source": "legacy_xlsx_import",
            "run_context_json": '{"source":"legacy_xlsx_import","sub_domain":"Legacy subdomain","developer_remarks":"Reviewer-only secret"}'}


def edit_repo(row):
    client = Mock()
    read = Mock(); read.result.return_value = [row] if row else []
    write = Mock(); write.result.return_value = []
    client.query.side_effect = [read, write]
    return BigQueryRepository(client=client), client


def test_all_submitted_fields_are_editable_and_capture_a_new_version_atomically():
    repo, client = edit_repo(saved_row())
    payload = MyFeedbackUpdate(expected_revision=4, title="Corrected title", question="Corrected question", answer="Corrected captured response",
        agent_id="neo-rules-agent", agent_version="release-2", run_id="run-2", conversation_id="conversation-2",
        business_domain="F2S", business_subdomain="Batch management", environment="nonprod",
        feedback_text="Corrected feedback", expected_behavior="Correct expectation", user_verdict="Partially correct",
        issue_categories=["Missing information"], impact="High", data_source="Training docs", language="English", follow_up="New follow-up")
    with patch.object(repo, "get_my_feedback", return_value={"id": "FDB-EDIT"}):
        repo.update_my_feedback("FDB-EDIT", ["demo@example.test", "owner@example.test"], payload, actor="demo@example.test")
    sql = client.query.call_args.args[0]
    assert "BEGIN TRANSACTION" in sql and "COMMIT TRANSACTION" in sql
    assert "LOWER(TRIM(f.reporter)) IN UNNEST(@reporters)" in sql
    assert "COALESCE(revision, 1) = @expected_revision" in sql
    assert "NOT IN UNNEST(@closed_states)" in sql and "NOT IN UNNEST(@closed_statuses)" in sql
    assert "INSERT INTO" in sql and "feedback_answer_versions" in sql and "feedback_workflow_jobs" in sql
    assert "'submitter_updated'" in sql
    assert sql.count("expected_behavior_verified = FALSE") == 1
    assert "reviewer_notes =" not in sql
    parameters = client.query.call_args.kwargs["job_config"].query_parameters
    values = {parameter.name: parameter.value for parameter in parameters if hasattr(parameter, "value")}
    assert values["answer"] == "Corrected captured response"
    assert values["expected_revision"] == 4 and values["next_revision"] == 5
    original, corrected = json.loads(values["original_payload"]), json.loads(values["snapshot_payload"])
    assert original["answer"] == "Original captured answer"
    assert original["question"] == "Original question"
    assert corrected["answer"] == "Corrected captured response"
    assert corrected["question"] == "Corrected question"
    assert corrected["kind"] == "submission_edit" and corrected["revision"] == 5
    assert corrected["businessDomain"] == "F2S" and corrected["businessSubdomain"] == "Batch management"
    assert corrected["dataSource"] == "Training docs" and corrected["followUp"] == "New follow-up"
    assert "Reviewer-only secret" not in values["snapshot_payload"]
    queued = json.loads(values["job_payload"])
    assert queued["generatedAnswer"] == "Corrected captured response"
    assert queued["runContext"]["submission_answer_id"] == "submission:FDB-EDIT:r5"
    assert queued["expectedBehaviorVerified"] is False
    assert queued["issueCategories"] == ["Missing information"]
    assert json.loads(values["event_payload"])["answer_version_id"] == "submission:FDB-EDIT:r5"


def test_a_stale_revision_is_rejected_without_writing():
    repo, client = edit_repo(saved_row())
    with pytest.raises(ValueError, match="changed while you were editing"):
        repo.update_my_feedback("FDB-EDIT", ["owner@example.test"], MyFeedbackUpdate(answer="Edited", expected_revision=3), "owner@example.test")
    client.query.assert_called_once()


def test_other_owners_and_closed_reviews_cannot_edit_captured_responses():
    repo, client = edit_repo(None)
    assert repo.update_my_feedback("FDB-EDIT", ["other@example.test"], MyFeedbackUpdate(answer="Edited"), "other@example.test") is None
    client.query.assert_called_once()
    for status in ("Resolved", "Awaiting your confirmation", "Retesting"):
        repo, client = edit_repo({**saved_row(), "public_status": status})
        with pytest.raises(ValueError, match="review is closed"):
            repo.update_my_feedback("FDB-EDIT", ["owner@example.test"], MyFeedbackUpdate(answer="Edited"), "owner@example.test")
        client.query.assert_called_once()


@pytest.mark.parametrize("field", ["reporter", "reviewer_notes", "public_status", "confirmed_rca", "expected_behavior_verified", "resolution_summary", "run_context"])
def test_review_decisions_identity_and_internal_context_are_not_reporter_editable(field):
    with pytest.raises(ValidationError):
        MyFeedbackUpdate.model_validate({field: "not allowed"})


def test_worker_diagnoses_the_corrected_capture_without_relabeling_the_original():
    repo = Mock()
    record = FeedbackRecord(id="FDB-EDIT", agentName="neo-rules-agent", model="model", prompt="Corrected question", generatedAnswer="Corrected captured response",
        title="Feedback", excerpt="Issue", userVerdict="Incorrect", severity="High", state="Triaged", reportedTime="now", impact="High", revision=5,
        runContext={"submission_answer_id":"submission:FDB-EDIT:r5"})
    repo._json_object.side_effect = json.loads
    repo.get_version.side_effect = [{"question":"Original question","answer":"Original capture"},
                                   {"kind":"submission_edit","question":record.prompt,"answer":record.generatedAnswer}]
    repo.get_feedback.return_value = record
    result = {"suggested_rca":"reasoning_error","rca_subcategory":"Missing rule","rca_rationale":"A source rule was missed.","suggested_rca_confidence":0.9}
    job = {"id":"JOB-EDIT","kind":"enrich","payload_json":record.model_dump_json()}
    with patch("app.workflow_worker.evidence_for", return_value=[]), patch("app.workflow_worker.suggest_root_cause", return_value=result) as diagnose:
        process_feedback_job(repo, job)
    assert diagnose.call_args.args[0]["generatedAnswer"] == "Corrected captured response"
    saved = repo.save_version.call_args.args[3]
    assert saved["answerId"] == "submission:FDB-EDIT:r5"
    repo.update_rca_suggestion.assert_called_once_with("FDB-EDIT", result, expected_revision=5,
        source_answer_id='submission:FDB-EDIT:r5', source_question=record.prompt, source_answer=record.generatedAnswer)
