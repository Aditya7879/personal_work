import { FeedbackItem, RcaEvidence, UserVerdict } from '../types';

export type FeedbackSubmission = {
  environment_id?: string;
  title?: string;
  environment?: AgentEnvironment;
  agent_version?: string;
  agent_id?: string;
  run_id?: string;
  conversation_id?: string;
  question?: string;
  answer?: string;
  business_domain?: string;
  business_subdomain?: string;
  user_verdict: UserVerdict;
  issue_categories: string[];
  feedback_text: string;
  expected_behavior?: string;
  impact: 'Low' | 'Medium' | 'High';
  reporter?: string;
  run_context?: Record<string, unknown>;
};

export type UserRole = 'reporter' | 'reviewer';
export type ApplicationRole = UserRole | 'demo_admin';
export type AuthUser = { email: string; displayName: string; role: UserRole; accessRole?: ApplicationRole; canSwitchDemoViews?: boolean; cacheScope?: string; demoMode?: 'private_demo' | 'demo_admin' };
export type AuthSession = { accessToken: string; user: AuthUser; expiresIn: number; mode?: 'mock' | 'google_iam' | 'private_demo' };
export type AgentEnvironment = 'nonprod' | 'prod' | 'unknown';
export type PublicFeedbackStatus = 'Received' | 'In review' | 'Needs information' | 'Retesting' | 'Awaiting your confirmation' | 'Resolved' | 'Not planned' | 'Duplicate';
export const publicFeedbackStatuses: PublicFeedbackStatus[] = ['Received', 'In review', 'Needs information', 'Retesting', 'Awaiting your confirmation', 'Resolved', 'Not planned', 'Duplicate'];
export type BusinessContext = {
  environmentId?: string | null;
  environmentLabel?: string | null;
  mainEnvironmentId?: string | null;
  mainEnvironmentKind?: AgentEnvironment | null;
  mainEnvironmentLabel?: string | null;
  environmentResult?: WorkflowAttempt | null;
  businessDomain?: string;
  businessSubdomain?: string | null;
  domainSource?: string;
  domainConfidence?: number | null;
  domainReason?: string | null;
  domainVerified?: boolean;
  domainEvidence?: Array<{ source: string; page?: string | number | null; elementId?: string | null; method?: string }>;
  environment?: AgentEnvironment;
  agentVersion?: string | null;
  revision?: number;
  latestPublishedAttemptId?: string | null;
  expectedBehaviorVerified?: boolean;
  publicStatus?: PublicFeedbackStatus;
};
export type MyFeedbackFilterOptions = { domains: string[] };
export type FeedbackFilterOptions = MyFeedbackFilterOptions & { reporters: string[] };
export type BusinessTaxonomyOptions = { domains: string[]; subdomains: Record<string, string[]>; allowCustom: boolean };
export type MyFeedbackEvent = { id: string; status: PublicFeedbackStatus; createdAt: string; message: string };
export type AnswerReview = {
  state: 'available' | 'already_responded' | 'processing' | 'no_fresh_answer' | 'outdated_revision' | 'different_environment' | 'environment_unknown' | 'unavailable';
  attemptId?: string | null; answerId?: string | null; environmentId?: string | null;
  environmentKind: AgentEnvironment; environmentLabel?: string | null; revision: number;
  confirmation?: 'fixed' | 'partially_fixed' | 'still_incorrect' | null;
  userVerdict?: string | null;
  displayAnswerId?: string | null; displayAnswerRevision?: number | null;
};
export type MyFeedbackRecord = BusinessContext & {
  id: string;
  title: string;
  feedbackText: string;
  question?: string | null;
  agentResponse?: string | null;
  agentId?: string;
  runId?: string | null;
  conversationId?: string | null;
  dataSource?: string | null;
  language?: string | null;
  followUp?: string | null;
  userVerdict: string;
  issueCategories: string[];
  impact: 'Low' | 'Medium' | 'High';
  severity: 'High' | 'Med' | 'Low';
  domain: string;
  expectedBehavior?: string | null;
  expectedBehaviorVerified: boolean;
  reviewedCause?: string | null;
  reviewedSubdomain?: string | null;
  reviewedDefect?: string | null;
  preliminaryCause?: string | null;
  preliminarySubdomain?: string | null;
  preliminaryDefect?: string | null;
  preliminaryCauseConfidence?: number | null;
  preliminaryCauseRationale?: string | null;
  proposedFix?: string | null;
  legacyContext?: {
    dataSource?: string;
    subDomain?: string;
    answerStatus?: string;
    followUp?: string;
    priorResolution?: string;
    language?: string;
  } | null;
  canEdit: boolean;
  publicStatus: PublicFeedbackStatus;
  publicMessage?: string | null;
  submittedAt: string;
  updatedAt: string;
  resolutionSummary?: string | null;
  resolutionVersion?: string | null;
  resolvedAt?: string | null;
  events: MyFeedbackEvent[];
  answerReview?: AnswerReview | null;
};
export type MyFeedbackUpdate = {
  environment_id?: string;
  answer?: string;
  agent_id?: string;
  agent_version?: string;
  run_id?: string;
  conversation_id?: string;
  data_source?: string;
  language?: string;
  follow_up?: string;
  expected_revision?: number;
  expected_updated_at?: string;
  title?: string;
  environment?: AgentEnvironment;
  business_domain?: string;
  business_subdomain?: string;
  question?: string;
  feedback_text?: string;
  expected_behavior?: string;
  user_verdict?: UserVerdict;
  issue_categories?: string[];
  impact?: 'Low' | 'Medium' | 'High';
};
export type MyFeedbackListResponse = { items: MyFeedbackRecord[]; total: number; page: number; pageSize: number };
export type MockUser = AuthUser;

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
  scope?: { environmentId?: string | null; environmentName: string; assets: string; evaluations: string; quality: string; reviewProgress: string };
  all_feedback_total?: number; native_feedback_count?: number; promoted_feedback_count?: number; unassigned_feedback_count?: number;
  retest_count?: number; queued_retest_count?: number; running_retest_count?: number; failed_retest_count?: number;
  assessment_breakdown?: Array<{ verdict: string; count: number }>;
  feedback_total: number;
  feedback_needing_review: number;
  golden_dataset_count: number;
  approved_case_count: number;
  rca_runs_count: number;
  auto_classified_count: number;
  rca_review_count: number;
  latest_pass_rate?: number | null;
  latest_evaluation_id?: string | null;
  feedback_trend: Array<{ date: string; feedback_count: number; issue_count: number }>;
  state_breakdown: Array<{ state: string; count: number }>;
  verdict_breakdown: Array<{ verdict: string; count: number }>;
  root_cause_breakdown: Array<{ category: string; count: number; auto_count: number; review_count: number }>;
  subcategory_breakdown: Array<{ category?: string | null; subcategory: string; count: number }>;
  evaluation_trend: Array<{
    evaluation_id: string;
    label?: string | null;
    completed_at: string;
    pass_rate: number;
    passed_cases: number;
    total_cases: number;
  }>;
  recent_feedback: Array<{
    feedback_id: string;
    title: string;
    state: string;
    severity: string;
    user_verdict: string;
    root_cause?: string | null;
    updated_at: string;
  }>;
};

export type RcaSuggestion = {
  feedback_id: string;
  suggested_rca: string;
  suggested_rca_confidence: number;
  rca_subcategory?: string;
  rca_rationale: string;
  rca_required_claims: string[];
  rca_supported_claims: string[];
  rca_missing_claims: string[];
  rca_contradicted_claims: string[];
  rca_evidence: RcaEvidence[];
  rca_review_required: boolean;
  rca_auto_accepted: boolean;
  rca_suggestion_status: string;
  rca_suggested_at?: string | null;
};

const apiBase = (import.meta.env?.VITE_API_URL || '').replace(/\/$/, '');
const authStorageKey = 'agent-quality-auth-v1';
export const sessionExpiredEvent = 'agent-quality-session-expired';
let expiredAccessToken: string | null = null;
// Pin this tab's workspace identity. Another tab changing localStorage must
// never turn a stale demo form into a live-data mutation.
let workspaceSession: AuthSession | undefined;

function sameSession(left: AuthSession | null | undefined, right: AuthSession | null | undefined): boolean {
  return left?.accessToken === right?.accessToken && left?.mode === right?.mode && left?.user.email === right?.user.email && left?.user.cacheScope === right?.user.cacheScope;
}

function changedSession(notify = true): never {
  clearReadCache();
  if (notify && typeof window !== 'undefined') window.dispatchEvent(new Event(sessionExpiredEvent));
  throw new ApiError('Your workspace sign-in or demo view changed. Exit this view or refresh before continuing.', 499);
}

function requestSession(): AuthSession | null {
  const stored = readAuthSession();
  if (workspaceSession && !sameSession(workspaceSession, stored)) changedSession();
  return workspaceSession || stored;
}

export class ApiError extends Error {
  constructor(message: string, public readonly status: number) {
    super(message);
    this.name = 'ApiError';
  }
}

export function isAuthenticationError(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 401 || error.status === 499);
}
const readCache = new Map<string, { expires: number; value: unknown }>();
const pendingReads = new Map<string, Promise<unknown>>();
let cacheEpoch = 0;

export function clearReadCache(): void {
  cacheEpoch += 1;
  readCache.clear();
  pendingReads.clear();
}

async function apiGet<T>(path: string, ttl = 30_000, refresh = false): Promise<T> {
  if (refresh) clearReadCache();
  const session = requestSession();
  if (session?.accessToken && session.accessToken === expiredAccessToken) throw new ApiError('Your session has expired. Sign in again to continue.', 401);
  const scope = `${session?.accessToken || ''}:${session?.user.cacheScope || ''}`;
  const key = `${scope}:${path}`;
  const cached = readCache.get(key);
  if (cached && cached.expires > Date.now()) return cached.value as T;
  const existing = pendingReads.get(key);
  if (existing) return existing as Promise<T>;
  const epoch = cacheEpoch;
  const request = apiFetch(endpoint(path), refresh ? { headers: { 'Cache-Control': 'no-cache' } } : {}).then(parseResponse<T>).then((value) => {
    if (epoch === cacheEpoch && ttl > 0) {
      readCache.set(key, { value, expires: Date.now() + ttl });
      const oldest = readCache.keys().next().value;
      if (readCache.size > 150 && oldest !== undefined) readCache.delete(oldest);
    }
    return value;
  }).finally(() => { if (pendingReads.get(key) === request) pendingReads.delete(key); });
  pendingReads.set(key, request);
  return request;
}

function endpoint(path: string): string {
  return `${apiBase}${path}`;
}

export function readAuthSession(): AuthSession | null {
  try {
    const value = localStorage.getItem(authStorageKey);
    if (!value) return null;
    const session = JSON.parse(value) as AuthSession;
    return (session.accessToken || session.mode === 'google_iam') && session.user?.email && (!session.mode || ['mock', 'google_iam', 'private_demo'].includes(session.mode)) ? session : null;
  } catch {
    return null;
  }
}

export function saveAuthSession(session: AuthSession): void {
  expiredAccessToken = null;
  clearReadCache();
  workspaceSession = session;
  localStorage.setItem(authStorageKey, JSON.stringify(session));
}

export function clearAuthSession(): void {
  expiredAccessToken = null;
  clearReadCache();
  workspaceSession = undefined;
  localStorage.removeItem(authStorageKey);
}

async function apiFetch(url: string, init: RequestInit = {}): Promise<Response> {
  if (init.method && init.method !== 'GET') clearReadCache();
  const headers = new Headers(init.headers);
  if (!headers.has('Accept')) headers.set('Accept', 'application/json');
  const session = requestSession();
  if (session?.mode === 'google_iam') headers.set('X-Requested-With', 'XMLHttpRequest');
  if (session?.user.demoMode === 'demo_admin') headers.set('X-Feedback-Demo-View', '1');
  if (session?.accessToken && session.accessToken === expiredAccessToken) throw new ApiError('Your session has expired. Sign in again to continue.', 401);
  if (session?.accessToken && session.mode === 'private_demo') headers.set('X-Feedback-Demo-Authorization', `Bearer ${session.accessToken}`);
  else if (session?.accessToken && session.mode !== 'google_iam') headers.set('Authorization', `Bearer ${session.accessToken}`);
  if (session?.mode === 'google_iam' && init.method && !['GET', 'HEAD', 'OPTIONS'].includes(init.method.toUpperCase())) headers.set('X-Feedback-CSRF', '1');
  const response = await fetch(url, { ...init, credentials: 'same-origin', headers });
  const current = readAuthSession();
  if (session && !sameSession(current, session)) changedSession(!workspaceSession || !sameSession(workspaceSession, current));
  if ((response.status === 401 || response.status === 403 && session?.user.demoMode === 'demo_admin') && session && (session.mode === 'google_iam' || expiredAccessToken !== session.accessToken)) {
    expiredAccessToken = session.accessToken || null;
    clearReadCache();
    window.dispatchEvent(new Event(sessionExpiredEvent));
  }
  if (init.method && init.method !== 'GET') clearReadCache();
  return response;
}

export async function listMockUsers(): Promise<MockUser[]> {
  return parseResponse<MockUser[]>(await fetch(endpoint('/api/auth/mock-users')));
}

export async function signInAsMockUser(email: string): Promise<AuthSession> {
  const session = await parseResponse<AuthSession>(await fetch(endpoint('/api/auth/mock-login'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  }));
  saveAuthSession(session);
  return session;
}

export async function signInViaPrivateProxy(): Promise<AuthUser> {
  clearAuthSession();
  const user = await getCurrentUser();
  // This is UI/cache state only. Signed Google credentials stay in IAP/the proxy
  // and are never returned to JavaScript or stored in the browser.
  saveAuthSession({ mode: 'google_iam', accessToken: '', user, expiresIn: 0 });
  return user;
}

export async function getGoogleSignInConfig(): Promise<{ managedBrowserSignIn: boolean }> {
  const response = await fetch(endpoint('/auth/config'), { cache: 'no-store', credentials: 'same-origin' });
  if (!response.ok) throw new ApiError('Google sign-in configuration is unavailable', response.status);
  const value = await response.json().catch(() => ({}));
  return { managedBrowserSignIn: value.managedBrowserSignIn === true };
}

export async function getCurrentUser(): Promise<AuthUser> {
  const user = await parseResponse<AuthUser>(await apiFetch(endpoint('/api/auth/me')));
  const session = readAuthSession();
  if (session && session.user.cacheScope !== user.cacheScope) saveAuthSession({ ...session, user });
  return user;
}

async function parseResponse<T>(response: Response): Promise<T> {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = typeof payload.detail === 'string' ? payload.detail : `Request failed (${response.status})`;
    throw new ApiError(response.status === 401 && /invalid or expired|sign in to continue/i.test(detail) ? 'Your session has expired. Sign in again to continue.' : detail, response.status);
  }
  return payload as T;
}

export async function listFeedback(params: {
  search?: string;
  state?: string;
  severity?: string;
  verdict?: string;
  rootCause?: string;
  reporter?: string;
  domain?: string;
  environment?: AgentEnvironment | 'All';
  environmentId?: string | 'All';
  status?: PublicFeedbackStatus | 'All';
  page?: number;
  pageSize?: number;
} = {}): Promise<FeedbackListResponse> {
  const query = new URLSearchParams();
  if (params.search) query.set('search', params.search);
  if (params.state && params.state !== 'All') query.set('state', params.state);
  if (params.severity && params.severity !== 'All') query.set('severity', params.severity);
  if (params.verdict && params.verdict !== 'All') query.set('verdict', params.verdict);
  if (params.rootCause && params.rootCause !== 'All') query.set('root_cause', params.rootCause);
  if (params.reporter && params.reporter !== 'All') query.set('reporter', params.reporter);
  if (params.domain && params.domain !== 'All') query.set('domain', params.domain);
  if (params.environment && params.environment !== 'All') query.set('environment', params.environment);
  if (params.environmentId && params.environmentId !== 'All') query.set('environment_id', params.environmentId);
  if (params.status && params.status !== 'All') query.set('public_status', params.status);
  query.set('page', String(params.page || 1));
  query.set('page_size', String(params.pageSize || 25));
  return apiGet<FeedbackListResponse>(`/api/feedback?${query}`);
}

export async function getFeedbackFilterOptions(): Promise<FeedbackFilterOptions> {
  return apiGet<FeedbackFilterOptions>('/api/feedback/filters', 60_000);
}

export async function getMyFeedbackFilterOptions(): Promise<MyFeedbackFilterOptions> {
  return apiGet<MyFeedbackFilterOptions>('/api/my/feedback/filters', 60_000);
}

export function getBusinessTaxonomyOptions(refresh = false): Promise<BusinessTaxonomyOptions> {
  return apiGet<BusinessTaxonomyOptions>('/api/my/business-taxonomy', 60_000, refresh);
}

export async function getFeedback(feedbackId: string): Promise<FeedbackItem> {
  return apiGet<FeedbackItem>(`/api/feedback/${encodeURIComponent(feedbackId)}`);
}

export async function createFeedback(payload: FeedbackSubmission): Promise<FeedbackItem> {
  return parseResponse<FeedbackItem>(await apiFetch(endpoint('/api/feedback'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }));
}

export async function updateFeedback(
  id: string,
  updates: Record<string, unknown>,
): Promise<FeedbackItem> {
  return parseResponse<FeedbackItem>(await apiFetch(endpoint(`/api/feedback/${encodeURIComponent(id)}/triage`), {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates),
  }));
}

export async function suggestRootCause(feedbackId: string): Promise<RcaSuggestion> {
  return parseResponse<RcaSuggestion>(await apiFetch(endpoint(`/api/feedback/${encodeURIComponent(feedbackId)}/root-cause/suggest`), {
    method: 'POST',
  }));
}

export async function listGoldenDatasets(): Promise<GoldenDatasetRecord[]> {
  return apiGet<GoldenDatasetRecord[]>('/api/golden-datasets');
}

export async function createGoldenDataset(payload: { name: string; description?: string; owner?: string }): Promise<GoldenDatasetRecord> {
  return parseResponse<GoldenDatasetRecord>(await apiFetch(endpoint('/api/golden-datasets'), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }));
}

export async function createGoldenDatasetVersion(datasetId: string): Promise<GoldenDatasetRecord & { copied_cases: number }> {
  return parseResponse<GoldenDatasetRecord & { copied_cases: number }>(await apiFetch(endpoint(`/api/golden-datasets/${encodeURIComponent(datasetId)}/versions`), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}),
  }));
}

export async function listGoldenCases(datasetId: string, version?: string): Promise<GoldenCaseRecord[]> {
  const query = version ? `?version=${encodeURIComponent(version)}` : '';
  return parseResponse<GoldenCaseRecord[]>(await apiFetch(endpoint(`/api/golden-datasets/${encodeURIComponent(datasetId)}/cases${query}`)));
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
  return parseResponse<GoldenCaseRecord>(await apiFetch(endpoint(`/api/golden-datasets/${encodeURIComponent(datasetId)}/cases`), {
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
  return parseResponse<GoldenCaseRecord>(await apiFetch(endpoint(`/api/feedback/${encodeURIComponent(feedbackId)}/golden-candidate`), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }));
}

export async function setGoldenCaseState(caseId: string, state: 'approved' | 'rejected', curator?: string): Promise<GoldenCaseRecord> {
  return parseResponse<GoldenCaseRecord>(await apiFetch(endpoint(`/api/golden-cases/${encodeURIComponent(caseId)}/state`), {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ state, curator }),
  }));
}

export async function listEvaluationRuns(): Promise<EvaluationRunRecord[]> {
  return apiGet<EvaluationRunRecord[]>('/api/evaluations');
}

export async function getOverviewMetrics(refresh = false, environmentId?: string): Promise<OverviewMetrics> {
  const query = environmentId && environmentId !== 'All' ? '?environment_id=' + encodeURIComponent(environmentId) : '';
  return apiGet<OverviewMetrics>('/api/overview' + query, 30_000, refresh);
}

export async function createEvaluationRun(payload: {
  dataset_id: string;
  dataset_version?: string;
  label?: string;
  mode?: 'full' | 'reviewed_cases';
}): Promise<EvaluationRunRecord> {
  return parseResponse<EvaluationRunRecord>(await apiFetch(endpoint('/api/evaluations'), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }));
}

export async function listEvaluationCases(evaluationId: string): Promise<EvaluationCaseResultRecord[]> {
  return parseResponse<EvaluationCaseResultRecord[]>(await apiFetch(endpoint(`/api/evaluations/${encodeURIComponent(evaluationId)}/cases`)));
}

export async function listMyFeedback(params: { search?: string; domain?: string; environment?: AgentEnvironment | 'All'; environmentId?: string; status?: PublicFeedbackStatus | 'All'; page?: number; pageSize?: number } = {}, refresh = false): Promise<MyFeedbackListResponse> {
  const query = new URLSearchParams();
  if (params.search) query.set('search', params.search);
  if (params.domain && params.domain !== 'All') query.set('domain', params.domain);
  if (params.environment && params.environment !== 'All') query.set('environment', params.environment);
  if (params.environmentId && params.environmentId !== 'All') query.set('environment_id', params.environmentId);
  if (params.status && params.status !== 'All') query.set('public_status', params.status);
  query.set('page', String(params.page || 1));
  query.set('page_size', String(params.pageSize || 20));
  return apiGet<MyFeedbackListResponse>(`/api/my/feedback?${query}`, 15_000, refresh);
}

export async function getMyFeedback(feedbackId: string, refresh = false): Promise<MyFeedbackRecord> {
  return apiGet<MyFeedbackRecord>(`/api/my/feedback/${encodeURIComponent(feedbackId)}`, 15_000, refresh);
}

export async function createMyFeedback(payload: FeedbackSubmission): Promise<MyFeedbackRecord> {
  return parseResponse<MyFeedbackRecord>(await apiFetch(endpoint('/api/my/feedback'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }));
}

export async function updateMyFeedback(feedbackId: string, payload: MyFeedbackUpdate): Promise<MyFeedbackRecord> {
  return parseResponse<MyFeedbackRecord>(await apiFetch(endpoint(`/api/my/feedback/${encodeURIComponent(feedbackId)}`), {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }));
}

export type AgentTarget = { id: string; agentId: string; environment: AgentEnvironment; environmentId?: string; environmentName?: string; label: string; configured: boolean; canRetest: boolean; reason?: string | null; agentVersion?: string | null; protocol?: 'quality_json' | 'neo_companion'; timeoutSeconds?: number };
export type WorkflowAttempt = {
  id: string; kind: 'enrich' | 'rca' | 'retest'; status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled';
  environment: AgentEnvironment; environmentId?: string | null; environmentLabel?: string | null; batchId?: string | null;
  phase?: string; revision: number; createdAt: string; sharedAt?: string | null; summary?: string | null;
  configurationRevision?: number | null;
  confirmation?: 'fixed' | 'partially_fixed' | 'still_incorrect' | null;
  userVerdict?: string | null;
  assessment?: 'appears_fixed' | 'still_incorrect' | 'inconclusive' | null; reason?: string | null;
  reviewRequired?: boolean; assessmentVerified?: boolean; automaticallyShared?: boolean; resultAvailable?: boolean;
  error?: string | null; rcaCategory?: string | null; rcaDefect?: string | null;
};
export type AnswerVersion = {
  id: string; attemptId?: string | null; kind: 'original' | 'submission_edit' | 'retest'; question?: string; answer?: string;
  environment: AgentEnvironment; agentVersion?: string | null; modelVersion?: string | null; corpusVersion?: string | null;
  environmentId?: string | null; environmentLabel?: string | null; batchId?: string | null; baselineAnswerId?: string | null;
  configurationRevision?: number | null;
  runId?: string | null; conversationId?: string | null; latencyMs?: number | null; protocol?: string | null;
  sources?: Array<Record<string, unknown>>;
  privateTrace?: { toolCalls?: Array<Record<string, unknown>>; toolResults?: Array<Record<string, unknown>>; messages?: unknown[]; messageCount: number; toolCallCount: number; toolResultCount: number; truncated: boolean };
  revision: number; createdAt: string;
  userVerdict?: string | null;
};
export type DiagnosisVersion = {
  id: string; attemptId?: string | null; answerId: string; category: string; defect?: string | null;
  rationale: string; confidence?: number | null; verified: boolean; environment: AgentEnvironment; createdAt: string;
  environmentId?: string | null; environmentLabel?: string | null;
  configurationRevision?: number | null;
  // Private fields are supplied only by reviewer history, never reporter history.
  evidence?: RcaEvidence[]; evidenceBackend?: string | null; corpusVersion?: string | null;
  retrievalStatus?: 'available' | 'no_matches' | 'unavailable'; suggestionStatus?: string | null;
  requiredClaims?: string[]; remainingClaims?: string[];
};
export type FeedbackHistory = { answers: AnswerVersion[]; diagnoses: DiagnosisVersion[]; attempts: WorkflowAttempt[]; sharingPolicy?: 'automatic'; pendingRetestCount?: number; latestConfirmableAttemptId?: string | null; historyLimit?: number; answerReview?: AnswerReview | null };
export type FeedbackNotification = { id: string; feedbackId: string; attemptId: string; message: string; createdAt: string; readAt?: string | null; environmentId?: string | null };

export function getAgentTargets(reviewer: boolean): Promise<AgentTarget[]> {
  return apiGet<AgentTarget[]>(reviewer ? '/api/agent-targets' : '/api/my/agent-targets');
}

export function getFeedbackHistory(feedbackId: string, reviewer: boolean, refresh = false): Promise<FeedbackHistory> {
  return apiGet<FeedbackHistory>(`/api/${reviewer ? '' : 'my/'}feedback/${encodeURIComponent(feedbackId)}/history`, 8_000, refresh);
}

export async function queueFeedbackAnalysis(feedbackId: string): Promise<WorkflowAttempt> {
  return parseResponse<WorkflowAttempt>(await apiFetch(endpoint(`/api/feedback/${encodeURIComponent(feedbackId)}/analysis`), { method: 'POST' }));
}

export async function queueSavedAnswerRca(feedbackId: string, answerId: string): Promise<WorkflowAttempt> {
  return parseResponse<WorkflowAttempt>(await apiFetch(endpoint(`/api/feedback/${encodeURIComponent(feedbackId)}/answer-rca`), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ answer_id: answerId, idempotency_key: crypto.randomUUID() }),
  }));
}

export async function queueRetest(feedbackId: string, targetId: string): Promise<WorkflowAttempt> {
  return parseResponse<WorkflowAttempt>(await apiFetch(endpoint(`/api/feedback/${encodeURIComponent(feedbackId)}/retests`), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ target_id: targetId, idempotency_key: crypto.randomUUID() }) }));
}

export async function confirmRetest(feedbackId: string, attemptId: string, verdict: 'fixed' | 'partially_fixed' | 'still_incorrect', comment: string, expectedConfirmation?: 'fixed' | 'partially_fixed' | 'still_incorrect' | null): Promise<MyFeedbackRecord> {
  return parseResponse<MyFeedbackRecord>(await apiFetch(endpoint(`/api/my/feedback/${encodeURIComponent(feedbackId)}/retests/${encodeURIComponent(attemptId)}/confirmation`), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ verdict, comment, ...(expectedConfirmation ? { expected_confirmation: expectedConfirmation } : {}) }) }));
}

export function getNotifications(refresh = false): Promise<FeedbackNotification[]> {
  return apiGet<FeedbackNotification[]>('/api/my/notifications', 10_000, refresh);
}

export async function readNotification(id: string): Promise<void> {
  // A presenter may preview a reporter view, but not alter that real reporter's
  // persisted unread state. The dropdown's local demo state can still advance.
  if (readAuthSession()?.mode === 'private_demo') return;
  const response = await apiFetch(endpoint(`/api/my/notifications/${encodeURIComponent(id)}/read`), { method: 'POST' });
  if (!response.ok) await parseResponse(response);
}

export type AgentEnvironmentConfig = {
  id: string; agentId: string; name: string; kind: 'nonprod' | 'prod'; enabled: boolean; revision: number;
  configured: boolean; canRetest: boolean; reason?: string | null; canManage: boolean;
  canActivate?: boolean; activationReason?: string | null; manageReason?: string | null; canTest?: boolean; testReason?: string | null;
  persisted: boolean; accessStatus: 'unverified' | 'not_configured' | 'running' | 'succeeded' | 'failed' | 'outcome_unknown'; updatedAt?: string;
  lastTest?: EndpointTestResult | null;
  url?: string; protocol?: 'neo_companion' | 'quality_json'; auth?: 'google_access_token' | 'google_id_token' | 'none';
  timeoutSeconds?: number; agentVersion?: string | null;
};
export type EnvironmentInput = {
  name: string; kind: 'nonprod' | 'prod'; url: string; protocol: 'neo_companion' | 'quality_json';
  auth: 'google_access_token' | 'google_id_token' | 'none'; timeout_seconds: number; enabled: boolean;
  agent_version?: string | null; expected_revision?: number;
};
export type PromotionFilters = { search?: string; state?: string; severity?: string; verdict?: string; root_cause?: string;
  reporter?: string; domain?: string; environment?: AgentEnvironment; environment_id?: string; public_status?: PublicFeedbackStatus };
export type PromotionSelection = { feedback_ids: string[]; all_matching: boolean; filters: PromotionFilters };
export type PromotionPreview = { count: number; selectionToken: string; items: Array<{ id: string; title: string; revision: number }>; limit: number };
export type PromotionBatch = {
  id: string; targetId: string; targetName: string; sourceEnvironmentId?: string | null; createdAt: string;
  requestedBy: string; total: number; finished: boolean; canCancel: boolean;
  counts: Record<'queued' | 'running' | 'completed' | 'failed' | 'cancelled', number>;
  items: Array<WorkflowAttempt & { feedbackId: string }>;
};
export function getAgentEnvironments(reviewer: boolean, refresh = false): Promise<AgentEnvironmentConfig[]> {
  return apiGet<AgentEnvironmentConfig[]>(`/api/${reviewer ? '' : 'my/'}agent-environments`, 10_000, refresh);
}
export async function saveAgentEnvironment(input: EnvironmentInput, id?: string): Promise<AgentEnvironmentConfig> {
  return parseResponse<AgentEnvironmentConfig>(await apiFetch(endpoint('/api/agent-environments' + (id ? '/' + encodeURIComponent(id) : '')), {
    method: id ? 'PATCH' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input),
  }));
}
export async function previewPromotion(selection: PromotionSelection): Promise<PromotionPreview> {
  return parseResponse<PromotionPreview>(await apiFetch(endpoint('/api/promotions/preview'), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(selection),
  }));
}
export async function createPromotion(selection: PromotionSelection, targetId: string, selectionToken: string, key: string): Promise<PromotionBatch> {
  return parseResponse<PromotionBatch>(await apiFetch(endpoint('/api/promotions'), { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...selection, target_id: targetId, selection_token: selectionToken, idempotency_key: key }),
  }));
}
export function getPromotion(id: string): Promise<PromotionBatch> {
  return apiGet<PromotionBatch>(`/api/promotions/${encodeURIComponent(id)}`, 0, true);
}
export function getPromotions(): Promise<PromotionBatch[]> {
  return apiGet<PromotionBatch[]>('/api/promotions', 0, true);
}
export async function cancelPromotion(id: string): Promise<PromotionBatch> {
  return parseResponse<PromotionBatch>(await apiFetch(endpoint(`/api/promotions/${encodeURIComponent(id)}/cancel`), { method: 'POST' }));
}

export type EndpointTestResult = {
  id: string; environmentId: string; configurationRevision: number; status: 'running' | 'succeeded' | 'failed' | 'outcome_unknown';
  httpStatus?: number | null; elapsedMs?: number; answerPreview?: string; answerCharacters?: number;
  error?: string; errorCode?: string; message?: string; outcomeUnknown?: boolean; automaticRetries?: number;
  runtimeIdentity?: { label: string; principal?: string | null; credentialType?: string }; runtimeScope?: string;
  createdAt: string; completedAt?: string | null;
};
export async function testAgentEndpoint(id: string, revision: number, question: string, key: string): Promise<EndpointTestResult> {
  return parseResponse<EndpointTestResult>(await apiFetch(endpoint(`/api/agent-environments/${encodeURIComponent(id)}/test`), {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ expected_revision: revision, question, idempotency_key: key }),
  }));
}
export function getEndpointTest(id: string, testId: string): Promise<EndpointTestResult> {
  return apiGet<EndpointTestResult>(`/api/agent-environments/${encodeURIComponent(id)}/tests/${encodeURIComponent(testId)}`, 0, true);
}

export type AccessGrant = {
  email: string; displayName: string; role: ApplicationRole; active: boolean; expiresAt: string | null;
  createdAt: string | null; updatedAt: string; updatedBy: string; canEdit: boolean; status: 'active' | 'expired' | 'revoked';
};
export type AccessGrantInput = { email?: string; display_name: string; role: ApplicationRole; active: boolean; expires_at: string | null; expected_updated_at?: string };
export type AccessGrantList = { items: AccessGrant[]; total: number; page: number; pageSize: number; allowedDomains: string[]; propagationSeconds: number };
export type AccessGrantEvent = { id: string; actor: string; action: 'granted' | 'updated' | 'revoked'; createdAt: string; before: AccessGrant | null; after: AccessGrant };

export function listAccessGrants(search = '', page = 1): Promise<AccessGrantList> {
  const query = new URLSearchParams({ search, page: String(page), page_size: '25' });
  return apiGet<AccessGrantList>('/api/access-grants?' + query, 0, true);
}

export async function saveAccessGrant(input: AccessGrantInput, email?: string): Promise<AccessGrant> {
  return parseResponse<AccessGrant>(await apiFetch(endpoint('/api/access-grants' + (email ? '/' + encodeURIComponent(email) : '')), {
    method: email ? 'PATCH' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input),
  }));
}

export function getAccessGrantHistory(email: string): Promise<AccessGrantEvent[]> {
  return apiGet<AccessGrantEvent[]>('/api/access-grants/' + encodeURIComponent(email) + '/history', 0, true);
}
