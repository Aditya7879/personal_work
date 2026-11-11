import React, { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { AnimatePresence } from 'motion/react';
import { ArrowLeft, Check, LoaderCircle, X } from 'lucide-react';
import { AgentEnvironment, MyFeedbackRecord, MyFeedbackUpdate, updateMyFeedback } from '../api/feedbackApi';
import { UserVerdict } from '../types';
import { Notice } from './Notice';
import { AnimatedDiv, AnimatedSection } from './UiMotion';
import { dialogFocusTargets } from '../utils/dialogFocus';
import { ActionButton } from './ActionButton';
import { BusinessTaxonomyFields } from './BusinessTaxonomyFields';
import { useUnsavedDemoDraft } from '../utils/unsavedDemoDrafts';

const userCategories = (values: string[]) => values.filter((value) => !['legacy_csv_import', 'legacy_xlsx_import'].includes(value));

function draftFor(record: MyFeedbackRecord) {
  return { title: record.title || '', question: record.question || '', answer: record.agentResponse || '',
    feedback_text: record.feedbackText || '', expected_behavior: record.expectedBehavior || '',
    user_verdict: record.userVerdict as UserVerdict, impact: record.impact,
    categories: userCategories(record.issueCategories).join(', '),
    business_domain: record.businessDomain || record.domain || 'Unspecified',
    business_subdomain: record.businessSubdomain || (['user_submitted','user_confirmed','reviewer_confirmed'].includes(record.domainSource || '') ? '' : record.legacyContext?.subDomain) || '',
    environment: record.environment || 'unknown' as AgentEnvironment,
    agent_id: record.agentId || 'neo-rules-agent', agent_version: record.agentVersion || '',
    run_id: record.runId || '', conversation_id: record.conversationId || '',
    data_source: record.dataSource || record.legacyContext?.dataSource || '',
    language: record.language || record.legacyContext?.language || '',
    follow_up: record.followUp || record.legacyContext?.followUp || '' };
}

export const FeedbackEditView: React.FC<{ feedback: MyFeedbackRecord; onCancel: () => void; onSaved: (record: MyFeedbackRecord) => void }> = ({ feedback, onCancel, onSaved }) => {
  const [draft, setDraft] = useState(() => draftFor(feedback));
  const baseline = useRef(draftFor(feedback));
  const initialRecord = useRef(feedback);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [discarding, setDiscarding] = useState(false);
  const dialog = useRef<HTMLDivElement>(null);
  const discardDialog = useRef<HTMLElement>(null);
  const titleRef = useRef<HTMLInputElement>(null);
  const discardTrigger = useRef<HTMLElement | null>(null);
  const id = useId();
  const formId = `${id}-form`;
  const setField = <K extends keyof typeof draft>(field: K, value: typeof draft[K]) => setDraft((current) => ({ ...current, [field]: value }));
  const payload: MyFeedbackUpdate = {};
  for (const key of ['title', 'question', 'answer', 'feedback_text', 'expected_behavior', 'business_domain', 'business_subdomain', 'environment', 'agent_id', 'agent_version', 'run_id', 'conversation_id', 'data_source', 'language', 'follow_up'] as const) {
    if (draft[key].trim() !== baseline.current[key].trim()) (payload as Record<string, unknown>)[key] = draft[key].trim();
  }
  if (draft.user_verdict !== baseline.current.user_verdict) payload.user_verdict = draft.user_verdict;
  if (draft.impact !== baseline.current.impact) payload.impact = draft.impact;
  const categories = Array.from(new Set(draft.categories.split(',').map((value) => value.trim()).filter(Boolean)));
  if (categories.join('\n') !== userCategories(initialRecord.current.issueCategories).join('\n')) payload.issue_categories = categories;
  if (payload.business_domain === '') payload.business_domain = 'Unspecified';
  const changeCount = Object.keys(payload).length;
  const createsInputRevision = ['question', 'answer', 'expected_behavior', 'feedback_text', 'follow_up', 'environment',
    'environment_id', 'agent_id', 'agent_version', 'run_id', 'conversation_id', 'data_source', 'language'].some(key => key in payload);
  useUnsavedDemoDraft(changeCount > 0);
  const requestCancel = () => { if (!saving) { if (changeCount) setDiscarding(true); else onCancel(); } };

  useLayoutEffect(() => {
    const overflow = document.body.style.overflow;
    const root = document.getElementById('root');
    const previousInert = root?.inert || false;
    const previousHidden = root?.getAttribute('aria-hidden');
    if (root) { root.inert = true; root.setAttribute('aria-hidden', 'true'); }
    document.body.style.overflow = 'hidden';
    titleRef.current?.focus();
    return () => {
      document.body.style.overflow = overflow;
      if (root) { root.inert = previousInert; if (previousHidden == null) root.removeAttribute('aria-hidden'); else root.setAttribute('aria-hidden', previousHidden); }
      requestAnimationFrame(() => document.querySelector<HTMLButtonElement>('[data-feedback-edit]')?.focus());
    };
  }, []);
  useEffect(() => { if (discarding) { discardTrigger.current = document.activeElement instanceof HTMLElement ? document.activeElement : null; discardDialog.current?.querySelector<HTMLButtonElement>('button')?.focus(); } }, [discarding]);

  const save = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!changeCount || saving) return;
    if (categories.length > 20) { setError('Use no more than 20 categories.'); return; }
    setSaving(true); setError(null);
    try { onSaved(await updateMyFeedback(feedback.id, { ...payload, expected_revision: initialRecord.current.revision || 1, expected_updated_at: initialRecord.current.updatedAt })); }
    catch (error) { setError(error instanceof Error ? error.message : 'Could not save your changes. Your edits are still here.'); }
    finally { setSaving(false); }
  };
  const fieldClass = 'mt-1.5 w-full rounded-lg border border-surface-border bg-surface px-3 py-2.5 text-body-sm font-normal text-ink-primary outline-none transition focus:border-primary-container focus:ring-2 focus:ring-primary-container/10 disabled:opacity-60';
  const labelClass = 'block text-label-sm font-semibold text-ink-secondary';

  return createPortal(<AnimatedDiv surface="editor" ref={dialog} role="dialog" aria-modal="true" aria-labelledby={`${id}-title`} className="fixed inset-0 z-[60] flex flex-col bg-canvas text-ink-primary" onKeyDown={(event) => {
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); if (discarding) setDiscarding(false); else requestCancel(); }
    if (event.key !== 'Tab') return;
    const scope = discarding ? discardDialog.current : dialog.current;
    const elements = scope ? dialogFocusTargets(scope) : [];
    const first = elements[0], last = elements[elements.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  }}>
    <header className="shrink-0 border-b border-surface-border bg-surface"><div className="mx-auto flex w-full max-w-5xl items-center justify-between gap-4 px-4 py-4 sm:px-8"><div className="flex min-w-0 items-center gap-3"><ActionButton label="Exit feedback editor" icon={<ArrowLeft />} disabled={saving} onClick={requestCancel} /><div className="min-w-0"><h1 id={`${id}-title`} className="font-headline-md">Edit your submission</h1><p className="mt-0.5 truncate font-code-xs text-ink-muted">{feedback.id}</p></div></div><button type="button" disabled={saving} onClick={requestCancel} aria-label="Close feedback editor" className="rounded-lg p-2 text-ink-muted hover:bg-state-gray-soft disabled:opacity-50"><X size={19} aria-hidden="true" /></button></div></header>
    <div className="min-h-0 flex-1 overflow-y-auto"><form id={formId} onSubmit={(event) => void save(event)} className="mx-auto flex w-full max-w-5xl flex-col gap-5 px-4 py-6 sm:px-8">
      <p className="text-body-sm text-ink-secondary">Update your submitted details. Meaningful changes to the question, captured response, expectations or execution context create an input revision. A submitted-verdict, title, impact or category correction is audited without invalidating the saved answer or RCA. To rate a fresh agent answer, use “Your verdict for this answer” in answer history, not this submission editor.</p>
      {!!changeCount && <p role="note" className="rounded-lg border border-surface-border bg-surface p-3 text-body-sm text-ink-secondary">{createsInputRevision ? 'These input or criteria changes create a new revision. Earlier answers and assessments remain historical.' : 'These opinion/metadata changes will not create an input revision, clear RCA, or start an AI check.'}</p>}
      {error && <Notice title="Changes weren't saved" message={error} onDismiss={() => setError(null)} />}
      <fieldset disabled={saving} className="space-y-5">
        <section className="rounded-xl border border-surface-border bg-surface p-4 sm:p-5"><h2 className="font-title-md">Question & captured response</h2><div className="mt-4 space-y-4">
          <label className={labelClass}>Title<input ref={titleRef} aria-label="Submission title" required maxLength={120} value={draft.title} onChange={(event) => setField('title', event.target.value)} className={fieldClass} /></label>
          <label className={labelClass}>Original question<textarea aria-label="Submitted question" maxLength={20000} rows={3} value={draft.question} onChange={(event) => setField('question', event.target.value)} className={fieldClass} /></label>
          <label className={labelClass}>Agent response you submitted<span className="mt-1 block text-body-sm font-normal text-ink-muted">Correct the captured response if needed. This does not change what a connected agent actually returned; earlier captures and retests remain separate versions.</span><textarea aria-label="Submitted agent response" maxLength={50000} rows={7} value={draft.answer} onChange={(event) => setField('answer', event.target.value)} className={`${fieldClass} font-mono`} /></label>
        </div></section>
        <section className="rounded-xl border border-surface-border bg-surface p-4 sm:p-5"><h2 className="font-title-md">Your feedback & expected answer</h2><div className="mt-4 space-y-4">
          <label className={labelClass}>What went wrong?<textarea aria-label="Submitted feedback" required maxLength={10000} rows={4} value={draft.feedback_text} onChange={(event) => setField('feedback_text', event.target.value)} className={fieldClass} /></label>
          <label className={labelClass}>Expected answer<textarea aria-label="Submitted expected answer" maxLength={10000} rows={4} value={draft.expected_behavior} onChange={(event) => setField('expected_behavior', event.target.value)} className={fieldClass} /></label>
          <div className="grid gap-4 sm:grid-cols-2"><label className={labelClass}>Submitted-answer verdict<select aria-label="Submitted verdict" value={draft.user_verdict} onChange={(event) => setField('user_verdict', event.target.value as UserVerdict)} className={fieldClass}>{(['Correct', 'Partially correct', 'Incorrect', 'Unsafe or misleading', 'Not specified'] as UserVerdict[]).map((value) => <option key={value}>{value}</option>)}</select></label><label className={labelClass}>Business impact<select aria-label="Submitted impact" value={draft.impact} onChange={(event) => setField('impact', event.target.value as typeof draft.impact)} className={fieldClass}>{['Low', 'Medium', 'High'].map((value) => <option key={value}>{value}</option>)}</select></label></div>
          <label className={labelClass}>Issue categories<input aria-label="Submitted categories" maxLength={2000} value={draft.categories} onChange={(event) => setField('categories', event.target.value)} placeholder="Comma-separated categories" className={fieldClass} /></label>
        </div></section>
        <section className="rounded-xl border border-surface-border bg-surface p-4 sm:p-5"><h2 className="font-title-md">Business context</h2><div className="mt-4"><BusinessTaxonomyFields domain={draft.business_domain} subdomain={draft.business_subdomain} domainLabel="Submitted domain" subdomainLabel="Submitted subdomain" onChange={(domain, subdomain) => setDraft((current) => ({ ...current, business_domain: domain, business_subdomain: subdomain }))} disabled={saving} /></div><div className="mt-4 grid gap-4 sm:grid-cols-2"><label className={labelClass}>Agent environment<select aria-label="Submitted environment" value={draft.environment} onChange={(event) => setField('environment', event.target.value as AgentEnvironment)} className={fieldClass}><option value="unknown">Not recorded / unknown</option><option value="nonprod">Non-production</option><option value="prod">Production</option></select></label><label className={labelClass}>Language<input aria-label="Submitted language" maxLength={100} value={draft.language} onChange={(event) => setField('language', event.target.value)} className={fieldClass} /></label></div></section>
        <section className="rounded-xl border border-surface-border bg-surface p-4 sm:p-5"><h2 className="font-title-md">Agent & source references</h2><div className="mt-4 grid gap-4 sm:grid-cols-2">{([['agent_id', 'Agent identifier', 200], ['agent_version', 'Agent / release version', 200], ['run_id', 'Run reference', 200], ['conversation_id', 'Conversation reference', 200], ['data_source', 'Data source', 2000]] as const).map(([key, label, limit]) => <label key={key} className={labelClass}>{label}<input aria-label={label} required={key === 'agent_id'} maxLength={limit} value={draft[key]} onChange={(event) => setField(key, event.target.value)} className={fieldClass} /></label>)}</div><label className={`mt-4 ${labelClass}`}>Follow-up<textarea aria-label="Submitted follow-up" maxLength={4000} rows={3} value={draft.follow_up} onChange={(event) => setField('follow_up', event.target.value)} className={fieldClass} /></label></section>
      </fieldset>
    </form></div>
    <footer className="shrink-0 border-t border-surface-border bg-surface"><div className="mx-auto flex w-full max-w-5xl items-center justify-between gap-4 px-4 py-4 sm:px-8"><p className="text-metadata text-ink-muted">{saving ? 'Saving your changes…' : changeCount ? `${changeCount} changed field${changeCount === 1 ? '' : 's'} · not saved yet` : 'No changes yet'}</p><div className="flex shrink-0 items-center gap-2"><button type="button" disabled={saving} onClick={requestCancel} className="rounded-lg border border-surface-border px-4 py-2.5 text-label-sm font-semibold text-ink-secondary hover:bg-canvas disabled:opacity-50">Cancel</button><button type="submit" form={formId} disabled={saving || !changeCount} className="inline-flex items-center gap-2 rounded-lg bg-primary-container px-4 py-2.5 text-label-sm font-semibold text-on-primary hover:bg-primary disabled:opacity-50">{saving ? <LoaderCircle size={16} className="animate-spin" aria-hidden="true" /> : <Check size={16} aria-hidden="true" />}{saving ? 'Saving…' : 'Save changes'}</button></div></div></footer>
    <AnimatePresence onExitComplete={() => { if (discardTrigger.current?.isConnected) discardTrigger.current.focus({ preventScroll: true }); }}>{discarding && <AnimatedDiv key="discard" surface="backdrop" className="fixed inset-0 z-[70] flex items-center justify-center bg-ink-primary/25 p-4 backdrop-blur-sm"><AnimatedSection ref={discardDialog} role="alertdialog" aria-modal="true" aria-labelledby={`${id}-discard-title`} className="w-full max-w-md rounded-2xl border border-surface-border bg-surface p-5 shadow-xl"><h2 id={`${id}-discard-title`} className="font-title-md">Discard unsaved changes?</h2><p className="mt-2 text-body-sm text-ink-secondary">Your saved submission will not change. Keep editing if you want to save these updates.</p><div className="mt-5 flex justify-end gap-2"><button type="button" onClick={() => setDiscarding(false)} className="rounded-lg border border-surface-border px-3 py-2 text-label-sm font-semibold text-ink-secondary">Keep editing</button><button type="button" onClick={onCancel} className="rounded-lg bg-primary-container px-3 py-2 text-label-sm font-semibold text-on-primary">Discard changes</button></div></AnimatedSection></AnimatedDiv>}</AnimatePresence>
  </AnimatedDiv>, document.body);
};
