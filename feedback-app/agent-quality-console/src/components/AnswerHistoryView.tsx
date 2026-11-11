import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AnimatePresence } from 'motion/react';
import { AgentTarget, AnswerVersion, BusinessContext, DiagnosisVersion, FeedbackHistory, clearReadCache, confirmRetest, getAgentTargets, getFeedbackHistory, queueFeedbackAnalysis, queueRetest, queueSavedAnswerRca } from '../api/feedbackApi';
import { AnswerMarkdown } from './AnswerMarkdown';
import { formatRcaLabel } from '../utils/formatRcaLabel';
import { Notice } from './Notice';
import { CollapsibleSection } from './CollapsibleSection';
import { ContentPreview } from './ContentPreview';
import { AnswerComparisonDialog } from './AnswerComparisonDialog';
import { BookOpen, Maximize2, RefreshCw, ScanSearch } from 'lucide-react';
import { diagnosesForAnswer } from '../utils/answerAssessment';
import { RcaRationale } from './RcaRationale';
import { answersInEnvironment } from '../utils/environmentScope';
import { ActionButton } from './ActionButton';
import { answerReview, reviewAnswer, reviewMessage, answerUserVerdict, answerEligibilityNote } from '../utils/answerReview';

export type AnswerHistorySelection = { feedbackId: string; environmentId?: string; history: FeedbackHistory | null; selected?: AnswerVersion; error: string | null };

export const AnswerHistoryView: React.FC<{
  feedbackId: string; reviewer?: boolean; context: BusinessContext; onDataChanged: () => void | Promise<void>; expandRequest?: number;
  reviewRequest?: number;
  selectedVersionId?: string; onSelectVersion?: (id: string) => void;
  onSelectionChange?: (selection: AnswerHistorySelection) => void;
  onReviewEvidence?: (diagnosis: DiagnosisVersion, evidenceId?: string) => void;
  onReviewSubmission?: () => void; refreshRequest?: number;
  environmentId?: string; environmentName?: string;
}> = ({ feedbackId, reviewer = false, context, onDataChanged, expandRequest, reviewRequest, selectedVersionId, onSelectVersion, onSelectionChange, onReviewEvidence, onReviewSubmission, refreshRequest, environmentId, environmentName }) => {
  const [loadedHistory, setLoadedHistory] = useState<{ feedbackId: string; reviewer: boolean; data: FeedbackHistory } | null>(null);
  const history = loadedHistory?.feedbackId === feedbackId && loadedHistory.reviewer === reviewer ? loadedHistory.data : null;
  const [targets, setTargets] = useState<AgentTarget[]>([]);
  const [targetId, setTargetId] = useState('');
  const [localSelectedAnswerId, setLocalSelectedAnswerId] = useState('');
  const selectedAnswerId = selectedVersionId ?? localSelectedAnswerId;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [comment, setComment] = useState('');
  const [traceOpen, setTraceOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [comparisonOpen, setComparisonOpen] = useState(false);
  const [historyRefreshing, setHistoryRefreshing] = useState(false);
  const inFlightScope = useRef<string | null>(null);
  const mutationInFlight = useRef(false);
  const [verdictEdit, setVerdictEdit] = useState<{ attemptId: string; previous: 'fixed' | 'partially_fixed' | 'still_incorrect' } | null>(null);
  const [reviewEnvironment, setReviewEnvironment] = useState<{ id: string; name?: string } | null>(null);
  const manualReview = useRef(false);
  const focusReview = useRef(false);
  const offeredAttempt = useRef<string | null>(null);
  const reviewControls = useRef<HTMLDivElement>(null);
  const displayedEnvironmentId = reviewEnvironment?.id || environmentId;
  const displayedEnvironmentName = reviewEnvironment?.name || environmentName;
  const scope = `${reviewer ? 'reviewer' : 'reporter'}:${feedbackId}:${environmentId || 'All'}`;
  const activeId = useRef(scope);
  const loadSequence = useRef(0);
  const changedCallback = useRef(onDataChanged);
  const selectionCallback = useRef(onSelectionChange);
  const previousStatuses = useRef(new Map<string, string>());
  const previousResults = useRef<Set<string> | null>(null);
  const previousDiagnoses = useRef<Set<string> | null>(null);
  const panelRoot = useRef<HTMLDivElement>(null);
  const previousSharedContext = useRef(context.latestPublishedAttemptId);
  activeId.current = scope; changedCallback.current = onDataChanged; selectionCallback.current = onSelectionChange;
  const load = useCallback(async (refresh = false) => {
    if (!refresh && inFlightScope.current === scope) return;
    inFlightScope.current = scope;
    const sequence = ++loadSequence.current;
    if (refresh) setHistoryRefreshing(true);
    try {
      const data = await getFeedbackHistory(feedbackId, reviewer, refresh);
      if (activeId.current !== scope || sequence !== loadSequence.current) return;
      const completed = data.attempts.some((attempt) => ['queued', 'running'].includes(previousStatuses.current.get(attempt.id) || '') && ['completed', 'failed'].includes(attempt.status));
      const available = new Set(data.answers.filter((answer) => answer.kind === 'retest' && answer.attemptId).map((answer) => answer.attemptId!));
      const newResult = previousResults.current !== null && [...available].some((id) => !previousResults.current?.has(id));
      const diagnosisIds = new Set(data.diagnoses.map((diagnosis) => diagnosis.id));
      const newDiagnosis = previousDiagnoses.current !== null && [...diagnosisIds].some((id) => !previousDiagnoses.current?.has(id));
      previousResults.current = available;
      previousDiagnoses.current = diagnosisIds;
      previousStatuses.current = new Map(data.attempts.map((attempt) => [attempt.id, attempt.status]));
      setLoadedHistory({ feedbackId, reviewer, data }); setError(null);
      if (completed || newResult || newDiagnosis) { clearReadCache(); await changedCallback.current(); }
    } catch (error) { if (activeId.current === scope && sequence === loadSequence.current) setError(error instanceof Error ? error.message : 'Could not load answer history'); }
    finally { if (activeId.current === scope && sequence === loadSequence.current) { inFlightScope.current = null; setHistoryRefreshing(false); } }
  }, [feedbackId, reviewer, scope]);
  useEffect(() => {
    activeId.current = scope;
    setLoadedHistory(null); setLocalSelectedAnswerId(''); setComment(''); setTraceOpen(false); setError(null); previousStatuses.current.clear();
    setHistoryOpen(false);
    setHistoryRefreshing(false); setVerdictEdit(null);
    setReviewEnvironment(null); manualReview.current = false; offeredAttempt.current = null;
    setComparisonOpen(false); previousResults.current = null; previousDiagnoses.current = null;
    previousSharedContext.current = context.latestPublishedAttemptId;
    void load();
    if (reviewer) void getAgentTargets(true).then((values) => { if (activeId.current === scope) { setTargets(values); setTargetId(values.find((value) => value.id === environmentId)?.id || values.find((value) => value.id === context.environmentId && value.canRetest)?.id || values.find((value) => value.canRetest)?.id || values[0]?.id || ''); } }).catch((error) => { if (activeId.current === scope) setError(error.message); });
    return () => { activeId.current = ''; };
  }, [feedbackId, reviewer, load]);
  useEffect(() => { if (refreshRequest) void load(true); }, [refreshRequest, load]);
  useEffect(() => { if (expandRequest) setHistoryOpen(true); }, [feedbackId, expandRequest]);
  useEffect(() => {
    if (!reviewRequest || reviewer) return;
    manualReview.current = true; focusReview.current = true; setHistoryOpen(true);
    void load(true).then(() => { if (activeId.current === scope) return changedCallback.current(); })
      .catch(error => { if (activeId.current === scope) setError(error instanceof Error ? error.message : 'Could not refresh the latest review'); });
  }, [reviewRequest, reviewer, load]);
  useEffect(() => {
    const latest = context.latestPublishedAttemptId;
    const changed = previousSharedContext.current !== latest;
    previousSharedContext.current = latest;
    if (changed && latest && !previousResults.current?.has(latest)) void load(true);
  }, [context.latestPublishedAttemptId, load]);
  const hasActiveJobs = Boolean(history?.pendingRetestCount || history?.attempts.some((attempt) => ['queued', 'running'].includes(attempt.status)));
  const shouldPoll = hasActiveJobs || historyOpen || !reviewer;
  useEffect(() => {
    if (!shouldPoll) return;
    const timer = window.setInterval(() => { if (document.visibilityState === 'visible' && panelRoot.current?.getClientRects().length) void load(); }, 10_000);
    return () => window.clearInterval(timer);
  }, [shouldPoll, load]);
  const runAction = async (action: () => Promise<unknown>) => {
    if (mutationInFlight.current) return;
    mutationInFlight.current = true;
    setBusy(true); setError(null);
    try { await action(); setVerdictEdit(null); clearReadCache(); await load(true); await changedCallback.current(); }
    catch (error) { setError(error instanceof Error ? error.message : 'Could not complete this action'); }
    finally { mutationInFlight.current = false; setBusy(false); }
  };
  const original = history?.answers.find((answer) => answer.kind === 'original');
  const scopedAnswers = answersInEnvironment(history, context, displayedEnvironmentId);
  const refreshed = scopedAnswers.filter((answer) => answer.kind !== 'original');
  const selected = refreshed.find((answer) => answer.id === selectedAnswerId) || refreshed[refreshed.length - 1];
  const attempt = history?.attempts.find((item) => item.id === selected?.attemptId);
  const diagnoses = diagnosesForAnswer(history, selected?.id || (!displayedEnvironmentId || context.environmentId === displayedEnvironmentId ? original?.id : undefined));
  useEffect(() => { selectionCallback.current?.({ feedbackId, environmentId, history, selected, error }); }, [feedbackId, environmentId, history, selected, error]);
  const target = targets.find((item) => item.id === targetId);
  const review = answerReview(history, context);
  const eligibleAnswer = reviewAnswer(history, review);
  const currentEnvironmentKind = review.environmentKind;
  const currentEnvironmentId = review.environmentId;
  const current = attempt?.revision === review.revision && attempt?.environment === currentEnvironmentKind && !!currentEnvironmentId && attempt?.environmentId === currentEnvironmentId;
  const latestConfirmable = history?.sharingPolicy === 'automatic' ? history.latestConfirmableAttemptId : context.latestPublishedAttemptId;
  const editingRecordedVerdict = verdictEdit?.attemptId === attempt?.id;
  const canConfirm = !reviewer && (review.state === 'available' || review.state === 'already_responded' && editingRecordedVerdict) && !!selected?.answer?.trim() && attempt?.kind === 'retest' && attempt.status === 'completed' && attempt.id === latestConfirmable && (!attempt.confirmation || editingRecordedVerdict) && current;
  useEffect(() => {
    if (reviewer || !history || historyRefreshing) return;
    if (manualReview.current) {
      manualReview.current = false; setHistoryOpen(true);
      if (eligibleAnswer && review.environmentId) {
        setReviewEnvironment({ id: review.environmentId, name: review.environmentLabel || undefined });
        if (selectedAnswerId !== eligibleAnswer.id) { setLocalSelectedAnswerId(eligibleAnswer.id); setComment(''); }
      }
    }
    if (review.state === 'available' && eligibleAnswer && offeredAttempt.current !== review.attemptId) {
      offeredAttempt.current = review.attemptId || null;
      // Do not silently replace an explicitly filtered environment or a typed response.
      if ((!displayedEnvironmentId || displayedEnvironmentId === review.environmentId) && !comment.trim()) {
        setLocalSelectedAnswerId(eligibleAnswer.id); setHistoryOpen(true);
      }
    }
  }, [history, historyRefreshing, reviewer, review.state, review.attemptId, review.environmentId, eligibleAnswer?.id]);
  const focusReviewControls = () => {
    if (!focusReview.current || !reviewControls.current) return;
    focusReview.current = false; reviewControls.current.focus({ preventScroll: true });
    reviewControls.current.scrollIntoView({ block: 'nearest' });
  };
  useEffect(() => { if (canConfirm && historyOpen && !historyRefreshing) focusReviewControls(); }, [canConfirm, historyOpen, historyRefreshing]);
  const openLatestReview = () => {
    manualReview.current = true; focusReview.current = true; setHistoryOpen(true); void load(true);
  };
  const selectAnswerVersion = (id: string) => { setLocalSelectedAnswerId(id); onSelectVersion?.(id); setComment(''); setTraceOpen(false); setVerdictEdit(null); };
  const selectedVerdict = answerUserVerdict(selected, history);
  const eligibilityNote = selected ? answerEligibilityNote(selected, review) : undefined;

  return <><div ref={panelRoot} className="min-w-0">{!reviewer && history && <section aria-label="Updated answer review" className={`mb-3 rounded-xl border p-3 text-body-sm ${review.state === 'available' ? 'border-evidence-teal/25 bg-evidence-soft/40' : 'border-surface-border bg-canvas'}`}><p role="status" className="text-ink-secondary">{reviewMessage(review)}</p><button type="button" disabled={busy || historyRefreshing} onClick={openLatestReview} className="mt-2 font-semibold text-primary underline underline-offset-2 disabled:opacity-50">{historyRefreshing ? 'Refreshing latest answer…' : review.state === 'already_responded' ? 'View recorded response' : review.state === 'available' ? 'Review updated answer' : 'Check for an updated answer'}</button></section>}<CollapsibleSection key={feedbackId} title="Answer history & fix verification" summary={history ? `${history.answers.length} saved response${history.answers.length === 1 ? '' : 's'} · ${history.diagnoses.length} RCA check${history.diagnoses.length === 1 ? '' : 's'}` : 'Saved responses, retests and confirmations'} badge={error ? 'Needs attention' : hasActiveJobs ? 'Check in progress' : !reviewer && refreshed.some((answer) => answer.kind === 'retest') ? 'Automatic updates' : undefined} open={historyOpen} onOpened={focusReviewControls} onOpenChange={(open) => { setHistoryOpen(open); if (open) void load(); }}>
    <div className="flex flex-col items-start gap-2"><p className="text-body-sm text-ink-muted">Answers and automated verdicts appear here automatically.</p><div className="flex min-w-0 max-w-full items-center gap-1"><ActionButton label="Refresh history" icon={<RefreshCw />} tone="ghost" size="sm" onClick={() => void load(true)} />{!!history?.answers.length && <ActionButton label="Compare saved answers" aria-label="Expand comparison" compactLabel="Compare" icon={<Maximize2 />} size="sm" aria-haspopup="dialog" onClick={() => { if (selected) selectAnswerVersion(selected.id); setComparisonOpen(true); }} />}</div></div>
    <p className="mt-2 text-metadata text-ink-muted">{displayedEnvironmentId ? `Showing results for ${displayedEnvironmentName || displayedEnvironmentId}. ` : ''}{reviewEnvironment && environmentId && environmentId !== reviewEnvironment.id ? 'Opened the current main environment for your review; your list filter is unchanged. ' : ''}No manual sharing is required. AI assessments are unverified; availability does not mean a fix was deployed or accepted. Raw evidence and reviewer notes stay private.</p>
    {reviewer && <div className="mt-4 flex flex-wrap items-end gap-3 rounded-lg bg-canvas p-3">
      <label className="text-label-sm text-ink-secondary">Retest target<select aria-label="Retest target" value={targetId} onChange={(event) => setTargetId(event.target.value)} className="mt-1 block max-w-full rounded-lg border border-surface-border bg-surface px-3 py-2 text-body-sm">{targets.map((item) => <option key={item.id} value={item.id}>{item.label}{!item.canRetest ? ' · unavailable' : ''}</option>)}</select></label>
      <button type="button" disabled={busy || !target?.canRetest || hasActiveJobs} onClick={() => { selectAnswerVersion(''); void runAction(() => queueRetest(feedbackId, targetId)); }} className="rounded-lg bg-primary-container px-3 py-2 text-label-sm font-semibold text-on-primary disabled:opacity-50">Run fresh answer + RCA</button>
      <ActionButton label="Recheck domain & original RCA" icon={<ScanSearch />} expanded disabled={busy || hasActiveJobs} onClick={() => { onReviewSubmission?.(); void runAction(() => queueFeedbackAnalysis(feedbackId)); }} />
      {selected?.answer && <ActionButton label="Recheck selected RCA only" icon={<ScanSearch />} expanded disabled={busy || hasActiveJobs} onClick={() => void runAction(() => queueSavedAnswerRca(feedbackId, selected.id))} title="Recheck the selected saved answer without invoking NEO again" />}
      {target?.reason && <p className="basis-full text-body-sm text-review-amber">{target.reason}. No agent invocation is made until its connection and permissions are configured.</p>}
      {target?.canRetest && target.protocol === 'neo_companion' && <p className="basis-full text-metadata text-ink-muted">NEO Companion target configured · each retest starts a fresh conversation. The agent request can take up to {Math.ceil((target.timeoutSeconds || 300) / 60)} minutes, followed by the evidence/RCA check. Original answers are never replaced.</p>}
      {target && target.environment !== context.environment && <p className="basis-full text-metadata text-ink-muted">This is a cross-environment investigation. Its result is visible automatically, but cannot resolve a report from another or unknown environment.</p>}
    </div>}
    {error && <div className="mt-3"><Notice title="Answer history action couldn't complete" message={error} onDismiss={() => setError(null)} /></div>}
    {!history && !error && <p className="mt-3 text-body-sm text-ink-muted" role="status">Loading saved answer history…</p>}
    {!!history?.attempts.length && <ul className="mt-3 space-y-1 text-body-sm text-ink-secondary">{history.attempts.filter((item) => !displayedEnvironmentId || item.environmentId === displayedEnvironmentId).slice(0, 5).map((item) => <li key={item.id} className="flex flex-wrap items-center gap-2"><span className="rounded bg-surface-container-low px-2 py-1 text-metadata">{item.kind === 'retest' ? 'Fresh answer + RCA' : 'Domain / RCA check'} · {item.environmentLabel || item.environment} · {item.status}</span>{item.status === 'running' && item.kind === 'retest' && <span role="status" className="text-ink-muted">{history.answers.some((answer) => answer.attemptId === item.id) ? 'Agent answer saved · evidence/RCA check in progress' : 'Waiting for the agent response…'}</span>}{item.error && <span className="text-issue-red">{item.error}</span>}</li>)}</ul>}
    {history && displayedEnvironmentId && !refreshed.length && <p role="status" className="mt-3 rounded-lg border border-surface-border bg-canvas p-3 text-body-sm text-ink-secondary">No refreshed answer is saved in {displayedEnvironmentName || 'this environment'}. Other environments are not used as a substitute.</p>}
    {!!refreshed.length && <label className="mt-4 block text-label-sm text-ink-secondary">Answer version<select aria-label="Answer version" value={selected?.id || ''} onChange={(event) => selectAnswerVersion(event.target.value)} className="ml-2 max-w-full rounded-lg border border-surface-border bg-surface px-3 py-2 text-body-sm">{refreshed.map((answer, index) => <option key={answer.id} value={answer.id}>{answer.kind === 'submission_edit' ? `Submission correction · revision ${answer.revision}` : `Retest ${index + 1}`} · {answer.environment} · {answer.agentVersion || 'version not recorded'} · {new Date(answer.createdAt).toLocaleString()}</option>)}</select></label>}
    {history && <div className="mt-4 grid gap-3 @xl:grid-cols-2">
      <article className="min-w-0"><h4 className="font-label-md font-semibold">Original answer</h4><p className="mb-2 mt-1 text-metadata text-ink-muted">{original?.environment || 'unknown'} · {original?.agentVersion || 'agent version not recorded'}</p>{original?.answer ? <ContentPreview key={original.id} label="Original answer"><AnswerMarkdown content={original.answer} /></ContentPreview> : <p className="text-body-sm text-ink-muted">No original answer snapshot was captured. Do not infer what the agent previously said.</p>}</article>
      <article className="min-w-0"><h4 className="font-label-md font-semibold">{selected?.kind === 'submission_edit' ? 'Corrected submitted response' : 'Updated answer'}</h4>{selected ? <><p className="mb-2 mt-1 text-metadata text-ink-muted">{selected.environment} · {selected.agentVersion || 'agent version not recorded'} · {selected.kind === 'submission_edit' ? 'Edited capture · not an agent rerun' : 'Automatically visible to reporter'}</p><ContentPreview key={selected.id} label="Updated answer"><AnswerMarkdown content={selected.answer || ''} /></ContentPreview></> : <p className="mt-2 text-body-sm text-ink-muted">No refreshed response has been saved yet. Retest answers appear automatically when available.</p>}</article>
    </div>}
    {reviewer && selected?.kind === 'retest' && <details key={selected.id} className="mt-3 rounded-lg border border-surface-border bg-canvas p-3" onToggle={(event) => setTraceOpen(event.currentTarget.open)}>
      <summary className="cursor-pointer text-label-sm font-semibold text-ink-secondary">Agent diagnostics · reviewer only</summary>
      {traceOpen && <div className="mt-3 space-y-2 text-body-sm text-ink-secondary">
        <dl className="grid gap-x-4 gap-y-1 sm:grid-cols-[auto_1fr]"><dt>Conversation</dt><dd className="break-all font-mono text-metadata">{selected.conversationId || 'Not returned by the agent'}</dd><dt>Run reference</dt><dd className="break-all font-mono text-metadata">{selected.runId || 'Not returned by the agent'}</dd><dt>Response time</dt><dd>{typeof selected.latencyMs === 'number' ? `${(selected.latencyMs / 1000).toFixed(1)} seconds` : 'Not recorded'}</dd><dt>Protocol</dt><dd>{selected.protocol === 'neo_companion' ? 'NEO Companion generations' : selected.protocol || 'Not recorded'}</dd></dl>
        <p>{selected.privateTrace ? `${selected.privateTrace.toolCallCount} tool calls · ${selected.privateTrace.toolResultCount} tool results · ${selected.privateTrace.messageCount} messages${selected.privateTrace.truncated ? ' · diagnostic capture truncated for size' : ''}` : 'No tool trace was returned for this answer.'}</p>
        <p className="text-metadata text-ink-muted">Raw agent/tool data is untrusted and private to reviewers. It is not proof that a source claim or proposed fix is correct.</p>
        {(selected.privateTrace || !!selected.sources?.length) && <pre aria-label="Private agent trace" className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-surface-border bg-surface p-3 text-metadata text-ink-secondary">{JSON.stringify({ trace: selected.privateTrace, sources: selected.sources }, null, 2)}</pre>}
      </div>}
    </details>}
    {selected && <section aria-label="Reporter verdict for this answer" className="mt-3 rounded-lg border border-surface-border p-3"><h4 className="font-label-md font-semibold">{reviewer ? 'Reporter verdict for this answer' : 'Your verdict for this answer'}</h4><p className="mt-1 font-semibold text-ink-primary">{selectedVerdict}</p><p className="mt-1 text-metadata text-ink-muted">{selected.environmentLabel || selected.environment} · input revision {selected.revision} · this answer version only. The AI comparison and RCA are separate and unchanged.</p>{!reviewer && attempt?.confirmation && current && attempt.id === latestConfirmable && !editingRecordedVerdict && <button type="button" disabled={busy} onClick={() => { setVerdictEdit({ attemptId: attempt.id, previous: attempt.confirmation! }); setComment(''); }} className="mt-2 text-label-sm font-semibold text-primary underline underline-offset-2">Change your verdict for this answer</button>}</section>}
    {attempt?.kind === 'retest' && <div aria-label="AI comparison" className="mt-3 rounded-lg border border-surface-border bg-canvas p-3 text-body-sm text-ink-secondary"><div className="flex flex-wrap items-center justify-between gap-2"><strong className="text-ink-primary">AI comparison for this answer</strong><span className="text-metadata text-ink-muted">AI · not verified</span></div><p className="mt-1 font-semibold text-ink-primary">{attempt.assessment ? formatRcaLabel(attempt.assessment) : attempt.status === 'failed' ? 'Assessment unavailable' : attempt.status === 'completed' ? 'No assessment recorded' : 'Assessment in progress'}</p>{attempt.reason && <p className="mt-2 whitespace-pre-wrap">{attempt.reason}</p>}<p className="mt-2 text-metadata text-ink-muted">{attempt.environmentLabel || attempt.environment} · input revision {attempt.revision}. This saved AI assessment may differ from your verdict; a user response does not rewrite it or its reasoning.</p></div>}
    {attempt?.summary && <div className="mt-3 rounded-lg border border-surface-border p-3 text-body-sm text-ink-secondary"><strong>Reviewer explanation</strong><p className="mt-1 whitespace-pre-wrap">{attempt.summary}</p></div>}
    {!!diagnoses.length && <div className="mt-3 space-y-2"><h4 className="font-label-md font-semibold">RCA for this answer version</h4>{diagnoses.map((diagnosis) => <div key={diagnosis.id} className="rounded-lg border border-surface-border p-3 text-body-sm"><p className="font-semibold">{formatRcaLabel(diagnosis.category)} · {diagnosis.verified ? 'Reviewer verified' : 'AI suggestion · not verified'}</p>{diagnosis.defect && <p className="mt-1 text-ink-secondary">Defect: {diagnosis.defect}</p>}<div className="mt-1 text-ink-secondary"><RcaRationale text={diagnosis.rationale} evidence={reviewer ? diagnosis.evidence : undefined} onCitationClick={reviewer && onReviewEvidence ? (id) => onReviewEvidence(diagnosis, id) : undefined} /></div>{reviewer && !!diagnosis.evidence?.length && onReviewEvidence && <ActionButton label={`Review ${diagnosis.evidence.length} cited source passages`} compactLabel={`${diagnosis.evidence.length} sources`} icon={<BookOpen />} tone="ghost" size="sm" containerClassName="mt-3" onClick={() => onReviewEvidence(diagnosis)} />}</div>)}</div>}
    {attempt?.kind === 'retest' && eligibilityNote && <p role="note" className="mt-3 text-body-sm text-ink-muted">{eligibilityNote}</p>}
    {attempt?.kind === 'retest' && current && latestConfirmable && attempt.id !== latestConfirmable && <p className="mt-3 text-body-sm text-ink-muted">A newer completed result exists for this environment and input. Select that version to confirm an outcome.</p>}
     {canConfirm && <div ref={reviewControls} tabIndex={-1} aria-label="Your response to the updated answer" className="mt-4 rounded-xl border border-evidence-teal/25 bg-evidence-soft/40 p-3 outline-none"><h4 className="font-title-md">{editingRecordedVerdict ? 'Change your verdict for this answer' : 'Does this updated answer fix your issue?'}</h4><p className="mt-1 text-body-sm text-ink-secondary">Your response applies only to this latest saved answer in {attempt.environmentLabel || attempt.environment}. It does not change the AI comparison, RCA, or submitted answer. Corrections are audited.</p><textarea aria-label="Remaining issue or confirmation comment" rows={3} value={comment} onChange={(event) => setComment(event.target.value)} maxLength={4000} placeholder="What is still missing or wrong? Required if the issue is not fully fixed." className="mt-3 w-full rounded-lg border border-surface-border bg-surface p-3 text-body-sm" /><div className="mt-3 flex flex-wrap gap-2">{([['fixed', 'Correct'], ['partially_fixed', 'Partially correct'], ['still_incorrect', 'Incorrect']] as const).map(([verdict, label]) => <button type="button" key={verdict} disabled={busy || historyRefreshing || (verdict !== 'fixed' && !comment.trim())} onClick={() => void runAction(() => confirmRetest(feedbackId, attempt.id, verdict, comment.trim(), verdictEdit?.previous))} className="rounded-lg border border-surface-border bg-surface px-3 py-2 text-label-sm font-semibold text-primary disabled:opacity-50">{label}</button>)}{editingRecordedVerdict && <button type="button" disabled={busy} onClick={() => { setVerdictEdit(null); setComment(''); }} className="px-3 py-2 text-label-sm text-ink-secondary underline">Cancel verdict change</button>}</div></div>}
    {attempt?.confirmation && <p className="mt-3 rounded-lg bg-canvas p-3 text-body-sm text-ink-secondary">Your response to this version: <strong>{selectedVerdict}</strong>. {attempt.confirmation === 'fixed' && current && attempt.id === latestConfirmable ? 'This current answer was marked correct by its reporter.' : 'This is the saved reporter opinion for this version, separate from the AI assessment.'}</p>}
  </CollapsibleSection></div><AnimatePresence key={scope}>{comparisonOpen && history && <AnswerComparisonDialog key="comparison" feedbackId={feedbackId} original={original ? { ...original, userVerdict: answerUserVerdict(original, history) } : undefined} selected={selected ? { ...selected, userVerdict: selectedVerdict } : undefined} versions={refreshed.map(answer => ({ ...answer, userVerdict: answerUserVerdict(answer, history) }))} onSelectVersion={selectAnswerVersion} onClose={() => setComparisonOpen(false)} />}</AnimatePresence></>;
};
