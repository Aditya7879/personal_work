import React, { useEffect, useId, useRef, useState } from 'react';
import { History, Pencil, Plus, RefreshCw, ShieldCheck, Users, X } from 'lucide-react';
import { AccessGrant, AccessGrantEvent, AccessGrantInput, AccessGrantList, AuthUser, getAccessGrantHistory, listAccessGrants, saveAccessGrant } from '../api/feedbackApi';
import { useDebouncedValue } from '../utils/useDebouncedValue';
import { ActionButton } from './ActionButton';
import { Notice } from './Notice';
import { useUnsavedDemoDraft } from '../utils/unsavedDemoDrafts';

const fieldClass = 'mt-1.5 w-full rounded-lg border border-surface-border bg-canvas px-3 py-2.5 text-body-sm font-normal text-ink-primary outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:opacity-60';
const roleLabel = (role: AccessGrant['role']) => role === 'demo_admin' ? 'Demo Admin' : role === 'reviewer' ? 'Reviewer' : 'Reporter';

export function accessExpiryInput(value: string | null): string {
  if (!value) return '';
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return '';
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

function dateLabel(value: string | null): string {
  return value ? new Date(value).toLocaleString() : 'No expiry';
}

export function AccessManagementView({ currentUser, enabled }: { currentUser: AuthUser; enabled: boolean }) {
  const [data, setData] = useState<AccessGrantList | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [refresh, setRefresh] = useState(0);
  const [editing, setEditing] = useState<AccessGrant | 'new' | null>(null);
  const [saved, setSaved] = useState<AccessGrant | null>(null);
  const [historyFor, setHistoryFor] = useState<string | null>(null);
  const request = useRef(0);
  const debouncedSearch = useDebouncedValue(search);

  useEffect(() => {
    if (!enabled) return;
    const sequence = ++request.current;
    setLoading(true); setError(null);
    void listAccessGrants(debouncedSearch, page)
      .then((result) => { if (sequence === request.current) setData(result); })
      .catch((cause) => { if (sequence === request.current) setError(cause instanceof Error ? cause.message : 'Could not load application access'); })
      .finally(() => { if (sequence === request.current) setLoading(false); });
    return () => { request.current += 1; };
  }, [enabled, debouncedSearch, page, refresh]);

  if (!enabled) return <section className="space-y-3 rounded-xl border border-surface-border bg-surface p-5" aria-label="People and access">
    <h2 className="font-title-md">People &amp; access</h2><p className="text-body-sm text-ink-secondary">Access management requires your real Google reviewer identity in the hosted app. Demo profiles cannot view or change real company grants.</p>
  </section>;

  return <section className="space-y-4" aria-label="People and access">
    <header className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="font-title-lg">People &amp; access</h2><p className="mt-1 text-body-sm text-ink-secondary">Give people application access, change their role, set an expiry or revoke access.</p></div><div className="flex gap-2">
      <ActionButton label="Refresh people" icon={<RefreshCw />} loading={loading} disabled={loading} onClick={() => setRefresh((value) => value + 1)} />
      <button type="button" className="inline-flex items-center gap-2 rounded-lg bg-primary-container px-3 py-2 text-label-sm font-semibold text-on-primary" onClick={() => { setEditing('new'); setSaved(null); }}><Plus size={16} aria-hidden="true" />Add person</button>
    </div></header>
    <p className="rounded-lg border border-surface-border bg-surface p-3 text-body-sm text-ink-secondary"><ShieldCheck size={16} aria-hidden="true" className="mr-2 inline" />Google verifies identity; saved BigQuery grants control access. Changes take effect within 30 seconds. These grants do not change cloud IAM, NEO permissions or feedback ownership.</p>
    {saved && <p role="status" className="rounded-lg border border-surface-border bg-surface p-3 text-body-sm text-ink-secondary">{saved.active ? 'Access saved' : 'Access revoked'} for <strong>{saved.email}</strong>. The change is audited. No invitation email was sent.</p>}
    {error && <Notice title="People couldn't be loaded" message={error} onDismiss={() => setError(null)} actionLabel="Refresh" onAction={() => setRefresh((value) => value + 1)} />}
    <div className="grid items-start gap-5 xl:grid-cols-3">
      <div className="min-w-0 space-y-4 xl:col-span-2">
        <div className="overflow-hidden rounded-xl border border-surface-border bg-surface">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-surface-border p-4"><div className="flex items-center gap-2"><Users size={18} aria-hidden="true" className="text-ink-muted" /><span className="text-label-sm font-semibold">{data ? `${data.total} ${data.total === 1 ? 'person' : 'people'}` : 'Application access'}</span></div>
            <label className="text-label-sm">Search people<input type="search" value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} className="ml-2 rounded-lg border border-surface-border bg-canvas px-3 py-2 text-body-sm outline-none focus-visible:ring-2 focus-visible:ring-primary" placeholder="Name or email" /></label>
          </div>
          <div aria-busy={loading} className="max-h-[36rem] overflow-y-auto">
            {!data?.items.length ? <p role="status" className="p-5 text-body-sm text-ink-muted">{loading ? 'Loading people…' : error ? 'Refresh to check the saved access list.' : 'No matching access grants. Add a person to give them access.'}</p> : <ul className="divide-y divide-surface-border">{data.items.map((grant) => <li key={grant.email} className="flex flex-wrap items-start justify-between gap-3 p-4">
              <div className="min-w-0 flex-1"><p className="break-words text-label-md font-semibold">{grant.displayName || grant.email}{grant.email === currentUser.email && <span className="ml-2 text-metadata font-normal text-ink-muted">You</span>}</p>{grant.displayName && <p className="mt-0.5 break-all text-body-sm text-ink-secondary">{grant.email}</p>}
                <p className="mt-2 text-label-sm capitalize">{roleLabel(grant.role)} <span className="px-1 text-ink-muted">·</span><span className={grant.status === 'active' ? 'text-evidence-teal' : 'text-ink-muted'}>{grant.status}</span></p>
                <p className="mt-1 text-metadata text-ink-muted">{grant.expiresAt ? `Expires ${dateLabel(grant.expiresAt)}` : 'No expiry'}</p><p className="mt-1 break-words text-metadata text-ink-muted">Updated {dateLabel(grant.updatedAt)}{grant.updatedBy ? ` by ${grant.updatedBy}` : ''}</p>
                {!grant.canEdit && <p className="mt-1 text-metadata text-ink-muted">Another reviewer must change your own access.</p>}
              </div><div className="flex gap-2"><ActionButton label="History" icon={<History />} size="sm" aria-label={`View access history for ${grant.email}`} onClick={() => setHistoryFor(grant.email)} /><ActionButton label="Edit access" icon={<Pencil />} size="sm" aria-label={`Edit access for ${grant.email}`} disabled={!grant.canEdit} title={!grant.canEdit ? 'Another reviewer must change your own access' : 'Change role, expiry or active status'} onClick={() => { setEditing(grant); setSaved(null); }} /></div>
            </li>)}</ul>}
          </div>
          <div className="flex items-center justify-between border-t border-surface-border p-3 text-label-sm"><button type="button" disabled={page <= 1 || loading} onClick={() => setPage((value) => value - 1)} className="rounded-lg border border-surface-border px-3 py-2 disabled:opacity-40">Previous</button><span>Page {page}</span><button type="button" disabled={loading || !data || page * data.pageSize >= data.total} onClick={() => setPage((value) => value + 1)} className="rounded-lg border border-surface-border px-3 py-2 disabled:opacity-40">Next</button></div>
        </div>
        {historyFor && <AccessHistory key={historyFor + ':' + refresh} email={historyFor} onClose={() => setHistoryFor(null)} />}
      </div>
      {editing ? <AccessGrantForm key={editing === 'new' ? 'new' : editing.email} grant={editing === 'new' ? undefined : editing} allowedDomains={data?.allowedDomains || []} onCancel={() => setEditing(null)} onSaved={(result) => { setSaved(result); setEditing(null); setRefresh((value) => value + 1); }} /> : <aside className="space-y-3 rounded-xl border border-dashed border-surface-border p-5 text-body-sm text-ink-secondary">
        <h3 className="font-title-md text-ink-primary">Choose the least access needed</h3><p><strong className="text-ink-primary">Reporter</strong> — submit feedback and view, edit or confirm their own reports.</p><p><strong className="text-ink-primary">Reviewer</strong> — review feedback across owners, manage environments and manage application access.</p><p><strong className="text-ink-primary">Demo Admin</strong> — the same Reviewer permissions, plus switching between isolated Reporter and Reviewer demo views. It cannot confirm another employee's real feedback.</p><p>Only individual company emails are supported. Revocation keeps the access record and its audit history; it does not delete feedback or change ownership.</p><p>Share the app URL yourself. This screen does not send invitation emails or grant upstream model access.</p>
      </aside>}
    </div>
  </section>;
}

export function AccessGrantForm({ grant, allowedDomains, onCancel, onSaved }: { grant?: AccessGrant; allowedDomains: string[]; onCancel: () => void; onSaved: (grant: AccessGrant) => void }) {
  const id = useId();
  const [email, setEmail] = useState(grant?.email || '');
  const [name, setName] = useState(grant?.displayName || '');
  const [role, setRole] = useState<AccessGrant['role']>(grant?.role || 'reporter');
  const [active, setActive] = useState(grant?.active ?? true);
  const [expiry, setExpiry] = useState(accessExpiryInput(grant?.expiresAt || null));
  const [pending, setPending] = useState<AccessGrantInput | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useUnsavedDemoDraft(Boolean(pending) || email !== (grant?.email || '') || name !== (grant?.displayName || '') || role !== (grant?.role || 'reporter') || active !== (grant?.active ?? true) || expiry !== accessExpiryInput(grant?.expiresAt || null));

  const review = (event: React.FormEvent) => {
    event.preventDefault(); setError(null);
    try {
      const expiresAt = grant?.expiresAt && expiry === accessExpiryInput(grant.expiresAt) ? grant.expiresAt : expiry ? new Date(expiry).toISOString() : null;
      if (active && expiresAt && new Date(expiresAt).getTime() <= Date.now()) throw new Error('Choose a future expiry for active access, or clear the expiry.');
      setPending({ ...(grant ? { expected_updated_at: grant.updatedAt } : { email: email.trim().toLowerCase() }),
        display_name: name.trim(), role, active, expires_at: expiresAt });
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Check the expiry date.'); }
  };
  const save = async () => {
    if (!pending || saving) return;
    setSaving(true); setError(null);
    try { onSaved(await saveAccessGrant(pending, grant?.email)); }
    catch (cause) { setPending(null); setError(`${cause instanceof Error ? cause.message : 'Access could not be saved.'} Your draft is still here. Refresh the list and check the saved state before trying again.`); }
    finally { setSaving(false); }
  };

  return <form onSubmit={review} aria-labelledby={`${id}-title`} className="space-y-4 rounded-xl border border-surface-border bg-surface p-4 sm:p-5">
    <div className="flex items-start justify-between gap-2"><h3 id={`${id}-title`} className="font-title-md">{grant ? 'Edit application access' : 'Add person'}</h3><button type="button" disabled={saving} onClick={onCancel} aria-label="Close access editor" className="rounded-lg p-2 text-ink-muted hover:bg-canvas focus-visible:ring-2 focus-visible:ring-primary"><X size={16} aria-hidden="true" /></button></div>
    {error && <Notice title="Access wasn't saved" message={error} onDismiss={() => setError(null)} />}
    <fieldset disabled={saving || Boolean(pending)} className="space-y-4">
      <div><label className="block text-label-sm font-medium" htmlFor={`${id}-email`}>Company email</label><input id={`${id}-email`} aria-describedby={allowedDomains.length ? `${id}-email-hint` : undefined} type="email" required maxLength={320} disabled={Boolean(grant)} value={email} onChange={(event) => setEmail(event.target.value)} className={fieldClass} autoComplete="off" />{allowedDomains.length > 0 && <p id={`${id}-email-hint`} className="mt-1 text-metadata text-ink-muted">Approved {allowedDomains.length === 1 ? 'domain' : 'domains'}: {allowedDomains.join(', ')}</p>}</div>
      <label className="block text-label-sm font-medium" htmlFor={`${id}-name`}>Display name <span className="font-normal text-ink-muted">(optional)</span><input id={`${id}-name`} maxLength={200} value={name} onChange={(event) => setName(event.target.value)} className={fieldClass} /></label>
      <label className="block text-label-sm font-medium" htmlFor={`${id}-role`}>Application role<select id={`${id}-role`} value={role} onChange={(event) => setRole(event.target.value as AccessGrant['role'])} className={fieldClass}><option value="reporter">Reporter</option><option value="reviewer">Reviewer</option><option value="demo_admin">Demo Admin</option></select></label>
      <p className="text-metadata text-ink-muted">{role === 'demo_admin' ? 'Demo Admins retain Reviewer permissions and can switch isolated demo views after IAP sign-in. This grants no employee impersonation, cloud IAM or extra upstream access.' : role === 'reviewer' ? 'Reviewers can see all feedback and manage environments and people. Only grant this when needed.' : 'Reporters can access only their own feedback and shared results.'}</p>
      <div><label className="block text-label-sm font-medium" htmlFor={`${id}-expiry`}>Access expires <span className="font-normal text-ink-muted">(optional)</span></label><input id={`${id}-expiry`} aria-describedby={`${id}-expiry-hint`} type="datetime-local" value={expiry} onChange={(event) => setExpiry(event.target.value)} className={fieldClass} /><p id={`${id}-expiry-hint`} className="mt-1 text-metadata text-ink-muted">Your local timezone. Leave blank for no expiry.</p></div>
      <label className="inline-flex items-center gap-2 text-label-sm"><input type="checkbox" checked={active} onChange={(event) => setActive(event.target.checked)} />Access active</label>
      {!active && <p className="text-body-sm text-ink-secondary">Saving will revoke application access. The person's feedback and access history are retained.</p>}
    </fieldset>
    {pending ? <div role="region" aria-label="Confirm access change" className="space-y-3 rounded-lg border border-surface-border bg-canvas p-3">
      <p className="text-label-sm font-semibold">Confirm {pending.active ? grant ? 'access change' : 'access grant' : 'access revocation'}</p><p className="break-all text-body-sm">{email.trim().toLowerCase()}</p><p className="text-body-sm capitalize">{pending.active ? roleLabel(pending.role) : 'Revoked'} · {pending.expires_at ? dateLabel(pending.expires_at) : 'No expiry'}</p>
      <div className="flex flex-wrap justify-end gap-2"><button type="button" disabled={saving} onClick={() => setPending(null)} className="rounded-lg border border-surface-border px-3 py-2 text-label-sm">Back to edit</button><button type="button" disabled={saving} onClick={() => void save()} className="rounded-lg bg-primary-container px-3 py-2 text-label-sm font-semibold text-on-primary disabled:opacity-50">{saving ? 'Saving…' : !pending.active ? 'Revoke access' : grant ? 'Save access change' : 'Grant access'}</button></div>
    </div> : <div className="flex justify-end gap-2 border-t border-surface-border pt-4"><button type="button" onClick={onCancel} className="rounded-lg border border-surface-border px-3 py-2 text-label-sm">Cancel</button><button type="submit" className="rounded-lg bg-primary-container px-3 py-2 text-label-sm font-semibold text-on-primary">Review access change</button></div>}
  </form>;
}

function AccessHistory({ email, onClose }: { email: string; onClose: () => void }) {
  const [events, setEvents] = useState<AccessGrantEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    void getAccessGrantHistory(email).then((rows) => { if (!cancelled) setEvents(rows); }).catch((cause) => { if (!cancelled) setError(cause instanceof Error ? cause.message : 'Could not load history'); });
    return () => { cancelled = true; };
  }, [email]);
  return <section className="rounded-xl border border-surface-border bg-surface p-4" aria-label={`Access history for ${email}`}><div className="mb-3 flex items-start justify-between gap-3"><div><h3 className="font-title-md">Access history</h3><p className="mt-1 break-all text-body-sm text-ink-secondary">{email}</p></div><button type="button" aria-label="Close access history" onClick={onClose} className="rounded-lg p-2 text-ink-muted focus-visible:ring-2 focus-visible:ring-primary"><X size={16} /></button></div>
    {error ? <p role="alert" className="text-body-sm text-ink-secondary">{error}</p> : !events ? <p role="status" className="text-body-sm text-ink-muted">Loading access history…</p> : !events.length ? <p className="text-body-sm text-ink-muted">No changes recorded through this screen yet. Earlier migration timestamps remain on the access record.</p> : <ol className="max-h-64 space-y-3 overflow-y-auto" tabIndex={0} aria-label="Recent access changes">{events.map((event) => <li key={event.id} className="rounded-lg border border-surface-border p-3 text-body-sm"><p className="font-semibold capitalize">{event.action} · {event.after.active ? roleLabel(event.after.role) : 'access revoked'}</p><p className="mt-1 text-ink-secondary">{event.after.expiresAt ? `Expires ${dateLabel(event.after.expiresAt)}` : 'No expiry'}</p>{event.before && <p className="mt-1 text-ink-secondary">Previously {event.before.active ? roleLabel(event.before.role) : 'revoked'} · {event.before.expiresAt ? `expires ${dateLabel(event.before.expiresAt)}` : 'no expiry'}</p>}<p className="mt-1 break-words text-metadata text-ink-muted">{dateLabel(event.createdAt)} · {event.actor}</p></li>)}</ol>}
  </section>;
}
