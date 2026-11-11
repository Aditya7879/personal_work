"""Persistent environments and bounded, explicitly confirmed cross-environment retests."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import re
from threading import Lock
from urllib.parse import urlsplit

from google.api_core.exceptions import BadRequest, NotFound
from google.cloud import bigquery

from .agent_targets import AgentTarget, agent_targets, legacy_environment_id, stored_environment_kind, validate_environment_target
from .cache import read_cache
from .config import settings
from .demo_context import is_demo
from .models import AgentEnvironmentInput, FeedbackRecord, PromotionSelection, PromotionCreate


_READY: set[str] = set()
_LOCK = Lock()


def parameter(name, value, kind="STRING"):
    return bigquery.ScalarQueryParameter(name, kind, value)


def environment_target(row: dict) -> AgentTarget:
    return AgentTarget(id=row["id"], agent_id=row["agent_id"], environment=row["kind"],
        label=f"NEO · {row['name']}", url=row.get("url") or "", auth=row.get("auth") or "google_access_token",
        audience=row.get("audience") or "", token_env=row.get("token_env") or "", version=row.get("agent_version"),
        protocol=row.get("protocol") or "neo_companion", timeout_seconds=int(row.get("timeout_seconds") or 300),
        enabled=bool(row.get("enabled", True)), configuration_version=int(row.get("revision") or 1))


def public_environment(row: dict, user, include_configuration: bool = False) -> dict:
    target = environment_target(row)
    reason = target.blocked_reason(user)
    if reason is None and not settings.workflow_worker_enabled and not is_demo():
        reason = "The workflow worker is disabled; enable it only after runtime access is approved"
    can_activate = user.role == "reviewer"
    can_manage = user.role == "reviewer"
    test_reason = ("Reviewer access is required to test endpoints" if user.role != "reviewer" else
        "Add and save an endpoint URL before testing" if not target.url else None)
    last_test = row.get("last_test")
    value = {"id": row["id"], "agentId": row["agent_id"], "name": row["name"], "kind": row["kind"],
        "enabled": bool(row.get("enabled", True)), "revision": int(row.get("revision") or 1),
        "configured": bool(target.url), "canRetest": reason is None, "reason": reason,
        "canManage": can_manage, "canActivate": can_activate,
        "manageReason": None if can_manage else "Reviewer access is required",
        "activationReason": None if can_activate else "Reviewer access is required",
        "canTest": test_reason is None, "testReason": test_reason,
        "accessStatus": last_test.get("status", "unverified") if last_test else "unverified" if target.url else "not_configured",
        "persisted": bool(row.get("persisted", True)), "updatedAt": str(row.get("updated_at") or "")}
    if include_configuration:
        value.update(url=target.url, protocol=target.protocol, auth=target.auth,
                      timeoutSeconds=target.timeout_seconds, agentVersion=target.version, lastTest=last_test)
    if is_demo():
        from .role_demo import require_demo_scope
        require_demo_scope()
        value.update(canManage=False,canActivate=False,canTest=False,
            manageReason='Fixed sample connections in the isolated demo',activationReason='Fixed sample connections in the isolated demo',
            testReason='Real endpoint tests are disabled; retests use clearly labelled simulation',accessStatus='demo_simulated')
    return value


def bootstrap_environments() -> list[dict]:
    return [{"id": target.id, "agent_id": target.agent_id,
        "name": target.label.split(" · ")[-1], "kind": target.environment, "url": target.url,
        "auth": target.auth, "audience": target.audience, "token_env": target.token_env,
        "protocol": target.protocol, "timeout_seconds": target.timeout_seconds, "agent_version": target.version,
        "enabled": bool(target.url), "revision": 1, "persisted": False} for target in agent_targets()
        if target.agent_id == settings.default_agent_id]


class EnvironmentRepositoryMixin:
    def environment_transaction(self, sql: str, params: list) -> None:
        try:
            self.workflow_query(sql, params)
        except BadRequest as error:
            if "concurrent update" in str(error).lower():
                raise ValueError("Another operation changed the target or selection. Review it and retry the same confirmation") from error
            expected = {"Environment changed or already exists": "Environment changed or already exists; reload before saving",
                "Target configuration changed or was disabled": "Target configuration changed or was disabled; review it before confirming",
                "Feedback input changed; review selection again": "Feedback input changed; review the selection again",
                "A selected input already has an active target check": "Some selected feedback already has a queued/running check in this target environment. Wait for it or cancel queued items first"}
            for marker, message in expected.items():
                if marker in str(error):
                    raise ValueError(message) from error
            raise

    def ensure_environment_schema(self) -> None:
        """Additive only: no feedback/golden/history rows are backfilled or rewritten."""
        with _LOCK:
            if self.dataset_ref in _READY:
                return
            schemas = {
                "agent_environments": [("id", "STRING"), ("agent_id", "STRING"), ("name", "STRING"),
                    ("kind", "STRING"), ("url", "STRING"), ("auth", "STRING"), ("audience", "STRING"),
                    ("token_env", "STRING"), ("protocol", "STRING"), ("timeout_seconds", "INT64"),
                    ("agent_version", "STRING"), ("enabled", "BOOL"), ("revision", "INT64"),
                    ("dispatch_epoch", "INT64"), ("created_at", "TIMESTAMP"), ("updated_at", "TIMESTAMP"), ("updated_by", "STRING")],
                "agent_environment_versions": [("id", "STRING"), ("environment_id", "STRING"), ("revision", "INT64"),
                    ("created_at", "TIMESTAMP"), ("actor", "STRING"), ("payload_json", "STRING")],
                "feedback_promotion_batches": [("id", "STRING"), ("target_id", "STRING"), ("target_name", "STRING"),
                    ("source_environment_id", "STRING"), ("created_at", "TIMESTAMP"), ("requested_by", "STRING"),
                    ("request_hash", "STRING"), ("total", "INT64"), ("cancelled_at", "TIMESTAMP")],
                "feedback_main_environments": [("feedback_id", "STRING"), ("agent_id", "STRING"),
                    ("environment_id", "STRING"), ("environment_kind", "STRING"), ("environment_label", "STRING"),
                    ("source_environment_id", "STRING"), ("promotion_batch_id", "STRING"), ("revision", "INT64"),
                    ("selected_by", "STRING"), ("created_at", "TIMESTAMP"), ("updated_at", "TIMESTAMP")],
                "agent_endpoint_tests": [("id", "STRING"), ("environment_id", "STRING"), ("configuration_revision", "INT64"),
                    ("runtime_scope", "STRING"), ("requested_by", "STRING"), ("created_at", "TIMESTAMP"),
                    ("completed_at", "TIMESTAMP"), ("status", "STRING"), ("result_json", "STRING")],
            }
            for name, fields in schemas.items():
                self.client.create_table(bigquery.Table(self.workflow_table(name), schema=[bigquery.SchemaField(key, kind) for key, kind in fields]), exists_ok=True)
            for key, kind in [("batch_id", "STRING"), ("target_snapshot_json", "STRING"), ("phase", "STRING"), ("generation_started_at", "TIMESTAMP")]:
                self.workflow_query(f"ALTER TABLE `{self.workflow_table('feedback_workflow_jobs')}` ADD COLUMN IF NOT EXISTS {key} {kind}")
            for row in bootstrap_environments():
                fields = [key for key in row if key != "persisted"]
                params = [parameter(key, row[key], "BOOL" if key == "enabled" else "INT64" if key in {"revision", "timeout_seconds"} else "STRING") for key in fields]
                self.workflow_query(f"""MERGE `{self.workflow_table('agent_environments')}` t USING (SELECT @id AS id) s ON t.id=s.id
                    WHEN NOT MATCHED THEN INSERT ({','.join(fields)},dispatch_epoch,created_at,updated_at,updated_by)
                    VALUES ({','.join('@'+key for key in fields)},0,CURRENT_TIMESTAMP(),CURRENT_TIMESTAMP(),'system:existing_configuration')""", params)
            self.workflow_query(f"""MERGE `{self.workflow_table('agent_environment_versions')}` v
                USING (SELECT CONCAT(id,':r',CAST(revision AS STRING)) AS version_id,id,revision,updated_at,updated_by,TO_JSON_STRING(e) AS payload
                    FROM `{self.workflow_table('agent_environments')}` e WHERE agent_id=@agent) s ON v.id=s.version_id
                WHEN NOT MATCHED THEN INSERT(id,environment_id,revision,created_at,actor,payload_json)
                    VALUES(s.version_id,s.id,s.revision,COALESCE(s.updated_at,CURRENT_TIMESTAMP()),s.updated_by,s.payload)""",
                [parameter("agent", settings.default_agent_id)])
            _READY.add(self.dataset_ref)
        read_cache.invalidate()

    def list_agent_environments(self, include_tests: bool = True) -> list[dict]:
        try:
            rows = self.workflow_query(f"SELECT * FROM `{self.workflow_table('agent_environments')}` WHERE agent_id=@agent ORDER BY created_at,id", [parameter("agent", settings.default_agent_id)])
        except NotFound:
            return bootstrap_environments()
        if include_tests and rows:
            from .endpoint_tests import runtime_scope, test_result
            try:
                tests = self.workflow_query(f"""SELECT t.* FROM `{self.workflow_table('agent_endpoint_tests')}` t
                    JOIN `{self.workflow_table('agent_environments')}` e ON e.id=t.environment_id AND e.revision=t.configuration_revision
                    WHERE e.agent_id=@agent AND t.runtime_scope=@runtime
                    QUALIFY ROW_NUMBER() OVER(PARTITION BY t.environment_id ORDER BY t.created_at DESC,t.id DESC)=1""",
                    [parameter("agent", settings.default_agent_id), parameter("runtime", runtime_scope())])
                latest = {row["environment_id"]: test_result(row) for row in tests}
                rows = [{**row, "last_test": latest.get(row["id"])} for row in rows]
            except NotFound:
                pass
        return rows

    def get_agent_environment(self, environment_id: str) -> dict:
        row = next((row for row in self.list_agent_environments(include_tests=False) if row["id"] == environment_id), None)
        if row is None:
            raise KeyError("Environment not found")
        return row

    def save_agent_environment(self, payload: AgentEnvironmentInput, actor: str, environment_id: str | None = None) -> dict:
        self.ensure_environment_schema()
        old = self.get_agent_environment(environment_id) if environment_id else None
        if old and old["kind"] != payload.kind:
            raise ValueError("Environment type cannot be changed; create a separate environment instead")
        if old and payload.expected_revision != int(old["revision"]):
            raise ValueError("This configuration changed. Reload it before saving")
        duplicates = [row for row in self.list_agent_environments() if row["name"].casefold() == payload.name.casefold() and row["id"] != environment_id]
        if duplicates:
            raise ValueError("An environment with this name already exists")
        slug = re.sub(r"[^a-z0-9]+", "-", payload.name.lower()).strip("-")[:36] or "environment"
        identity = environment_id or f"neo-{slug}-{hashlib.sha256(payload.name.casefold().encode()).hexdigest()[:8]}"
        row = {"id": identity, "agent_id": settings.default_agent_id, "name": payload.name, "kind": payload.kind,
            "url": payload.url, "auth": payload.auth, "audience": f"{urlsplit(payload.url).scheme}://{urlsplit(payload.url).netloc}" if payload.auth == "google_id_token" and payload.url else "",
            "token_env": "", "protocol": payload.protocol, "timeout_seconds": payload.timeout_seconds,
            "agent_version": payload.agent_version, "enabled": payload.enabled, "revision": int(old["revision"]) + 1 if old else 1}
        validate_environment_target(environment_target(row))
        params = [parameter(key, value, "BOOL" if key == "enabled" else "INT64" if key in {"revision", "timeout_seconds"} else "STRING") for key, value in row.items()]
        params += [parameter("actor", actor), parameter("expected", payload.expected_revision, "INT64"), parameter("snapshot", json.dumps(row))]
        fields = list(row)
        if old:
            mutation = f"""UPDATE `{self.workflow_table('agent_environments')}` SET {','.join(key+'=@'+key for key in fields if key != 'id')},
                updated_at=CURRENT_TIMESTAMP(),updated_by=@actor WHERE id=@id AND revision=@expected;"""
        else:
            mutation = f"""MERGE `{self.workflow_table('agent_environments')}` t USING (SELECT @id AS id) s ON t.id=s.id
                WHEN NOT MATCHED THEN INSERT ({','.join(fields)},dispatch_epoch,created_at,updated_at,updated_by)
                VALUES ({','.join('@'+key for key in fields)},0,CURRENT_TIMESTAMP(),CURRENT_TIMESTAMP(),@actor);"""
        self.environment_transaction(f"""BEGIN TRANSACTION; {mutation}
            ASSERT @@row_count=1 AS 'Environment changed or already exists';
            INSERT INTO `{self.workflow_table('agent_environment_versions')}` (id,environment_id,revision,created_at,actor,payload_json)
                VALUES(CONCAT(@id,':r',CAST(@revision AS STRING)),@id,@revision,CURRENT_TIMESTAMP(),@actor,@snapshot);
            COMMIT TRANSACTION;""", params)
        read_cache.invalidate()
        return self.get_agent_environment(identity)

    def select_promotion_records(self, selection: PromotionSelection) -> tuple[list[FeedbackRecord], str]:
        limit = min(20 if is_demo() else 500, max(1, settings.promotion_batch_limit))
        if selection.filters.environment_id:
            self.get_agent_environment(selection.filters.environment_id)
        if selection.all_matching:
            filters = selection.filters.model_dump(exclude_none=True)
            records, total = self.list_feedback(**filters, agent_id=settings.default_agent_id, page_size=limit + 1)
            if total > limit:
                raise ValueError(f"Select at most {limit} feedback records per batch; narrow the filters")
        else:
            if len(selection.feedback_ids) > limit:
                raise ValueError(f"Select at most {limit} feedback records per batch")
            rows = self.workflow_query(f"SELECT * FROM `{self.feedback_ref}` WHERE feedback_id IN UNNEST(@ids) AND agent_id=@agent",
                [bigquery.ArrayQueryParameter("ids", "STRING", selection.feedback_ids), parameter("agent", settings.default_agent_id)])
            records = [self._record(row) for row in rows]
            if len(records) != len(selection.feedback_ids):
                raise ValueError("Some selected feedback no longer exists or belongs to another agent")
        if not records:
            raise ValueError("No feedback matches this selection")
        if len(records) > limit:
            raise ValueError(f"Select at most {limit} feedback records per batch; review the changed selection")
        if any(not record.prompt.strip() for record in records):
            raise ValueError("Every selected feedback must have its original question before promotion")
        token = hashlib.sha256(json.dumps({"records": sorted((record.id, record.revision) for record in records),
            "source": selection.filters.environment_id}, sort_keys=True).encode()).hexdigest()
        return records, token

    def promotion_preview(self, selection: PromotionSelection) -> dict:
        records, token = self.select_promotion_records(selection)
        return {"count": len(records), "selectionToken": token,
                "items": [{"id": row.id, "title": row.title, "revision": row.revision} for row in records[:5]],
                "limit": min(20 if is_demo() else 500, settings.promotion_batch_limit)}

    def _promotion_baselines(self, records: list[FeedbackRecord], source_id: str | None) -> dict:
        rows = self.workflow_query(f"""SELECT v.feedback_id,v.id,v.payload_json,j.target_id FROM `{self.workflow_table('feedback_answer_versions')}` v
            LEFT JOIN `{self.workflow_table('feedback_workflow_jobs')}` j ON j.id=v.attempt_id
            WHERE v.feedback_id IN UNNEST(@ids) ORDER BY v.created_at DESC,v.id DESC""",
            [bigquery.ArrayQueryParameter("ids", "STRING", [row.id for row in records])])
        baselines = {}
        by_id = {row.id: row for row in records}
        for row in rows:
            record = by_id[row["feedback_id"]]
            answer = self._json_object(row["payload_json"])
            identity = answer.get("environmentId") or row.get("target_id") or record.environmentId
            if record.id not in baselines and answer.get("question") == record.prompt and answer.get("revision", 1) == record.revision:
                if (source_id and identity == source_id) or (not source_id and row["id"] == (record.runContext.get("submission_answer_id") or f"original:{record.id}")):
                    baselines[record.id] = {"id": row["id"], **answer}
        return baselines

    def create_promotion(self, payload: PromotionCreate, target_row: dict, actor: str) -> dict:
        self.ensure_environment_schema()
        batch_id = "PROM-" + hashlib.sha256(f"{actor}:{payload.idempotency_key}".encode()).hexdigest()[:28]
        request_hash = hashlib.sha256(payload.model_dump_json().encode()).hexdigest()
        existing = self.get_promotion(batch_id, missing_ok=True)
        if existing:
            if existing["requestHash"] != request_hash or existing["requestedBy"] != actor:
                raise ValueError("This confirmation key belongs to a different promotion")
            return existing
        records, token = self.select_promotion_records(payload)
        if token != payload.selection_token:
            raise ValueError("The selection or input revisions changed. Review the updated count before confirming")
        target = environment_target(target_row)
        baselines = self._promotion_baselines(records, payload.filters.environment_id)
        values = []
        for record in records:
            job_id = "JOB-" + hashlib.sha256(f"{batch_id}:{record.id}:{record.revision}".encode()).hexdigest()[:32]
            snapshot = {"target": asdict(target), "environmentName": target_row["name"],
                "baseline": baselines.get(record.id), "sourceEnvironmentId": payload.filters.environment_id}
            original = {"kind": "original", "question": record.prompt, "answer": record.generatedAnswer,
                "environment": record.environment, "environmentId": record.environmentId,
                "environmentLabel": record.environmentLabel, "revision": record.revision, "createdAt": record.reportedTime}
            values.append(bigquery.StructQueryParameter(None, parameter("id", job_id), parameter("feedback_id", record.id),
                parameter("revision", record.revision, "INT64"), parameter("payload", record.model_dump_json()),
                parameter("snapshot", json.dumps(snapshot)), parameter("original", json.dumps(original))))
        params = [parameter("batch", batch_id), parameter("target", target.id), parameter("name", target_row["name"]),
            parameter("target_revision", target_row["revision"], "INT64"), parameter("environment", stored_environment_kind(target.agent_id, target.environment, target.id)),
            parameter("target_kind", target.environment),
            parameter("source", payload.filters.environment_id), parameter("actor", actor), parameter("request_hash", request_hash),
            parameter("total", len(records), "INT64"), parameter("agent", settings.default_agent_id),
            *self._environment_parameters(), bigquery.ArrayQueryParameter("items", "STRUCT", values)]
        if len(json.dumps([value.to_api_repr() for value in params]).encode()) > 9_000_000:
            raise ValueError("Selected answers are too large for one batch. Select fewer feedback records")
        jobs = self.workflow_table('feedback_workflow_jobs')
        self.environment_transaction(f"""BEGIN TRANSACTION;
            UPDATE `{self.workflow_table('agent_environments')}` SET dispatch_epoch=COALESCE(dispatch_epoch,0)+1
                WHERE id=@target AND revision=@target_revision AND enabled;
            ASSERT @@row_count=1 AS 'Target configuration changed or was disabled';
            MERGE `{self.workflow_table('feedback_promotion_batches')}` t USING (SELECT @batch AS id) s ON t.id=s.id
            WHEN NOT MATCHED THEN INSERT(id,target_id,target_name,source_environment_id,created_at,requested_by,request_hash,total)
                VALUES(@batch,@target,@name,@source,CURRENT_TIMESTAMP(),@actor,@request_hash,@total);
            IF @@row_count=1 THEN
                ASSERT NOT EXISTS(SELECT 1 FROM `{jobs}` j JOIN UNNEST(@items) s ON j.feedback_id=s.feedback_id AND j.revision=s.revision
                    WHERE j.kind='retest' AND j.target_id=@target AND j.status IN ('queued','running')) AS 'A selected input already has an active target check';
                ASSERT (SELECT COUNT(*) FROM `{self.feedback_ref}` f JOIN UNNEST(@items) s ON f.feedback_id=s.feedback_id
                    WHERE COALESCE(f.revision,1)=s.revision) = @total AS 'Feedback input changed; review selection again';
                MERGE `{self.workflow_table('feedback_answer_versions')}` v USING UNNEST(@items) s ON v.id=CONCAT('original:',s.feedback_id)
                WHEN NOT MATCHED THEN INSERT(id,feedback_id,attempt_id,created_at,payload_json)
                    VALUES(CONCAT('original:',s.feedback_id),s.feedback_id,NULL,CURRENT_TIMESTAMP(),s.original);
                INSERT INTO `{jobs}` (id,feedback_id,kind,status,phase,created_at,updated_at,attempts,revision,target_id,environment,requested_by,payload_json,batch_id,target_snapshot_json)
                SELECT id,feedback_id,'retest','queued','queued',CURRENT_TIMESTAMP(),CURRENT_TIMESTAMP(),0,revision,@target,@environment,@actor,payload,@batch,snapshot FROM UNNEST(@items);
                INSERT INTO `{self.events_ref}` (event_id,feedback_id,event_type,created_at,actor,payload_json)
                SELECT CONCAT('promotion:',id),feedback_id,'environment_promotion_requested',CURRENT_TIMESTAMP(),@actor,
                     TO_JSON_STRING(STRUCT(@batch AS batch_id,@target AS target_environment_id,@target_kind AS target_environment_kind,
                        @source AS filtered_source_environment_id,revision AS revision)) FROM UNNEST(@items);
                ASSERT NOT EXISTS(SELECT 1 FROM `{self.workflow_table('feedback_main_environments')}`
                    GROUP BY feedback_id,agent_id HAVING COUNT(*)>1) AS 'Duplicate main environment selections require review';
                MERGE `{self.workflow_table('feedback_main_environments')}` m
                 USING (SELECT s.feedback_id,f.agent_id,@target AS environment_id,@target_kind AS environment_kind,@name AS environment_label,
                    COALESCE(JSON_VALUE(f.run_context_json,'$.environment_id'),
                        CASE COALESCE(JSON_VALUE(f.run_context_json,'$.environment_kind'),f.environment)
                            WHEN 'nonprod' THEN @legacy_nonprod WHEN 'prod' THEN @legacy_prod END) AS source_environment_id,
                    @batch AS promotion_batch_id,@actor AS selected_by
                    FROM UNNEST(@items) s JOIN `{self.feedback_ref}` f ON f.feedback_id=s.feedback_id
                        AND COALESCE(f.revision,1)=s.revision) s
                    ON m.feedback_id=s.feedback_id AND m.agent_id=s.agent_id
                WHEN MATCHED THEN UPDATE SET environment_id=s.environment_id,environment_kind=s.environment_kind,
                    environment_label=s.environment_label,source_environment_id=s.source_environment_id,
                    promotion_batch_id=s.promotion_batch_id,revision=COALESCE(m.revision,0)+1,
                    selected_by=s.selected_by,updated_at=CURRENT_TIMESTAMP()
                WHEN NOT MATCHED THEN INSERT(feedback_id,agent_id,environment_id,environment_kind,environment_label,
                    source_environment_id,promotion_batch_id,revision,selected_by,created_at,updated_at)
                    VALUES(s.feedback_id,s.agent_id,s.environment_id,s.environment_kind,s.environment_label,
                        s.source_environment_id,s.promotion_batch_id,1,s.selected_by,CURRENT_TIMESTAMP(),CURRENT_TIMESTAMP());
                 ASSERT (SELECT COUNT(*) FROM `{self.workflow_table('feedback_main_environments')}` m
                     JOIN UNNEST(@items) s ON m.feedback_id=s.feedback_id WHERE m.agent_id=@agent
                     AND m.promotion_batch_id=@batch AND m.environment_id=@target AND m.environment_kind=@target_kind)=@total AS 'Main environment selection failed';
                INSERT INTO `{self.events_ref}` (event_id,feedback_id,event_type,created_at,actor,payload_json)
                    SELECT CONCAT('main-environment:',@batch,':',m.feedback_id),m.feedback_id,'main_environment_selected',
                        CURRENT_TIMESTAMP(),@actor,TO_JSON_STRING(STRUCT(m.promotion_batch_id AS promotion_batch_id,
                            m.source_environment_id AS original_environment_id,m.environment_id AS main_environment_id,
                            m.environment_kind AS main_environment_kind,m.environment_label AS main_environment_label,
                            m.revision AS selection_revision))
                    FROM `{self.workflow_table('feedback_main_environments')}` m JOIN UNNEST(@items) s ON m.feedback_id=s.feedback_id
                    WHERE m.agent_id=@agent AND m.promotion_batch_id=@batch;
            END IF;
            COMMIT TRANSACTION;""", params)
        read_cache.invalidate()
        result = self.get_promotion(batch_id)
        if result["requestHash"] != request_hash or result["requestedBy"] != actor:
            raise ValueError("This confirmation key belongs to another promotion")
        return result

    def get_promotion(self, batch_id: str, missing_ok: bool = False) -> dict | None:
        try:
            rows = self.workflow_query(f"SELECT * FROM `{self.workflow_table('feedback_promotion_batches')}` WHERE id=@id LIMIT 1", [parameter("id", batch_id)])
        except NotFound:
            if missing_ok:
                return None
            raise
        if not rows:
            if missing_ok:
                return None
            raise KeyError("Promotion not found")
        row = rows[0]
        jobs = self.workflow_query(f"SELECT j.*, {self._saved_retest_answer('j')} AS result_available FROM `{self.workflow_table('feedback_workflow_jobs')}` j WHERE batch_id=@id ORDER BY created_at,id", [parameter("id", batch_id)])
        return self._promotion_response(row, jobs)

    def _promotion_response(self, row: dict, jobs: list[dict], counts: dict | None = None) -> dict:
        counts = counts or {state: sum(job.get("status") == state for job in jobs) for state in ["queued", "running", "completed", "failed", "cancelled"]}
        return {"id": row["id"], "targetId": row["target_id"], "targetName": row["target_name"],
            "sourceEnvironmentId": row.get("source_environment_id"), "createdAt": str(row["created_at"]),
            "requestedBy": row["requested_by"], "requestHash": row["request_hash"], "total": row["total"],
            "counts": counts, "finished": counts["queued"] + counts["running"] == 0,
            "items": [{**self.safe_job(job), "feedbackId": job["feedback_id"], "resultAvailable": bool(job.get("result_available"))} for job in jobs]}

    def list_promotions(self) -> list[dict]:
        try:
            rows = self.workflow_query(f"SELECT * FROM `{self.workflow_table('feedback_promotion_batches')}` ORDER BY created_at DESC LIMIT 12")
        except NotFound:
            return []
        if not rows:
            return []
        grouped = self.workflow_query(f"SELECT batch_id,status,COUNT(*) AS count FROM `{self.workflow_table('feedback_workflow_jobs')}` WHERE batch_id IN UNNEST(@ids) GROUP BY batch_id,status",
            [bigquery.ArrayQueryParameter("ids", "STRING", [row["id"] for row in rows])])
        return [self._promotion_response(row, [], {state: sum(item["count"] for item in grouped if item["batch_id"] == row["id"] and item["status"] == state) for state in ["queued", "running", "completed", "failed", "cancelled"]}) for row in rows]

    def cancel_promotion(self, batch_id: str, actor: str) -> dict:
        self.get_promotion(batch_id)
        self.workflow_query(f"""BEGIN TRANSACTION;
            UPDATE `{self.workflow_table('feedback_promotion_batches')}` SET cancelled_at=CURRENT_TIMESTAMP() WHERE id=@id;
            UPDATE `{self.workflow_table('feedback_workflow_jobs')}` SET status='cancelled',phase='cancelled',updated_at=CURRENT_TIMESTAMP()
                WHERE batch_id=@id AND status='queued';
            INSERT INTO `{self.events_ref}` (event_id,feedback_id,event_type,created_at,actor,payload_json)
                VALUES(@event,'','promotion_remaining_cancelled',CURRENT_TIMESTAMP(),@actor,TO_JSON_STRING(STRUCT(@id AS batch_id)));
            COMMIT TRANSACTION;""", [parameter("id", batch_id), parameter("actor", actor), parameter("event", "cancel:" + hashlib.sha256(f"{batch_id}:{datetime.now(timezone.utc).isoformat()}".encode()).hexdigest()[:24])])
        read_cache.invalidate()
        return self.get_promotion(batch_id)

    def environment_results(self, records: list[FeedbackRecord], environment_id: str) -> dict:
        if not records:
            return {}
        rows = self.workflow_query(f"""SELECT j.*,JSON_VALUE(v.payload_json,'$.category') AS rca_category,
            JSON_VALUE(v.payload_json,'$.defect') AS rca_defect
            FROM `{self.workflow_table('feedback_workflow_jobs')}` j
            LEFT JOIN `{self.workflow_table('feedback_rca_versions')}` v ON v.answer_id=CONCAT('answer:',j.id)
            WHERE j.feedback_id IN UNNEST(@ids) AND j.kind='retest' AND j.target_id=@environment
            QUALIFY ROW_NUMBER() OVER(PARTITION BY j.feedback_id ORDER BY j.created_at DESC,j.id DESC,v.created_at DESC,v.id DESC)=1""",
            [bigquery.ArrayQueryParameter("ids", "STRING", [row.id for row in records]), parameter("environment", environment_id)])
        return {row["feedback_id"]: {**self.safe_job(row), "rcaCategory": row.get("rca_category"), "rcaDefect": row.get("rca_defect")} for row in rows}

    def main_environment_results(self, records: list[FeedbackRecord]) -> dict:
        """Return the latest linked attempt for each selected main environment.

        The original source environment stays on the feedback record; this summary
        only supplies the current main target's saved validation status to All views.
        """
        selections = [record for record in records if record.mainEnvironmentId]
        if not selections:
            return {}
        params = [bigquery.ArrayQueryParameter('selections','STRUCT',[
            bigquery.StructQueryParameter(None,parameter('feedback_id',record.id),parameter('environment_id',record.mainEnvironmentId),
                parameter('revision',record.revision,'INT64'))
            for record in selections])]
        rows = self.workflow_query(f"""SELECT j.*,JSON_VALUE(v.payload_json,'$.category') AS rca_category,
            JSON_VALUE(v.payload_json,'$.defect') AS rca_defect
            FROM `{self.workflow_table('feedback_workflow_jobs')}` j
            JOIN UNNEST(@selections) selected ON selected.feedback_id=j.feedback_id AND selected.environment_id=j.target_id
                AND selected.revision=j.revision
            LEFT JOIN `{self.workflow_table('feedback_rca_versions')}` v ON v.answer_id=CONCAT('answer:',j.id)
            WHERE j.kind='retest'
            QUALIFY ROW_NUMBER() OVER(PARTITION BY j.feedback_id ORDER BY j.created_at DESC,j.id DESC,v.created_at DESC,v.id DESC)=1""",params)
        return {row['feedback_id']:{**self.safe_job(row),'rcaCategory':row.get('rca_category'),'rcaDefect':row.get('rca_defect')} for row in rows}

    def queue_saved_answer_rca(self, feedback_id: str, answer_id: str, actor: str, key: str) -> dict:
        record = self.get_feedback(feedback_id)
        rows = self.workflow_query(f"SELECT payload_json FROM `{self.workflow_table('feedback_answer_versions')}` WHERE id=@answer AND feedback_id=@feedback LIMIT 1",
            [parameter("answer", answer_id), parameter("feedback", feedback_id)])
        if not record or not rows:
            raise KeyError("Saved answer not found for this feedback")
        answer = self._json_object(rows[0]["payload_json"])
        if not answer.get("answer") or not answer.get("question"):
            raise ValueError("A saved question and answer are required for an RCA-only recheck")
        updated = record.model_copy(update={"prompt": answer["question"], "generatedAnswer": answer["answer"],
            "revision": answer.get("revision", 1), "environment": answer.get("environment", "unknown"),
            "environmentId": answer.get("environmentId"), "environmentLabel": answer.get("environmentLabel"),
            "runContext": {**record.runContext, "analysis_answer_id": answer_id}})
        return self.enqueue_feedback_job(updated, "rca", actor, answer.get("environmentId"), answer.get("environment"), key,
            target_snapshot={"environmentName": answer.get("environmentLabel"), "configurationRevision": answer.get("configurationRevision")})
