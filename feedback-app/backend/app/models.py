from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


UserVerdict = Literal["Correct", "Partially correct", "Incorrect", "Unsafe or misleading", "Not specified"]
Impact = Literal["Low", "Medium", "High"]
FeedbackState = Literal[
    "Submitted",
    "Triaged",
    "Evidence review",
    "Golden candidate",
    "Approved for dataset",
    "Needs more information",
    "Duplicate",
    "Rejected",
]


class FeedbackCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(default="neo-rules-agent", min_length=1, max_length=200)
    run_id: str | None = Field(default=None, max_length=200)
    conversation_id: str | None = Field(default=None, max_length=200)
    question: str | None = Field(default=None, max_length=20000)
    answer: str | None = Field(default=None, max_length=50000)
    user_verdict: UserVerdict
    issue_categories: list[str] = Field(default_factory=list, max_length=20)
    feedback_text: str = Field(min_length=1, max_length=10000)
    expected_behavior: str | None = Field(default=None, max_length=10000)
    impact: Impact = "Medium"
    reporter: str | None = Field(default=None, max_length=320)
    run_context: dict[str, Any] = Field(default_factory=dict)
    source: str = Field(default="feedback_app", max_length=100)

    @model_validator(mode="after")
    def validate_feedback(self) -> "FeedbackCreate":
        if self.user_verdict != "Correct" and not self.feedback_text.strip():
            raise ValueError("feedback_text is required for non-correct feedback")
        return self


class TriageUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: FeedbackState | None = None
    confirmed_rca: str | None = Field(default=None, max_length=200)
    subcategory: str | None = Field(default=None, max_length=300)
    reviewer_notes: str | None = Field(default=None, max_length=10000)
    recommended_fix: str | None = Field(default=None, max_length=10000)
    expected_behavior: str | None = Field(default=None, max_length=10000)
    assigned_reviewer: str | None = Field(default=None, max_length=320)
    claims: list[dict[str, Any]] | None = None
    evidence: list[dict[str, Any]] | None = None


class GoldenDatasetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=200)
    description: str = Field(default="", max_length=4000)
    owner: str | None = Field(default=None, max_length=320)


class GoldenCaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feedback_id: str | None = None
    title: str = Field(min_length=2, max_length=300)
    question: str = Field(min_length=1, max_length=20000)
    expected_behavior: str = Field(min_length=1, max_length=10000)
    required_claims: list[str] = Field(default_factory=list)
    expected_status: str | None = Field(default=None, max_length=100)
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    curator: str | None = Field(default=None, max_length=320)


class GoldenCaseFromFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str
    expected_behavior: str = Field(min_length=1, max_length=10000)
    required_claims: list[str] = Field(default_factory=list)
    expected_status: str | None = Field(default=None, max_length=100)
    curator: str | None = Field(default=None, max_length=320)


class EvaluationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str
    dataset_version: str | None = None
    label: str | None = Field(default=None, max_length=200)
    mode: Literal["full", "reviewed_cases"] = "full"


class EvaluationRunRecord(BaseModel):
    id: str
    dataset_id: str
    dataset_name: str
    dataset_version: str
    label: str | None = None
    status: Literal["queued", "running", "completed", "failed"]
    total_cases: int = 0
    passed_cases: int = 0
    failed_cases: int = 0
    review_required_cases: int = 0
    pass_rate: float | None = None
    started_at: str | None = None
    completed_at: str | None = None
    error: str | None = None


class FeedbackRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    agentName: str
    model: str
    runId: str | None = None
    conversationId: str | None = None
    prompt: str
    generatedAnswer: str
    title: str
    excerpt: str
    fullQuote: str | None = None
    highlightedDefect: str | None = None
    userVerdict: str
    issueCategories: list[str] = Field(default_factory=list)
    suggestedRca: str | None = None
    suggestedRcaConfidence: float | None = None
    confirmedRca: str | None = None
    defectSubCategory: str | None = None
    severity: str
    state: str
    reporter: str | None = None
    reportedTime: str
    assignedReviewer: str | None = None
    groundTruthHint: str | None = None
    impact: str
    tags: list[str] = Field(default_factory=list)
    correlatedReports: list[str] = Field(default_factory=list)
    claims: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    reviewerNotes: str | None = None
    recommendedFix: str | None = None
    runContext: dict[str, Any] = Field(default_factory=dict)


class FeedbackListResponse(BaseModel):
    items: list[FeedbackRecord]
    total: int
    page: int
    pageSize: int


class HealthResponse(BaseModel):
    status: str
    bigquery: str
    project: str
    dataset: str
