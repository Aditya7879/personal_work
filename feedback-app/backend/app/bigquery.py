from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from google.cloud import bigquery

from .config import settings
from .models import (
    EvaluationCreate,
    FeedbackCreate,
    FeedbackRecord,
    GoldenCaseCreate,
    GoldenCaseFromFeedback,
    GoldenDatasetCreate,
    TriageUpdate,
)


FEEDBACK_TABLE = "feedback_items"
EVENT_TABLE = "feedback_events"
DATASET_TABLE = "golden_datasets"
CASE_TABLE = "golden_cases"
EVALUATION_TABLE = "evaluation_runs"
EVALUATION_CASE_TABLE = "evaluation_case_results"


class BigQueryRepository:
    """BigQuery persistence for feedback and append-only audit events."""

    def __init__(self, client: bigquery.Client | None = None) -> None:
        self.client = client or bigquery.Client(project=settings.project_id)
        self.dataset_ref = f"{settings.project_id}.{settings.dataset}"
        self.feedback_ref = f"{self.dataset_ref}.{FEEDBACK_TABLE}"
        self.events_ref = f"{self.dataset_ref}.{EVENT_TABLE}"
        self.golden_datasets_ref = f"{self.dataset_ref}.{DATASET_TABLE}"
        self.golden_cases_ref = f"{self.dataset_ref}.{CASE_TABLE}"
        self.evaluations_ref = f"{self.dataset_ref}.{EVALUATION_TABLE}"
        self.evaluation_cases_ref = f"{self.dataset_ref}.{EVALUATION_CASE_TABLE}"

    def ensure_schema(self) -> None:
        dataset = bigquery.Dataset(self.dataset_ref)
        dataset.location = settings.location
        self.client.create_dataset(dataset, exists_ok=True)
        feedback_schema = [
            bigquery.SchemaField("feedback_id", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("created_at", "TIMESTAMP", mode="REQUIRED"),
            bigquery.SchemaField("updated_at", "TIMESTAMP", mode="REQUIRED"),
            bigquery.SchemaField("agent_id", "STRING"),
            bigquery.SchemaField("run_id", "STRING"),
            bigquery.SchemaField("conversation_id", "STRING"),
            bigquery.SchemaField("question", "STRING"),
            bigquery.SchemaField("answer", "STRING"),
            bigquery.SchemaField("title", "STRING"),
            bigquery.SchemaField("excerpt", "STRING"),
            bigquery.SchemaField("full_quote", "STRING"),
            bigquery.SchemaField("user_verdict", "STRING"),
            bigquery.SchemaField("issue_categories_json", "STRING"),
            bigquery.SchemaField("feedback_text", "STRING"),
            bigquery.SchemaField("expected_behavior", "STRING"),
            bigquery.SchemaField("impact", "STRING"),
            bigquery.SchemaField("severity", "STRING"),
            bigquery.SchemaField("state", "STRING"),
            bigquery.SchemaField("reporter", "STRING"),
            bigquery.SchemaField("suggested_rca", "STRING"),
            bigquery.SchemaField("suggested_rca_confidence", "FLOAT64"),
            bigquery.SchemaField("confirmed_rca", "STRING"),
            bigquery.SchemaField("subcategory", "STRING"),
            bigquery.SchemaField("reviewer_notes", "STRING"),
            bigquery.SchemaField("recommended_fix", "STRING"),
            bigquery.SchemaField("assigned_reviewer", "STRING"),
            bigquery.SchemaField("ground_truth_hint", "STRING"),
            bigquery.SchemaField("tags_json", "STRING"),
            bigquery.SchemaField("correlated_reports_json", "STRING"),
            bigquery.SchemaField("claims_json", "STRING"),
            bigquery.SchemaField("evidence_json", "STRING"),
            bigquery.SchemaField("run_context_json", "STRING"),
            bigquery.SchemaField("source", "STRING"),
        ]
        event_schema = [
            bigquery.SchemaField("event_id", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("feedback_id", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("event_type", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("created_at", "TIMESTAMP", mode="REQUIRED"),
            bigquery.SchemaField("actor", "STRING"),
            bigquery.SchemaField("payload_json", "STRING"),
        ]
        self.client.create_table(
            bigquery.Table(self.feedback_ref, schema=feedback_schema), exists_ok=True
        )
        self.client.create_table(
            bigquery.Table(self.events_ref, schema=event_schema), exists_ok=True
        )
        schemas = {
            self.golden_datasets_ref: [
                bigquery.SchemaField("dataset_id", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("name", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("description", "STRING"),
                bigquery.SchemaField("owner", "STRING"),
                bigquery.SchemaField("current_version", "STRING"),
                bigquery.SchemaField("created_at", "TIMESTAMP", mode="REQUIRED"),
                bigquery.SchemaField("updated_at", "TIMESTAMP", mode="REQUIRED"),
            ],
            self.golden_cases_ref: [
                bigquery.SchemaField("case_id", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("dataset_id", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("dataset_version", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("feedback_id", "STRING"),
                bigquery.SchemaField("title", "STRING"),
                bigquery.SchemaField("question", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("expected_behavior", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("required_claims_json", "STRING"),
                bigquery.SchemaField("expected_status", "STRING"),
                bigquery.SchemaField("evidence_refs_json", "STRING"),
                bigquery.SchemaField("curator", "STRING"),
                bigquery.SchemaField("state", "STRING"),
                bigquery.SchemaField("created_at", "TIMESTAMP", mode="REQUIRED"),
            ],
            self.evaluations_ref: [
                bigquery.SchemaField("evaluation_id", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("dataset_id", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("dataset_name", "STRING"),
                bigquery.SchemaField("dataset_version", "STRING"),
                bigquery.SchemaField("label", "STRING"),
                bigquery.SchemaField("status", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("total_cases", "INT64"),
                bigquery.SchemaField("passed_cases", "INT64"),
                bigquery.SchemaField("failed_cases", "INT64"),
                bigquery.SchemaField("review_required_cases", "INT64"),
                bigquery.SchemaField("pass_rate", "FLOAT64"),
                bigquery.SchemaField("started_at", "TIMESTAMP"),
                bigquery.SchemaField("completed_at", "TIMESTAMP"),
                bigquery.SchemaField("error", "STRING"),
            ],
            self.evaluation_cases_ref: [
                bigquery.SchemaField("evaluation_id", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("case_id", "STRING", mode="REQUIRED"),
                bigquery.SchemaField("result", "STRING"),
                bigquery.SchemaField("actual_status", "STRING"),
                bigquery.SchemaField("actual_answer", "STRING"),
                bigquery.SchemaField("missing_claims_json", "STRING"),
                bigquery.SchemaField("created_at", "TIMESTAMP", mode="REQUIRED"),
            ],
        }
        for table_ref, schema in schemas.items():
            self.client.create_table(bigquery.Table(table_ref, schema=schema), exists_ok=True)

    def ping(self) -> bool:
        self.client.query("SELECT 1", location=settings.location).result()
        return True

    def _insert_rows(self, table_ref: str, rows: list[dict[str, Any]]) -> None:
        """Append rows through a completed load job, avoiding streaming buffers."""
        if not rows:
            return
        job = self.client.load_table_from_json(
            rows,
            table_ref,
            job_config=bigquery.LoadJobConfig(write_disposition="WRITE_APPEND"),
            location=settings.location,
        )
        job.result()

    def overview(self) -> dict[str, Any]:
        sql = f"""
        SELECT
          (SELECT COUNT(*) FROM `{self.feedback_ref}`) AS feedback_total,
          (SELECT COUNTIF(state NOT IN ('Approved for dataset', 'Rejected', 'Duplicate')) FROM `{self.feedback_ref}`) AS feedback_needing_review,
          (SELECT COUNT(*) FROM `{self.golden_datasets_ref}`) AS golden_dataset_count,
          (SELECT COUNTIF(c.state = 'approved') FROM `{self.golden_datasets_ref}` d
             LEFT JOIN `{self.golden_cases_ref}` c
               ON c.dataset_id = d.dataset_id AND c.dataset_version = d.current_version) AS approved_case_count,
          (SELECT pass_rate FROM `{self.evaluations_ref}` WHERE status = 'completed' ORDER BY completed_at DESC LIMIT 1) AS latest_pass_rate,
          (SELECT evaluation_id FROM `{self.evaluations_ref}` ORDER BY started_at DESC LIMIT 1) AS latest_evaluation_id
        """
        row = next(iter(self.client.query(sql, location=settings.location).result()))
        return dict(row)

    def list_feedback(
        self,
        *,
        state: str | None = None,
        severity: str | None = None,
        verdict: str | None = None,
        root_cause: str | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> tuple[list[FeedbackRecord], int]:
        conditions = ["TRUE"]
        parameters: list[bigquery.ScalarQueryParameter] = []
        if state:
            conditions.append("state = @state")
            parameters.append(bigquery.ScalarQueryParameter("state", "STRING", state))
        if severity:
            conditions.append("severity = @severity")
            parameters.append(bigquery.ScalarQueryParameter("severity", "STRING", severity))
        if verdict:
            conditions.append("user_verdict = @verdict")
            parameters.append(bigquery.ScalarQueryParameter("verdict", "STRING", verdict))
        if root_cause:
            conditions.append("COALESCE(confirmed_rca, suggested_rca) = @root_cause")
            parameters.append(bigquery.ScalarQueryParameter("root_cause", "STRING", root_cause))
        if search:
            conditions.append(
                "(LOWER(title) LIKE LOWER(@search) OR LOWER(feedback_id) LIKE LOWER(@search) "
                "OR LOWER(question) LIKE LOWER(@search) OR LOWER(run_id) LIKE LOWER(@search))"
            )
            parameters.append(bigquery.ScalarQueryParameter("search", "STRING", f"%{search}%"))
        where = " AND ".join(conditions)
        count_job = self.client.query(
            f"SELECT COUNT(*) AS total FROM `{self.feedback_ref}` WHERE {where}",
            job_config=bigquery.QueryJobConfig(query_parameters=parameters),
            location=settings.location,
        )
        total = int(next(iter(count_job.result())).total)
        offset = max(page - 1, 0) * page_size
        query_parameters = [
            *parameters,
            bigquery.ScalarQueryParameter("limit", "INT64", page_size),
            bigquery.ScalarQueryParameter("offset", "INT64", offset),
        ]
        rows = self.client.query(
            f"SELECT * FROM `{self.feedback_ref}` WHERE {where} "
            "ORDER BY updated_at DESC LIMIT @limit OFFSET @offset",
            job_config=bigquery.QueryJobConfig(query_parameters=query_parameters),
            location=settings.location,
        ).result()
        return [self._record(dict(row)) for row in rows], total

    def get_feedback(self, feedback_id: str) -> FeedbackRecord | None:
        rows = self.client.query(
            f"SELECT * FROM `{self.feedback_ref}` WHERE feedback_id = @feedback_id LIMIT 1",
            job_config=bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("feedback_id", "STRING", feedback_id)
            ]),
            location=settings.location,
        ).result()
        row = next(iter(rows), None)
        return self._record(dict(row)) if row else None

    def create_feedback(self, payload: FeedbackCreate) -> FeedbackRecord:
        row = self._feedback_row(payload)
        self._insert_rows(self.feedback_ref, [row])
        self._insert_event(row["feedback_id"], "submitted", payload.reporter, payload.model_dump())
        return self._record(row)

    def create_feedback_batch(self, payloads: list[FeedbackCreate]) -> int:
        rows = [self._feedback_row(payload) for payload in payloads]
        if not rows:
            return 0
        self._insert_rows(self.feedback_ref, rows)
        events = [
            {
                "event_id": str(uuid.uuid4()),
                "feedback_id": row["feedback_id"],
                "event_type": "submitted",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "actor": payload.reporter,
                "payload_json": json.dumps(payload.model_dump(), default=str),
            }
            for row, payload in zip(rows, payloads)
        ]
        self._insert_rows(self.events_ref, events)
        return len(rows)

    def legacy_row_keys(self) -> set[str]:
        rows = self.client.query(
            f"SELECT JSON_VALUE(run_context_json, '$.legacy_row') AS legacy_row "
            f"FROM `{self.feedback_ref}` WHERE JSON_VALUE(run_context_json, '$.source') = 'legacy_csv_import'",
            location=settings.location,
        ).result()
        return {str(row.legacy_row) for row in rows if row.legacy_row is not None}

    def normalize_legacy_verdicts(self) -> int:
        sql = f"""
        UPDATE `{self.feedback_ref}`
        SET user_verdict = CASE
              WHEN LOWER(TRIM(JSON_VALUE(run_context_json, '$.answer_status'))) = 'correct' THEN 'Correct'
              WHEN LOWER(TRIM(JSON_VALUE(run_context_json, '$.answer_status'))) LIKE 'partially correct%' THEN 'Partially correct'
              WHEN STARTS_WITH(LOWER(TRIM(JSON_VALUE(run_context_json, '$.answer_status'))), 'wrong')
                OR LOWER(TRIM(JSON_VALUE(run_context_json, '$.answer_status'))) = 'incorrect' THEN 'Incorrect'
              ELSE 'Not specified'
            END,
            impact = CASE
              WHEN STARTS_WITH(LOWER(TRIM(JSON_VALUE(run_context_json, '$.answer_status'))), 'wrong')
                OR LOWER(TRIM(JSON_VALUE(run_context_json, '$.answer_status'))) = 'incorrect' THEN 'High'
              ELSE 'Medium'
            END,
            severity = CASE
              WHEN STARTS_WITH(LOWER(TRIM(JSON_VALUE(run_context_json, '$.answer_status'))), 'wrong')
                OR LOWER(TRIM(JSON_VALUE(run_context_json, '$.answer_status'))) = 'incorrect' THEN 'High'
              ELSE 'Med'
            END,
            state = CASE
              WHEN LOWER(TRIM(JSON_VALUE(run_context_json, '$.status'))) IN ('closed', 'done', 'correct') THEN 'Triaged'
              ELSE 'Submitted'
            END,
            full_quote = CONCAT(
              IF(NULLIF(TRIM(JSON_VALUE(run_context_json, '$.follow_up')), '') IS NULL, '', CONCAT('Follow-up: ', TRIM(JSON_VALUE(run_context_json, '$.follow_up')), '\\n\\n')),
              IF(NULLIF(TRIM(ground_truth_hint), '') IS NULL, '', CONCAT('Expected answer: ', TRIM(ground_truth_hint), '\\n\\n')),
              IF(NULLIF(TRIM(COALESCE(JSON_VALUE(run_context_json, '$.developer_remarks'), JSON_VALUE(issue_categories_json, '$[1]'))), '') IS NULL, '', CONCAT('Developer remarks: ', TRIM(COALESCE(JSON_VALUE(run_context_json, '$.developer_remarks'), JSON_VALUE(issue_categories_json, '$[1]'))), '\\n\\n')),
              IF(NULLIF(TRIM(JSON_VALUE(run_context_json, '$.resolution')), '') IS NULL, '', CONCAT('Resolution: ', TRIM(JSON_VALUE(run_context_json, '$.resolution'))))
            ),
            excerpt = SUBSTR(CONCAT(
              IF(NULLIF(TRIM(JSON_VALUE(run_context_json, '$.follow_up')), '') IS NULL, '', CONCAT('Follow-up: ', TRIM(JSON_VALUE(run_context_json, '$.follow_up')))),
              IF(NULLIF(TRIM(COALESCE(JSON_VALUE(run_context_json, '$.developer_remarks'), JSON_VALUE(issue_categories_json, '$[1]'))), '') IS NULL, '', CONCAT(' ', TRIM(COALESCE(JSON_VALUE(run_context_json, '$.developer_remarks'), JSON_VALUE(issue_categories_json, '$[1]')))))
            ), 1, 160),
            source = 'legacy_csv_import'
        WHERE JSON_VALUE(run_context_json, '$.source') = 'legacy_csv_import'
          AND state = 'Submitted'
        """
        job = self.client.query(sql, location=settings.location)
        job.result()
        return int(job.num_dml_affected_rows or 0)

    def _feedback_row(self, payload: FeedbackCreate) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        feedback_id = f"FDB-{uuid.uuid4().hex[:8].upper()}"
        return {
            "feedback_id": feedback_id,
            "created_at": now,
            "updated_at": now,
            "agent_id": payload.agent_id,
            "run_id": payload.run_id,
            "conversation_id": payload.conversation_id,
            "question": payload.question or "",
            "answer": payload.answer or "",
            "title": (payload.question or "User feedback").strip()[:120],
            "excerpt": payload.feedback_text[:160],
            "full_quote": payload.feedback_text,
            "user_verdict": payload.user_verdict,
            "issue_categories_json": json.dumps(payload.issue_categories),
            "feedback_text": payload.feedback_text,
            "expected_behavior": payload.expected_behavior,
            "impact": payload.impact,
            "severity": {"Low": "Low", "Medium": "Med", "High": "High"}[payload.impact],
            "state": "Submitted",
            "reporter": payload.reporter,
            "suggested_rca": None,
            "suggested_rca_confidence": None,
            "confirmed_rca": None,
            "subcategory": None,
            "reviewer_notes": None,
            "recommended_fix": None,
            "assigned_reviewer": None,
            "ground_truth_hint": payload.expected_behavior,
            "tags_json": json.dumps(payload.issue_categories),
            "correlated_reports_json": "[]",
            "claims_json": "[]",
            "evidence_json": "[]",
            "run_context_json": json.dumps(payload.run_context, default=str),
            "source": payload.source,
        }

    def update_triage(
        self,
        feedback_id: str,
        payload: TriageUpdate,
        actor: str | None = None,
    ) -> FeedbackRecord | None:
        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            return self.get_feedback(feedback_id)
        now = datetime.now(timezone.utc).isoformat()
        assignments = ["updated_at = @updated_at"]
        params = [bigquery.ScalarQueryParameter("updated_at", "TIMESTAMP", now)]
        for key in (
            "state",
            "confirmed_rca",
            "subcategory",
            "reviewer_notes",
            "recommended_fix",
            "expected_behavior",
            "assigned_reviewer",
        ):
            if key in updates:
                column = "ground_truth_hint" if key == "expected_behavior" else key
                assignments.append(f"{column} = @{key}")
                params.append(bigquery.ScalarQueryParameter(key, "STRING", updates[key]))
        for key in ("claims", "evidence"):
            if key in updates:
                column = f"{key}_json"
                parameter = f"{key}_json"
                assignments.append(f"{column} = @{parameter}")
                params.append(bigquery.ScalarQueryParameter(parameter, "STRING", json.dumps(updates[key], default=str)))
        params.append(bigquery.ScalarQueryParameter("feedback_id", "STRING", feedback_id))
        self.client.query(
            f"UPDATE `{self.feedback_ref}` SET {', '.join(assignments)} WHERE feedback_id = @feedback_id",
            job_config=bigquery.QueryJobConfig(query_parameters=params),
            location=settings.location,
        ).result()
        self._insert_event(feedback_id, "triage_updated", actor, updates)
        return self.get_feedback(feedback_id)

    def create_golden_dataset(self, payload: GoldenDatasetCreate) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        row = {
            "dataset_id": f"DS-{uuid.uuid4().hex[:10].upper()}",
            "name": payload.name,
            "description": payload.description,
            "owner": payload.owner,
            "current_version": "1.0.0",
            "created_at": now,
            "updated_at": now,
        }
        self._insert_rows(self.golden_datasets_ref, [row])
        return {**row, "case_count": 0, "reviewer_count": 0, "tags": [], "pending_reviews": 0}

    def create_golden_dataset_version(self, dataset_id: str, curator: str | None = None) -> dict[str, Any]:
        dataset = self.get_golden_dataset(dataset_id)
        if not dataset:
            raise KeyError("Golden dataset not found")
        current = str(dataset.get("current_version") or "1.0.0")
        parts = current.split(".")
        if len(parts) != 3 or not all(part.isdigit() for part in parts):
            raise ValueError("Dataset current_version must be semantic major.minor.patch")
        next_version = f"{parts[0]}.{parts[1]}.{int(parts[2]) + 1}"
        previous_cases = [case for case in self.list_golden_cases(dataset_id, current) if case.get("state") == "approved"]
        if not previous_cases:
            raise ValueError("Approve at least one golden case before creating a new dataset version")
        now = datetime.now(timezone.utc).isoformat()
        cloned = [{
            "case_id": f"GC-{uuid.uuid4().hex[:8].upper()}",
            "dataset_id": dataset_id,
            "dataset_version": next_version,
            "feedback_id": case.get("feedback_id"),
            "title": case["title"],
            "question": case["question"],
            "expected_behavior": case["expected_behavior"],
            "required_claims_json": json.dumps(case.get("required_claims") or []),
            "expected_status": case.get("expected_status"),
            "evidence_refs_json": json.dumps(case.get("evidence_refs") or [], default=str),
            "curator": curator or case.get("curator"),
            "state": "approved",
            "created_at": now,
        } for case in previous_cases]
        if cloned:
            self._insert_rows(self.golden_cases_ref, cloned)
        self.client.query(
            f"UPDATE `{self.golden_datasets_ref}` SET current_version = @version, updated_at = @updated_at WHERE dataset_id = @dataset_id",
            job_config=bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("version", "STRING", next_version),
                bigquery.ScalarQueryParameter("updated_at", "TIMESTAMP", now),
                bigquery.ScalarQueryParameter("dataset_id", "STRING", dataset_id),
            ]), location=settings.location,
        ).result()
        refreshed = self.get_golden_dataset(dataset_id) or dataset
        return {**refreshed, "copied_cases": len(cloned)}

    def list_golden_datasets(self) -> list[dict[str, Any]]:
        sql = f"""
        SELECT d.dataset_id, d.name, d.description, d.owner, d.current_version,
               d.created_at, d.updated_at,
               COUNTIF(c.state = 'approved') AS case_count,
               COUNT(DISTINCT c.curator) AS reviewer_count,
               COUNTIF(c.state = 'candidate') AS pending_reviews
        FROM `{self.golden_datasets_ref}` d
        LEFT JOIN `{self.golden_cases_ref}` c
          ON c.dataset_id = d.dataset_id AND c.dataset_version = d.current_version
        GROUP BY d.dataset_id, d.name, d.description, d.owner, d.current_version,
                 d.created_at, d.updated_at
        ORDER BY d.updated_at DESC
        """
        return [dict(row) for row in self.client.query(sql, location=settings.location).result()]

    def get_golden_dataset(self, dataset_id: str) -> dict[str, Any] | None:
        rows = self.client.query(
            f"SELECT * FROM `{self.golden_datasets_ref}` WHERE dataset_id = @dataset_id LIMIT 1",
            job_config=bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("dataset_id", "STRING", dataset_id)
            ]), location=settings.location,
        ).result()
        row = next(iter(rows), None)
        return dict(row) if row else None

    def list_golden_cases(self, dataset_id: str, version: str | None = None) -> list[dict[str, Any]]:
        if version is None:
            dataset = self.get_golden_dataset(dataset_id)
            if not dataset:
                return []
            version = dataset["current_version"]
        rows = self.client.query(
            f"SELECT * FROM `{self.golden_cases_ref}` WHERE dataset_id = @dataset_id "
            "AND dataset_version = @version ORDER BY created_at DESC",
            job_config=bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("dataset_id", "STRING", dataset_id),
                bigquery.ScalarQueryParameter("version", "STRING", version),
            ]), location=settings.location,
        ).result()
        return [self._golden_case(dict(row)) for row in rows]

    def set_golden_case_state(self, case_id: str, state: str, curator: str | None = None) -> dict[str, Any] | None:
        if state not in {"candidate", "approved", "rejected"}:
            raise ValueError("Unsupported golden case state")
        self.client.query(
            f"UPDATE `{self.golden_cases_ref}` SET state = @state, curator = COALESCE(@curator, curator) WHERE case_id = @case_id",
            job_config=bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("state", "STRING", state),
                bigquery.ScalarQueryParameter("curator", "STRING", curator),
                bigquery.ScalarQueryParameter("case_id", "STRING", case_id),
            ]), location=settings.location,
        ).result()
        rows = self.client.query(
            f"SELECT * FROM `{self.golden_cases_ref}` WHERE case_id = @case_id LIMIT 1",
            job_config=bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("case_id", "STRING", case_id)
            ]), location=settings.location,
        ).result()
        row = next(iter(rows), None)
        if not row:
            return None
        record = self._golden_case(dict(row))
        if record.get("feedback_id") and state == "approved":
            self.update_triage(
                record["feedback_id"],
                TriageUpdate(state="Approved for dataset"),
                actor=curator,
            )
        return record

    def add_golden_case(self, dataset_id: str, payload: GoldenCaseCreate, *, state: str = "candidate") -> dict[str, Any]:
        dataset = self.get_golden_dataset(dataset_id)
        if not dataset:
            raise KeyError("Golden dataset not found")
        row = {
            "case_id": f"GC-{uuid.uuid4().hex[:8].upper()}",
            "dataset_id": dataset_id,
            "dataset_version": dataset["current_version"],
            "feedback_id": payload.feedback_id,
            "title": payload.title,
            "question": payload.question,
            "expected_behavior": payload.expected_behavior,
            "required_claims_json": json.dumps(payload.required_claims),
            "expected_status": payload.expected_status,
            "evidence_refs_json": json.dumps(payload.evidence_refs, default=str),
            "curator": payload.curator,
            "state": state,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._insert_rows(self.golden_cases_ref, [row])
        return self._golden_case(row)

    def approve_feedback_as_golden_case(
        self, feedback_id: str, payload: GoldenCaseFromFeedback
    ) -> dict[str, Any]:
        feedback = self.get_feedback(feedback_id)
        if not feedback:
            raise KeyError("Feedback item not found")
        case = self.add_golden_case(payload.dataset_id, GoldenCaseCreate(
            feedback_id=feedback_id,
            title=feedback.title,
            question=feedback.prompt,
            expected_behavior=payload.expected_behavior,
            required_claims=payload.required_claims,
            expected_status=payload.expected_status,
            evidence_refs=feedback.evidence,
            curator=payload.curator,
        ), state="candidate")
        self.update_triage(feedback_id, TriageUpdate(state="Golden candidate"), actor=payload.curator)
        return case

    def create_evaluation(self, payload: EvaluationCreate) -> dict[str, Any]:
        dataset = self.get_golden_dataset(payload.dataset_id)
        if not dataset:
            raise KeyError("Golden dataset not found")
        version = payload.dataset_version or dataset["current_version"]
        cases = [case for case in self.list_golden_cases(payload.dataset_id, version) if case.get("state") == "approved"]
        if not cases:
            raise ValueError("Dataset version has no approved golden cases")
        now = datetime.now(timezone.utc).isoformat()
        row = {
            "evaluation_id": f"EV-{uuid.uuid4().hex[:10].upper()}",
            "dataset_id": payload.dataset_id,
            "dataset_name": dataset["name"],
            "dataset_version": version,
            "label": payload.label,
            "status": "queued",
            "total_cases": len(cases),
            "passed_cases": 0,
            "failed_cases": 0,
            "review_required_cases": 0,
            "pass_rate": None,
            "started_at": now,
            "completed_at": None,
            "error": None,
        }
        self._insert_rows(self.evaluations_ref, [row])
        return self._evaluation_record(row)

    def get_evaluation(self, evaluation_id: str) -> dict[str, Any] | None:
        rows = self.client.query(
            f"SELECT * FROM `{self.evaluations_ref}` WHERE evaluation_id = @evaluation_id LIMIT 1",
            job_config=bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("evaluation_id", "STRING", evaluation_id)
            ]), location=settings.location,
        ).result()
        row = next(iter(rows), None)
        return self._evaluation_record(dict(row)) if row else None

    def list_evaluations(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.client.query(
            f"SELECT * FROM `{self.evaluations_ref}` ORDER BY started_at DESC LIMIT @limit",
            job_config=bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("limit", "INT64", limit)
            ]), location=settings.location,
        ).result()
        return [self._evaluation_record(dict(row)) for row in rows]

    def list_evaluation_cases(self, evaluation_id: str) -> list[dict[str, Any]]:
        rows = self.client.query(
            f"SELECT * FROM `{self.evaluation_cases_ref}` WHERE evaluation_id = @evaluation_id ORDER BY created_at",
            job_config=bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("evaluation_id", "STRING", evaluation_id)
            ]), location=settings.location,
        ).result()
        result = []
        for row in rows:
            record = dict(row)
            record["missing_claims"] = self._json_list(record.pop("missing_claims_json", None))
            result.append(record)
        return result

    def save_evaluation_results(self, evaluation_id: str, results: list[dict[str, Any]]) -> None:
        if results:
            self._insert_rows(self.evaluation_cases_ref, results)
        passed = sum(result.get("result") == "passed" for result in results)
        failed = sum(result.get("result") == "failed" for result in results)
        review = sum(result.get("result") == "review_required" for result in results)
        total = len(results)
        status = "completed"
        self._update_evaluation(evaluation_id, {
            "status": status,
            "total_cases": total,
            "passed_cases": passed,
            "failed_cases": failed,
            "review_required_cases": review,
            "pass_rate": (passed / total * 100) if total else None,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })

    def mark_evaluation_running(self, evaluation_id: str) -> None:
        self._update_evaluation(evaluation_id, {
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
        })

    def fail_evaluation(self, evaluation_id: str, error: str) -> None:
        self._update_evaluation(evaluation_id, {
            "status": "failed",
            "error": error[:4000],
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })

    def _update_evaluation(self, evaluation_id: str, updates: dict[str, Any]) -> None:
        assignments = []
        params = [bigquery.ScalarQueryParameter("evaluation_id", "STRING", evaluation_id)]
        for key, value in updates.items():
            assignments.append(f"{key} = @{key}")
            field_type = "FLOAT64" if key == "pass_rate" else ("INT64" if key.endswith("cases") else "TIMESTAMP" if key.endswith("_at") else "STRING")
            params.append(bigquery.ScalarQueryParameter(key, field_type, value))
        self.client.query(
            f"UPDATE `{self.evaluations_ref}` SET {', '.join(assignments)} WHERE evaluation_id = @evaluation_id",
            job_config=bigquery.QueryJobConfig(query_parameters=params), location=settings.location,
        ).result()

    @staticmethod
    def _golden_case(row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "required_claims": BigQueryRepository._json_list(row.get("required_claims_json")),
            "evidence_refs": BigQueryRepository._json_list(row.get("evidence_refs_json")),
        }

    @staticmethod
    def _evaluation_record(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row.get("evaluation_id"),
            "dataset_id": row.get("dataset_id"),
            "dataset_name": row.get("dataset_name"),
            "dataset_version": row.get("dataset_version"),
            "label": row.get("label"),
            "status": row.get("status"),
            "total_cases": row.get("total_cases") or 0,
            "passed_cases": row.get("passed_cases") or 0,
            "failed_cases": row.get("failed_cases") or 0,
            "review_required_cases": row.get("review_required_cases") or 0,
            "pass_rate": row.get("pass_rate"),
            "started_at": str(row.get("started_at") or ""),
            "completed_at": str(row.get("completed_at") or "") or None,
            "error": row.get("error"),
        }

    def _insert_event(self, feedback_id: str, event_type: str, actor: str | None, payload: Any) -> None:
        row = {
            "event_id": str(uuid.uuid4()),
            "feedback_id": feedback_id,
            "event_type": event_type,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "actor": actor,
            "payload_json": json.dumps(payload, default=str),
        }
        self._insert_rows(self.events_ref, [row])

    @staticmethod
    def _json_list(value: Any) -> list[Any]:
        if not value:
            return []
        if isinstance(value, list):
            return value
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except (TypeError, json.JSONDecodeError):
            return []

    def _record(self, row: dict[str, Any]) -> FeedbackRecord:
        issue_categories = self._json_list(row.get("issue_categories_json"))
        run_context = self._json_object(row.get("run_context_json"))
        is_legacy = row.get("source") == "legacy_csv_import" or run_context.get("source") == "legacy_csv_import"
        if is_legacy:
            legacy_categories = [str(item) for item in issue_categories if str(item) != "legacy_csv_import"]
            if legacy_categories and not run_context.get("developer_remarks"):
                run_context["developer_remarks"] = legacy_categories[0]
            issue_categories = ["legacy_csv_import"]
        return FeedbackRecord(
            id=str(row.get("feedback_id") or ""),
            agentName=str(row.get("agent_id") or settings.default_agent_id),
            model="linked run metadata unavailable",
            runId=row.get("run_id"),
            conversationId=row.get("conversation_id"),
            prompt=str(row.get("question") or ""),
            generatedAnswer=str(row.get("answer") or ""),
            title=str(row.get("title") or "Feedback"),
            excerpt=str(row.get("excerpt") or ""),
            fullQuote=row.get("full_quote"),
            userVerdict=str(row.get("user_verdict") or "Incorrect"),
            issueCategories=issue_categories,
            suggestedRca=row.get("suggested_rca"),
            suggestedRcaConfidence=row.get("suggested_rca_confidence"),
            confirmedRca=row.get("confirmed_rca"),
            defectSubCategory=row.get("subcategory"),
            severity=str(row.get("severity") or "Med"),
            state=str(row.get("state") or "Submitted"),
            reporter=row.get("reporter"),
            reportedTime=str(row.get("created_at") or ""),
            assignedReviewer=row.get("assigned_reviewer"),
            groundTruthHint=row.get("ground_truth_hint"),
            impact=str(row.get("impact") or "Medium"),
            tags=[str(item) for item in self._json_list(row.get("tags_json")) if str(item) == "legacy_csv_import"] if is_legacy else self._json_list(row.get("tags_json")),
            correlatedReports=self._json_list(row.get("correlated_reports_json")),
            claims=self._json_list(row.get("claims_json")),
            evidence=self._json_list(row.get("evidence_json")),
            reviewerNotes=row.get("reviewer_notes"),
            recommendedFix=row.get("recommended_fix"),
            runContext=run_context,
        )

    @staticmethod
    def _json_object(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if not value:
            return {}
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, json.JSONDecodeError):
            return {}
