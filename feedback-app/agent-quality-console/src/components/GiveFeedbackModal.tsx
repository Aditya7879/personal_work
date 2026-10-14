import React, { useState } from 'react';
import { UserVerdict } from '../types';
import { FeedbackSubmission } from '../api/feedbackApi';

interface GiveFeedbackModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (newItem: FeedbackSubmission) => void;
}

export const GiveFeedbackModal: React.FC<GiveFeedbackModalProps> = ({
  isOpen,
  onClose,
  onSubmit
}) => {
  const [verdict, setVerdict] = useState<UserVerdict>('Not specified');
  const [selectedIssues, setSelectedIssues] = useState<string[]>([]);
  const [details, setDetails] = useState('');
  const [groundTruthHint, setGroundTruthHint] = useState('');
  const [impact, setImpact] = useState<'Low' | 'Medium' | 'High'>('Medium');

  if (!isOpen) return null;

  const toggleIssue = (issue: string) => {
    setSelectedIssues((prev) =>
      prev.includes(issue) ? prev.filter((i) => i !== issue) : [...prev, issue]
    );
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit({
      user_verdict: verdict,
      issue_categories: selectedIssues,
      feedback_text: details,
      expected_behavior: groundTruthHint || undefined,
      impact,
    });
    onClose();
  };

  return (
    <div className="fixed inset-0 bg-ink-primary/40 backdrop-blur-sm z-50 flex items-center justify-center p-space-md animate-in fade-in duration-200">
      <div className="w-full max-w-2xl bg-surface rounded-2xl shadow-2xl border border-surface-border flex flex-col overflow-hidden max-h-[90vh]">
        {/* Header */}
        <div className="px-space-lg pt-space-lg pb-space-md border-b border-surface-border bg-surface flex items-start justify-between gap-space-md">
          <div className="flex flex-col gap-0.5">
            <div className="flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-primary-container"></span>
              <h2 className="font-headline-md text-headline-md text-ink-primary font-semibold tracking-tight">
                Give feedback
              </h2>
            </div>
            <p className="font-body-sm text-body-sm text-ink-secondary">
              Help calibrate answers for this question and enrich golden evaluation datasets.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded-lg text-ink-muted hover:text-ink-primary hover:bg-state-gray-soft transition-colors cursor-pointer"
          >
            <span className="material-symbols-outlined text-[20px]">close</span>
          </button>
        </div>

        {/* Scrollable Form Body */}
        <form onSubmit={handleSubmit} className="p-space-lg overflow-y-auto flex flex-col gap-space-lg bg-surface">
          {/* Subject Reference */}
          <div className="p-space-md bg-canvas rounded-xl border border-surface-border flex flex-col gap-2">
            <div className="flex items-center justify-between text-ink-muted font-metadata text-metadata">
              <span className="uppercase tracking-wider font-semibold text-ink-secondary">Subject Reference</span>
               <span className="font-code-xs text-code-xs text-ink-muted font-mono">No linked agent run</span>
            </div>
            <div className="font-title-md text-title-md text-ink-primary font-semibold">
               No linked question was supplied. You can still submit feedback and add context below.
            </div>
            <div className="p-space-sm bg-surface rounded-lg border-l-2 border-issue-red flex flex-col gap-1">
              <span className="font-metadata text-metadata text-ink-muted">Generated assertion excerpt</span>
              <p className="font-code-sm text-code-sm text-ink-secondary line-clamp-2 font-mono">
                 No answer excerpt attached.
              </p>
            </div>
          </div>

          {/* 1. How was this answer? */}
          <div className="flex flex-col gap-space-sm">
            <div className="flex items-center justify-between">
              <label className="font-title-md text-title-md text-ink-primary font-semibold flex items-center gap-1.5">
                <span>1. How was this answer?</span>
                <span className="text-issue-red font-semibold">*</span>
              </label>
              <span className="font-metadata text-metadata text-ink-muted">Required</span>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 bg-canvas p-1 rounded-xl border border-surface-border">
              {(['Not specified', 'Correct', 'Partially correct', 'Incorrect', 'Unsafe or misleading'] as UserVerdict[]).map((v) => (
                <button
                  key={v}
                  type="button"
                  onClick={() => setVerdict(v)}
                  className={`py-2 px-3 rounded-lg font-label-sm text-label-sm transition-all text-center flex items-center justify-center gap-1 cursor-pointer ${
                    verdict === v
                        ? v === 'Incorrect' || v === 'Unsafe or misleading'
                        ? 'text-on-primary bg-issue-red shadow-sm font-semibold'
                        : 'text-on-primary bg-primary-container shadow-sm font-semibold'
                      : 'text-ink-secondary hover:text-ink-primary hover:bg-surface'
                  }`}
                >
                  {verdict === v && (
                    <span className="material-symbols-outlined text-[14px]">
                      {v === 'Incorrect' ? 'error' : v === 'Not specified' ? 'remove' : 'check'}
                    </span>
                  )}
                  <span>{v}</span>
                </button>
              ))}
            </div>
          </div>

          {/* 2. What went wrong? */}
          <div className="flex flex-col gap-space-sm">
            <div className="flex items-center justify-between">
              <label className="font-title-md text-title-md text-ink-primary font-semibold">
                2. What went wrong?
              </label>
              <span className="font-metadata text-metadata text-ink-muted">Select all applicable</span>
            </div>

            <div className="flex flex-wrap gap-2">
              {[
                'Incorrect fact',
                'Wrong source or citation',
                'Missing information',
                'Wrong region/scope',
                'Did not answer question',
                'Formatting/readability',
                'Other'
              ].map((issue) => {
                const isSelected = selectedIssues.includes(issue);
                return (
                  <button
                    key={issue}
                    type="button"
                    onClick={() => toggleIssue(issue)}
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg font-label-sm text-label-sm transition-all cursor-pointer ${
                      isSelected
                        ? 'bg-indigo-soft border border-primary-container text-primary-container shadow-xs font-semibold'
                        : 'bg-surface hover:bg-state-gray-soft border border-surface-border text-ink-secondary hover:text-ink-primary'
                    }`}
                  >
                    {isSelected && <span className="material-symbols-outlined text-[16px]">check</span>}
                    <span>{issue}</span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* 3. Tell us more */}
          <div className="flex flex-col gap-space-xs">
            <div className="flex items-center justify-between">
              <label className="font-title-md text-title-md text-ink-primary font-semibold flex items-center gap-1" htmlFor="feedback-details">
                <span>3. Tell us more</span>
                <span className="text-issue-red font-semibold">*</span>
              </label>
              <span className="font-metadata text-metadata text-ink-muted">
                {details.length} / 500 chars
              </span>
            </div>
            <textarea
              id="feedback-details"
              rows={3}
              value={details}
              onChange={(e) => setDetails(e.target.value)}
              className="w-full p-space-sm bg-surface border border-surface-border rounded-lg font-body-sm text-body-sm text-ink-primary focus:outline-none focus:border-primary-container focus:ring-2 focus:ring-primary-container/20 transition-all resize-y"
              required
            />
          </div>

          {/* 4. Golden Hint */}
          <div className="flex flex-col gap-space-xs">
            <div className="flex items-center justify-between">
              <label className="font-title-md text-title-md text-ink-primary font-semibold flex items-center gap-2" htmlFor="ground-truth-hint">
                <span>4. What should the answer have said?</span>
                <span className="font-metadata text-metadata px-1.5 py-0.5 rounded bg-dataset-soft text-dataset-purple uppercase tracking-wider font-semibold">
                  Golden dataset hint
                </span>
              </label>
              <span className="font-metadata text-metadata text-ink-muted">Optional</span>
            </div>
            <input
              id="ground-truth-hint"
              type="text"
              value={groundTruthHint}
              onChange={(e) => setGroundTruthHint(e.target.value)}
              className="w-full px-space-sm py-2 bg-surface border border-surface-border rounded-lg font-body-sm text-body-sm text-ink-primary focus:outline-none focus:border-primary-container focus:ring-2 focus:ring-primary-container/20 transition-all font-mono"
            />
          </div>

          {/* 5. Business Impact */}
          <div className="flex flex-col gap-space-sm">
            <label className="font-title-md text-title-md text-ink-primary font-semibold">
              5. Business impact
            </label>
            <div className="grid grid-cols-3 gap-2">
              {(['Low', 'Medium', 'High'] as const).map((lvl) => (
                <label
                  key={lvl}
                  className={`flex items-center justify-center gap-2 p-2.5 rounded-lg border cursor-pointer transition-all ${
                    impact === lvl
                      ? lvl === 'High'
                        ? 'border-issue-red bg-issue-soft text-issue-red font-semibold'
                        : 'border-primary bg-indigo-soft text-primary font-semibold'
                      : 'border-surface-border bg-surface hover:bg-state-gray-soft text-ink-secondary'
                  }`}
                >
                  <input
                    type="radio"
                    name="impact"
                    value={lvl}
                    checked={impact === lvl}
                    onChange={() => setImpact(lvl)}
                    className="accent-primary"
                  />
                  <span className="font-label-sm text-label-sm">{lvl}</span>
                </label>
              ))}
            </div>
          </div>

          {/* 6. Attachments */}
          <div className="flex flex-col gap-space-xs">
            <label className="font-title-md text-title-md text-ink-primary font-semibold">
              6. Attach supporting material
            </label>
            <div className="border-2 border-dashed border-surface-border hover:border-primary-container rounded-xl p-space-md bg-canvas hover:bg-indigo-soft/30 transition-all text-center flex flex-col items-center justify-center gap-2 cursor-pointer group">
              <div className="w-10 h-10 rounded-full bg-surface flex items-center justify-center text-ink-muted group-hover:text-primary-container shadow-xs">
                <span className="material-symbols-outlined text-[22px]">upload_file</span>
              </div>
              <div className="flex flex-col gap-0.5">
                <span className="font-label-md text-label-md text-ink-primary font-medium">
                  Drop screenshots, export CSVs, or paste reference doc URLs
                </span>
                <span className="font-metadata text-metadata text-ink-muted">
                  PDF, PNG, JPG, or TXT up to 15MB each
                </span>
              </div>
            </div>
          </div>

          {/* Footer */}
          <div className="pt-space-md border-t border-surface-border flex flex-col gap-space-md bg-surface">
            <div className="flex items-center gap-2 text-ink-muted">
              <span className="material-symbols-outlined text-[16px] text-evidence-teal shrink-0">verified_user</span>
              <span className="font-metadata text-metadata text-ink-muted">
                Your feedback will be reviewed by domain SMEs before ingestion into golden regression runs.
              </span>
            </div>

            <div className="flex items-center justify-between gap-space-md">
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 rounded-lg font-label-md text-label-md text-ink-secondary hover:text-ink-primary hover:bg-state-gray-soft transition-colors cursor-pointer"
              >
                Cancel
              </button>

              <div className="flex items-center gap-space-sm">
                <button
                  type="button"
                  onClick={onClose}
                  className="px-3 py-2 rounded-lg font-label-md text-label-md text-ink-secondary bg-surface border border-surface-border hover:bg-state-gray-soft transition-colors cursor-pointer"
                >
                  Save draft
                </button>
                <button
                  type="submit"
                  className="px-5 py-2 rounded-lg font-label-md text-label-md text-on-primary bg-primary-container hover:bg-primary transition-colors shadow-sm flex items-center gap-1.5 cursor-pointer font-semibold"
                >
                  <span className="material-symbols-outlined text-[18px]">send</span>
                  <span>Submit feedback</span>
                </button>
              </div>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
};
