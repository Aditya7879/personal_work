import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app, repository
from app.models import FeedbackRecord
from app.root_cause import suggest_root_cause


class FakeEvidenceIndex:
    def search(self, question, expected):
        return [{
            "evidence_id": "D1",
            "source": "training.md",
            "page": "12",
            "element_id": "element-4",
            "element_type": "Table",
            "origin": "vlm",
            "score": 2.4,
            "excerpt": "Material status 30 is reviewed in the lifecycle table.",
            "context": "Material status 30 is reviewed in the lifecycle table.",
        }]


class EmptyEvidenceIndex:
    def search(self, question, expected):
        return []


class RootCauseSuggestionTest(unittest.TestCase):
    def test_root_cause_api_returns_and_persists_a_suggestion_without_confirmation(self):
        suggestion = {
            "suggested_rca": "retrieval_failure",
            "suggested_rca_confidence": 0.72,
            "rca_subcategory": "source passage not selected",
            "rca_rationale": "A matching source passage was found but was absent from the answer.",
            "rca_required_claims": ["Claim A"],
            "rca_supported_claims": [],
            "rca_missing_claims": ["Claim A"],
            "rca_contradicted_claims": [],
            "rca_evidence": [{"evidence_id": "D1", "source": "doc.pdf", "page": "5", "excerpt": "Claim A"}],
            "rca_review_required": True,
            "rca_auto_accepted": False,
            "rca_suggestion_status": "sonnet_suggested",
            "rca_suggested_at": None,
        }

        class FakeRepository:
            saved = None

            def get_feedback(self, feedback_id):
                return FeedbackRecord(
                    id=feedback_id,
                    agentName="neo-rules-agent",
                    model="unknown",
                    prompt="Question",
                    generatedAnswer="Answer",
                    title="Case",
                    excerpt="Feedback",
                    userVerdict="Incorrect",
                    severity="High",
                    state="Submitted",
                    reportedTime="now",
                    impact="High",
                )

            def ensure_original(self, record):
                pass

            def save_version(self, *args, **kwargs):
                self.saved_version = args[3]

            def update_rca_suggestion(self, feedback_id, value, **kwargs):
                self.saved = value
                self.source_context = kwargs
                return self.get_feedback(feedback_id)

        fake = FakeRepository()
        app.dependency_overrides[repository] = lambda: fake
        try:
            login = TestClient(app).post("/api/auth/mock-login", json={"email": "quality.reviewer@example.test"})
            token = login.json()["accessToken"]
            with patch("app.main.suggest_root_cause", return_value=suggestion):
                response = TestClient(app).post(
                    "/api/feedback/FDB-1/root-cause/suggest",
                    headers={"Authorization": f"Bearer {token}"},
                )
        finally:
            app.dependency_overrides.pop(repository, None)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["rca_review_required"])
        self.assertFalse(response.json()["rca_auto_accepted"])
        self.assertEqual(fake.saved["suggested_rca"], "retrieval_failure")
        self.assertNotIn("confirmed_rca", fake.saved)
        self.assertFalse(fake.saved_version['verified'])
        self.assertEqual(fake.source_context['source_answer_id'], 'original:FDB-1')
        self.assertEqual(fake.source_context['expected_revision'], 1)

    def test_suggestion_preserves_only_cited_source_evidence_and_flags_lower_confidence(self):
        feedback = {
            "prompt": "Why was the MM status answer incorrect?",
            "generatedAnswer": "It said status 99.",
            "userVerdict": "Incorrect",
            "fullQuote": "Expected status 30.",
            "groundTruthHint": "Status 30 is in the source.",
            "runContext": {},
        }
        decision = {
            "root_cause": "reasoning_error",
            "subcategory": "wrong status selected",
            "rationale": "The answer conflicts with the retrieved lifecycle passage.",
            "required_claims": ["status 30"],
            "supported_claims": [],
            "missing_claims": ["status 30"],
            "contradicted_claims": ["status 99"],
            "evidence_ids": ["D1", "D999"],
            "confidence": 0.82,
            "review_required": False,
        }
        with patch("app.root_cause.get_document_evidence_index", return_value=FakeEvidenceIndex()), patch(
            "app.root_cause._judge", return_value=decision
        ):
            result = suggest_root_cause(feedback)

        self.assertEqual(result["suggested_rca"], "reasoning_error")
        self.assertEqual([item["evidence_id"] for item in result["rca_evidence"]], ["D1"])
        self.assertTrue(result["rca_review_required"])
        self.assertFalse(result["rca_auto_accepted"])

    def test_high_confidence_cited_result_with_subcategory_is_auto_classified(self):
        decision = {
            "root_cause": "factual_error",
            "subcategory": "Incorrect schedule time",
            "rationale": "The answer's schedule conflicts with the cited source.",
            "required_claims": ["scheduled at noon"],
            "supported_claims": ["scheduled at noon"],
            "missing_claims": [],
            "contradicted_claims": ["runs every night"],
            "evidence_ids": ["D1"],
            "confidence": 0.91,
            "review_required": False,
        }
        with patch("app.root_cause.get_document_evidence_index", return_value=FakeEvidenceIndex()), patch(
            "app.root_cause._judge", return_value=decision
        ):
            result = suggest_root_cause({"prompt": "When does the job run?"})

        self.assertEqual(result["suggested_rca"], "factual_error")
        self.assertEqual(result["rca_subcategory"], "Incorrect schedule time")
        self.assertFalse(result["rca_review_required"])
        self.assertTrue(result["rca_auto_accepted"])
        self.assertEqual(result["rca_suggestion_status"], "auto_classified")

    def test_high_confidence_still_requires_review_when_model_flags_ambiguity(self):
        decision = {
            "root_cause": "reasoning_error",
            "subcategory": "unsupported_conclusion",
            "rationale": "The intent is ambiguous.",
            "evidence_ids": ["D1"],
            "confidence": 0.99,
            "review_required": True,
        }
        with patch("app.root_cause.get_document_evidence_index", return_value=FakeEvidenceIndex()), patch(
            "app.root_cause._judge", return_value=decision
        ):
            result = suggest_root_cause({"prompt": "Question"})

        self.assertTrue(result["rca_review_required"])
        self.assertFalse(result["rca_auto_accepted"])

    def test_suggestion_without_model_evidence_link_downgrades_to_insufficient(self):
        with patch("app.root_cause.get_document_evidence_index", return_value=FakeEvidenceIndex()), patch(
            "app.root_cause._judge",
            return_value={
                "root_cause": "retrieval_failure",
                "rationale": "Suggested from vague context.",
                "evidence_ids": [],
                "confidence": 0.9,
                "review_required": False,
            },
        ):
            result = suggest_root_cause({"prompt": "Question"})

        self.assertEqual(result["suggested_rca"], "insufficient_evidence")
        self.assertEqual(result["suggested_rca_confidence"], 0.25)
        self.assertEqual(result["rca_evidence"], [])
        self.assertTrue(result["rca_review_required"])

    def test_no_document_hits_cannot_produce_confident_rca(self):
        with patch("app.root_cause.get_document_evidence_index", return_value=EmptyEvidenceIndex()), patch(
            "app.root_cause._judge",
            return_value={
                "root_cause": "reasoning_error",
                "rationale": "The answer seems wrong.",
                "evidence_ids": [],
                "confidence": 0.99,
                "review_required": False,
            },
        ):
            result = suggest_root_cause({"prompt": "Question"})

        self.assertEqual(result["suggested_rca"], "insufficient_evidence")
        self.assertLessEqual(result["suggested_rca_confidence"], 0.25)
        self.assertTrue(result["rca_review_required"])

    def test_unavailable_document_store_fails_closed(self):
        with patch("app.root_cause.get_document_evidence_index", side_effect=PermissionError("bucket access denied")):
            result = suggest_root_cause({"prompt": "Question"})

        self.assertEqual(result["suggested_rca"], "insufficient_evidence")
        self.assertEqual(result["rca_suggestion_status"], "evidence_unavailable")
        self.assertEqual(result["rca_retrieval_status"], "unavailable")
        self.assertIn("No local evidence fallback", result["rca_rationale"])
        self.assertEqual(result["rca_evidence"], [])
        self.assertTrue(result["rca_review_required"])
        self.assertFalse(result["rca_auto_accepted"])

    def test_empty_graph_hits_do_not_call_the_judge_or_claim_a_missing_document(self):
        with patch("app.root_cause.get_document_evidence_index", return_value=EmptyEvidenceIndex()), patch("app.root_cause._judge") as judge:
            result = suggest_root_cause({"prompt": "Question"})
        judge.assert_not_called()
        self.assertEqual(result["rca_suggestion_status"], "no_matching_evidence")
        self.assertEqual(result["rca_retrieval_status"], "no_matches")
        self.assertEqual(result["suggested_rca"], "insufficient_evidence")

    def test_neo4j_evidence_provenance_survives_citation_selection(self):
        evidence = [{**FakeEvidenceIndex().search("", "")[0], "origin": "neo4j", "corpus_version": "manifest-version", "chunk_id": "real-chunk", "matched_entities": ["retrieval hint"]}]
        with patch("app.root_cause._judge", return_value={"root_cause": "incomplete_answer", "subcategory": "Missing rule", "rationale": "A required rule was omitted.", "evidence_ids": ["D1"], "confidence": 0.9, "review_required": True}):
            result = suggest_root_cause({"prompt": "Question"}, evidence_override=evidence)
        self.assertEqual(result["rca_evidence"], evidence)
        self.assertEqual(result["rca_evidence_backend"], "neo4j")
        self.assertEqual(result["rca_corpus_version"], "manifest-version")
        self.assertEqual(result["rca_retrieval_status"], "available")


if __name__ == "__main__":
    unittest.main()
