import React, { Suspense, lazy, useEffect, useRef, useState } from 'react';
import { AnimatePresence, useReducedMotion } from 'motion/react';
import { FeedbackItem, ViewPath } from './types';
import {
  AuthUser,
  AgentEnvironment,
  approveFeedbackAsGoldenCase,
  clearAuthSession,
  clearReadCache,
  createEvaluationRun,
  createFeedback,
  createMyFeedback,
  createGoldenCase,
  createGoldenDataset,
  createGoldenDatasetVersion,
  EvaluationRunRecord,
  EvaluationCaseResultRecord,
  FeedbackFilterOptions,
  FeedbackSubmission,
  getFeedback,
  getFeedbackFilterOptions,
  getMyFeedbackFilterOptions,
  getCurrentUser,
  getGoogleSignInConfig,
  getOverviewMetrics,
  isAuthenticationError,
  GoldenCaseRecord,
  GoldenDatasetRecord,
  listEvaluationRuns,
  listEvaluationCases,
  listGoldenCases,
  listGoldenDatasets,
  listFeedback,
  listMockUsers,
  listMyFeedback,
  MockUser,
  MyFeedbackListResponse,
  PublicFeedbackStatus,
  OverviewMetrics,
  setGoldenCaseState,
  readAuthSession,
  saveAuthSession,
  signInAsMockUser,
  signInViaPrivateProxy,
  sessionExpiredEvent,
  queueFeedbackAnalysis,
  updateFeedback,
  AgentEnvironmentConfig,
  getAgentEnvironments,
} from './api/feedbackApi';
import { Header } from './components/Header';
import { MockSignInView } from './components/MockSignInView';
import { PublicHeader } from './components/PublicHeader';
import { Sidebar } from './components/Sidebar';
import { useDebouncedValue } from './utils/useDebouncedValue';
import { Notice, NoticeViewport } from './components/Notice';
import { PrivateAccessView } from './components/PrivateAccessView';
import { shouldShowDemoPicker } from './utils/demoAuth';
import { DemoAdminSession, getDemoAdminSession, logoutDemoAdmin, resetAdminDemo, selectDemoPersona } from './api/demoAdminApi';
import { DemoAdminControls } from './components/DemoAdminControls';
import { DemoViewChooser } from './components/DemoViewChooser';
import { confirmDemoNavigation } from './utils/unsavedDemoDrafts';

const privateIamDeployment = import.meta.env.VITE_AUTH_MODE === 'google_iam';
const privateDemoDeployment = import.meta.env.VITE_AUTH_MODE === 'private_demo';

const FeedbackInboxView = lazy(() => import('./components/FeedbackInboxView').then((module) => ({ default: module.FeedbackInboxView })));
const FeedbackDetailView = lazy(() => import('./components/FeedbackDetailView').then((module) => ({ default: module.FeedbackDetailView })));
const TriageQueueView = lazy(() => import('./components/TriageQueueView').then((module) => ({ default: module.TriageQueueView })));
const GiveFeedbackModal = lazy(() => import('./components/GiveFeedbackModal').then((module) => ({ default: module.GiveFeedbackModal })));
const OverviewView = lazy(() => import('./components/OverviewView').then((module) => ({ default: module.OverviewView })));
const GoldenDatasetsView = lazy(() => import('./components/GoldenDatasetsView').then((module) => ({ default: module.GoldenDatasetsView })));
const EvaluationRunsView = lazy(() => import('./components/EvaluationRunsView').then((module) => ({ default: module.EvaluationRunsView })));
const ReleaseComparisonsView = lazy(() => import('./components/ReleaseComparisonsView').then((module) => ({ default: module.ReleaseComparisonsView })));
const MyFeedbackView = lazy(() => import('./components/MyFeedbackView').then((module) => ({ default: module.MyFeedbackView })));
const SettingsView = lazy(() => import('./components/SettingsView').then((module) => ({ default: module.SettingsView })));

function requestError(error: unknown, fallback: string): string | null {
  return isAuthenticationError(error) ? null : error instanceof Error ? error.message : fallback;
}

function expiredSessionMessage(message: string | null): boolean {
  return Boolean(message && /invalid or expired sign-in token|session has expired|sign in to continue/i.test(message));
}

export default function App() {
  const reducedMotion = useReducedMotion();
  const [activeView, setActiveView] = useState<ViewPath>('overview');
  const [visitedViews, setVisitedViews] = useState<Set<ViewPath>>(() => new Set(['overview']));
  const [authUser, setAuthUser] = useState<AuthUser | null>(null);
  const authUserRef = useRef<AuthUser | null>(authUser);
  authUserRef.current = authUser;
  const [sessionExpired, setSessionExpired] = useState(false);
  const [authLoading, setAuthLoading] = useState(true);
  const [authError, setAuthError] = useState<string | null>(null);
  const [managedBrowserSignIn, setManagedBrowserSignIn] = useState(false);
  const [mockUsers, setMockUsers] = useState<MockUser[]>([]);
  const [demoSession, setDemoSession] = useState<DemoAdminSession | null>(null);
  const [demoBusy, setDemoBusy] = useState(false);
  const [demoChooserOpen, setDemoChooserOpen] = useState(false);
  const [demoError, setDemoError] = useState<string | null>(null);
  const [environments, setEnvironments] = useState<AgentEnvironmentConfig[]>([]);
  const [environmentsLoading, setEnvironmentsLoading] = useState(false);
  const [environmentError, setEnvironmentError] = useState<string | null>(null);
  const [workspaceEnvironmentId, setWorkspaceEnvironmentId] = useState('All');
  const workspaceEnvironmentRef = useRef(workspaceEnvironmentId);
  workspaceEnvironmentRef.current = workspaceEnvironmentId;
  const workspaceEnvironment = environments.find((row) => row.id === workspaceEnvironmentId);
  const environmentRequest = useRef(0);
  const [selectedDetailId, setSelectedDetailId] = useState<string | null>(null);
  const [feedbackItems, setFeedbackItems] = useState<FeedbackItem[]>([]);
  const [feedbackTotal, setFeedbackTotal] = useState(0);
  const [feedbackPage, setFeedbackPage] = useState(1);
  const feedbackPageSize = 25;
  const [feedbackStateFilter, setFeedbackStateFilter] = useState('All');
  const [feedbackSeverityFilter, setFeedbackSeverityFilter] = useState('All');
  const [feedbackVerdictFilter, setFeedbackVerdictFilter] = useState('All');
  const [feedbackRcaFilter, setFeedbackRcaFilter] = useState('All');
  const [feedbackReporterFilter, setFeedbackReporterFilter] = useState('All');
  const [feedbackDomainFilter, setFeedbackDomainFilter] = useState('All');
  const [feedbackEnvironmentFilter, setFeedbackEnvironmentFilter] = useState<AgentEnvironment | 'All'>('All');
  const [feedbackStatusFilter, setFeedbackStatusFilter] = useState<PublicFeedbackStatus | 'All'>('All');
  const [feedbackFilterOptions, setFeedbackFilterOptions] = useState<FeedbackFilterOptions>({ domains: [], reporters: [] });
  const [feedbackFiltersLoading, setFeedbackFiltersLoading] = useState(false);
  const [feedbackFiltersError, setFeedbackFiltersError] = useState<string | null>(null);
  const [feedbackFiltersReload, setFeedbackFiltersReload] = useState(0);
  const [isFeedbackLoading, setIsFeedbackLoading] = useState(true);
  const [isDetailLoading, setIsDetailLoading] = useState(false);
  const [feedbackError, setFeedbackError] = useState<string | null>(null);
  const [isFeedbackModalOpen, setIsFeedbackModalOpen] = useState(false);
  const [globalSearchQuery, setGlobalSearchQuery] = useState('');
  const [datasets, setDatasets] = useState<GoldenDatasetRecord[]>([]);
  const [selectedDatasetId, setSelectedDatasetId] = useState<string | null>(null);
  const [goldenCases, setGoldenCases] = useState<GoldenCaseRecord[]>([]);
  const [isGoldenCasesLoading, setIsGoldenCasesLoading] = useState(false);
  const [evaluationRuns, setEvaluationRuns] = useState<EvaluationRunRecord[]>([]);
  const [selectedEvaluationId, setSelectedEvaluationId] = useState<string | null>(null);
  const [evaluationCaseResults, setEvaluationCaseResults] = useState<EvaluationCaseResultRecord[]>([]);
  const [overviewMetrics, setOverviewMetrics] = useState<OverviewMetrics | null>(null);
  const [overviewLoading, setOverviewLoading] = useState(true);
  const overviewRequest = useRef(0);
  const [qualityLoading, setQualityLoading] = useState(true);
  const [myFeedbackData, setMyFeedbackData] = useState<MyFeedbackListResponse | null>(null);
  const [myFeedbackLoading, setMyFeedbackLoading] = useState(false);
  const [myFeedbackError, setMyFeedbackError] = useState<string | null>(null);
  const [myFeedbackPage, setMyFeedbackPage] = useState(1);
  const [myFeedbackSearch, setMyFeedbackSearch] = useState('');
  const [myFeedbackDomain, setMyFeedbackDomain] = useState('All');
  const [myFeedbackEnvironment, setMyFeedbackEnvironment] = useState<AgentEnvironment | 'All'>('All');
  const [myFeedbackStatus, setMyFeedbackStatus] = useState<PublicFeedbackStatus | 'All'>('All');
  const [myFeedbackReload, setMyFeedbackReload] = useState(0);
  const [myFeedbackOpenRequest, setMyFeedbackOpenRequest] = useState<{ feedbackId: string; sequence: number } | null>(null);
  const feedbackCache = useRef(new Map<string, { items: FeedbackItem[]; total: number; fetchedAt: number }>());
  const myFeedbackCache = useRef(new Map<string, MyFeedbackListResponse>());
  const debouncedReviewerSearch = useDebouncedValue(globalSearchQuery);
  const debouncedMySearch = useDebouncedValue(myFeedbackSearch);
  const feedbackRequestId = useRef(0);
  const goldenCasesCache = useRef(new Map<string, GoldenCaseRecord[]>());

  const openHomeForUser = (user: AuthUser) => {
    setWorkspaceEnvironmentId('All');
    setMyFeedbackOpenRequest(null);
    const home: ViewPath = user.role === 'reporter' ? 'my-feedback' : 'overview';
    setActiveView(home);
    setVisitedViews(new Set([home]));
  };

  const acceptDemoSession = (session: DemoAdminSession) => {
    clearUserWorkspace();
    const user = session.active && session.user ? session.user : session.realUser;
    saveAuthSession({ mode: 'google_iam', accessToken: '', user, expiresIn: 0 });
    authUserRef.current = user;
    setDemoSession(session.active ? session : null);
    setDemoChooserOpen(false); setDemoError(null);
    setAuthUser(user); openHomeForUser(user); setAuthError(null);
  };

  const restoreGoogleUser = async (user: AuthUser) => {
    if (user.demoMode === 'demo_admin') {
      const session = await getDemoAdminSession();
      setDemoSession(session);
      user = session.user || session.realUser;
      saveAuthSession({ mode: 'google_iam', accessToken: '', user, expiresIn: 0 });
    }
    authUserRef.current = user;
    setAuthUser(user); openHomeForUser(user); setAuthError(null);
  };

  useEffect(() => {
    let cancelled = false;
    if (privateIamDeployment) {
      void getGoogleSignInConfig().then((config) => {
        if (!cancelled) setManagedBrowserSignIn(config.managedBrowserSignIn);
        return signInViaPrivateProxy();
      }).then((user) => {
        if (!cancelled) return restoreGoogleUser(user);
      }).catch((error) => { if (!cancelled) setAuthError(error instanceof Error ? error.message : 'Private access is unavailable'); })
        .finally(() => { if (!cancelled) setAuthLoading(false); });
      return () => { cancelled = true; };
    }
    const loadUsers = async () => {
      try {
        setMockUsers(await listMockUsers());
        setAuthError(null);
      } catch (error) {
        if (!cancelled) setAuthError(error instanceof Error ? error.message : 'Mock sign-in is unavailable');
      }
    };
    const storedSession = readAuthSession();
    const startAtPicker = shouldShowDemoPicker(privateIamDeployment, window.location.search, storedSession?.mode);
    if (startAtPicker) clearAuthSession();
    const session = startAtPicker ? null : storedSession;
    if (!session) {
      void loadUsers().finally(() => { if (!cancelled) setAuthLoading(false); });
    } else {
      void getCurrentUser()
        .then((user) => {
          if (!cancelled) {
            setAuthUser(user);
            openHomeForUser(user);
          }
        })
        .catch(async () => {
          clearAuthSession();
          await loadUsers();
        })
        .finally(() => { if (!cancelled) setAuthLoading(false); });
    }
    return () => { cancelled = true; };
  }, []);

  const handleMockSignIn = async (user: MockUser) => {
    setAuthError(null);
    try {
      const session = await signInAsMockUser(user.email);
      setAuthUser(session.user);
      openHomeForUser(session.user);
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : 'Could not sign in');
    }
  };

  const clearUserWorkspace = () => {
    authUserRef.current = null;
    overviewRequest.current += 1;
    environmentRequest.current += 1;
    setEnvironments([]); setEnvironmentError(null); setWorkspaceEnvironmentId('All');
    feedbackRequestId.current += 1;
    clearAuthSession();
    setSessionExpired(false);
    setIsFeedbackModalOpen(false);
    setAuthUser(null);
    setDemoSession(null); setDemoChooserOpen(false); setDemoError(null);
    setActiveView('overview');
    setVisitedViews(new Set());
    setFeedbackItems([]);
    setFeedbackTotal(0);
    setFeedbackPage(1);
    setFeedbackStateFilter('All');
    setFeedbackSeverityFilter('All');
    setFeedbackVerdictFilter('All');
    setFeedbackRcaFilter('All');
    setFeedbackReporterFilter('All');
    setFeedbackDomainFilter('All');
    setFeedbackEnvironmentFilter('All');
    setFeedbackStatusFilter('All');
    setGlobalSearchQuery('');
    setFeedbackFilterOptions({ domains: [], reporters: [] });
    setFeedbackFiltersError(null);
    setSelectedDetailId(null);
    setDatasets([]);
    setSelectedDatasetId(null);
    setEvaluationRuns([]);
    setSelectedEvaluationId(null);
    setEvaluationCaseResults([]);
    setGoldenCases([]);
    setOverviewMetrics(null);
    setFeedbackError(null);
    setMyFeedbackError(null);
    setMyFeedbackData(null);
    setMyFeedbackPage(1);
    setMyFeedbackSearch('');
    setMyFeedbackDomain('All');
    setMyFeedbackEnvironment('All');
    setMyFeedbackStatus('All');
    setMyFeedbackOpenRequest(null);
    feedbackCache.current.clear();
    myFeedbackCache.current.clear();
    goldenCasesCache.current.clear();
  };

  const handleSignOut = () => {
    if (authUserRef.current?.demoMode === 'demo_admin') { void exitDemo(); return; }
    if (!confirmDemoNavigation('Leave your current workspace?')) return;
    clearUserWorkspace();
    if (privateIamDeployment) { setMockUsers([]); setAuthError(null); }
    else void listMockUsers().then(setMockUsers).catch(error => setAuthError(error instanceof Error ? error.message : 'Could not load development test users'));
    if (managedBrowserSignIn) window.location.assign('/?gcp-iap-mode=CLEAR_LOGIN_COOKIE');
  };

  const openDemoChooser = async () => {
    if (demoBusy || !authUserRef.current?.canSwitchDemoViews || !confirmDemoNavigation('Switch the demo view?')) return;
    setDemoBusy(true);
    try { setDemoSession(await getDemoAdminSession()); setDemoError(null); setDemoChooserOpen(true); }
    catch (error) { setFeedbackError(error instanceof Error ? error.message : 'Could not open demo views. You can still exit an expired demo.'); }
    finally { setDemoBusy(false); }
  };

  const switchDemoPersona = async (email: string) => {
    if (demoBusy) return;
    setDemoBusy(true); setDemoError(null);
    try { acceptDemoSession(await selectDemoPersona(email)); }
    catch (error) { setDemoError(error instanceof Error ? error.message : 'Could not switch demo view'); }
    finally { setDemoBusy(false); }
  };

  const exitDemo = async () => {
    if (demoBusy || !confirmDemoNavigation('Exit demo and return to your real Google account?')) return;
    setDemoBusy(true);
    try { acceptDemoSession(await logoutDemoAdmin()); }
    catch (error) { setFeedbackError(error instanceof Error ? error.message : 'Could not exit demo. The current view remains isolated.'); }
    finally { setDemoBusy(false); }
  };

  const resetDemo = async () => {
    if (demoBusy || !confirmDemoNavigation('Reset the isolated demo data?') || !window.confirm('Reset only the isolated demo sample data? Saved demo changes will be removed. Live feedback and user grants will not change.')) return;
    setDemoBusy(true);
    try { const result = await resetAdminDemo(); acceptDemoSession(result.session); }
    catch (error) { setFeedbackError(error instanceof Error ? error.message : 'Could not reset the demo'); }
    finally { setDemoBusy(false); }
  };

  useEffect(() => {
    const onExpired = () => {
      if (!authUserRef.current) return;
      setSessionExpired(true);
      setFeedbackError(null);
      setFeedbackFiltersError(null);
      setMyFeedbackError(null);
    };
    window.addEventListener(sessionExpiredEvent, onExpired);
    const onStorage = (event: StorageEvent) => { if (event.key === 'agent-quality-auth-v1') onExpired(); };
    window.addEventListener('storage', onStorage);
    return () => { window.removeEventListener(sessionExpiredEvent, onExpired); window.removeEventListener('storage', onStorage); };
  }, []);

  const reloadEnvironments = async () => {
    const user = authUserRef.current;
    if (!user) return;
    const sequence = ++environmentRequest.current;
    setEnvironmentsLoading(true);
    try {
      const values = await getAgentEnvironments(user.role === 'reviewer', true);
      if (sequence === environmentRequest.current && authUserRef.current === user) { setEnvironments(values); setEnvironmentError(null); }
    } catch (error) {
      if (sequence === environmentRequest.current) setEnvironmentError(requestError(error, 'Could not load environments'));
    } finally { if (sequence === environmentRequest.current) setEnvironmentsLoading(false); }
  };
  useEffect(() => { if (authUser) void reloadEnvironments(); }, [authUser?.email, authUser?.role, authUser?.cacheScope]);
  const selectWorkspaceEnvironment = (id: string) => {
    // Selecting the shared scope also clears a source-only inbox predicate,
    // including when All environments is already the header's current scope.
    setFeedbackEnvironmentFilter('All'); setMyFeedbackEnvironment('All');
    setFeedbackPage(1); setMyFeedbackPage(1);
    if (id === workspaceEnvironmentRef.current) return;
    feedbackRequestId.current += 1;
    overviewRequest.current += 1;
    workspaceEnvironmentRef.current = id;
    setOverviewMetrics(null); setOverviewLoading(true);
    setWorkspaceEnvironmentId(id);
  };

  useEffect(() => {
    if (expiredSessionMessage(feedbackError) || expiredSessionMessage(feedbackFiltersError) || expiredSessionMessage(myFeedbackError)) {
      setSessionExpired(true);
      if (expiredSessionMessage(feedbackError)) setFeedbackError(null);
      if (expiredSessionMessage(feedbackFiltersError)) setFeedbackFiltersError(null);
      if (expiredSessionMessage(myFeedbackError)) setMyFeedbackError(null);
    }
  }, [feedbackError, feedbackFiltersError, myFeedbackError]);

  const loadFeedback = async (force = false) => {
    const requestId = ++feedbackRequestId.current;
    setFeedbackError(null);
    const query = {
      search: debouncedReviewerSearch,
      state: feedbackStateFilter,
      severity: feedbackSeverityFilter,
      verdict: feedbackVerdictFilter,
      rootCause: feedbackRcaFilter,
      reporter: feedbackReporterFilter,
      domain: feedbackDomainFilter,
      environment: feedbackEnvironmentFilter,
      environmentId: workspaceEnvironmentId,
      status: feedbackStatusFilter,
      page: feedbackPage,
      pageSize: feedbackPageSize,
    };
    const cacheKey = JSON.stringify(query);
    const cached = feedbackCache.current.get(cacheKey);
    if (cached) {
      setFeedbackItems(cached.items);
      setFeedbackTotal(cached.total);
      const cacheIsFresh = Date.now() - cached.fetchedAt < 60_000;
      setIsFeedbackLoading(!cacheIsFresh || force);
      if (!force && cacheIsFresh) return;
    } else {
      setFeedbackItems([]);
      setFeedbackTotal(0);
      setIsFeedbackLoading(true);
    }
    setFeedbackError(null);
    try {
      const response = await listFeedback(query);
      if (requestId !== feedbackRequestId.current) return;
      feedbackCache.current.set(cacheKey, { items: response.items, total: response.total, fetchedAt: Date.now() });
      setFeedbackItems(response.items);
      setFeedbackTotal(response.total);
      setSelectedDetailId((current) => (
        current && response.items.some((item) => item.id === current)
          ? current
          : response.items[0]?.id || null
      ));
    } catch (error) {
      if (requestId === feedbackRequestId.current) setFeedbackError(requestError(error, 'Could not load feedback'));
    } finally {
      if (requestId === feedbackRequestId.current) setIsFeedbackLoading(false);
    }
  };

  useEffect(() => {
    if (authUser?.role !== 'reviewer') return;
    if (activeView !== 'feedback-inbox' && activeView !== 'triage-queue') return;
    void loadFeedback();
  }, [authUser?.email, authUser?.role, authUser?.cacheScope, activeView, debouncedReviewerSearch, feedbackPage, feedbackStateFilter, feedbackSeverityFilter, feedbackVerdictFilter, feedbackRcaFilter, feedbackReporterFilter, feedbackDomainFilter, feedbackEnvironmentFilter, feedbackStatusFilter, workspaceEnvironmentId]);

  const reloadOverview = async (refresh = false) => {
    const user = authUserRef.current;
    if (user?.role !== 'reviewer') return;
    const scope = workspaceEnvironmentRef.current;
    const sequence = ++overviewRequest.current;
    setOverviewLoading(true);
    try {
      const metrics = await getOverviewMetrics(refresh, scope);
      if (sequence === overviewRequest.current && workspaceEnvironmentRef.current === scope && authUserRef.current === user) setOverviewMetrics(metrics);
    } catch (error) {
      if (sequence === overviewRequest.current) setFeedbackError(requestError(error, 'Could not load the selected environment dashboard'));
    } finally { if (sequence === overviewRequest.current) setOverviewLoading(false); }
  };
  useEffect(() => { if (authUserRef.current?.role === 'reviewer') void reloadOverview(); }, [workspaceEnvironmentId]);

  const loadQualityData = async (preferredDatasetId?: string, refresh = false) => {
    const user = authUserRef.current;
    setQualityLoading(true);
    try {
      const [datasetRows, runRows] = await Promise.all([
        listGoldenDatasets(),
        listEvaluationRuns(),
        reloadOverview(refresh),
      ]);
      if (authUserRef.current !== user) return;
      setDatasets(datasetRows);
      setEvaluationRuns(runRows);
      const requestedDatasetId = preferredDatasetId || selectedDatasetId;
      const selected = requestedDatasetId && datasetRows.some((dataset) => dataset.dataset_id === requestedDatasetId)
        ? requestedDatasetId
        : datasetRows[0]?.dataset_id || null;
      setSelectedDatasetId(selected);
    } catch (error) {
      if (authUserRef.current === user) setFeedbackError(requestError(error, 'Could not load quality data'));
    } finally {
      if (authUserRef.current === user) setQualityLoading(false);
    }
  };

  useEffect(() => {
    if (authUser?.role !== 'reviewer') return;
    void loadQualityData();
  }, [authUser?.role, authUser?.cacheScope]);

  useEffect(() => {
    if (!authUser) return;
    let cancelled = false;
    setFeedbackFiltersLoading(true);
    setFeedbackFiltersError(null);
    const request = authUser.role === 'reporter'
      ? getMyFeedbackFilterOptions().then((options) => ({ ...options, reporters: [] }))
      : getFeedbackFilterOptions();
    void request
      .then((options) => { if (!cancelled) setFeedbackFilterOptions(options); })
      .catch((error) => { if (!cancelled) setFeedbackFiltersError(requestError(error, 'Could not load filter choices')); })
      .finally(() => { if (!cancelled) setFeedbackFiltersLoading(false); });
    return () => { cancelled = true; };
  }, [authUser?.email, authUser?.role, authUser?.cacheScope, feedbackFiltersReload]);

  useEffect(() => {
    if (authUser?.role !== 'reporter' || activeView !== 'my-feedback') return;
    let cancelled = false;
    let inFlight = false;
    const key = JSON.stringify([authUser.cacheScope || authUser.email, debouncedMySearch, myFeedbackDomain, myFeedbackEnvironment, myFeedbackStatus, myFeedbackPage, workspaceEnvironmentId]);
    setMyFeedbackData(myFeedbackCache.current.get(key) || null);
    setMyFeedbackLoading(true);
    setMyFeedbackError(null);
    const query = {
      search: debouncedMySearch,
      domain: myFeedbackDomain,
      environment: myFeedbackEnvironment,
      environmentId: workspaceEnvironmentId,
      status: myFeedbackStatus,
      page: myFeedbackPage,
      pageSize: 20,
    };
    const load = async (refresh = false) => {
      if (inFlight || cancelled) return;
      inFlight = true;
      try {
        const response = await listMyFeedback(query, refresh);
        if (!cancelled) { myFeedbackCache.current.set(key, response); setMyFeedbackData(response); setMyFeedbackError(null); }
      } catch (error) { if (!cancelled) setMyFeedbackError(requestError(error, 'Could not load your feedback')); }
      finally { inFlight = false; if (!cancelled) setMyFeedbackLoading(false); }
    };
    void load(true);
    const refreshVisible = () => { if (document.visibilityState === 'visible') void load(true); };
    const timer = window.setInterval(refreshVisible, 30_000);
    window.addEventListener('focus', refreshVisible);
    document.addEventListener('visibilitychange', refreshVisible);
    return () => { cancelled = true; window.clearInterval(timer); window.removeEventListener('focus', refreshVisible); document.removeEventListener('visibilitychange', refreshVisible); };
  }, [authUser?.email, authUser?.role, authUser?.cacheScope, activeView, debouncedMySearch, myFeedbackDomain, myFeedbackEnvironment, myFeedbackStatus, myFeedbackPage, myFeedbackReload, workspaceEnvironmentId]);

  const selectedDatasetVersion = datasets.find((dataset) => dataset.dataset_id === selectedDatasetId)?.current_version || null;

  useEffect(() => {
    if (authUser?.role !== 'reviewer') return;
    if (activeView !== 'golden-datasets' || !selectedDatasetId || !selectedDatasetVersion) return;
    const cacheKey = `${selectedDatasetId}:${selectedDatasetVersion}`;
    const cachedCases = goldenCasesCache.current.get(cacheKey);
    if (cachedCases) {
      setGoldenCases(cachedCases);
      setIsGoldenCasesLoading(false);
      return;
    }

    let cancelled = false;
    setGoldenCases([]);
    setIsGoldenCasesLoading(true);
    void listGoldenCases(selectedDatasetId, selectedDatasetVersion)
      .then((rows) => {
        if (!cancelled) { goldenCasesCache.current.set(cacheKey, rows); setGoldenCases(rows); }
      })
      .catch((error) => {
        if (!cancelled) setFeedbackError(requestError(error, 'Could not load dataset cases'));
      })
      .finally(() => {
        if (!cancelled) setIsGoldenCasesLoading(false);
      });
    return () => { cancelled = true; };
  }, [authUser?.role, authUser?.cacheScope, activeView, selectedDatasetId, selectedDatasetVersion]);

  useEffect(() => {
    if (authUser?.role !== 'reviewer') return;
    if (!selectedEvaluationId) { setEvaluationCaseResults([]); return; }
    let cancelled = false;
    void listEvaluationCases(selectedEvaluationId)
      .then(rows => { if (!cancelled) setEvaluationCaseResults(rows); })
      .catch((error) => { if (!cancelled) setFeedbackError(requestError(error, 'Could not load evaluation case results')); });
    return () => { cancelled = true; };
  }, [authUser?.role, authUser?.cacheScope, selectedEvaluationId]);

  const handleNavigate = (view: ViewPath, targetId?: string) => {
    if (authUser?.role === 'reporter' && view !== 'my-feedback') return;
    setActiveView(view);
    setVisitedViews((previous) => {
      if (previous.has(view)) return previous;
      const next = new Set(previous);
      next.add(view);
      return next;
    });
    if (targetId) {
      setSelectedDetailId(targetId);
      if (view === 'feedback-detail') {
        setIsDetailLoading(true);
        void getFeedback(targetId)
          .then((record) => setFeedbackItems((items) => [record, ...items.filter((item) => item.id !== targetId)]))
          .catch((error) => setFeedbackError(requestError(error, 'Could not load feedback detail')))
          .finally(() => setIsDetailLoading(false));
      }
    }
    window.scrollTo({ top: 0, behavior: reducedMotion ? 'instant' : 'smooth' });
  };

  const handleUpdateItem = async (id: string, updates: Partial<FeedbackItem>) => {
    try {
      const updated = await updateFeedback(id, updates as Record<string, unknown>);
      feedbackCache.current.clear();
      setFeedbackItems((items) => items.map((item) => item.id === id ? updated : item));
    } catch (error) {
      setFeedbackError(requestError(error, 'Could not update feedback'));
    }
  };

  const handleBulkUpdate = async (ids: string[], updates: Record<string, unknown>) => {
    await Promise.all(ids.map((id) => updateFeedback(id, updates)));
    feedbackCache.current.clear();
    await loadFeedback(true);
  };

  const handleSaveTriage = async (id: string, updates: Record<string, unknown>) => {
    const updated = await updateFeedback(id, updates);
    feedbackCache.current.clear();
    setFeedbackItems((items) => items.map((item) => item.id === id ? updated : item));
    void reloadOverview(true);
  };

  const handleNewFeedback = async (submission: FeedbackSubmission) => {
    try {
      if (authUser?.role === 'reporter') {
        await createMyFeedback(submission);
        setFeedbackFiltersReload((value) => value + 1);
        setIsFeedbackModalOpen(false);
        setMyFeedbackPage(1);
        setMyFeedbackReload((value) => value + 1);
        setActiveView('my-feedback');
        setVisitedViews((previous) => new Set([...previous, 'my-feedback']));
        return;
      }
      const created = await createFeedback(submission);
      setFeedbackFiltersReload((value) => value + 1);
      feedbackCache.current.clear();
      setFeedbackItems((items) => [created, ...items]);
      setIsFeedbackModalOpen(false);
      handleNavigate('feedback-detail', created.id);
    } catch (error) {
      if (authUser?.role === 'reporter') {
        setMyFeedbackError(requestError(error, 'Could not submit feedback'));
      } else {
        setFeedbackError(requestError(error, 'Could not submit feedback'));
      }
      throw error;
    }
  };

  const handleSelectDataset = (datasetId: string) => {
    setSelectedDatasetId(datasetId);
  };

  const handleCreateDataset = async (input: { name: string; description?: string }) => {
    const created = await createGoldenDataset(input);
    setDatasets((previous) => [created, ...previous]);
    setSelectedDatasetId(created.dataset_id);
    setGoldenCases([]);
    await reloadOverview(true);
  };

  const handleCreateDatasetVersion = async (datasetId: string) => {
    await createGoldenDatasetVersion(datasetId);
    await loadQualityData();
  };

  const handleCreateGoldenCase = async (datasetId: string, input: {
    title: string; question: string; expected_behavior: string; required_claims: string[]; expected_status?: string;
  }) => {
    const created = await createGoldenCase(datasetId, input);
    const version = datasets.find((dataset) => dataset.dataset_id === datasetId)?.current_version;
    setGoldenCases((previous) => {
      const updated = [created, ...previous];
      if (version) goldenCasesCache.current.set(`${datasetId}:${version}`, updated);
      return updated;
    });
    await loadQualityData();
  };

  const handleSetGoldenCaseState = async (caseId: string, state: 'approved' | 'rejected') => {
    const updated = await setGoldenCaseState(caseId, state);
    const version = datasets.find((dataset) => dataset.dataset_id === updated.dataset_id)?.current_version;
    setGoldenCases((previous) => {
      const cases = previous.map((item) => item.case_id === caseId ? updated : item);
      if (version) goldenCasesCache.current.set(`${updated.dataset_id}:${version}`, cases);
      return cases;
    });
    await loadQualityData();
  };

  const handlePromoteCandidate = async (item: FeedbackItem, datasetId: string) => {
    if (item.state !== 'Review complete' || !item.expectedBehaviorVerified || !item.groundTruthHint?.trim()) {
      throw new Error('Complete evidence review and verify expected behavior before adding this feedback to a dataset.');
    }
    if (!datasetId || !datasets.some((dataset) => dataset.dataset_id === datasetId)) {
      throw new Error('Choose a valid target golden dataset.');
    }
    await approveFeedbackAsGoldenCase(item.id, {
      dataset_id: datasetId,
      expected_behavior: item.groundTruthHint,
      required_claims: item.claims?.map((claim) => claim.statement) || [],
    });
    feedbackCache.current.clear();
    for (const key of goldenCasesCache.current.keys()) {
      if (key.startsWith(`${datasetId}:`)) goldenCasesCache.current.delete(key);
    }
    setSelectedDatasetId(datasetId);
    await Promise.all([loadFeedback(true), loadQualityData(datasetId)]);
  };

  const handleSuggestRootCause = async (feedbackId: string) => {
    await queueFeedbackAnalysis(feedbackId);
    feedbackCache.current.clear();
  };

  const handleStartEvaluation = async (input: {
    dataset_id: string; dataset_version?: string; label?: string; mode: 'full' | 'reviewed_cases';
  }) => {
    const run = await createEvaluationRun(input);
    setEvaluationRuns((previous) => [run, ...previous]);
    setSelectedEvaluationId(run.id);
    await reloadOverview(true);
  };

  const currentDetailItem = feedbackItems.find((item) => item.id === selectedDetailId) || null;

  if (authLoading) {
    return <div className="flex min-h-screen items-center justify-center bg-canvas text-body-sm text-ink-secondary" role="status">Checking sign-in…</div>;
  }
  if (!authUser) {
    if (privateIamDeployment) return <PrivateAccessView error={authError} managedBrowserSignIn={managedBrowserSignIn} onConnect={() => {
      setAuthLoading(true); setAuthError(null);
       void signInViaPrivateProxy().then(restoreGoogleUser)
        .catch((error) => setAuthError(error instanceof Error ? error.message : 'Private access is unavailable'))
        .finally(() => setAuthLoading(false));
    }} />;
    return <><MockSignInView users={mockUsers} loading={false} error={null} onSignIn={handleMockSignIn} privateDemo={privateDemoDeployment} /><NoticeViewport>{authError && <Notice key="sign-in" title="Couldn't sign in" message={authError} onDismiss={() => setAuthError(null)} />}</NoticeViewport></>;
  }

  return (
    <div key={authUser.cacheScope || `${authUser.email}:${authUser.role}`} className="min-h-screen bg-canvas text-ink-primary font-body antialiased flex flex-col">
      <NoticeViewport>
        {environmentError && <Notice key="environments" title="Environment settings unavailable" message={environmentError} onDismiss={() => setEnvironmentError(null)} actionLabel="Try again" onAction={() => void reloadEnvironments()} />}
        {sessionExpired && <Notice key="session" tone="warning" title={authUser.demoMode === 'demo_admin' ? 'Demo view expired or changed' : 'Your session has expired or changed'} message={authUser.demoMode === 'demo_admin' ? 'Demo requests remain isolated and cannot fall back to live data. Exit demo to restore your real Google account.' : 'Refresh or sign in again to continue. Your current view will stay open until you’re ready.'} actionLabel={authUser.demoMode === 'demo_admin' ? 'Exit demo' : 'Sign in again'} onAction={handleSignOut} onDismiss={() => setSessionExpired(false)} />}
        {feedbackError && !expiredSessionMessage(feedbackError) && <Notice key="feedback" title="Something needs your attention" message={feedbackError} onDismiss={() => setFeedbackError(null)} />}
        {feedbackFiltersError && !expiredSessionMessage(feedbackFiltersError) && ['my-feedback', 'feedback-inbox', 'triage-queue'].includes(activeView) && <Notice key="filters" title="Filter choices unavailable" message={feedbackFiltersError} onDismiss={() => setFeedbackFiltersError(null)} />}
        {myFeedbackError && !expiredSessionMessage(myFeedbackError) && activeView === 'my-feedback' && <Notice key="my-feedback" title="Couldn't load your feedback" message={myFeedbackError} onDismiss={() => setMyFeedbackError(null)} />}
      </NoticeViewport>
      {authUser.role === 'reporter' ? (
        <PublicHeader user={authUser} environments={environments} environmentId={workspaceEnvironmentId} environmentsLoading={environmentsLoading} onEnvironmentChange={selectWorkspaceEnvironment} demoMode={!privateIamDeployment} signOutLabel={authUser.demoMode === 'demo_admin' ? 'Exit demo' : managedBrowserSignIn ? 'Switch Google account' : 'Sign out'} onSignOut={handleSignOut} onNewFeedback={() => setIsFeedbackModalOpen(true)} onOpenFeedback={(feedbackId, environmentId) => {
          if (authUserRef.current?.role !== 'reporter') return;
          if (environmentId) selectWorkspaceEnvironment(environmentId);
          handleNavigate('my-feedback');
          setMyFeedbackOpenRequest((previous) => ({ feedbackId, sequence: (previous?.sequence || 0) + 1 }));
        }} />
      ) : (
        <Header
          searchQuery={globalSearchQuery}
          onSearch={(query) => { setFeedbackPage(1); setGlobalSearchQuery(query); }}
          onOpenGiveFeedback={() => setIsFeedbackModalOpen(true)}
          currentUser={authUser}
          demoMode={!privateIamDeployment}
          onSignOut={handleSignOut}
          signOutLabel={authUser.demoMode === 'demo_admin' ? 'Exit demo' : managedBrowserSignIn ? 'Switch Google account' : 'Sign out'}
          environments={environments}
          environmentId={workspaceEnvironmentId}
          environmentsLoading={environmentsLoading}
          onEnvironmentChange={selectWorkspaceEnvironment}
        />
      )}
      <div className="flex flex-1 pt-26 sm:pt-14">
        <Sidebar
          activeView={activeView}
          onNavigate={handleNavigate}
          feedbackCount={overviewMetrics?.feedback_total ?? feedbackTotal}
          role={authUser.role}
        />
        <div className="flex-1 w-full pl-0 sm:pl-60 min-w-0">
          <main className="p-4 sm:p-6 max-w-[1600px] mx-auto">
            {privateIamDeployment && <DemoAdminControls session={demoSession} user={authUser} busy={demoBusy} onSwitch={() => void openDemoChooser()} onReset={() => void resetDemo()} onExit={() => void exitDemo()} />}
            {workspaceEnvironment && activeView !== 'settings' && <p role="note" className="mb-4 rounded-lg border border-surface-border bg-surface px-3 py-2 text-metadata text-ink-secondary">NEO · <strong>{workspaceEnvironment.name}</strong> · {['golden-datasets', 'evaluation-runs', 'release-comparisons'].includes(activeView) ? 'These resources are agent-wide unless explicitly tagged to an environment.' : 'Showing original reports and linked results for this environment. The reported environment and owner are unchanged.'}</p>}
            <PageSlot view="my-feedback" activeView={activeView} visited={visitedViews.has('my-feedback')}>
              <MyFeedbackView
                environmentId={workspaceEnvironment?.id}
                environmentName={workspaceEnvironment?.name}
                data={myFeedbackData}
                loading={myFeedbackLoading}
                page={myFeedbackPage}
                search={myFeedbackSearch}
                domain={myFeedbackDomain}
                environment={myFeedbackEnvironment}
                domains={feedbackFilterOptions.domains}
                filtersLoading={feedbackFiltersLoading}
                status={myFeedbackStatus}
                onPageChange={setMyFeedbackPage}
                onSearchChange={(search) => { setMyFeedbackPage(1); setMyFeedbackSearch(search); }}
                onDomainChange={(domain) => { setMyFeedbackPage(1); setMyFeedbackDomain(domain); }}
                onEnvironmentChange={(environment) => { setMyFeedbackPage(1); setMyFeedbackEnvironment(environment); }}
                onStatusChange={(status) => { setMyFeedbackPage(1); setMyFeedbackStatus(status); }}
                onClearFilters={() => { setMyFeedbackPage(1); setMyFeedbackSearch(''); setMyFeedbackDomain('All'); setMyFeedbackEnvironment('All'); setMyFeedbackStatus('All'); }}
                onDataChanged={() => { clearReadCache(); myFeedbackCache.current.clear(); setMyFeedbackReload((value) => value + 1); setFeedbackFiltersReload((value) => value + 1); }}
                openRequest={myFeedbackOpenRequest}
              />
            </PageSlot>

            <PageSlot view="feedback-inbox" activeView={activeView} visited={visitedViews.has('feedback-inbox')}>
              <FeedbackInboxView
                environments={environments}
                environmentsLoading={environmentsLoading}
                workspaceEnvironmentId={workspaceEnvironment?.id}
                onViewEnvironment={selectWorkspaceEnvironment}
                onPromotionComplete={() => { clearReadCache(); feedbackCache.current.clear(); void loadFeedback(true); void reloadOverview(true); }}
                items={feedbackItems}
                page={feedbackPage}
                pageSize={feedbackPageSize}
                total={feedbackTotal}
                onPageChange={setFeedbackPage}
                isLoading={isFeedbackLoading}
                onNavigate={handleNavigate}
                onOpenGiveFeedback={() => setIsFeedbackModalOpen(true)}
                onBulkUpdate={handleBulkUpdate}
                stateFilter={feedbackStateFilter}
                severityFilter={feedbackSeverityFilter}
                verdictFilter={feedbackVerdictFilter}
                rcaFilter={feedbackRcaFilter}
                reporterFilter={feedbackReporterFilter}
                domainFilter={feedbackDomainFilter}
                environmentFilter={feedbackEnvironmentFilter}
                statusFilter={feedbackStatusFilter}
                filterOptions={feedbackFilterOptions}
                filtersLoading={feedbackFiltersLoading}
                searchQuery={globalSearchQuery}
                onSearchQueryChange={setGlobalSearchQuery}
                onFiltersChange={(filters) => {
                  setFeedbackPage(1);
                  setFeedbackStateFilter(filters.state);
                  setFeedbackSeverityFilter(filters.severity);
                  setFeedbackVerdictFilter(filters.verdict);
                  setFeedbackRcaFilter(filters.rootCause);
                  setFeedbackReporterFilter(filters.reporter);
                  setFeedbackDomainFilter(filters.domain);
                  setFeedbackEnvironmentFilter(filters.environment);
                  setFeedbackStatusFilter(filters.status);
                }}
              />
            </PageSlot>
            <PageSlot view="feedback-detail" activeView={activeView} visited={visitedViews.has('feedback-detail')}>
              {isDetailLoading && !currentDetailItem ? <PageLoading /> : currentDetailItem ? <FeedbackDetailView
                key={currentDetailItem.id}
                environmentId={workspaceEnvironment?.id}
                environmentName={workspaceEnvironment?.name}
                item={currentDetailItem}
                datasets={datasets}
                onNavigate={handleNavigate}
                onPromoteToCandidate={handlePromoteCandidate}
                onSaveTriage={handleSaveTriage}
                onSuggestRootCause={handleSuggestRootCause}
                onDataChanged={async () => { clearReadCache(); const updated = await getFeedback(currentDetailItem.id); feedbackCache.current.clear(); setFeedbackItems((items) => items.map((item) => item.id === updated.id ? updated : item)); setFeedbackFiltersReload((value) => value + 1); }}
              /> : <DisconnectedView title="Select a feedback item to inspect" />}
            </PageSlot>
            <PageSlot view="triage-queue" activeView={activeView} visited={visitedViews.has('triage-queue')}>
              <TriageQueueView
                items={feedbackItems}
                isLoading={isFeedbackLoading}
                onNavigate={handleNavigate}
                onUpdateItem={handleUpdateItem}
                onSaveRca={handleSaveTriage}
                onSuggestRca={handleSuggestRootCause}
              />
            </PageSlot>
            <PageSlot view="overview" activeView={activeView} visited={visitedViews.has('overview')}>
              <OverviewView metrics={overviewMetrics} environmentName={workspaceEnvironment?.name || 'All environments'} loading={overviewLoading} onNavigate={handleNavigate} onRefresh={() => void loadQualityData(undefined, true)} />
            </PageSlot>
            <PageSlot view="golden-datasets" activeView={activeView} visited={visitedViews.has('golden-datasets')}>
              <GoldenDatasetsView
                datasets={datasets}
                selectedDatasetId={selectedDatasetId}
                cases={goldenCases}
                loading={qualityLoading || isGoldenCasesLoading}
                onSelectDataset={(id) => void handleSelectDataset(id)}
                onCreateDataset={handleCreateDataset}
                onCreateVersion={handleCreateDatasetVersion}
                onCreateCase={handleCreateGoldenCase}
                onSetCaseState={handleSetGoldenCaseState}
              />
            </PageSlot>
            <PageSlot view="evaluation-runs" activeView={activeView} visited={visitedViews.has('evaluation-runs')}>
              <EvaluationRunsView
                datasets={datasets}
                runs={evaluationRuns}
                loading={qualityLoading}
                selectedRunId={selectedEvaluationId}
                caseResults={evaluationCaseResults}
                onSelectRun={setSelectedEvaluationId}
                onRefresh={() => void loadQualityData()}
                onCreateRun={handleStartEvaluation}
              />
            </PageSlot>
            <PageSlot view="release-comparisons" activeView={activeView} visited={visitedViews.has('release-comparisons')}>
              <ReleaseComparisonsView runs={evaluationRuns} loading={qualityLoading} onRefresh={() => void loadQualityData()} />
            </PageSlot>
            <PageSlot view="settings" activeView={activeView} visited={visitedViews.has('settings')}>
              <SettingsView environments={environments} loading={environmentsLoading} onRefresh={reloadEnvironments} currentUser={authUser} googleAuthenticated={privateIamDeployment} />
            </PageSlot>
          </main>
        </div>
      </div>
      <AnimatePresence>{isFeedbackModalOpen && <Suspense key="feedback-form" fallback={null}>
        <GiveFeedbackModal
          environments={environments}
          defaultEnvironmentId={workspaceEnvironment?.id}
          isOpen={isFeedbackModalOpen}
          onClose={() => setIsFeedbackModalOpen(false)}
          onSubmit={handleNewFeedback}
        />
      </Suspense>}</AnimatePresence>
      <AnimatePresence>{demoChooserOpen && demoSession && <DemoViewChooser key="demo-view-chooser" session={demoSession} busy={demoBusy} error={demoError} onSelect={email => void switchDemoPersona(email)} onClose={() => setDemoChooserOpen(false)} />}</AnimatePresence>
    </div>
  );
}

function viewTitle(view: ViewPath): string {
  return {
    overview: 'Overview metrics',
    'golden-datasets': 'Golden datasets',
    'evaluation-runs': 'Evaluation runs',
    'release-comparisons': 'Release comparisons',
    settings: 'Settings',
    'feedback-inbox': 'Feedback inbox',
    'feedback-detail': 'Feedback detail',
    'triage-queue': 'Triage queue',
    'my-feedback': 'My feedback',
  }[view];
}

function DisconnectedView({ title }: { title: string }) {
  return (
    <div className="flex min-h-[420px] items-center justify-center rounded-xl border border-surface-border bg-surface p-space-xl text-center shadow-sm">
      <div className="max-w-md">
        <span className="material-symbols-outlined text-[42px] text-ink-muted">database_off</span>
        <h1 className="mt-space-md font-headline-md text-ink-primary">{title}</h1>
        <p className="mt-space-sm font-body-md text-ink-secondary">
          This workspace will show live data after its FastAPI and BigQuery repository is implemented.
        </p>
      </div>
    </div>
  );
}

function PageSlot({ view, activeView, visited, children }: {
  view: ViewPath;
  activeView: ViewPath;
  visited: boolean;
  children: React.ReactNode;
}) {
  if (!visited) return null;
  const active = view === activeView;
  return <div className={active ? 'page-view-active' : 'hidden'} aria-hidden={!active}>
    <Suspense fallback={<PageLoading />}>{children}</Suspense>
  </div>;
}

function PageLoading() {
  return <div className="flex flex-col gap-space-lg" role="status" aria-label="Loading view">
    <div className="flex items-end justify-between gap-4"><div className="space-y-2"><div className="skeleton h-3 w-28" /><div className="skeleton h-8 w-56" /><div className="skeleton h-4 w-80 max-w-full" /></div><div className="skeleton h-9 w-28 rounded-lg" /></div>
    <div className="grid gap-space-md xl:grid-cols-12"><div className="skeleton h-56 rounded-xl xl:col-span-4" /><div className="skeleton h-80 rounded-xl xl:col-span-8" /></div>
    <div className="grid gap-space-md xl:grid-cols-12"><div className="skeleton h-64 rounded-xl xl:col-span-4" /><div className="skeleton h-64 rounded-xl xl:col-span-8" /></div>
  </div>;
}
