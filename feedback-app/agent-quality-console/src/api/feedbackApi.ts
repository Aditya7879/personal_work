import { FeedbackItem, UserVerdict } from '../types';

export type FeedbackSubmission = {
  agent_id?: string;
  run_id?: string;
  conversation_id?: string;
  question?: string;
  answer?: string;
  user_verdict: UserVerdict;
  issue_categories: string[];
  feedback_text: string;
  expected_behavior?: string;
  impact: 'Low' | 'Medium' | 'High';
  reporter?: string;
  run_context?: Record<string, unknown>;
};

export type FeedbackListResponse = {
  items: FeedbackItem[];
  total: number;
  page: number;
  pageSize: number;
};

export type GoldenDatasetRecord = {
  dataset_id: string;
  name: string;
  description?: string;
  owner?: string;
  current_version: string;
  case_count?: number;
  reviewer_count?: number;
  pending_reviews?: number;
  created_at: string;
  updated_at: string;
};

export type GoldenCaseRecord = {
  case_id: string;
  dataset_id: string;
  dataset_version: string;
  feedback_id?: string;
  title: string;
  question: string;
  expected_behavior: string;
  required_claims: string[];
  expected_status?: string;
  evidence_refs: Array<Record<string, unknown>>;
  curator?: string;
  state: string;
  created_at: string;
};

export type EvaluationRunRecord = {
  id: string;
  dataset_id: string;
  dataset_name: string;
  dataset_version: string;
  label?: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  total_cases: number;
  passed_cases: number;
  failed_cases: number;
  review_required_cases: number;
  pass_rate?: number;
  started_at?: string;
  completed_at?: string;
  error?: string;
};

export type EvaluationCaseResultRecord = {
  evaluation_id: string;
  case_id: string;
  result: 'passed' | 'failed' | 'review_required';
  actual_status?: string;
  actual_answer?: string;
  missing_claims: string[];
  created_at: string;
};

export type OverviewMetrics = {
  feedback_total: number;
  feedback_needing_review: number;
  golden_dataset_count: number;
  approved_case_count: number;
  latest_pass_rate?: number | null;
  latest_evaluation_id?: string | null;
};

const apiBase = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '');

function endpoint(path: string): string {
  return `${apiBase}${path}`;
}

async function parseResponse<T>(response: Response): Promise<T> {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof payload.detail === 'string' ? payload.detail : `Request failed (${response.status})`;
    throw new Error(detail);
  }
  return payload as T;
}

export async function listFeedback(params: {
  search?: string;
  state?: string;
  severity?: string;
  verdict?: string;
  rootCause?: string;
  page?: number;
  pageSize?: number;
} = {}): Promise<FeedbackListResponse> {
  const query = new URLSearchParams();
  if (params.search) query.set('search', params.search);
  if (params.state && params.state !== 'All') query.set('state', params.state);
  if (params.severity && params.severity !== 'All') query.set('severity', params.severity);
  if (params.verdict && params.verdict !== 'All') query.set('verdict', params.verdict);
  if (params.rootCause && params.rootCause !== 'All') query.set('root_cause', params.rootCause);
  query.set('page', String(params.page || 1));
  query.set('page_size', String(params.pageSize || 25));
  return parseResponse<FeedbackListResponse>(await fetch(endpoint(`/api/feedback?${query}`)));
}

export async function createFeedback(payload: FeedbackSubmission): Promise<FeedbackItem> {
  return parseResponse<FeedbackItem>(await fetch(endpoint('/api/feedback'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }));
}

export async function updateFeedback(
  id: string,
  updates: Record<string, unknown>,
): Promise<FeedbackItem> {
  return parseResponse<FeedbackItem>(await fetch(endpoint(`/api/feedback/${encodeURIComponent(id)}/triage`), {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates),
  }));
}

export async function listGoldenDatasets(): Promise<GoldenDatasetRecord[]> {
  return parseResponse<GoldenDatasetRecord[]>(await fetch(endpoint('/api/golden-datasets')));
}

export async function createGoldenDataset(payload: { name: string; description?: string; owner?: string }): Promise<GoldenDatasetRecord> {
  return parseResponse<GoldenDatasetRecord>(await fetch(endpoint('/api/golden-datasets'), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }));
}

export async function createGoldenDatasetVersion(datasetId: string): Promise<GoldenDatasetRecord & { copied_cases: number }> {
  return parseResponse<GoldenDatasetRecord & { copied_cases: number }>(await fetch(endpoint(`/api/golden-datasets/${encodeURIComponent(datasetId)}/versions`), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}),
  }));
}

export async function listGoldenCases(datasetId: string, version?: string): Promise<GoldenCaseRecord[]> {
  const query = version ? `?version=${encodeURIComponent(version)}` : '';
  return parseResponse<GoldenCaseRecord[]>(await fetch(endpoint(`/api/golden-datasets/${encodeURIComponent(datasetId)}/cases${query}`)));
}

export async function createGoldenCase(datasetId: string, payload: {
  feedback_id?: string;
  title: string;
  question: string;
  expected_behavior: string;
  required_claims?: string[];
  expected_status?: string;
  evidence_refs?: Array<Record<string, unknown>>;
  curator?: string;
}): Promise<GoldenCaseRecord> {
  return parseResponse<GoldenCaseRecord>(await fetch(endpoint(`/api/golden-datasets/${encodeURIComponent(datasetId)}/cases`), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }));
}

export async function approveFeedbackAsGoldenCase(feedbackId: string, payload: {
  dataset_id: string;
  expected_behavior: string;
  required_claims?: string[];
  expected_status?: string;
  curator?: string;
}): Promise<GoldenCaseRecord> {
  return parseResponse<GoldenCaseRecord>(await fetch(endpoint(`/api/feedback/${encodeURIComponent(feedbackId)}/golden-candidate`), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }));
}

export async function setGoldenCaseState(caseId: string, state: 'approved' | 'rejected', curator?: string): Promise<GoldenCaseRecord> {
  return parseResponse<GoldenCaseRecord>(await fetch(endpoint(`/api/golden-cases/${encodeURIComponent(caseId)}/state`), {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ state, curator }),
  }));
}

export async function listEvaluationRuns(): Promise<EvaluationRunRecord[]> {
  return parseResponse<EvaluationRunRecord[]>(await fetch(endpoint('/api/evaluations')));
}

export async function getOverviewMetrics(): Promise<OverviewMetrics> {
  return parseResponse<OverviewMetrics>(await fetch(endpoint('/api/overview')));
}

export async function createEvaluationRun(payload: {
  dataset_id: string;
  dataset_version?: string;
  label?: string;
  mode?: 'full' | 'reviewed_cases';
}): Promise<EvaluationRunRecord> {
  return parseResponse<EvaluationRunRecord>(await fetch(endpoint('/api/evaluations'), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }));
}

export async function listEvaluationCases(evaluationId: string): Promise<EvaluationCaseResultRecord[]> {
  return parseResponse<EvaluationCaseResultRecord[]>(await fetch(endpoint(`/api/evaluations/${encodeURIComponent(evaluationId)}/cases`)));
}
