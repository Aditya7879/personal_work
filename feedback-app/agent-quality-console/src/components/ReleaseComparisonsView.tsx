import React from 'react';
import { EvaluationRunRecord } from '../api/feedbackApi';
import { RefreshCw } from 'lucide-react';
import { ActionButton } from './ActionButton';

export const ReleaseComparisonsView: React.FC<{ runs: EvaluationRunRecord[]; loading: boolean; onRefresh: () => void }> = ({ runs, loading, onRefresh }) => {
  const completed = runs.filter((run) => run.status === 'completed' && run.pass_rate != null);
  const candidate = completed[0];
  const baseline = candidate
    ? completed.slice(1).find((run) => run.dataset_id === candidate.dataset_id && run.dataset_version === candidate.dataset_version)
    : undefined;
  const delta = candidate && baseline ? (candidate.pass_rate || 0) - (baseline.pass_rate || 0) : null;
  return <div className="flex flex-col gap-space-lg">
    <header className="flex flex-wrap items-end justify-between gap-3"><div><div className="font-metadata uppercase tracking-wider text-ink-muted">Release gates</div><h1 className="mt-1 font-headline-lg text-ink-primary">Evaluation comparison</h1><p className="mt-1 font-body-md text-ink-secondary">Compare completed BigQuery evaluation runs. This view does not approve or deploy releases.</p></div><ActionButton label="Refresh runs" icon={<RefreshCw />} onClick={onRefresh} loading={loading} /></header>
    {loading && runs.length === 0 && <ReleaseSkeleton />}
    {loading && runs.length > 0 && <p className="flex items-center gap-2 font-metadata text-ink-muted"><span className="h-2 w-2 animate-pulse rounded-full bg-primary-container" />Refreshing evaluation data…</p>}
    {!loading && !candidate && <div className="rounded-xl border border-dashed border-surface-border bg-surface p-space-xl text-center"><h2 className="font-title-md text-ink-primary">No completed evaluation to compare</h2><p className="mt-1 text-body-sm text-ink-muted">Run an evaluation on an approved golden dataset first.</p></div>}
    {candidate && <>
      <section className="rounded-xl border border-surface-border bg-surface p-space-lg shadow-sm"><div className="grid gap-space-md md:grid-cols-3"><Metric label="Candidate" value={`${candidate.dataset_name} v${candidate.dataset_version}`} /><Metric label="Pass rate" value={`${candidate.pass_rate?.toFixed(1)}%`} /><Metric label="Change vs prior run" value={delta == null ? 'Baseline unavailable' : `${delta >= 0 ? '+' : ''}${delta.toFixed(1)}%`} /></div></section>
      {candidate && baseline && <section className="grid gap-space-md md:grid-cols-2"><RunCard label="Latest run" run={candidate} /><RunCard label="Previous completed run" run={baseline} /></section>}
      <p className="text-metadata text-ink-muted">Comparison is descriptive only. Release approval gates and human sign-off are not implemented yet.</p>
    </>}
      <section className="overflow-hidden rounded-xl border border-surface-border bg-surface"><div className="border-b border-surface-border p-space-md"><h2 className="font-title-md text-ink-primary">Completed runs</h2></div>{loading && runs.length === 0 ? <div className="space-y-2 p-space-md"><div className="skeleton h-12 rounded-lg" /><div className="skeleton h-12 rounded-lg" /></div> : <div className="divide-y divide-surface-border">{completed.map((run) => <div key={run.id} className="flex flex-wrap items-center justify-between gap-2 p-space-md"><div><span className="font-code-xs text-primary">{run.id}</span><span className="ml-3 text-body-sm text-ink-primary">{run.dataset_name} v{run.dataset_version}</span></div><span className="font-label-md text-ink-secondary tabular-nums">{run.pass_rate?.toFixed(1)}% · {run.passed_cases}/{run.total_cases} passed</span></div>)}</div>}</section>
  </div>;
};

function Metric({ label, value }: { label: string; value: string }) { return <div className="rounded-lg bg-canvas p-space-md"><p className="font-metadata uppercase text-ink-muted">{label}</p><p className="mt-1 break-words font-title-md text-ink-primary">{value}</p></div>; }
function RunCard({ label, run }: { label: string; run: EvaluationRunRecord }) { return <article className="rounded-xl border border-surface-border bg-surface p-space-lg"><p className="font-metadata uppercase text-ink-muted">{label}</p><h2 className="mt-2 font-title-md text-ink-primary">{run.dataset_name} · v{run.dataset_version}</h2><p className="mt-1 font-code-xs text-primary">{run.id}</p><p className="mt-4 font-headline-lg text-ink-primary tabular-nums">{run.pass_rate?.toFixed(1)}%</p><p className="text-body-sm text-ink-secondary">{run.passed_cases} passed · {run.failed_cases} failed · {run.review_required_cases} require review</p></article>; }

function ReleaseSkeleton() {
  return <div className="grid gap-space-md md:grid-cols-3" role="status" aria-label="Loading release comparison">
    {Array.from({ length: 3 }, (_, index) => <div key={index} className="skeleton h-28 rounded-xl" />)}
  </div>;
}
