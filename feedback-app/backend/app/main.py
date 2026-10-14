from __future__ import annotations

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .bigquery import BigQueryRepository
from .config import settings
from .models import (
    EvaluationCreate,
    FeedbackCreate,
    FeedbackListResponse,
    FeedbackRecord,
    GoldenCaseCreate,
    GoldenCaseFromFeedback,
    GoldenDatasetCreate,
    HealthResponse,
    TriageUpdate,
)
from .evaluation import run_evaluation

app = FastAPI(title="Agent Quality Console API", version="0.1.0")
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


@app.get("/healthz", response_model=HealthResponse)
def healthz() -> HealthResponse:
    try:
        BigQueryRepository().ping()
        status = "connected"
    except Exception:
        status = "unavailable"
    return HealthResponse(status="ok", bigquery=status, project=settings.project_id, dataset=settings.dataset)


@app.post("/api/admin/bigquery/init")
def initialize_bigquery(repo: BigQueryRepository = Depends(repository)) -> dict[str, str]:
    repo.ensure_schema()
    return {"status": "initialized", "dataset": repo.dataset_ref}


@app.get("/api/overview")
def overview(repo: BigQueryRepository = Depends(repository)) -> dict[str, Any]:
    return repo.overview()


@app.get("/api/feedback", response_model=FeedbackListResponse)
def list_feedback(
    state: str | None = None,
    severity: str | None = None,
    verdict: str | None = None,
    root_cause: str | None = None,
    search: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    repo: BigQueryRepository = Depends(repository),
) -> FeedbackListResponse:
    items, total = repo.list_feedback(state=state, severity=severity, verdict=verdict, root_cause=root_cause, search=search, page=page, page_size=page_size)
    return FeedbackListResponse(items=items, total=total, page=page, pageSize=page_size)


@app.get("/api/feedback/{feedback_id}", response_model=FeedbackRecord)
def get_feedback(feedback_id: str, repo: BigQueryRepository = Depends(repository)) -> FeedbackRecord:
    record = repo.get_feedback(feedback_id)
    if not record:
        raise HTTPException(status_code=404, detail="Feedback item not found")
    return record


@app.post("/api/feedback", response_model=FeedbackRecord, status_code=201)
def create_feedback(payload: FeedbackCreate, repo: BigQueryRepository = Depends(repository)) -> FeedbackRecord:
    return repo.create_feedback(payload)


@app.patch("/api/feedback/{feedback_id}/triage", response_model=FeedbackRecord)
def update_triage(feedback_id: str, payload: TriageUpdate, repo: BigQueryRepository = Depends(repository)) -> FeedbackRecord:
    record = repo.update_triage(feedback_id, payload)
    if not record:
        raise HTTPException(status_code=404, detail="Feedback item not found")
    return record


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
