import React from 'react';
import { FeedbackItem } from '../types';
import { AnswerMarkdown } from './AnswerMarkdown';
import { ContentPreview } from './ContentPreview';
import { ChevronDown } from 'lucide-react';
import { UserVerdictBadge } from './UserVerdictBadge';

const importedLabels: Record<string, string> = {
  data_source: 'Data source', sub_domain: 'Submitted subdomain', status: 'Imported status',
  answer_status: 'Original answer status', latency_seconds: 'Latency (seconds)', follow_up: 'Follow-up',
  developer_remarks: 'Developer remarks · reviewer only', resolution: 'Historical resolution',
  status_note: 'Imported status note', language: 'Language',
};

function formatSubmittedAt(value: string): string {
  if (!value) return 'Not recorded';
  const date = new Date(value.replace(' ', 'T'));
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

export const SubmissionContextCard: React.FC<{ item: FeedbackItem }> = ({ item }) => {
  const imported = ['legacy_csv_import', 'legacy_xlsx_import'].includes(String(item.runContext?.source || ''));
  return (
  <section className="workspace-panel min-w-0 rounded-xl border border-surface-border bg-surface p-4" aria-labelledby={`submission-context-${item.id}`}>
    <div className="mb-4 flex flex-wrap items-center justify-between gap-2"><h2 id={`submission-context-${item.id}`} className="font-title-md text-ink-primary">Submission</h2><div className="flex flex-wrap items-center gap-2"><UserVerdictBadge value={item.userVerdict} /><span className="text-metadata text-ink-muted">{item.impact} impact</span></div></div>
    <div className="space-y-4">
      <div><h3 className="mb-1.5 text-label-sm font-medium text-ink-secondary">Question</h3><ContentPreview key={`${item.id}-${item.revision}-question`} label="Submitted question" compact><p className="whitespace-pre-wrap text-ink-primary">{item.prompt || 'No question was captured.'}</p></ContentPreview></div>
      <div><div className="mb-1.5 flex items-center justify-between gap-2"><h3 className="text-label-sm font-medium text-ink-secondary">Agent response</h3>{item.highlightedDefect && <span className="text-metadata text-ink-muted">Defect excerpt attached</span>}</div><ContentPreview key={`${item.id}-${item.revision}-answer`} label="Submitted agent response"><AnswerMarkdown content={item.generatedAnswer || 'No answer snapshot was attached to this feedback.'} /></ContentPreview></div>
    </div>
    <details key={item.id} className="group mt-4 border-t border-surface-border">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 pt-3 text-label-sm font-medium text-ink-secondary outline-none focus-visible:ring-2 focus-visible:ring-primary [&::-webkit-details-marker]:hidden"><span>Feedback & metadata</span><ChevronDown size={15} aria-hidden="true" className="shrink-0 text-ink-muted transition-transform group-open:rotate-180" /></summary>
      <div className="mt-3 space-y-4">
        {(item.fullQuote || item.excerpt) && <div><h3 className="mb-1.5 text-label-sm font-medium text-ink-secondary">{imported && /^Imported (spreadsheet|CSV) feedback\b/i.test(item.fullQuote || item.excerpt) ? 'Import note' : 'Submitted feedback'}</h3><ContentPreview label="Submitted feedback" compact><p className="whitespace-pre-wrap">{item.fullQuote || item.excerpt}</p></ContentPreview></div>}
        <dl className="grid min-w-0 gap-x-5 gap-y-3 text-body-sm sm:grid-cols-2">
          <SubmissionField label="Reported" value={formatSubmittedAt(item.reportedTime)} />
          <SubmissionField label="Reporter" value={item.reporter || 'Not recorded'} />
          <SubmissionField label="Agent" value={item.agentName} />
          {item.model && item.model !== 'unknown' && <SubmissionField label="Model" value={item.model} />}
          {item.runId && <SubmissionField label="Run reference" value={item.runId} />}
          {item.agentVersion && <SubmissionField label="Agent version" value={item.agentVersion} />}
          {imported && Object.entries(importedLabels).map(([key, label]) => {
            const value = item.runContext?.[key];
            return value == null || value === '' ? null : <SubmissionField key={key} label={label} value={String(value)} />;
          })}
        </dl>
        {!!item.tags.length && <div><h3 className="mb-2 text-label-sm font-medium text-ink-secondary">Tags</h3><div className="flex flex-wrap gap-1.5">{item.tags.map((tag) => <span key={tag} className="rounded-md bg-state-gray-soft px-2 py-1 text-metadata text-ink-secondary">{tag.replaceAll('_', ' ')}</span>)}</div></div>}
        {!!item.correlatedReports?.length && <div><h3 className="text-label-sm font-medium text-ink-secondary">Related reports</h3><p className="mt-1 break-words text-body-sm text-ink-muted">{item.correlatedReports.join(', ')}</p></div>}
      </div>
    </details>
  </section>
  );
};

function SubmissionField({ label, value }: { label: string; value: string }) {
  return <div className="min-w-0"><dt className="text-metadata text-ink-muted">{label}</dt><dd className="mt-0.5 whitespace-pre-wrap break-words text-ink-secondary [overflow-wrap:anywhere]">{value}</dd></div>;
}
