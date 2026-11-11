import React, { useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { UserVerdict } from '../types';
import { AgentEnvironment, AgentEnvironmentConfig, FeedbackSubmission } from '../api/feedbackApi';
import { AnimatedDiv, AnimatedSection } from './UiMotion';
import { containDialogFocus, useDialogFocus } from '../utils/dialogFocus';
import { BusinessTaxonomyFields } from './BusinessTaxonomyFields';
import { useUnsavedDemoDraft } from '../utils/unsavedDemoDrafts';

interface GiveFeedbackModalProps {
  environments?: AgentEnvironmentConfig[];
  defaultEnvironmentId?: string;
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (newItem: FeedbackSubmission) => Promise<void>;
}

export const GiveFeedbackModal: React.FC<GiveFeedbackModalProps> = ({
  isOpen,
  onClose,
  onSubmit,
  environments = [],
  defaultEnvironmentId
}) => {
  const [subject, setSubject] = useState('');
  const [question, setQuestion] = useState('');
  const [answer, setAnswer] = useState('');
  const initialEnvironment = environments.find((row) => row.id === defaultEnvironmentId) || environments.find((row) => row.kind === 'nonprod' && row.enabled);
  const [environment, setEnvironment] = useState<AgentEnvironment>(initialEnvironment?.kind || 'nonprod');
  const [environmentId, setEnvironmentId] = useState(initialEnvironment?.id || '');
  const [agentVersion, setAgentVersion] = useState('');
  const [runId, setRunId] = useState('');
  const [saving, setSaving] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [verdict, setVerdict] = useState<UserVerdict>('Not specified');
  const [selectedIssues, setSelectedIssues] = useState<string[]>([]);
  const [details, setDetails] = useState('');
  const [groundTruthHint, setGroundTruthHint] = useState('');
  const [impact, setImpact] = useState<'Low' | 'Medium' | 'High'>('Medium');
  const [businessDomain, setBusinessDomain] = useState('');
  const [businessSubdomain, setBusinessSubdomain] = useState('');
  useUnsavedDemoDraft(isOpen && Boolean(subject || question || answer || details || groundTruthHint || businessDomain || businessSubdomain || agentVersion || runId || selectedIssues.length || verdict !== 'Not specified' || impact !== 'Medium'));
  const dialog = useRef<HTMLElement>(null);
  const id = useId();
  useDialogFocus(dialog, isOpen);

  if (!isOpen) return null;

  const toggleIssue = (issue: string) => {
    setSelectedIssues((prev) =>
      prev.includes(issue) ? prev.filter((i) => i !== issue) : [...prev, issue]
    );
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (saving) return;
    setSaving(true); setSubmitError(null);
    try {
    await onSubmit({
      title: subject.trim(),
      question: question.trim() || undefined,
      answer: answer.trim() || undefined,
      environment: environments.length ? environments.find((row) => row.id === environmentId)?.kind || 'unknown' : environment,
      environment_id: environments.find((row) => row.id === environmentId)?.id || undefined,
      agent_version: agentVersion.trim() || undefined,
      run_id: runId.trim() || undefined,
      business_domain: businessDomain.trim() || undefined,
      business_subdomain: businessSubdomain.trim() || undefined,
      user_verdict: verdict,
      issue_categories: selectedIssues,
      feedback_text: details,
      expected_behavior: groundTruthHint || undefined,
      impact,
    });
    onClose();
    } catch (error) { setSubmitError(error instanceof Error ? error.message : 'Could not submit your feedback'); }
    finally { setSaving(false); }
  };

  return createPortal(
    <AnimatedDiv surface="backdrop" className="fixed inset-0 bg-ink-primary/40 backdrop-blur-sm z-50 flex items-center justify-center p-space-md" onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <AnimatedSection ref={dialog} role="dialog" aria-modal="true" aria-labelledby={`${id}-title`} aria-describedby={`${id}-description`} tabIndex={-1} onKeyDown={(event) => containDialogFocus(event, onClose)} className="w-full max-w-2xl bg-surface rounded-2xl shadow-2xl border border-surface-border flex flex-col overflow-hidden max-h-[90dvh] outline-none">
        {/* Header */}
        <div className="px-space-lg pt-space-lg pb-space-md border-b border-surface-border bg-surface flex items-start justify-between gap-space-md">
          <div className="flex flex-col gap-0.5">
            <div className="flex items-center gap-2">
              <span className="w-2.5 h-2.5 rounded-full bg-primary-container"></span>
              <h2 id={`${id}-title`} className="font-headline-md text-headline-md text-ink-primary font-semibold tracking-tight">
                Submit feedback
              </h2>
            </div>
            <p id={`${id}-description`} className="font-body-sm text-body-sm text-ink-secondary">
              Tell us what happened. You can follow the review and any resolution from My feedback.
            </p>
          </div>
          <button
             type="button"
             aria-label="Close feedback form"
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
              <span className="uppercase tracking-wider font-semibold text-ink-secondary">Your report</span>
               <span className="font-label-sm text-ink-muted">Visible only to you and the review team</span>
            </div>
            <div className="font-title-md text-title-md text-ink-primary font-semibold">
               Add a short title and tell us what went wrong. Please don’t include sensitive personal information.
            </div>
          </div>

          <div className="flex flex-col gap-space-xs">
            <label className="font-title-md text-title-md text-ink-primary font-semibold" htmlFor="feedback-subject">What is this about?</label>
            <input
              id="feedback-subject"
              data-dialog-autofocus
              value={subject}
              onChange={(event) => setSubject(event.target.value)}
              maxLength={120}
              required
              placeholder="A short title for your feedback"
              className="w-full rounded-lg border border-surface-border bg-surface px-3 py-2.5 text-body-sm text-ink-primary focus:border-primary-container focus:outline-none"
            />
          </div>

          <section className="flex flex-col gap-3 rounded-xl border border-surface-border bg-canvas p-space-md">
            <h3 className="font-title-md text-ink-primary">Capture the original question and answer</h3>
            <p className="text-body-sm text-ink-muted">The title is only a summary. The exact question is needed to retest the agent, and the original answer is preserved for comparison. You can provide business context below; document-based hints are used only when it wasn't supplied.</p>
            <label className="text-label-sm text-ink-secondary">Original question<textarea aria-label="Original question" value={question} onChange={(event) => setQuestion(event.target.value)} rows={3} maxLength={20000} placeholder="Paste the exact question you asked the agent" className="mt-1 w-full rounded-lg border border-surface-border bg-surface p-3 text-body-sm" /></label>
            <label className="text-label-sm text-ink-secondary">Original agent answer<textarea aria-label="Original agent answer" value={answer} onChange={(event) => setAnswer(event.target.value)} rows={4} maxLength={50000} placeholder="Paste the response that led to this feedback" className="mt-1 w-full rounded-lg border border-surface-border bg-surface p-3 text-body-sm" /></label>
            <div className="grid gap-3 sm:grid-cols-3"><label className="text-label-sm text-ink-secondary">Agent environment{environments.length ? <select aria-label="Agent environment" value={environmentId} onChange={(event) => { setEnvironmentId(event.target.value); setEnvironment(environments.find((row) => row.id === event.target.value)?.kind || 'unknown'); }} className="mt-1 w-full rounded-lg border border-surface-border bg-surface px-2 py-2 text-body-sm"><option value="">Not sure</option>{environments.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}</select> : <select aria-label="Agent environment" value={environment} onChange={(event) => setEnvironment(event.target.value as AgentEnvironment)} className="mt-1 w-full rounded-lg border border-surface-border bg-surface px-2 py-2 text-body-sm"><option value="nonprod">Non-production</option><option value="prod">Production</option><option value="unknown">Not sure</option></select>}</label><label className="text-label-sm text-ink-secondary">Agent / release version<input aria-label="Agent release version" value={agentVersion} onChange={(event) => setAgentVersion(event.target.value)} maxLength={200} placeholder="If available" className="mt-1 w-full rounded-lg border border-surface-border bg-surface px-2 py-2 text-body-sm" /></label><label className="text-label-sm text-ink-secondary">Run reference<input aria-label="Agent run reference" value={runId} onChange={(event) => setRunId(event.target.value)} maxLength={200} placeholder="If available" className="mt-1 w-full rounded-lg border border-surface-border bg-surface px-2 py-2 text-body-sm" /></label></div>
          </section>

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
                  aria-label={v}
                  aria-pressed={verdict === v}
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
                    <span aria-hidden="true" className="material-symbols-outlined text-[14px]">
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
                    aria-label={issue}
                    aria-pressed={isSelected}
                    onClick={() => toggleIssue(issue)}
                    className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg font-label-sm text-label-sm transition-all cursor-pointer ${
                      isSelected
                        ? 'bg-indigo-soft border border-primary-container text-primary-container shadow-xs font-semibold'
                        : 'bg-surface hover:bg-state-gray-soft border border-surface-border text-ink-secondary hover:text-ink-primary'
                    }`}
                  >
                    {isSelected && <span aria-hidden="true" className="material-symbols-outlined text-[16px]">check</span>}
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

          {/* Optional expected answer */}
          <div className="flex flex-col gap-space-xs">
            <div className="flex items-center justify-between">
              <label className="font-title-md text-title-md text-ink-primary font-semibold" htmlFor="ground-truth-hint">
                What would have been a better answer?
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

          <section className="space-y-3 rounded-xl border border-surface-border bg-canvas p-space-md" aria-label="Business classification">
            <h3 className="font-title-md text-ink-primary">4. Business domain &amp; subdomain</h3>
            <p className="text-body-sm text-ink-muted">Choose an existing classification or select Other to enter a custom domain or subdomain. Your choices are saved with this feedback and won't be overwritten by automatic suggestions. Leave them unselected if you're unsure.</p>
            <BusinessTaxonomyFields domain={businessDomain} subdomain={businessSubdomain} disabled={saving} onChange={(domain, subdomain) => { setBusinessDomain(domain); setBusinessSubdomain(subdomain); }} />
          </section>

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
            {submitError && <p className="rounded-lg bg-issue-soft p-3 text-body-sm text-issue-red">{submitError}</p>}
            <div className="flex items-center gap-2 text-ink-muted">
              <span className="material-symbols-outlined text-[16px] text-evidence-teal shrink-0">verified_user</span>
              <span className="font-metadata text-metadata text-ink-muted">
                Your feedback will be reviewed by domain SMEs before ingestion into golden regression runs.
              </span>
            </div>

            <div className="flex flex-col gap-space-md sm:flex-row sm:items-center sm:justify-between">
              <button
                type="button"
                onClick={onClose}
                className="px-4 py-2 rounded-lg font-label-md text-label-md text-ink-secondary hover:text-ink-primary hover:bg-state-gray-soft transition-colors cursor-pointer"
              >
                Cancel
              </button>

              <div className="flex flex-wrap items-center justify-end gap-space-sm">
                <button
                  type="button"
                  onClick={onClose}
                  className="px-3 py-2 rounded-lg font-label-md text-label-md text-ink-secondary bg-surface border border-surface-border hover:bg-state-gray-soft transition-colors cursor-pointer"
                >
                   Close without submitting
                </button>
                <button
                   type="submit"
                   disabled={saving}
                  className="px-5 py-2 rounded-lg font-label-md text-label-md text-on-primary bg-primary-container hover:bg-primary transition-colors shadow-sm flex items-center gap-1.5 cursor-pointer font-semibold"
                >
                  <span aria-hidden="true" className="material-symbols-outlined text-[18px]">send</span>
                   <span>{saving ? 'Saving feedback…' : 'Submit feedback'}</span>
                </button>
              </div>
            </div>
          </div>
        </form>
      </AnimatedSection>
    </AnimatedDiv>, document.body,
  );
};
