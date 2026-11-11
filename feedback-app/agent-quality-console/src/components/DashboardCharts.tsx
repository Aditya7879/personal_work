import React from 'react';
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { OverviewMetrics } from '../api/feedbackApi';
import { ViewPath } from '../types';
import { formatRcaLabel } from '../utils/formatRcaLabel';
import { ArrowUpRight, CircleDashed } from 'lucide-react';
import { ActionButton } from './ActionButton';

type Navigate = (view: ViewPath, targetId?: string) => void;
const workflowStages = ['Submitted', 'Triaged', 'Evidence review', 'Review complete', 'Golden candidate', 'Approved for dataset'];
const tooltipStyle: React.CSSProperties = {
  border: '1px solid var(--color-surface-border)',
  borderRadius: 10,
  boxShadow: '0 4px 16px rgba(16, 24, 40, 0.08)',
  backgroundColor: 'var(--color-surface)',
  color: 'var(--color-ink-primary)',
  fontFamily: 'Inter, system-ui, sans-serif',
  fontSize: 12,
};

export default function DashboardCharts({ metrics, onNavigate }: {
  metrics: OverviewMetrics;
  onNavigate: Navigate;
}) {
  const activeFeedbackDays = metrics.feedback_trend.filter((item) => item.feedback_count > 0).length;
  const hasTrend = activeFeedbackDays > 1;
  const verdictDescription = metrics.scope?.environmentId ? 'Source-reported verdicts for cases in this environment, not target-agent correctness' : activeFeedbackDays === 1
    ? 'User-reported · imported records share one date' : 'User-reported verdicts, not independent validation';

  return <>
    <section className="grid gap-4 lg:grid-cols-12">
      <Panel className="lg:col-span-8" title={hasTrend ? 'Feedback activity' : 'Feedback verdicts'} description={hasTrend ? 'Daily submissions and reported issues · last 30 days' : verdictDescription}>
        <FeedbackTrendChart data={metrics.feedback_trend} verdicts={metrics.verdict_breakdown} />
      </Panel>
      <Panel className="lg:col-span-4" title="Source report review progress" description="Original report workflows; promotion does not reset or resolve them">
        <WorkflowProgression data={metrics.state_breakdown} />
      </Panel>
    </section>

    <section className="grid items-start gap-4 lg:grid-cols-12">
      <Panel className="lg:col-span-6" title="RCA classifications" description="Latest saved-answer assessment per case and environment; no cross-environment fallback" action={<ActionButton label="Review feedback" icon={<ArrowUpRight />} tone="ghost" size="sm" onClick={() => onNavigate('feedback-inbox')} />}>
        <RootCauseChart data={metrics.root_cause_breakdown} />
      </Panel>
      <Panel className="lg:col-span-6" title="Retest assessments" description="Automated comparisons in this scope · unverified, never an owner confirmation">
        {metrics.assessment_breakdown?.length ? <ul className="space-y-3">{metrics.assessment_breakdown.map((entry) => <li key={entry.verdict} className="flex items-center justify-between gap-3 text-body-sm"><span className="text-ink-secondary">{formatRcaLabel(entry.verdict)}</span><span className="font-semibold tabular-nums">{entry.count}</span></li>)}</ul> : <ChartEmpty title="No comparison saved yet" text="Fresh answers and RCA appear after an explicitly requested retest completes." />}
      </Panel>
    </section>
    <Panel title="Evaluation performance · agent-wide" description="Legacy completed runs have no environment tag; these are not selected-environment results" action={<ActionButton label="View runs" icon={<ArrowUpRight />} tone="ghost" size="sm" onClick={() => onNavigate('evaluation-runs')} />}><EvaluationTrendChart data={metrics.evaluation_trend} latestId={metrics.latest_evaluation_id} latestPassRate={metrics.latest_pass_rate} /></Panel>
  </>;
}

function Panel({ title, description, action, className = '', children }: {
  title: string;
  description: string;
  action?: React.ReactNode;
  className?: string;
  children: React.ReactNode;
}) {
  return <section aria-label={title} className={`workspace-panel min-w-0 rounded-xl border border-surface-border bg-surface p-4 sm:p-5 ${className}`}>
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

function FeedbackTrendChart({ data, verdicts }: {
  data: OverviewMetrics['feedback_trend'];
  verdicts: OverviewMetrics['verdict_breakdown'];
}) {
  const activeDays = data.filter((item) => item.feedback_count > 0);
  const hasTrend = activeDays.length > 1;
  if (!hasTrend && !verdicts.length) return <ChartEmpty text="No feedback has been received in the last 30 days." />;

  if (!hasTrend) {
    return <VerdictChart data={verdicts} />;
  }

  return <ResponsiveContainer width="100%" height={220}>
    <AreaChart data={data} margin={{ top: 10, right: 14, left: -18, bottom: 0 }}>
      <defs>
        <linearGradient id="feedbackArea" x1="0" y1="0" x2="0" y2="1">
          <stop offset="5%" stopColor="var(--chart-primary)" stopOpacity={0.12} />
          <stop offset="95%" stopColor="var(--chart-primary)" stopOpacity={0.015} />
        </linearGradient>
      </defs>
      <CartesianGrid vertical={false} stroke="var(--color-surface-border)" strokeDasharray="4 5" />
      <XAxis dataKey="date" tickFormatter={formatShortDate} tickLine={false} axisLine={false} minTickGap={30} tick={{ fill: 'var(--color-ink-muted)', fontSize: 12 }} />
      <YAxis allowDecimals={false} tickLine={false} axisLine={false} width={42} tick={{ fill: 'var(--color-ink-muted)', fontSize: 12 }} />
      <Tooltip labelFormatter={(label) => formatShortDate(String(label))} contentStyle={tooltipStyle} />
      <Area type="monotone" dataKey="feedback_count" name="All feedback" stroke="var(--chart-primary)" strokeWidth={2} fill="url(#feedbackArea)" activeDot={{ r: 4 }} />
      <Area type="monotone" dataKey="issue_count" name="Incorrect / unsafe" stroke="var(--chart-danger)" strokeWidth={2} fill="transparent" activeDot={{ r: 4 }} />
    </AreaChart>
  </ResponsiveContainer>;
}

function VerdictChart({ data }: { data: OverviewMetrics['verdict_breakdown'] }) {
  const total = data.reduce((sum, item) => sum + item.count, 0);
  if (!total) return <ChartEmpty text="No feedback verdicts have been recorded yet." />;

  const correct = data.find((item) => item.verdict === 'Correct')?.count || 0;
  return <div className="flex flex-col gap-5 pt-1">
    <div className="flex items-end justify-between gap-4"><div className="flex items-baseline gap-2"><span className="text-3xl font-semibold tracking-tight tabular-nums text-ink-primary">{(correct / total * 100).toFixed(1)}<span className="ml-0.5 text-lg text-ink-muted">%</span></span><span className="text-body-sm text-ink-muted">reported correct</span></div><span className="text-metadata tabular-nums text-ink-muted">{total.toLocaleString()} submissions</span></div>
    <div>
      <div role="img" aria-label={data.map((item) => `${item.verdict}: ${item.count} of ${total}`).join('; ')} className="flex h-2.5 w-full overflow-hidden rounded-full bg-state-gray-soft">
        {data.filter((item) => item.count > 0).map((item) => <span key={item.verdict} className="h-full border-r-2 border-surface last:border-0" style={{ width: `${item.count / total * 100}%`, backgroundColor: verdictColor(item.verdict) }} />)}
      </div>
    </div>
    <div className="grid gap-x-6 gap-y-3 sm:grid-cols-2">
      {data.map((item) => <div key={item.verdict} className="flex items-center gap-2 border-b border-surface-border pb-2 text-label-sm">
        <span className="h-2 w-2 shrink-0 rounded-sm" style={{ backgroundColor: verdictColor(item.verdict) }} /><span className="flex-1 text-ink-secondary">{item.verdict}</span>
        <span className="font-semibold tabular-nums text-ink-primary">{item.count.toLocaleString()}</span><span className="w-12 text-right text-metadata tabular-nums text-ink-muted">{(item.count / total * 100).toFixed(1)}%</span>
      </div>)}
    </div>
  </div>;
}

function WorkflowProgression({ data }: { data: OverviewMetrics['state_breakdown'] }) {
  if (!data.length) return <ChartEmpty text="No feedback has entered the workflow yet." />;
  const counts = new Map(data.map(({ state, count }) => [state, count]));
  const otherStates = data.filter(({ state }) => !workflowStages.includes(state));

  const total = data.reduce((sum, item) => sum + item.count, 0);
  return <div className="space-y-3">
    <ol className="space-y-2.5">
      {workflowStages.map((stage) => {
        const count = counts.get(stage) || 0;
        return <li key={stage} className="space-y-1.5">
          <div className="flex items-center justify-between gap-2 text-label-sm">
            <span className={count ? 'text-ink-secondary' : 'text-ink-muted'}>{stage}</span>
            <span className={`tabular-nums ${count ? 'font-semibold text-ink-primary' : 'text-ink-muted'}`}>{count.toLocaleString()}</span>
          </div>
          <div aria-hidden="true" className="h-0.5 overflow-hidden rounded-full bg-state-gray-soft"><div className="h-full rounded-full bg-chart-primary" style={{ width: `${total ? count / total * 100 : 0}%`, backgroundColor: 'var(--chart-primary)' }} /></div>
        </li>;
      })}
    </ol>
    {otherStates.length > 0 && <p className="border-t border-surface-border pt-2 font-metadata text-ink-muted">
      Other outcomes: {otherStates.map(({ state, count }) => `${formatRcaLabel(state)} ${count}`).join(' · ')}
    </p>}
  </div>;
}

function RootCauseChart({ data }: { data: OverviewMetrics['root_cause_breakdown'] }) {
  if (!data.length) return <ChartEmpty title="No classifications yet" text="Run a document-backed RCA from the feedback inbox." />;
  const total = data.reduce((sum, item) => sum + item.count, 0);
  const chartData = [...data].sort((a, b) => b.count - a.count).slice(0, 5);
  return <div className="space-y-3">{chartData.map((item) => <div key={item.category}>
    <div className="mb-1.5 flex items-center justify-between gap-3 text-label-sm"><span className="text-ink-secondary">{formatRcaLabel(item.category)}</span><span className="font-semibold tabular-nums text-ink-primary">{item.count}</span></div>
    <div aria-hidden="true" className="h-1 overflow-hidden rounded-full bg-state-gray-soft"><div className="h-full rounded-full" style={{ width: `${total ? item.count / total * 100 : 0}%`, backgroundColor: 'var(--chart-primary)' }} /></div>
    <p className="mt-1 text-metadata text-ink-muted">{item.auto_count} auto-classified · {item.review_count} review recommended</p>
  </div>)}{data.length > 5 && <p className="text-metadata text-ink-muted">Top 5 of {data.length} categories · all classifications are in the inbox.</p>}</div>;
}

function EvaluationTrendChart({ data, latestId, latestPassRate }: {
  data: OverviewMetrics['evaluation_trend'];
  latestId?: string | null;
  latestPassRate?: number | null;
}) {
  if (!data.length) return <ChartEmpty title="No completed runs" text="Approve golden cases before running an evaluation." />;
  return <div>
    <div className="mb-3 flex items-end justify-between gap-3 rounded-lg bg-canvas px-3 py-2">
      <div className="min-w-0">
        <span className="block font-metadata uppercase tracking-wide text-ink-muted">Latest completed run</span>
        <span className="mt-1 block truncate font-code-xs text-ink-secondary">{latestId || 'Run reference not recorded'}</span>
      </div>
      <span className="shrink-0 font-headline-md tabular-nums text-ink-primary">{latestPassRate == null ? '—' : `${latestPassRate.toFixed(1)}%`}</span>
    </div>
    <EvaluationLine data={data} />
  </div>;
}

function EvaluationLine({ data }: { data: OverviewMetrics['evaluation_trend'] }) {
  return <ResponsiveContainer width="100%" height={170}>
    <LineChart data={data} margin={{ top: 10, right: 16, left: -14, bottom: 0 }}>
      <CartesianGrid vertical={false} stroke="var(--color-surface-border)" strokeDasharray="4 5" />
      <XAxis dataKey="completed_at" tickFormatter={formatShortDate} tickLine={false} axisLine={false} minTickGap={24} tick={{ fill: 'var(--color-ink-muted)', fontSize: 12 }} />
      <YAxis domain={[0, 100]} tickFormatter={(value) => `${value}%`} tickLine={false} axisLine={false} width={46} tick={{ fill: 'var(--color-ink-muted)', fontSize: 12 }} />
      <Tooltip labelFormatter={(label) => formatShortDate(String(label))} formatter={(value) => [`${Number(value).toFixed(1)}%`, 'Pass rate']} contentStyle={tooltipStyle} />
      <Line type="monotone" dataKey="pass_rate" name="Pass rate" stroke="var(--chart-primary)" strokeWidth={2} activeDot={{ r: 4 }} dot={{ r: 3, fill: 'var(--color-surface)', strokeWidth: 2 }} />
    </LineChart>
  </ResponsiveContainer>;
}

function ChartEmpty({ title, text }: { title?: string; text: string }) {
  return <div className="dashboard-empty flex items-start gap-3 py-2"><CircleDashed size={18} aria-hidden="true" className="mt-0.5 shrink-0 text-ink-muted" /><div>{title && <p className="text-label-sm font-medium text-ink-secondary">{title}</p>}<p className={`${title ? 'mt-1' : ''} text-body-sm text-ink-muted`}>{text}</p></div></div>;
}

function formatShortDate(value: string): string {
  const date = new Date(value.length === 10 ? `${value}T12:00:00` : value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function verdictColor(verdict: string): string {
  if (verdict === 'Incorrect' || verdict === 'Unsafe or misleading') return 'var(--chart-danger)';
  if (verdict === 'Partially correct') return 'var(--chart-warning)';
  if (verdict === 'Correct') return 'var(--chart-primary)';
  return 'var(--chart-neutral)';
}
