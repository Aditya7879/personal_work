from __future__ import annotations

import csv
import sys
from pathlib import Path

from app.bigquery import BigQueryRepository
from app.models import FeedbackCreate


def verdict(value: str) -> str:
    normalized = value.strip().casefold().rstrip(".")
    if normalized == "correct":
        return "Correct"
    if normalized in {"partially correct", "partial", "partially_correct"}:
        return "Partially correct"
    if normalized.startswith("wrong") or normalized in {"incorrect", "i don't understand the answer"}:
        return "Incorrect"
    return "Not specified"


def feedback_text(row: dict[str, str]) -> str:
    fields = (
        ("Follow-up", row.get("Follow-up")),
        ("Expected answer", row.get("Expected answers")),
        ("Developer remarks", row.get("Remarks (Dev team)")),
        ("Resolution", row.get("Resolution")),
    )
    collected = [f"{label}: {value.strip()}" for label, value in fields if value and value.strip()]
    return "\n\n".join(collected) or "Imported legacy feedback; no notes provided."


def main(path: str) -> None:
    source = Path(path)
    with source.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    repository = BigQueryRepository()
    repository.ensure_schema()
    existing_rows = repository.legacy_row_keys()
    payloads: list[FeedbackCreate] = []
    for row in rows:
        legacy_row = str(row.get("No.") or "").strip()
        if legacy_row in existing_rows:
            continue
        question = (row.get("Questions") or "").strip() or None
        answer = (row.get("Answers") or "").strip() or None
        answer_status = (row.get("Answer status") or "").strip()
        root_hint = (row.get("Remarks (Dev team)") or "").strip()
        categories = ["legacy_csv_import"]
        payloads.append(FeedbackCreate(
            agent_id="neo-rules-agent",
            question=question,
            answer=answer,
            user_verdict=verdict(answer_status),
            issue_categories=categories,
            feedback_text=feedback_text(row),
            expected_behavior=(row.get("Expected answers") or "").strip() or None,
            impact="High" if verdict(answer_status) == "Incorrect" else "Medium",
            reporter=(row.get("User") or "").strip() or None,
            source="legacy_csv_import",
            run_context={
                "source": "legacy_csv_import",
                "source_file": str(source),
                "legacy_row": row.get("No."),
                "data_source": row.get("Data source"),
                "sub_domain": row.get("Sub-domain"),
                "status": row.get("Status"),
                "answer_status": answer_status,
                "follow_up": row.get("Follow-up"),
                "developer_remarks": root_hint,
                "resolution": row.get("Resolution"),
                "language": row.get("Language"),
            },
        ))
    imported = repository.create_feedback_batch(payloads)
    normalized = repository.normalize_legacy_verdicts()
    print(f"Imported {imported} new feedback records and normalized {normalized} legacy rows from {source}; skipped {len(rows) - imported} existing rows")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python -m scripts.import_feedback_csv <csv-path>")
    main(sys.argv[1])
