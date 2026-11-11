import React, { Suspense, lazy } from 'react';
import { OverviewMetrics } from '../api/feedbackApi';
import { ViewPath } from '../types';
import { formatRcaLabel } from '../utils/formatRcaLabel';
import { ArrowUpRight, ChevronRight, Database, Flag, Inbox, ListChecks, RefreshCw, ScanSearch, type LucideIcon } from 'lucide-react';
import { ActionButton } from './ActionButton';

const DashboardCharts = lazy(() => import('./DashboardCharts'));
type Navigate = (view: ViewPath, targetId?: string) => void;

export const OverviewView: React.FC<{
  metrics: OverviewMetrics | null;
  loading: boolean;
  onNavigate: Navigate;
  onRefresh: () => void;
  environmentName?: string;
}> = ({ metrics, loading, onNavigate, onRefresh, environmentName = 'All environments' }) => {
  const feedbackInPeriod = metrics?.feedback_trend.reduce((sum, point) => sum + point.feedback_count, 0) || 0;
  const issueInPeriod = metrics?.feedback_trend.reduce((sum, point) => sum + point.issue_count, 0) || 0;

  return (
    <div className="overview-workspace flex flex-col gap-5 pb-6">
      <header className="flex flex-wrap items-end justify-between gap-space-md">
        <div>
          <h1 className="font-headline-lg text-ink-primary">{environmentName} overview</h1>
          <p className="mt-1 text-body-md text-ink-muted">Distinct feedback cases and latest saved-answer checks for the selected environment. Promoting a case does not create another feedback record.</p>
        </div>
        <div className="flex items-center gap-space-sm">
          {loading && metrics && <span className="font-metadata text-ink-muted">Showing saved data · refreshing</span>}
          <span className="hidden text-metadata text-ink-muted sm:inline">Activity window · 30 days</span>
          <ActionButton label="Refresh" icon={<RefreshCw />} disabled={loading} loading={loading} onClick={onRefresh} />
        </div>
      </header>

      {loading && !metrics && <OverviewSkeleton />}
      {!loading && !metrics && (
        <div className="rounded-xl border border-dashed border-surface-border bg-surface p-space-xl text-center">
          <p className="font-title-md text-ink-primary">Overview data is unavailable</p>
          <p className="mt-1 font-body-sm text-ink-muted">Check the BigQuery connection, then refresh this page.</p>
        </div>
      )}

      {metrics && <>
        <section className="metric-rail grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-surface-border bg-surface-border lg:grid-cols-5" aria-label="Quality metrics">
          <MetricCard label="Feedback cases" value={metrics.feedback_total} detail={metrics.scope?.environmentId ? `${metrics.native_feedback_count || 0} reported here · ${metrics.promoted_feedback_count || 0} promoted in` : `${metrics.all_feedback_total ?? metrics.feedback_total} distinct reports · no promotion duplicates`} icon={Inbox} action={() => onNavigate('feedback-inbox')} />
          <MetricCard label="Open source reports" value={metrics.feedback_needing_review} detail="Original report workflows, not target verdicts" icon={ListChecks} action={() => onNavigate('triage-queue')} />
          <MetricCard label="RCA assessments" value={metrics.rca_runs_count} detail="Latest saved answer per case / environment" icon={ScanSearch} action={() => onNavigate('feedback-inbox')} />
          <MetricCard label="Retest attempts" value={metrics.retest_count || 0} detail={`${metrics.queued_retest_count || 0} queued · ${metrics.running_retest_count || 0} running · ${metrics.failed_retest_count || 0} failed`} icon={RefreshCw} action={() => onNavigate('feedback-inbox')} />
          <MetricCard label="New reported issues" value={issueInPeriod} detail={`${feedbackInPeriod} source submissions · last 30 days`} icon={Flag} action={() => onNavigate('feedback-inbox')} />
        </section>

        <Suspense fallback={<ChartPanelsSkeleton />}>
          <DashboardCharts metrics={metrics} onNavigate={onNavigate} />
        </Suspense>

        <section className="grid items-start gap-4 xl:grid-cols-12">
          {!!metrics.subcategory_breakdown.length && <Panel className="xl:col-span-4" title="Frequent defects" description="Latest saved-answer RCA in this scope">
            <SubcategoryList data={metrics.subcategory_breakdown} />
          </Panel>}
          <Panel className={metrics.subcategory_breakdown.length ? 'xl:col-span-8' : 'xl:col-span-12'} title="Recent feedback" description="Source updates and linked environment checks" action={<ActionButton label="Open inbox" icon={<ArrowUpRight />} tone="ghost" size="sm" onClick={() => onNavigate('feedback-inbox')} />}>
            <RecentFeedback items={metrics.recent_feedback} onNavigate={onNavigate} />
          </Panel>
        </section>
        <section className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-surface-border bg-surface p-4" aria-label="Agent-wide resources"><div><h2 className="font-title-md">Agent-wide resources</h2><p className="mt-1 text-metadata text-ink-muted">Golden datasets and legacy evaluations are shared across environments, not attributed to the selected environment.</p></div><button type="button" onClick={() => onNavigate('golden-datasets')} className="inline-flex items-center gap-2 rounded-lg border border-surface-border px-3 py-2 text-label-sm text-ink-secondary"><Database size={15} />{metrics.golden_dataset_count} golden datasets · {metrics.approved_case_count} approved cases</button></section>
      </>}
    </div>
  );
};

function MetricCard({ label, value, detail, icon: Icon, action }: {
  label: string;
  value: number;
  detail: string;
  icon: LucideIcon;
  action: () => void;
}) {
  return <button type="button" onClick={action} className="group min-w-0 bg-surface px-4 py-4 text-left outline-none transition-colors last:col-span-2 hover:bg-canvas focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary lg:last:col-span-1">
    <div className="flex items-start justify-between gap-2">
      <span className="truncate text-label-sm font-medium text-ink-secondary">{label}</span>
      <Icon size={15} aria-hidden="true" className="hidden shrink-0 text-ink-muted xl:block" />
    </div>
    <span className="mt-2 block font-metric tabular-nums">{value.toLocaleString()}</span>
    <span className="mt-1 block text-metadata text-ink-muted">{detail}</span>
  </button>;
}

function Panel({ title, description, action, className = '', children }: {
  title: string;
  description: string;
  action?: React.ReactNode;
  className?: string;
  children: React.ReactNode;
}) {
  return <section className={`workspace-panel min-w-0 rounded-xl border border-surface-border bg-surface p-4 sm:p-5 ${className}`}>
    <div className="mb-space-md flex flex-wrap items-start justify-between gap-2">
      <div>
        <h2 className="font-title-md text-ink-primary">{title}</h2>
        <p className="mt-0.5 text-metadata text-ink-muted">{description}</p>
      </div>
      {action}
    </div>
    {children}
  </section>;
}

function SubcategoryList({ data }: { data: OverviewMetrics['subcategory_breakdown'] }) {
  if (!data.length) return <Empty text="Subcategories appear after an RCA run detects a specific defect." />;
  return <div className="divide-y divide-surface-border">
    {data.map((item, index) => <div key={`${item.category || 'uncategorized'}-${item.subcategory}`} className="flex items-center gap-3 py-2.5 first:pt-0 last:pb-0">
      <span className="w-5 shrink-0 text-metadata tabular-nums text-ink-muted">{String(index + 1).padStart(2, '0')}</span>
      <div className="min-w-0 flex-1">
        <p className="break-words font-label-sm font-medium text-ink-primary">{formatRcaLabel(item.subcategory)}</p>
        {item.category && <p className="mt-0.5 truncate font-metadata text-ink-muted">{formatRcaLabel(item.category)}</p>}
      </div>
      <span className="font-label-sm font-semibold tabular-nums text-ink-secondary">{item.count}</span>
    </div>)}
  </div>;
}

function RecentFeedback({ items, onNavigate }: { items: OverviewMetrics['recent_feedback']; onNavigate: Navigate }) {
  if (!items.length) return <Empty text="New feedback records will appear here." />;
  return <div className="divide-y divide-surface-border">
    {items.slice(0, 5).map((item) => <button key={item.feedback_id} type="button" onClick={() => onNavigate('feedback-detail', item.feedback_id)} className="flex w-full items-center gap-3 rounded-md py-2.5 text-left outline-none transition-colors first:pt-0 last:pb-0 hover:bg-canvas focus-visible:ring-2 focus-visible:ring-primary">
      <Inbox size={15} aria-hidden="true" className="shrink-0 text-ink-muted" />
      <div className="min-w-0 flex-1">
        <p className="truncate font-label-md font-medium text-ink-primary">{item.title || 'Feedback'}</p>
        <p className="mt-0.5 truncate text-metadata text-ink-muted">{item.feedback_id} · {item.state}{item.root_cause ? ` · ${formatRcaLabel(item.root_cause)}` : ''}</p>
      </div>
      <span className="hidden shrink-0 rounded-md border border-surface-border px-2 py-1 text-metadata text-ink-secondary sm:inline">{item.user_verdict}</span>
      <ChevronRight size={15} aria-hidden="true" className="shrink-0 text-ink-muted" />
    </button>)}
  </div>;
}

function Empty({ text }: { text: string }) {
  return <p className="py-4 text-body-sm text-ink-muted">{text}</p>;
}

function OverviewSkeleton() {
  return <div className="flex flex-col gap-space-md" aria-label="Loading overview">
    <div className="grid gap-space-md sm:grid-cols-2 xl:grid-cols-5">{Array.from({ length: 5 }, (_, index) => <div key={index} className="h-32 animate-pulse rounded-xl border border-surface-border bg-surface" />)}</div>
    <div className="grid gap-4 xl:grid-cols-12"><div className="skeleton h-64 rounded-xl border border-surface-border xl:col-span-8" /><div className="skeleton h-64 rounded-xl border border-surface-border xl:col-span-4" /></div>
  </div>;
}

function ChartPanelsSkeleton() {
  return <div className="grid gap-space-md xl:grid-cols-12" aria-label="Loading charts">
    <div className="skeleton h-64 rounded-xl border border-surface-border xl:col-span-8" />
    <div className="skeleton h-64 rounded-xl border border-surface-border xl:col-span-4" />
    <div className="skeleton h-32 rounded-xl border border-surface-border xl:col-span-6" />
    <div className="skeleton h-32 rounded-xl border border-surface-border xl:col-span-6" />
  </div>;
}
