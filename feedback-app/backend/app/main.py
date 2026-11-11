from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Any
import uuid

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.concurrency import run_in_threadpool
from starlette.responses import Response

from .auth import get_request_user, issue_mock_token, list_mock_users, private_demo_presenter
from .bigquery import BigQueryRepository
from .config import settings
from .cache import read_cache
from .document_evidence import close_document_evidence_index, get_document_evidence_index
from .environment_repository import environment_target, public_environment
from .models import (
    EvaluationCreate,
    AgentEnvironment,
    BusinessTaxonomyOptions,
    AnswerConfirmation,
    FeedbackCreate,
    FeedbackFilterOptions,
    FeedbackListResponse,
    FeedbackRecord,
    GoldenCaseCreate,
    GoldenCaseFromFeedback,
    GoldenDatasetCreate,
    HealthResponse,
    MockLoginRequest,
    MyFeedbackFilterOptions,
    MyFeedbackListResponse,
    MyFeedbackRecord,
    MyFeedbackUpdate,
    PublicFeedbackStatus,
    RcaSuggestionResponse,
    RetestCreate,
    TriageUpdate,
)
from .evaluation import run_evaluation
from .root_cause import suggest_root_cause
from .workflow_worker import diagnosis_payload, feedback_worker
from .rca_progress import current_source_answer_id
from .environment_routes import environment_router
from .access_routes import access_router
from .role_demo_routes import role_demo_router
from .role_demo import COOKIE as DEMO_COOKIE,decode_view,require_enabled,require_action
from .demo_context import demo_scope,is_demo
from .demo_simulation import drain as finish_demo_work

@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.workflow_worker_enabled:
        feedback_worker.start()
    yield
    feedback_worker.stop()
    if feedback_worker.thread is None or not feedback_worker.thread.is_alive():
        close_document_evidence_index()


app = FastAPI(title="Agent Quality Console API", version="0.2.0", lifespan=lifespan)

@app.middleware("http")
async def require_api_identity(request: Request, call_next):
    path = request.url.path
    if not path.startswith("/api/") or request.method == "OPTIONS":
        return await call_next(request)
    if path in {"/api/auth/mock-users", "/api/auth/mock-login"}:
        return await call_next(request)
    try:
        user = await run_in_threadpool(get_request_user, request)
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    request.state.real_user=user
    request.state.user=user
    controller_path=path.startswith('/api/demo-admin/')
    marker=request.headers.get('x-feedback-demo-view')
    requested=marker=='1'
    token=request.cookies.get(DEMO_COOKIE)
    try:
        if marker is not None and not requested:raise HTTPException(400,'Invalid demo-view marker')
        if controller_path:
            if settings.role_demo_enabled:
                require_enabled()
                with demo_scope():return await authorized_response(request,call_next,user)
            return await authorized_response(request,call_next,user)
        if token and not requested and not controller_path and path!='/api/auth/me':
            raise HTTPException(409,'Exit demo before accessing the live workspace')
        if requested or(path=='/api/auth/me'and token):
            if not token:raise HTTPException(401,'Demo view expired; choose a demo view again')
            if requested and request.method not in{'GET','HEAD','OPTIONS'}:require_action(request)
            try:selected=await run_in_threadpool(decode_view,user,token)
            except HTTPException as exc:
                if path!='/api/auth/me'or requested or exc.status_code>=500:raise
                response=await authorized_response(request,call_next,user)
                response.delete_cookie(DEMO_COOKIE,httponly=True,secure=settings.demo_frontend_origin.startswith('https://'),samesite='strict',path='/')
                return response
            request.state.user=selected
            with demo_scope():return await authorized_response(request,call_next,selected)
        return await authorized_response(request,call_next,user)
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code,content={'detail':exc.detail})


async def authorized_response(request:Request,call_next,user):
    path=request.url.path
    if not path.startswith("/api/my/") and path != "/api/auth/me" and not path.startswith('/api/demo-admin/') and user.role != "reviewer":
        return JSONResponse(status_code=403, content={"detail": "Reviewer access required"})
    if is_demo() and request.method not in {'GET','HEAD','OPTIONS'} and (
            path.startswith('/api/agent-environments') or path=='/api/admin/bigquery/init' or path=='/api/evaluations'):
        return JSONResponse(status_code=409,content={'detail':'The isolated demo uses fixed sample connections and simulated AI. Live connection, schema and evaluation execution controls are disabled.'})
    cache_paths = {"/api/my/feedback", "/api/my/feedback/filters", "/api/feedback", "/api/feedback/filters",
                   "/api/overview", "/api/golden-datasets", "/api/evaluations", "/api/my/agent-targets", "/api/agent-targets", "/api/my/notifications", "/api/my/business-taxonomy"}
    key = (is_demo(),user.email,user.role,user.presenter_email,getattr(user,'demo_session_scope',None),tuple(sorted(user.feedback_emails)),path,tuple(sorted(request.query_params.multi_items())))
    history_path = path.endswith("/history") and (path.startswith("/api/my/feedback/") or path.startswith("/api/feedback/"))
    cacheable = request.method == "GET" and (path in cache_paths or history_path) and request.headers.get("Cache-Control") != "no-cache"
    if cacheable:
        cached = read_cache.get(key)
        if cached:
            return Response(cached.body, media_type=cached.media_type, headers={"X-Feedback-Cache": "HIT", "Cache-Control": "private, no-store"})
    generation = read_cache.generation
    response = await call_next(request)
    if request.method != "GET":
        read_cache.invalidate()
    if cacheable and response.status_code == 200 and "application/json" in response.headers.get("content-type", ""):
        body = b"".join([chunk async for chunk in response.body_iterator])
        ttl = min(10, settings.read_cache_ttl_seconds) if path == "/api/my/notifications" or history_path else settings.read_cache_ttl_seconds
        read_cache.put(key, body, "application/json", ttl, generation)
        return Response(body, status_code=response.status_code, media_type="application/json", headers={"X-Feedback-Cache": "MISS", "Cache-Control": "private, no-store"})
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.allow_all_origins else list(settings.cors_origins),
    allow_credentials=not settings.allow_all_origins,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["*"],
)


def repository() -> BigQueryRepository:
    try:
        return BigQueryRepository()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"BigQuery is unavailable: {exc}") from exc


app.include_router(environment_router(repository))
app.include_router(access_router)
app.include_router(role_demo_router(repository))


@app.get("/healthz", response_model=HealthResponse)
def healthz() -> HealthResponse:
    try:
        BigQueryRepository().ping()
        status = "connected"
    except Exception:
        status = "unavailable"
    return HealthResponse(status="ok", bigquery=status, project=settings.project_id, dataset=settings.dataset)


@app.get("/api/evidence/status")
def evidence_status() -> dict[str, Any]:
    """Reviewer-only, read-only diagnostics; no credentials or document excerpts."""
    try:
        retriever = get_document_evidence_index()
        if hasattr(retriever, "stats"):
            return retriever.stats()
        return {"backend": retriever.backend_name, "connected": True, "legacyExplicitOptIn": True}
    except Exception:
        return JSONResponse(status_code=503, content={"backend": settings.evidence_backend, "connected": False,
            "detail": "Evidence retrieval is unavailable. Check the backend graph, embedding-model and source-manifest configuration. No automatic local fallback was used."})


@app.get("/api/auth/mock-users")
def get_mock_users(request: Request) -> list[dict[str, str]]:
    presenter = private_demo_presenter(request) if settings.auth_mode == "private_demo" else None
    return list_mock_users(presenter)


@app.post("/api/auth/mock-login")
def mock_login(payload: MockLoginRequest, request: Request) -> dict[str, Any]:
    presenter = private_demo_presenter(request) if settings.auth_mode == "private_demo" else None
    token, user, expires_in = issue_mock_token(payload.email, presenter)
    response = {"accessToken": token, "tokenType": "bearer", "expiresIn": expires_in, "user": user.public_dict()}
    if presenter:
        response["mode"] = "private_demo"
    return response


def preview_may_act_as_owner(user, record: FeedbackRecord) -> bool:
    """A role preview is not a real employee's owner confirmation/edit grant."""
    if not user.presenter_email:
        return True
    reporter = str(record.reporter or "").strip().lower()
    return reporter == user.presenter_email or (reporter == user.email and reporter.endswith("@example.test"))


def require_preview_owner(repo: BigQueryRepository, request: Request, feedback_id: str) -> None:
    user = request.state.user
    if not user.presenter_email:
        return
    if not repo.get_my_feedback(feedback_id, user.feedback_emails):
        raise HTTPException(status_code=404, detail="Feedback item not found")
    record = repo.get_feedback(feedback_id)
    if not record or not preview_may_act_as_owner(user, record):
        raise HTTPException(status_code=403, detail="A demo role cannot edit or confirm on behalf of this feedback's actual reporter")


def demo_submission(payload: FeedbackCreate, user) -> FeedbackCreate:
    if not user.presenter_email:
        return payload
    return payload.model_copy(update={"run_context": {**payload.run_context, "private_demo_presenter": user.presenter_email}})


def capture_environment(payload, repo):
    if isinstance(payload, FeedbackCreate):
        payload = payload.model_copy(update={"run_context": {key: value for key, value in payload.run_context.items() if key not in {"environment_id", "environment_kind", "environment_label"}}})
    if not payload.environment_id:
        return payload
    try:
        row = repo.get_agent_environment(payload.environment_id)
    except KeyError as exc:
        raise HTTPException(422, "Choose an existing agent environment") from exc
    if hasattr(payload, "agent_id") and payload.agent_id and payload.agent_id != row["agent_id"]:
        raise HTTPException(409, "The environment belongs to a different agent")
    updates = {"environment": row["kind"]}
    if isinstance(payload, FeedbackCreate):
        updates["run_context"] = {**payload.run_context, "environment_id": row["id"], "environment_label": row["name"], "environment_kind": row["kind"]}
    return payload.model_copy(update=updates)


@app.get("/api/auth/me")
def current_user(request: Request) -> dict[str, Any]:
    return request.state.user.public_dict()


@app.get("/api/my/feedback", response_model=MyFeedbackListResponse)
def list_my_feedback(
    request: Request,
    search: str | None = None,
    domain: str | None = Query(default=None, min_length=1, max_length=300),
    environment: AgentEnvironment | None = None,
    environment_id: str | None = Query(default=None, max_length=200),
    public_status: PublicFeedbackStatus | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    repo: BigQueryRepository = Depends(repository),
) -> MyFeedbackListResponse:
    if environment_id:
        try:
            repo.get_agent_environment(environment_id)
        except KeyError as exc:
            raise HTTPException(422, "Choose an existing environment") from exc
    records, total = repo.list_my_feedback(
        request.state.user.feedback_emails,
        search=search,
        domain=domain,
        environment=environment,
        **({"environment_id": environment_id} if environment_id else {}),
        public_status=public_status,
        page=page,
        page_size=page_size,
    )
    if request.state.user.presenter_email and not is_demo():
        records = [{**record, "canEdit": False} for record in records]
    return MyFeedbackListResponse(items=[MyFeedbackRecord(**record) for record in records], total=total, page=page, pageSize=page_size)


@app.get("/api/my/feedback/filters", response_model=MyFeedbackFilterOptions)
def my_feedback_filter_options(
    request: Request,
    repo: BigQueryRepository = Depends(repository),
) -> MyFeedbackFilterOptions:
    options = repo.list_feedback_filter_options(reporter=request.state.user.feedback_emails)
    return MyFeedbackFilterOptions(**options)


@app.get('/api/my/business-taxonomy', response_model=BusinessTaxonomyOptions)
def business_taxonomy(request: Request, repo: BigQueryRepository = Depends(repository)) -> BusinessTaxonomyOptions:
    reporter = None if request.state.user.role == 'reviewer' else request.state.user.feedback_emails
    return BusinessTaxonomyOptions(**repo.list_business_taxonomy(reporter=reporter))


@app.get("/api/my/feedback/{feedback_id}", response_model=MyFeedbackRecord)
def get_my_feedback(
    feedback_id: str,
    request: Request,
    repo: BigQueryRepository = Depends(repository),
) -> MyFeedbackRecord:
    record = repo.get_my_feedback(feedback_id, request.state.user.feedback_emails)
    if not record:
        raise HTTPException(status_code=404, detail="Feedback item not found")
    if request.state.user.presenter_email:
        captured = repo.get_feedback(feedback_id)
        record = {**record, "canEdit": bool(record.get("canEdit") and captured and preview_may_act_as_owner(request.state.user, captured))}
    return MyFeedbackRecord(**record)


@app.patch("/api/my/feedback/{feedback_id}", response_model=MyFeedbackRecord)
def update_my_feedback(
    feedback_id: str,
    payload: MyFeedbackUpdate,
    request: Request,
    repo: BigQueryRepository = Depends(repository),
) -> MyFeedbackRecord:
    require_preview_owner(repo, request, feedback_id)
    payload = capture_environment(payload, repo)
    try:
        record = repo.update_my_feedback(
            feedback_id,
            request.state.user.feedback_emails,
            payload,
            actor=request.state.user.audit_email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    finish_demo_work(repo)
    if not record:
        raise HTTPException(status_code=404, detail="Feedback item not found")
    return MyFeedbackRecord(**record)


@app.post("/api/my/feedback", response_model=MyFeedbackRecord, status_code=201)
def create_my_feedback(
    payload: FeedbackCreate,
    request: Request,
    repo: BigQueryRepository = Depends(repository),
) -> MyFeedbackRecord:
    trusted_payload = demo_submission(capture_environment(payload.model_copy(update={"reporter": request.state.user.email}), repo), request.state.user)
    created = repo.create_feedback(trusted_payload)
    repo.enqueue_feedback_job(created, "enrich", request.state.user.audit_email)
    finish_demo_work(repo)
    if is_demo():return MyFeedbackRecord(**repo.get_my_feedback(created.id,request.state.user.feedback_emails))
    return MyFeedbackRecord(**repo._my_feedback_record(created, []))


@app.post("/api/admin/bigquery/init")
def initialize_bigquery(repo: BigQueryRepository = Depends(repository)) -> dict[str, str]:
    repo.ensure_schema()
    return {"status": "initialized", "dataset": repo.dataset_ref}


@app.get("/api/overview")
def overview(environment_id: str | None = Query(default=None, max_length=200), repo: BigQueryRepository = Depends(repository)) -> dict[str, Any]:
    try:
        return repo.overview(environment_id) if environment_id else repo.overview()
    except KeyError as exc:
        raise HTTPException(422, "Choose an existing environment") from exc


@app.get("/api/feedback", response_model=FeedbackListResponse)
def list_feedback(
    state: str | None = None,
    severity: str | None = None,
    verdict: str | None = None,
    root_cause: str | None = None,
    reporter: str | None = Query(default=None, min_length=1, max_length=320),
    domain: str | None = Query(default=None, min_length=1, max_length=300),
    environment: AgentEnvironment | None = None,
    environment_id: str | None = Query(default=None, max_length=200),
    public_status: PublicFeedbackStatus | None = None,
    search: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    repo: BigQueryRepository = Depends(repository),
) -> FeedbackListResponse:
    if environment_id:
        try:
            repo.get_agent_environment(environment_id)
        except KeyError as exc:
            raise HTTPException(422, "Choose an existing environment") from exc
    items, total = repo.list_feedback(
        state=state,
        severity=severity,
        verdict=verdict,
        root_cause=root_cause,
        reporter=reporter,
        domain=domain,
        environment=environment,
        **({"environment_id": environment_id} if environment_id else {}),
        public_status=public_status,
        search=search,
        page=page,
        page_size=page_size,
    )
    return FeedbackListResponse(items=items, total=total, page=page, pageSize=page_size)


@app.get("/api/feedback/filters", response_model=FeedbackFilterOptions)
def feedback_filter_options(repo: BigQueryRepository = Depends(repository)) -> FeedbackFilterOptions:
    return FeedbackFilterOptions(**repo.list_feedback_filter_options(include_reporters=True))


@app.get("/api/feedback/{feedback_id}", response_model=FeedbackRecord)
def get_feedback(feedback_id: str, repo: BigQueryRepository = Depends(repository)) -> FeedbackRecord:
    record = repo.get_feedback(feedback_id)
    if not record:
        raise HTTPException(status_code=404, detail="Feedback item not found")
    return record


@app.post("/api/feedback", response_model=FeedbackRecord, status_code=201)
def create_feedback(payload: FeedbackCreate, request: Request, repo: BigQueryRepository = Depends(repository)) -> FeedbackRecord:
    trusted_payload = demo_submission(capture_environment(payload.model_copy(update={"reporter": payload.reporter or request.state.user.email}), repo), request.state.user)
    created = repo.create_feedback(trusted_payload)
    repo.enqueue_feedback_job(created, "enrich", request.state.user.audit_email)
    finish_demo_work(repo)
    if is_demo():return repo.get_feedback(created.id)
    return created


def accessible_feedback(repo: BigQueryRepository, request: Request, feedback_id: str) -> FeedbackRecord:
    if request.state.user.role == "reviewer":
        record = repo.get_feedback(feedback_id)
    else:
        owned = repo.get_my_feedback(feedback_id, request.state.user.feedback_emails)
        record = repo.get_feedback(feedback_id) if owned else None
    if not record:
        raise HTTPException(status_code=404, detail="Feedback item not found")
    return record


@app.get("/api/agent-targets")
@app.get("/api/my/agent-targets")
def configured_agent_targets(request: Request, repo: BigQueryRepository = Depends(repository)) -> list[dict]:
    try:
        return [{**environment_target(row).public_dict(request.state.user), **{
            "canRetest": public_environment(row, request.state.user)["canRetest"], "reason": public_environment(row, request.state.user)["reason"],
            "environmentId": row["id"], "environmentName": row["name"]}} for row in repo.list_agent_environments()]
    except (ValueError, KeyError):
        raise HTTPException(status_code=503, detail="Agent target configuration is invalid")


@app.get("/api/feedback/{feedback_id}/history")
@app.get("/api/my/feedback/{feedback_id}/history")
def answer_history(feedback_id: str, request: Request, repo: BigQueryRepository = Depends(repository)) -> dict:
    public = request.url.path.startswith("/api/my/")
    try:
        history = repo.feedback_history(feedback_id, request.state.user.feedback_emails if public else None)
        if public and request.state.user.presenter_email:
            record = repo.get_feedback(feedback_id)
            if not record or not preview_may_act_as_owner(request.state.user, record):
                history = {**history, "latestConfirmableAttemptId": None}
        return history
    except KeyError:
        raise HTTPException(status_code=404, detail="Feedback item not found")


@app.post("/api/feedback/{feedback_id}/analysis", status_code=202)
def queue_feedback_analysis(feedback_id: str, request: Request, repo: BigQueryRepository = Depends(repository)) -> dict:
    record = accessible_feedback(repo, request, feedback_id)
    job = repo.enqueue_feedback_job(record, "enrich", request.state.user.audit_email, idempotency_key=uuid.uuid4().hex)
    finish_demo_work(repo)
    if is_demo():job=repo.get_feedback_job(job['id'])
    return repo.safe_job(job)


@app.post("/api/feedback/{feedback_id}/retests", status_code=202)
def queue_retest(feedback_id: str, payload: RetestCreate, request: Request, repo: BigQueryRepository = Depends(repository)) -> dict:
    record = accessible_feedback(repo, request, feedback_id)
    if not record.prompt.strip():
        raise HTTPException(status_code=409, detail="Capture the original question before running a retest")
    try:
        row = repo.get_agent_environment(payload.target_id)
        target = environment_target(row)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=422, detail="Choose a configured environment") from exc
    reason = target.blocked_reason(request.state.user)
    if reason:
        raise HTTPException(status_code=503, detail=reason)
    if target.agent_id != record.agentName:
        raise HTTPException(status_code=409, detail="The selected target belongs to a different agent")
    if not settings.workflow_worker_enabled and not is_demo():
        raise HTTPException(503, "The workflow worker is disabled")
    repo.ensure_environment_schema()
    job = repo.enqueue_feedback_job(record, "retest", request.state.user.audit_email, target.id, target.environment, payload.idempotency_key,
        target_snapshot={"target": asdict(target), "environmentName": row["name"]})
    finish_demo_work(repo)
    if is_demo():job=repo.get_feedback_job(job['id'])
    return repo.safe_job(job)


@app.post("/api/my/feedback/{feedback_id}/retests/{attempt_id}/confirmation", response_model=MyFeedbackRecord)
def confirm_retest(feedback_id: str, attempt_id: str, payload: AnswerConfirmation, request: Request, repo: BigQueryRepository = Depends(repository)) -> MyFeedbackRecord:
    require_preview_owner(repo, request, feedback_id)
    try:
        result=repo.confirm_retest(feedback_id, attempt_id, request.state.user.feedback_emails, request.state.user.audit_email, payload)
        finish_demo_work(repo)
        return MyFeedbackRecord(**result)
    except KeyError:
        raise HTTPException(status_code=404, detail="Shared answer not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.get("/api/my/notifications")
def notifications(request: Request, repo: BigQueryRepository = Depends(repository)) -> list[dict]:
    return repo.list_notifications(request.state.user.feedback_emails)


@app.post("/api/my/notifications/{notification_id}/read", status_code=204)
def read_notification(notification_id: str, request: Request, repo: BigQueryRepository = Depends(repository)) -> Response:
    if request.state.user.presenter_email and not is_demo():
        raise HTTPException(status_code=403, detail="Demo roles do not change another person's saved notification state")
    repo.mark_notification_read(notification_id, request.state.user.feedback_emails)
    return Response(status_code=204)


@app.patch("/api/feedback/{feedback_id}/triage", response_model=FeedbackRecord)
def update_triage(feedback_id: str, payload: TriageUpdate, request: Request, repo: BigQueryRepository = Depends(repository)) -> FeedbackRecord:
    payload = capture_environment(payload, repo)
    try:
        record = repo.update_triage(feedback_id, payload, actor=request.state.user.audit_email)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not record:
        raise HTTPException(status_code=404, detail="Feedback item not found")
    return record


@app.post("/api/feedback/{feedback_id}/root-cause/suggest", response_model=RcaSuggestionResponse)
def suggest_feedback_root_cause(
    feedback_id: str,
    repo: BigQueryRepository = Depends(repository),
) -> RcaSuggestionResponse:
    record = repo.get_feedback(feedback_id)
    if not record:
        raise HTTPException(status_code=404, detail="Feedback item not found")
    suggestion = suggest_root_cause(record.model_dump())
    try:
        answer_id = current_source_answer_id(record)
        repo.ensure_original(record)
        repo.save_version('feedback_rca_versions', 'rca:direct:' + uuid.uuid4().hex, feedback_id,
            diagnosis_payload(suggestion, record, answer_id), answer_id=answer_id)
        updated = repo.update_rca_suggestion(feedback_id, suggestion, expected_revision=record.revision,
            source_answer_id=answer_id, source_question=record.prompt, source_answer=record.generatedAnswer)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Could not persist root-cause suggestion") from exc
    if not updated:
        raise HTTPException(status_code=409, detail='The feedback changed during analysis. Its RCA is retained in history; the current review state was not advanced.')
    return RcaSuggestionResponse(feedback_id=feedback_id, **suggestion)


@app.get("/api/golden-datasets")
def list_golden_datasets(repo: BigQueryRepository = Depends(repository)) -> list[dict[str, Any]]:
    return repo.list_golden_datasets()


@app.post("/api/golden-datasets", status_code=201)
def create_golden_dataset(payload: GoldenDatasetCreate, repo: BigQueryRepository = Depends(repository)) -> dict[str, Any]:
    return repo.create_golden_dataset(payload)


@app.post("/api/golden-datasets/{dataset_id}/versions")
def create_golden_dataset_version(
    dataset_id: str,
    payload: dict[str, str] | None = None,
    repo: BigQueryRepository = Depends(repository),
) -> dict[str, Any]:
    try:
        return repo.create_golden_dataset_version(dataset_id, (payload or {}).get("curator"))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/golden-datasets/{dataset_id}/cases")
def list_golden_cases(
    dataset_id: str,
    version: str | None = None,
    repo: BigQueryRepository = Depends(repository),
) -> list[dict[str, Any]]:
    if not repo.get_golden_dataset(dataset_id):
        raise HTTPException(status_code=404, detail="Golden dataset not found")
    return repo.list_golden_cases(dataset_id, version)


@app.post("/api/golden-datasets/{dataset_id}/cases", status_code=201)
def add_golden_case(
    dataset_id: str,
    payload: GoldenCaseCreate,
    repo: BigQueryRepository = Depends(repository),
) -> dict[str, Any]:
    try:
        return repo.add_golden_case(dataset_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.patch("/api/golden-cases/{case_id}/state")
def set_golden_case_state(
    case_id: str,
    payload: dict[str, str],
    repo: BigQueryRepository = Depends(repository),
) -> dict[str, Any]:
    try:
        result = repo.set_golden_case_state(case_id, payload.get("state", ""), payload.get("curator"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not result:
        raise HTTPException(status_code=404, detail="Golden case not found")
    return result


@app.post("/api/feedback/{feedback_id}/golden-candidate", status_code=201)
def create_feedback_golden_candidate(
    feedback_id: str,
    payload: GoldenCaseFromFeedback,
    repo: BigQueryRepository = Depends(repository),
) -> dict[str, Any]:
    try:
        return repo.approve_feedback_as_golden_case(feedback_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/evaluations", status_code=202)
def create_evaluation(
    payload: EvaluationCreate,
    background_tasks: BackgroundTasks,
    repo: BigQueryRepository = Depends(repository),
) -> dict[str, Any]:
    try:
        run = repo.create_evaluation(payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    background_tasks.add_task(run_evaluation, run["id"])
    return run


@app.get("/api/evaluations")
def list_evaluations(
    limit: int = Query(default=50, ge=1, le=200),
    repo: BigQueryRepository = Depends(repository),
) -> list[dict[str, Any]]:
    return repo.list_evaluations(limit)


@app.get("/api/evaluations/{evaluation_id}")
def get_evaluation(evaluation_id: str, repo: BigQueryRepository = Depends(repository)) -> dict[str, Any]:
    run = repo.get_evaluation(evaluation_id)
    if not run:
        raise HTTPException(status_code=404, detail="Evaluation run not found")
    return run


@app.get("/api/evaluations/{evaluation_id}/cases")
def list_evaluation_cases(evaluation_id: str, repo: BigQueryRepository = Depends(repository)) -> list[dict[str, Any]]:
    if not repo.get_evaluation(evaluation_id):
        raise HTTPException(status_code=404, detail="Evaluation run not found")
    return repo.list_evaluation_cases(evaluation_id)
