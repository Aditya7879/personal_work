import React, { useState } from 'react';
import { GoldenCaseRecord, GoldenDatasetRecord } from '../api/feedbackApi';
import { FolderPlus } from 'lucide-react';
import { ActionButton } from './ActionButton';

interface Props {
  datasets: GoldenDatasetRecord[];
  selectedDatasetId: string | null;
  cases: GoldenCaseRecord[];
  loading: boolean;
  onSelectDataset: (id: string) => void;
  onCreateDataset: (input: { name: string; description: string }) => Promise<void>;
  onCreateVersion: (datasetId: string) => Promise<void>;
  onCreateCase: (datasetId: string, input: {
    title: string; question: string; expected_behavior: string; required_claims: string[]; expected_status?: string;
  }) => Promise<void>;
  onSetCaseState: (caseId: string, state: 'approved' | 'rejected') => Promise<void>;
}

export const GoldenDatasetsView: React.FC<Props> = ({
  datasets,
  selectedDatasetId,
  cases,
  loading,
  onSelectDataset,
  onCreateDataset,
  onCreateVersion,
  onCreateCase,
  onSetCaseState,
}) => {
  const [createDatasetOpen, setCreateDatasetOpen] = useState(false);
  const [createCaseOpen, setCreateCaseOpen] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [title, setTitle] = useState('');
  const [question, setQuestion] = useState('');
  const [expected, setExpected] = useState('');
  const [expectedStatus, setExpectedStatus] = useState('');
  const [claims, setClaims] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const selected = datasets.find((dataset) => dataset.dataset_id === selectedDatasetId);

  const submitDataset = async (event: React.FormEvent) => {
    event.preventDefault();
    setSaving(true); setError(null);
    try {
      await onCreateDataset({ name, description });
      setName(''); setDescription(''); setCreateDatasetOpen(false);
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not create dataset'); }
    finally { setSaving(false); }
  };

  const submitCase = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!selectedDatasetId) return;
    setSaving(true); setError(null);
    try {
      await onCreateCase(selectedDatasetId, {
        title,
        question,
        expected_behavior: expected,
        required_claims: claims.split('\n').map((line) => line.trim()).filter(Boolean),
        expected_status: expectedStatus || undefined,
      });
      setTitle(''); setQuestion(''); setExpected(''); setExpectedStatus(''); setClaims(''); setCreateCaseOpen(false);
    } catch (err) { setError(err instanceof Error ? err.message : 'Could not create golden candidate'); }
    finally { setSaving(false); }
  };

  return (
    <div className="flex flex-col gap-space-lg">
      <header className="flex flex-wrap items-end justify-between gap-space-md">
        <div>
          <div className="font-metadata uppercase tracking-wider text-ink-muted">Registry · reviewer-curated</div>
          <h1 className="mt-1 font-headline-lg text-ink-primary">Golden datasets</h1>
          <p className="mt-1 font-body-md text-ink-secondary">Only approved cases are included in evaluation runs. User feedback remains a candidate until a reviewer approves it.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <ActionButton label="New dataset" aria-label="Create dataset" compactLabel="New" icon={<FolderPlus />} onClick={() => setCreateDatasetOpen(true)} />
          <button onClick={() => selectedDatasetId && void onCreateVersion(selectedDatasetId).catch((err) => setError(err.message))} disabled={!selectedDatasetId || saving || !selected?.case_count} className="rounded-lg border border-surface-border bg-surface px-3 py-2 text-label-md text-ink-primary disabled:opacity-50" type="button" title={!selected?.case_count ? 'Approve at least one case first' : 'Snapshot approved cases into the next version'}>Create next version</button>
          <button onClick={() => setCreateCaseOpen(true)} disabled={!selectedDatasetId} className="rounded-lg bg-dataset-purple px-3 py-2 text-label-md font-semibold text-on-primary disabled:opacity-50" type="button">Add golden candidate</button>
        </div>
      </header>

      {error && <div className="rounded-lg border border-issue-red/30 bg-issue-soft px-3 py-2 text-body-sm text-issue-red">{error}</div>}

      <div className="grid gap-space-lg xl:grid-cols-[320px_1fr]">
        <section className="rounded-xl border border-surface-border bg-surface p-space-md shadow-sm">
          <h2 className="mb-3 font-title-md text-ink-primary">Datasets</h2>
          {loading && datasets.length === 0 && <div className="space-y-2" role="status" aria-label="Loading datasets">{Array.from({ length: 4 }, (_, index) => <div key={index} className="skeleton h-[76px] rounded-lg" />)}</div>}
          {!loading && datasets.length === 0 && <p className="rounded-lg border border-dashed border-surface-border p-4 text-body-sm text-ink-muted">No golden datasets yet. Create one to curate reviewed examples.</p>}
          <div className="flex flex-col gap-2">
            {datasets.map((dataset) => (
              <button key={dataset.dataset_id} onClick={() => onSelectDataset(dataset.dataset_id)} className={`rounded-lg border p-3 text-left transition-colors ${selectedDatasetId === dataset.dataset_id ? 'border-dataset-purple bg-dataset-soft/50' : 'border-surface-border hover:bg-state-gray-soft'}`} type="button">
                <span className="block font-label-md font-semibold text-ink-primary">{dataset.name}</span>
                <span className="mt-1 block font-metadata text-ink-muted">v{dataset.current_version} · {dataset.case_count || 0} cases</span>
                <span className="mt-1 block font-metadata text-review-amber">{dataset.pending_reviews || 0} candidates awaiting approval</span>
              </button>
            ))}
          </div>
        </section>

        <section className="overflow-hidden rounded-xl border border-surface-border bg-surface shadow-sm">
          <div className="flex items-center justify-between border-b border-surface-border p-space-md">
            <div>
              <h2 className="font-title-md text-ink-primary">{selected?.name || 'Dataset cases'}</h2>
              <p className="font-metadata text-ink-muted">{selected ? `Version ${selected.current_version}` : 'Select a dataset to view cases'}</p>
            </div>
            {selected && <span className="rounded-full bg-evidence-soft px-2 py-1 font-metadata font-semibold text-evidence-teal">Current version {selected.current_version}</span>}
          </div>
          {!selected && <p className="p-space-lg text-body-sm text-ink-muted">Create or select a dataset to get started.</p>}
          {selected && loading && cases.length === 0 && <div className="space-y-2 p-space-md" role="status" aria-label="Loading dataset cases">{Array.from({ length: 5 }, (_, index) => <div key={index} className="skeleton h-16 rounded-lg" />)}</div>}
          {selected && !loading && cases.length === 0 && <p className="m-space-md rounded-lg border border-dashed border-surface-border p-space-lg text-center text-body-sm text-ink-muted">No cases in this dataset version.</p>}
          {selected && cases.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead className="bg-state-gray-soft/60 font-metadata uppercase text-ink-muted"><tr><th className="p-3">Case</th><th className="p-3">Question</th><th className="p-3">Expected behavior</th><th className="p-3">State</th><th className="p-3 text-right">Review</th></tr></thead>
                <tbody className="divide-y divide-surface-border">
                  {cases.map((item) => <tr key={item.case_id}>
                    <td className="p-3 font-code-xs text-dataset-purple">{item.case_id}</td>
                    <td className="max-w-sm p-3 text-body-sm text-ink-primary">{item.question}</td>
                    <td className="max-w-sm p-3 text-body-sm text-ink-secondary">{item.expected_behavior}</td>
                    <td className="p-3"><span className={`rounded px-2 py-1 font-metadata ${item.state === 'approved' ? 'bg-evidence-soft text-evidence-teal' : 'bg-review-soft text-review-amber'}`}>{item.state}</span></td>
                    <td className="p-3 text-right">{item.state !== 'approved' && <button onClick={() => void onSetCaseState(item.case_id, 'approved')} className="rounded bg-evidence-soft px-2.5 py-1.5 text-label-sm font-semibold text-evidence-teal">Approve</button>}</td>
                  </tr>)}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>

      {createDatasetOpen && <Modal title="Create golden dataset" onClose={() => setCreateDatasetOpen(false)}>
        <form onSubmit={(event) => void submitDataset(event)} className="flex flex-col gap-3">
          <label className="text-label-sm text-ink-secondary">Name<input required value={name} onChange={(event) => setName(event.target.value)} className="mt-1 w-full rounded-lg border border-surface-border p-2 text-body-sm text-ink-primary" /></label>
          <label className="text-label-sm text-ink-secondary">Description<textarea value={description} onChange={(event) => setDescription(event.target.value)} rows={3} className="mt-1 w-full rounded-lg border border-surface-border p-2 text-body-sm text-ink-primary" /></label>
          <div className="flex justify-end"><button disabled={saving} className="rounded-lg bg-primary-container px-4 py-2 text-label-md font-semibold text-on-primary disabled:opacity-50">{saving ? 'Creating…' : 'Create dataset'}</button></div>
        </form>
      </Modal>}

      {createCaseOpen && <Modal title="Add golden candidate" onClose={() => setCreateCaseOpen(false)}>
        <form onSubmit={(event) => void submitCase(event)} className="flex flex-col gap-3">
          <label className="text-label-sm text-ink-secondary">Title<input required value={title} onChange={(event) => setTitle(event.target.value)} className="mt-1 w-full rounded-lg border border-surface-border p-2 text-body-sm text-ink-primary" /></label>
          <label className="text-label-sm text-ink-secondary">Question<textarea required value={question} onChange={(event) => setQuestion(event.target.value)} rows={2} className="mt-1 w-full rounded-lg border border-surface-border p-2 text-body-sm text-ink-primary" /></label>
          <label className="text-label-sm text-ink-secondary">Expected behavior<textarea required value={expected} onChange={(event) => setExpected(event.target.value)} rows={3} className="mt-1 w-full rounded-lg border border-surface-border p-2 text-body-sm text-ink-primary" /></label>
          <label className="text-label-sm text-ink-secondary">Expected agent response status<select value={expectedStatus} onChange={(event) => setExpectedStatus(event.target.value)} className="mt-1 w-full rounded-lg border border-surface-border p-2 text-body-sm text-ink-primary"><option value="">Do not assert status</option><option value="verified">verified</option><option value="partial">partial</option><option value="clarification_required">clarification_required</option><option value="insufficient_evidence">insufficient_evidence</option></select></label>
          <label className="text-label-sm text-ink-secondary">Required claims (one per line)<textarea value={claims} onChange={(event) => setClaims(event.target.value)} rows={3} className="mt-1 w-full rounded-lg border border-surface-border p-2 text-body-sm text-ink-primary" /></label>
          <p className="text-metadata text-review-amber">New cases are candidates and are excluded from evals until approved.</p>
          <div className="flex justify-end"><button disabled={saving} className="rounded-lg bg-dataset-purple px-4 py-2 text-label-md font-semibold text-on-primary disabled:opacity-50">{saving ? 'Saving…' : 'Create candidate'}</button></div>
        </form>
      </Modal>}
    </div>
  );
};

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink-primary/40 p-4"><div className="w-full max-w-xl rounded-xl border border-surface-border bg-surface p-space-lg shadow-2xl"><div className="mb-4 flex items-center justify-between"><h2 className="font-headline-sm text-ink-primary">{title}</h2><button onClick={onClose} type="button" className="text-ink-muted">Close</button></div>{children}</div></div>;
}
