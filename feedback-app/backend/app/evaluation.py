from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import httpx

from .bigquery import BigQueryRepository
from .config import settings


def _evaluate_answer(case: dict[str, Any], result: dict[str, Any]) -> tuple[str, list[str]]:
    """Transparent baseline evaluator; it does not claim semantic judging."""

    answer = str(result.get("answer") or "")
    normalized = " ".join(answer.casefold().split())
    required = case.get("required_claims") or []
    missing = [str(claim) for claim in required if " ".join(str(claim).casefold().split()) not in normalized]
    expected_status = case.get("expected_status")
    actual_status = str(result.get("status") or "")
    if not answer.strip():
        return "failed", ["Agent returned an empty answer"]
    if expected_status and actual_status != expected_status:
        return "failed", [f"Expected status `{expected_status}`, got `{actual_status or 'missing'}`"]
    if missing:
        return "review_required", missing
    return "passed", []


def run_evaluation(evaluation_id: str) -> None:
    from .demo_context import is_demo
    if is_demo():
        raise RuntimeError('Real evaluation execution is disabled in demo views')
    repository = BigQueryRepository()
    try:
        if not settings.neo_agent_api_url:
            raise ValueError("Configure NEO_AGENT_API_URL before invoking the real evaluation agent")
        evaluation = repository.get_evaluation(evaluation_id)
        if not evaluation:
            return
        repository.mark_evaluation_running(evaluation_id)
        cases = repository.list_golden_cases(
            evaluation["dataset_id"], evaluation["dataset_version"]
        )
        cases = [case for case in cases if case.get("state") == "approved"]
        results: list[dict[str, Any]] = []
        with httpx.Client(timeout=httpx.Timeout(90.0)) as client:
            for case in cases:
                now = datetime.now(timezone.utc).isoformat()
                try:
                    response = client.post(
                        f"{settings.neo_agent_api_url}/api/agent/runs",
                        json={
                            "conversation_id": f"quality-eval-{evaluation_id}-{case['case_id']}",
                            "question": case["question"],
                        },
                    )
                    response.raise_for_status()
                    actual = response.json()
                    status, missing = _evaluate_answer(case, actual)
                    results.append({
                        "evaluation_id": evaluation_id,
                        "case_id": case["case_id"],
                        "result": status,
                        "actual_status": actual.get("status"),
                        "actual_answer": str(actual.get("answer") or "")[:30000],
                        "missing_claims_json": json.dumps(missing),
                        "created_at": now,
                    })
                except Exception as exc:
                    results.append({
                        "evaluation_id": evaluation_id,
                        "case_id": case["case_id"],
                        "result": "review_required",
                        "actual_status": "tool_error",
                        "actual_answer": f"Evaluation request failed: {type(exc).__name__}",
                        "missing_claims_json": json.dumps(["Agent invocation failed; inspect evaluation worker logs."]),
                        "created_at": now,
                    })
        repository.save_evaluation_results(evaluation_id, results)
    except Exception as exc:
        repository.fail_evaluation(evaluation_id, f"Evaluation worker failed: {type(exc).__name__}: {exc}")
