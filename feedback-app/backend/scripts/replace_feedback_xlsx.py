"""Validated, staged, atomic replacement of feedback from an updated workbook."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google.cloud import bigquery
from openpyxl import load_workbook

from app.bigquery import BigQueryRepository
from app.config import settings
from app.models import FeedbackCreate
from app.business_domain import workbook_business_taxonomy
from scripts.import_feedback_csv import verdict


FEEDBACK_TABLES = (
    "feedback_items", "feedback_events", "feedback_answer_versions",
    "feedback_rca_versions", "feedback_workflow_jobs", "feedback_notifications",
)
REQUIRED_HEADERS = {"No.", "Question", "Sub-domain", "User", "Data source", "Status", "Answer status",
                    "Expected answer", "Generated answer", "Latency (s)", "Follow-up", "Remarks (Dev team)",
                    "Resolution", "Status note", "Language"}


def text(value) -> str:
    return str(value).strip() if value is not None else ""


def row_number(value) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and int(value) == value:
        return str(int(value))
    return text(value)


def read_feedback_workbook(path: Path) -> list[FeedbackCreate]:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        if "All Questions" not in workbook.sheetnames:
            raise ValueError("Use the All Questions sheet; language subsets must not be imported twice")
        sheet = workbook["All Questions"]
        iterator = sheet.iter_rows(values_only=True)
        headers = [text(value) for value in next(iterator)]
        missing = REQUIRED_HEADERS - set(headers)
        if missing:
            raise ValueError("Workbook is missing columns: " + ", ".join(sorted(missing)))
        if len(headers) != len(set(headers)):
            raise ValueError("Workbook has duplicate column headers")
        payloads, seen = [], set()
        for excel_row, values in enumerate(iterator, start=2):
            if not any(text(value) for value in values):
                continue
            record = dict(zip(headers, values))
            number = row_number(record.get("No."))
            if not number or number in seen:
                raise ValueError(f"Missing or duplicate feedback number at workbook row {excel_row}")
            seen.add(number)
            question, answer = text(record.get("Question")), text(record.get("Generated answer"))
            if not question or not answer:
                raise ValueError(f"Question or generated answer is missing at workbook row {excel_row}; existing feedback was not removed")
            answer_status = text(record.get("Answer status"))
            follow_up = text(record.get("Follow-up"))
            feedback = follow_up or f"Imported spreadsheet feedback. Original answer status: {answer_status or 'not recorded'}."
            payloads.append(FeedbackCreate(
                agent_id="neo-rules-agent", title=question[:120], question=question, answer=answer,
                user_verdict=verdict(answer_status), issue_categories=["legacy_xlsx_import"],
                feedback_text=feedback, expected_behavior=text(record.get("Expected answer")) or None,
                impact="High" if verdict(answer_status) == "Incorrect" else "Medium",
                reporter=text(record.get("User")) or None, environment="unknown", source="legacy_xlsx_import",
                run_context={
                    "source": "legacy_xlsx_import", "source_file": str(path.resolve()), "source_sha256": digest,
                    "source_sheet": "All Questions", "workbook_row": excel_row, "legacy_row": number,
                    "data_source": text(record.get("Data source")), "sub_domain": text(record.get("Sub-domain")),
                    "status": text(record.get("Status")), "answer_status": answer_status,
                    "latency_seconds": record.get("Latency (s)"), "follow_up": follow_up,
                    "developer_remarks": text(record.get("Remarks (Dev team)")),
                    "resolution": text(record.get("Resolution")), "status_note": text(record.get("Status note")),
                    "language": text(record.get("Language")),
                },
            ))
        if not payloads:
            raise ValueError("No valid feedback records found; refusing to remove existing feedback")
        taxonomy = workbook_business_taxonomy([text(payload.run_context.get("sub_domain")) for payload in payloads])
        for payload in payloads:
            classification = taxonomy[text(payload.run_context.get("sub_domain"))]
            if classification["domain"]:
                payload.run_context.update(domain=classification["domain"], business_subdomain=classification["subdomain"],
                                           classification_source="workbook_import")
        return payloads
    finally:
        workbook.close()


def prepare_rows(repo: BigQueryRepository, payloads: list[FeedbackCreate], existing_ids: dict[str, str]) -> tuple[list[dict], list[dict], list[dict]]:
    rows, events, originals = [], [], []
    for payload in payloads:
        row = repo._feedback_row(payload)
        number = row_number(payload.run_context["legacy_row"])
        if number in existing_ids:
            row["feedback_id"] = existing_ids[number]
        closed = text(payload.run_context.get("status")).casefold() in {"closed", "done", "correct"}
        row["state"] = "Triaged" if closed else "Submitted"
        row["public_status"] = "In review" if closed else "Received"
        row["public_message"] = "Imported spreadsheet status retained as historical context; the updated answer has not been independently verified." if closed else None
        notes = [("Developer remarks", payload.run_context.get("developer_remarks")), ("Imported status note", payload.run_context.get("status_note"))]
        row["reviewer_notes"] = "\n\n".join(f"{label}: {value}" for label, value in notes if value) or None
        rows.append(row)
        events.append({"event_id": str(uuid.uuid4()), "feedback_id": row["feedback_id"], "event_type": "submitted",
                       "created_at": row["created_at"], "actor": payload.reporter,
                       "payload_json": json.dumps(payload.model_dump(), ensure_ascii=False, default=str)})
        originals.append({"id": f"original:{row['feedback_id']}", "feedback_id": row["feedback_id"], "attempt_id": None,
                          "created_at": row["created_at"], "payload_json": json.dumps({
                              "kind": "original", "question": payload.question, "answer": payload.answer,
                              "environment": "unknown", "agentId": payload.agent_id, "agentVersion": None,
                              "revision": 1, "createdAt": row["created_at"], "origin": "updated_workbook_baseline",
                              "sourceSha256": payload.run_context["source_sha256"],
                          }, ensure_ascii=False)})
    return rows, events, originals


def export_backup(repo: BigQueryRepository, directory: Path, path: Path) -> dict[str, int]:
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    counts = {}
    for name in FEEDBACK_TABLES:
        file = directory / f"{name}.jsonl"
        descriptor = os.open(file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        count = 0
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            for raw in repo.client.query(f"SELECT * FROM `{repo.dataset_ref}.{name}`", location=settings.location).result():
                output.write(json.dumps(dict(raw), ensure_ascii=False, default=str) + "\n")
                count += 1
        counts[name] = count
    descriptor = os.open(directory / "manifest.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        json.dump({"dataset": repo.dataset_ref, "replaced_from": str(path), "counts": counts, "created_at": datetime.now(timezone.utc).isoformat()}, output, indent=2)
    return counts


def replace_feedback(repo: BigQueryRepository, path: Path, payloads: list[FeedbackCreate], backup_dir: Path) -> dict:
    existing = repo.workflow_query(f"SELECT feedback_id, JSON_VALUE(run_context_json,'$.legacy_row') AS row_number FROM `{repo.feedback_ref}`")
    numbers = [row_number(row.get("row_number")) for row in existing if row.get("row_number") is not None]
    if len(numbers) != len(set(numbers)):
        raise ValueError("Existing feedback has duplicate source row numbers; refusing ambiguous ID preservation")
    ids = {row_number(row["row_number"]): row["feedback_id"] for row in existing if row.get("row_number") is not None}
    rows, events, originals = prepare_rows(repo, payloads, ids)
    counts = export_backup(repo, backup_dir, path)
    stages = {}
    for table_name, values in (("feedback_items", rows), ("feedback_events", events), ("feedback_answer_versions", originals)):
        source = repo.client.get_table(f"{repo.dataset_ref}.{table_name}")
        stage_name = f"{repo.dataset_ref}._feedback_replace_{uuid.uuid4().hex[:12]}"
        stage = bigquery.Table(stage_name, schema=source.schema)
        stage.expires = datetime.now(timezone.utc) + timedelta(hours=1)
        repo.client.create_table(stage)
        repo.client.load_table_from_json(values, stage_name,
            job_config=bigquery.LoadJobConfig(schema=source.schema, write_disposition="WRITE_EMPTY"), location=settings.location).result()
        staged_count = repo.workflow_query(f"SELECT COUNT(*) AS count FROM `{stage_name}`")[0]["count"]
        if int(staged_count) != len(payloads):
            raise ValueError("Staging validation failed; active feedback was not removed")
        stages[table_name] = (stage_name, [field.name for field in source.schema])
    statements = ["BEGIN TRANSACTION;"]
    for name in FEEDBACK_TABLES:
        statements.append(f"ASSERT (SELECT COUNT(*) FROM `{repo.dataset_ref}.{name}`) = {counts[name]} AS 'Feedback changed during replacement; retry after quiescing writers';")
    for name in reversed(FEEDBACK_TABLES):
        statements.append(f"DELETE FROM `{repo.dataset_ref}.{name}` WHERE TRUE;")
    for name, (stage_name, fields) in stages.items():
        columns = ", ".join(f"`{field}`" for field in fields)
        statements.append(f"INSERT INTO `{repo.dataset_ref}.{name}` ({columns}) SELECT {columns} FROM `{stage_name}`;")
        statements.append(f"ASSERT (SELECT COUNT(*) FROM `{repo.dataset_ref}.{name}`) = {len(payloads)} AS 'Imported feedback count mismatch';")
    statements.append("COMMIT TRANSACTION;")
    repo.client.query("\n".join(statements), location=settings.location).result()
    return {"old_counts": counts, "imported": len(payloads), "preserved_ids": sum(row_number(payload.run_context["legacy_row"]) in ids for payload in payloads), "backup_dir": str(backup_dir)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--backup-dir", type=Path)
    args = parser.parse_args()
    payloads = read_feedback_workbook(args.path)
    print("Validated workbook rows:", len(payloads), "· All Questions only")
    print("Answer verdicts:", dict(Counter(payload.user_verdict for payload in payloads)))
    print("Rows without a reporter:", sum(payload.reporter is None for payload in payloads))
    if not args.replace:
        print("Preview only; no feedback was removed.")
        return
    directory = args.backup_dir or Path('/tmp/opencode') / f"feedback-refresh-backup-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
    repo = BigQueryRepository()
    print("Replacing feedback in:", repo.dataset_ref)
    result = replace_feedback(repo, args.path, payloads, directory)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
