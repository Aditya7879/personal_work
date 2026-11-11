"""Reviewer configuration and explicit promotion actions; no arbitrary browser endpoints."""
from fastapi import APIRouter, Depends, HTTPException, Request
from google.api_core.exceptions import Aborted, Conflict

from .agent_targets import AgentTarget, validate_environment_target
from .config import settings
from .demo_context import is_demo
from .environment_repository import environment_target, public_environment
from .models import AgentEnvironmentInput, PromotionSelection, PromotionCreate, AnswerRcaRetry, EndpointTestInput


def environment_router(repository) -> APIRouter:
    router = APIRouter()

    def public_batch(batch, user):
        return {**{key: value for key, value in batch.items() if key != "requestHash"},
                "canCancel": batch["requestedBy"] == user.audit_email and batch["counts"]["queued"] > 0}

    @router.get("/api/agent-environments")
    @router.get("/api/my/agent-environments")
    def environments(request: Request, repo=Depends(repository)):
        return [public_environment(row, request.state.user, request.state.user.role == "reviewer") for row in repo.list_agent_environments()]

    @router.post("/api/agent-environments", status_code=201)
    def create_environment(payload: AgentEnvironmentInput, request: Request, repo=Depends(repository)):
        validate_payload(payload)
        try:
            row = repo.save_agent_environment(payload, request.state.user.audit_email)
            return public_environment(row, request.state.user, True)
        except (ValueError, Aborted, Conflict) as exc:
            raise HTTPException(409, str(exc) if isinstance(exc, ValueError) else "Configuration changed; reload before saving") from exc

    @router.patch("/api/agent-environments/{environment_id}")
    def update_environment(environment_id: str, payload: AgentEnvironmentInput, request: Request, repo=Depends(repository)):
        try:
            old = repo.get_agent_environment(environment_id)
            if old["kind"] != payload.kind:
                raise HTTPException(409, "Environment type cannot be changed; create a separate environment instead")
            if payload.expected_revision != int(old["revision"]):
                raise HTTPException(409, "This configuration changed. Reload it before saving")
            validate_payload(payload)
            row = repo.save_agent_environment(payload, request.state.user.audit_email, environment_id)
            return public_environment(row, request.state.user, True)
        except KeyError as exc:
            raise HTTPException(404, "Environment not found") from exc
        except (ValueError, Aborted, Conflict) as exc:
            raise HTTPException(409, str(exc) if isinstance(exc, ValueError) else "Configuration changed; reload before saving") from exc

    def validate_payload(payload):
        try:
            validate_environment_target(AgentTarget("candidate", settings.default_agent_id, payload.kind, payload.name,
                url=payload.url, auth=payload.auth, protocol=payload.protocol, timeout_seconds=payload.timeout_seconds, enabled=payload.enabled))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post("/api/agent-environments/{environment_id}/test")
    def test_endpoint(environment_id: str, payload: EndpointTestInput, request: Request, repo=Depends(repository)):
        from .endpoint_tests import run_endpoint_test
        try:
            row = repo.get_agent_environment(environment_id)
            return run_endpoint_test(repo, row, payload, request.state.user.audit_email)
        except KeyError as exc:
            raise HTTPException(404, "Environment not found") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.get("/api/agent-environments/{environment_id}/tests/{test_id}")
    def endpoint_test_result(environment_id: str, test_id: str, repo=Depends(repository)):
        from .endpoint_tests import get_endpoint_test
        try:
            return get_endpoint_test(repo, environment_id, test_id)
        except KeyError as exc:
            raise HTTPException(404, "Endpoint test not found") from exc

    @router.post("/api/promotions/preview")
    def preview(payload: PromotionSelection, repo=Depends(repository)):
        try:
            return repo.promotion_preview(payload)
        except (ValueError, KeyError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post("/api/promotions", status_code=202)
    def promote(payload: PromotionCreate, request: Request, repo=Depends(repository)):
        try:
            row = repo.get_agent_environment(payload.target_id)
            target = environment_target(row)
            reason = target.blocked_reason(request.state.user)
            if reason:
                raise HTTPException(409, reason)
            if not settings.workflow_worker_enabled and not is_demo():
                raise HTTPException(503, "The workflow worker is disabled; no batch was queued")
            if not is_demo():
                validate_environment_target(target)
            result = repo.create_promotion(payload, row, request.state.user.audit_email)
            if is_demo():
                from .demo_simulation import drain
                drain(repo)
                result=repo.get_promotion(result['id'])
            return public_batch(result, request.state.user)
        except KeyError as exc:
            raise HTTPException(404, "Environment not found") from exc
        except (ValueError, Aborted, Conflict) as exc:
            raise HTTPException(409, str(exc) if isinstance(exc, ValueError) else "Inputs or configuration changed; review and confirm again") from exc

    @router.get("/api/promotions")
    def promotions(request: Request, repo=Depends(repository)):
        return [public_batch(row, request.state.user) for row in repo.list_promotions()]

    @router.post("/api/feedback/{feedback_id}/answer-rca", status_code=202)
    def recheck_saved_answer(feedback_id: str, payload: AnswerRcaRetry, request: Request, repo=Depends(repository)):
        if not settings.workflow_worker_enabled and not is_demo():
            raise HTTPException(503, "The workflow worker is disabled")
        try:
            job=repo.queue_saved_answer_rca(feedback_id,payload.answer_id,request.state.user.audit_email,payload.idempotency_key)
            if is_demo():
                from .demo_simulation import drain
                drain(repo)
                job=repo.get_feedback_job(job['id'])
            return repo.safe_job(job)
        except KeyError as exc:
            raise HTTPException(404, "Saved answer not found for this feedback") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.get("/api/promotions/{batch_id}")
    def promotion(batch_id: str, request: Request, repo=Depends(repository)):
        try:
            return public_batch(repo.get_promotion(batch_id), request.state.user)
        except KeyError as exc:
            raise HTTPException(404, "Promotion not found") from exc

    @router.post("/api/promotions/{batch_id}/cancel")
    def cancel(batch_id: str, request: Request, repo=Depends(repository)):
        try:
            row = repo.get_promotion(batch_id)
            if row["requestedBy"] != request.state.user.audit_email:
                raise HTTPException(403, "Only the requester can cancel the remaining queued items")
            return public_batch(repo.cancel_promotion(batch_id, request.state.user.audit_email), request.state.user)
        except KeyError as exc:
            raise HTTPException(404, "Promotion not found") from exc

    return router
