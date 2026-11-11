import React, { useEffect, useRef, useState } from 'react';
import { ArrowUpRight, ChevronDown, RefreshCw } from 'lucide-react';
import { PromotionBatch, cancelPromotion, getPromotion, getPromotions } from '../api/feedbackApi';
import { AnimatedCollapse } from './UiMotion';
import { formatRcaLabel } from '../utils/formatRcaLabel';
import { ActionButton } from './ActionButton';

export function PromotionProgress({ batchId, initial, onOpenFeedback, onViewEnvironment, onUpdated }: {
  batchId: string; initial?: PromotionBatch; onOpenFeedback: (id: string) => void; onViewEnvironment: (id: string) => void; onUpdated?: () => void;
}) {
  const [batch, setBatch] = useState<PromotionBatch | null>(initial || null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(true);
  const [busy, setBusy] = useState(false);
  const root = useRef<HTMLElement>(null);
  const priorFinished = useRef(Boolean(initial?.finished));
  const changed = useRef(onUpdated); changed.current = onUpdated;
  useEffect(() => {
    let cancelled = false, inFlight = false;
    const load = async () => {
      if (inFlight || document.visibilityState !== 'visible' || !root.current?.getClientRects().length) return;
      inFlight = true;
      try { const value = await getPromotion(batchId); if (!cancelled) { setBatch(value); setError(null); if (value.finished && !priorFinished.current) changed.current?.(); priorFinished.current = value.finished; } }
      catch (error) { if (!cancelled) setError(error instanceof Error ? error.message : 'Could not load batch progress'); }
      finally { inFlight = false; }
    };
    void load(); const timer = window.setInterval(() => { if (!priorFinished.current) void load(); }, 5000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [batchId]);
  const cancel = async () => { if (busy) return; setBusy(true); try { setBatch(await cancelPromotion(batchId)); } catch (error) { setError(error instanceof Error ? error.message : 'Could not cancel queued items'); } finally { setBusy(false); } };
  const complete = batch ? batch.counts.completed + batch.counts.failed + batch.counts.cancelled : 0;
  return <section ref={root} aria-label="Promotion progress" className="overflow-hidden rounded-xl border border-surface-border bg-surface">
    <header className="flex flex-wrap items-start justify-between gap-3 p-4"><div><h2 className="font-title-md">{batch?.targetName || 'Environment promotion'} <span className="ml-2 text-metadata font-normal text-ink-muted">{batch?.finished ? batch.counts.cancelled === batch.total ? 'Batch cancelled' : batch.counts.failed ? 'Finished with failures' : 'Batch finished' : 'In progress'}</span></h2><p role="status" className="mt-1 text-metadata text-ink-secondary">{batch ? `${complete} / ${batch.total} processed · ${batch.counts.queued} queued · ${batch.counts.running} running · ${batch.counts.failed} failed${batch.counts.cancelled ? ` · ${batch.counts.cancelled} cancelled` : ''}` : 'Loading batch progress…'}</p></div><div className="flex flex-wrap gap-2">{batch && <ActionButton label="View target environment" compactLabel="Environment" icon={<ArrowUpRight />} size="sm" onClick={() => onViewEnvironment(batch.targetId)} />}{batch?.canCancel && <button type="button" disabled={busy} onClick={() => void cancel()} className="rounded-lg border border-surface-border px-2.5 py-1.5 text-label-sm text-ink-secondary disabled:opacity-50">Cancel queued</button>}<button type="button" aria-label="Toggle promotion details" aria-expanded={expanded} onClick={() => setExpanded((value) => !value)} className="rounded-lg p-2 text-ink-muted"><ChevronDown size={16} className={`transition-transform ${expanded ? 'rotate-180' : ''}`} /></button></div></header>
    {batch && <div role="progressbar" aria-label="Promotion completion" aria-valuemin={0} aria-valuemax={batch.total} aria-valuenow={complete} className="h-1 bg-canvas"><div className="h-full bg-primary-container transition-[width] duration-200" style={{ width: `${batch.total ? complete / batch.total * 100 : 0}%` }} /></div>}
    {error && <p role="alert" className="px-4 py-3 text-body-sm text-issue-red">{error}</p>}
    {batch && <AnimatedCollapse open={expanded}><div className="max-h-80 overflow-auto border-t border-surface-border"><ul className="divide-y divide-surface-border">{batch.items.map((item) => <li key={item.id} className="flex flex-wrap items-center gap-3 px-4 py-2.5 text-body-sm"><button type="button" onClick={() => { onViewEnvironment(batch.targetId); onOpenFeedback(item.feedbackId); }} className="font-code-xs font-semibold text-ink-primary underline underline-offset-4">{item.feedbackId}</button><span className={item.status === 'failed' ? 'text-issue-red' : 'text-ink-secondary'}>{item.status === 'running' ? item.phase === 'rca' ? 'Answer saved · checking RCA' : 'Fetching fresh answer' : formatRcaLabel(item.status)}</span>{item.assessment && <span className="text-metadata text-ink-muted">{formatRcaLabel(item.assessment)} · AI not verified</span>}{item.error && <p className="basis-full text-metadata text-issue-red">{item.error}</p>}</li>)}</ul><p className="border-t border-surface-border px-4 py-3 text-metadata text-ink-muted">Completed means processing finished, not that the answer is correct. Running calls finish normally if queued items are cancelled. Saved responses and safe RCA are automatically owner-visible.</p></div></AnimatedCollapse>}
  </section>;
}

export function PromotionActivity({ onOpenFeedback, onViewEnvironment, refresh }: { onOpenFeedback: (id: string) => void; onViewEnvironment: (id: string) => void; refresh?: number }) {
  const [batches, setBatches] = useState<PromotionBatch[]>([]);
  const [selected, setSelected] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  useEffect(() => { let cancelled = false; void getPromotions().then((values) => { if (!cancelled) { setBatches(values); setError(null); } }).catch((error) => { if (!cancelled) setError(error instanceof Error ? error.message : 'Could not load promotion history'); }); return () => { cancelled = true; }; }, [refresh, reload]);
  if (!batches.length && !error) return null;
  return <div className="space-y-3"><div className="flex flex-wrap items-center gap-2"><label className="text-label-sm text-ink-secondary">Recent promotions<select aria-label="Recent promotions" value={selected} onChange={(event) => setSelected(event.target.value)} className="ml-2 max-w-full rounded-lg border border-surface-border bg-surface px-2 py-1.5 text-body-sm"><option value="">Choose a batch…</option>{batches.map((batch) => <option value={batch.id} key={batch.id}>{batch.targetName} · {batch.total} feedback · {new Date(batch.createdAt).toLocaleString()}</option>)}</select></label><ActionButton label="Refresh promotions" icon={<RefreshCw />} size="sm" tone="ghost" onClick={() => setReload((value) => value + 1)} /></div>{error && <p role="alert" className="text-body-sm text-issue-red">{error}</p>}{selected && <PromotionProgress key={selected} batchId={selected} onOpenFeedback={onOpenFeedback} onViewEnvironment={onViewEnvironment} />}</div>;
}
