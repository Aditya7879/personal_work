import React, { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { CheckCircle2, LoaderCircle, X, XCircle } from 'lucide-react';
import { AgentEnvironmentConfig, EndpointTestResult, getEndpointTest, testAgentEndpoint } from '../api/feedbackApi';
import { AnimatedDiv, AnimatedSection } from './UiMotion';
import { containDialogFocus, useDialogFocus } from '../utils/dialogFocus';

export function EndpointTestDialog({ environment, onClose, onChanged }: { environment: AgentEnvironmentConfig; onClose: () => void; onChanged: () => Promise<void> }) {
  const dialog = useRef<HTMLElement>(null);
  useDialogFocus(dialog);
  const id = useId();
  const [question, setQuestion] = useState('Hello. Please reply with a brief greeting.');
  const [result, setResult] = useState<EndpointTestResult | null>(environment.lastTest || null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const key = useRef<string | null>(null);
  const mounted = useRef(true);
  const changed = useRef(onChanged); changed.current = onChanged;
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const runningId = result?.status === 'running' ? result.id : null;
  useEffect(() => {
    if (!runningId) return;
    let cancelled = false, inFlight = false;
    const timer = window.setInterval(async () => {
      if (inFlight) return; inFlight = true;
      try { const next = await getEndpointTest(environment.id, runningId); if (!cancelled) { setResult(next); if (next.status !== 'running') await changed.current(); } }
      catch (error) { if (!cancelled) setError(error instanceof Error ? error.message : 'Could not read the test result'); }
      finally { inFlight = false; }
    }, 2000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [runningId, environment.id]);
  const run = async (fresh: boolean) => {
    if (busy || !question.trim()) return;
    if (fresh || !key.current) key.current = crypto.randomUUID();
    setBusy(true); setError(null); setResult(null);
    try {
      const value = await testAgentEndpoint(environment.id, environment.revision, question, key.current);
      if (mounted.current) { setResult(value); await changed.current(); }
    } catch (error) { if (mounted.current) setError(error instanceof Error ? error.message : 'The test response was lost. Check the previous attempt; do not assume no request was sent.'); }
    finally { if (mounted.current) setBusy(false); }
  };
  const priorTerminal = result && result.status !== 'running';
  return createPortal(<AnimatedDiv surface="backdrop" className="fixed inset-0 z-[75] flex items-center justify-center bg-ink-primary/35 p-4" onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <AnimatedSection ref={dialog} role="dialog" aria-modal="true" aria-labelledby={`${id}-title`} aria-describedby={`${id}-description`} onKeyDown={(event) => containDialogFocus(event, onClose)} className="flex max-h-[90dvh] w-full max-w-2xl flex-col overflow-hidden rounded-xl border border-surface-border bg-surface shadow-2xl">
      <header className="flex items-start justify-between gap-3 border-b border-surface-border p-5"><div><h2 id={`${id}-title`} className="font-headline-md">Test {environment.name} endpoint</h2><p id={`${id}-description`} className="mt-1 text-body-sm text-ink-muted">One response request using saved configuration r{environment.revision}. No feedback or RCA is created.</p></div><button type="button" onClick={onClose} aria-label="Close endpoint test" className="rounded-lg p-1.5 text-ink-muted hover:bg-canvas"><X size={18} /></button></header>
      <div className="space-y-4 overflow-auto p-5">
        <p className="break-all rounded-lg bg-canvas p-3 font-code-xs text-ink-secondary">{environment.url}</p>
        <p className="text-metadata text-ink-muted">Uses the backend's runtime credentials—not your browser identity. Unsaved connection edits are not tested. The upstream response timeout is capped at 60 seconds; requests are never automatically replayed.</p>
        <label className="block text-label-sm font-medium">Sample question<textarea data-dialog-autofocus aria-label="Endpoint test question" value={question} maxLength={2000} rows={3} disabled={busy || Boolean(runningId)} onChange={(event) => { setQuestion(event.target.value); setResult(null); setError(null); key.current = null; }} className="mt-1.5 w-full rounded-lg border border-surface-border bg-canvas p-3 text-body-sm font-normal outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:opacity-60" /></label>
        <p className="text-metadata text-ink-muted">Use a non-sensitive test question. A successful response confirms connectivity, not correctness or a deployed fix.</p>
        {busy && <p role="status" className="flex items-center gap-2 text-body-sm text-ink-secondary"><LoaderCircle size={16} className="motion-safe:animate-spin" />Waiting for a completed agent response… You can close this window; use Refresh environments to see the saved result later.</p>}
        {error && <p role="alert" className="rounded-lg bg-issue-soft p-3 text-body-sm text-issue-red">{error}</p>}
        {result && <section aria-label="Endpoint test result" className="space-y-3 rounded-lg border border-surface-border bg-canvas p-4"><div className="flex flex-wrap items-center gap-2 text-label-sm font-semibold">{result.status === 'succeeded' ? <CheckCircle2 size={17} className="text-evidence-teal" /> : result.status === 'failed' ? <XCircle size={17} className="text-issue-red" /> : <LoaderCircle size={16} />}<span>{result.status === 'succeeded' ? 'Completed response received' : result.status === 'failed' ? 'Endpoint test failed' : result.status === 'running' ? 'Test is running' : 'Test outcome unknown'}</span>{result.httpStatus != null && <span className="rounded bg-surface px-2 py-1 font-code-xs">HTTP {result.httpStatus}</span>}{result.elapsedMs != null && <span className="text-metadata font-normal text-ink-muted">{(result.elapsedMs / 1000).toFixed(2)}s</span>}</div>
          {result.error && <p role="alert" className="whitespace-pre-wrap text-body-sm text-issue-red">{result.error}</p>}
          {result.message && <p className="text-body-sm text-ink-secondary">{result.message}</p>}
          {result.answerPreview && <div><h3 className="text-metadata font-semibold text-ink-secondary">Response preview</h3><p tabIndex={0} className="mt-2 max-h-52 overflow-auto whitespace-pre-wrap break-words text-body-sm text-ink-secondary">{result.answerPreview}</p></div>}
          {result.runtimeIdentity && <p className="text-metadata text-ink-muted">{result.runtimeIdentity.label}{result.runtimeIdentity.principal ? ` · ${result.runtimeIdentity.principal}` : ' · principal not reported'}{result.runtimeIdentity.credentialType ? ` · ${result.runtimeIdentity.credentialType}` : ''}</p>}
          <p className="break-all font-code-xs text-ink-muted">{result.id} · configuration r{result.configurationRevision}</p>
          {result.outcomeUnknown && <p className="text-metadata text-review-amber">The upstream may already have processed the request. Starting a new test is a deliberate new request, not recovery of this one.</p>}
        </section>}
      </div>
      <footer className="flex flex-wrap justify-end gap-2 border-t border-surface-border p-4"><button type="button" onClick={onClose} className="rounded-lg border border-surface-border px-3 py-2 text-label-sm">Close</button>{!runningId && <button type="button" disabled={busy || !question.trim()} onClick={() => void run(Boolean(priorTerminal))} className="rounded-lg bg-primary-container px-4 py-2 text-label-sm font-semibold text-on-primary disabled:opacity-45">{busy ? 'Testing…' : priorTerminal ? 'Run new test' : error && key.current ? 'Check previous attempt' : 'Send one test request'}</button>}</footer>
    </AnimatedSection>
  </AnimatedDiv>, document.body);
}
