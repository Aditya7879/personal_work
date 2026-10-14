import React, { useState } from 'react';
import { EvaluationCaseResultRecord, EvaluationRunRecord, GoldenDatasetRecord } from '../api/feedbackApi';

interface Props {
  datasets: GoldenDatasetRecord[];
  runs: EvaluationRunRecord[];
  loading: boolean;
  onRefresh: () => void;
  selectedRunId: string | null;
  caseResults: EvaluationCaseResultRecord[];
  onSelectRun: (id: string) => void;
  onCreateRun: (input: { dataset_id: string; dataset_version?: string; label?: string; mode: 'full' | 'reviewed_cases' }) => Promise<void>;
}

export const EvaluationRunsView: React.FC<Props> = ({ datasets, runs, loading, onRefresh, selectedRunId, caseResults, onSelectRun, onCreateRun }) => {
  const [open, setOpen] = useState(false);
  const [datasetId, setDatasetId] = useState('');
  const [label, setLabel] = useState('');
  const mode = 'full' as const;
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!datasetId) return;
    setSaving(true); setError(null);
    try {
      const dataset = datasets.find((item) => item.dataset_id === datasetId);
      await onCreateRun({ dataset_id: datasetId, dataset_version: dataset?.current_version, label, mode });
      setOpen(false); setLabel('');
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : 'Could not start evaluation');
    } finally { setSaving(false); }
  };

  return (
    <div className="flex flex-col gap-space-lg">
      <header className="flex flex-wrap items-end justify-between gap-space-md">
        <div>
          <div className="font-metadata uppercase tracking-wider text-ink-muted">Continuous testing</div>
          <h1 className="mt-1 font-headline-lg text-ink-primary">Evaluation runs</h1>
          <p className="mt-1 font-body-md text-ink-secondary">Run approved golden cases against the configured NEO Rules Agent and inspect case-level outcomes.</p>
        </div>
        <div className="flex gap-2">
          <button onClick={onRefresh} className="rounded-lg border border-surface-border bg-surface px-3 py-2 text-label-md text-ink-primary" type="button">Refresh</button>
          <button onClick={() => setOpen(true)} disabled={!datasets.length} className="rounded-lg bg-primary-container px-3 py-2 text-label-md font-semibold text-on-primary disabled:opacity-50" type="button">Run evaluation</button>
        </div>
      </header>
      {error && <div className="rounded-lg border border-issue-red/30 bg-issue-soft px-3 py-2 text-body-sm text-issue-red">{error}</div>}
      <section className="overflow-hidden rounded-xl border border-surface-border bg-surface shadow-sm">
        <div className="border-b border-surface-border p-space-md"><h2 className="font-title-md text-ink-primary">Evaluation history</h2></div>
        {loading && <p className="p-space-lg text-body-sm text-ink-muted">Loading evaluation runs…</p>}
        {!loading && runs.length === 0 && <div className="p-space-xl text-center"><p className="font-title-md text-ink-primary">No evaluation runs yet</p><p className="mt-1 text-body-sm text-ink-muted">Create a dataset and approve cases before starting an evaluation.</p></div>}
        {runs.length > 0 && <div className="overflow-x-auto"><table className="w-full text-left"><thead className="bg-state-gray-soft/60 font-metadata uppercase text-ink-muted"><tr><th className="p-3">Run</th><th className="p-3">Dataset</th><th className="p-3">Status</th><th className="p-3">Cases</th><th className="p-3">Pass rate</th><th className="p-3">Started</th></tr></thead><tbody className="divide-y divide-surface-border">{runs.map((run) => <tr key={run.id} onClick={() => onSelectRun(run.id)} className={`cursor-pointer hover:bg-canvas ${selectedRunId === run.id ? 'bg-indigo-soft/40' : ''}`}><td className="p-3"><span className="font-code-xs text-primary">{run.id}</span>{run.label && <span className="ml-2 text-body-sm text-ink-primary">{run.label}</span>}</td><td className="p-3 text-body-sm text-ink-primary">{run.dataset_name} <span className="text-ink-muted">v{run.dataset_version}</span></td><td className="p-3"><span className="rounded bg-state-gray-soft px-2 py-1 font-metadata text-ink-secondary">{run.status}</span>{run.error && <p className="mt-1 max-w-sm text-metadata text-issue-red">{run.error}</p>}</td><td className="p-3 font-code-xs text-ink-secondary">{run.passed_cases}/{run.total_cases} passed · {run.failed_cases} failed · {run.review_required_cases} review</td><td className="p-3 font-code-sm text-ink-primary">{run.pass_rate == null ? '—' : `${run.pass_rate.toFixed(1)}%`}</td><td className="p-3 font-metadata text-ink-muted">{run.started_at || '—'}</td></tr>)}</tbody></table></div>}
      </section>
      {selectedRunId && <section className="overflow-hidden rounded-xl border border-surface-border bg-surface shadow-sm"><div className="border-b border-surface-border p-space-md"><h2 className="font-title-md text-ink-primary">Case results · {selectedRunId}</h2></div>{caseResults.length === 0 ? <p className="p-space-md text-body-sm text-ink-muted">No case results are available yet. The run may still be queued or have no approved cases.</p> : <div className="divide-y divide-surface-border">{caseResults.map((item) => <article key={item.case_id} className="p-space-md"><div className="flex flex-wrap items-center justify-between gap-2"><span className="font-code-xs text-primary">{item.case_id}</span><span className={`rounded px-2 py-1 font-metadata ${item.result === 'passed' ? 'bg-evidence-soft text-evidence-teal' : item.result === 'failed' ? 'bg-issue-soft text-issue-red' : 'bg-review-soft text-review-amber'}`}>{item.result}</span><span className="font-metadata text-ink-muted">Agent status: {item.actual_status || '—'}</span></div><p className="mt-2 whitespace-pre-wrap text-body-sm text-ink-secondary">{item.actual_answer || 'No answer captured'}</p>{item.missing_claims.length > 0 && <p className="mt-2 text-body-sm text-review-amber">Review: {item.missing_claims.join(' · ')}</p>}</article>)}</div>}</section>}
      <p className="text-metadata text-ink-muted">Starter evaluator checks expected status and required-claim text matches. Treat results as review aids, not semantic approval.</p>
      {open && <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-primary/40 p-4"><form onSubmit={(event) => void submit(event)} className="w-full max-w-lg rounded-xl border border-surface-border bg-surface p-space-lg shadow-2xl"><div className="mb-4 flex justify-between"><h2 className="font-headline-sm text-ink-primary">Start evaluation</h2><button type="button" onClick={() => setOpen(false)} className="text-ink-muted">Close</button></div><label className="mb-3 block text-label-sm text-ink-secondary">Golden dataset<select required value={datasetId} onChange={(event) => setDatasetId(event.target.value)} className="mt-1 w-full rounded-lg border border-surface-border p-2 text-body-sm text-ink-primary"><option value="">Choose dataset</option>{datasets.map((dataset) => <option key={dataset.dataset_id} value={dataset.dataset_id}>{dataset.name} · v{dataset.current_version}</option>)}</select></label><label className="mb-3 block text-label-sm text-ink-secondary">Run label<input value={label} onChange={(event) => setLabel(event.target.value)} placeholder="e.g. pre-release check" className="mt-1 w-full rounded-lg border border-surface-border p-2 text-body-sm text-ink-primary" /></label><div className="mb-5 rounded-lg bg-canvas p-3 text-body-sm text-ink-secondary">All approved cases in the selected dataset version will run. Candidates are excluded.</div>{error && <p className="mb-3 text-body-sm text-issue-red">{error}</p>}<div className="flex justify-end"><button disabled={saving || !datasetId} className="rounded-lg bg-primary-container px-4 py-2 text-label-md font-semibold text-on-primary disabled:opacity-50">{saving ? 'Queueing…' : 'Start evaluation'}</button></div></form></div>}
    </div>
  );
};
