import React, { useState } from 'react';
import { FeedbackItem, ViewPath } from '../types';

interface TriageQueueViewProps {
  items: FeedbackItem[];
  onNavigate: (view: ViewPath, targetId?: string) => void;
  onUpdateItem: (id: string, updates: Partial<FeedbackItem>) => Promise<void>;
  onPromoteCandidate: (item: FeedbackItem) => Promise<void>;
}

export const TriageQueueView: React.FC<TriageQueueViewProps> = ({
  items,
  onNavigate,
  onUpdateItem,
  onPromoteCandidate,
}) => {
  const triageItems = items.filter((i) => i.state === 'Triaged' || i.state === 'Submitted');
  const [selectedItem, setSelectedItem] = useState<FeedbackItem>(triageItems[0] || items[0]);
  const [actionSuccessToast, setActionSuccessToast] = useState<string | null>(null);

  const showToast = (msg: string) => {
    setActionSuccessToast(msg);
    setTimeout(() => setActionSuccessToast(null), 2500);
  };

  const handleApproveForReview = async (item: FeedbackItem) => {
    try {
      await onUpdateItem(item.id, { state: 'Evidence review' });
      showToast(`Moved ${item.id} to Evidence Review`);
    } catch (error) {
      showToast(error instanceof Error ? error.message : 'Could not update feedback');
    }
  };

  const handlePromoteToGolden = async (item: FeedbackItem) => {
    try {
      await onPromoteCandidate(item);
      showToast(`Created a golden candidate from ${item.id}`);
    } catch (error) {
      showToast(error instanceof Error ? error.message : 'Could not create golden candidate');
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
            <span className="px-2 py-0.5 rounded-full bg-indigo-soft text-primary font-code-xs font-semibold">
              Workflow Gate
            </span>
            <span className="font-metadata uppercase tracking-wider text-ink-muted">Triage &amp; Taxonomy</span>
          </div>
          <h1 className="font-headline-lg text-headline-lg text-ink-primary tracking-tight font-semibold">
            Triage queue
          </h1>
          <p className="font-body-md text-body-md text-ink-secondary mt-0.5">
            Rapidly classify automated root causes, review heuristic tags, and route to domain SMEs.
          </p>
        </div>

        <div className="flex items-center gap-2">
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
                  onClick={() => setSelectedItem(item)}
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
                      className={`px-2 py-0.5 rounded-full font-code-xs font-semibold ${
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
                  <span className="px-2 py-0.5 rounded bg-surface-container font-code-xs font-medium">
                    {selectedItem.agentName}
                  </span>
                </div>
                <h2 className="font-headline-sm text-headline-sm text-ink-primary font-semibold">
                  {selectedItem.title}
                </h2>
              </div>

              <button
                type="button"
                onClick={() => onNavigate('feedback-detail', selectedItem.id)}
                className="px-3 py-1.5 rounded-lg bg-surface-container-low hover:bg-state-gray-soft text-primary font-label-sm font-medium flex items-center gap-1 cursor-pointer"
              >
                <span>Full Evidence Trace</span>
                <span className="material-symbols-outlined text-[16px]">open_in_new</span>
              </button>
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
              <div className="p-3 bg-canvas rounded-lg text-body-sm text-ink-secondary border border-surface-border leading-relaxed">
                "{selectedItem.generatedAnswer}"
              </div>
            </div>

            {/* RCA Suggestion Breakdown */}
            <div className="p-space-md rounded-xl bg-indigo-soft/50 border border-primary/20 flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <span className="font-label-md text-ink-primary font-semibold flex items-center gap-1.5">
                  <span className="material-symbols-outlined text-primary text-[18px]">auto_awesome</span>
                  Automated Classifier Assessment
                </span>
                <span className="font-code-xs text-evidence-teal font-semibold font-mono">
                  {(selectedItem.suggestedRcaConfidence * 100).toFixed(0)}% Confidence
                </span>
              </div>
              <p className="font-body-sm text-ink-secondary">
                   Predicted Root Cause: <strong>{selectedItem.suggestedRca || 'Not classified'}</strong>. No automated
                   root-cause classification has been persisted for this feedback yet.
              </p>
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
                <button
                  type="button"
                  onClick={() => void handlePromoteToGolden(selectedItem)}
                  className="px-3.5 py-2 rounded-lg bg-dataset-soft hover:bg-dataset-purple/20 text-dataset-purple font-label-md font-semibold transition-colors flex items-center gap-1 cursor-pointer"
                >
                  <span className="material-symbols-outlined text-[18px]">star</span>
                  <span>Flag Golden Candidate</span>
                </button>

                <button
                  type="button"
                  onClick={() => void handleApproveForReview(selectedItem)}
                  className="px-4 py-2 rounded-lg bg-primary-container hover:bg-primary text-on-primary font-label-md font-semibold transition-colors shadow-sm flex items-center gap-1.5 cursor-pointer"
                >
                  <span className="material-symbols-outlined text-[18px]">assignment_turned_in</span>
                  <span>Route to Evidence Review</span>
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
