import React, { useState } from 'react';
import { AnimatePresence } from 'motion/react';
import { Check, Pencil, Play, Plus, RefreshCw, Server, X } from 'lucide-react';
import { AgentEnvironmentConfig, EnvironmentInput, saveAgentEnvironment } from '../api/feedbackApi';
import { CollapsibleSection } from './CollapsibleSection';
import { EndpointTestDialog } from './EndpointTestDialog';
import { Notice } from './Notice';
import { ActionButton } from './ActionButton';
import { useUnsavedDemoDraft } from '../utils/unsavedDemoDrafts';

export function EnvironmentSettingsView({ environments, loading, onRefresh, embedded = false }: { environments: AgentEnvironmentConfig[]; loading: boolean; onRefresh: () => Promise<void>; embedded?: boolean }) {
  const [editing, setEditing] = useState<AgentEnvironmentConfig | 'new' | null>(null);
  const [testing, setTesting] = useState<AgentEnvironmentConfig | null>(null);
  const [saved, setSaved] = useState(false);
  return <div className="space-y-5">
    <header className="flex flex-wrap items-start justify-between gap-3"><div>{embedded ? <h2 className="font-title-lg">Environments</h2> : <h1 className="font-headline-lg">Settings</h1>}<p className="mt-1 text-body-sm text-ink-secondary">Manage NEO environments and response endpoints.</p></div>
      <div className="flex gap-2"><ActionButton label="Refresh environments" icon={<RefreshCw />} onClick={() => void onRefresh()} disabled={loading} loading={loading} /><button type="button" onClick={() => { setEditing('new'); setSaved(false); }} className="inline-flex items-center gap-2 rounded-lg bg-primary-container px-3 py-2 text-label-sm font-semibold text-on-primary"><Plus size={16} />Create environment</button></div>
    </header>
    {saved && <p role="status" className="rounded-lg border border-surface-border bg-surface p-3 text-body-sm text-ink-secondary"><Check size={16} className="mr-2 inline" />Environment saved. No agent was called. Use Test endpoint for one deliberate response check.</p>}
    <div className="grid items-start gap-5 xl:grid-cols-2">
      <section className="overflow-hidden rounded-xl border border-surface-border bg-surface">
        <div className="flex items-center gap-3 border-b border-surface-border p-4"><Server size={18} className="text-ink-muted" /><div><h2 className="font-title-md">NEO environments</h2><p className="text-metadata text-ink-muted">One agent · separate endpoints and result histories</p></div></div>
        {!environments.length ? <p className="p-5 text-body-sm text-ink-muted">{loading ? 'Loading environments…' : 'No environments are available yet.'}</p> : <ul className="divide-y divide-surface-border">{environments.map((environment) => <EnvironmentCard key={environment.id} environment={environment} onEdit={() => { setEditing(environment); setSaved(false); }} onTest={() => setTesting(environment)} />)}</ul>}
      </section>
      {editing ? <EnvironmentForm key={editing === 'new' ? 'new' : editing.id} environment={editing === 'new' ? undefined : editing} onCancel={() => setEditing(null)} onSaved={async () => { await onRefresh(); setEditing(null); setSaved(true); }} /> : <section className="rounded-xl border border-dashed border-surface-border p-6 text-body-sm text-ink-secondary">
        <h2 className="font-title-md text-ink-primary">Configure first, test explicitly</h2><p className="mt-2">Create or edit a saved connection, then use Test endpoint to send one sample question. Saving does not deploy an agent, grant access or generate answers.</p><p className="mt-3">You can test a saved endpoint while its environment is disabled. Each test uses the backend's runtime credentials.</p><p className="mt-3">Promote & retest in the feedback inbox runs selected feedback questions. Connection tests do not create feedback or run RCA. New-agent creation is not part of this release.</p>
      </section>}
    </div>
    <AnimatePresence>{testing && <EndpointTestDialog key={`${testing.id}:${testing.revision}`} environment={testing} onClose={() => setTesting(null)} onChanged={onRefresh} />}</AnimatePresence>
  </div>;
}

function EnvironmentCard({ environment, onEdit, onTest }: { environment: AgentEnvironmentConfig; onEdit: () => void; onTest: () => void }) {
  const kindLabel = environment.kind === 'prod' ? 'Production' : 'Non-production';
  const last = environment.lastTest;
  const canTest = environment.canTest ?? (environment.canRetest && environment.configured);
  return <li className="p-4">
    <div className="flex flex-wrap items-start justify-between gap-3"><div className="min-w-0"><h3 className="text-label-md font-semibold">{environment.name}{environment.name.toLowerCase() !== kindLabel.toLowerCase() && <span className="ml-2 font-normal text-ink-muted">{kindLabel}</span>}</h3><p className="mt-1 text-metadata text-ink-muted">{!environment.enabled ? 'Disabled' : environment.configured ? 'Configured' : 'Endpoint not configured'} · configuration r{environment.revision}</p></div>
      <div className="flex flex-wrap gap-2"><ActionButton label="Test endpoint" compactLabel="Test" icon={<Play />} size="sm" disabled={!canTest} title={!canTest ? environment.testReason || 'Save an endpoint URL before testing' : 'Send one explicit response request using the saved configuration'} onClick={onTest} aria-label={`Test ${environment.name} endpoint`} /><ActionButton label="Edit" icon={<Pencil />} size="sm" disabled={!environment.canManage} title={environment.canManage ? 'Edit saved configuration' : environment.manageReason || 'Reviewer access is required'} onClick={onEdit} aria-label={`Edit ${environment.name} environment`} /></div>
    </div>
    {environment.url && <p className="mt-3 break-all rounded-md bg-canvas p-2 font-code-xs text-ink-secondary">{environment.url}</p>}
    {!canTest && environment.testReason && <p className="mt-2 text-metadata text-ink-muted">{environment.testReason}</p>}
    {!environment.canManage && environment.manageReason && <p className="mt-2 text-metadata text-ink-muted">{environment.manageReason}</p>}
    {last ? <div className="mt-3 rounded-lg border border-surface-border bg-canvas p-3" aria-label={`Last endpoint test for ${environment.name}`}><p className={`text-label-sm font-medium ${last.status === 'failed' ? 'text-issue-red' : last.status === 'succeeded' ? 'text-evidence-teal' : 'text-ink-secondary'}`}>Last test: {last.status === 'succeeded' ? 'completed response received' : last.status === 'failed' ? 'failed' : last.status === 'running' ? 'running' : 'outcome unknown'}{last.httpStatus != null ? ` · HTTP ${last.httpStatus}` : ''}{last.elapsedMs != null ? ` · ${(last.elapsedMs / 1000).toFixed(2)}s` : ''}</p>{last.error && <p className="mt-1 text-body-sm text-issue-red">{last.error}</p>}<p className="mt-1 text-metadata text-ink-muted">Configuration r{last.configurationRevision} · {last.completedAt || last.createdAt}</p></div> : environment.configured && <p className="mt-2 text-metadata text-ink-muted">No endpoint test saved for this configuration in this runtime.</p>}
  </li>;
}

function EnvironmentForm({ environment, onCancel, onSaved }: { environment?: AgentEnvironmentConfig; onCancel: () => void; onSaved: () => Promise<void> }) {
  const [draft, setDraft] = useState<EnvironmentInput>({ name: environment?.name || '', kind: environment?.kind || 'nonprod', url: environment?.url || '', protocol: (environment?.configured ? environment.protocol : undefined) || 'neo_companion', auth: (environment?.configured ? environment.auth : undefined) || 'google_access_token', timeout_seconds: environment?.timeoutSeconds || 300, enabled: environment?.enabled ?? true, agent_version: environment?.agentVersion || '', expected_revision: environment?.revision });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [initialDraft] = useState(() => JSON.stringify(draft));
  useUnsavedDemoDraft(JSON.stringify(draft) !== initialDraft);
  const field = 'mt-1.5 w-full rounded-lg border border-surface-border bg-canvas px-3 py-2.5 text-body-sm font-normal text-ink-primary outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:opacity-60';
  const submit = async (event: React.FormEvent) => {
    event.preventDefault(); if (saving) return; setSaving(true); setError(null);
    try { await saveAgentEnvironment(draft, environment?.id); await onSaved(); }
    catch (error) { setError(error instanceof Error ? error.message : 'Could not save the environment'); }
    finally { setSaving(false); }
  };
  return <form onSubmit={(event) => void submit(event)} className="space-y-4 rounded-xl border border-surface-border bg-surface p-4 sm:p-5" aria-label={environment ? 'Edit environment' : 'Create environment'}>
    <div className="flex items-center justify-between gap-3"><h2 className="font-title-md">{environment ? `Edit ${environment.name}` : 'Create NEO environment'}</h2><button type="button" disabled={saving} onClick={onCancel} aria-label="Close environment editor" className="rounded-lg p-2 text-ink-muted hover:bg-canvas"><X size={16} /></button></div>
    {error && <Notice title="Environment wasn't saved" message={error} onDismiss={() => setError(null)} />}
    <fieldset disabled={saving} className="space-y-4">
      <label className="block text-label-sm font-medium">Environment name<input aria-label="Environment name" required maxLength={60} value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} placeholder="e.g. DEV, UAT or Staging" className={field} /></label>
      <label className="block text-label-sm font-medium">Environment type<select aria-label="Environment type" disabled={Boolean(environment)} value={draft.kind} onChange={(event) => setDraft({ ...draft, kind: event.target.value as EnvironmentInput['kind'] })} className={field}><option value="nonprod">Non-production</option><option value="prod">Production</option></select></label>
      <label className="block text-label-sm font-medium">Agent response endpoint<input aria-label="Agent response endpoint" type="url" required={draft.enabled} value={draft.url} onChange={(event) => setDraft({ ...draft, url: event.target.value })} placeholder="https://api.loreal.net/…/contexts/…/configs/default/generations" className={field} /><span className="mt-1.5 block text-metadata font-normal text-ink-muted">Approved HTTPS invocation endpoints only—not web-chat pages. Test endpoint uses the saved configuration, not unsaved form changes.</span></label>
      <label className="inline-flex items-center gap-2 text-label-sm"><input type="checkbox" checked={draft.enabled} onChange={(event) => setDraft({ ...draft, enabled: event.target.checked })} />Enable this environment for retests</label>
      <CollapsibleSection title="Advanced connection settings" summary="Runtime authentication, response format and timeout"><div className="space-y-3">
        <label className="block text-label-sm">Response format<select aria-label="Environment response format" value={draft.protocol} onChange={(event) => setDraft({ ...draft, protocol: event.target.value as EnvironmentInput['protocol'] })} className={field}><option value="neo_companion">NEO Companion generations</option><option value="quality_json">Quality JSON API</option></select></label>
        <label className="block text-label-sm">Authentication<select aria-label="Environment authentication" value={draft.auth} onChange={(event) => setDraft({ ...draft, auth: event.target.value as EnvironmentInput['auth'] })} className={field}><option value="google_access_token">Runtime Google OAuth</option><option value="google_id_token">Runtime Google ID token</option><option value="none">No authentication · approved endpoints only</option></select></label>
        <p className="text-metadata text-ink-muted">Credentials stay server-side. Never paste personal tokens, passwords or credentials into URLs.</p>
        <label className="block text-label-sm">Request timeout (seconds)<input aria-label="Environment timeout" type="number" min={1} max={600} required value={draft.timeout_seconds} onChange={(event) => setDraft({ ...draft, timeout_seconds: Number(event.target.value) })} className={field} /></label>
        <label className="block text-label-sm">Agent / release version<input aria-label="Environment agent version" maxLength={200} value={draft.agent_version || ''} onChange={(event) => setDraft({ ...draft, agent_version: event.target.value })} className={field} /></label>
      </div></CollapsibleSection>
    </fieldset>
    <div className="flex justify-end gap-2 border-t border-surface-border pt-4"><button type="button" disabled={saving} onClick={onCancel} className="rounded-lg border border-surface-border px-3 py-2 text-label-sm text-ink-secondary">Cancel</button><button type="submit" disabled={saving} className="rounded-lg bg-primary-container px-4 py-2 text-label-sm font-semibold text-on-primary disabled:opacity-50">{saving ? 'Saving…' : 'Save environment'}</button></div>
  </form>;
}
