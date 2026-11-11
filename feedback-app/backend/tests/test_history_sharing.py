import json
from unittest.mock import Mock

import pytest

from app.bigquery import BigQueryRepository


@pytest.mark.parametrize("assessment", ["appears_fixed", "still_incorrect", "inconclusive"])
def test_all_retest_answers_and_verdicts_are_automatic_but_raw_evidence_is_private(assessment):
    client = Mock()
    original = {"id": "original:FDB-1", "attempt_id": None, "payload_json": json.dumps({
        "kind": "original", "question": "Submitted question", "answer": "Submitted answer",
        "environment": "unknown", "revision": 1, "privateTrace": {"messages": ["private"]},
        "reviewerNotes": "Private reviewer comment", "sources": [{"context": "Raw document text"}],
    })}
    updated = {"id": "answer:JOB-1", "attempt_id": "JOB-1", "payload_json": json.dumps({
        "kind": "retest", "question": "Submitted question", "answer": "Fresh agent answer", "environment": "nonprod", "revision": 1,
        "privateTrace": {"messages": ["Private raw tool result"]}, "sources": [{"context": "Raw document text"}],
    })}
    job = {"id": "JOB-1", "kind": "retest", "status": "completed", "environment": "nonprod", "revision": 1,
        "published_at": None, "result_json": json.dumps({"assessment": assessment, "reason": "Automated comparison reason", "reviewRequired": False, "privateNotes": "Private reviewer comment"}),
        "payload_json": "Private internal job payload", "lease_token": "Private lease token"}
    diagnosis = {"id": "rca:JOB-1", "attempt_id": "JOB-1", "payload_json": json.dumps({"category": "reasoning_error",
        "rationale": "Suggested cause", "verified": False, "answerId": "answer:JOB-1", "evidence": [{"context": "Raw document text"}]})}
    client.query.return_value.result.return_value = [{"allowed_count": 1, "pending_retest_count": 0, "latest_confirmable_id": "JOB-1",
        "jobs_json": [json.dumps(job)], "answers_json": [json.dumps(original), json.dumps(updated)], "diagnoses_json": [json.dumps(diagnosis)]}]
    repo = BigQueryRepository(client=client)
    history = repo.feedback_history("FDB-1", ["owner@example.test"])
    assert history["sharingPolicy"] == "automatic"
    assert "unsharedRetestCount" not in history
    assert history["latestConfirmableAttemptId"] == "JOB-1"
    assert history["answers"][0]["answer"] == "Submitted answer"
    assert history["answers"][1]["answer"] == "Fresh agent answer"
    assert history["answers"][1]["environment"] == "nonprod"
    assert history["attempts"][0]["assessment"] == assessment
    assert history["attempts"][0]["automaticallyShared"] is True
    assert history["attempts"][0]["assessmentVerified"] is False
    assert history["attempts"][0]["reviewRequired"] is True
    assert history["attempts"][0]["resultAvailable"] is True
    assert history["attempts"][0]["sharedAt"] is None  # No manual publication is required.
    assert history["diagnoses"][0]["verified"] is False
    serialized = json.dumps(history)
    assert "privateTrace" not in serialized and "Private reviewer comment" not in serialized and "Raw document text" not in serialized
    assert "Private internal job payload" not in serialized and "Private lease token" not in serialized
    sql = client.query.call_args.args[0]
    assert "LOWER(TRIM(f.reporter)) IN UNNEST(@reporters)" in sql
    assert "j.kind != 'retest' OR j.published_at IS NOT NULL" not in sql
    assert "j.published_at IS NULL" not in sql
    assert repo._same_environment('a', 'j') in sql and "j.revision = a.revision" in sql
    assert f"LEFT JOIN `{repo.workflow_table('feedback_main_environments')}` m" in sql and "COALESCE(NULLIF(a.main_environment_kind" in sql
    assert "ORDER BY IF(JSON_VALUE(v.payload_json, '$.kind') = 'original', 0, 1), v.created_at DESC" in sql
    assert "UPDATE " not in sql  # Viewing history cannot mutate workflow or resolve a report.


def test_another_reporter_still_cannot_read_any_automatically_available_result():
    client = Mock()
    client.query.return_value.result.return_value = [{"allowed_count": 0, "pending_retest_count": 99,
        "jobs_json": [], "answers_json": [], "diagnoses_json": []}]
    with pytest.raises(KeyError, match="not found"):
        BigQueryRepository(client=client).feedback_history("FDB-OTHER", ["other@example.test"])


def test_old_or_empty_history_has_automatic_policy_without_invented_results():
    client = Mock()
    client.query.return_value.result.return_value = [{"allowed_count": 1, "jobs_json": [], "answers_json": [], "diagnoses_json": []}]
    history = BigQueryRepository(client=client).feedback_history("FDB-1", ["owner@example.test"])
    assert history == {"answers": [], "diagnoses": [], "attempts": [], "sharingPolicy": "automatic",
                       "pendingRetestCount": 0, "latestConfirmableAttemptId": None, "historyLimit": 100}


def test_a_saved_answer_remains_visible_when_its_later_assessment_fails():
    client = Mock()
    answer = {"id": "answer:JOB-FAILED", "attempt_id": "JOB-FAILED", "payload_json": json.dumps({"kind": "retest", "answer": "Actual captured response", "environment": "nonprod", "revision": 1})}
    job = {"id": "JOB-FAILED", "kind": "retest", "status": "failed", "environment": "nonprod", "revision": 1,
           "error": "Private internal exception detail", "result_json": "{}"}
    client.query.return_value.result.return_value = [{"allowed_count": 1, "jobs_json": [json.dumps(job)], "answers_json": [json.dumps(answer)], "diagnoses_json": []}]
    history = BigQueryRepository(client=client).feedback_history("FDB-1", ["owner@example.test"])
    assert history["answers"][0]["answer"] == "Actual captured response"
    assert history["attempts"][0]["assessment"] is None
    assert history["attempts"][0]["resultAvailable"] is True
    assert "Private internal exception detail" not in json.dumps(history)
    assert history["latestConfirmableAttemptId"] is None
