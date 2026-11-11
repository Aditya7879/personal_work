import React, { useEffect, useState } from 'react';
import { AnimatePresence } from 'motion/react';
import { FeedbackItem, ViewPath } from '../types';
import { AgentEnvironment, AgentEnvironmentConfig, FeedbackFilterOptions, PromotionBatch, PromotionFilters, PromotionSelection, PublicFeedbackStatus, publicFeedbackStatuses } from '../api/feedbackApi';
import { ColumnFilter } from './ColumnFilter';
import { HorizontalTableScroll } from './HorizontalTableScroll';
import { formatRcaLabel } from '../utils/formatRcaLabel';
import { UserVerdictBadge } from './UserVerdictBadge';
import { PromotionDialog } from './PromotionDialog';
import { PromotionActivity, PromotionProgress } from './PromotionProgress';
import { ArrowRight, Check, ChevronFirst, ChevronLast, ChevronLeft, ChevronRight, Copy, Download, FilterX, ListChecks, X } from 'lucide-react';
import { ActionButton } from './ActionButton';
import { inboxEnvironmentFilter, inboxEnvironmentSelection, inboxRcaContext, inboxRowEnvironment } from '../utils/inboxEnvironment';

interface FeedbackInboxFilters {
  state: string;
  severity: string;
  verdict: string;
  rootCause: string;
  reporter: string;
  domain: string;
  environment: AgentEnvironment | 'All';
  status: PublicFeedbackStatus | 'All';
}

interface FeedbackInboxViewProps {
  environments?: AgentEnvironmentConfig[];
  environmentsLoading?: boolean;
  workspaceEnvironmentId?: string;
  onViewEnvironment?: (id: string) => void;
  onPromotionComplete?: () => void;
  items: FeedbackItem[];
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  stateFilter: string;
  severityFilter: string;
  verdictFilter: string;
  rcaFilter: string;
  reporterFilter: string;
  domainFilter: string;
  environmentFilter: AgentEnvironment | 'All';
  statusFilter: PublicFeedbackStatus | 'All';
  filterOptions: FeedbackFilterOptions;
  filtersLoading: boolean;
  onFiltersChange: (filters: FeedbackInboxFilters) => void;
  searchQuery: string;
  onSearchQueryChange: (query: string) => void;
  isLoading?: boolean;
  onNavigate: (view: ViewPath, targetId?: string) => void;
  onOpenGiveFeedback: () => void;
  onBulkUpdate: (ids: string[], updates: Record<string, unknown>) => Promise<void>;
}

const reviewStateOptions = ['Submitted', 'Triaged', 'Evidence review', 'Review complete', 'Golden candidate', 'Approved for dataset', 'Needs more information', 'Duplicate', 'Rejected'].map((value) => ({ value, label: value }));
const severityOptions = [{ value: 'High', label: 'High' }, { value: 'Med', label: 'Medium' }, { value: 'Low', label: 'Low' }];
const verdictOptions = ['Correct', 'Incorrect', 'Partially correct', 'Unsafe or misleading', 'Not specified'].map((value) => ({ value, label: value }));
const rcaOptions = [
  { value: 'retrieval_failure', label: 'Retrieval failure' },
  { value: 'source_gap', label: 'Knowledge/source gap' },
  { value: 'reasoning_error', label: 'Reasoning error' },
  { value: 'incomplete_answer', label: 'Incomplete answer' },
  { value: 'wrong_region_or_scope', label: 'Wrong region or scope' },
  { value: 'table_interpretation_error', label: 'Table interpretation error' },
  { value: 'citation_failure', label: 'Citation failure' },
  { value: 'image_ocr_error', label: 'Image/OCR error' },
  { value: 'outdated_content', label: 'Outdated content' },
  { value: 'ambiguous_question', label: 'Ambiguous question' },
];

export const FeedbackInboxView: React.FC<FeedbackInboxViewProps> = ({
  items,
  page,
  pageSize,
  total,
  onPageChange,
  stateFilter,
  severityFilter,
  verdictFilter,
  rcaFilter,
  reporterFilter,
  domainFilter,
  environmentFilter,
  statusFilter,
  filterOptions,
  filtersLoading,
  onFiltersChange,
  searchQuery,
  onSearchQueryChange,
  isLoading = false,
  onNavigate,
  onOpenGiveFeedback,
  onBulkUpdate,
  environments = [],
  environmentsLoading = false,
  workspaceEnvironmentId,
  onViewEnvironment,
  onPromotionComplete
}) => {
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [allMatching, setAllMatching] = useState(false);
  const [promotion, setPromotion] = useState<PromotionSelection | null>(null);
  const [activeBatch, setActiveBatch] = useState<PromotionBatch | null>(null);
  const [promotionReload, setPromotionReload] = useState(0);

  useEffect(() => {
    setSelectedIds([]);
    setAllMatching(false);
  }, [stateFilter, severityFilter, verdictFilter, rcaFilter, reporterFilter, domainFilter, environmentFilter, statusFilter, searchQuery, workspaceEnvironmentId]);

  const changeFilters = (updates: Partial<FeedbackInboxFilters>) => onFiltersChange({
    state: stateFilter,
    severity: severityFilter,
    verdict: verdictFilter,
    rootCause: rcaFilter,
    reporter: reporterFilter,
    domain: domainFilter,
    environment: environmentFilter,
    status: statusFilter,
    ...updates,
  });

  const clearFilters = () => {
    onViewEnvironment?.('All');
    onFiltersChange({ state: 'All', severity: 'All', verdict: 'All', rootCause: 'All', reporter: 'All', domain: 'All', environment: 'All', status: 'All' });
    onPageChange(1);
    onSearchQueryChange('');
  };

  const activeCount = items.filter((item) => item.state !== 'Rejected').length;
  const highCount = items.filter((item) => item.severity === 'High').length;
  const mediumCount = items.filter((item) => item.severity === 'Med').length;
  const lowCount = items.filter((item) => item.severity === 'Low').length;
  const goldenCount = items.filter((item) => item.state === 'Golden candidate').length;
  const classifiedCount = items.filter((item) => item.suggestedRca).length;

  const toggleSelectAll = () => {
    if (allMatching) { setAllMatching(false); setSelectedIds([]); return; }
    const pageSelected = filteredItems.every((item) => selectedIds.includes(item.id));
    setSelectedIds((values) => pageSelected ? values.filter((id) => !filteredItems.some((item) => item.id === id)) : [...new Set([...values, ...filteredItems.map((item) => item.id)])]);
  };

  const toggleSelectRow = (id: string) => {
    setSelectedIds((prev) =>
      prev.includes(id) ? prev.filter((item) => item !== id) : [...prev, id]
    );
  };

  const copyRunId = (runId: string) => {
    if (!runId) return;
    navigator.clipboard?.writeText(runId);
    setCopiedId(runId);
    setTimeout(() => setCopiedId(null), 1500);
  };

  const exportCsv = () => {
    const columns: Array<keyof FeedbackItem> = ['id', 'title', 'domain', 'prompt', 'generatedAnswer', 'userVerdict', 'state', 'publicStatus', 'confirmedRca', 'reporter'];
    const quote = (value: unknown) => `"${String(value ?? '').replaceAll('"', '""')}"`;
    const csv = [columns.join(','), ...filteredItems.map((item) => columns.map((column) => quote(item[column])).join(','))].join('\n');
    const link = document.createElement('a');
    link.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    link.download = 'feedback-export.csv';
    link.click();
    URL.revokeObjectURL(link.href);
  };

  const updateSelected = async (state: string) => {
    if (allMatching) return;
    await onBulkUpdate(selectedIds, { state });
    setSelectedIds([]);
  };

  const filteredItems = items;
  const selectedCount = allMatching ? total : selectedIds.length;
  const promotionFilters: PromotionFilters = {
    search: searchQuery || undefined, state: stateFilter === 'All' ? undefined : stateFilter,
    severity: severityFilter === 'All' ? undefined : severityFilter, verdict: verdictFilter === 'All' ? undefined : verdictFilter,
    root_cause: rcaFilter === 'All' ? undefined : rcaFilter, reporter: reporterFilter === 'All' ? undefined : reporterFilter,
    domain: domainFilter === 'All' ? undefined : domainFilter, environment: environmentFilter === 'All' ? undefined : environmentFilter,
    public_status: statusFilter === 'All' ? undefined : statusFilter, environment_id: workspaceEnvironmentId,
  };
  const environmentControl = inboxEnvironmentFilter(environments, workspaceEnvironmentId, environmentFilter, Boolean(onViewEnvironment));
  const changeEnvironment = (value: string) => {
    if (!onViewEnvironment) { changeFilters({ environment:value as AgentEnvironment | 'All' }); return; }
    const selection = inboxEnvironmentSelection(value);
    onViewEnvironment(selection.workspaceId);
    changeFilters({ environment:selection.kind });
    onPageChange(1);
  };
  const activeFilterCount = [stateFilter, severityFilter, verdictFilter, rcaFilter, reporterFilter, domainFilter, statusFilter].filter((value) => value !== 'All').length + (environmentControl.value !== 'All' ? 1 : 0) + (searchQuery ? 1 : 0);

  return (
    <div className="flex flex-col w-full animate-in fade-in duration-200">
      <div className="mb-4 space-y-3">
        {activeBatch && <PromotionProgress key={activeBatch.id} batchId={activeBatch.id} initial={activeBatch} onOpenFeedback={(id) => onNavigate('feedback-detail', id)} onViewEnvironment={(id) => onViewEnvironment?.(id)} onUpdated={onPromotionComplete} />}
        <PromotionActivity refresh={promotionReload} onOpenFeedback={(id) => onNavigate('feedback-detail', id)} onViewEnvironment={(id) => onViewEnvironment?.(id)} />
      </div>
      {isLoading && (
        <div className="mb-space-md flex items-center gap-2 rounded-lg border border-surface-border bg-surface px-3 py-2 text-body-sm text-ink-secondary" role="status">
          <span className="h-2 w-2 animate-pulse rounded-full bg-primary-container" />
          Refreshing feedback…
        </div>
      )}
      {/* Top Stat / Velocity Overview Bento Strip */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-space-md mb-space-lg">
        <div className="bg-surface rounded-xl p-space-md shadow-sm relative overflow-hidden flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="font-metadata text-metadata uppercase tracking-wider text-ink-muted">
               Feedback records
            </span>
          </div>
          <div className="flex items-baseline gap-space-sm mt-space-sm">
              <span className="font-metric">{total}</span>
             <span className="font-label-sm text-label-sm text-ink-muted">matching current filters</span>
          </div>
          <div className="mt-space-sm w-full bg-state-gray-soft h-1.5 rounded-full overflow-hidden flex">
             <div className="bg-issue-red h-full" style={{ width: `${activeCount ? (highCount / activeCount) * 100 : 0}%` }} title={`High: ${highCount}`}></div>
             <div className="bg-review-amber h-full" style={{ width: `${activeCount ? (mediumCount / activeCount) * 100 : 0}%` }} title={`Med: ${mediumCount}`}></div>
             <div className="bg-state-gray h-full" style={{ width: `${activeCount ? (lowCount / activeCount) * 100 : 0}%` }} title={`Low: ${lowCount}`}></div>
          </div>
        </div>

        <div className="bg-surface rounded-xl p-space-md shadow-sm relative overflow-hidden flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="font-metadata text-metadata uppercase tracking-wider text-ink-muted">
              AI RCA Confidence
            </span>
            <span className="material-symbols-outlined text-[18px] text-tertiary">auto_awesome</span>
          </div>
          <div className="flex items-baseline gap-space-sm mt-space-sm">
             <span className="font-metric">—</span>
             <span className="font-label-sm text-label-sm text-ink-muted font-medium">Not calculated</span>
          </div>
          <div className="flex items-center gap-space-xs mt-space-sm text-body-sm font-body-sm text-ink-muted">
             <span className="w-2 h-2 rounded-full bg-state-gray"></span>
             <span>{classifiedCount}/{items.length} classified</span>
          </div>
        </div>

        <div className="bg-surface rounded-xl p-space-md shadow-sm relative overflow-hidden flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="font-metadata text-metadata uppercase tracking-wider text-ink-muted">
              Golden Candidates
            </span>
            <span className="font-label-sm text-label-sm bg-dataset-soft text-dataset-purple px-1.5 py-0.5 rounded font-semibold">
              Priority
            </span>
          </div>
          <div className="flex items-baseline gap-space-sm mt-space-sm">
             <span className="font-metric">{goldenCount}</span>
             <span className="font-label-sm text-label-sm text-ink-muted">golden candidates</span>
          </div>
          <div className="flex items-center gap-space-xs mt-space-sm text-body-sm font-body-sm text-ink-secondary">
            <span className="material-symbols-outlined text-[16px] text-dataset-purple">verified</span>
            <span>Candidates on this page</span>
          </div>
        </div>

        <div className="bg-surface rounded-xl p-space-md shadow-sm relative overflow-hidden flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="font-metadata text-metadata uppercase tracking-wider text-ink-muted">
              Review Latency (P50)
            </span>
            <span className="material-symbols-outlined text-[18px] text-primary-container">schedule</span>
          </div>
          <div className="flex items-baseline gap-space-sm mt-space-sm">
             <span className="font-metric">—</span>
             <span className="font-label-sm text-label-sm text-ink-muted">No review timing yet</span>
          </div>
          <div className="flex items-center gap-space-xs mt-space-sm text-body-sm font-body-sm text-ink-muted">
            <span className="material-symbols-outlined text-[16px]">hourglass_empty</span>
            <span>Timing not available</span>
          </div>
        </div>
      </div>

      {/* Primary Page Action Bar */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-space-md pb-space-lg">
        <div className="flex flex-col">
          <div className="flex items-center gap-space-sm">
            <h1 className="font-headline-lg text-headline-lg text-ink-primary tracking-tight">
              Feedback inbox
            </h1>
            <span className="px-2 py-0.5 bg-issue-soft text-issue-red font-label-sm text-label-sm font-semibold rounded-full">
               {activeCount} active
            </span>
          </div>
          <p className="font-body-md text-body-md text-ink-secondary mt-0.5">
              Promoted feedback shows its current main environment; the original reported source, owner and history remain preserved.
          </p>
        </div>

        <div className="flex items-center gap-space-sm self-start lg:self-center flex-wrap">
          {/* Batch Actions Dropdown */}
          <div className="relative inline-block text-left">
            <ActionButton label="Select page" compactLabel="Select" icon={<ListChecks />}
              onClick={() => { setAllMatching(false); setSelectedIds(filteredItems.map((item) => item.id)); }}
            />
          </div>

          {/* Export CSV */}
          <ActionButton label="Export CSV" icon={<Download />} onClick={exportCsv} />

          {/* New Feedback Trigger */}
          <button
            type="button"
            onClick={onOpenGiveFeedback}
            className="h-9 px-4 bg-primary-container text-on-primary hover:bg-primary font-label-md text-label-md rounded-lg shadow-sm flex items-center gap-space-xs transition-all cursor-pointer"
          >
            <span className="material-symbols-outlined text-[18px]">add</span>
            <span>New feedback</span>
          </button>
        </div>
      </div>

      {/* Search and reset; field filters live in the table headers. */}
      <div className="mb-space-md flex flex-wrap items-center gap-space-md rounded-xl border border-surface-border/50 bg-surface p-space-md shadow-sm">
        <div className="relative min-w-64 flex-1">
          <span className="material-symbols-outlined absolute left-3 top-2.5 text-ink-muted text-[18px]">search</span>
          <input
            className="w-full h-10 pl-9 pr-24 bg-state-gray-soft/40 hover:bg-state-gray-soft/70 focus:bg-surface rounded-lg font-body-sm text-body-sm text-ink-primary placeholder:text-ink-muted focus:outline-none border border-transparent focus:border-primary-container transition-all"
            placeholder="Search by feedback title, run ID, or question..."
            aria-label="Search feedback"
            type="text"
            value={searchQuery}
            onChange={(e) => { onPageChange(1); onSearchQueryChange(e.target.value); }}
          />
          {searchQuery && (
            <button
              type="button"
              onClick={() => { onPageChange(1); onSearchQueryChange(''); }}
              className="absolute right-3 top-2.5 font-label-sm text-label-sm text-ink-muted hover:text-ink-primary bg-surface px-1.5 py-0.5 rounded shadow-sm"
            >
              clear
            </button>
          )}
        </div>
        <div className="flex items-center gap-space-sm text-label-sm text-ink-secondary">
          <span className="rounded bg-surface-container-low px-2 py-1">{total} results{activeFilterCount > 0 ? ` · ${activeFilterCount} active filter${activeFilterCount === 1 ? '' : 's'}` : ''}</span>
          <ActionButton label="Clear filters" icon={<FilterX />} size="sm" tone="ghost" onClick={clearFilters} />
        </div>
      </div>

      {/* Main Dense Enterprise Data Table Container */}
      <div className="bg-surface rounded-xl shadow-sm overflow-hidden flex flex-col border border-surface-border">
        <HorizontalTableScroll label="Feedback inbox">
          <table aria-label="Feedback inbox" className="w-full text-left border-collapse min-w-[1840px]">
            {/* Sticky Header */}
            <thead className="sticky top-0 z-20 bg-surface-container-low">
              <tr className="font-metadata text-metadata uppercase tracking-wider text-ink-muted border-b border-surface-container">
                <th className="py-3 px-space-md w-10">
                  <input
                    className="rounded w-4 h-4 text-primary-container cursor-pointer accent-primary-container"
                    type="checkbox"
                     aria-label="Select current page"
                     checked={allMatching || (filteredItems.length > 0 && filteredItems.every((item) => selectedIds.includes(item.id)))}
                    onChange={toggleSelectAll}
                  />
                </th>
                <th className="py-3 px-space-sm w-28"><ColumnFilter label="Severity" value={severityFilter} options={severityOptions} allLabel="All severities" onChange={(value) => changeFilters({ severity: value })} /></th>
                <th className="py-3 px-space-md min-w-[280px]">Feedback &amp; Excerpt</th>
                <th className="py-3 px-space-md min-w-[180px]"><ColumnFilter label="Domain" value={domainFilter} options={filterOptions.domains.map((value) => ({ value, label: value }))} allLabel="All domains" loading={filtersLoading} onChange={(value) => changeFilters({ domain: value })} /></th>
                <th className="py-3 px-space-md w-36" title="Shows the current main environment after promotion. Details retain the originally reported source; this selector shares the exact named environment scope."><ColumnFilter label="Environment" value={environmentControl.value} options={environmentControl.options} allLabel="All environments" loading={Boolean(onViewEnvironment) && environmentsLoading} onChange={changeEnvironment} /></th>
                <th className="py-3 px-space-md min-w-[150px]">Agent / Run ID</th>
                <th className="py-3 px-space-md w-36" title="The reporter-submitted verdict is preserved separately from automated retest assessments"><ColumnFilter label="User verdict" value={verdictFilter} options={verdictOptions} allLabel="All verdicts" onChange={(value) => changeFilters({ verdict: value })} /></th>
                <th className="py-3 px-space-md min-w-[220px]"><ColumnFilter label="RCA" value={rcaFilter} options={rcaOptions} allLabel="All root causes" onChange={(value) => changeFilters({ rootCause: value })} /></th>
                <th className="py-3 px-space-md w-36" title="Review progress of the original source report. A linked target-environment RCA does not advance this workflow."><ColumnFilter label="Review state" value={stateFilter} options={reviewStateOptions} allLabel="All review states" onChange={(value) => changeFilters({ state: value })} />{workspaceEnvironmentId && <p className="mt-1 text-metadata font-normal normal-case text-ink-muted">Source report</p>}</th>
                <th className="py-3 px-space-md w-36"><ColumnFilter label="Status" value={statusFilter} options={publicFeedbackStatuses.map((value) => ({ value, label: value }))} allLabel="All statuses" onChange={(value) => changeFilters({ status: value as PublicFeedbackStatus | 'All' })} /></th>
                <th className="py-3 px-space-md w-32"><ColumnFilter label="User" value={reporterFilter} options={filterOptions.reporters.map((value) => ({ value, label: value }))} allLabel="All users" loading={filtersLoading} onChange={(value) => changeFilters({ reporter: value })} /></th>
                <th className="table-column-actions sticky right-0 z-30 w-28 min-w-28 border-l border-surface-border bg-surface-container-low py-3 pr-space-md pl-space-sm text-right">Action</th>
              </tr>
            </thead>

            <tbody className="divide-y divide-surface-container-low font-body-sm text-body-sm text-ink-primary">
              {isLoading && filteredItems.length === 0 && <tr><td colSpan={12}><FeedbackInboxSkeleton /></td></tr>}
              {!isLoading && filteredItems.length === 0 && <tr><td colSpan={12} className="px-space-md py-12 text-center text-ink-secondary"><p>No feedback matches the current filters.</p><button type="button" onClick={clearFilters} className="mt-3 rounded-lg border border-surface-border px-3 py-2 font-label-sm font-semibold text-primary hover:bg-indigo-soft">Clear filters</button></td></tr>}
              {filteredItems.map((item) => {
                const isSelected = allMatching || selectedIds.includes(item.id);
                const environmentCell = inboxRowEnvironment(item, environments, workspaceEnvironmentId, environmentFilter);
                const rcaContext = inboxRcaContext(item, workspaceEnvironmentId);
                return (
                  <tr
                    key={item.id}
                    className={`hover:bg-state-gray-soft/50 transition-colors group ${
                      isSelected ? 'bg-indigo-soft/30' : ''
                    }`}
                  >
                    <td className="py-3 px-space-md relative">
                      {item.severity === 'High' && (
                        <div className="absolute left-0 top-0 bottom-0 w-1 bg-issue-red"></div>
                      )}
                      {item.severity === 'Med' && (
                        <div className="absolute left-0 top-0 bottom-0 w-1 bg-review-amber"></div>
                      )}
                      <input
                        className="row-checkbox rounded w-4 h-4 text-primary-container cursor-pointer accent-primary-container"
                         type="checkbox"
                         aria-label={`Select feedback ${item.id}`}
                         disabled={allMatching}
                        checked={isSelected}
                        onChange={() => toggleSelectRow(item.id)}
                      />
                    </td>

                    <td className="py-3 px-space-sm whitespace-nowrap">
                      {item.severity === 'High' && (
                        <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-issue-soft text-issue-red font-label-sm text-label-sm font-semibold">
                          <span className="w-1.5 h-1.5 rounded-full bg-issue-red animate-pulse"></span>
                          High
                        </span>
                      )}
                      {item.severity === 'Med' && (
                        <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-review-soft text-review-amber font-label-sm text-label-sm font-semibold">
                          <span className="w-1.5 h-1.5 rounded-full bg-review-amber"></span>
                          Med
                        </span>
                      )}
                      {item.severity === 'Low' && (
                        <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-state-gray-soft text-ink-secondary font-label-sm text-label-sm font-semibold">
                          <span className="w-1.5 h-1.5 rounded-full bg-ink-muted"></span>
                          Low
                        </span>
                      )}
                    </td>

                    <td className="py-3 px-space-md">
                      <div className="flex max-w-[360px] flex-col gap-0.5">
                        <button
                          type="button"
                          onClick={() => onNavigate('feedback-detail', item.id)}
                          className="font-title-md text-title-md text-ink-primary hover:text-primary-container transition-colors line-clamp-1 text-left cursor-pointer"
                        >
                          {item.title}
                        </button>
                        <p className="font-body-sm text-body-sm text-ink-muted line-clamp-1">
                          “{item.excerpt}”
                        </p>
                      </div>
                    </td>

                    <td className="max-w-[240px] py-3 px-space-md text-ink-secondary">{item.domain || 'Unspecified'}</td>
                    <td className="py-3 px-space-md text-ink-secondary"><span className="break-words">{environmentCell.label}</span><p className="mt-1 text-metadata text-ink-muted">{environmentCell.detail}</p></td>

                    <td className="py-3 px-space-md">
                      <div className="flex flex-col">
                        <span className="whitespace-nowrap font-metadata text-metadata text-ink-secondary">{item.agentName}</span>
                        <div className="flex items-center gap-1 group/mono">
                          <span className="max-w-[180px] truncate whitespace-nowrap font-code-xs text-code-xs text-ink-muted group-hover/mono:text-ink-primary font-mono">
                            {item.runId || 'No linked run'}
                          </span>
                          {item.runId && <ActionButton label={copiedId === item.runId ? 'Copied run ID' : 'Copy Run ID'} icon={copiedId === item.runId ? <Check /> : <Copy />} tone="ghost" size="sm" expansion="overlay" expanded={copiedId === item.runId}
                            onClick={() => copyRunId(item.runId || '')}
                            title="Copy Run ID"
                          />}
                        </div>
                      </div>
                    </td>

                    <td className="py-3 px-space-md whitespace-nowrap">
                      <UserVerdictBadge value={item.userVerdict} />
                    </td>

                    <td className="py-3 px-space-md whitespace-nowrap">
                       {rcaContext.kind === 'attempt' ? <div className="text-body-sm text-ink-secondary">{rcaContext.attempt.rcaCategory ? formatRcaLabel(rcaContext.attempt.rcaCategory) : rcaContext.attempt.status === 'running' ? rcaContext.attempt.phase === 'rca' ? 'Answer saved · checking RCA' : 'Fetching fresh answer' : formatRcaLabel(rcaContext.attempt.assessment || rcaContext.attempt.status)}<p className="mt-1 text-metadata text-ink-muted">{rcaContext.attempt.revision !== item.revision ? `Earlier input · revision ${rcaContext.attempt.revision}` : 'Selected-environment check · AI unverified'}</p></div> : rcaContext.kind === 'missing' ? <span className="text-ink-muted">Not tested in this environment</span> : <><div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-surface-container-high/60 font-label-sm text-label-sm text-ink-secondary">
                         <span className="font-metadata text-tertiary font-semibold uppercase">{item.suggestedRcaStatus === 'reviewer_classified' ? 'Manual' : item.suggestedRcaStatus === 'auto_classified' ? 'Auto' : item.confirmedRca ? 'Manual' : 'AI'}</span>
                         <span className="text-ink-primary font-medium">{formatRcaLabel(item.confirmedRca || item.suggestedRca || 'Unclassified')}</span>
                        <span className="text-ink-muted font-normal">·</span>
                        <span className="font-semibold text-evidence-teal">
                           {item.suggestedRcaConfidence == null ? '—' : item.suggestedRcaConfidence.toFixed(2)}
                        </span>
                       </div>{workspaceEnvironmentId && <p className="mt-1 text-metadata text-ink-muted">Original answer RCA{item.confirmedRca ? ' · reviewer classified' : ' · AI unverified'}</p>}</>}
                    </td>

                    <td className="py-3 px-space-md whitespace-nowrap">
                      {item.state === 'Submitted' && (
                        <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded bg-state-gray-soft text-ink-secondary font-label-sm text-label-sm">
                          <span className="w-1.5 h-1.5 rounded-full bg-ink-muted"></span>
                          Submitted
                        </span>
                      )}
                      {item.state === 'Triaged' && (
                        <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded bg-indigo-soft text-primary-container font-label-sm text-label-sm font-medium">
                          <span className="w-1.5 h-1.5 rounded-full bg-primary-container"></span>
                          Triaged
                        </span>
                      )}
                      {item.state === 'Evidence review' && (
                        <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded bg-review-soft text-review-amber font-label-sm text-label-sm font-medium">
                          <span className="w-1.5 h-1.5 rounded-full bg-review-amber"></span>
                          Evidence review
                        </span>
                      )}
                      {item.state === 'Review complete' && (
                        <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded bg-evidence-soft text-evidence-teal font-label-sm text-label-sm font-medium">
                          <span className="w-1.5 h-1.5 rounded-full bg-evidence-teal"></span>
                          Review complete
                        </span>
                      )}
                      {item.state === 'Golden candidate' && (
                        <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded bg-dataset-soft text-dataset-purple font-label-sm text-label-sm font-medium">
                          <span className="w-1.5 h-1.5 rounded-full bg-dataset-purple"></span>
                          Golden candidate
                        </span>
                      )}
                       {!['Submitted', 'Triaged', 'Evidence review', 'Review complete', 'Golden candidate'].includes(item.state) && (
                        <span className="inline-flex items-center rounded bg-state-gray-soft px-2 py-0.5 font-label-sm text-ink-secondary">{item.state}</span>
                       )}
                       {item.state === 'Triaged' && !item.confirmedRca && ['sonnet_suggested', 'auto_classified'].includes(item.suggestedRcaStatus || '') && <p className="mt-1 text-metadata text-ink-muted">AI ready · human review pending</p>}
                    </td>

                    <td className="py-3 px-space-md whitespace-nowrap"><span className="inline-flex rounded-full bg-surface-container-low px-2.5 py-1 font-label-sm text-ink-secondary">{item.publicStatus || 'Received'}</span></td>

                    <td className="py-3 px-space-md whitespace-nowrap">
                      <div className="flex flex-col">
                        <span className="font-label-sm text-label-sm text-ink-primary truncate max-w-[110px]">
                          {item.reporter ? item.reporter.split('@')[0] : 'Unknown reporter'}
                        </span>
                        <span className="font-metadata text-metadata text-ink-muted">{item.reportedTime}</span>
                      </div>
                    </td>

                    <td className={`table-column-actions sticky right-0 z-10 border-l border-surface-border py-3 pr-space-md pl-space-sm text-right whitespace-nowrap ${isSelected ? 'bg-indigo-soft' : 'bg-surface group-hover:bg-canvas'}`}>
                      <ActionButton label="Open feedback" icon={<ArrowRight />} tone="soft" size="sm" expansion="overlay" align="end" containerClassName="ml-auto"
                        onClick={() => onNavigate('feedback-detail', item.id)}
                        aria-label={`Open feedback ${item.id}`}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </HorizontalTableScroll>

        {/* Table Footer / Pagination */}
        <div className="py-space-sm px-space-md bg-surface border-t border-surface-container flex flex-col sm:flex-row items-center justify-between gap-space-sm">
          <div className="flex items-center gap-space-md">
            <span className="font-body-sm text-body-sm text-ink-muted">Showing {total ? (page - 1) * pageSize + 1 : 0}–{Math.min(page * pageSize, total)} of {total} items</span>
            <div className="hidden sm:flex items-center gap-1.5">
              <span className="font-metadata text-metadata text-ink-muted uppercase">Rows per page:</span>
              <span className="font-label-sm text-ink-secondary">{pageSize}</span>
            </div>
          </div>

          <div className="flex items-center gap-space-xs">
            <button aria-label="First feedback page" onClick={() => onPageChange(1)} className="flex h-8 w-8 items-center justify-center rounded-lg text-ink-muted transition-colors hover:bg-state-gray-soft hover:text-ink-primary disabled:opacity-40" disabled={page <= 1} type="button"><ChevronFirst size={18} aria-hidden="true" /></button>
            <button aria-label="Previous feedback page" onClick={() => onPageChange(Math.max(1, page - 1))} className="flex h-8 w-8 items-center justify-center rounded-lg text-ink-muted transition-colors hover:bg-state-gray-soft hover:text-ink-primary disabled:opacity-40" disabled={page <= 1} type="button"><ChevronLeft size={18} aria-hidden="true" /></button>
             <div className="flex items-center gap-1 px-2 font-label-sm text-label-sm text-ink-primary">
              <span className="font-bold">{page}</span>
              <span className="text-ink-muted">/</span>
              <span>{Math.max(1, Math.ceil(total / pageSize))}</span>
            </div>
            <button aria-label="Next feedback page" onClick={() => onPageChange(Math.min(Math.max(1, Math.ceil(total / pageSize)), page + 1))} className="flex h-8 w-8 items-center justify-center rounded-lg text-ink-secondary transition-colors hover:bg-state-gray-soft hover:text-ink-primary disabled:opacity-40" disabled={page >= Math.ceil(total / pageSize)} type="button"><ChevronRight size={18} aria-hidden="true" /></button>
            <button aria-label="Last feedback page" onClick={() => onPageChange(Math.max(1, Math.ceil(total / pageSize)))} className="flex h-8 w-8 items-center justify-center rounded-lg text-ink-secondary transition-colors hover:bg-state-gray-soft hover:text-ink-primary disabled:opacity-40" disabled={page >= Math.ceil(total / pageSize)} type="button"><ChevronLast size={18} aria-hidden="true" /></button>
          </div>
        </div>
      </div>

      {/* Floating / Docked Bulk Selection Action Bar */}
      {selectedCount > 0 && (
        <div aria-label="Selected feedback actions" className="fixed bottom-4 left-1/2 z-30 flex w-max max-w-[calc(100vw-2rem)] -translate-x-1/2 flex-wrap items-center justify-center gap-3 rounded-xl border border-surface-border/20 bg-inverse-surface px-4 py-3 text-inverse-on-surface shadow-xl sm:left-[calc(50%+7.5rem)] sm:max-w-[calc(100vw-17rem)]">
          <div className="flex items-center gap-space-sm border-r border-state-gray/40 pr-space-md">
            <span className="w-2 h-2 rounded-full bg-evidence-teal animate-ping"></span>
            <span className="font-label-md text-label-md font-semibold">
              {selectedCount} item{selectedCount > 1 ? 's' : ''} selected{allMatching ? ' · all matching' : ''}
            </span>
          </div>

          <div className="flex min-w-0 flex-wrap items-center gap-space-xs">
            <button type="button" onClick={() => setPromotion({ feedback_ids: allMatching ? [] : [...selectedIds], all_matching: allMatching, filters: promotionFilters })} className="h-8 rounded-lg bg-surface px-3 text-label-sm font-semibold text-ink-primary">Promote & retest</button>
            {!allMatching && total > selectedIds.length && <button type="button" onClick={() => { setAllMatching(true); setSelectedIds([]); }} className="h-8 rounded-lg px-2 text-label-sm underline underline-offset-4">Select all {total} matching</button>}
            <button type="button" onClick={() => { setSelectedIds([]); setAllMatching(false); }} className="flex h-8 items-center gap-1.5 rounded-lg bg-surface/10 px-3 text-label-sm text-inverse-on-surface transition-colors hover:bg-surface/20"><X size={16} aria-hidden="true" />Clear selection</button>

            <button
              type="button"
               onClick={() => void updateSelected('Duplicate')}
               disabled={allMatching}
              className="h-8 px-3 rounded-lg bg-surface/10 hover:bg-surface/20 text-inverse-on-surface font-label-sm text-label-sm flex items-center gap-1.5 transition-all cursor-pointer"
            >
              <span className="material-symbols-outlined text-[16px]">content_copy</span>
              <span>Mark duplicate</span>
            </button>

            <button
              type="button"
               onClick={() => void updateSelected('Triaged').then(() => onNavigate('triage-queue'))}
               disabled={allMatching}
              className="h-8 px-3 rounded-lg bg-primary-container hover:bg-primary text-on-primary font-label-sm text-label-sm flex items-center gap-1.5 transition-all cursor-pointer"
            >
              <span className="material-symbols-outlined text-[16px]">low_priority</span>
              <span>Move to triage</span>
            </button>

            <button type="button" onClick={exportCsv} className="flex h-8 items-center gap-1.5 rounded-lg bg-surface/10 px-3 text-label-sm text-inverse-on-surface transition-colors hover:bg-surface/20"><Download size={16} aria-hidden="true" />Export page</button>
          </div>

          <div className="pl-space-sm">
            <button
              type="button"
              onClick={() => { setSelectedIds([]); setAllMatching(false); }}
              className="text-state-gray hover:text-inverse-on-surface p-1 rounded transition-colors cursor-pointer"
              title="Deselect all"
            >
              <span className="material-symbols-outlined text-[16px]">close</span>
            </button>
          </div>
        </div>
      )}
      <AnimatePresence>{promotion && <PromotionDialog key="promotion" selection={promotion} environments={environments} onClose={() => setPromotion(null)} onSettings={() => { setPromotion(null); onNavigate('settings'); }} onSubmitted={(batch) => { setActiveBatch(batch); setPromotion(null); setSelectedIds([]); setAllMatching(false); setPromotionReload((value) => value + 1); onPromotionComplete?.(); }} />}</AnimatePresence>
    </div>
  );
};

function FeedbackInboxSkeleton() {
  return <div className="space-y-2 p-space-md" role="status" aria-label="Loading feedback inbox">
    {Array.from({ length: 7 }, (_, index) => <div key={index} className="skeleton h-14 w-full rounded-lg" />)}
  </div>;
}
