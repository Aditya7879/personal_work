import json
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient
from google.api_core.exceptions import Conflict, Forbidden

from app.bigquery import BigQueryRepository
from app.main import app, repository
from app.models import AnswerConfirmation
from app.workflow_worker import FeedbackWorker


@pytest.mark.parametrize("assessment", ["appears_fixed", "still_incorrect", "inconclusive"])
def test_completed_retest_is_finalized_notified_and_audited_once_without_any_review_gate(assessment):
    repo = BigQueryRepository(client=Mock())
    with patch.object(repo, "workflow_query") as query:
        repo.complete_feedback_job({"id": "JOB-AUTO", "kind": "retest", "lease_token": "lease-owner"},
                                   {"assessment": assessment, "reason": "Automated verdict", "reviewRequired": True})
    sql, parameters = query.call_args.args
    assert "BEGIN TRANSACTION" in sql and "COMMIT TRANSACTION" in sql
    assert "status = 'completed', result_json = @result" in sql
    assert "j.status = 'running' AND j.lease_token = @token" in sql
    assert "IF @@row_count = 1 THEN" in sql
    assert "feedback_notifications" in sql and "ON n.id = s.id" in sql
    assert "retest_result_available" in sql and "CONCAT('auto-result:', j.id)" in sql
    assert "'system:auto_share'" in sql
    assert "expected_behavior_verified" not in sql
    assert "public_status =" not in sql and "public_message =" not in sql and "resolution_summary =" not in sql
    assert "answer =" not in sql and "user_verdict =" not in sql
    assert repo._same_environment('s', 'j') in sql and 'CREATE TEMP TABLE main_scope' in sql
    assert 's.revision=j.revision' in sql and 'MAIN_ENVIRONMENT_CHANGED' in sql
    assert "newer.created_at" in sql and "newer.id > j.id" in sql  # Out-of-order completions do not rewind the pointer.
    assert "NULLIF(TRIM(f.reporter), '') IS NOT NULL" in sql
    assert "av.id = CONCAT('answer:', j.id)" in sql
    values = {parameter.name: parameter.value for parameter in parameters}
    assert values["token"] == "lease-owner" and json.loads(values["result"])["assessment"] == assessment


def test_failed_completion_preserves_the_safe_error_without_inventing_a_verdict():
    repo = BigQueryRepository(client=Mock())
    with patch.object(repo, "workflow_query") as query, patch.object(repo, "auto_share_retest_result") as share:
        repo.complete_feedback_job({"id": "JOB-AUTO", "kind": "retest", "lease_token": "lease-owner"}, error="Safe failure message")
    share.assert_not_called()
    values = {parameter.name: parameter.value for parameter in query.call_args.args[1]}
    assert values["status"] == "failed" and values["error"] == "Safe failure message"
    assert json.loads(values["result"]) == {}


def test_reconciliation_recovers_existing_answers_without_replacing_a_verdict_or_generating_again():
    repo = BigQueryRepository(client=Mock())
    with patch.object(repo, "workflow_query", side_effect=[[{"id": "JOB-OLD"}], []]) as query:
        assert repo.reconcile_auto_shared_retest() is True
    selection, transaction = [call.args[0] for call in query.call_args_list]
    assert "j.status IN ('completed', 'failed')" in selection
    assert "j.published_at IS NULL" in selection and "av.id = CONCAT('answer:', j.id)" in selection
    assert "j.status IN ('completed', 'failed') AND j.published_at IS NULL" in transaction
    assert "result_json = @result" not in transaction and "SET status =" not in transaction
    assert "WHEN NOT MATCHED THEN INSERT" in transaction
    with patch.object(repo, "workflow_query", return_value=[]) as query:
        assert repo.reconcile_auto_shared_retest() is False
        query.assert_called_once()


def test_storage_conflicts_retry_the_same_idempotent_transaction_without_generation():
    repo = BigQueryRepository(client=Mock())
    with patch.object(repo, "workflow_query", side_effect=[Conflict("Concurrent DML"), []]) as query, patch("app.workflow_repository.time.sleep") as wait:
        repo.auto_share_retest_result("JOB-AUTO", {"assessment": "inconclusive"}, "lease-owner")
    assert query.call_count == 2
    assert query.call_args_list[0] == query.call_args_list[1]
    wait.assert_called_once_with(0.2)


def test_permission_errors_are_not_retried_as_storage_conflicts():
    repo = BigQueryRepository(client=Mock())
    with patch.object(repo, "workflow_query", side_effect=Forbidden("Not authorized")) as query, patch("app.workflow_repository.time.sleep") as wait:
        with pytest.raises(Forbidden):
            repo.auto_share_retest_result("JOB-AUTO", {"assessment": "inconclusive"}, "lease-owner")
    query.assert_called_once()
    wait.assert_not_called()


def test_worker_prioritizes_reconciliation_without_an_agent_call_or_new_job():
    repo, worker = Mock(), FeedbackWorker()

    def reconciled():
        worker.stop_event.set()
        return True

    repo.reconcile_auto_shared_retest.side_effect = reconciled
    with patch("app.workflow_worker.BigQueryRepository", return_value=repo), patch("app.workflow_worker.invoke_agent") as invoke:
        worker.run()
    repo.claim_feedback_job.assert_not_called()
    invoke.assert_not_called()


def test_unknown_environment_has_no_confirmable_result_but_does_not_restrict_visibility():
    repo = BigQueryRepository(client=Mock())
    with patch.object(repo, "workflow_query") as query:
        assert repo.latest_confirmable_retest("FDB-1", 1, "unknown") is None
    query.assert_not_called()


def test_latest_confirmation_lookup_is_completed_input_and_environment_scoped():
    repo = BigQueryRepository(client=Mock())
    with patch.object(repo, "workflow_query", return_value=[{"id": "JOB-NEWEST"}]) as query:
        assert repo.latest_confirmable_retest("FDB-1", 4, "prod") == "JOB-NEWEST"
    sql = query.call_args.args[0]
    assert "j.status = 'completed'" in sql and "j.kind = 'retest'" in sql
    assert "j.revision = @revision" in sql and repo._job_environment_kind('j') + " = @environment" in sql
    assert "DESC, j.id DESC LIMIT 1" in sql
    assert "published_at" not in sql and "expected_behavior_verified" not in sql
    values = {parameter.name: parameter.value for parameter in query.call_args.args[1]}
    assert {key: values[key] for key in ("id", "revision", "environment")} == {"id": "FDB-1", "revision": 4, "environment": "prod"}
    assert {"legacy_nonprod", "legacy_prod", "legacy_agent"} <= values.keys()
    assert "run_context_json,'$.environment_id'" in query.call_args.args[0]
    assert 'JOIN scoped_feedback f' in sql and f"LEFT JOIN `{repo.workflow_table('feedback_main_environments')}` m" in sql


def test_confirmation_does_not_need_manual_publication_or_verified_expected_answer():
    repo = BigQueryRepository(client=Mock())
    owned = {"id": "FDB-1", "revision": 1, "environment": "nonprod", "expectedBehaviorVerified": False, "latestPublishedAttemptId": None}
    job = {"id": "JOB-1", "feedback_id": "FDB-1", "kind": "retest", "status": "completed", "revision": 1,
           "environment": "nonprod", "created_at": "2026-10-15T00:00:00Z", "published_at": None, "result_json": '{"assessment":"inconclusive"}'}
    with patch.object(repo, "get_my_feedback", return_value=owned), patch.object(repo, "get_feedback_job", return_value=job), \
         patch.object(repo, "latest_confirmable_retest", return_value="JOB-1"), patch.object(repo, "get_version", return_value={"answer": "Saved answer"}), \
         patch.object(repo, "workflow_query") as query, patch.object(repo, "_insert_event"):
        repo.confirm_retest("FDB-1", "JOB-1", ["owner@example.test"], "owner@example.test", AnswerConfirmation(verdict="fixed"))
    sql = query.call_args.args[0]
    assert "current_job.status = 'completed'" in sql and "newer.status = 'completed'" in sql
    assert repo._current_environment_kind('owner_context') + " = @environment" in sql and "COALESCE(f.revision, 1) = @revision" in sql
    assert "LOWER(TRIM(f.reporter)) IN UNNEST(@reporters)" in sql
    assert ".published_at" not in sql


@pytest.mark.parametrize("changes", [{"kind": "enrich"}, {"status": "running"}, {"status": "failed"}])
def test_only_an_actual_completed_retest_can_receive_a_resolution_response(changes):
    repo = BigQueryRepository(client=Mock())
    job = {"feedback_id": "FDB-1", "kind": "retest", "status": "completed", "revision": 1, "environment": "nonprod", **changes}
    with patch.object(repo, "get_my_feedback", return_value={"id": "FDB-1", "revision": 1, "environment": "nonprod"}), patch.object(repo, "get_feedback_job", return_value=job), patch.object(repo, "workflow_query") as query:
        with pytest.raises(ValueError, match="Complete the retest"):
            repo.confirm_retest("FDB-1", "JOB-1", ["owner@example.test"], "owner@example.test", AnswerConfirmation(verdict="fixed"))
    query.assert_not_called()


def test_removing_manual_publication_does_not_expose_a_backdoor_endpoint():
    fake = Mock()
    app.dependency_overrides[repository] = lambda: fake
    try:
        client = TestClient(app)
        token = client.post("/api/auth/mock-login", json={"email": "quality.reviewer@example.test"}).json()["accessToken"]
        response = client.post("/api/feedback/FDB-1/retests/JOB-1/publish", headers={"Authorization": "Bearer " + token}, json={"summary": "No manual sharing", "reviewer_verified": True})
        assert response.status_code == 404
        assert not fake.method_calls
    finally:
        app.dependency_overrides.pop(repository, None)
