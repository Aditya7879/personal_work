"""A resumable, bounded worker; BigQuery leases survive API restarts."""
from __future__ import annotations

import hashlib
import logging
from threading import Event, Thread

from .agent_targets import AgentTarget, get_target, invoke_agent, validate_environment_target
from .agent_errors import AgentInvocationError
from .bigquery import BigQueryRepository
from .business_domain import infer_business_domain
from .config import settings
from .demo_context import is_demo
from .document_evidence import evidence_metadata, get_document_evidence_index
from .models import FeedbackRecord
from .root_cause import assess_correction, suggest_root_cause
from .workflow_repository import now_iso
from .rca_progress import completed_rca, current_source_answer_id

logger = logging.getLogger(__name__)


def source_records(sources: list[dict]) -> list[dict]:
    records = []
    for source in sources[:12]:
        if not isinstance(source, dict):
            continue
        name = str(source.get("source") or source.get("document_name") or "")
        context = str(source.get("context") or source.get("text") or source.get("excerpt") or "")
        if not name or not context:
            continue
        digest = hashlib.sha256(f"{name}:{source.get('page')}:{context}".encode()).hexdigest()[:16]
        records.append({"evidence_id": f"SRC-{digest}", "source": name, "page": source.get("page"),
                        "element_id": source.get("element_id") or source.get("chunk_id"), "context": context[:4000],
                        "excerpt": context[:1200], "origin": "agent_retrieval", "score": 1.0})
    return records


def evidence_for(record: FeedbackRecord, sources: list[dict] | None = None) -> list[dict]:
    evidence = source_records(sources or [])
    if evidence:
        return evidence
    return get_document_evidence_index().search(record.prompt, record.groundTruthHint or "")


def diagnosis_payload(result: dict, record: FeedbackRecord, answer_id: str, configuration_revision: int | None = None) -> dict:
    metadata = {**evidence_metadata(result.get("rca_evidence", [])), **result}
    return {"category": result["suggested_rca"], "defect": result.get("rca_subcategory"),
            "rationale": result["rca_rationale"], "confidence": result["suggested_rca_confidence"],
             "verified": False, "answerId": answer_id, "revision": record.revision, "environment": record.environment,
             "environmentId": record.environmentId, "environmentLabel": record.environmentLabel,
             "configurationRevision": configuration_revision,
             "evidence": result.get("rca_evidence", []), "model": 'demo-simulated' if is_demo() else settings.btap_model,
            "corpusVersion": metadata.get("rca_corpus_version"), "createdAt": now_iso(),
            "evidenceBackend": metadata.get("rca_evidence_backend"),
            "retrievalStatus": metadata.get("rca_retrieval_status"),
             "suggestionStatus": result.get("rca_suggestion_status"),
             "failureCode": result.get("rca_failure_code"), "httpStatus": result.get("rca_failure_http_status"),
            "requiredClaims": result.get("rca_required_claims", []), "remainingClaims": result.get("rca_missing_claims", [])}


def process_feedback_job(repo: BigQueryRepository, job: dict) -> None:
    record = FeedbackRecord(**repo._json_object(job["payload_json"]))
    original = repo.get_version("feedback_answer_versions", f"original:{record.id}") or {}
    captured = original
    capture_id = f"original:{record.id}"
    corrected_id = str(record.runContext.get("submission_answer_id") or "")
    if corrected_id.startswith(f"submission:{record.id}:r"):
        corrected = repo.get_version("feedback_answer_versions", corrected_id)
        if corrected and corrected.get("kind") == "submission_edit" and corrected.get("question") == record.prompt and corrected.get("answer") == record.generatedAnswer:
            captured, capture_id = corrected, corrected_id
    if job["kind"] in {"enrich", "rca"}:
        evidence_unavailable = False
        try:
            evidence = evidence_for(record)
        except Exception as exc:
            logger.warning("Source retrieval unavailable for feedback job %s (%s); no local fallback used", job["id"], type(exc).__name__)
            evidence = []
            evidence_unavailable = True
        if job["kind"] == "enrich" and not evidence_unavailable:
            repo.save_domain_suggestion(record.id, record.revision, infer_business_domain(record.prompt, evidence))
        answer_id = str(record.runContext.get("analysis_answer_id") or capture_id) if job["kind"] == "rca" else capture_id
        if record.generatedAnswer and (answer_id != capture_id or (record.prompt == captured.get("question") and record.generatedAnswer == captured.get('answer'))):
            result = suggest_root_cause(record.model_dump(), evidence_override=evidence, evidence_unavailable=evidence_unavailable)
        else:
            result = {"suggested_rca": "insufficient_evidence", "suggested_rca_confidence": 0,
                      "rca_subcategory": None, "rca_rationale": "The original question/answer pair was not captured or has changed. Supply that context before diagnosing the original answer.",
                      "rca_evidence": [], "rca_review_required": True, "rca_auto_accepted": False,
                      "rca_suggestion_status": "needs_original_answer", "rca_required_claims": [], "rca_supported_claims": [], "rca_missing_claims": [], "rca_contradicted_claims": []}
        retry_metadata = repo._json_object(job.get("target_snapshot_json")) if job.get("target_snapshot_json") else {}
        repo.save_version("feedback_rca_versions", f"rca:{job['id']}", record.id, diagnosis_payload(result, record, answer_id, retry_metadata.get("configurationRevision")), job["id"], answer_id)
        current = repo.get_feedback(record.id)
        current_source = (current and current.revision == record.revision and answer_id == current_source_answer_id(current)
            and answer_id == capture_id and current.prompt == record.prompt and current.generatedAnswer == record.generatedAnswer)
        applied = None
        if current_source:
            applied = repo.update_rca_suggestion(record.id, result, expected_revision=record.revision,
                source_answer_id=answer_id, source_question=record.prompt, source_answer=record.generatedAnswer)
        reason = ('Source evidence retrieval is unavailable; no root cause was inferred. Business classification and original answers are unchanged.' if evidence_unavailable else
            'Source-answer RCA is ready for human review; the diagnosis remains unverified.' if current_source and applied and completed_rca(result) else
            'Analysis finished without a conclusive RCA; the existing review state was not advanced.' if current_source and not completed_rca(result) else
            "Selected-answer RCA is saved in history; the original report's current review state was not changed.")
        repo.complete_feedback_job(job, {'reason':reason,'reviewRequired':True,'appliedToCurrentRevision':bool(applied)})
        return

    snapshot = repo._json_object(job.get("target_snapshot_json")) if job.get("target_snapshot_json") else {}
    if snapshot:
        target = AgentTarget(**snapshot["target"])
        current_target = repo.get_agent_environment(target.id)
        if not current_target.get("enabled") or current_target["kind"] != target.environment:
            raise ValueError("Target environment was disabled or changed")
        validate_environment_target(target)
        if snapshot.get("baseline"):
            captured = snapshot["baseline"]
    else:
        target = get_target(job["target_id"])
    job_kind = snapshot.get("target", {}).get("environment") or job["environment"]
    if target.environment != job_kind or target.agent_id != record.agentName:
        raise ValueError("The configured target no longer matches this attempt")
    answer_id = f"answer:{job['id']}"
    answer = repo.get_version("feedback_answer_versions", answer_id)
    if answer is None:
        if not repo.mark_generation_started(job):
            raise AgentInvocationError("outcome_unknown")
        generated = invoke_agent(target, record.prompt, job["id"], {key: record.runContext[key] for key in ("conversation_history", "region", "language") if key in record.runContext})
        answer = {**generated, "kind": "retest", "question": record.prompt, "environment": target.environment,
                  "agentId": target.agent_id, "revision": record.revision, "createdAt": now_iso(),
                  "environmentId": target.id, "environmentLabel": snapshot.get("environmentName") or target.label,
                  "configurationRevision": target.configuration_version,
                  "batchId": job.get("batch_id"), "baselineAnswerId": captured.get("id") or capture_id}
        repo.save_version("feedback_answer_versions", answer_id, record.id, answer, job["id"])
        answer = repo.get_version("feedback_answer_versions", answer_id) or answer
    repo.set_feedback_job_phase(job, "rca")
    updated = record.model_copy(update={"generatedAnswer": answer["answer"], "environment": target.environment,
        "environmentId": target.id, "environmentLabel": snapshot.get("environmentName") or target.label, "agentVersion": answer.get("agentVersion")})
    evidence_unavailable = False
    try:
        evidence = evidence_for(updated, answer.get("sources"))
    except Exception as exc:
        logger.warning("Source retrieval unavailable for feedback job %s (%s); saved answer retained", job["id"], type(exc).__name__)
        evidence = []
        evidence_unavailable = True
    diagnosis_id = f"rca:{job['id']}"
    if repo.get_version("feedback_rca_versions", diagnosis_id) is None:
        diagnosis = suggest_root_cause(updated.model_dump(), evidence_override=evidence, evidence_unavailable=evidence_unavailable)
        repo.save_version("feedback_rca_versions", diagnosis_id, record.id, diagnosis_payload(diagnosis, updated, answer_id, target.configuration_version), job["id"], answer_id)
    baseline = record.model_copy(update={"prompt": captured.get("question") or "", "generatedAnswer": captured.get("answer") or ""})
    comparison = ({"assessment": "inconclusive", "reason": "No source-environment answer was saved for this input revision. The target answer was assessed independently; no before/after fix is asserted.", "reviewRequired": True}
        if snapshot.get("sourceEnvironmentId") and not snapshot.get("baseline") else
        assess_correction(baseline.model_dump(), updated.model_dump(), evidence, evidence_unavailable=evidence_unavailable))
    repo.complete_feedback_job(job, comparison)


class FeedbackWorker:
    def __init__(self) -> None:
        self.stop_event = Event()
        self.thread: Thread | None = None

    def start(self) -> None:
        if self.thread is not None and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = Thread(target=self.run, name="feedback-workflow", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=1)

    def run(self) -> None:
        while not self.stop_event.is_set():
            job = None
            try:
                repo = BigQueryRepository()
                if repo.reconcile_auto_shared_retest():
                    continue
                job = repo.claim_feedback_job()
                if job:
                    finished = Event()
                    def heartbeat():
                        while not finished.wait(60):
                            try:
                                repo.renew_feedback_lease(job["id"], job["lease_token"])
                            except Exception:
                                logger.warning("Feedback lease renewal failed for %s", job["id"])
                    lease_thread = Thread(target=heartbeat, daemon=True)
                    lease_thread.start()
                    try:
                        process_feedback_job(repo, job)
                    finally:
                        finished.set()
                    continue
            except Exception as exc:
                logger.exception("Feedback workflow job failed%s", f" ({job['id']})" if job else "")
                if job:
                    try:
                        repo.complete_feedback_job(job, error=exc.public_message if isinstance(exc, AgentInvocationError) else "Check failed; inspect worker logs and retry from the review workspace.")
                    except Exception:
                        logger.warning("Could not finalize feedback job %s; its lease can be reclaimed", job["id"])
            self.stop_event.wait(max(5, settings.workflow_poll_seconds))


feedback_worker = FeedbackWorker()
