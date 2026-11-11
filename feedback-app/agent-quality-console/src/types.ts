export type ViewPath = 
  | 'overview'
  | 'my-feedback'
  | 'feedback-inbox'
  | 'feedback-detail'
  | 'triage-queue'
  | 'golden-datasets'
  | 'evaluation-runs'
  | 'release-comparisons'
  | 'settings';

export type Severity = 'High' | 'Med' | 'Low';
export type FeedbackState = 'Submitted' | 'Triaged' | 'Evidence review' | 'Review complete' | 'Golden candidate' | 'Approved for dataset' | 'Needs more information' | 'Duplicate' | 'Rejected';
export type PublicFeedbackStatus = 'Received' | 'In review' | 'Needs information' | 'Retesting' | 'Awaiting your confirmation' | 'Resolved' | 'Not planned' | 'Duplicate';
export type UserVerdict = 'Correct' | 'Partially correct' | 'Incorrect' | 'Unsafe or misleading' | 'Not specified';

export interface RcaEvidence {
  evidence_id?: string;
  source?: string;
  page?: string | number | null;
  element_id?: string | null;
  element_type?: string | null;
  excerpt?: string;
  context?: string;
  score?: number;
  origin?: string;
  document_id?: string;
  chunk_id?: string;
  chunk_position?: number | null;
  parser_origin?: string | null;
  source_uris?: string[];
  corpus_version?: string | null;
  chunk_content_sha256?: string;
  retrieval_methods?: string[];
  context_start?: number;
  context_end?: number;
}

export interface FeedbackItem {
  id: string;
  title: string;
  excerpt: string;
  fullQuote?: string;
  agentName: string;
  model: string;
  runId: string | null;
  prompt: string;
  generatedAnswer: string;
  highlightedDefect?: string;
  userVerdict: UserVerdict;
  suggestedRca: string;
  suggestedRcaConfidence: number;
  confirmedRca?: string;
  defectSubCategory?: string;
  severity: Severity;
  state: FeedbackState;
  domain?: string;
  businessDomain?: string;
  businessSubdomain?: string | null;
  domainSource?: string;
  domainConfidence?: number | null;
  domainReason?: string | null;
  domainVerified?: boolean;
  domainEvidence?: Array<{ source: string; page?: string | number | null; elementId?: string | null; method?: string }>;
  environment?: 'nonprod' | 'prod' | 'unknown';
  environmentId?: string | null;
  environmentLabel?: string | null;
  mainEnvironmentId?: string | null;
  mainEnvironmentKind?: 'nonprod' | 'prod' | 'unknown' | null;
  mainEnvironmentLabel?: string | null;
  environmentResult?: import('./api/feedbackApi').WorkflowAttempt | null;
  agentVersion?: string | null;
  revision?: number;
  latestPublishedAttemptId?: string | null;
  publicStatus?: PublicFeedbackStatus;
  publicMessage?: string | null;
  resolutionSummary?: string | null;
  resolutionVersion?: string | null;
  resolvedAt?: string | null;
  updatedAt?: string | null;
  reporter: string | null;
  reportedTime: string;
  assignedReviewer?: string;
  groundTruthHint?: string;
  expectedBehaviorVerified?: boolean;
  impact: 'Low' | 'Medium' | 'High';
  tags: string[];
  correlatedReports?: string[];
  claims?: {
    id: string;
    statement: string;
    verdict: 'Supported' | 'Contradicted' | 'Missing';
    linkedEvidence?: string[];
    confidence?: number;
  }[];
  evidence?: {
    id?: string;
    source?: string;
    page?: string | number | null;
    excerpt?: string;
  }[];
  reviewerNotes?: string;
  recommendedFix?: string;
  runContext?: Record<string, unknown>;
  suggestedRcaRationale?: string;
  suggestedRcaSubcategory?: string;
  suggestedRcaEvidence?: RcaEvidence[];
  suggestedRcaRequiredClaims?: string[];
  suggestedRcaSupportedClaims?: string[];
  suggestedRcaMissingClaims?: string[];
  suggestedRcaContradictedClaims?: string[];
  suggestedRcaReviewRequired?: boolean;
  suggestedRcaStatus?: string;
}
