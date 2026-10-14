from __future__ import annotations

import sys

from openpyxl import load_workbook

from app.bigquery import BigQueryRepository
from app.models import FeedbackCreate


def main(path: str) -> None:
    workbook = load_workbook(path, read_only=True, data_only=True)
    sheet = workbook.active
    headers = [cell.value for cell in next(sheet.iter_rows(min_row=1, max_row=1))]
    rows = [dict(zip(headers, row)) for row in sheet.iter_rows(min_row=2, values_only=True)]
    repository = BigQueryRepository()
    repository.ensure_schema()
    for row in rows:
        question = str(row.get("Question") or "Legacy triage case")
        feedback = str(row.get("Companion Answer") or row.get("Evidence") or "Imported legacy triage record")
        repository.create_feedback(FeedbackCreate(
            agent_id="neo-rules-agent",
            question=question,
            answer=str(row.get("Companion Answer") or ""),
            user_verdict="Incorrect",
            issue_categories=[str(row.get("Root Cause") or "unknown")],
            feedback_text=feedback,
            expected_behavior=str(row.get("Expected Answer") or "") or None,
            impact="Medium",
            run_context={"legacy_row": row.get("Row"), "source_file": str(path)},
        ))
    print(f"Imported {len(rows)} records from {path}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/import_legacy_triage.py <xlsx>")
    main(sys.argv[1])
