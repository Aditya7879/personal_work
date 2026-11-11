import React, { useEffect, useState } from 'react';
import { AgentEnvironment, BusinessContext } from '../api/feedbackApi';
import { CollapsibleSection } from './CollapsibleSection';
import { BusinessTaxonomyFields } from './BusinessTaxonomyFields';
import { useUnsavedDemoDraft } from '../utils/unsavedDemoDrafts';

export function businessClassificationLabel(context: BusinessContext): string {
  return context.domainVerified ? 'Confirmed classification' : context.domainSource === 'workbook_import' ? 'Imported workbook classification'
    : context.domainSource === 'user_submitted' ? 'Provided at submission · not independently verified'
    : context.domainSource === 'document_inferred' ? 'Document suggestion · not confirmed' : 'Needs confirmation';
}

export const BusinessDomainPanel: React.FC<{ context: BusinessContext; canEdit?: boolean; onSave: (fields: { business_domain: string; business_subdomain: string; environment: AgentEnvironment }) => Promise<void> }> = ({ context, canEdit = true, onSave }) => {
  const [domain, setDomain] = useState(context.businessDomain || 'Unspecified');
  const [subdomain, setSubdomain] = useState(context.businessSubdomain || '');
  const [environment, setEnvironment] = useState<AgentEnvironment>(context.environment || 'unknown');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useUnsavedDemoDraft(canEdit && (domain !== (context.businessDomain || 'Unspecified') || subdomain !== (context.businessSubdomain || '') || environment !== (context.environment || 'unknown')));
  useEffect(() => { setDomain(context.businessDomain || 'Unspecified'); setSubdomain(context.businessSubdomain || ''); setEnvironment(context.environment || 'unknown'); }, [context.businessDomain, context.businessSubdomain, context.environment]);
  const save = async () => {
    setSaving(true); setError(null);
    try { await onSave({ business_domain: domain.trim() || 'Unspecified', business_subdomain: subdomain.trim(), environment }); }
    catch (error) { setError(error instanceof Error ? error.message : 'Could not save business classification'); }
    finally { setSaving(false); }
  };
  const environmentLabel = context.environment === 'prod' ? 'Production' : context.environment === 'nonprod' ? 'Non-production' : 'Environment not recorded';
  return <CollapsibleSection title="Business domain & environment" summary={`${context.businessDomain || 'Unspecified'}${context.businessSubdomain ? ` / ${context.businessSubdomain}` : ''} · ${environmentLabel}`}>
    <p className="text-metadata font-medium text-ink-secondary">{businessClassificationLabel(context)}</p>
    <p className="mt-2 text-body-sm text-ink-secondary">{context.domainReason || 'Business context is separate from the RCA defect. Confirm it from the relevant documents.'}</p>
    {!!context.domainEvidence?.length && <ul className="mt-2 space-y-1 text-metadata text-ink-muted">{context.domainEvidence.map((evidence, index) => <li key={`${evidence.source}-${index}`}><span className="font-semibold">Source:</span> {evidence.source}{evidence.page != null && ` · page ${evidence.page}`} · {evidence.method === 'retrieved_document_content' ? 'document-content hint' : 'document-name hint'}</li>)}</ul>}
    <div className="mt-3"><BusinessTaxonomyFields domain={domain} subdomain={subdomain} disabled={!canEdit || saving} onChange={(nextDomain, nextSubdomain) => { setDomain(nextDomain); setSubdomain(nextSubdomain); }} /></div>
    <div className="mt-3 grid gap-3 @xl:grid-cols-3">
      <label className="text-label-sm text-ink-secondary">Original agent environment<select aria-label="Feedback environment" disabled={!canEdit || saving} value={environment} onChange={(event) => setEnvironment(event.target.value as AgentEnvironment)} className="mt-1 w-full rounded-lg border border-surface-border bg-surface px-2 py-2 text-body-sm"><option value="unknown">Not recorded / unknown</option><option value="nonprod">Non-production</option><option value="prod">Production</option></select></label>
    </div>
    {environment === 'unknown' && <p className="mt-2 text-metadata text-ink-muted">Retest answers remain visible automatically. Confirm the actual original environment before a result can resolve this report.</p>}
    {error && <p className="mt-2 text-body-sm text-issue-red">{error}</p>}
    {canEdit && <button type="button" onClick={() => void save()} disabled={saving} className="mt-3 rounded-lg border border-primary/20 bg-surface px-3 py-2 text-label-sm font-semibold text-primary disabled:opacity-50">{saving ? 'Saving…' : 'Confirm / correct classification'}</button>}
  </CollapsibleSection>;
};
