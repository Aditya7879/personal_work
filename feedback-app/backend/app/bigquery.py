from __future__ import annotations

import json
import hashlib
import uuid
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from google.cloud import bigquery

from .config import settings
from .business_domain import USER_CLASSIFICATION_SOURCES, business_taxonomy_options, domain_from_metadata
from .cache import read_cache
from .workflow_repository import WorkflowRepositoryMixin
from .environment_repository import EnvironmentRepositoryMixin
from .dashboard import load_overview
from .feedback_ownership import ensure_ownership_tables, owner_scope
from .demo_context import DEMO_DATASET,is_demo
from .agent_targets import legacy_environment_id, stored_environment_kind
from .rca_progress import RCA_TRIAGE_MESSAGE, completed_rca, source_answer_id_sql, source_triage_guard
from .models import (
    EvaluationCreate,
    FeedbackCreate,
    FeedbackRecord,
    GoldenCaseCreate,
    GoldenCaseFromFeedback,
    GoldenDatasetCreate,
    TriageUpdate,
    MyFeedbackUpdate,
)


FEEDBACK_TABLE = "feedback_items"
EVENT_TABLE = "feedback_events"
DATASET_TABLE = "golden_datasets"
CASE_TABLE = "golden_cases"
EVALUATION_TABLE = "evaluation_runs"
EVALUATION_CASE_TABLE = "evaluation_case_results"

FEEDBACK_DOMAIN_SQL = (
    "COALESCE(NULLIF(TRIM(business_domain), ''), "
    "IF(domain_source IN ('user_submitted','user_confirmed','reviewer_confirmed'),'Unspecified', "
    "REGEXP_EXTRACT(UPPER(COALESCE(JSON_VALUE(run_context_json, '$.domain'), JSON_VALUE(run_context_json, '$.sub_domain'), '')), "
    "r'(?:^|[^A-Z0-9])(O2C|F2S|P2P|R2R)(?:$|[^A-Z0-9])')), 'Unspecified')"
)
FEEDBACK_SUBDOMAIN_SQL = (
    "CASE WHEN domain_source IN ('user_submitted','user_confirmed','reviewer_confirmed') "
    "THEN NULLIF(TRIM(business_subdomain),'') ELSE COALESCE(NULLIF(TRIM(business_subdomain),''), "
    "NULLIF(TRIM(JSON_VALUE(SAFE.PARSE_JSON(run_context_json),'$.business_subdomain')),''), "
    "NULLIF(TRIM(JSON_VALUE(SAFE.PARSE_JSON(run_context_json),'$.sub_domain')),'')) END"
)
PUBLIC_STATUS_SQL = (
    "COALESCE(NULLIF(public_status, ''), CASE state "
    "WHEN 'Submitted' THEN 'Received' "
    "WHEN 'Needs more information' THEN 'Needs information' "
    "WHEN 'Rejected' THEN 'Not planned' "
    "WHEN 'Duplicate' THEN 'Duplicate' ELSE 'In review' END)"
)


_CLIENT_LOCK = Lock()
_CLIENTS: dict[str, bigquery.Client] = {}


def get_bigquery_client() -> bigquery.Client:
    with _CLIENT_LOCK:
        if settings.project_id not in _CLIENTS:
            _CLIENTS[settings.project_id] = bigquery.Client(project=settings.project_id)
        return _CLIENTS[settings.project_id]


class BigQueryRepository(EnvironmentRepositoryMixin, WorkflowRepositoryMixin):
    """BigQuery persistence for feedback and append-only audit events."""

    def __init__(self, client: bigquery.Client | None = None) -> None:
        self.client = client if client is not None else get_bigquery_client()
        if is_demo():
            from .role_demo import require_demo_scope
            require_demo_scope()
        self.dataset_ref = f"{settings.project_id}.{DEMO_DATASET if is_demo() else settings.dataset}"
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
            bigquery.SchemaField("expected_behavior_verified", "BOOL"),
            bigquery.SchemaField("impact", "STRING"),
            bigquery.SchemaField("severity", "STRING"),
            bigquery.SchemaField("state", "STRING"),
            bigquery.SchemaField("reporter", "STRING"),
            bigquery.SchemaField("public_status", "STRING"),
            bigquery.SchemaField("public_message", "STRING"),
            bigquery.SchemaField("resolution_summary", "STRING"),
            bigquery.SchemaField("resolution_version", "STRING"),
            bigquery.SchemaField("resolved_at", "TIMESTAMP"),
            bigquery.SchemaField("suggested_rca", "STRING"),
            bigquery.SchemaField("suggested_rca_confidence", "FLOAT64"),
            bigquery.SchemaField("rca_suggested_subcategory", "STRING"),
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
            bigquery.SchemaField("environment", "STRING"),
            bigquery.SchemaField("agent_version", "STRING"),
            bigquery.SchemaField("revision", "INT64"),
            bigquery.SchemaField("business_domain", "STRING"),
            bigquery.SchemaField("business_subdomain", "STRING"),
            bigquery.SchemaField("domain_source", "STRING"),
            bigquery.SchemaField("domain_confidence", "FLOAT64"),
            bigquery.SchemaField("domain_reason", "STRING"),
            bigquery.SchemaField("domain_evidence_json", "STRING"),
            bigquery.SchemaField("domain_verified", "BOOL"),
            bigquery.SchemaField("latest_published_attempt_id", "STRING"),
            bigquery.SchemaField("rca_rationale", "STRING"),
            bigquery.SchemaField("rca_evidence_json", "STRING"),
            bigquery.SchemaField("rca_required_claims_json", "STRING"),
            bigquery.SchemaField("rca_supported_claims_json", "STRING"),
            bigquery.SchemaField("rca_missing_claims_json", "STRING"),
            bigquery.SchemaField("rca_contradicted_claims_json", "STRING"),
            bigquery.SchemaField("rca_review_required", "BOOL"),
            bigquery.SchemaField("rca_suggestion_status", "STRING"),
            bigquery.SchemaField("rca_suggested_at", "TIMESTAMP"),
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
        for column_name, column_type in (
            ("public_status", "STRING"),
            ("public_message", "STRING"),
            ("resolution_summary", "STRING"),
            ("resolution_version", "STRING"),
            ("resolved_at", "TIMESTAMP"),
        ):
            self.client.query(
                f"ALTER TABLE `{self.feedback_ref}` ADD COLUMN IF NOT EXISTS {column_name} {column_type}",
                location=settings.location,
            ).result()
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
        # Existing sandbox datasets are upgraded in place when new review fields
        # are introduced; no data table is dropped or rewritten.
        current_fields = {field.name for field in self.client.get_table(self.feedback_ref).schema}
        for field in feedback_schema:
            if field.name not in current_fields:
                self.client.query(
                    f"ALTER TABLE `{self.feedback_ref}` ADD COLUMN IF NOT EXISTS `{field.name}` {field.field_type}",
                    location=settings.location,
                ).result()
        self.ensure_workflow_schema()
        self.ensure_environment_schema()
        ensure_ownership_tables(self.client, self.dataset_ref)
        read_cache.invalidate()

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
        read_cache.invalidate()

    def overview(self, environment_id: str | None = None) -> dict[str, Any]:
        return load_overview(self, environment_id)

    def list_feedback(
        self,
        *,
        state: str | None = None,
        severity: str | None = None,
        verdict: str | None = None,
        root_cause: str | None = None,
        reporter: str | list[str] | None = None,
        domain: str | None = None,
        environment: str | None = None,
        environment_id: str | None = None,
        agent_id: str | None = None,
        public_status: str | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> tuple[list[FeedbackRecord], int]:
        conditions = ["TRUE"]
        parameters: list[Any] = []
        if agent_id:
            conditions.append("agent_id = @agent_id")
            parameters.append(bigquery.ScalarQueryParameter("agent_id", "STRING", agent_id))
        if environment_id:
            selected = self.get_agent_environment(environment_id)
            legacy_kind = selected["kind"] if legacy_environment_id(selected["agent_id"], selected["kind"]) == environment_id else "__not_legacy__"
            conditions.append(f"""(JSON_VALUE(run_context_json,'$.environment_id')=@environment_id
                OR (JSON_VALUE(run_context_json,'$.environment_id') IS NULL AND agent_id=@environment_agent AND environment=@legacy_kind)
                OR feedback_id IN (SELECT m.feedback_id FROM `{self.workflow_table('feedback_main_environments')}` m
                    WHERE m.agent_id=@environment_agent AND m.environment_id=@environment_id)
                OR feedback_id IN (SELECT j.feedback_id FROM `{self.workflow_table('feedback_workflow_jobs')}` j
                    WHERE j.kind='retest' AND j.target_id=@environment_id))""")
            parameters.extend([bigquery.ScalarQueryParameter("environment_id", "STRING", environment_id),
                bigquery.ScalarQueryParameter("environment_agent", "STRING", selected["agent_id"]),
                bigquery.ScalarQueryParameter("legacy_kind", "STRING", legacy_kind)])
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
        if reporter is not None:
            reporter_condition, reporter_parameter = self._reporter_filter(reporter)
            conditions.append(reporter_condition)
            parameters.append(reporter_parameter)
        if domain:
            conditions.append(f"LOWER({FEEDBACK_DOMAIN_SQL}) = LOWER(TRIM(@domain))")
            parameters.append(bigquery.ScalarQueryParameter("domain", "STRING", domain))
        if environment:
            source_match = f"COALESCE(NULLIF({self._source_environment_kind()}, ''), 'unknown') = @environment"
            if environment in {'nonprod', 'prod'}:
                # Environment filters describe case membership, not a relabel of
                # the original report. A failed/queued check is still a link,
                # consistently with the named workspace/dashboard selection.
                conditions.append(f"""({source_match} OR feedback_id IN (
                    SELECT j.feedback_id FROM `{self.workflow_table('feedback_workflow_jobs')}` j
                    WHERE j.kind='retest' AND {self._job_environment_kind('j')} = @environment))""")
            else:
                # "Not recorded" is an original-source property; unknown target
                # metadata is never guessed to be a real named environment.
                conditions.append(source_match)
            parameters.append(bigquery.ScalarQueryParameter("environment", "STRING", environment))
        if public_status:
            conditions.append(f"{PUBLIC_STATUS_SQL} = @public_status")
            parameters.append(bigquery.ScalarQueryParameter("public_status", "STRING", public_status))
        if search:
            conditions.append(
                "(LOWER(title) LIKE LOWER(@search) OR LOWER(feedback_id) LIKE LOWER(@search) "
                "OR LOWER(question) LIKE LOWER(@search) OR LOWER(run_id) LIKE LOWER(@search))"
            )
            parameters.append(bigquery.ScalarQueryParameter("search", "STRING", f"%{search}%"))
        where = " AND ".join(conditions)
        count_job = self.client.query(
            f"SELECT COUNT(*) AS total FROM `{self.feedback_ref}` f WHERE {where}",
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
            f"SELECT f.*,m.environment_id AS main_environment_id,m.environment_kind AS main_environment_kind,"
            f"m.environment_label AS main_environment_label FROM `{self.feedback_ref}` f "
            f"LEFT JOIN (SELECT feedback_id AS main_feedback_id,agent_id AS main_agent_id,environment_id,environment_kind,environment_label "
            f"FROM `{self.workflow_table('feedback_main_environments')}`) m ON m.main_feedback_id=f.feedback_id AND m.main_agent_id=f.agent_id "
            f"WHERE {where} ORDER BY f.updated_at DESC,f.feedback_id DESC LIMIT @limit OFFSET @offset",
            job_config=bigquery.QueryJobConfig(query_parameters=query_parameters),
            location=settings.location,
        ).result()
        records = [self._record(dict(row)) for row in rows]
        if environment_id:
            results = self.environment_results(records, environment_id)
            for record in records:
                record.environmentResult = results.get(record.id)
        elif any(record.mainEnvironmentId for record in records):
            results = self.main_environment_results(records)
            for record in records:
                record.environmentResult = results.get(record.id)
        return records, total

    def _reporter_filter(self, reporter: str | list[str]) -> tuple[str, Any]:
        if isinstance(reporter, list):
            return (
                owner_scope(self, 'f'),
                bigquery.ArrayQueryParameter("reporters", "STRING", [value.strip().lower() for value in reporter]),
            )
        return (
            owner_scope(self, 'f', parameter='reporter', scalar=True),
            bigquery.ScalarQueryParameter("reporter", "STRING", reporter),
        )

    def list_feedback_filter_options(
        self,
        reporter: str | list[str] | None = None,
        *,
        include_reporters: bool = False,
    ) -> dict[str, list[str]]:
        """Return choices from the entire authorized scope, never just one page."""
        where = "TRUE"
        parameters: list[Any] = []
        if reporter is not None:
            where, parameter = self._reporter_filter(reporter)
            parameters.append(parameter)
        reporter_column = ", NULLIF(TRIM(reporter), '') AS reporter" if include_reporters else ""
        reporter_choices = (
            ", ARRAY(SELECT MIN(reporter) FROM scoped WHERE reporter IS NOT NULL "
            "GROUP BY LOWER(reporter) ORDER BY LOWER(MIN(reporter))) AS reporters"
            if include_reporters else ""
        )
        rows = self.client.query(
            f"WITH scoped AS (SELECT {FEEDBACK_DOMAIN_SQL} AS domain{reporter_column} "
            f"FROM `{self.feedback_ref}` f WHERE {where}) "
            "SELECT ARRAY(SELECT MIN(domain) FROM scoped "
            "GROUP BY LOWER(domain) ORDER BY LOWER(MIN(domain))) AS domains"
            f"{reporter_choices}",
            job_config=bigquery.QueryJobConfig(query_parameters=parameters),
            location=settings.location,
        ).result()
        row = dict(next(iter(rows), {}))
        options = {"domains": list(row.get("domains") or [])}
        if include_reporters:
            options["reporters"] = list(row.get("reporters") or [])
        return options

    def list_business_taxonomy(self, reporter: str | list[str] | None = None) -> dict:
        """Standard suggestions plus saved labels inside the caller's feedback scope."""
        where, parameters = 'TRUE', []
        if reporter is not None:
            where, parameter = self._reporter_filter(reporter)
            parameters.append(parameter)
        rows = self.client.query(f"""SELECT DISTINCT {FEEDBACK_DOMAIN_SQL} AS business_domain,
            {FEEDBACK_SUBDOMAIN_SQL} AS business_subdomain
            FROM `{self.feedback_ref}` f WHERE {where}
            ORDER BY business_domain,business_subdomain LIMIT 1000""",
            job_config=bigquery.QueryJobConfig(query_parameters=parameters), location=settings.location).result()
        return business_taxonomy_options([dict(row) for row in rows])

    def get_feedback(self, feedback_id: str) -> FeedbackRecord | None:
        rows = self.client.query(
            f"SELECT f.*,m.environment_id AS main_environment_id,m.environment_kind AS main_environment_kind,"
            f"m.environment_label AS main_environment_label FROM `{self.feedback_ref}` f "
            f"LEFT JOIN (SELECT feedback_id AS main_feedback_id,agent_id AS main_agent_id,environment_id,environment_kind,environment_label "
            f"FROM `{self.workflow_table('feedback_main_environments')}`) m ON m.main_feedback_id=f.feedback_id AND m.main_agent_id=f.agent_id "
            f"WHERE f.feedback_id = @feedback_id LIMIT 1",
            job_config=bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("feedback_id", "STRING", feedback_id)
            ]),
            location=settings.location,
        ).result()
        row = next(iter(rows), None)
        return self._record(dict(row)) if row else None

    def list_my_feedback(
        self,
        reporter: str | list[str],
        *,
        search: str | None = None,
        domain: str | None = None,
        environment: str | None = None,
        environment_id: str | None = None,
        public_status: str | None = None,
        page: int = 1,
        page_size: int = 25,
    ) -> tuple[list[dict[str, Any]], int]:
        records, total = self.list_feedback(
            reporter=reporter,
            search=search,
            domain=domain,
            environment=environment,
            **({"environment_id": environment_id} if environment_id else {}),
            public_status=public_status,
            page=page,
            page_size=page_size,
        )
        if not records:
            return [], total
        reviews = self.feedback_answer_reviews([record.id for record in records], reporter)
        # A list is a summary, not twenty full answers and twenty timelines.
        summaries = []
        for record in records:
            summary = self._my_feedback_record(record, [])
            summary['answerReview'] = reviews.get(record.id)
            for key in ("question", "agentResponse", "expectedBehavior", "legacyContext", "preliminaryCauseRationale", "proposedFix"):
                summary[key] = None
            summary["events"] = []
            summaries.append(summary)
        return summaries, total

    def get_my_feedback(self, feedback_id: str, reporter: str | list[str]) -> dict[str, Any] | None:
        reporter_filter = owner_scope(self, 'f', parameter='reporter', scalar=True)
        reporter_parameters: list[Any]
        if isinstance(reporter, list):
            reporter_filter = owner_scope(self, 'f')
            reporter_parameters = [bigquery.ArrayQueryParameter("reporters", "STRING", [value.strip().lower() for value in reporter])]
        else:
            reporter_parameters = [bigquery.ScalarQueryParameter("reporter", "STRING", reporter)]
        rows = self.client.query(
            f"SELECT f.*,m.environment_id AS main_environment_id,m.environment_kind AS main_environment_kind,"
            f"m.environment_label AS main_environment_label FROM `{self.feedback_ref}` f "
            f"LEFT JOIN (SELECT feedback_id AS main_feedback_id,agent_id AS main_agent_id,environment_id,environment_kind,environment_label "
            f"FROM `{self.workflow_table('feedback_main_environments')}`) m ON m.main_feedback_id=f.feedback_id AND m.main_agent_id=f.agent_id "
            f"WHERE f.feedback_id = @feedback_id AND {reporter_filter} LIMIT 1",
            job_config=bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("feedback_id", "STRING", feedback_id),
                *reporter_parameters,
            ]),
            location=settings.location,
        ).result()
        row = next(iter(rows), None)
        if not row:
            return None
        record = self._record(dict(row))
        review = self.feedback_answer_reviews([feedback_id], reporter).get(feedback_id)
        events = self._public_event_map([feedback_id]).get(feedback_id, [])
        return {**self._my_feedback_record(record, events), 'answerReview': review}

    def update_my_feedback(
        self,
        feedback_id: str,
        reporter: str | list[str],
        payload: MyFeedbackUpdate,
        actor: str,
    ) -> dict[str, Any] | None:
        updates = payload.model_dump(exclude_unset=True)
        expected_revision = updates.pop("expected_revision", None)
        expected_updated_at = updates.pop('expected_updated_at', None)
        if not updates:
            return self.get_my_feedback(feedback_id, reporter)

        reporters = reporter if isinstance(reporter, list) else [reporter]
        rows = self.client.query(
            f"SELECT f.* FROM `{self.feedback_ref}` f "
            f"WHERE f.feedback_id = @feedback_id AND {owner_scope(self, 'f')} LIMIT 1",
            job_config=bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("feedback_id", "STRING", feedback_id),
                bigquery.ArrayQueryParameter("reporters", "STRING", [email.strip().lower() for email in reporters]),
            ]),
            location=settings.location,
        ).result()
        current_row = next(iter(rows), None)
        if not current_row:
            return None
        current = dict(current_row)
        from .submission_edits import REVISION_FIELDS, meaningful_updates, timestamp
        if expected_updated_at is not None and timestamp(expected_updated_at) != timestamp(current.get('updated_at')):
            raise ValueError('This submission changed while you were editing. Reload it before saving.')
        terminal_states = {"Review complete", "Golden candidate", "Approved for dataset", "Rejected", "Duplicate"}
        terminal_public_statuses = {"Resolved", "Not planned", "Duplicate", "Awaiting your confirmation", "Retesting"}
        if current.get("state") in terminal_states or current.get("public_status") in terminal_public_statuses:
            raise ValueError("This feedback can no longer be edited because its review is closed")
        revision = int(current.get("revision") or 1)
        if expected_revision is not None and expected_revision != revision:
            raise ValueError("This submission changed while you were editing. Reload it before saving.")
        updates = meaningful_updates(current, self._json_object(current.get('run_context_json')), updates)
        if not updates:
            return self.get_my_feedback(feedback_id, reporter)
        revision_changed = bool(REVISION_FIELDS.intersection(updates))
        if not revision_changed and expected_updated_at is None:
            raise ValueError('Refresh the feedback editor before saving these details; an edit version is required.')
        now = datetime.now(timezone.utc).isoformat()
        next_revision = revision + 1 if revision_changed else revision
        assignments = ["updated_at = @updated_at"]
        if revision_changed:
            assignments.extend(["revision = @next_revision", "latest_published_attempt_id = NULL"])
        parameters: list[bigquery.ScalarQueryParameter] = [
            bigquery.ScalarQueryParameter("updated_at", "TIMESTAMP", now),
            bigquery.ScalarQueryParameter("feedback_id", "STRING", feedback_id),
            bigquery.ArrayQueryParameter("reporters", "STRING", [email.strip().lower() for email in reporters]),
            bigquery.ScalarQueryParameter("expected_revision", "INT64", revision),
            bigquery.ScalarQueryParameter('expected_updated_at', 'TIMESTAMP', timestamp(current.get('updated_at'))),
            bigquery.ScalarQueryParameter("next_revision", "INT64", next_revision),
            bigquery.ArrayQueryParameter("closed_states", "STRING", sorted(terminal_states)),
            bigquery.ArrayQueryParameter("closed_statuses", "STRING", sorted(terminal_public_statuses)),
        ]
        candidate = {**current, "feedback_id": feedback_id, "updated_at": now, "revision": next_revision}
        if revision_changed:
            candidate['latest_published_attempt_id'] = None
        context = self._json_object(current.get("run_context_json"))
        if "environment_id" in updates:
            identity = updates["environment_id"]
            if identity:
                selected_environment = self.get_agent_environment(identity)
                context.update(environment_id=identity, environment_label=selected_environment["name"], environment_kind=selected_environment["kind"])
            else:
                context.pop("environment_id", None)
                context.pop("environment_label", None)
                context.pop("environment_kind", None)
        elif "environment" in updates and updates["environment"] != current.get("environment"):
            context.pop("environment_id", None)
            context.pop("environment_label", None)
            context.pop("environment_kind", None)
        if "question" in updates:
            question = str(updates["question"] or "").strip()
            assignments.append("question = @question")
            parameters.append(bigquery.ScalarQueryParameter("question", "STRING", question))
            candidate["question"] = question
        for field in ("answer", "agent_id", "agent_version", "run_id", "conversation_id"):
            if field not in updates:
                continue
            value = str(updates[field] or "").strip()
            if field == "agent_id" and not value:
                raise ValueError("Agent identifier cannot be empty")
            value = value if field in {"answer", "agent_id"} else value or None
            assignments.append(f"{field} = @{field}")
            parameters.append(bigquery.ScalarQueryParameter(field, "STRING", value))
            candidate[field] = value
        if "title" in updates:
            title = str(updates["title"] or "").strip()
            if not title:
                raise ValueError("Add a short title before saving your feedback")
            assignments.append("title = @title")
            parameters.append(bigquery.ScalarQueryParameter("title", "STRING", title))
            candidate["title"] = title
        for key in ("environment", "business_domain", "business_subdomain"):
            if key in updates:
                assignments.append(f"{key} = @{key}")
                value = stored_environment_kind(str(candidate.get("agent_id") or settings.default_agent_id), updates[key] or 'unknown', context.get("environment_id")) if key == "environment" else updates[key]
                parameters.append(bigquery.ScalarQueryParameter(key, "STRING", value))
                candidate[key] = value
        if "business_domain" in updates or "business_subdomain" in updates:
            domain_value = "@business_domain" if "business_domain" in updates else "business_domain"
            assignments.extend([f"domain_verified = COALESCE({domain_value}, 'Unspecified') != 'Unspecified'", "domain_source = 'user_confirmed'", "domain_confidence = NULL", "domain_evidence_json = '[]'", "domain_reason = 'Business context recorded by the submitter; an unknown domain still needs evidence.'"])
            candidate.update(domain_verified=bool(candidate.get("business_domain") and candidate["business_domain"] != "Unspecified"), domain_source="user_confirmed", domain_confidence=None, domain_evidence_json="[]", domain_reason="Business context recorded by the submitter; an unknown domain still needs evidence.")
        if "feedback_text" in updates:
            feedback_text = str(updates["feedback_text"] or "").strip()
            if not feedback_text:
                raise ValueError("Feedback details cannot be empty")
            assignments.extend([
                "feedback_text = @feedback_text",
                "full_quote = @feedback_text",
                "excerpt = SUBSTR(@feedback_text, 1, 160)",
            ])
            parameters.append(bigquery.ScalarQueryParameter("feedback_text", "STRING", feedback_text))
            candidate.update(feedback_text=feedback_text, full_quote=feedback_text, excerpt=feedback_text[:160])
        if "expected_behavior" in updates:
            expected_behavior = str(updates["expected_behavior"] or "").strip() or None
            assignments.extend([
                "expected_behavior = @expected_behavior",
                "ground_truth_hint = @expected_behavior",
                "expected_behavior_verified = FALSE",
            ])
            parameters.append(bigquery.ScalarQueryParameter("expected_behavior", "STRING", expected_behavior))
            candidate.update(expected_behavior=expected_behavior, ground_truth_hint=expected_behavior, expected_behavior_verified=False)
        if "user_verdict" in updates and updates["user_verdict"] is not None:
            assignments.append("user_verdict = @user_verdict")
            parameters.append(bigquery.ScalarQueryParameter("user_verdict", "STRING", updates["user_verdict"]))
            candidate["user_verdict"] = updates["user_verdict"]
        if "issue_categories" in updates and updates["issue_categories"] is not None:
            categories_json = json.dumps(updates["issue_categories"])
            assignments.extend(["issue_categories_json = @categories_json", "tags_json = @categories_json"])
            parameters.append(bigquery.ScalarQueryParameter("categories_json", "STRING", categories_json))
            candidate.update(issue_categories_json=categories_json, tags_json=categories_json)
            context["reporter_edited_categories"] = True
        if "impact" in updates and updates["impact"] is not None:
            impact = updates["impact"]
            assignments.extend(["impact = @impact", "severity = @severity"])
            parameters.extend([
                bigquery.ScalarQueryParameter("impact", "STRING", impact),
                bigquery.ScalarQueryParameter("severity", "STRING", {"Low": "Low", "Medium": "Med", "High": "High"}[impact]),
            ])
            candidate.update(impact=impact, severity={"Low": "Low", "Medium": "Med", "High": "High"}[impact])

        for field in ("data_source", "language", "follow_up"):
            if field in updates:
                context[field] = str(updates[field] or "").strip() or None

        if revision_changed:
            assignments.extend(["expected_behavior_verified = FALSE", "confirmed_rca = NULL", "subcategory = NULL", "suggested_rca = NULL", "suggested_rca_confidence = NULL", "rca_rationale = NULL", "rca_suggested_subcategory = NULL", "rca_evidence_json = '[]'", "rca_review_required = TRUE", "rca_suggestion_status = 'review_required'"])
            candidate.update(expected_behavior_verified=False, confirmed_rca=None, subcategory=None, suggested_rca=None, suggested_rca_confidence=None, rca_rationale=None, rca_suggested_subcategory=None, rca_evidence_json="[]", rca_review_required=True, rca_suggestion_status="review_required")

        reopened_needs_info = revision_changed and current.get("public_status") == "Needs information"
        if revision_changed and current.get("state") in {"Evidence review", "Needs more information"}:
            assignments.extend(["state = 'Triaged'", "expected_behavior_verified = FALSE"])
            candidate.update(state="Triaged", expected_behavior_verified=False)
        if reopened_needs_info:
            assignments.extend([
                "public_status = 'Received'",
                "public_message = 'Updated details received; the review team will take another look.'",
            ])
            candidate.update(public_status="Received", public_message="Updated details received; the review team will take another look.")

        snapshot_id = f"submission:{feedback_id}:r{next_revision}" if revision_changed else context.get('submission_answer_id') or f'original:{feedback_id}'
        if revision_changed:
            context["submission_answer_id"] = snapshot_id
        elif 'user_verdict' in updates:
            verdicts = dict(context.get('answer_user_verdicts') or {})
            verdicts[snapshot_id] = updates['user_verdict']
            context['answer_user_verdicts'] = verdicts
        candidate["run_context_json"] = json.dumps(context, default=str)
        assignments.append("run_context_json = @run_context_json")
        parameters.append(bigquery.ScalarQueryParameter("run_context_json", "STRING", candidate["run_context_json"]))
        before = self._record({**current, "feedback_id": feedback_id})
        after = self._record(candidate)
        def snapshot(record, kind):
            return json.dumps({"kind": kind, "question": record.prompt, "answer": record.generatedAnswer,
                "environment": record.environment, "environmentId": record.environmentId, "environmentLabel": record.environmentLabel, "agentId": record.agentName, "agentVersion": record.agentVersion,
                "runId": record.runId, "conversationId": record.conversationId, "revision": record.revision,
                "businessDomain": record.businessDomain, "businessSubdomain": record.businessSubdomain,
                "feedbackText": record.fullQuote or record.excerpt, "expectedBehavior": record.groundTruthHint,
                "userVerdict": record.userVerdict, "issueCategories": record.issueCategories, "impact": record.impact,
                "dataSource": record.runContext.get("data_source"), "language": record.runContext.get("language"),
                "followUp": record.runContext.get("follow_up"), "createdAt": record.reportedTime if kind == "original" else now,
                "origin": "reporter_correction" if kind == "submission_edit" else "submitted_original"}, default=str)
        event_payload = {"public_status": candidate.get("public_status") or self._public_status_from_internal_state(str(candidate.get("state") or "Submitted")),
                         "updated_fields": sorted(updates), "revision": next_revision, "answer_version_id": snapshot_id,
                         'revision_changed': revision_changed, 'user_verdict': updates.get('user_verdict')}
        job_id = "JOB-" + hashlib.sha256(f"{feedback_id}:{next_revision}:enrich:{actor}:None:enrich".encode()).hexdigest()[:32]
        parameters.extend([
            bigquery.ScalarQueryParameter("snapshot_id", "STRING", snapshot_id),
            bigquery.ScalarQueryParameter("original_id", "STRING", f"original:{feedback_id}"),
            bigquery.ScalarQueryParameter("original_payload", "STRING", snapshot(before, "original")),
            bigquery.ScalarQueryParameter("snapshot_payload", "STRING", snapshot(after, "submission_edit")),
            bigquery.ScalarQueryParameter("event_id", "STRING", str(uuid.uuid4())),
            bigquery.ScalarQueryParameter("actor", "STRING", actor),
            bigquery.ScalarQueryParameter("event_payload", "STRING", json.dumps(event_payload)),
            bigquery.ScalarQueryParameter("job_id", "STRING", job_id),
            bigquery.ScalarQueryParameter("job_environment", "STRING", after.environment),
            bigquery.ScalarQueryParameter("job_payload", "STRING", after.model_dump_json()),
        ])
        assignments = list(dict.fromkeys(assignments))
        sql = f"""BEGIN TRANSACTION;
            UPDATE `{self.feedback_ref}` f SET {', '.join(assignments)}
                WHERE f.feedback_id = @feedback_id AND {owner_scope(self, 'f')}
             AND COALESCE(revision, 1) = @expected_revision
                AND f.updated_at IS NOT DISTINCT FROM @expected_updated_at
                AND COALESCE(state, 'Submitted') NOT IN UNNEST(@closed_states)
                AND COALESCE(public_status, 'Received') NOT IN UNNEST(@closed_statuses);
            ASSERT @@row_count = 1 AS 'Submission changed or closed during editing';
            MERGE `{self.workflow_table('feedback_answer_versions')}` v USING (SELECT @original_id AS id) s ON v.id=s.id
            WHEN NOT MATCHED THEN INSERT(id,feedback_id,attempt_id,created_at,payload_json) VALUES(@original_id,@feedback_id,NULL,@updated_at,@original_payload);
            INSERT INTO `{self.workflow_table('feedback_answer_versions')}` (id,feedback_id,attempt_id,created_at,payload_json)
                VALUES(@snapshot_id,@feedback_id,NULL,@updated_at,@snapshot_payload);
            INSERT INTO `{self.events_ref}` (event_id,feedback_id,event_type,created_at,actor,payload_json)
                VALUES(@event_id,@feedback_id,'submitter_updated',@updated_at,@actor,@event_payload);
            MERGE `{self.workflow_table('feedback_workflow_jobs')}` j USING (SELECT @job_id AS id) s ON j.id=s.id
            WHEN NOT MATCHED THEN INSERT(id,feedback_id,kind,status,created_at,updated_at,attempts,revision,environment,requested_by,payload_json)
                VALUES(@job_id,@feedback_id,'enrich','queued',@updated_at,@updated_at,0,@next_revision,@job_environment,@actor,@job_payload);
            COMMIT TRANSACTION;"""
        if not revision_changed:
            # Opinion/metadata edits are audited but never create answer variants,
            # clear an RCA/latest-result pointer, or enqueue any provider work.
            sql = f"""BEGIN TRANSACTION;
                UPDATE `{self.feedback_ref}` f SET {', '.join(assignments)}
                WHERE f.feedback_id=@feedback_id AND {owner_scope(self,'f')}
                    AND COALESCE(revision,1)=@expected_revision
                    AND f.updated_at IS NOT DISTINCT FROM @expected_updated_at
                    AND COALESCE(state,'Submitted') NOT IN UNNEST(@closed_states)
                    AND COALESCE(public_status,'Received') NOT IN UNNEST(@closed_statuses);
                ASSERT @@row_count=1 AS 'Submission changed or closed during editing';
                INSERT INTO `{self.events_ref}` (event_id,feedback_id,event_type,created_at,actor,payload_json)
                    VALUES(@event_id,@feedback_id,'submitter_updated',@updated_at,@actor,@event_payload);
                COMMIT TRANSACTION;"""
        try:
            self.client.query(sql,
            job_config=bigquery.QueryJobConfig(query_parameters=parameters),
            location=settings.location,
            ).result()
        except Exception as exc:
            if "Submission changed or closed during editing" in str(exc):
                raise ValueError("This submission changed or its review closed while you were editing. Reload before saving.") from exc
            raise
        read_cache.invalidate()
        return self.get_my_feedback(feedback_id, reporter)

    def _public_event_map(self, feedback_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        if not feedback_ids:
            return {}
        rows = self.client.query(
            f"SELECT feedback_id, event_id, event_type, created_at, payload_json "
            f"FROM `{self.events_ref}` WHERE feedback_id IN UNNEST(@feedback_ids) "
            "AND event_type IN ('submitted', 'public_status_updated', 'submitter_updated', 'rca_auto_triaged') ORDER BY created_at",
            job_config=bigquery.QueryJobConfig(query_parameters=[
                bigquery.ArrayQueryParameter("feedback_ids", "STRING", feedback_ids)
            ]),
            location=settings.location,
        ).result()
        events: dict[str, list[dict[str, Any]]] = {}
        for raw in rows:
            row = dict(raw)
            payload = self._json_object(row.get("payload_json"))
            event_type = row.get("event_type")
            if event_type == "submitted":
                event = {
                    "id": str(row.get("event_id") or "submitted"),
                    "status": "Received",
                    "createdAt": str(row.get("created_at") or ""),
                    "message": "We received your feedback.",
                }
            elif event_type == "submitter_updated":
                status = payload.get("public_status", "In review")
                if status not in {"Received", "In review", "Needs information", "Retesting", "Awaiting your confirmation", "Resolved", "Not planned", "Duplicate"}:
                    status = "In review"
                event = {
                    "id": str(row.get("event_id") or "submitter-update"),
                    "status": status,
                    "createdAt": str(row.get("created_at") or ""),
                    "message": "You updated your submission. The review team will see the latest details.",
                }
            else:
                status = payload.get("public_status")
                if status not in {"Received", "In review", "Needs information", "Retesting", "Awaiting your confirmation", "Resolved", "Not planned", "Duplicate"}:
                    continue
                message = payload.get("public_message") or payload.get("resolution_summary") or {
                    "In review": "Our team is reviewing your feedback.",
                    "Needs information": "Our team needs more information to continue.",
                    "Resolved": "Your feedback has been resolved.",
                    "Not planned": "We reviewed your feedback but are not planning a change.",
                    "Duplicate": "This feedback is tracked with a related report.",
                    "Received": "We received your feedback.",
                    "Retesting": "A fresh answer is being checked against source evidence.",
                    "Awaiting your confirmation": "An updated answer is ready for you to review.",
                }[status]
                event = {
                    "id": str(row.get("event_id") or "status-update"),
                    "status": status,
                    "createdAt": str(row.get("created_at") or ""),
                    "message": str(message),
                }
            events.setdefault(str(row.get("feedback_id")), []).append(event)
        return events

    @staticmethod
    def _my_feedback_record(record: FeedbackRecord, events: list[dict[str, Any]]) -> dict[str, Any]:
        timeline = list(events)
        if not timeline:
            timeline.append({
                "id": f"{record.id}-submitted",
                "status": "Received",
                "createdAt": record.reportedTime,
                "message": "We received your feedback.",
            })
        legacy_context = None
        if record.runContext.get("source") in {"legacy_csv_import", "legacy_xlsx_import"}:
            legacy_fields = {
                "dataSource": "data_source",
                "subDomain": "sub_domain",
                "answerStatus": "answer_status",
                "followUp": "follow_up",
                "priorResolution": "resolution",
                "language": "language",
            }
            safe_values = {
                public_key: str(record.runContext.get(source_key)).strip()[:4000]
                for public_key, source_key in legacy_fields.items()
                if record.runContext.get(source_key) not in (None, "")
            }
            legacy_context = safe_values or None
        return {
            "id": record.id,
            "title": record.title,
            "feedbackText": record.fullQuote or record.excerpt or "",
            "question": record.prompt or None,
            "agentResponse": record.generatedAnswer or None,
            "agentId": record.agentName,
            "runId": record.runId,
            "conversationId": record.conversationId,
            "dataSource": record.runContext.get("data_source") or None,
            "language": record.runContext.get("language") or None,
            "followUp": record.runContext.get("follow_up") or None,
            "userVerdict": record.userVerdict,
            "issueCategories": record.issueCategories,
            "impact": record.impact,
            "severity": record.severity,
            "domain": record.domain,
            "businessDomain": record.businessDomain,
            "businessSubdomain": record.businessSubdomain,
            "domainSource": record.domainSource,
            "domainConfidence": record.domainConfidence,
            "domainReason": record.domainReason,
            "domainVerified": record.domainVerified,
            "domainEvidence": record.domainEvidence,
            "environment": record.environment,
            "environmentId": record.environmentId,
            "environmentLabel": record.environmentLabel,
            "mainEnvironmentId": record.mainEnvironmentId,
            "mainEnvironmentKind": record.mainEnvironmentKind,
            "mainEnvironmentLabel": record.mainEnvironmentLabel,
            "environmentResult": record.environmentResult,
            "agentVersion": record.agentVersion,
            "revision": record.revision,
            "latestPublishedAttemptId": record.latestPublishedAttemptId,
            "expectedBehavior": record.groundTruthHint,
            "expectedBehaviorVerified": record.expectedBehaviorVerified,
            "reviewedCause": record.confirmedRca if record.suggestedRcaStatus == "reviewer_classified" else None,
            "reviewedSubdomain": None,
            "reviewedDefect": record.defectSubCategory if record.suggestedRcaStatus == "reviewer_classified" else None,
            "preliminaryCause": record.suggestedRca if record.suggestedRcaStatus != "reviewer_classified" else None,
            "preliminarySubdomain": None,
            "preliminaryDefect": record.suggestedRcaSubcategory if record.suggestedRcaStatus != "reviewer_classified" else None,
            "preliminaryCauseConfidence": record.suggestedRcaConfidence if record.suggestedRcaStatus != "reviewer_classified" else None,
            "preliminaryCauseRationale": record.suggestedRcaRationale if record.suggestedRcaStatus != "reviewer_classified" else None,
            "proposedFix": record.recommendedFix or None,
            "legacyContext": legacy_context,
            "publicStatus": record.publicStatus,
            "publicMessage": record.publicMessage,
            "submittedAt": record.reportedTime,
            "updatedAt": record.updatedAt or record.reportedTime,
            "resolutionSummary": record.resolutionSummary,
            "resolutionVersion": record.resolutionVersion,
            "resolvedAt": record.resolvedAt,
            "canEdit": record.state not in {"Review complete", "Golden candidate", "Approved for dataset", "Rejected", "Duplicate"}
            and record.publicStatus not in {"Resolved", "Not planned", "Duplicate", "Awaiting your confirmation", "Retesting"},
            "events": timeline,
        }

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
        run_context = dict(payload.run_context)
        if payload.environment_id:
            run_context["environment_id"] = payload.environment_id
            run_context["environment_kind"] = payload.environment
        explicit_taxonomy = bool({'business_domain', 'business_subdomain'}.intersection(payload.model_fields_set))
        if explicit_taxonomy:
            business_domain = payload.business_domain or 'Unspecified'
            business_subdomain = payload.business_subdomain
            has_business_context = business_domain != 'Unspecified' or bool(business_subdomain)
            domain_source = 'user_submitted' if has_business_context else 'unspecified'
            domain_reason = 'Business context supplied by the submitter; it has not been independently verified against documents.' if has_business_context else None
        else:
            business_domain = domain_from_metadata(str(payload.run_context.get('domain') or payload.run_context.get('sub_domain') or ''))
            business_subdomain = payload.run_context.get('business_subdomain') or payload.run_context.get('sub_domain')
            workbook = payload.source == 'legacy_xlsx_import' and payload.run_context.get('classification_source') == 'workbook_import'
            domain_source = 'workbook_import' if workbook else 'submitted' if payload.run_context.get('domain') or payload.run_context.get('sub_domain') else 'unspecified'
            domain_reason = 'Domain and subdomain imported from the authoritative workbook classification; not an AI inference.' if workbook else None
        return {
            "feedback_id": feedback_id,
            "created_at": now,
            "updated_at": now,
            "agent_id": payload.agent_id,
            "run_id": payload.run_id,
            "conversation_id": payload.conversation_id,
            "question": payload.question or "",
            "answer": payload.answer or "",
            "title": (payload.title or payload.question or "User feedback").strip()[:120],
            "environment": stored_environment_kind(payload.agent_id, payload.environment, run_context.get("environment_id")),
            "agent_version": payload.agent_version,
            "revision": 1,
            "business_domain": business_domain,
            "business_subdomain": business_subdomain,
            "domain_source": domain_source,
            "domain_reason": domain_reason,
            "domain_verified": False,
            "excerpt": payload.feedback_text[:160],
            "full_quote": payload.feedback_text,
            "user_verdict": payload.user_verdict,
            "issue_categories_json": json.dumps(payload.issue_categories),
            "feedback_text": payload.feedback_text,
            "expected_behavior": payload.expected_behavior,
            "expected_behavior_verified": False,
            "impact": payload.impact,
            "severity": {"Low": "Low", "Medium": "Med", "High": "High"}[payload.impact],
            "state": "Submitted",
            "reporter": payload.reporter,
            "public_status": "Received",
            "public_message": None,
            "resolution_summary": None,
            "resolution_version": None,
            "resolved_at": None,
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
            "run_context_json": json.dumps(run_context, default=str),
            "source": payload.source,
        }

    def update_triage(
        self,
        feedback_id: str,
        payload: TriageUpdate,
        actor: str | None = None,
        allow_dataset_lifecycle: bool = False,
    ) -> FeedbackRecord | None:
        updates = payload.model_dump(exclude_unset=True)
        if not updates:
            return self.get_feedback(feedback_id)
        target_state = updates.get("state")
        if target_state in {"Golden candidate", "Approved for dataset"} and not allow_dataset_lifecycle:
            raise ValueError("Feedback can only enter a golden dataset through the reviewed dataset workflow")
        if target_state == "Evidence review":
            current = self.get_feedback(feedback_id)
            if not current:
                return None
            if current.state == "Approved for dataset":
                raise ValueError("An approved feedback case cannot be moved back into evidence review")
            if current.state == "Golden candidate":
                self.client.query(
                    f"UPDATE `{self.golden_cases_ref}` SET state = 'rejected' "
                    "WHERE feedback_id = @feedback_id AND state = 'candidate'",
                    job_config=bigquery.QueryJobConfig(query_parameters=[
                        bigquery.ScalarQueryParameter("feedback_id", "STRING", feedback_id)
                    ]),
                    location=settings.location,
                ).result()
        if target_state == "Review complete":
            current = self.get_feedback(feedback_id)
            if not current:
                return None
            expected_behavior = updates.get("expected_behavior", current.groundTruthHint)
            verified = updates.get("expected_behavior_verified", current.expectedBehaviorVerified)
            if current.state not in {"Evidence review", "Review complete"}:
                raise ValueError("Complete evidence review before marking feedback reviewed")
            if not str(expected_behavior or "").strip() or not verified:
                raise ValueError("Reviewer-verified expected behavior is required to complete review")
        public_fields = {"public_status", "public_message", "resolution_summary", "resolution_version"}
        public_event_payload: dict[str, Any] | None = None
        if public_fields.intersection(updates):
            current_public = self.get_feedback(feedback_id)
            if not current_public:
                return None
            public_status = updates.get("public_status", current_public.publicStatus)
            public_message = updates.get("public_message", current_public.publicMessage)
            resolution_summary = updates.get("resolution_summary", current_public.resolutionSummary)
            resolution_version = updates.get("resolution_version", current_public.resolutionVersion)
            if public_status == "Resolved" and not str(resolution_summary or "").strip():
                raise ValueError("Add a user-facing resolution summary before marking feedback resolved")
            if public_status in {"Resolved", "Retesting", "Awaiting your confirmation"} and public_status != current_public.publicStatus:
                raise ValueError("Reporter confirmation and the retest workflow must be used for this status")
            if public_status in {"Needs information", "Not planned", "Duplicate"} and not str(public_message or resolution_summary or "").strip():
                raise ValueError("Add a user-facing explanation for this status")
            public_event_payload = {
                "public_status": public_status,
                "public_message": public_message,
                "resolution_summary": resolution_summary,
                "resolution_version": resolution_version,
            }
        now = datetime.now(timezone.utc).isoformat()
        assignments = ["updated_at = @updated_at"]
        context = None
        if "environment_id" in updates or "environment" in updates:
            captured = self.get_feedback(feedback_id)
            if captured:
                context = dict(captured.runContext)
                identity = updates.get("environment_id")
                if identity:
                    selected_environment = self.get_agent_environment(identity)
                    context.update(environment_id=identity, environment_label=selected_environment["name"], environment_kind=selected_environment["kind"])
                elif "environment_id" in updates or updates.get("environment") != captured.environment:
                    context.pop("environment_id", None)
                    context.pop("environment_label", None)
                    context.pop("environment_kind", None)
                if context != captured.runContext:
                    assignments += ["run_context_json = @environment_context", "revision = COALESCE(revision, 1) + 1", "latest_published_attempt_id = NULL", "public_status = 'In review'", "resolved_at = NULL"]
        else:
            context = None
        if any(key in updates for key in ("expected_behavior", "environment", "business_domain", "business_subdomain")):
            current_input = self.get_feedback(feedback_id)
            changed = current_input is not None and any(
                updates[key] != getattr(current_input, {"expected_behavior": "groundTruthHint", "environment": "environment", "business_domain": "businessDomain", "business_subdomain": "businessSubdomain"}[key])
                for key in ("expected_behavior", "environment", "business_domain", "business_subdomain") if key in updates
            )
            if changed:
                assignments.append("revision = COALESCE(revision, 1) + 1")
                assignments.extend(["latest_published_attempt_id = NULL", "public_status = 'In review'"])
        params = [bigquery.ScalarQueryParameter("updated_at", "TIMESTAMP", now)]
        if "run_context_json = @environment_context" in assignments:
            params.append(bigquery.ScalarQueryParameter("environment_context", "STRING", json.dumps(context)))
        assignments = list(dict.fromkeys(assignments))
        for key in (
            "state",
            "confirmed_rca",
            "subcategory",
            "reviewer_notes",
            "recommended_fix",
            "expected_behavior",
            "assigned_reviewer",
            "environment",
            "business_domain",
            "business_subdomain",
        ):
            if key in updates:
                column = "ground_truth_hint" if key == "expected_behavior" else key
                assignments.append(f"{column} = @{key}")
                value = updates[key]
                if key == "environment" and current_input is not None:
                    value = stored_environment_kind(current_input.agentName, value or 'unknown', (context if context is not None else current_input.runContext).get("environment_id"))
                if key == "state" and updates.get("confirmed_rca") and value == "Submitted":
                    value = "Triaged"
                params.append(bigquery.ScalarQueryParameter(key, "STRING", value))
        if "business_domain" in updates or "business_subdomain" in updates:
            domain_value = "@business_domain" if "business_domain" in updates else "business_domain"
            assignments.extend([f"domain_verified = COALESCE({domain_value}, 'Unspecified') != 'Unspecified'", "domain_source = 'reviewer_confirmed'", "domain_confidence = NULL", "domain_evidence_json = '[]'", "domain_reason = 'Business context recorded by the review team; an unknown domain still needs evidence.'"])
        for key in ("public_status", "public_message", "resolution_summary", "resolution_version"):
            if key in updates:
                assignments.append(f"{key} = @{key}")
                params.append(bigquery.ScalarQueryParameter(key, "STRING", updates[key]))
        if "public_status" in updates:
            if updates["public_status"] == "Resolved":
                assignments.append("resolved_at = COALESCE(resolved_at, @resolved_at)")
                params.append(bigquery.ScalarQueryParameter("resolved_at", "TIMESTAMP", now))
            else:
                assignments.append("resolved_at = NULL")
        for key in ("claims", "evidence"):
            if key in updates:
                column = f"{key}_json"
                parameter = f"{key}_json"
                assignments.append(f"{column} = @{parameter}")
                params.append(bigquery.ScalarQueryParameter(parameter, "STRING", json.dumps(updates[key], default=str)))
        if "expected_behavior_verified" in updates:
            assignments.append("expected_behavior_verified = @expected_behavior_verified")
            params.append(bigquery.ScalarQueryParameter(
                "expected_behavior_verified", "BOOL", updates["expected_behavior_verified"]
            ))
        if "confirmed_rca" in updates and updates["confirmed_rca"]:
            assignments.extend([
                "rca_review_required = FALSE",
                "rca_suggestion_status = 'reviewer_classified'",
            ])
            if "state" not in updates:
                assignments.append("state = IF(state = 'Submitted', 'Triaged', state)")
        elif "confirmed_rca" in updates:
            assignments.extend([
                "rca_review_required = TRUE",
                "rca_suggestion_status = 'review_required'",
            ])
        params.append(bigquery.ScalarQueryParameter("feedback_id", "STRING", feedback_id))
        self.client.query(
            f"UPDATE `{self.feedback_ref}` SET {', '.join(assignments)} WHERE feedback_id = @feedback_id",
            job_config=bigquery.QueryJobConfig(query_parameters=params),
            location=settings.location,
        ).result()
        read_cache.invalidate()
        self._insert_event(feedback_id, "triage_updated", actor, updates)
        if public_event_payload:
            self._insert_event(feedback_id, "public_status_updated", actor, public_event_payload)
        updated_record = self.get_feedback(feedback_id)
        if updates.get("confirmed_rca") and updated_record:
            self.ensure_original(updated_record)
            answer_id = f"original:{feedback_id}"
            self.save_version("feedback_rca_versions", f"reviewed:{uuid.uuid4().hex}", feedback_id, {
                "category": updates["confirmed_rca"], "defect": updates.get("subcategory", updated_record.defectSubCategory),
                "rationale": updates.get("public_message") or updated_record.publicMessage or "Classification reviewed by the team.",
                "verified": True, "answerId": answer_id, "environment": updated_record.environment,
                "revision": updated_record.revision, "createdAt": now,
            }, answer_id=answer_id)
        return updated_record

    def update_rca_suggestion(self, feedback_id: str, suggestion: dict[str, Any], expected_revision: int | None = None,
            *, source_answer_id: str | None = None, source_question: str | None = None, source_answer: str | None = None) -> FeedbackRecord | None:
        now = datetime.now(timezone.utc).isoformat()
        event_id = str(uuid.uuid4())
        triage_ready = expected_revision is not None and source_answer_id is not None and completed_rca(suggestion)
        params = [
            bigquery.ScalarQueryParameter("suggested_rca", "STRING", suggestion["suggested_rca"]),
            bigquery.ScalarQueryParameter("confidence", "FLOAT64", suggestion["suggested_rca_confidence"]),
            bigquery.ScalarQueryParameter("subcategory", "STRING", suggestion.get("rca_subcategory")),
            bigquery.ScalarQueryParameter("rationale", "STRING", suggestion["rca_rationale"]),
            *[
                bigquery.ScalarQueryParameter(name, "STRING", json.dumps(suggestion.get(source_key) or [], default=str))
                for name, source_key in (
                    ("evidence", "rca_evidence"),
                    ("required_claims", "rca_required_claims"),
                    ("supported_claims", "rca_supported_claims"),
                    ("missing_claims", "rca_missing_claims"),
                    ("contradicted_claims", "rca_contradicted_claims"),
                )
            ],
            bigquery.ScalarQueryParameter("review_required", "BOOL", suggestion["rca_review_required"]),
            bigquery.ScalarQueryParameter('triage_ready', 'BOOL', triage_ready),
            bigquery.ScalarQueryParameter('triage_message', 'STRING', RCA_TRIAGE_MESSAGE),
            bigquery.ScalarQueryParameter("suggestion_status", "STRING", suggestion["rca_suggestion_status"]),
            bigquery.ScalarQueryParameter("suggested_at", "TIMESTAMP", now),
            bigquery.ScalarQueryParameter("feedback_id", "STRING", feedback_id),
            bigquery.ScalarQueryParameter('event_id', 'STRING', event_id),
            bigquery.ScalarQueryParameter('triage_event_id', 'STRING', 'rca-triaged:' + event_id),
            bigquery.ScalarQueryParameter('event_type', 'STRING', 'rca_auto_classified' if suggestion.get('rca_auto_accepted') else 'rca_suggestion_created'),
            bigquery.ScalarQueryParameter('event_payload', 'STRING', json.dumps(suggestion, default=str)),
            bigquery.ScalarQueryParameter('triage_payload', 'STRING', json.dumps({'state':'Triaged','previous_state':'Submitted',
                'public_status':'In review','public_message':RCA_TRIAGE_MESSAGE,'revision':expected_revision,
                'answer_id':source_answer_id,'assessment_verified':False}, default=str)),
        ]
        conditions = ['feedback_id = @feedback_id']
        if expected_revision is not None:
            params.append(bigquery.ScalarQueryParameter("expected_revision", "INT64", expected_revision))
            conditions.append('COALESCE(revision, 1) = @expected_revision')
        if source_answer_id is not None:
            params.append(bigquery.ScalarQueryParameter('source_answer_id', 'STRING', source_answer_id))
            conditions.append(source_answer_id_sql() + ' = @source_answer_id')
        for key, value in [('question', source_question), ('answer', source_answer)]:
            if value is not None:
                params.append(bigquery.ScalarQueryParameter('source_' + key, 'STRING', value))
                conditions.append(f'COALESCE({key},\'\') = @source_{key}')
        where = ' AND '.join(conditions)
        guard = source_triage_guard()
        rows = list(self.client.query(
            f"""
            DECLARE applied INT64 DEFAULT 0;
            DECLARE advanced BOOL DEFAULT FALSE;
            BEGIN TRANSACTION;
            SET advanced = COALESCE((SELECT @triage_ready AND {guard} FROM `{self.feedback_ref}` WHERE {where} LIMIT 1), FALSE);
            UPDATE `{self.feedback_ref}` SET
              suggested_rca = @suggested_rca,
              suggested_rca_confidence = @confidence,
              rca_suggested_subcategory = @subcategory,
              rca_rationale = @rationale,
              rca_evidence_json = @evidence,
              rca_required_claims_json = @required_claims,
              rca_supported_claims_json = @supported_claims,
              rca_missing_claims_json = @missing_claims,
              rca_contradicted_claims_json = @contradicted_claims,
              rca_review_required = IF(rca_suggestion_status = 'reviewer_classified', rca_review_required, @review_required),
              state = IF(@triage_ready AND {guard}, 'Triaged', state),
              public_status = IF(@triage_ready AND {guard}, 'In review', public_status),
              public_message = IF(@triage_ready AND {guard}, COALESCE(public_message, @triage_message), public_message),
               rca_suggestion_status = IF(rca_suggestion_status = 'reviewer_classified', rca_suggestion_status, @suggestion_status),
              rca_suggested_at = @suggested_at,
              updated_at = @suggested_at
            WHERE {where};
            SET applied = @@row_count;
            IF applied = 1 THEN
                INSERT INTO `{self.events_ref}`(event_id,feedback_id,event_type,created_at,actor,payload_json)
                VALUES(@event_id,@feedback_id,@event_type,@suggested_at,NULL,@event_payload);
                IF advanced THEN
                    INSERT INTO `{self.events_ref}`(event_id,feedback_id,event_type,created_at,actor,payload_json)
                    VALUES(@triage_event_id,@feedback_id,'rca_auto_triaged',@suggested_at,'system:rca_triage',@triage_payload);
                END IF;
            END IF;
            COMMIT TRANSACTION;
            SELECT applied;
            """,
            job_config=bigquery.QueryJobConfig(query_parameters=params),
            location=settings.location, job_id='source_rca_' + event_id.replace('-', ''), job_retry=None,
        ).result(job_retry=None))
        if not rows:
            raise RuntimeError('Source RCA finalization did not return its guarded update result')
        if int(rows[0]['applied']) != 1:
            return None
        read_cache.invalidate()
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
        existing_rows = self.client.query(
            f"SELECT * FROM `{self.golden_cases_ref}` WHERE case_id = @case_id LIMIT 1",
            job_config=bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("case_id", "STRING", case_id)
            ]),
            location=settings.location,
        ).result()
        existing = next(iter(existing_rows), None)
        if not existing:
            return None
        existing_record = self._golden_case(dict(existing))
        feedback_id = existing_record.get("feedback_id")
        if state == "approved" and feedback_id:
            feedback = self.get_feedback(feedback_id)
            if not feedback or not feedback.expectedBehaviorVerified or not (feedback.groundTruthHint or "").strip():
                raise ValueError("This feedback candidate cannot be approved until expected behavior is reviewed and verified")
            if feedback.state not in {"Golden candidate", "Approved for dataset"}:
                raise ValueError("Feedback must complete review and be added to a dataset before approval")
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
                allow_dataset_lifecycle=True,
            )
        return record

    def add_golden_case(
        self,
        dataset_id: str,
        payload: GoldenCaseCreate,
        *,
        state: str = "candidate",
        reviewed_feedback: bool = False,
    ) -> dict[str, Any]:
        if payload.feedback_id and not reviewed_feedback:
            raise ValueError("Feedback-linked cases must pass the completed-review workflow")
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
        if feedback.state != "Review complete":
            raise ValueError("Complete the evidence review before adding feedback to a golden dataset")
        if not feedback.expectedBehaviorVerified or not (feedback.groundTruthHint or "").strip():
            raise ValueError("Reviewer-verified expected behavior is required before adding a golden case")
        reviewed_expected = (feedback.groundTruthHint or "").strip()
        if payload.expected_behavior.strip() != reviewed_expected:
            raise ValueError("Expected behavior changed; save it and complete the review again")
        dataset = self.get_golden_dataset(payload.dataset_id)
        if not dataset:
            raise KeyError("Golden dataset not found")
        duplicates = self.client.query(
            f"""
            SELECT COUNT(*) AS count
            FROM `{self.golden_cases_ref}`
            WHERE feedback_id = @feedback_id
              AND dataset_id = @dataset_id
              AND dataset_version = @dataset_version
              AND state != 'rejected'
            """,
            job_config=bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("feedback_id", "STRING", feedback_id),
                bigquery.ScalarQueryParameter("dataset_id", "STRING", payload.dataset_id),
                bigquery.ScalarQueryParameter("dataset_version", "STRING", dataset["current_version"]),
            ]),
            location=settings.location,
        ).result()
        if int(next(iter(duplicates)).count) > 0:
            raise ValueError("This feedback already has a candidate in the selected dataset version")

        evidence_refs = [*feedback.evidence, *feedback.suggestedRcaEvidence]
        case = self.add_golden_case(payload.dataset_id, GoldenCaseCreate(
            feedback_id=feedback_id,
            title=feedback.title,
            question=feedback.prompt,
            expected_behavior=reviewed_expected,
            required_claims=payload.required_claims,
            expected_status=payload.expected_status,
            evidence_refs=evidence_refs,
            curator=payload.curator,
        ), state="candidate", reviewed_feedback=True)
        self.update_triage(
            feedback_id,
            TriageUpdate(state="Golden candidate"),
            actor=payload.curator,
            allow_dataset_lifecycle=True,
        )
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
        legacy_sources = {"legacy_csv_import", "legacy_xlsx_import"}
        is_legacy = row.get("source") in legacy_sources or run_context.get("source") in legacy_sources
        import_tag = "legacy_xlsx_import" if row.get("source") == "legacy_xlsx_import" or run_context.get("source") == "legacy_xlsx_import" else "legacy_csv_import"
        if is_legacy and not run_context.get("reporter_edited_categories"):
            legacy_categories = [str(item) for item in issue_categories if str(item) not in legacy_sources]
            if legacy_categories and not run_context.get("developer_remarks"):
                run_context["developer_remarks"] = legacy_categories[0]
            issue_categories = [import_tag]
        internal_state = str(row.get("state") or "Submitted")
        public_status = row.get("public_status") or self._public_status_from_internal_state(internal_state)
        explicit_environment_id = run_context.get("environment_id")
        if not isinstance(explicit_environment_id, str) or not explicit_environment_id or len(explicit_environment_id) > 200:
            explicit_environment_id = None
        context_kind = run_context.get("environment_kind")
        kind = context_kind if explicit_environment_id and isinstance(context_kind, str) and context_kind in {"nonprod", "prod"} else row.get("environment") or "unknown"
        if kind not in {"nonprod", "prod", "unknown"}:
            kind = "unknown"
        environment_id = explicit_environment_id or legacy_environment_id(str(row.get("agent_id") or settings.default_agent_id), kind)
        environment_label = run_context.get("environment_label")
        if not isinstance(environment_label, str):
            environment_label = None
        explicit_business_context = row.get('domain_source') in USER_CLASSIFICATION_SOURCES
        business_domain = row.get('business_domain') or (None if explicit_business_context else domain_from_metadata(self._feedback_domain(run_context))) or 'Unspecified'
        business_subdomain = row.get('business_subdomain') or (None if explicit_business_context else run_context.get('sub_domain'))
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
            state=internal_state,
            domain=str(business_domain),
            businessDomain=str(business_domain),
            businessSubdomain=business_subdomain,
            domainSource=str(row.get("domain_source") or ("legacy_submitted" if run_context.get("sub_domain") else "unspecified")),
            domainConfidence=row.get("domain_confidence"),
            domainReason=row.get("domain_reason"),
            domainVerified=bool(row.get("domain_verified")),
            domainEvidence=self._json_list(row.get("domain_evidence_json")),
            environment=kind,
            environmentId=environment_id,
            environmentLabel=(environment_label[:60] if environment_label else None) or ({"nonprod": "Non-production", "prod": "Production"}.get(kind) if environment_id else None),
            mainEnvironmentId=row.get("main_environment_id"),
            mainEnvironmentKind=row.get("main_environment_kind"),
            mainEnvironmentLabel=row.get("main_environment_label"),
            agentVersion=row.get("agent_version"),
            revision=int(row.get("revision") or 1),
            latestPublishedAttemptId=row.get("latest_published_attempt_id"),
            reporter=row.get("reporter"),
            reportedTime=str(row.get("created_at") or ""),
            updatedAt=str(row.get("updated_at") or "") or None,
            publicStatus=public_status,
            publicMessage=row.get("public_message"),
            resolutionSummary=row.get("resolution_summary"),
            resolutionVersion=row.get("resolution_version"),
            resolvedAt=str(row.get("resolved_at") or "") or None,
            assignedReviewer=row.get("assigned_reviewer"),
            groundTruthHint=row.get("ground_truth_hint"),
            expectedBehaviorVerified=bool(row.get("expected_behavior_verified")),
            impact=str(row.get("impact") or "Medium"),
            tags=[str(item) for item in self._json_list(row.get("tags_json")) if str(item) in legacy_sources] if is_legacy and not run_context.get("reporter_edited_categories") else self._json_list(row.get("tags_json")),
            correlatedReports=self._json_list(row.get("correlated_reports_json")),
            claims=self._json_list(row.get("claims_json")),
            evidence=self._json_list(row.get("evidence_json")),
            reviewerNotes=row.get("reviewer_notes"),
            recommendedFix=row.get("recommended_fix"),
            runContext=run_context,
            suggestedRcaRationale=row.get("rca_rationale"),
            suggestedRcaSubcategory=row.get("rca_suggested_subcategory"),
            suggestedRcaEvidence=self._json_list(row.get("rca_evidence_json")),
            suggestedRcaRequiredClaims=self._json_list(row.get("rca_required_claims_json")),
            suggestedRcaSupportedClaims=self._json_list(row.get("rca_supported_claims_json")),
            suggestedRcaMissingClaims=self._json_list(row.get("rca_missing_claims_json")),
            suggestedRcaContradictedClaims=self._json_list(row.get("rca_contradicted_claims_json")),
            suggestedRcaReviewRequired=row.get("rca_review_required"),
            suggestedRcaStatus=row.get("rca_suggestion_status"),
        )

    @staticmethod
    def _feedback_domain(run_context: dict[str, Any]) -> str:
        for key in ("domain", "sub_domain"):
            value = run_context.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return "Unspecified"

    @staticmethod
    def _public_status_from_internal_state(state: str) -> str:
        return {
            "Submitted": "Received",
            "Needs more information": "Needs information",
            "Rejected": "Not planned",
            "Duplicate": "Duplicate",
        }.get(state, "In review")

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
