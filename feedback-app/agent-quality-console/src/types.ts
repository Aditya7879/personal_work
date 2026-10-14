export type ViewPath = 
  | 'overview'
  | 'feedback-inbox'
  | 'feedback-detail'
  | 'triage-queue'
  | 'golden-datasets'
  | 'evaluation-runs'
  | 'release-comparisons'
  | 'settings';

export type Severity = 'High' | 'Med' | 'Low';
export type FeedbackState = 'Submitted' | 'Triaged' | 'Evidence review' | 'Golden candidate' | 'Approved for dataset' | 'Needs more information' | 'Duplicate' | 'Rejected';
export type UserVerdict = 'Correct' | 'Partially correct' | 'Incorrect' | 'Unsafe or misleading' | 'Not specified';

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
  reporter: string | null;
  reportedTime: string;
  assignedReviewer?: string;
  groundTruthHint?: string;
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
    page?: number;
    excerpt?: string;
  }[];
  reviewerNotes?: string;
  recommendedFix?: string;
  runContext?: Record<string, unknown>;
}
