import json
import unittest
from unittest.mock import Mock, patch

from app.bigquery import BigQueryRepository
from app.models import FeedbackRecord, GoldenCaseCreate, GoldenCaseFromFeedback, MyFeedbackUpdate, TriageUpdate


class BigQueryRepositoryTest(unittest.TestCase):
    def test_appends_use_completed_load_jobs_not_streaming_inserts(self):
        client = Mock()
        job = Mock()
        client.load_table_from_json.return_value = job
        repository = BigQueryRepository(client=client)

        repository._insert_rows("project.dataset.table", [{"id": "1"}])

        client.load_table_from_json.assert_called_once()
        job.result.assert_called_once_with()
        client.insert_rows_json.assert_not_called()

    def test_feedback_listing_always_filters_submitter_when_requested(self):
        client = Mock()
        count_job = Mock()
        count_job.result.return_value = [Mock(total=0)]
        rows_job = Mock()
        rows_job.result.return_value = []
        client.query.side_effect = [count_job, rows_job]
        repository = BigQueryRepository(client=client)

        items, total = repository.list_feedback(reporter="alex@example.test")

        self.assertEqual(items, [])
        self.assertEqual(total, 0)
        self.assertIn("LOWER(TRIM(f.reporter)) = LOWER(TRIM(@reporter))", client.query.call_args_list[0].args[0])
        parameters = client.query.call_args_list[0].kwargs["job_config"].query_parameters
        self.assertEqual(parameters[0].name, "reporter")
        self.assertEqual(parameters[0].value, "alex@example.test")

    def test_mock_demo_listing_can_scope_alias_and_seed_owner(self):
        client = Mock()
        count_job = Mock()
        count_job.result.return_value = [Mock(total=0)]
        rows_job = Mock()
        rows_job.result.return_value = []
        client.query.side_effect = [count_job, rows_job]
        repository = BigQueryRepository(client=client)

        repository.list_my_feedback(["demo@example.test", "seed@example.test"])

        query = client.query.call_args_list[0].args[0]
        self.assertIn("LOWER(TRIM(f.reporter)) IN UNNEST(@reporters)", query)
        parameters = client.query.call_args_list[0].kwargs["job_config"].query_parameters
        self.assertEqual(parameters[0].name, "reporters")
        self.assertEqual(parameters[0].values, ["demo@example.test", "seed@example.test"])

    def test_user_domain_and_status_filters_apply_before_count_and_pagination(self):
        client = Mock()
        count_job = Mock()
        count_job.result.return_value = [Mock(total=7)]
        rows_job = Mock()
        rows_job.result.return_value = []
        client.query.side_effect = [count_job, rows_job]
        repository = BigQueryRepository(client=client)

        items, total = repository.list_feedback(
            reporter=" Alex@example.test ",
            domain=" F2S - Batch Management ",
            public_status="In review",
            state="Triaged",
            search="batch",
            page=3,
            page_size=25,
        )

        self.assertEqual(items, [])
        self.assertEqual(total, 7)
        for call in client.query.call_args_list:
            query = call.args[0]
            self.assertIn("LOWER(TRIM(f.reporter)) = LOWER(TRIM(@reporter))", query)
            self.assertIn("JSON_VALUE(run_context_json, '$.domain')", query)
            self.assertIn("JSON_VALUE(run_context_json, '$.sub_domain')", query)
            self.assertIn("LOWER(TRIM(@domain))", query)
            self.assertIn("= @public_status", query)
            self.assertIn("state = @state", query)
            values = {parameter.name: parameter.value for parameter in call.kwargs["job_config"].query_parameters}
            self.assertEqual(values["reporter"], " Alex@example.test ")
            self.assertEqual(values["domain"], " F2S - Batch Management ")
            self.assertEqual(values["public_status"], "In review")
            self.assertEqual(values["state"], "Triaged")
            self.assertEqual(values["search"], "%batch%")
        row_values = {parameter.name: parameter.value for parameter in client.query.call_args.kwargs["job_config"].query_parameters}
        self.assertEqual(row_values["limit"], 25)
        self.assertEqual(row_values["offset"], 50)

    def test_domain_values_are_query_parameters_not_sql(self):
        client = Mock()
        count_job = Mock()
        count_job.result.return_value = [Mock(total=0)]
        rows_job = Mock()
        rows_job.result.return_value = []
        client.query.side_effect = [count_job, rows_job]
        repository = BigQueryRepository(client=client)
        domain = "F2S') OR TRUE --"

        repository.list_feedback(domain=domain)

        for call in client.query.call_args_list:
            self.assertNotIn(domain, call.args[0])
            parameter = next(item for item in call.kwargs["job_config"].query_parameters if item.name == "domain")
            self.assertEqual(parameter.value, domain)

    def test_reporter_domain_and_status_filters_keep_both_demo_owners(self):
        repository = BigQueryRepository(client=Mock())
        with patch.object(repository, "list_feedback", return_value=([], 0)) as listing:
            repository.list_my_feedback(
                ["demo@example.test", "seed@example.test"],
                domain="F2S - Batch Management",
                public_status="Received",
                page=2,
                page_size=20,
            )

        listing.assert_called_once_with(
            reporter=["demo@example.test", "seed@example.test"],
            search=None,
            domain="F2S - Batch Management",
            environment=None,
            public_status="Received",
            page=2,
            page_size=20,
        )

    def test_public_domain_options_are_owner_scoped_without_reporter_values(self):
        client = Mock()
        client.query.return_value.result.return_value = [{
            "domains": ["F2S - Batch Management", "Unspecified"],
            "reporters": ["private@example.test"],
        }]
        repository = BigQueryRepository(client=client)

        options = repository.list_feedback_filter_options(["Demo@example.test", " Seed@example.test "])

        self.assertEqual(options, {"domains": ["F2S - Batch Management", "Unspecified"]})
        query = client.query.call_args.args[0]
        self.assertIn("LOWER(TRIM(f.reporter)) IN UNNEST(@reporters)", query)
        self.assertIn("GROUP BY LOWER(domain)", query)
        self.assertNotIn("AS reporters", query)
        self.assertNotIn("LIMIT", query)
        parameters = client.query.call_args.kwargs["job_config"].query_parameters
        self.assertEqual(parameters[0].values, ["demo@example.test", "seed@example.test"])

    def test_reviewer_filter_options_cover_all_users_and_domains(self):
        client = Mock()
        client.query.return_value.result.return_value = [{
            "domains": ["F2S - Batch Management", "O2C - Credit Management"],
            "reporters": ["alex@example.test", "sam@example.test"],
        }]
        repository = BigQueryRepository(client=client)

        options = repository.list_feedback_filter_options(include_reporters=True)

        self.assertEqual(options["reporters"], ["alex@example.test", "sam@example.test"])
        query = client.query.call_args.args[0]
        self.assertIn("WHERE TRUE", query)
        self.assertIn("GROUP BY LOWER(reporter)", query)
        self.assertIn("AS reporters", query)
        self.assertNotIn("LIMIT", query)

    def test_empty_owner_scope_does_not_fall_back_to_all_feedback(self):
        client = Mock()
        client.query.return_value.result.return_value = [{"domains": []}]
        repository = BigQueryRepository(client=client)

        options = repository.list_feedback_filter_options([])

        self.assertEqual(options, {"domains": []})
        self.assertIn("IN UNNEST(@reporters)", client.query.call_args.args[0])
        self.assertEqual(client.query.call_args.kwargs["job_config"].query_parameters[0].values, [])

    def test_domain_display_matches_explicit_legacy_and_unspecified_contexts(self):
        repository = BigQueryRepository(client=Mock())
        cases = [
            ({"domain": " O2C ", "sub_domain": "F2S"}, "O2C"),
            ({"domain": " ", "sub_domain": " F2S - Batch Management "}, "F2S"),
            ({"sub_domain": "O2C - Credit Management"}, "O2C"),
            ({"domain": None, "sub_domain": ""}, "Unspecified"),
            ({}, "Unspecified"),
        ]
        for context, expected in cases:
            with self.subTest(context=context):
                record = repository._record({"feedback_id": "FDB-1", "run_context_json": json.dumps(context)})
                self.assertEqual(record.domain, expected)
                self.assertEqual(repository._my_feedback_record(record, [])["domain"], expected)

    def test_submitter_edit_is_owner_scoped_and_invalidates_expected_answer_review(self):
        client = Mock()
        client.query.return_value.result.return_value = [{"state": "Evidence review", "public_status": "In review"}]
        repository = BigQueryRepository(client=client)
        with patch.object(repository, "_insert_event") as insert_event, patch.object(
            repository, "get_my_feedback", return_value={"id": "FDB-1"}
        ):
            result = repository.update_my_feedback(
                "FDB-1",
                ["demo@example.test", "seed@example.test"],
                MyFeedbackUpdate(
                    question="Updated title",
                    feedback_text="Updated details",
                    expected_behavior="Expected response",
                    user_verdict="Incorrect",
                    issue_categories=["Missing information"],
                    impact="High",
                ),
                actor="demo@example.test",
            )

        update_query = client.query.call_args_list[1].args[0]
        self.assertIn("LOWER(TRIM(f.reporter)) IN UNNEST(@reporters)", update_query)
        self.assertIn("expected_behavior_verified = FALSE", update_query)
        self.assertIn("state = 'Triaged'", update_query)
        self.assertEqual(result, {"id": "FDB-1"})
        insert_event.assert_not_called()  # Audit and capture are committed in the same transaction now.
        self.assertIn("'submitter_updated'", update_query)
        self.assertIn("feedback_answer_versions", update_query)
        values = {parameter.name: parameter.value for parameter in client.query.call_args_list[1].kwargs["job_config"].query_parameters if hasattr(parameter, "value")}
        event = json.loads(values["event_payload"])
        self.assertEqual(event["public_status"], "In review")
        self.assertEqual(event["updated_fields"], ["expected_behavior", "feedback_text", "impact", "issue_categories", "question", "user_verdict"])
        self.assertEqual(event["revision"], 2)
        self.assertEqual(event["answer_version_id"], "submission:FDB-1:r2")

    def test_submitter_cannot_edit_closed_feedback(self):
        client = Mock()
        client.query.return_value.result.return_value = [{"state": "Approved for dataset", "public_status": "Resolved"}]
        repository = BigQueryRepository(client=client)
        with self.assertRaisesRegex(ValueError, "review is closed"):
            repository.update_my_feedback(
                "FDB-1", "alex@example.test", MyFeedbackUpdate(feedback_text="Changed"), actor="alex@example.test"
            )
        client.query.assert_called_once()

    def test_reviewer_cannot_bypass_reporter_confirmation_to_resolve_feedback(self):
        client = Mock()
        repository = BigQueryRepository(client=client)
        current = FeedbackRecord(
            id="FDB-1", agentName="agent", model="model", prompt="question", generatedAnswer="answer",
            title="case", excerpt="feedback", userVerdict="Incorrect", severity="High", state="Triaged",
            reportedTime="now", impact="High", publicStatus="In review",
        )
        with patch.object(repository, "get_feedback", return_value=current), patch.object(repository, "_insert_event") as insert_event:
            with self.assertRaisesRegex(ValueError, "resolution summary"):
                repository.update_triage("FDB-1", TriageUpdate(public_status="Resolved"), actor="reviewer@example.test")

            with self.assertRaisesRegex(ValueError, "Reporter confirmation"):
                repository.update_triage("FDB-1", TriageUpdate(public_status="Resolved", resolution_summary="A new answer is ready."), actor="reviewer@example.test")
        client.query.assert_not_called()
        insert_event.assert_not_called()

    def test_auto_classification_persists_category_and_subcategory(self):
        client = Mock()
        repository = BigQueryRepository(client=client)
        suggestion = {
            "suggested_rca": "factual_error",
            "suggested_rca_confidence": 0.91,
            "rca_subcategory": "Incorrect schedule time",
            "rca_rationale": "The cited source contradicts the answer.",
            "rca_evidence": [{"evidence_id": "D1"}],
            "rca_required_claims": [],
            "rca_supported_claims": [],
            "rca_missing_claims": [],
            "rca_contradicted_claims": [],
            "rca_review_required": False,
            "rca_auto_accepted": True,
            "rca_suggestion_status": "auto_classified",
        }
        with patch.object(repository, "_insert_event") as insert_event, patch.object(repository, "get_feedback", return_value=None):
            repository.client.query.return_value.result.return_value = [{'applied': 1}]
            repository.update_rca_suggestion("FDB-1", suggestion, expected_revision=1,
                source_answer_id='original:FDB-1', source_question='Question', source_answer='Answer')

        query = client.query.call_args.args[0]
        self.assertNotIn("confirmed_rca = IF(@auto_accept", query)
        self.assertNotIn("subcategory = IF(@auto_accept", query)
        self.assertIn("suggested_rca = @suggested_rca", query)
        self.assertIn("state = IF(@triage_ready AND state='Submitted'", query)
        self.assertIn('BEGIN TRANSACTION', query)
        self.assertIn('rca_auto_triaged', query)
        insert_event.assert_not_called()  # The suggestion and audit are committed atomically.
        params = {value.name: value.value for value in client.query.call_args.kwargs['job_config'].query_parameters}
        self.assertEqual(params['event_type'], 'rca_auto_classified')
        self.assertEqual(json.loads(params['event_payload']), suggestion)

    def test_saving_manual_classification_marks_it_reviewed(self):
        client = Mock()
        repository = BigQueryRepository(client=client)
        with patch.object(repository, "_insert_event"), patch.object(repository, "get_feedback", return_value=None):
            repository.update_triage("FDB-1", TriageUpdate(confirmed_rca="factual_error"))

        query = client.query.call_args.args[0]
        self.assertIn("state = IF(state = 'Submitted', 'Triaged', state)", query)
        self.assertIn("rca_review_required = FALSE", query)
        self.assertIn("rca_suggestion_status = 'reviewer_classified'", query)

    def test_review_cannot_complete_without_explicit_evidence_verification(self):
        client = Mock()
        repository = BigQueryRepository(client=client)
        current = FeedbackRecord(
            id="FDB-1", agentName="agent", model="model", prompt="question", generatedAnswer="answer",
            title="case", excerpt="feedback", userVerdict="Incorrect", severity="High", state="Evidence review",
            reportedTime="now", impact="High", groundTruthHint="expected but not verified",
            expectedBehaviorVerified=False,
        )
        with patch.object(repository, "get_feedback", return_value=current):
            with self.assertRaisesRegex(ValueError, "Reviewer-verified expected behavior"):
                repository.update_triage("FDB-1", TriageUpdate(state="Review complete"))

        client.query.assert_not_called()

    def test_review_completion_saves_verified_expected_behavior(self):
        client = Mock()
        repository = BigQueryRepository(client=client)
        current = FeedbackRecord(
            id="FDB-1", agentName="agent", model="model", prompt="question", generatedAnswer="answer",
            title="case", excerpt="feedback", userVerdict="Incorrect", severity="High", state="Evidence review",
            reportedTime="now", impact="High",
        )
        with patch.object(repository, "get_feedback", return_value=current), patch.object(repository, "_insert_event"):
            repository.update_triage("FDB-1", TriageUpdate(
                state="Review complete",
                expected_behavior="Verified expected behavior",
                expected_behavior_verified=True,
            ))

        query = client.query.call_args.args[0]
        self.assertIn("state = @state", query)
        self.assertIn("ground_truth_hint = @expected_behavior", query)
        self.assertIn("expected_behavior_verified = @expected_behavior_verified", query)

    def test_feedback_link_cannot_bypass_review_through_manual_case_endpoint(self):
        repository = BigQueryRepository(client=Mock())
        with self.assertRaisesRegex(ValueError, "completed-review workflow"):
            repository.add_golden_case("DS-1", GoldenCaseCreate(
                feedback_id="FDB-1",
                title="case",
                question="question",
                expected_behavior="expected",
            ))

    def test_feedback_promotion_requires_completed_verified_review(self):
        repository = BigQueryRepository(client=Mock())
        current = FeedbackRecord(
            id="FDB-1", agentName="agent", model="model", prompt="question", generatedAnswer="answer",
            title="case", excerpt="feedback", userVerdict="Incorrect", severity="High", state="Evidence review",
            reportedTime="now", impact="High", groundTruthHint="expected", expectedBehaviorVerified=False,
        )
        payload = GoldenCaseFromFeedback(dataset_id="DS-1", expected_behavior="expected")
        with patch.object(repository, "get_feedback", return_value=current):
            with self.assertRaisesRegex(ValueError, "Complete the evidence review"):
                repository.approve_feedback_as_golden_case("FDB-1", payload)

    def test_feedback_linked_candidate_cannot_be_approved_without_verified_behavior(self):
        client = Mock()
        client.query.return_value.result.return_value = [{
            "case_id": "GC-1",
            "dataset_id": "DS-1",
            "dataset_version": "1.0.0",
            "feedback_id": "FDB-1",
            "state": "candidate",
        }]
        repository = BigQueryRepository(client=client)
        feedback = FeedbackRecord(
            id="FDB-1", agentName="agent", model="model", prompt="question", generatedAnswer="answer",
            title="case", excerpt="feedback", userVerdict="Incorrect", severity="High", state="Golden candidate",
            reportedTime="now", impact="High", groundTruthHint="unverified", expectedBehaviorVerified=False,
        )
        with patch.object(repository, "get_feedback", return_value=feedback):
            with self.assertRaisesRegex(ValueError, "cannot be approved"):
                repository.set_golden_case_state("GC-1", "approved")

        client.query.assert_called_once()

    def test_reopening_unverified_candidate_withdraws_pending_dataset_cases(self):
        client = Mock()
        repository = BigQueryRepository(client=client)
        current = FeedbackRecord(
            id="FDB-1", agentName="agent", model="model", prompt="question", generatedAnswer="answer",
            title="case", excerpt="feedback", userVerdict="Incorrect", severity="High", state="Golden candidate",
            reportedTime="now", impact="High", groundTruthHint="unverified", expectedBehaviorVerified=False,
        )
        with patch.object(repository, "get_feedback", return_value=current), patch.object(repository, "_insert_event"):
            repository.update_triage("FDB-1", TriageUpdate(
                state="Evidence review",
                expected_behavior_verified=False,
            ))

        self.assertEqual(client.query.call_count, 2)
        self.assertIn("state = 'rejected'", client.query.call_args_list[0].args[0])
        self.assertIn("state = @state", client.query.call_args_list[1].args[0])

    def test_overview_returns_bigquery_series_for_dashboard_charts(self):
        client = Mock()
        repository = BigQueryRepository(client=client)
        row = {
            "feedback_total": 2,
            "feedback_needing_review": 1,
            "golden_dataset_count": 1,
            "approved_case_count": 3,
            "rca_runs_count": 2,
            "auto_classified_count": 1,
            "rca_review_count": 1,
            "latest_pass_rate": 75.0,
            "latest_evaluation_id": "EVAL-2",
            "feedback_trend_json": json.dumps([{"date": "2026-09-28", "feedback_count": 2, "issue_count": 1}]),
            "state_breakdown_json": json.dumps([{"state": "Submitted", "count": 2}]),
            "verdict_breakdown_json": json.dumps([{"verdict": "Incorrect", "count": 1}]),
            "root_cause_breakdown_json": json.dumps([{"category": "factual_error", "count": 1, "auto_count": 1, "review_count": 0}]),
            "subcategory_breakdown_json": json.dumps([{"category": "factual_error", "subcategory": "Incorrect schedule time", "count": 1}]),
            "evaluation_trend_json": json.dumps([
                {"evaluation_id": "EVAL-2", "label": "latest", "completed_at": "2026-09-28T12:00:00Z", "pass_rate": 75.0, "passed_cases": 3, "total_cases": 4},
                {"evaluation_id": "EVAL-1", "label": "previous", "completed_at": "2026-09-27T12:00:00Z", "pass_rate": 50.0, "passed_cases": 2, "total_cases": 4},
            ]),
            "recent_feedback_json": json.dumps([{"feedback_id": "FDB-1", "title": "Recent feedback", "state": "Submitted",
              "severity": "High", "user_verdict": "Incorrect", "root_cause": "factual_error",
              "updated_at": "2026-09-28T12:00:00Z"}]),
        }
        client.query.return_value.result.return_value = [row]

        result = repository.overview()

        client.query.assert_called_once()
        self.assertEqual(result["auto_classified_count"], 1)
        self.assertEqual(result["rca_runs_count"], 2)
        self.assertEqual(result["verdict_breakdown"][0]["verdict"], "Incorrect")
        self.assertEqual(result["feedback_trend"][0]["feedback_count"], 2)
        self.assertEqual(result["root_cause_breakdown"][0]["category"], "factual_error")
        self.assertEqual(result["evaluation_trend"][0]["evaluation_id"], "EVAL-1")
        self.assertEqual(result["recent_feedback"][0]["feedback_id"], "FDB-1")


if __name__ == "__main__":
    unittest.main()
