from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .business_domain import normalize_business_label


UserVerdict = Literal["Correct", "Partially correct", "Incorrect", "Unsafe or misleading", "Not specified"]
Impact = Literal["Low", "Medium", "High"]
AgentEnvironment = Literal["nonprod", "prod", "unknown"]
FeedbackState = Literal[
    "Submitted",
    "Triaged",
    "Evidence review",
    "Review complete",
    "Golden candidate",
    "Approved for dataset",
    "Needs more information",
    "Duplicate",
    "Rejected",
]
PublicFeedbackStatus = Literal[
    "Received",
    "In review",
    "Needs information",
    "Retesting",
    "Awaiting your confirmation",
    "Resolved",
    "Not planned",
    "Duplicate",
]


class FeedbackCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str = Field(default="neo-rules-agent", min_length=1, max_length=200)
    title: str | None = Field(default=None, min_length=1, max_length=120)
    environment: AgentEnvironment = "unknown"
    environment_id: str | None = Field(default=None, min_length=1, max_length=200)
    agent_version: str | None = Field(default=None, max_length=200)
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
    business_domain: str | None = Field(default=None, max_length=100)
    business_subdomain: str | None = Field(default=None, max_length=300)

    @field_validator('business_domain', 'business_subdomain', mode='before')
    @classmethod
    def business_labels(cls, value, info):
        return normalize_business_label(value, domain=info.field_name == 'business_domain')

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
    expected_behavior_verified: bool | None = None
    assigned_reviewer: str | None = Field(default=None, max_length=320)
    claims: list[dict[str, Any]] | None = None
    evidence: list[dict[str, Any]] | None = None
    public_status: PublicFeedbackStatus | None = None
    public_message: str | None = Field(default=None, max_length=2000)
    resolution_summary: str | None = Field(default=None, max_length=4000)
    resolution_version: str | None = Field(default=None, max_length=200)
    environment: AgentEnvironment | None = None
    environment_id: str | None = Field(default=None, min_length=1, max_length=200)
    business_domain: str | None = Field(default=None, max_length=100)
    business_subdomain: str | None = Field(default=None, max_length=300)

    @field_validator('business_domain', 'business_subdomain', mode='before')
    @classmethod
    def business_labels(cls, value, info):
        return normalize_business_label(value, domain=info.field_name == 'business_domain')


class RcaSuggestionResponse(BaseModel):
    feedback_id: str
    suggested_rca: str
    suggested_rca_confidence: float
    rca_subcategory: str | None = None
    rca_rationale: str
    rca_required_claims: list[str] = Field(default_factory=list)
    rca_supported_claims: list[str] = Field(default_factory=list)
    rca_missing_claims: list[str] = Field(default_factory=list)
    rca_contradicted_claims: list[str] = Field(default_factory=list)
    rca_evidence: list[dict[str, Any]] = Field(default_factory=list)
    rca_review_required: bool = True
    rca_auto_accepted: bool = False
    rca_suggestion_status: str
    rca_suggested_at: str | None = None
    rca_evidence_backend: str | None = None
    rca_corpus_version: str | None = None
    rca_retrieval_status: Literal["available", "no_matches", "unavailable"] | None = None
    rca_failure_code: str | None = None
    rca_failure_http_status: int | None = None


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
    domain: str = "Unspecified"
    businessDomain: str = "Unspecified"
    businessSubdomain: str | None = None
    domainSource: str = "unspecified"
    domainConfidence: float | None = None
    domainReason: str | None = None
    domainVerified: bool = False
    domainEvidence: list[dict[str, Any]] = Field(default_factory=list)
    environment: AgentEnvironment = "unknown"
    environmentId: str | None = None
    environmentLabel: str | None = None
    mainEnvironmentId: str | None = None
    mainEnvironmentKind: AgentEnvironment | None = None
    mainEnvironmentLabel: str | None = None
    environmentResult: dict[str, Any] | None = None
    agentVersion: str | None = None
    revision: int = 1
    latestPublishedAttemptId: str | None = None
    reporter: str | None = None
    reportedTime: str
    updatedAt: str | None = None
    publicStatus: PublicFeedbackStatus = "Received"
    publicMessage: str | None = None
    resolutionSummary: str | None = None
    resolutionVersion: str | None = None
    resolvedAt: str | None = None
    assignedReviewer: str | None = None
    groundTruthHint: str | None = None
    expectedBehaviorVerified: bool = False
    impact: str
    tags: list[str] = Field(default_factory=list)
    correlatedReports: list[str] = Field(default_factory=list)
    claims: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    reviewerNotes: str | None = None
    recommendedFix: str | None = None
    runContext: dict[str, Any] = Field(default_factory=dict)
    suggestedRcaRationale: str | None = None
    suggestedRcaSubcategory: str | None = None
    suggestedRcaEvidence: list[dict[str, Any]] = Field(default_factory=list)
    suggestedRcaRequiredClaims: list[str] = Field(default_factory=list)
    suggestedRcaSupportedClaims: list[str] = Field(default_factory=list)
    suggestedRcaMissingClaims: list[str] = Field(default_factory=list)
    suggestedRcaContradictedClaims: list[str] = Field(default_factory=list)
    suggestedRcaReviewRequired: bool | None = None
    suggestedRcaStatus: str | None = None


class FeedbackListResponse(BaseModel):
    items: list[FeedbackRecord]
    total: int
    page: int
    pageSize: int


class MyFeedbackFilterOptions(BaseModel):
    domains: list[str] = Field(default_factory=list)


class FeedbackFilterOptions(MyFeedbackFilterOptions):
    reporters: list[str] = Field(default_factory=list)


class BusinessTaxonomyOptions(BaseModel):
    domains: list[str] = Field(default_factory=list)
    subdomains: dict[str, list[str]] = Field(default_factory=dict)
    allowCustom: bool = True


class PublicFeedbackEvent(BaseModel):
    id: str
    status: PublicFeedbackStatus
    createdAt: str
    message: str


class AnswerReview(BaseModel):
    state: Literal['available', 'already_responded', 'processing', 'no_fresh_answer',
        'outdated_revision', 'different_environment', 'environment_unknown', 'unavailable']
    attemptId: str | None = None
    answerId: str | None = None
    environmentId: str | None = None
    environmentKind: AgentEnvironment = 'unknown'
    environmentLabel: str | None = None
    revision: int = 1
    confirmation: Literal['fixed', 'partially_fixed', 'still_incorrect'] | None = None
    displayAnswerId: str | None = None
    displayAnswerRevision: int | None = None
    userVerdict: str | None = None


class MyFeedbackRecord(BaseModel):
    id: str
    title: str
    feedbackText: str
    question: str | None = None
    agentResponse: str | None = None
    agentId: str = "neo-rules-agent"
    runId: str | None = None
    conversationId: str | None = None
    dataSource: str | None = None
    language: str | None = None
    followUp: str | None = None
    userVerdict: str
    issueCategories: list[str] = Field(default_factory=list)
    impact: Impact = "Medium"
    severity: str = "Med"
    domain: str = "Unspecified"
    businessDomain: str = "Unspecified"
    businessSubdomain: str | None = None
    domainSource: str = "unspecified"
    domainConfidence: float | None = None
    domainReason: str | None = None
    domainVerified: bool = False
    domainEvidence: list[dict[str, Any]] = Field(default_factory=list)
    environment: AgentEnvironment = "unknown"
    environmentId: str | None = None
    environmentLabel: str | None = None
    mainEnvironmentId: str | None = None
    mainEnvironmentKind: AgentEnvironment | None = None
    mainEnvironmentLabel: str | None = None
    environmentResult: dict[str, Any] | None = None
    agentVersion: str | None = None
    revision: int = 1
    latestPublishedAttemptId: str | None = None
    expectedBehavior: str | None = None
    expectedBehaviorVerified: bool = False
    reviewedCause: str | None = None
    reviewedSubdomain: str | None = None
    reviewedDefect: str | None = None
    preliminaryCause: str | None = None
    preliminarySubdomain: str | None = None
    preliminaryDefect: str | None = None
    preliminaryCauseConfidence: float | None = None
    preliminaryCauseRationale: str | None = None
    proposedFix: str | None = None
    legacyContext: dict[str, str] | None = None
    publicStatus: PublicFeedbackStatus
    publicMessage: str | None = None
    submittedAt: str
    updatedAt: str
    resolutionSummary: str | None = None
    resolutionVersion: str | None = None
    resolvedAt: str | None = None
    events: list[PublicFeedbackEvent] = Field(default_factory=list)
    answerReview: AnswerReview | None = None
    canEdit: bool = True


class MyFeedbackListResponse(BaseModel):
    items: list[MyFeedbackRecord]
    total: int
    page: int
    pageSize: int


class MyFeedbackUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str | None = Field(default=None, max_length=20000)
    answer: str | None = Field(default=None, max_length=50000)
    agent_id: str | None = Field(default=None, min_length=1, max_length=200)
    agent_version: str | None = Field(default=None, max_length=200)
    run_id: str | None = Field(default=None, max_length=200)
    conversation_id: str | None = Field(default=None, max_length=200)
    data_source: str | None = Field(default=None, max_length=2000)
    language: str | None = Field(default=None, max_length=100)
    follow_up: str | None = Field(default=None, max_length=4000)
    expected_revision: int | None = Field(default=None, ge=1)
    expected_updated_at: str | None = Field(default=None, max_length=100)
    title: str | None = Field(default=None, min_length=1, max_length=120)
    environment: AgentEnvironment | None = None
    environment_id: str | None = Field(default=None, min_length=1, max_length=200)
    business_domain: str | None = Field(default=None, min_length=1, max_length=100)
    business_subdomain: str | None = Field(default=None, max_length=300)
    feedback_text: str | None = Field(default=None, max_length=10000)
    expected_behavior: str | None = Field(default=None, max_length=10000)
    user_verdict: UserVerdict | None = None
    issue_categories: list[str] | None = Field(default=None, max_length=20)
    impact: Impact | None = None

    @field_validator('business_domain', 'business_subdomain', mode='before')
    @classmethod
    def business_labels(cls, value, info):
        return normalize_business_label(value, domain=info.field_name == 'business_domain')


class MockLoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class RetestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_id: str = Field(min_length=1, max_length=200)
    idempotency_key: str = Field(min_length=8, max_length=200)


class AnswerRcaRetry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer_id: str = Field(min_length=1, max_length=300)
    idempotency_key: str = Field(min_length=8, max_length=200)


class AgentEnvironmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=60)
    kind: Literal["nonprod", "prod"] = "nonprod"
    url: str = Field(default="", max_length=2000)
    protocol: Literal["neo_companion", "quality_json"] = "neo_companion"
    auth: Literal["google_access_token", "google_id_token", "none"] = "google_access_token"
    timeout_seconds: int = Field(default=300, ge=1, le=600)
    enabled: bool = True
    agent_version: str | None = Field(default=None, max_length=200)
    expected_revision: int | None = Field(default=None, ge=1)


class EndpointTestInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    question: str = Field(default="Hello. Please reply with a brief greeting.", min_length=1, max_length=2000)
    expected_revision: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=200)


class PromotionFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: str | None = Field(default=None, max_length=100)
    severity: str | None = Field(default=None, max_length=100)
    verdict: str | None = Field(default=None, max_length=100)
    root_cause: str | None = Field(default=None, max_length=200)
    reporter: str | None = Field(default=None, max_length=320)
    domain: str | None = Field(default=None, max_length=300)
    environment: AgentEnvironment | None = None
    environment_id: str | None = Field(default=None, max_length=200)
    public_status: PublicFeedbackStatus | None = None
    search: str | None = Field(default=None, max_length=2000)


class PromotionSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    feedback_ids: list[str] = Field(default_factory=list, max_length=500)
    all_matching: bool = False
    filters: PromotionFilters = Field(default_factory=PromotionFilters)

    @model_validator(mode="after")
    def selection_is_explicit(self):
        if self.all_matching == bool(self.feedback_ids):
            raise ValueError("Choose explicit feedback IDs or all matching filters, not both")
        if any(not value or len(value) > 200 for value in self.feedback_ids):
            raise ValueError("Invalid feedback ID")
        self.feedback_ids = sorted(set(self.feedback_ids))
        return self


class PromotionCreate(PromotionSelection):
    target_id: str = Field(min_length=1, max_length=200)
    idempotency_key: str = Field(min_length=8, max_length=200)
    selection_token: str = Field(min_length=20, max_length=200)


class AnswerConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    verdict: Literal["fixed", "partially_fixed", "still_incorrect"]
    comment: str = Field(default="", max_length=4000)
    expected_confirmation: Literal['fixed', 'partially_fixed', 'still_incorrect'] | None = None

    @model_validator(mode="after")
    def rejection_needs_context(self) -> "AnswerConfirmation":
        if self.verdict != "fixed" and not self.comment.strip():
            raise ValueError("Tell the review team what is still incorrect")
        return self


class HealthResponse(BaseModel):
    status: str
    bigquery: str
    project: str
    dataset: str
