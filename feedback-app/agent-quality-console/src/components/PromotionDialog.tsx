import React, { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { ArrowRight, Settings2, X } from 'lucide-react';
import { AgentEnvironmentConfig, PromotionBatch, PromotionPreview, PromotionSelection, createPromotion, previewPromotion } from '../api/feedbackApi';
import { AnimatedDiv, AnimatedSection } from './UiMotion';
import { containDialogFocus, useDialogFocus } from '../utils/dialogFocus';
import { ActionButton } from './ActionButton';

export function PromotionDialog({ selection, environments, onClose, onSubmitted, onSettings }: {
  selection: PromotionSelection; environments: AgentEnvironmentConfig[]; onClose: () => void;
  onSubmitted: (batch: PromotionBatch) => void; onSettings: () => void;
}) {
  const id = useId();
  const dialog = useRef<HTMLElement>(null);
  useDialogFocus(dialog);
  const [preview, setPreview] = useState<PromotionPreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const choices = environments.filter((row) => row.id !== selection.filters.environment_id);
  const [targetId, setTargetId] = useState(() => choices.find((row) => row.canRetest)?.id || '');
  const target = choices.find((row) => row.id === targetId);
  const intentKeys = useRef(new Map<string, string>());
  useEffect(() => {
    let cancelled = false; setLoading(true); setError(null); setPreview(null);
    void previewPromotion(selection).then((value) => { if (!cancelled) setPreview(value); })
      .catch((error) => { if (!cancelled) setError(error instanceof Error ? error.message : 'Could not review the selection'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [selection, reload]);
  const submit = async (event: React.FormEvent) => {
    event.preventDefault(); if (busy || !preview || !target?.canRetest) return;
    setBusy(true); setError(null);
    const intent = `${targetId}:${preview.selectionToken}`;
    if (!intentKeys.current.has(intent)) intentKeys.current.set(intent, crypto.randomUUID());
    try { onSubmitted(await createPromotion(selection, targetId, preview.selectionToken, intentKeys.current.get(intent)!)); }
    catch (error) { setError(error instanceof Error ? error.message : 'Could not start promotion. No automatic retry was made.'); }
    finally { setBusy(false); }
  };
  const close = () => { if (!busy) onClose(); };
  return createPortal(<AnimatedDiv surface="backdrop" className="fixed inset-0 z-[70] flex items-center justify-center bg-ink-primary/35 p-4" onClick={(event) => { if (event.target === event.currentTarget) close(); }}>
    <AnimatedSection ref={dialog} role="dialog" aria-modal="true" aria-labelledby={`${id}-title`} aria-describedby={`${id}-description`} onKeyDown={(event) => containDialogFocus(event, close)} className="flex max-h-[90dvh] w-full max-w-xl flex-col overflow-hidden rounded-xl border border-surface-border bg-surface shadow-2xl">
      <header className="flex items-start justify-between gap-3 border-b border-surface-border p-5"><div><h2 id={`${id}-title`} className="font-headline-md">Promote & retest</h2><p id={`${id}-description`} className="mt-1 text-body-sm text-ink-muted">Same feedback IDs. Fresh answers and RCA in the target environment.</p></div><button type="button" disabled={busy} aria-label="Close promotion" onClick={close} className="rounded-lg p-1.5 text-ink-muted hover:bg-canvas"><X size={18} /></button></header>
      <form onSubmit={(event) => void submit(event)} className="space-y-4 overflow-auto p-5">
        {loading ? <p role="status" className="text-body-sm text-ink-muted">Checking the exact selection and input revisions…</p> : preview && <div className="rounded-lg border border-surface-border bg-canvas p-4"><p className="text-body-sm font-semibold">{preview.count} feedback record{preview.count === 1 ? '' : 's'} selected</p><p className="mt-1 text-metadata text-ink-muted">This requests {preview.count} fresh agent response{preview.count === 1 ? '' : 's'} and an evidence-backed RCA for each. Original submissions are not moved, copied or overwritten.</p><ul className="mt-3 space-y-1 text-metadata text-ink-secondary">{preview.items.map((row) => <li key={row.id} className="truncate">{row.title} <span className="font-code-xs text-ink-muted">· {row.id} · r{row.revision}</span></li>)}{preview.count > preview.items.length && <li className="text-ink-muted">and {preview.count - preview.items.length} more…</li>}</ul></div>}
        <label className="block text-label-sm font-medium">Target environment<select data-dialog-autofocus aria-label="Promotion target environment" value={targetId} disabled={busy} onChange={(event) => setTargetId(event.target.value)} className="mt-1.5 w-full rounded-lg border border-surface-border bg-surface px-3 py-2.5 text-body-sm"><option value="">Choose target environment…</option>{choices.map((row) => <option key={row.id} value={row.id} disabled={!row.canRetest}>{row.name}{row.kind === 'prod' ? ' · Production' : ''}{!row.canRetest ? ' · unavailable' : ''}</option>)}</select></label>
        {target?.kind === 'prod' && <p className="rounded-lg bg-review-soft p-3 text-body-sm text-review-amber">Production execution: confirm that you intend to send these questions to the production agent. Your explicit production grant is checked again on the server.</p>}
        {!choices.some((row) => row.canRetest) && <p className="text-body-sm text-ink-muted">No authorized target is ready. Configure an enabled environment and ensure its runtime permissions and worker are available.</p>}
        {target?.canRetest && <p className="text-metadata text-ink-muted">Saving a connection does not verify runtime access. For an untested endpoint, start with one feedback before running a large batch.</p>}
        <ActionButton label="Manage environments" compactLabel="Manage" icon={<Settings2 />} tone="ghost" size="sm" disabled={busy} onClick={onSettings} />
        {error && <div role="alert" className="rounded-lg bg-issue-soft p-3 text-body-sm text-issue-red">{error}<button type="button" disabled={busy} onClick={() => setReload((value) => value + 1)} className="mt-2 block text-label-sm font-semibold underline">Review selection again</button></div>}
        <p className="text-metadata text-ink-muted">Results appear automatically, including incorrect or inconclusive outcomes. Promotion never deploys a fix or resolves the original report.</p>
        <footer className="flex justify-end gap-2 border-t border-surface-border pt-4"><button type="button" disabled={busy} onClick={close} className="rounded-lg border border-surface-border px-3 py-2 text-label-sm">Cancel</button><button type="submit" disabled={busy || loading || !preview || !target?.canRetest} className="inline-flex items-center gap-2 rounded-lg bg-primary-container px-4 py-2 text-label-sm font-semibold text-on-primary disabled:opacity-45">{busy ? 'Starting batch…' : `Confirm & run${preview ? ` ${preview.count}` : ''}`}<ArrowRight size={15} /></button></footer>
      </form>
    </AnimatedSection>
  </AnimatedDiv>, document.body);
}
