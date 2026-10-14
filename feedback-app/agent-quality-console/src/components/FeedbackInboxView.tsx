import React, { useState } from 'react';
import { FeedbackItem, ViewPath } from '../types';

interface FeedbackInboxViewProps {
  items: FeedbackItem[];
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  stateFilter: string;
  severityFilter: string;
  verdictFilter: string;
  rcaFilter: string;
  onFiltersChange: (filters: { state: string; severity: string; verdict: string; rootCause: string }) => void;
  searchQuery: string;
  onSearchQueryChange: (query: string) => void;
  isLoading?: boolean;
  onNavigate: (view: ViewPath, targetId?: string) => void;
  onOpenGiveFeedback: () => void;
  onBulkUpdate: (ids: string[], updates: Record<string, unknown>) => Promise<void>;
}

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
  onFiltersChange,
  searchQuery,
  onSearchQueryChange,
  isLoading = false,
  onNavigate,
  onOpenGiveFeedback,
  onBulkUpdate
}) => {
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const activeCount = items.filter((item) => item.state !== 'Rejected').length;
  const highCount = items.filter((item) => item.severity === 'High').length;
  const mediumCount = items.filter((item) => item.severity === 'Med').length;
  const lowCount = items.filter((item) => item.severity === 'Low').length;
  const goldenCount = items.filter((item) => item.state === 'Golden candidate').length;
  const classifiedCount = items.filter((item) => item.suggestedRca).length;

  const toggleSelectAll = () => {
    if (selectedIds.length === filteredItems.length) {
      setSelectedIds([]);
    } else {
      setSelectedIds(filteredItems.map((i) => i.id));
    }
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
    const columns: Array<keyof FeedbackItem> = ['id', 'title', 'prompt', 'generatedAnswer', 'userVerdict', 'state', 'confirmedRca', 'reporter'];
    const quote = (value: unknown) => `"${String(value ?? '').replaceAll('"', '""')}"`;
    const csv = [columns.join(','), ...filteredItems.map((item) => columns.map((column) => quote(item[column])).join(','))].join('\n');
    const link = document.createElement('a');
    link.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    link.download = 'feedback-export.csv';
    link.click();
    URL.revokeObjectURL(link.href);
  };

  const updateSelected = async (state: string) => {
    await onBulkUpdate(selectedIds, { state });
    setSelectedIds([]);
  };

  const filteredItems = items.filter((item) => {
    return true;
  });

  return (
    <div className="flex flex-col w-full animate-in fade-in duration-200">
      {isLoading && (
        <div className="mb-space-md rounded-lg border border-surface-border bg-surface px-3 py-2 text-body-sm text-ink-secondary">
          Loading feedback from BigQuery…
        </div>
      )}
      {/* Top Stat / Velocity Overview Bento Strip */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-space-md mb-space-lg">
        <div className="bg-surface rounded-xl p-space-md shadow-sm relative overflow-hidden flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="font-metadata text-metadata uppercase tracking-wider text-ink-muted">
               Feedback records
            </span>
            <span className="inline-flex items-center gap-1 font-code-xs text-code-xs text-issue-red bg-issue-soft px-1.5 py-0.5 rounded">
              <span className="material-symbols-outlined text-[14px]">trending_up</span> +18.4%
            </span>
          </div>
          <div className="flex items-baseline gap-space-sm mt-space-sm">
             <span className="font-code-sm text-[32px] leading-tight font-semibold text-ink-primary">{activeCount}</span>
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
             <span className="font-code-sm text-[32px] leading-tight font-semibold text-ink-primary">—</span>
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
            <span className="font-code-xs text-code-xs bg-dataset-soft text-dataset-purple px-1.5 py-0.5 rounded font-semibold">
              Priority
            </span>
          </div>
          <div className="flex items-baseline gap-space-sm mt-space-sm">
             <span className="font-code-sm text-[32px] leading-tight font-semibold text-ink-primary">{goldenCount}</span>
             <span className="font-label-sm text-label-sm text-ink-muted">golden candidates</span>
          </div>
          <div className="flex items-center gap-space-xs mt-space-sm text-body-sm font-body-sm text-ink-secondary">
            <span className="material-symbols-outlined text-[16px] text-dataset-purple">verified</span>
            <span>Zero-day compliance drift detected</span>
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
             <span className="font-code-sm text-[32px] leading-tight font-semibold text-ink-primary">—</span>
             <span className="font-label-sm text-label-sm text-ink-muted">No review timing yet</span>
          </div>
          <div className="flex items-center gap-space-xs mt-space-sm text-body-sm font-body-sm text-evidence-teal">
            <span className="material-symbols-outlined text-[16px]">check_circle</span>
            <span>Within SLA threshold</span>
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
            <span className="px-2 py-0.5 bg-issue-soft text-issue-red font-code-xs text-code-xs font-semibold rounded-full">
               {activeCount} active
            </span>
          </div>
          <p className="font-body-md text-body-md text-ink-secondary mt-0.5">
             Feedback submitted by users is stored in BigQuery and can be triaged into reviewed golden candidates.
          </p>
        </div>

        <div className="flex items-center gap-space-sm self-start lg:self-center flex-wrap">
          {/* Batch Actions Dropdown */}
          <div className="relative inline-block text-left">
            <button
              type="button"
              onClick={() => setSelectedIds(filteredItems.map((item) => item.id))}
              className="h-9 px-3.5 bg-surface text-ink-primary hover:bg-state-gray-soft font-label-md text-label-md rounded-lg shadow-sm flex items-center gap-space-xs transition-all cursor-pointer border border-surface-border"
            >
              <span className="material-symbols-outlined text-[18px] text-ink-secondary">assignment_ind</span>
              <span>Batch assign</span>
              <span className="material-symbols-outlined text-[16px] text-ink-muted">expand_more</span>
            </button>
          </div>

          {/* Export CSV */}
          <button
            type="button"
              onClick={exportCsv}
            className="h-9 px-3.5 bg-surface text-ink-primary hover:bg-state-gray-soft font-label-md text-label-md rounded-lg shadow-sm flex items-center gap-space-xs transition-all cursor-pointer border border-surface-border"
          >
            <span className="material-symbols-outlined text-[18px] text-ink-secondary">download</span>
            <span>Export CSV</span>
          </button>

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

      {/* Filter & Precision Search Bar */}
      <div className="bg-surface rounded-xl p-space-md shadow-sm mb-space-md flex flex-col gap-space-md border border-surface-border/50">
        <div className="flex flex-wrap items-center gap-space-sm">
          {/* State Filter */}
          <div className="flex items-center gap-1">
            <span className="font-metadata text-metadata text-ink-muted uppercase">State:</span>
            <select
              value={stateFilter}
              onChange={(e) => onFiltersChange({ state: e.target.value, severity: severityFilter, verdict: verdictFilter, rootCause: rcaFilter })}
              className="h-8 px-2.5 bg-surface-container-low hover:bg-surface-container text-ink-primary font-label-sm text-label-sm rounded-lg border border-transparent focus:outline-none cursor-pointer"
            >
              <option value="All">All states ({activeCount})</option>
              <option value="Submitted">Submitted</option>
              <option value="Triaged">Triaged</option>
              <option value="Evidence review">Evidence review</option>
              <option value="Golden candidate">Golden candidate</option>
              <option value="Approved for dataset">Approved for dataset</option>
              <option value="Needs more information">Needs more information</option>
              <option value="Duplicate">Duplicate</option>
              <option value="Rejected">Rejected</option>
            </select>
          </div>

          {/* Severity Filter */}
          <div className="flex items-center gap-1">
            <span className="font-metadata text-metadata text-ink-muted uppercase">Severity:</span>
            <select
              value={severityFilter}
              onChange={(e) => onFiltersChange({ state: stateFilter, severity: e.target.value, verdict: verdictFilter, rootCause: rcaFilter })}
              className="h-8 px-2.5 bg-surface-container-low hover:bg-surface-container text-ink-primary font-label-sm text-label-sm rounded-lg border border-transparent focus:outline-none cursor-pointer"
            >
              <option value="All">All</option>
              <option value="High">High</option>
              <option value="Med">Medium</option>
              <option value="Low">Low</option>
            </select>
          </div>

          {/* Verdict Filter Pill */}
          <div className="flex items-center gap-1">
            <span className="font-metadata text-metadata text-ink-muted uppercase">Verdict:</span>
            <select
              value={verdictFilter}
              onChange={(e) => onFiltersChange({ state: stateFilter, severity: severityFilter, verdict: e.target.value, rootCause: rcaFilter })}
              className="h-8 px-2.5 bg-surface-container-low hover:bg-surface-container text-ink-primary font-label-sm text-label-sm rounded-lg border border-transparent focus:outline-none cursor-pointer"
            >
              <option value="All">All verdicts</option>
              <option value="Incorrect">Incorrect</option>
              <option value="Partially correct">Partially correct</option>
              <option value="Unsafe or misleading">Unsafe / Misleading</option>
              <option value="Not specified">Not specified</option>
            </select>
          </div>

          {/* RCA Filter */}
          <div className="flex items-center gap-1">
            <span className="font-metadata text-metadata text-ink-muted uppercase">RCA:</span>
            <select
              value={rcaFilter}
              onChange={(e) => onFiltersChange({ state: stateFilter, severity: severityFilter, verdict: verdictFilter, rootCause: e.target.value })}
              className="h-8 px-2.5 bg-surface-container-low hover:bg-surface-container text-ink-primary font-label-sm text-label-sm rounded-lg border border-transparent focus:outline-none cursor-pointer"
            >
              <option value="All">All root causes</option>
              <option value="Retrieval failure">Retrieval failure</option>
              <option value="Reasoning error">Reasoning error</option>
              <option value="Wrong region / scope">Wrong region / scope</option>
              <option value="Table interpretation error">Table interpretation error</option>
              <option value="Citation failure">Citation failure</option>
              <option value="Knowledge / source gap">Knowledge gap</option>
            </select>
          </div>

          {/* Spacer */}
          <div className="hidden xl:flex flex-1"></div>

          {/* Reset Filters */}
          <div className="flex items-center gap-space-sm ml-auto">
            <div className="flex items-center gap-1 px-2 py-1 bg-surface-container-high rounded font-code-xs text-code-xs text-ink-secondary">
              <span className="w-1.5 h-1.5 rounded-full bg-primary-container"></span>
              <span>{filteredItems.length} items shown</span>
            </div>
            <button
              type="button"
              onClick={() => {
                 onFiltersChange({ state: 'All', severity: 'All', verdict: 'All', rootCause: 'All' });
                 onPageChange(1);
                 onSearchQueryChange('');
              }}
              className="text-ink-secondary hover:text-issue-red font-label-sm text-label-sm transition-colors cursor-pointer flex items-center gap-0.5"
            >
              <span>Clear filters</span>
            </button>
          </div>
        </div>

        {/* Freeform Search Bar */}
        <div className="relative w-full">
          <span className="material-symbols-outlined absolute left-3 top-2.5 text-ink-muted text-[18px]">search</span>
          <input
            className="w-full h-10 pl-9 pr-24 bg-state-gray-soft/40 hover:bg-state-gray-soft/70 focus:bg-surface rounded-lg font-body-sm text-body-sm text-ink-primary placeholder:text-ink-muted focus:outline-none border border-transparent focus:border-primary-container transition-all"
            placeholder="Filter by feedback title, run ID, question, or reporter..."
            type="text"
            value={searchQuery}
            onChange={(e) => { onPageChange(1); onSearchQueryChange(e.target.value); }}
          />
          {searchQuery && (
            <button
              type="button"
              onClick={() => { onPageChange(1); onSearchQueryChange(''); }}
              className="absolute right-3 top-2.5 font-code-xs text-code-xs text-ink-muted hover:text-ink-primary bg-surface px-1.5 py-0.5 rounded shadow-sm"
            >
              clear
            </button>
          )}
        </div>
      </div>

      {/* Main Dense Enterprise Data Table Container */}
      <div className="bg-surface rounded-xl shadow-sm overflow-hidden flex flex-col border border-surface-border">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse min-w-[1100px]">
            {/* Sticky Header */}
            <thead className="bg-surface-container-low/80 sticky top-0 z-10 backdrop-blur">
              <tr className="font-metadata text-metadata uppercase tracking-wider text-ink-muted border-b border-surface-container">
                <th className="py-3 px-space-md w-10">
                  <input
                    className="rounded w-4 h-4 text-primary-container cursor-pointer accent-primary-container"
                    type="checkbox"
                    checked={selectedIds.length > 0 && selectedIds.length === filteredItems.length}
                    onChange={toggleSelectAll}
                  />
                </th>
                <th className="py-3 px-space-sm w-28">Severity</th>
                <th className="py-3 px-space-md min-w-[280px]">Feedback &amp; Excerpt</th>
                <th className="py-3 px-space-md w-36">Agent / Run ID</th>
                <th className="py-3 px-space-md w-36">User Verdict</th>
                <th className="py-3 px-space-md min-w-[220px]">Suggested RCA (Root Cause)</th>
                <th className="py-3 px-space-md w-36">State</th>
                <th className="py-3 px-space-md w-32">Reporter</th>
                <th className="py-3 pr-space-md pl-space-sm text-right w-24">Action</th>
              </tr>
            </thead>

            <tbody className="divide-y divide-surface-container-low font-body-sm text-body-sm text-ink-primary">
              {filteredItems.map((item) => {
                const isSelected = selectedIds.includes(item.id);
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
                      <div className="flex flex-col gap-0.5">
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

                    <td className="py-3 px-space-md">
                      <div className="flex flex-col">
                        <span className="font-metadata text-metadata text-ink-secondary">{item.agentName}</span>
                        <div className="flex items-center gap-1 group/mono">
                          <span className="font-code-xs text-code-xs text-ink-muted group-hover/mono:text-ink-primary font-mono">
                            {item.runId || 'No linked run'}
                          </span>
                          {item.runId && <button
                            type="button"
                            onClick={() => copyRunId(item.runId || '')}
                            className="text-ink-muted hover:text-ink-primary transition-opacity cursor-pointer"
                            title="Copy Run ID"
                          >
                            <span className="material-symbols-outlined text-[13px]">
                              {copiedId === item.runId ? 'check' : 'content_copy'}
                            </span>
                          </button>}
                        </div>
                      </div>
                    </td>

                    <td className="py-3 px-space-md whitespace-nowrap">
                      {item.userVerdict === 'Incorrect' && (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-issue-soft text-issue-red font-label-sm text-label-sm">
                          <span className="material-symbols-outlined text-[14px]">cancel</span>
                          Incorrect
                        </span>
                      )}
                      {item.userVerdict === 'Partially correct' && (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-review-soft text-review-amber font-label-sm text-label-sm">
                          <span className="material-symbols-outlined text-[14px]">help_center</span>
                          Partially correct
                        </span>
                      )}
                      {item.userVerdict === 'Unsafe or misleading' && (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-issue-soft text-issue-red font-label-sm text-label-sm font-medium">
                          <span className="material-symbols-outlined text-[14px]">warning</span>
                          Unsafe
                        </span>
                      )}
                      {item.userVerdict === 'Not specified' && (
                        <span className="inline-flex items-center gap-1 rounded bg-state-gray-soft px-2 py-0.5 font-label-sm text-ink-secondary">
                          <span className="material-symbols-outlined text-[14px]">remove</span>
                          Not specified
                        </span>
                      )}
                    </td>

                    <td className="py-3 px-space-md whitespace-nowrap">
                      <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-surface-container-high/60 font-code-xs text-code-xs text-ink-secondary">
                         <span className="font-metadata text-metadata text-tertiary font-semibold uppercase">{item.confirmedRca ? 'Human' : 'AI'}</span>
                         <span className="text-ink-primary font-medium">{item.confirmedRca || item.suggestedRca || 'Unclassified'}</span>
                        <span className="text-ink-muted font-normal">·</span>
                        <span className="font-semibold text-evidence-teal">
                           {item.suggestedRcaConfidence == null ? '—' : item.suggestedRcaConfidence.toFixed(2)}
                        </span>
                      </div>
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
                      {item.state === 'Golden candidate' && (
                        <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded bg-dataset-soft text-dataset-purple font-label-sm text-label-sm font-medium">
                          <span className="w-1.5 h-1.5 rounded-full bg-dataset-purple"></span>
                          Golden candidate
                        </span>
                      )}
                      {!['Submitted', 'Triaged', 'Evidence review', 'Golden candidate'].includes(item.state) && (
                        <span className="inline-flex items-center rounded bg-state-gray-soft px-2 py-0.5 font-label-sm text-ink-secondary">{item.state}</span>
                      )}
                    </td>

                    <td className="py-3 px-space-md whitespace-nowrap">
                      <div className="flex flex-col">
                        <span className="font-label-sm text-label-sm text-ink-primary truncate max-w-[110px]">
                          {item.reporter ? item.reporter.split('@')[0] : 'Unknown reporter'}
                        </span>
                        <span className="font-metadata text-metadata text-ink-muted">{item.reportedTime}</span>
                      </div>
                    </td>

                    <td className="py-3 pr-space-md pl-space-sm text-right whitespace-nowrap">
                      <button
                        type="button"
                        onClick={() => onNavigate('feedback-detail', item.id)}
                        className="px-2.5 py-1 bg-surface-container-low hover:bg-primary-container hover:text-on-primary text-ink-primary font-label-sm text-label-sm rounded transition-all cursor-pointer flex items-center gap-1 ml-auto"
                      >
                        <span>Review</span>
                        <span className="material-symbols-outlined text-[14px]">arrow_forward</span>
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Table Footer / Pagination */}
        <div className="py-space-sm px-space-md bg-surface border-t border-surface-container flex flex-col sm:flex-row items-center justify-between gap-space-sm">
          <div className="flex items-center gap-space-md">
            <span className="font-body-sm text-body-sm text-ink-muted">Showing {total ? (page - 1) * pageSize + 1 : 0}–{Math.min(page * pageSize, total)} of {total} items</span>
            <div className="hidden sm:flex items-center gap-1.5">
              <span className="font-metadata text-metadata text-ink-muted uppercase">Rows per page:</span>
              <select className="bg-surface-container-low text-ink-primary font-label-sm text-label-sm rounded px-1.5 py-0.5 focus:outline-none">
                <option>10</option>
                <option defaultValue="25">25</option>
                <option>50</option>
              </select>
            </div>
          </div>

          <div className="flex items-center gap-space-xs">
            <button onClick={() => onPageChange(1)} className="h-8 px-2.5 rounded bg-surface text-ink-muted hover:text-ink-primary hover:bg-state-gray-soft disabled:opacity-40 transition-colors" disabled={page <= 1} type="button">
              <span className="material-symbols-outlined text-[18px]">first_page</span>
            </button>
            <button onClick={() => onPageChange(Math.max(1, page - 1))} className="h-8 px-2.5 rounded bg-surface text-ink-muted hover:text-ink-primary hover:bg-state-gray-soft disabled:opacity-40 transition-colors" disabled={page <= 1} type="button">
              <span className="material-symbols-outlined text-[18px]">chevron_left</span>
            </button>
            <div className="flex items-center gap-1 px-2 font-code-xs text-code-xs text-ink-primary">
              <span className="font-bold">{page}</span>
              <span className="text-ink-muted">/</span>
              <span>{Math.max(1, Math.ceil(total / pageSize))}</span>
            </div>
            <button onClick={() => onPageChange(Math.min(Math.max(1, Math.ceil(total / pageSize)), page + 1))} className="h-8 px-2.5 rounded bg-surface text-ink-secondary hover:text-ink-primary hover:bg-state-gray-soft disabled:opacity-40 transition-colors cursor-pointer" disabled={page >= Math.ceil(total / pageSize)} type="button">
              <span className="material-symbols-outlined text-[18px]">chevron_right</span>
            </button>
            <button onClick={() => onPageChange(Math.max(1, Math.ceil(total / pageSize)))} className="h-8 px-2.5 rounded bg-surface text-ink-secondary hover:text-ink-primary hover:bg-state-gray-soft disabled:opacity-40 transition-colors cursor-pointer" disabled={page >= Math.ceil(total / pageSize)} type="button">
              <span className="material-symbols-outlined text-[18px]">last_page</span>
            </button>
          </div>
        </div>
      </div>

      {/* Floating / Docked Bulk Selection Action Bar */}
      {selectedIds.length > 0 && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-30 bg-inverse-surface text-inverse-on-surface px-space-md py-space-sm rounded-xl shadow-xl flex items-center gap-space-md border border-surface-border/20 backdrop-blur animate-in fade-in slide-in-from-bottom-2">
          <div className="flex items-center gap-space-sm border-r border-state-gray/40 pr-space-md">
            <span className="w-2 h-2 rounded-full bg-evidence-teal animate-ping"></span>
            <span className="font-label-md text-label-md font-semibold">
              {selectedIds.length} item{selectedIds.length > 1 ? 's' : ''} selected
            </span>
          </div>

          <div className="flex items-center gap-space-xs">
            <button
              type="button"
               onClick={() => setSelectedIds([])}
              className="h-8 px-3 rounded-lg bg-surface/10 hover:bg-surface/20 text-inverse-on-surface font-label-sm text-label-sm flex items-center gap-1.5 transition-all cursor-pointer"
            >
              <span className="material-symbols-outlined text-[16px]">person_add</span>
              <span>Assign reviewer</span>
            </button>

            <button
              type="button"
              onClick={() => void updateSelected('Duplicate')}
              className="h-8 px-3 rounded-lg bg-surface/10 hover:bg-surface/20 text-inverse-on-surface font-label-sm text-label-sm flex items-center gap-1.5 transition-all cursor-pointer"
            >
              <span className="material-symbols-outlined text-[16px]">content_copy</span>
              <span>Mark duplicate</span>
            </button>

            <button
              type="button"
              onClick={() => void updateSelected('Triaged').then(() => onNavigate('triage-queue'))}
              className="h-8 px-3 rounded-lg bg-primary-container hover:bg-primary text-on-primary font-label-sm text-label-sm flex items-center gap-1.5 transition-all cursor-pointer"
            >
              <span className="material-symbols-outlined text-[16px]">low_priority</span>
              <span>Move to triage</span>
            </button>

            <button
              type="button"
              onClick={exportCsv}
              className="h-8 px-3 rounded-lg bg-surface/10 hover:bg-surface/20 text-inverse-on-surface font-label-sm text-label-sm flex items-center gap-1.5 transition-all cursor-pointer"
            >
              <span className="material-symbols-outlined text-[16px]">file_download</span>
              <span>Export selected</span>
            </button>
          </div>

          <div className="pl-space-sm">
            <button
              type="button"
              onClick={() => setSelectedIds([])}
              className="text-state-gray hover:text-inverse-on-surface p-1 rounded transition-colors cursor-pointer"
              title="Deselect all"
            >
              <span className="material-symbols-outlined text-[16px]">close</span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
