"""Durable jobs, immutable answer/diagnosis records and scoped notifications."""
from __future__ import annotations

from .feedback_ownership import owner_scope

import hashlib
import json
import time
import uuid
from datetime import datetime, timezone

from google.cloud import bigquery
from google.api_core.exceptions import Aborted, Conflict, ServiceUnavailable

from .cache import read_cache
from .agent_errors import safe_workflow_error
from .config import settings
from .models import AnswerConfirmation, FeedbackRecord
from .agent_targets import legacy_environment_id, stored_environment_kind


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def scalar(name: str, value, kind: str = "STRING"):
    return bigquery.ScalarQueryParameter(name, kind, value)


class WorkflowRepositoryMixin:
    def workflow_table(self, name: str) -> str:
        return f"{self.dataset_ref}.{name}"

    def workflow_query(self, sql: str, parameters: list | None = None) -> list[dict]:
        return [dict(row) for row in self.client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=parameters or []), location=settings.location).result()]

    def ensure_workflow_schema(self) -> None:
        schemas = {
            "feedback_answer_versions": [
                ("id", "STRING"), ("feedback_id", "STRING"), ("attempt_id", "STRING"),
                ("created_at", "TIMESTAMP"), ("payload_json", "STRING"),
            ],
            "feedback_rca_versions": [
                ("id", "STRING"), ("feedback_id", "STRING"), ("attempt_id", "STRING"),
                ("answer_id", "STRING"), ("created_at", "TIMESTAMP"), ("payload_json", "STRING"),
            ],
            "feedback_workflow_jobs": [
                ("id", "STRING"), ("feedback_id", "STRING"), ("kind", "STRING"), ("status", "STRING"),
                ("created_at", "TIMESTAMP"), ("updated_at", "TIMESTAMP"), ("lease_until", "TIMESTAMP"),
                ("lease_token", "STRING"), ("attempts", "INT64"), ("revision", "INT64"),
                ("target_id", "STRING"), ("environment", "STRING"), ("requested_by", "STRING"),
                ("payload_json", "STRING"), ("result_json", "STRING"), ("error", "STRING"),
                ("published_at", "TIMESTAMP"), ("published_by", "STRING"), ("public_summary", "STRING"),
                ("confirmation", "STRING"),
            ],
            "feedback_notifications": [
                ("id", "STRING"), ("feedback_id", "STRING"), ("attempt_id", "STRING"), ("recipient", "STRING"),
                ("created_at", "TIMESTAMP"), ("message", "STRING"), ("read_at", "TIMESTAMP"),
            ],
        }
        for name, fields in schemas.items():
            self.client.create_table(bigquery.Table(self.workflow_table(name), schema=[bigquery.SchemaField(key, kind) for key, kind in fields]), exists_ok=True)
        # Preserve legacy originals once, without guessing their environment.
        self.workflow_query(f"""
            MERGE `{self.workflow_table('feedback_answer_versions')}` t
            USING (SELECT CONCAT('original:', feedback_id) AS id, feedback_id, created_at,
                TO_JSON_STRING(STRUCT(question AS question, answer AS answer, agent_id AS agentId,
                COALESCE(NULLIF(environment, ''), 'unknown') AS environment, agent_version AS agentVersion,
                run_id AS runId, 'original' AS kind, created_at AS createdAt, 1 AS revision)) AS payload_json
                FROM `{self.feedback_ref}`) s ON t.id = s.id
            WHEN NOT MATCHED THEN INSERT (id, feedback_id, attempt_id, created_at, payload_json)
            VALUES(s.id, s.feedback_id, NULL, s.created_at, s.payload_json)
        """)
        self.workflow_query(f"""
            MERGE `{self.workflow_table('feedback_rca_versions')}` t
            USING (SELECT CONCAT('imported-rca:', feedback_id) AS id, feedback_id,
                COALESCE(rca_suggested_at, updated_at, created_at) AS created_at,
                TO_JSON_STRING(STRUCT(
                    IF(rca_suggestion_status = 'reviewer_classified', COALESCE(confirmed_rca, suggested_rca), COALESCE(suggested_rca, confirmed_rca)) AS category,
                    IF(rca_suggestion_status = 'reviewer_classified', subcategory, rca_suggested_subcategory) AS defect,
                    IF(rca_suggestion_status = 'reviewer_classified', COALESCE(public_message, 'Classification reviewed by the team.'), COALESCE(rca_rationale, 'Imported diagnosis; evidence review is still required.')) AS rationale,
                    suggested_rca_confidence AS confidence, COALESCE(rca_suggestion_status = 'reviewer_classified', FALSE) AS verified,
                    CONCAT('original:', feedback_id) AS answerId, COALESCE(NULLIF(environment, ''), 'unknown') AS environment,
                    COALESCE(rca_suggested_at, updated_at, created_at) AS createdAt, 'imported_latest_diagnosis' AS origin
                )) AS payload_json FROM `{self.feedback_ref}`
                WHERE suggested_rca IS NOT NULL OR confirmed_rca IS NOT NULL) s ON t.id = s.id
            WHEN NOT MATCHED THEN INSERT (id, feedback_id, attempt_id, answer_id, created_at, payload_json)
            VALUES(s.id, s.feedback_id, NULL, CONCAT('original:', s.feedback_id), s.created_at, s.payload_json)
        """)

    def save_version(self, table_name: str, version_id: str, feedback_id: str, payload: dict, attempt_id: str | None = None, answer_id: str | None = None) -> None:
        columns = ["id", "feedback_id", "attempt_id", "created_at", "payload_json"]
        parameters = [scalar("id", version_id), scalar("feedback_id", feedback_id), scalar("attempt_id", attempt_id),
                      scalar("created_at", now_iso(), "TIMESTAMP"), scalar("payload_json", json.dumps(payload, default=str))]
        if table_name == "feedback_rca_versions":
            columns.append("answer_id")
            parameters.append(scalar("answer_id", answer_id))
        if table_name not in {"feedback_answer_versions", "feedback_rca_versions"}:
            raise ValueError("Invalid workflow version table")
        self.workflow_query(f"""MERGE `{self.workflow_table(table_name)}` t USING (SELECT @id AS id) s ON t.id = s.id
            WHEN NOT MATCHED THEN INSERT ({', '.join(columns)}) VALUES ({', '.join('@' + key for key in columns)})""", parameters)
        read_cache.invalidate()

    def ensure_original(self, record: FeedbackRecord) -> None:
        self.save_version("feedback_answer_versions", f"original:{record.id}", record.id, {
            "kind": "original", "question": record.prompt, "answer": record.generatedAnswer,
            "environment": record.environment, "environmentId": record.environmentId, "environmentLabel": record.environmentLabel, "agentId": record.agentName, "agentVersion": record.agentVersion,
            "runId": record.runId, "createdAt": record.reportedTime, "revision": record.revision,
            "userVerdict": record.userVerdict,
        })

    def get_version(self, table_name: str, version_id: str) -> dict | None:
        if table_name not in {"feedback_answer_versions", "feedback_rca_versions"}:
            raise ValueError("Invalid workflow version table")
        rows = self.workflow_query(f"SELECT id, payload_json FROM `{self.workflow_table(table_name)}` WHERE id = @id LIMIT 1", [scalar("id", version_id)])
        return {"id": rows[0]["id"], **self._json_object(rows[0]["payload_json"])} if rows else None

    def enqueue_feedback_job(self, record: FeedbackRecord, kind: str, actor: str, target_id: str | None = None, environment: str | None = None, idempotency_key: str | None = None, target_snapshot: dict | None = None) -> dict:
        if kind not in {"enrich", "rca", "retest"}:
            raise ValueError("Invalid feedback job type")
        self.ensure_original(record)
        digest = hashlib.sha256(f"{record.id}:{record.revision}:{kind}:{actor}:{target_id}:{idempotency_key or kind}".encode()).hexdigest()[:32]
        job_id = f"JOB-{digest}"
        stamp = now_iso()
        job_environment = environment or record.environment
        if kind == "retest" and target_snapshot and target_snapshot.get("target"):
            frozen = target_snapshot["target"]
            job_environment = stored_environment_kind(frozen["agent_id"], frozen["environment"], frozen["id"])
        self.workflow_query(f"""
            MERGE `{self.workflow_table('feedback_workflow_jobs')}` t USING (SELECT @id AS id) s ON t.id = s.id
            WHEN NOT MATCHED THEN INSERT (id, feedback_id, kind, status, created_at, updated_at, attempts, revision,
                target_id, environment, requested_by, payload_json, target_snapshot_json, phase)
            VALUES (@id, @feedback_id, @kind, 'queued', @now, @now, 0, @revision, @target_id, @environment, @actor, @payload, @snapshot, 'queued')
        """, [scalar("id", job_id), scalar("feedback_id", record.id), scalar("kind", kind), scalar("now", stamp, "TIMESTAMP"),
               scalar("revision", record.revision, "INT64"), scalar("target_id", target_id), scalar("environment", job_environment),
               scalar("actor", actor), scalar("payload", json.dumps(record.model_dump(), default=str)), scalar("snapshot", json.dumps(target_snapshot) if target_snapshot else None)])
        read_cache.invalidate()
        return self.get_feedback_job(job_id) or {"id": job_id, "feedback_id": record.id, "kind": kind, "status": "queued"}

    def get_feedback_job(self, job_id: str) -> dict | None:
        rows = self.workflow_query(f"SELECT * FROM `{self.workflow_table('feedback_workflow_jobs')}` WHERE id = @id LIMIT 1", [scalar("id", job_id)])
        return rows[0] if rows else None

    def claim_feedback_job(self) -> dict | None:
        rows = self.workflow_query(f"""UPDATE `{self.workflow_table('feedback_workflow_jobs')}` j SET status='failed',phase='failed',
            error='The agent call outcome is unknown after an interruption. No automatic generation replay was made.',updated_at=CURRENT_TIMESTAMP()
            WHERE status='running' AND lease_until<CURRENT_TIMESTAMP() AND generation_started_at IS NOT NULL
                AND NOT {self._saved_retest_answer('j')};
            UPDATE `{self.workflow_table('feedback_workflow_jobs')}` SET status = 'failed',
            error = 'Worker restart retry limit reached', updated_at = CURRENT_TIMESTAMP()
            WHERE status = 'running' AND lease_until < CURRENT_TIMESTAMP() AND attempts >= 3;
            SELECT id FROM `{self.workflow_table('feedback_workflow_jobs')}`
            WHERE (status = 'queued' OR (status = 'running' AND lease_until < CURRENT_TIMESTAMP())) AND attempts < 3
            ORDER BY created_at LIMIT 1""")
        if not rows:
            return None
        job_id, token = rows[0]["id"], uuid.uuid4().hex
        job = self.client.query(f"""UPDATE `{self.workflow_table('feedback_workflow_jobs')}`
            SET status = 'running', updated_at = CURRENT_TIMESTAMP(), attempts = attempts + 1,
                lease_token = @token, lease_until = TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL 10 MINUTE)
            WHERE id = @id AND attempts < 3 AND
                (status = 'queued' OR (status = 'running' AND lease_until < CURRENT_TIMESTAMP()))""",
            job_config=bigquery.QueryJobConfig(query_parameters=[scalar("id", job_id), scalar("token", token)]), location=settings.location)
        job.result()
        if int(job.num_dml_affected_rows or 0) != 1:
            return None
        return self.get_feedback_job(job_id)

    def renew_feedback_lease(self, job_id: str, token: str) -> None:
        self.workflow_query(f"""UPDATE `{self.workflow_table('feedback_workflow_jobs')}`
            SET lease_until = TIMESTAMP_ADD(CURRENT_TIMESTAMP(), INTERVAL 10 MINUTE)
             WHERE id = @id AND status = 'running' AND lease_token = @token""", [scalar("id", job_id), scalar("token", token)])

    def mark_generation_started(self, job: dict) -> bool:
        rows = self.workflow_query(f"""UPDATE `{self.workflow_table('feedback_workflow_jobs')}`
            SET generation_started_at=CURRENT_TIMESTAMP(),phase='generating',updated_at=CURRENT_TIMESTAMP()
            WHERE id=@id AND status='running' AND lease_token=@token AND generation_started_at IS NULL;
            SELECT @@row_count AS claimed;""", [scalar("id", job["id"]), scalar("token", job.get("lease_token"))])
        return bool(rows and rows[0]["claimed"] == 1)

    def set_feedback_job_phase(self, job: dict, phase: str) -> None:
        self.workflow_query(f"""UPDATE `{self.workflow_table('feedback_workflow_jobs')}` SET phase=@phase,updated_at=CURRENT_TIMESTAMP()
            WHERE id=@id AND status='running' AND lease_token=@token""",
            [scalar("phase", phase), scalar("id", job["id"]), scalar("token", job.get("lease_token"))])

    @staticmethod
    def _environment_parameters() -> list:
        return [scalar("legacy_nonprod", legacy_environment_id(settings.default_agent_id, "nonprod")),
                scalar("legacy_prod", legacy_environment_id(settings.default_agent_id, "prod")), scalar("legacy_agent", settings.default_agent_id)]

    @staticmethod
    def _source_environment_kind(alias: str = "") -> str:
        prefix = alias + "." if alias else ""
        return f"COALESCE(IF(JSON_VALUE({prefix}run_context_json,'$.environment_id') IS NOT NULL AND JSON_VALUE({prefix}run_context_json,'$.environment_kind') IN ('nonprod','prod'),JSON_VALUE({prefix}run_context_json,'$.environment_kind'),NULL),{prefix}environment)"

    @staticmethod
    def _current_environment_kind(alias: str) -> str:
        return f"COALESCE(NULLIF({alias}.main_environment_kind,''),{WorkflowRepositoryMixin._source_environment_kind(alias)})"

    def _current_environment_id(self, alias: str) -> str:
        current_kind = self._current_environment_kind(alias)
        return f"COALESCE(NULLIF({alias}.main_environment_id,''),JSON_VALUE({alias}.run_context_json,'$.environment_id')," \
            f"IF({alias}.agent_id=@legacy_agent,CASE {current_kind} WHEN 'nonprod' THEN @legacy_nonprod WHEN 'prod' THEN @legacy_prod END,NULL))"

    @staticmethod
    def _job_environment_kind(alias: str) -> str:
        return f"COALESCE(JSON_VALUE({alias}.target_snapshot_json,'$.target.environment'),{alias}.environment)"

    def _same_environment(self, feedback: str, job: str) -> str:
        source_kind, target_kind = self._current_environment_kind(feedback), self._job_environment_kind(job)
        source = self._current_environment_id(feedback)
        target = f"COALESCE({job}.target_id,CASE {target_kind} WHEN 'nonprod' THEN @legacy_nonprod WHEN 'prod' THEN @legacy_prod END)"
        return f"({source_kind}={target_kind} AND {source} IS NOT NULL AND {source}={target})"

    def complete_feedback_job(self, job: dict, result: dict | None = None, error: str | None = None) -> None:
        if job.get("kind") == "retest" and error is None:
            self.auto_share_retest_result(job["id"], result or {}, job["lease_token"])
            return
        self.workflow_query(f"""UPDATE `{self.workflow_table('feedback_workflow_jobs')}` SET status = @status,
            result_json = @result, error = @error, phase = @status, updated_at = CURRENT_TIMESTAMP(), lease_until = NULL
            WHERE id = @id AND status = 'running' AND lease_token = @token""",
            [scalar("id", job["id"]), scalar("token", job["lease_token"]), scalar("status", "failed" if error else "completed"),
             scalar("result", json.dumps(result or {}, default=str)), scalar("error", error)])
        read_cache.invalidate()

    def _saved_retest_answer(self, alias: str) -> str:
        # Aliases are internal constants, never browser input.
        return f"""EXISTS (SELECT 1 FROM `{self.workflow_table('feedback_answer_versions')}` av
            WHERE av.feedback_id = {alias}.feedback_id AND av.attempt_id = {alias}.id
                AND av.id = CONCAT('answer:', {alias}.id)
                AND NULLIF(TRIM(JSON_VALUE(av.payload_json,'$.answer')),'') IS NOT NULL)"""

    def feedback_answer_reviews(self, feedback_ids: list[str], reporter: str | list[str]) -> dict:
        """One bounded, owner-scoped query for a page of review summaries, not full histories."""
        if not feedback_ids:
            return {}
        from .answer_review import review_summary
        scope, reporter_parameter = self._reporter_filter(reporter)
        rows = self.workflow_query(f"""WITH context AS (
            SELECT f.feedback_id,f.agent_id,f.run_context_json,f.environment,COALESCE(f.revision,1) AS revision,
                m.environment_id AS main_environment_id,m.environment_kind AS main_environment_kind,
                COALESCE(m.environment_label,JSON_VALUE(f.run_context_json,'$.environment_label')) AS environment_label
            FROM `{self.feedback_ref}` f LEFT JOIN `{self.workflow_table('feedback_main_environments')}` m
                ON m.feedback_id=f.feedback_id AND m.agent_id=f.agent_id
            WHERE f.feedback_id IN UNNEST(@ids) AND {scope}
        ), facts AS (
            SELECT j.feedback_id,j.id,j.status,j.revision,j.confirmation,j.created_at,
                j.target_id AS environmentId,{self._job_environment_kind('j')} AS environmentKind,
                j.revision=c.revision AS current_input,{self._same_environment('c','j')} AS current_environment,
                {self._saved_retest_answer('j')} AS saved_answer
            FROM context c JOIN `{self.workflow_table('feedback_workflow_jobs')}` j ON j.feedback_id=c.feedback_id
            WHERE j.kind='retest'
        ), completed AS (
            SELECT * FROM facts WHERE status='completed' AND current_input AND current_environment AND saved_answer
            QUALIFY ROW_NUMBER() OVER(PARTITION BY feedback_id ORDER BY COALESCE(created_at,TIMESTAMP '1970-01-01') DESC,id DESC)=1
        ), latest AS (
            SELECT * FROM facts QUALIFY ROW_NUMBER() OVER(PARTITION BY feedback_id
                ORDER BY COALESCE(created_at,TIMESTAMP '1970-01-01') DESC,id DESC)=1
        )
        SELECT c.feedback_id,c.revision,{self._current_environment_id('c')} AS environment_id,
            {self._current_environment_kind('c')} AS environment_kind,c.environment_label,
            TO_JSON_STRING(done) AS completed_json,TO_JSON_STRING(latest) AS latest_json
        FROM context c LEFT JOIN completed done ON done.feedback_id=c.feedback_id
            LEFT JOIN latest ON latest.feedback_id=c.feedback_id""",
            [bigquery.ArrayQueryParameter('ids','STRING',feedback_ids),reporter_parameter,*self._environment_parameters()])
        return {row['feedback_id']: review_summary({'revision':row.get('revision'),
            'environmentId':row.get('environment_id'),'environmentKind':row.get('environment_kind'),
            'environmentLabel':row.get('environment_label')},self._json_object(row.get('completed_json')),
            self._json_object(row.get('latest_json'))) for row in rows}

    def auto_share_retest_result(self, attempt_id: str, result: dict | None = None, lease_token: str | None = None) -> None:
        """Finalize a claimed result, or reconcile an older completed result.

        Visibility is automatic even before this transaction: this transaction
        durably records availability, creates one notification and advances only
        a matching current-input/environment pointer. It never resolves feedback,
        changes its public review status, or overwrites a submitted answer.
        """
        jobs = self.workflow_table("feedback_workflow_jobs")
        parameters = [scalar("attempt", attempt_id), *self._environment_parameters()]
        if lease_token is not None:
            assignments = "status = 'completed', result_json = @result, phase = 'completed', error = NULL, lease_until = NULL,"
            condition = "j.status = 'running' AND j.lease_token = @token"
            parameters.extend([scalar("result", json.dumps(result or {}, default=str)), scalar("token", lease_token)])
        else:
            assignments = ""
            condition = "j.status IN ('completed', 'failed') AND j.published_at IS NULL"
        main_table = self.workflow_table('feedback_main_environments')
        sql = f"""CREATE TEMP TABLE main_scope AS
            SELECT f.feedback_id,f.agent_id,COALESCE(f.revision,1) AS revision,f.run_context_json,f.environment,
                m.environment_id AS main_environment_id,m.environment_kind AS main_environment_kind,
                m.revision AS main_environment_revision
            FROM `{self.feedback_ref}` f
            JOIN `{jobs}` selected_job ON selected_job.feedback_id=f.feedback_id AND selected_job.id=@attempt
            LEFT JOIN `{main_table}` m ON m.feedback_id=f.feedback_id AND m.agent_id=f.agent_id;
            BEGIN TRANSACTION;
            ASSERT (SELECT COUNT(*) FROM main_scope)=1 AS 'AUTO_SHARE_FEEDBACK_MISSING';
            ASSERT NOT EXISTS(SELECT 1 FROM main_scope s LEFT JOIN `{main_table}` m
                ON m.feedback_id=s.feedback_id AND m.agent_id=s.agent_id
                WHERE m.revision IS DISTINCT FROM s.main_environment_revision
                    OR m.environment_id IS DISTINCT FROM s.main_environment_id
                    OR m.environment_kind IS DISTINCT FROM s.main_environment_kind) AS 'MAIN_ENVIRONMENT_CHANGED';
            UPDATE `{jobs}` j SET {assignments}
                published_at = COALESCE(published_at, CURRENT_TIMESTAMP()),
                published_by = COALESCE(published_by, 'system:auto_share'), updated_at = CURRENT_TIMESTAMP()
                WHERE j.id = @attempt AND j.kind = 'retest' AND {condition} AND {self._saved_retest_answer('j')};
            IF @@row_count = 1 THEN
                MERGE `{self.workflow_table('feedback_notifications')}` n USING (
                    SELECT j.id, j.feedback_id, f.reporter AS recipient, COALESCE(JSON_VALUE(j.target_snapshot_json,'$.environmentName'),j.environment) AS environment
                    FROM `{jobs}` j JOIN `{self.feedback_ref}` f ON f.feedback_id = j.feedback_id
                    WHERE j.id = @attempt AND NULLIF(TRIM(f.reporter), '') IS NOT NULL
                ) s ON n.id = s.id
                WHEN NOT MATCHED THEN INSERT (id, feedback_id, attempt_id, recipient, created_at, message)
                    VALUES(s.id, s.feedback_id, s.id, s.recipient, CURRENT_TIMESTAMP(),
                        CONCAT('A new ', s.environment, ' answer is available with its automated assessment or check status. AI analysis is unverified.'));
                UPDATE `{self.feedback_ref}` f SET latest_published_attempt_id = @attempt, updated_at = CURRENT_TIMESTAMP()
                    FROM `{jobs}` j JOIN main_scope s ON s.feedback_id=j.feedback_id
                    WHERE j.id = @attempt AND j.status = 'completed' AND f.feedback_id = j.feedback_id AND f.feedback_id=s.feedback_id
                        AND f.agent_id=s.agent_id AND COALESCE(f.revision,1)=j.revision AND s.revision=j.revision
                        AND {self._same_environment('s', 'j')}
                        AND {self._current_environment_kind('s')} IN ('nonprod', 'prod') AND NULLIF(TRIM(f.reporter), '') IS NOT NULL
                        AND NOT EXISTS (SELECT 1 FROM `{jobs}` newer
                            WHERE newer.feedback_id = s.feedback_id AND newer.kind = 'retest' AND newer.status = 'completed'
                                AND newer.revision = s.revision AND {self._same_environment('s', 'newer')}
                                AND (COALESCE(newer.created_at, TIMESTAMP '1970-01-01') > COALESCE(j.created_at, TIMESTAMP '1970-01-01')
                                    OR (COALESCE(newer.created_at, TIMESTAMP '1970-01-01') = COALESCE(j.created_at, TIMESTAMP '1970-01-01') AND newer.id > j.id))
                                AND {self._saved_retest_answer('newer')});
                MERGE `{self.events_ref}` e USING (
                    SELECT CONCAT('auto-result:', j.id) AS event_id, j.feedback_id,
                        TO_JSON_STRING(STRUCT(j.id AS attempt_id, j.environment AS environment,
                            j.revision AS revision, 'automatic' AS sharing_policy)) AS payload
                    FROM `{jobs}` j WHERE j.id = @attempt
                ) s ON e.event_id = s.event_id
                WHEN NOT MATCHED THEN INSERT (event_id, feedback_id, event_type, created_at, actor, payload_json)
                    VALUES(s.event_id, s.feedback_id, 'retest_result_available', CURRENT_TIMESTAMP(), 'system:auto_share', s.payload);
            END IF;
            COMMIT TRANSACTION;"""
        for retry in range(3):
            try:
                self.workflow_query(sql, parameters)
                break
            except (Aborted, Conflict, ServiceUnavailable):
                if retry == 2:
                    raise
                # Retry only the conditional, idempotent storage transaction.
                # Never replay a generation request to recover notification DML.
                time.sleep(0.2 * (2 ** retry))
        read_cache.invalidate()

    def reconcile_auto_shared_retest(self) -> bool:
        """Recover notifications/metadata after a crash, without invoking an agent."""
        rows = self.workflow_query(f"""SELECT j.id FROM `{self.workflow_table('feedback_workflow_jobs')}` j
            WHERE j.kind = 'retest' AND j.status IN ('completed', 'failed') AND j.published_at IS NULL
                AND {self._saved_retest_answer('j')}
            ORDER BY j.created_at, j.id LIMIT 1""")
        if not rows:
            return False
        self.auto_share_retest_result(rows[0]["id"])
        return True

    def latest_confirmable_retest(self, feedback_id: str, revision: int, environment: str) -> str | None:
        if environment not in {"nonprod", "prod"}:
            return None
        rows = self.workflow_query(f"""WITH scoped_feedback AS (
            SELECT f.feedback_id,f.agent_id,f.run_context_json,f.environment,
                m.environment_id AS main_environment_id,m.environment_kind AS main_environment_kind
            FROM `{self.feedback_ref}` f LEFT JOIN `{self.workflow_table('feedback_main_environments')}` m
                ON m.feedback_id=f.feedback_id AND m.agent_id=f.agent_id WHERE f.feedback_id=@id
        )
            SELECT j.id FROM `{self.workflow_table('feedback_workflow_jobs')}` j JOIN scoped_feedback f ON f.feedback_id=j.feedback_id
            WHERE j.feedback_id = @id AND j.kind = 'retest' AND j.status = 'completed'
                AND j.revision = @revision AND {self._job_environment_kind('j')} = @environment AND {self._same_environment('f','j')} AND {self._saved_retest_answer('j')}
            ORDER BY COALESCE(j.created_at, TIMESTAMP '1970-01-01') DESC, j.id DESC LIMIT 1""",
            [scalar("id", feedback_id), scalar("revision", revision, "INT64"), scalar("environment", environment), *self._environment_parameters()])
        return rows[0]["id"] if rows else None

    def save_domain_suggestion(self, feedback_id: str, revision: int, suggestion: dict) -> None:
        self.workflow_query(f"""UPDATE `{self.feedback_ref}` SET business_domain = @domain, business_subdomain = @subdomain,
            domain_source = @source, domain_confidence = @confidence, domain_reason = @reason,
            domain_evidence_json = @evidence, domain_verified = FALSE, updated_at = CURRENT_TIMESTAMP()
            WHERE feedback_id = @id AND COALESCE(revision, 1) = @revision AND NOT COALESCE(domain_verified, FALSE)
                AND COALESCE(domain_source, '') NOT IN ('workbook_import','user_submitted','user_confirmed','reviewer_confirmed','submitted','legacy_submitted')""",
            [scalar("id", feedback_id), scalar("revision", revision, "INT64"), scalar("domain", suggestion["domain"]),
             scalar("subdomain", suggestion.get("subdomain")), scalar("source", suggestion["source"]),
             scalar("confidence", suggestion.get("confidence"), "FLOAT64"), scalar("reason", suggestion["reason"]),
             scalar("evidence", json.dumps(suggestion.get("evidence") or []))])
        read_cache.invalidate()

    @staticmethod
    def safe_job(job: dict) -> dict:
        from .answer_review import user_verdict
        result = BigQueryJson.object(job.get("result_json"))
        snapshot = BigQueryJson.object(job.get("target_snapshot_json"))
        target = snapshot.get("target") or {}
        return {"id": job["id"], "kind": job.get("kind"), "status": job.get("status"),
                "environment": target.get("environment") or job.get("environment") or "unknown", "environmentId": job.get("target_id"),
                "environmentLabel": snapshot.get("environmentName"), "batchId": job.get("batch_id"),
                "configurationRevision": target.get("configuration_version") or snapshot.get("configurationRevision"),
                "phase": job.get("status") if job.get("status") in {"completed", "failed", "cancelled"} else job.get("phase") or job.get("status"), "revision": job.get("revision", 1),
                "createdAt": str(job.get("created_at") or ""), "updatedAt": str(job.get("updated_at") or ""),
                "sharedAt": str(job.get("published_at") or "") or None, "summary": job.get("public_summary"),
                "confirmation": job.get("confirmation"), "userVerdict": user_verdict(job.get('confirmation')), "assessment": result.get("assessment"),
                "reason": result.get("reason"), "reviewRequired": True, "assessmentVerified": False,
                "automaticallyShared": job.get("kind") == "retest",
                "error": safe_workflow_error(job.get("error")) if job.get("status") == "failed" else None}

    def feedback_history(self, feedback_id: str, reporters: list[str] | None = None) -> dict:
        parameters = [scalar("id", feedback_id), *self._environment_parameters()]
        scope = "TRUE"
        if reporters is not None:
            scope = owner_scope(self, 'f')
            parameters.append(bigquery.ArrayQueryParameter("reporters", "STRING", [value.strip().lower() for value in reporters]))
        result = self.workflow_query(f"""WITH allowed AS (
            SELECT f.feedback_id, COALESCE(f.revision, 1) AS revision,
                COALESCE({self._source_environment_kind('f')}, 'unknown') AS environment, f.agent_id, f.run_context_json,
                f.user_verdict AS submitted_user_verdict,
                m.environment_id AS main_environment_id,m.environment_kind AS main_environment_kind,
                COALESCE(m.environment_label,JSON_VALUE(f.run_context_json,'$.environment_label')) AS environment_label
                FROM `{self.feedback_ref}` f LEFT JOIN `{self.workflow_table('feedback_main_environments')}` m
                    ON m.feedback_id=f.feedback_id AND m.agent_id=f.agent_id WHERE f.feedback_id = @id AND {scope}),
            confirmable_job AS (
                SELECT j.id FROM `{self.workflow_table('feedback_workflow_jobs')}` j JOIN allowed a ON j.feedback_id=a.feedback_id
                WHERE j.kind = 'retest' AND j.status = 'completed' AND j.revision = a.revision
                    AND {self._same_environment('a','j')} AND {self._current_environment_kind('a')} IN ('nonprod','prod') AND {self._saved_retest_answer('j')}
                ORDER BY COALESCE(j.created_at, TIMESTAMP '1970-01-01') DESC, j.id DESC LIMIT 1),
            recent_answers AS (
                SELECT v.* FROM `{self.workflow_table('feedback_answer_versions')}` v JOIN allowed a ON v.feedback_id = a.feedback_id
                ORDER BY IF(JSON_VALUE(v.payload_json, '$.kind') = 'original', 0, 1), v.created_at DESC, v.id DESC LIMIT 100),
            selected_answers AS (
                SELECT v.* FROM `{self.workflow_table('feedback_answer_versions')}` v JOIN allowed a ON v.feedback_id=a.feedback_id
                WHERE v.id IN (SELECT id FROM recent_answers) OR v.attempt_id IN (SELECT id FROM confirmable_job)),
            selected_diagnoses AS (
                SELECT v.* FROM `{self.workflow_table('feedback_rca_versions')}` v JOIN allowed a ON v.feedback_id = a.feedback_id
                ORDER BY v.created_at DESC, v.id DESC LIMIT 100),
            recent_jobs AS (
                SELECT j.id FROM `{self.workflow_table('feedback_workflow_jobs')}` j JOIN allowed a ON j.feedback_id = a.feedback_id
                ORDER BY j.created_at DESC, j.id DESC LIMIT 100),
            visible_jobs AS (
                SELECT j.* FROM `{self.workflow_table('feedback_workflow_jobs')}` j JOIN allowed a ON j.feedback_id = a.feedback_id
                WHERE j.id IN (SELECT id FROM recent_jobs) OR j.id IN (SELECT attempt_id FROM selected_answers)
                    OR j.id IN (SELECT attempt_id FROM selected_diagnoses))
            SELECT (SELECT COUNT(*) FROM allowed) AS allowed_count,
                (SELECT TO_JSON_STRING(STRUCT(a.revision AS revision,{self._current_environment_id('a')} AS environmentId,
                    {self._current_environment_kind('a')} AS environmentKind,a.environment_label AS environmentLabel,
                    a.submitted_user_verdict AS submittedUserVerdict,
                    JSON_VALUE(a.run_context_json,'$.submission_answer_id') AS submissionAnswerId,
                    JSON_QUERY(a.run_context_json,'$.answer_user_verdicts') AS submittedVerdictsJson))
                    FROM allowed a LIMIT 1) AS review_context_json,
                (SELECT COUNT(*) FROM `{self.workflow_table('feedback_workflow_jobs')}` j JOIN allowed a ON j.feedback_id = a.feedback_id
                    WHERE j.kind = 'retest' AND j.status IN ('queued', 'running')) AS pending_retest_count,
                (SELECT id FROM confirmable_job) AS latest_confirmable_id,
                ARRAY(SELECT TO_JSON_STRING(STRUCT(j.id AS id, j.kind AS kind, j.status AS status,
                    j.environment AS environment, j.target_id AS target_id, j.batch_id AS batch_id, j.phase AS phase,
                    TO_JSON_STRING(STRUCT(JSON_VALUE(j.target_snapshot_json,'$.environmentName') AS environmentName,SAFE_CAST(JSON_VALUE(j.target_snapshot_json,'$.configurationRevision') AS INT64) AS configurationRevision,STRUCT(JSON_VALUE(j.target_snapshot_json,'$.target.environment') AS environment,SAFE_CAST(JSON_VALUE(j.target_snapshot_json,'$.target.configuration_version') AS INT64) AS configuration_version) AS target)) AS target_snapshot_json,
                    j.revision AS revision, j.created_at AS created_at, j.updated_at AS updated_at,
                    j.published_at AS published_at, j.public_summary AS public_summary, j.confirmation AS confirmation,
                    j.result_json AS result_json, j.error AS error)) FROM visible_jobs j ORDER BY j.created_at DESC, j.id DESC LIMIT 300) AS jobs_json,
                ARRAY(SELECT TO_JSON_STRING(v) FROM selected_answers v ORDER BY v.created_at, v.id) AS answers_json,
                ARRAY(SELECT TO_JSON_STRING(v) FROM selected_diagnoses v ORDER BY v.created_at, v.id) AS diagnoses_json""", parameters)
        if not result or not result[0]["allowed_count"]:
            raise KeyError("Feedback item not found")
        jobs = [json.loads(value) for value in result[0].get("jobs_json", [])]
        jobs_by_id = {job['id']: job for job in jobs}
        review_context = self._json_object(result[0].get('review_context_json'))
        source_verdicts = self._json_object(review_context.get('submittedVerdictsJson'))
        current_capture = review_context.get('submissionAnswerId') or f'original:{feedback_id}'
        rows = [{"type": kind, **json.loads(value)} for field, kind in (("answers_json", "answer"), ("diagnoses_json", "rca")) for value in result[0].get(field, [])]
        answers, diagnoses = [], []
        for row in rows:
            payload = self._json_object(row.get("payload_json"))
            if row["type"] == "answer":
                from .answer_review import user_verdict
                if payload.get('kind') == 'retest':
                    payload['userVerdict'] = user_verdict(jobs_by_id.get(row.get('attempt_id'),{}).get('confirmation'))
                elif row['id'] in source_verdicts:
                    payload['userVerdict'] = source_verdicts[row['id']]
                elif row['id'] == current_capture and review_context.get('submittedUserVerdict') is not None:
                    payload['userVerdict'] = review_context['submittedUserVerdict']
                # Agent sources can contain raw tool data; only reviewers receive them.
                if reporters is not None:
                    payload = {key: payload.get(key) for key in ("kind", "question", "answer", "environment", "environmentId", "environmentLabel", "configurationRevision", "batchId", "baselineAnswerId", "agentId", "agentVersion", "modelVersion", "corpusVersion", "createdAt", "revision", "businessDomain", "businessSubdomain", "feedbackText", "expectedBehavior", "userVerdict", "issueCategories", "impact", "runId", "conversationId", "dataSource", "language", "followUp", "latencyMs", "protocol")}
                answers.append({"id": row["id"], "attemptId": row.get("attempt_id"), **payload})
            else:
                if reporters is not None:
                    payload = {key: payload.get(key) for key in ("category", "defect", "rationale", "confidence", "verified", "answerId", "environment", "environmentId", "environmentLabel", "configurationRevision", "createdAt")}
                diagnoses.append({"id": row["id"], "attemptId": row.get("attempt_id"), **payload})
        answer_attempts = {answer.get("attemptId") for answer in answers if answer.get("attemptId")}
        response = {"answers": answers, "diagnoses": diagnoses,
                "attempts": [{**self.safe_job(job), "resultAvailable": job["id"] in answer_attempts} for job in jobs],
                "sharingPolicy": "automatic", "pendingRetestCount": int(result[0].get("pending_retest_count") or 0),
                "latestConfirmableAttemptId": result[0].get("latest_confirmable_id"), "historyLimit": 100}
        if result[0].get('review_context_json'):
            from .answer_review import review_summary
            context = self._json_object(result[0]['review_context_json'])
            completed = next((job for job in jobs if job['id']==result[0].get('latest_confirmable_id')),None)
            latest = next((job for job in jobs if job.get('kind')=='retest'),None)
            def review_job(job):
                if not job:
                    return None
                safe = self.safe_job(job)
                return {**safe,'environmentKind':safe['environment'], 'saved_answer':job['id'] in answer_attempts}
            response['answerReview'] = review_summary(context,review_job(completed),review_job(latest))
        return response

    def confirm_retest(self, feedback_id: str, attempt_id: str, reporters: list[str], actor: str, payload: AnswerConfirmation) -> dict:
        owned = self.get_my_feedback(feedback_id, reporters)
        if not owned:
            raise KeyError("Feedback item not found")
        job = self.get_feedback_job(attempt_id)
        if not job or job["feedback_id"] != feedback_id:
            raise KeyError("Retest not found")
        if job.get("kind") != "retest" or job.get("status") != "completed":
            raise ValueError("Complete the retest before responding to its result")
        if owned.get("revision", 1) != int(job["revision"]):
            raise ValueError("Review the latest completed answer; this input revision is no longer current")
        environment = owned.get("mainEnvironmentKind") or owned.get("environment") or "unknown"
        job_kind = self._json_object(job.get("target_snapshot_json")).get("target", {}).get("environment") or job["environment"]
        if environment not in {"nonprod", "prod"} or environment != job_kind:
            raise ValueError("The original environment is unknown or different; this visible result cannot resolve that report")
        original_id = owned.get("mainEnvironmentId") or owned.get("environmentId") or legacy_environment_id(owned.get("agentId") or settings.default_agent_id, environment)
        target_id = job.get("target_id") or legacy_environment_id(owned.get("agentId") or settings.default_agent_id, job_kind)
        if not original_id or original_id != target_id:
            raise ValueError("This result is from a different named environment and cannot resolve the original report")
        if self.latest_confirmable_retest(feedback_id, int(job["revision"]), environment) != attempt_id:
            raise ValueError("Review the latest completed answer for this input and environment")
        answer = self.get_version("feedback_answer_versions", f"answer:{attempt_id}")
        if not answer or not str(answer.get("answer") or "").strip():
            raise ValueError("A saved agent answer is required before confirmation")
        previous_confirmation = job.get('confirmation')
        if previous_confirmation:
            if job["confirmation"] == payload.verdict:
                return owned
            if payload.expected_confirmation != previous_confirmation:
                raise ValueError('This answer already has a response. Refresh it and explicitly change the verdict for this answer.')
        elif payload.expected_confirmation is not None:
            raise ValueError('The recorded verdict changed. Refresh this answer before responding.')
        fixed = payload.verdict == "fixed"
        status = "Resolved" if fixed else "In review"
        message = "You confirmed that the updated answer fixes your issue." if fixed else "Your remaining concerns have been sent back to the review team."
        jobs = self.workflow_table("feedback_workflow_jobs")
        main_environments = self.workflow_table("feedback_main_environments")
        try:
            self.workflow_query(f"""BEGIN TRANSACTION;
            ASSERT NOT EXISTS(SELECT 1 FROM `{main_environments}` GROUP BY feedback_id,agent_id HAVING COUNT(*)>1) AS 'MAIN_ENVIRONMENT_DUPLICATE';
            UPDATE `{self.feedback_ref}` f SET public_status = @status, public_message = @message,
                latest_published_attempt_id = @attempt,
                resolution_summary = IF(@fixed, @summary, IF(public_status='Resolved',NULL,resolution_summary)), resolved_at = IF(@fixed, CURRENT_TIMESTAMP(), NULL),
                updated_at = CURRENT_TIMESTAMP()
                FROM (SELECT source.feedback_id,source.agent_id,source.run_context_json,source.environment,
                        m.environment_id AS main_environment_id,m.environment_kind AS main_environment_kind
                    FROM `{self.feedback_ref}` source LEFT JOIN `{main_environments}` m
                        ON m.feedback_id=source.feedback_id AND m.agent_id=source.agent_id WHERE source.feedback_id=@id) owner_context
                WHERE f.feedback_id = @id AND f.feedback_id=owner_context.feedback_id AND f.agent_id=owner_context.agent_id
                    AND COALESCE(f.revision, 1) = @revision AND {self._current_environment_kind('owner_context')} = @environment
                    AND {owner_scope(self, 'f')}
                    AND EXISTS (SELECT 1 FROM `{jobs}` current_job WHERE current_job.id = @attempt
                        AND current_job.feedback_id = owner_context.feedback_id AND current_job.kind = 'retest' AND current_job.status = 'completed'
                        AND current_job.revision = @revision AND {self._job_environment_kind('current_job')} = @environment AND {self._same_environment('owner_context','current_job')}
                        AND {self._saved_retest_answer('current_job')})
                    AND NOT EXISTS (SELECT 1 FROM `{jobs}` newer WHERE newer.feedback_id = owner_context.feedback_id
                        AND newer.kind = 'retest' AND newer.status = 'completed' AND newer.revision = @revision
                        AND {self._job_environment_kind('newer')} = @environment AND {self._same_environment('owner_context','newer')}
                        AND (COALESCE(newer.created_at, TIMESTAMP '1970-01-01') > @attempt_created_at
                            OR (COALESCE(newer.created_at, TIMESTAMP '1970-01-01') = @attempt_created_at AND newer.id > @attempt))
                        AND {self._saved_retest_answer('newer')});
            ASSERT @@row_count = 1 AS 'Retest input or environment is no longer current';
            UPDATE `{jobs}` SET confirmation = @verdict,updated_at=CURRENT_TIMESTAMP()
                WHERE id = @attempt AND ((@previous_confirmation IS NULL AND confirmation IS NULL) OR confirmation=@previous_confirmation);
            ASSERT @@row_count = 1 AS 'An answer response is already recorded';
            INSERT INTO `{self.events_ref}` (event_id, feedback_id, event_type, created_at, actor, payload_json)
                VALUES (@event_id, @id, 'answer_confirmation', CURRENT_TIMESTAMP(), @actor, @confirmation_payload);
            COMMIT TRANSACTION;""", [scalar("id", feedback_id), scalar("attempt", attempt_id), scalar("revision", int(job["revision"]), "INT64"),
              scalar("environment", environment), scalar("attempt_created_at", job.get("created_at") or datetime(1970, 1, 1, tzinfo=timezone.utc), "TIMESTAMP"),
              scalar("status", status), scalar("message", message), scalar("summary", job.get("public_summary") or f"You confirmed that the {environment} response resolves this report."),
              scalar("fixed", fixed, "BOOL"), scalar("verdict", payload.verdict),
              scalar('previous_confirmation', previous_confirmation),
             scalar("event_id", str(uuid.uuid4())), scalar("actor", actor),
              scalar("confirmation_payload", json.dumps({"attempt_id": attempt_id, "answer_id": f'answer:{attempt_id}',
                  "verdict": payload.verdict, 'previous_verdict': previous_confirmation, "comment": payload.comment.strip()})),
               bigquery.ArrayQueryParameter("reporters", "STRING", [value.strip().lower() for value in reporters]), *self._environment_parameters()])
        except Exception as exc:
            if "Retest input or environment is no longer current" in str(exc) or "An answer response is already recorded" in str(exc):
                raise ValueError("This result changed or already has a response. Refresh history before confirming it.") from exc
            raise
        self._insert_event(feedback_id, "public_status_updated", actor, {"public_status": status, "public_message": message})
        # A reporter opinion is not an AI assessment. Never rerun or rewrite RCA,
        # the automated comparison, the captured answer, or the submitted verdict here.
        read_cache.invalidate()
        return self.get_my_feedback(feedback_id, reporters)

    def list_notifications(self, reporters: list[str]) -> list[dict]:
        rows = self.workflow_query(f"""SELECT n.id, n.feedback_id, n.attempt_id, n.created_at, n.message, n.read_at, j.target_id AS environment_id
             FROM `{self.workflow_table('feedback_notifications')}` n JOIN `{self.feedback_ref}` f ON n.feedback_id = f.feedback_id
            LEFT JOIN `{self.workflow_table('feedback_workflow_jobs')}` j ON j.id=n.attempt_id
            WHERE {owner_scope(self, 'f')} ORDER BY n.created_at DESC LIMIT 50""",
            [bigquery.ArrayQueryParameter("reporters", "STRING", [value.strip().lower() for value in reporters])])
        return [{"id": row["id"], "feedbackId": row["feedback_id"], "attemptId": row["attempt_id"], "message": row["message"],
                  "createdAt": str(row["created_at"]), "readAt": str(row.get("read_at") or "") or None, "environmentId": row.get("environment_id")} for row in rows]

    def mark_notification_read(self, notification_id: str, reporters: list[str]) -> None:
        self.workflow_query(f"""UPDATE `{self.workflow_table('feedback_notifications')}` n SET read_at = COALESCE(read_at, CURRENT_TIMESTAMP())
            WHERE id = @id AND EXISTS(SELECT 1 FROM `{self.feedback_ref}` f WHERE f.feedback_id = n.feedback_id
                AND {owner_scope(self, 'f')})""",
            [scalar("id", notification_id), bigquery.ArrayQueryParameter("reporters", "STRING", [value.strip().lower() for value in reporters])])
        read_cache.invalidate()


class BigQueryJson:
    @staticmethod
    def object(value) -> dict:
        if isinstance(value, dict):
            return value
        try:
            parsed = json.loads(value or "{}")
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, json.JSONDecodeError):
            return {}
