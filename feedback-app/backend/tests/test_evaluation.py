import unittest

from app.evaluation import _evaluate_answer


class EvaluationBaselineTest(unittest.TestCase):
    def test_required_claims_present_pass(self):
        status, missing = _evaluate_answer(
            {"required_claims": ["MM30", "Code IN"]},
            {"answer": "MM30 is shown for Code IN.", "status": "partial"},
        )
        self.assertEqual(status, "passed")
        self.assertEqual(missing, [])

    def test_missing_claim_requires_human_review(self):
        status, missing = _evaluate_answer(
            {"required_claims": ["MM30", "Code IN"]},
            {"answer": "MM30 appears in the source.", "status": "partial"},
        )
        self.assertEqual(status, "review_required")
        self.assertEqual(missing, ["Code IN"])

    def test_status_mismatch_fails(self):
        status, missing = _evaluate_answer(
            {"required_claims": [], "expected_status": "clarification_required"},
            {"answer": "I found the answer.", "status": "verified"},
        )
        self.assertEqual(status, "failed")
        self.assertTrue(missing)


if __name__ == "__main__":
    unittest.main()
