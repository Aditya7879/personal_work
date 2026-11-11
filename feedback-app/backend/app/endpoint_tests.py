"""Explicit, one-shot endpoint diagnostics. Never create feedback, RCA or workflow jobs."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
import socket
from threading import BoundedSemaphore
import time

from google.api_core.exceptions import NotFound

from .agent_errors import AgentInvocationError
from .agent_targets import invoke_agent, validate_environment_target
from .environment_repository import environment_target, parameter


_SLOTS = BoundedSemaphore(2)
logger = logging.getLogger(__name__)


def runtime_scope() -> str:
    if os.getenv("K_SERVICE"):
        return "cloud:" + os.environ["K_SERVICE"] + ":" + os.getenv("K_REVISION", "unknown")
    return "local:" + socket.gethostname()


def test_result(row: dict) -> dict:
    raw = row.get("result_json")
    try:
        value = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
    except (ValueError, TypeError):
        value = {}
    value.update(id=row["id"], environmentId=row["environment_id"], configurationRevision=row["configuration_revision"],
                 status=row["status"], createdAt=str(row["created_at"]), completedAt=str(row.get("completed_at") or "") or None)
    if value["status"] == "running":
        stamp = row["created_at"]
        if isinstance(stamp, str):
            stamp = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - stamp).total_seconds() > 90:
            value.update(status="outcome_unknown", outcomeUnknown=True,
                error="The test was interrupted or its result was not saved. It may have run upstream. No automatic replay was made.")
    return value


def get_endpoint_test(repo, environment_id: str, test_id: str) -> dict:
    try:
        rows = repo.workflow_query(f"""SELECT * FROM `{repo.workflow_table('agent_endpoint_tests')}`
            WHERE id=@id AND environment_id=@environment AND runtime_scope=@runtime LIMIT 1""",
            [parameter("id", test_id), parameter("environment", environment_id), parameter("runtime", runtime_scope())])
    except NotFound as error:
        raise KeyError("Endpoint test not found") from error
    if not rows:
        raise KeyError("Endpoint test not found")
    return test_result(rows[0])


def run_endpoint_test(repo, environment: dict, payload, actor: str) -> dict:
    repo.ensure_environment_schema()
    identity = "TEST-" + hashlib.sha256(f"{actor}:{environment['id']}:{payload.expected_revision}:{payload.idempotency_key}".encode()).hexdigest()[:32]
    question_hash = hashlib.sha256(payload.question.encode()).hexdigest()
    try:
        previous = get_endpoint_test(repo, environment['id'], identity)
    except KeyError:
        previous = None
    if previous:
        if previous.get("questionHash") != question_hash:
            raise ValueError("This test key belongs to another question; start a new test explicitly")
        return previous
    if payload.expected_revision != int(environment["revision"]):
        raise ValueError("The endpoint configuration changed. Reload it before testing")
    target = replace(environment_target(environment), enabled=True, timeout_seconds=min(int(environment.get("timeout_seconds") or 300), 60))
    if not target.url:
        raise ValueError("Add and save an endpoint URL before testing")
    validate_environment_target(target)
    if not _SLOTS.acquire(blocking=False):
        raise ValueError("Other endpoint tests are running. Wait before starting another")
    try:
        params = [parameter("id", identity), parameter("environment", target.id), parameter("revision", target.configuration_version, "INT64"),
            parameter("actor", actor), parameter("runtime", runtime_scope()),
            parameter("initial", json.dumps({"questionHash": question_hash, "message": "One response request; no feedback or RCA is created"}))]
        table = repo.workflow_table('agent_endpoint_tests')
        try:
            reservation = repo.workflow_query(f"""DECLARE made BOOL DEFAULT FALSE; BEGIN TRANSACTION;
                UPDATE `{repo.workflow_table('agent_environments')}` SET dispatch_epoch=COALESCE(dispatch_epoch,0)+1
                    WHERE id=@environment AND revision=@revision;
                ASSERT @@row_count=1 AS 'Endpoint configuration changed before testing';
                ASSERT NOT EXISTS(SELECT 1 FROM `{table}` WHERE environment_id=@environment AND runtime_scope=@runtime
                    AND status='running' AND created_at>TIMESTAMP_SUB(CURRENT_TIMESTAMP(),INTERVAL 90 SECOND) AND id!=@id)
                    AS 'An endpoint test is already running';
                MERGE `{table}` t USING (SELECT @id AS id) s ON t.id=s.id
                WHEN NOT MATCHED THEN INSERT(id,environment_id,configuration_revision,runtime_scope,requested_by,created_at,status,result_json)
                    VALUES(@id,@environment,@revision,@runtime,@actor,CURRENT_TIMESTAMP(),'running',@initial);
                SET made=(@@row_count=1); COMMIT TRANSACTION; SELECT made;""", params)
        except Exception as error:
            text = str(error)
            if "An endpoint test is already running" in text:
                raise ValueError("An endpoint test is already running for this environment. Wait for its result") from error
            if "Endpoint configuration changed before testing" in text or "concurrent update" in text.lower():
                raise ValueError("The endpoint or test state changed. Reload or retry the same test key") from error
            raise
        if not reservation or not reservation[0]["made"]:
            existing = get_endpoint_test(repo, target.id, identity)
            if existing.get("questionHash") != question_hash:
                raise ValueError("This test key belongs to another question; start a new test explicitly")
            return existing
        start = time.monotonic()
        diagnostic = {}
        outcome = {"questionHash": question_hash, "protocol": target.protocol, "timeoutSeconds": target.timeout_seconds,
                   "automaticRetries": 0, "feedbackCreated": False, "rcaRun": False,
                   "runtimeScope": runtime_scope()}
        try:
            answer = invoke_agent(target, payload.question, identity, diagnostics=diagnostic)
            outcome.update(status="succeeded", httpStatus=diagnostic.get("httpStatus", 200),
                answerPreview=diagnostic.get("answerPreview", ""), answerCharacters=len(answer["answer"]),
                message="A completed agent answer was returned. This test does not assess correctness or run RCA.")
        except AgentInvocationError as error:
            outcome.update(status="outcome_unknown" if error.code in {"timeout", "network", "outcome_unknown"} else "failed",
                httpStatus=error.http_status or diagnostic.get("httpStatus"), errorCode=error.code, error=error.public_message,
                outcomeUnknown=error.code in {"timeout", "network", "outcome_unknown"})
        except Exception as error:
            logger.error("Endpoint test %s could not complete (%s); no automatic replay", identity, type(error).__name__)
            outcome.update(status="outcome_unknown", outcomeUnknown=True, errorCode="internal",
                error="The endpoint test could not complete. Check the backend logs using this test ID. No automatic replay was made.")
        outcome.update(elapsedMs=round((time.monotonic() - start) * 1000), runtimeIdentity=diagnostic.get("runtimeIdentity"),
            authMode=target.auth, requestsAttempted=int(bool(diagnostic.get("requestStarted"))))
        repo.workflow_query(f"""UPDATE `{table}` SET status=@status,completed_at=CURRENT_TIMESTAMP(),result_json=@result
            WHERE id=@id AND status='running'""", [parameter("status", outcome["status"]), parameter("result", json.dumps(outcome)), parameter("id", identity)])
        return get_endpoint_test(repo, target.id, identity)
    finally:
        _SLOTS.release()
