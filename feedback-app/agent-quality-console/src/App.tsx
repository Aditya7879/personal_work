import React, { useEffect, useState } from 'react';
import { FeedbackItem, ViewPath } from './types';
import {
  approveFeedbackAsGoldenCase,
  createEvaluationRun,
  createFeedback,
  createGoldenCase,
  createGoldenDataset,
  createGoldenDatasetVersion,
  EvaluationRunRecord,
  EvaluationCaseResultRecord,
  FeedbackSubmission,
  getOverviewMetrics,
  GoldenCaseRecord,
  GoldenDatasetRecord,
  listEvaluationRuns,
  listEvaluationCases,
  listGoldenCases,
  listGoldenDatasets,
  listFeedback,
  OverviewMetrics,
  setGoldenCaseState,
  updateFeedback,
} from './api/feedbackApi';
import { Header } from './components/Header';
import { Sidebar } from './components/Sidebar';
import { FeedbackInboxView } from './components/FeedbackInboxView';
import { FeedbackDetailView } from './components/FeedbackDetailView';
import { TriageQueueView } from './components/TriageQueueView';
import { GiveFeedbackModal } from './components/GiveFeedbackModal';
import { OverviewView } from './components/OverviewView';
import { GoldenDatasetsView } from './components/GoldenDatasetsView';
import { EvaluationRunsView } from './components/EvaluationRunsView';
import { ReleaseComparisonsView } from './components/ReleaseComparisonsView';

export default function App() {
  const [activeView, setActiveView] = useState<ViewPath>('feedback-inbox');
  const [selectedDetailId, setSelectedDetailId] = useState<string | null>(null);
  const [feedbackItems, setFeedbackItems] = useState<FeedbackItem[]>([]);
  const [feedbackTotal, setFeedbackTotal] = useState(0);
  const [feedbackPage, setFeedbackPage] = useState(1);
  const feedbackPageSize = 25;
  const [feedbackStateFilter, setFeedbackStateFilter] = useState('All');
  const [feedbackSeverityFilter, setFeedbackSeverityFilter] = useState('All');
  const [feedbackVerdictFilter, setFeedbackVerdictFilter] = useState('All');
  const [feedbackRcaFilter, setFeedbackRcaFilter] = useState('All');
  const [isFeedbackLoading, setIsFeedbackLoading] = useState(true);
  const [feedbackError, setFeedbackError] = useState<string | null>(null);
  const [isFeedbackModalOpen, setIsFeedbackModalOpen] = useState(false);
  const [globalSearchQuery, setGlobalSearchQuery] = useState('');
  const [datasets, setDatasets] = useState<GoldenDatasetRecord[]>([]);
  const [selectedDatasetId, setSelectedDatasetId] = useState<string | null>(null);
  const [goldenCases, setGoldenCases] = useState<GoldenCaseRecord[]>([]);
  const [evaluationRuns, setEvaluationRuns] = useState<EvaluationRunRecord[]>([]);
  const [selectedEvaluationId, setSelectedEvaluationId] = useState<string | null>(null);
  const [evaluationCaseResults, setEvaluationCaseResults] = useState<EvaluationCaseResultRecord[]>([]);
  const [overviewMetrics, setOverviewMetrics] = useState<OverviewMetrics | null>(null);
  const [qualityLoading, setQualityLoading] = useState(true);

  const loadFeedback = async () => {
    setIsFeedbackLoading(true);
    setFeedbackError(null);
    try {
      const response = await listFeedback({
        search: globalSearchQuery,
        state: feedbackStateFilter,
        severity: feedbackSeverityFilter,
        verdict: feedbackVerdictFilter,
        rootCause: feedbackRcaFilter,
        page: feedbackPage,
        pageSize: feedbackPageSize,
      });
      setFeedbackItems(response.items);
      setFeedbackTotal(response.total);
      setSelectedDetailId((current) => (
        current && response.items.some((item) => item.id === current)
          ? current
          : response.items[0]?.id || null
      ));
    } catch (error) {
      setFeedbackError(error instanceof Error ? error.message : 'Could not load feedback');
    } finally {
      setIsFeedbackLoading(false);
    }
  };

  useEffect(() => {
    void loadFeedback();
  }, [globalSearchQuery, feedbackPage, feedbackStateFilter, feedbackSeverityFilter, feedbackVerdictFilter, feedbackRcaFilter]);

  const loadQualityData = async () => {
    setQualityLoading(true);
    try {
      const [datasetRows, runRows, metrics] = await Promise.all([
        listGoldenDatasets(),
        listEvaluationRuns(),
        getOverviewMetrics(),
      ]);
      setDatasets(datasetRows);
      setEvaluationRuns(runRows);
      setOverviewMetrics(metrics);
      const selected = selectedDatasetId && datasetRows.some((dataset) => dataset.dataset_id === selectedDatasetId)
        ? selectedDatasetId
        : datasetRows[0]?.dataset_id || null;
      setSelectedDatasetId(selected);
      setGoldenCases(selected ? await listGoldenCases(selected) : []);
    } catch (error) {
      setFeedbackError(error instanceof Error ? error.message : 'Could not load quality data');
    } finally {
      setQualityLoading(false);
    }
  };

  useEffect(() => {
    void loadQualityData();
  }, []);

  useEffect(() => {
    if (!selectedEvaluationId) { setEvaluationCaseResults([]); return; }
    void listEvaluationCases(selectedEvaluationId)
      .then(setEvaluationCaseResults)
      .catch((error) => setFeedbackError(error instanceof Error ? error.message : 'Could not load evaluation case results'));
  }, [selectedEvaluationId]);

  const handleNavigate = (view: ViewPath, targetId?: string) => {
    setActiveView(view);
    if (targetId) setSelectedDetailId(targetId);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const handleUpdateItem = async (id: string, updates: Partial<FeedbackItem>) => {
    try {
      const updated = await updateFeedback(id, updates as Record<string, unknown>);
      setFeedbackItems((items) => items.map((item) => item.id === id ? updated : item));
    } catch (error) {
      setFeedbackError(error instanceof Error ? error.message : 'Could not update feedback');
    }
  };

  const handleBulkUpdate = async (ids: string[], updates: Record<string, unknown>) => {
    await Promise.all(ids.map((id) => updateFeedback(id, updates)));
    await loadFeedback();
  };

  const handleSaveTriage = async (id: string, updates: Record<string, unknown>) => {
    const updated = await updateFeedback(id, updates);
    setFeedbackItems((items) => items.map((item) => item.id === id ? updated : item));
  };

  const handleNewFeedback = async (submission: FeedbackSubmission) => {
    try {
      const created = await createFeedback(submission);
      setFeedbackItems((items) => [created, ...items]);
      setIsFeedbackModalOpen(false);
      handleNavigate('feedback-detail', created.id);
    } catch (error) {
      setFeedbackError(error instanceof Error ? error.message : 'Could not submit feedback');
    }
  };

  const handleSelectDataset = async (datasetId: string) => {
    setSelectedDatasetId(datasetId);
    try { setGoldenCases(await listGoldenCases(datasetId)); }
    catch (error) { setFeedbackError(error instanceof Error ? error.message : 'Could not load dataset cases'); }
  };

  const handleCreateDataset = async (input: { name: string; description?: string }) => {
    const created = await createGoldenDataset(input);
    setDatasets((previous) => [created, ...previous]);
    setSelectedDatasetId(created.dataset_id);
    setGoldenCases([]);
    setOverviewMetrics(await getOverviewMetrics());
  };

  const handleCreateDatasetVersion = async (datasetId: string) => {
    await createGoldenDatasetVersion(datasetId);
    await loadQualityData();
  };

  const handleCreateGoldenCase = async (datasetId: string, input: {
    title: string; question: string; expected_behavior: string; required_claims: string[]; expected_status?: string;
  }) => {
    const created = await createGoldenCase(datasetId, input);
    setGoldenCases((previous) => [created, ...previous]);
    await loadQualityData();
  };

  const handleSetGoldenCaseState = async (caseId: string, state: 'approved' | 'rejected') => {
    const updated = await setGoldenCaseState(caseId, state);
    setGoldenCases((previous) => previous.map((item) => item.case_id === caseId ? updated : item));
    await loadQualityData();
  };

  const handlePromoteCandidate = async (item: FeedbackItem) => {
    if (!datasets.length) {
      throw new Error('Create a golden dataset before promoting feedback to a candidate.');
    }
    if (!item.groundTruthHint?.trim()) {
      throw new Error('Add reviewer-verified expected behavior and save it before creating a golden candidate.');
    }
    await approveFeedbackAsGoldenCase(item.id, {
      dataset_id: selectedDatasetId || datasets[0].dataset_id,
      expected_behavior: item.groundTruthHint,
      required_claims: item.claims?.map((claim) => claim.statement) || [],
    });
    await Promise.all([loadFeedback(), loadQualityData()]);
  };

  const handleStartEvaluation = async (input: {
    dataset_id: string; dataset_version?: string; label?: string; mode: 'full' | 'reviewed_cases';
  }) => {
    const run = await createEvaluationRun(input);
    setEvaluationRuns((previous) => [run, ...previous]);
    setSelectedEvaluationId(run.id);
    setOverviewMetrics(await getOverviewMetrics());
  };

  const currentDetailItem = feedbackItems.find((item) => item.id === selectedDetailId) || null;

  return (
    <div className="min-h-screen bg-canvas text-ink-primary font-body antialiased flex flex-col">
      <Header
        searchQuery={globalSearchQuery}
        onSearch={(query) => { setFeedbackPage(1); setGlobalSearchQuery(query); }}
        onOpenGiveFeedback={() => setIsFeedbackModalOpen(true)}
      />
      <div className="flex flex-1 pt-14">
        <Sidebar
          activeView={activeView}
          onNavigate={handleNavigate}
          feedbackCount={feedbackTotal}
        />
        <div className="flex-1 w-full pl-0 sm:pl-60 min-w-0 transition-all">
          <main className="p-space-md sm:p-space-lg lg:p-space-xl max-w-[1600px] mx-auto">
            {feedbackError && (
              <div className="mb-space-md rounded-lg border border-issue-red/30 bg-issue-soft px-3 py-2 text-body-sm text-issue-red">
                {feedbackError}
              </div>
            )}

            {activeView === 'feedback-inbox' && (
              <FeedbackInboxView
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
                searchQuery={globalSearchQuery}
                onSearchQueryChange={setGlobalSearchQuery}
                onFiltersChange={(filters) => {
                  setFeedbackPage(1);
                  setFeedbackStateFilter(filters.state);
                  setFeedbackSeverityFilter(filters.severity);
                  setFeedbackVerdictFilter(filters.verdict);
                  setFeedbackRcaFilter(filters.rootCause);
                }}
              />
            )}
            {activeView === 'feedback-detail' && currentDetailItem && (
              <FeedbackDetailView
                item={currentDetailItem}
                onNavigate={handleNavigate}
                onPromoteToCandidate={(item) => void handlePromoteCandidate(item).catch((error) => setFeedbackError(error.message))}
                onSaveTriage={handleSaveTriage}
              />
            )}
            {activeView === 'feedback-detail' && !currentDetailItem && (
              <DisconnectedView title="Select a feedback item to inspect" />
            )}
            {activeView === 'triage-queue' && (
              <TriageQueueView
                items={feedbackItems}
                onNavigate={handleNavigate}
                onUpdateItem={handleUpdateItem}
                onPromoteCandidate={handlePromoteCandidate}
              />
            )}
            {activeView === 'overview' && (
              <OverviewView metrics={overviewMetrics} loading={qualityLoading} onNavigate={handleNavigate} onRefresh={() => void loadQualityData()} />
            )}
            {activeView === 'golden-datasets' && (
              <GoldenDatasetsView
                datasets={datasets}
                selectedDatasetId={selectedDatasetId}
                cases={goldenCases}
                loading={qualityLoading}
                onSelectDataset={(id) => void handleSelectDataset(id)}
                onCreateDataset={handleCreateDataset}
                onCreateVersion={handleCreateDatasetVersion}
                onCreateCase={handleCreateGoldenCase}
                onSetCaseState={handleSetGoldenCaseState}
              />
            )}
            {activeView === 'evaluation-runs' && (
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
            )}
            {activeView === 'release-comparisons' && (
              <ReleaseComparisonsView runs={evaluationRuns} loading={qualityLoading} onRefresh={() => void loadQualityData()} />
            )}
            {activeView === 'settings' && (
              <DisconnectedView title={`${viewTitle(activeView)} is not connected yet`} />
            )}
          </main>
        </div>
      </div>
      <GiveFeedbackModal
        isOpen={isFeedbackModalOpen}
        onClose={() => setIsFeedbackModalOpen(false)}
        onSubmit={handleNewFeedback}
      />
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
