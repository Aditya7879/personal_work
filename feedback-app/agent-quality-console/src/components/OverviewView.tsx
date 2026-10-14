import React from 'react';
import { OverviewMetrics } from '../api/feedbackApi';
import { ViewPath } from '../types';

export const OverviewView: React.FC<{
  metrics: OverviewMetrics | null;
  loading: boolean;
  onNavigate: (view: ViewPath) => void;
  onRefresh: () => void;
}> = ({ metrics, loading, onNavigate, onRefresh }) => (
  <div className="flex flex-col gap-space-lg">
    <header className="flex items-end justify-between gap-space-md">
      <div><p className="font-metadata uppercase tracking-wider text-ink-muted">Agent quality</p><h1 className="mt-1 font-headline-lg text-ink-primary">Overview</h1><p className="mt-1 font-body-md text-ink-secondary">Live counts from the feedback and evaluation records stored in BigQuery.</p></div>
      <button onClick={onRefresh} className="rounded-lg border border-surface-border bg-surface px-3 py-2 text-label-md text-ink-primary" type="button">Refresh</button>
    </header>
    {loading && <div className="rounded-xl border border-surface-border bg-surface p-space-lg text-body-sm text-ink-muted">Loading workspace metrics…</div>}
    {!loading && metrics && <div className="grid gap-space-md sm:grid-cols-2 xl:grid-cols-4">
      <Metric label="Feedback submitted" value={metrics.feedback_total} action={() => onNavigate('feedback-inbox')} />
      <Metric label="Needs review" value={metrics.feedback_needing_review} action={() => onNavigate('triage-queue')} />
      <Metric label="Golden datasets" value={metrics.golden_dataset_count} action={() => onNavigate('golden-datasets')} />
      <Metric label="Approved golden cases" value={metrics.approved_case_count} action={() => onNavigate('golden-datasets')} />
    </div>}
    {!loading && metrics && <section className="rounded-xl border border-surface-border bg-surface p-space-lg shadow-sm"><div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-title-md text-ink-primary">Latest evaluation</h2><p className="mt-1 text-body-sm text-ink-secondary">{metrics.latest_evaluation_id || 'No evaluation has been run yet.'}</p></div><div className="text-right"><span className="font-metadata uppercase text-ink-muted">Pass rate</span><p className="font-headline-md text-ink-primary">{metrics.latest_pass_rate == null ? '—' : `${metrics.latest_pass_rate.toFixed(1)}%`}</p></div></div><button onClick={() => onNavigate('evaluation-runs')} className="mt-4 rounded-lg bg-primary-container px-3 py-2 text-label-sm font-semibold text-on-primary" type="button">Open evaluations</button></section>}
  </div>
);

function Metric({ label, value, action }: { label: string; value: number; action: () => void }) {
  return <button onClick={action} className="rounded-xl border border-surface-border bg-surface p-space-md text-left shadow-sm hover:border-primary-container"><span className="font-metadata uppercase tracking-wide text-ink-muted">{label}</span><span className="mt-2 block font-code-sm text-[30px] font-semibold text-ink-primary">{value}</span></button>;
}
