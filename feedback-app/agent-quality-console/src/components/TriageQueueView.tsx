import React, { useEffect, useState } from 'react';
import { AnswerMarkdown } from './AnswerMarkdown';
import { FeedbackItem, ViewPath } from '../types';
import { formatRcaLabel } from '../utils/formatRcaLabel';
import { ArrowUpRight } from 'lucide-react';
import { ActionButton } from './ActionButton';

interface TriageQueueViewProps {
  items: FeedbackItem[];
  isLoading?: boolean;
  onNavigate: (view: ViewPath, targetId?: string) => void;
  onUpdateItem: (id: string, updates: Partial<FeedbackItem>) => Promise<void>;
  onSaveRca: (id: string, updates: Record<string, unknown>) => Promise<void>;
  onSuggestRca: (id: string) => Promise<FeedbackItem | void>;
}

export const TriageQueueView: React.FC<TriageQueueViewProps> = ({
  items,
  isLoading = false,
  onNavigate,
  onUpdateItem,
  onSaveRca,
  onSuggestRca,
}) => {
  const triageItems = items.filter((item) => ['Submitted', 'Triaged', 'Evidence review', 'Review complete'].includes(item.state));
  const [selectedItemId, setSelectedItemId] = useState<string | null>(triageItems[0]?.id || items[0]?.id || null);
  const selectedItem = items.find((item) => item.id === selectedItemId) || triageItems[0] || items[0] || null;
  const [actionSuccessToast, setActionSuccessToast] = useState<string | null>(null);
  const [rootCause, setRootCause] = useState(selectedItem?.confirmedRca || selectedItem?.suggestedRca || '');
  const [subcategory, setSubcategory] = useState(selectedItem?.defectSubCategory || selectedItem?.suggestedRcaSubcategory || '');
  const [reviewerNotes, setReviewerNotes] = useState(selectedItem?.reviewerNotes || '');
  const [recommendedFix, setRecommendedFix] = useState(selectedItem?.recommendedFix || '');
  const [isSavingRca, setIsSavingRca] = useState(false);

  useEffect(() => {
    setRootCause(selectedItem?.confirmedRca || selectedItem?.suggestedRca || '');
    setSubcategory(selectedItem?.defectSubCategory || selectedItem?.suggestedRcaSubcategory || '');
    setReviewerNotes(selectedItem?.reviewerNotes || '');
    setRecommendedFix(selectedItem?.recommendedFix || '');
  }, [selectedItem?.id, selectedItem?.confirmedRca, selectedItem?.defectSubCategory, selectedItem?.suggestedRca, selectedItem?.suggestedRcaSubcategory, selectedItem?.reviewerNotes, selectedItem?.recommendedFix]);

  if (isLoading && items.length === 0) return <TriageQueueSkeleton />;

  const showToast = (msg: string) => {
    setActionSuccessToast(msg);
    setTimeout(() => setActionSuccessToast(null), 2500);
  };

  const handleApproveForReview = async (item: FeedbackItem) => {
    const nextState = item.state === 'Submitted' ? 'Triaged' : 'Evidence review';
    try {
      await onUpdateItem(item.id, { state: nextState });
      showToast(nextState === 'Triaged' ? `Marked ${item.id} as triaged` : `Started evidence review for ${item.id}`);
    } catch (error) {
      showToast(error instanceof Error ? error.message : 'Could not update feedback');
    }
  };

  const saveManualRca = async () => {
    if (!selectedItem || !rootCause) return;
    setIsSavingRca(true);
    try {
      await onSaveRca(selectedItem.id, {
        confirmed_rca: rootCause,
        subcategory: subcategory || null,
        reviewer_notes: reviewerNotes,
        recommended_fix: recommendedFix,
      });
      showToast(`Saved RCA changes for ${selectedItem.id}`);
    } catch (error) {
      showToast(error instanceof Error ? error.message : 'Could not save root cause');
    } finally {
      setIsSavingRca(false);
    }
  };

  return (
    <div className="flex flex-col w-full gap-space-lg animate-in fade-in duration-200">
      {actionSuccessToast && (
        <div className="fixed top-18 right-8 z-50 flex items-center gap-space-sm px-space-md py-space-sm bg-surface shadow-xl rounded-xl border border-surface-border animate-in fade-in">
          <span className="material-symbols-outlined text-evidence-teal text-[18px]">verified</span>
          <span className="font-label-md text-ink-primary font-medium">{actionSuccessToast}</span>
        </div>
      )}

      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-space-md">
        <div>
          <div className="flex items-center gap-space-sm mb-1">
            <span className="px-2 py-0.5 rounded-full bg-indigo-soft text-primary font-label-sm font-semibold">
              Workflow Gate
            </span>
            <span className="font-metadata uppercase tracking-wider text-ink-muted">Triage &amp; Taxonomy</span>
          </div>
          <h1 className="font-headline-lg text-headline-lg text-ink-primary tracking-tight font-semibold">
            Triage queue
          </h1>
          <p className="font-body-md text-body-md text-ink-secondary mt-0.5">
            Review source evidence and record a human-confirmed root cause before routing feedback into evaluation curation.
          </p>
        </div>

        <div className="flex items-center gap-2">
          {isLoading && <span className="inline-flex items-center gap-2 font-metadata text-ink-muted"><span className="h-2 w-2 animate-pulse rounded-full bg-primary-container" />Refreshing queue</span>}
          <span className="px-3 py-1.5 bg-surface rounded-lg border border-surface-border text-label-sm text-ink-secondary font-medium">
            Queue: <strong className="text-ink-primary">{triageItems.length} items</strong> pending triage
          </span>
        </div>
      </div>

      {/* 2-Column Split: Queue List & Inspection Drawer */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-space-lg items-start">
        {/* Left: Triage List (5 cols) */}
        <div className="lg:col-span-5 flex flex-col gap-space-sm">
          {triageItems.length === 0 ? (
            <div className="bg-surface rounded-xl p-space-xl text-center border border-surface-border">
              <span className="material-symbols-outlined text-evidence-teal text-[36px]">check_circle</span>
              <h3 className="font-title-md text-ink-primary mt-2 font-semibold">Queue Zero reached</h3>
              <p className="font-body-sm text-ink-muted mt-1">All incoming feedback reports have been routed.</p>
            </div>
          ) : (
            triageItems.map((item) => {
              const isSelected = selectedItem?.id === item.id;
              return (
                <div
                  key={item.id}
                  onClick={() => setSelectedItemId(item.id)}
                  className={`p-space-md rounded-xl border transition-all cursor-pointer flex flex-col gap-2 ${
                    isSelected
                      ? 'bg-indigo-soft/40 border-primary shadow-sm'
                      : 'bg-surface border-surface-border hover:border-outline-variant'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1.5 font-mono">
                      <span className="font-code-sm font-semibold text-primary">{item.id}</span>
                      <span className="text-outline-variant">·</span>
                       <span className="font-code-xs text-ink-muted">{item.runId?.slice(0, 10) || 'No run link'}</span>
                    </div>

                    <span
                       className={`px-2 py-0.5 rounded-full font-label-sm font-semibold ${
                        item.severity === 'High'
                          ? 'bg-issue-soft text-issue-red'
                          : 'bg-review-soft text-review-amber'
                      }`}
                    >
                      {item.severity}
                    </span>
                  </div>

                  <h3 className="font-title-md text-ink-primary font-semibold line-clamp-1">{item.title}</h3>
                  <p className="font-body-sm text-ink-muted line-clamp-2">{item.excerpt}</p>

                  <div className="flex items-center justify-between pt-2 border-t border-surface-border/50 text-metadata">
                    <span className="px-2 py-0.5 rounded bg-surface-container font-medium text-ink-secondary">
                       AI RCA: {item.suggestedRca || 'Unclassified'} ({item.suggestedRcaConfidence == null ? '—' : `${(item.suggestedRcaConfidence * 100).toFixed(0)}%`})
                    </span>
                    <span className="text-ink-muted">{item.reportedTime}</span>
                  </div>
                </div>
              );
            })
          )}
        </div>

        {/* Right: Inspection & Action Panel (7 cols) */}
        {selectedItem && (
          <div className="lg:col-span-7 bg-surface rounded-xl p-space-lg shadow-sm border border-surface-border flex flex-col gap-space-md">
            <div className="flex items-start justify-between pb-space-sm border-b border-surface-border">
              <div>
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-code-sm font-bold text-primary font-mono">{selectedItem.id}</span>
                   <span className="px-2 py-0.5 rounded bg-surface-container font-label-sm font-medium">
                    {selectedItem.agentName}
                  </span>
                </div>
                <h2 className="font-headline-sm text-headline-sm text-ink-primary font-semibold">
                  {selectedItem.title}
                </h2>
              </div>

              <ActionButton label="Evidence trace" aria-label="Full Evidence Trace" compactLabel="Evidence" icon={<ArrowUpRight />} size="sm" tone="soft"
                onClick={() => onNavigate('feedback-detail', selectedItem.id)}
              />
            </div>

            {/* Prompt & Answer */}
            <div className="flex flex-col gap-2">
              <span className="font-metadata uppercase text-ink-muted font-semibold">Reported Prompt</span>
              <div className="p-3 bg-canvas rounded-lg text-body-sm text-ink-primary border border-surface-border">
                "{selectedItem.prompt}"
              </div>
            </div>

            <div className="flex flex-col gap-2">
              <span className="font-metadata uppercase text-ink-muted font-semibold">Reported Answer</span>
                <AnswerMarkdown content={selectedItem.generatedAnswer || 'No answer snapshot was attached to this feedback.'} />
            </div>

            <div className="p-space-md rounded-xl bg-surface-container-low border border-surface-border flex flex-col gap-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-label-md text-ink-primary font-semibold flex items-center gap-1.5">
                  <span className="material-symbols-outlined text-primary text-[18px]">fact_check</span>
                  On-demand root-cause analysis
                </span>
                <button type="button" onClick={() => void onSuggestRca(selectedItem.id).then((updated) => {
                  if (updated) {
                    setRootCause(updated.confirmedRca || updated.suggestedRca || '');
                    setSubcategory(updated.defectSubCategory || updated.suggestedRcaSubcategory || '');
                  }
                  showToast(updated?.suggestedRcaReviewRequired === false ? 'RCA auto-classified. Edit it if needed.' : 'RCA result ready. Review or edit the classification.');
                }).catch((error: Error) => showToast(error.message))} className="rounded-lg bg-primary-container px-3 py-2 font-label-sm font-semibold text-on-primary hover:bg-primary">Run RCA</button>
              </div>
              {selectedItem.suggestedRca && <div className="rounded-lg border border-primary/10 bg-surface p-3 text-body-sm text-ink-secondary">
                <span className="font-label-sm font-semibold text-primary">Detected: {formatRcaLabel(selectedItem.suggestedRca)}{selectedItem.suggestedRcaSubcategory ? ` · ${formatRcaLabel(selectedItem.suggestedRcaSubcategory)}` : ''}</span>
                {selectedItem.suggestedRcaConfidence != null && <span className="ml-2 font-metadata">Confidence {(selectedItem.suggestedRcaConfidence * 100).toFixed(0)}%</span>}
                <span className={`ml-2 rounded px-2 py-0.5 font-metadata font-semibold ${selectedItem.suggestedRcaReviewRequired === false ? 'bg-evidence-soft text-evidence-teal' : 'bg-review-soft text-review-amber'}`}>
                  {selectedItem.suggestedRcaStatus === 'reviewer_classified' ? 'Manually classified' : selectedItem.suggestedRcaReviewRequired === false ? 'Auto-classified · editable' : 'Review recommended'}
                </span>
                <p className="mt-1">{selectedItem.suggestedRcaRationale || 'Review the linked document passages before selecting the final category.'}</p>
              </div>}
              <div className="grid gap-3 sm:grid-cols-2">
                  <label className="text-label-sm text-ink-secondary">RCA category
                  <select value={rootCause} onChange={(event) => setRootCause(event.target.value)} className="mt-1 w-full rounded-lg border border-surface-border bg-surface p-2 text-body-sm text-ink-primary">
                    <option value="">Choose root cause</option>
                    <option value="correct_but_differently_worded">Correct, differently worded</option>
                    <option value="factual_error">Factual error</option>
                    <option value="missing_required_content">Missing required content</option>
                    <option value="incomplete_answer">Incomplete answer</option>
                    <option value="wrong_region_or_scope">Wrong region or scope</option>
                    <option value="table_interpretation_error">Table interpretation error</option>
                    <option value="image_ocr_error">Image/OCR error</option>
                    <option value="retrieval_failure">Retrieval failure</option>
                    <option value="source_gap">Knowledge/source gap</option>
                    <option value="reasoning_error">Reasoning error</option>
                    <option value="citation_failure">Citation failure</option>
                    <option value="outdated_content">Outdated content</option>
                    <option value="ambiguous_question">Ambiguous question</option>
                    <option value="tool_error">Tool error</option>
                    <option value="format_mismatch">Format mismatch</option>
                    <option value="unsupported_expected_answer">Unsupported expected answer</option>
                    <option value="insufficient_evidence">Insufficient evidence</option>
                    <option value="other">Other</option>
                  </select>
                </label>
                  <label className="text-label-sm text-ink-secondary">RCA subcategory
                    <input value={subcategory} onChange={(event) => setSubcategory(event.target.value)} placeholder="Set or edit the specific defect" className="mt-1 w-full rounded-lg border border-surface-border bg-surface p-2 text-body-sm text-ink-primary" />
                </label>
              </div>
              <label className="text-label-sm text-ink-secondary">Reviewer rationale
                <textarea value={reviewerNotes} onChange={(event) => setReviewerNotes(event.target.value)} rows={3} placeholder="What evidence supports the root-cause classification?" className="mt-1 w-full rounded-lg border border-surface-border bg-surface p-2 text-body-sm text-ink-primary" />
              </label>
              <label className="text-label-sm text-ink-secondary">Recommended fix
                <textarea value={recommendedFix} onChange={(event) => setRecommendedFix(event.target.value)} rows={2} placeholder="Optional remediation" className="mt-1 w-full rounded-lg border border-surface-border bg-surface p-2 text-body-sm text-ink-primary" />
              </label>
              <div className="flex justify-end">
                <button type="button" disabled={!rootCause || isSavingRca} onClick={() => void saveManualRca()} className="rounded-lg bg-primary-container px-3.5 py-2 text-label-sm font-semibold text-on-primary disabled:opacity-50">
                  {isSavingRca ? 'Saving…' : 'Save RCA changes'}
                </button>
              </div>
            </div>

            {/* Triage Routing Actions */}
            <div className="pt-space-md border-t border-surface-border flex items-center justify-between gap-space-sm flex-wrap">
              <button
                type="button"
                  onClick={() => void onUpdateItem(selectedItem.id, { state: 'Rejected' }).then(() => showToast(`Marked ${selectedItem.id} as out-of-scope.`)).catch((error: Error) => showToast(error.message))}
                className="px-3.5 py-2 rounded-lg bg-issue-soft hover:bg-red-100 text-issue-red font-label-md transition-colors cursor-pointer"
              >
                Reject as Out-of-Scope
              </button>

              <div className="flex items-center gap-space-sm">
                {['Submitted', 'Triaged'].includes(selectedItem.state) ? <button
                  type="button"
                  onClick={() => void handleApproveForReview(selectedItem)}
                  className="px-4 py-2 rounded-lg bg-primary-container hover:bg-primary text-on-primary font-label-md font-semibold transition-colors shadow-sm flex items-center gap-1.5 cursor-pointer"
                >
                  <span className="material-symbols-outlined text-[18px]">{selectedItem.state === 'Submitted' ? 'task_alt' : 'fact_check'}</span>
                  <span>{selectedItem.state === 'Submitted' ? 'Mark triaged' : 'Start evidence review'}</span>
                </button> : <button
                  type="button"
                  onClick={() => onNavigate('feedback-detail', selectedItem.id)}
                  className="px-4 py-2 rounded-lg bg-primary-container hover:bg-primary text-on-primary font-label-md font-semibold transition-colors shadow-sm flex items-center gap-1.5 cursor-pointer"
                >
                  <span className="material-symbols-outlined text-[18px]">open_in_new</span>
                  <span>{selectedItem.state === 'Review complete' ? 'Choose golden dataset' : 'Continue review'}</span>
                </button>}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

function TriageQueueSkeleton() {
  return <div className="flex flex-col gap-space-lg" role="status" aria-label="Loading triage queue">
    <div className="flex items-end justify-between"><div className="space-y-2"><div className="skeleton h-3 w-28" /><div className="skeleton h-8 w-48" /><div className="skeleton h-4 w-96 max-w-full" /></div><div className="skeleton h-8 w-36 rounded-lg" /></div>
    <div className="grid gap-space-lg lg:grid-cols-12">
      <div className="flex flex-col gap-2 lg:col-span-5">{Array.from({ length: 5 }, (_, index) => <div key={index} className="skeleton h-28 rounded-xl" />)}</div>
      <div className="skeleton min-h-[520px] rounded-xl lg:col-span-7" />
    </div>
  </div>;
}
