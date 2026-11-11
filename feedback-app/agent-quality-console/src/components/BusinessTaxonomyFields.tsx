import React, { useEffect, useId, useState } from 'react';
import { BusinessTaxonomyOptions, getBusinessTaxonomyOptions } from '../api/feedbackApi';

export const standardBusinessDomains = ['O2C', 'F2S', 'P2P', 'R2R'];
const fallback: BusinessTaxonomyOptions = { domains: standardBusinessDomains, subdomains: {}, allowCustom: true };
const fieldClass = 'mt-1.5 w-full rounded-lg border border-surface-border bg-surface px-3 py-2.5 text-body-sm font-normal text-ink-primary outline-none focus-visible:ring-2 focus-visible:ring-primary disabled:opacity-60';
const knownValue = (value: string) => `known:${value}`;

export function BusinessTaxonomyFields({ domain, subdomain, onChange, disabled = false, options: suppliedOptions,
  domainLabel = 'Business domain', subdomainLabel = 'Business subdomain' }: {
  domain: string; subdomain: string; onChange: (domain: string, subdomain: string) => void; disabled?: boolean;
  options?: BusinessTaxonomyOptions; domainLabel?: string; subdomainLabel?: string;
}) {
  const id = useId();
  const [options, setOptions] = useState<BusinessTaxonomyOptions>(suppliedOptions || fallback);
  const [loading, setLoading] = useState(!suppliedOptions);
  const [unavailable, setUnavailable] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [customDomain, setCustomDomain] = useState(false);
  const [customSubdomain, setCustomSubdomain] = useState(false);
  const [domainDraft, setDomainDraft] = useState(standardBusinessDomains.includes(domain) || domain === 'Unspecified' ? '' : domain);
  const [subdomainDraft, setSubdomainDraft] = useState(subdomain);
  useEffect(() => {
    if (suppliedOptions) { setOptions(suppliedOptions); setLoading(false); return; }
    let cancelled = false;
    setLoading(true); setUnavailable(false);
    void getBusinessTaxonomyOptions(refresh > 0)
      .then((value) => { if (!cancelled) setOptions(value); })
      .catch(() => { if (!cancelled) setUnavailable(true); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [suppliedOptions, refresh]);

  const selectedDomain = domain && domain !== 'Unspecified' ? domain : '';
  const domains = Array.from(new Set([...standardBusinessDomains, ...options.domains, ...(!customDomain && selectedDomain ? [selectedDomain] : [])])).filter((value) => value !== 'Unspecified');
  const subdomains = Array.from(new Set([...(options.subdomains[selectedDomain || 'Unspecified'] || []), ...(!customSubdomain && subdomain ? [subdomain] : [])]));
  return <div className="space-y-3">
    <div className="grid gap-3 sm:grid-cols-2">
      <div className="min-w-0"><label htmlFor={`${id}-domain`} className="text-label-sm font-medium text-ink-secondary">{domainLabel} <span className="font-normal text-ink-muted">(optional)</span></label>
        <select id={`${id}-domain`} aria-label={domainLabel} disabled={disabled} value={customDomain ? 'custom' : selectedDomain ? knownValue(selectedDomain) : ''} onChange={(event) => {
          const value = event.target.value;
          setCustomSubdomain(false);
          if (value === 'custom') { setCustomDomain(true); onChange(domainDraft, ''); }
          else { setCustomDomain(false); onChange(value ? value.slice('known:'.length) : '', ''); }
        }} className={fieldClass}><option value="">Not sure / not provided</option>{domains.map((value) => <option key={value} value={knownValue(value)}>{value}</option>)}<option value="custom">Other — enter a custom domain</option></select>
        {customDomain && <div className="mt-2"><label htmlFor={`${id}-custom-domain`} className="text-label-sm text-ink-secondary">Custom domain</label><input id={`${id}-custom-domain`} aria-label="Custom business domain" disabled={disabled} required pattern={'.*\\S.*'} maxLength={100} value={domain} onChange={(event) => { setDomainDraft(event.target.value); onChange(event.target.value, subdomain); }} placeholder="Enter a business domain" className={fieldClass} /></div>}
      </div>
      <div className="min-w-0"><label htmlFor={`${id}-subdomain`} className="text-label-sm font-medium text-ink-secondary">{subdomainLabel} <span className="font-normal text-ink-muted">(optional)</span></label>
        <select id={`${id}-subdomain`} aria-label={subdomainLabel} disabled={disabled} value={customSubdomain ? 'custom' : subdomain ? knownValue(subdomain) : ''} onChange={(event) => {
          const value = event.target.value;
          if (value === 'custom') { setCustomSubdomain(true); onChange(domain, subdomainDraft); }
          else { setCustomSubdomain(false); onChange(domain, value ? value.slice('known:'.length) : ''); }
        }} className={fieldClass}><option value="">Not sure / not provided</option>{subdomains.map((value) => <option key={value} value={knownValue(value)}>{value}</option>)}<option value="custom">Other — enter a custom subdomain</option></select>
        {customSubdomain && <div className="mt-2"><label htmlFor={`${id}-custom-subdomain`} className="text-label-sm text-ink-secondary">Custom subdomain</label><input id={`${id}-custom-subdomain`} aria-label="Custom business subdomain" disabled={disabled} required pattern={'.*\\S.*'} maxLength={300} value={subdomain} onChange={(event) => { setSubdomainDraft(event.target.value); onChange(domain, event.target.value); }} placeholder="Enter a business subdomain" className={fieldClass} /></div>}
      </div>
    </div>
    {loading && <p role="status" className="text-metadata text-ink-muted">Loading saved business classifications… You can already choose a standard or custom domain.</p>}
    {unavailable && <p role="note" className="text-metadata text-ink-muted">Saved choices couldn't be loaded. Standard domains and custom entries are still available. <button type="button" disabled={disabled || loading} onClick={() => setRefresh((value) => value + 1)} className="rounded underline underline-offset-2 focus-visible:ring-2 focus-visible:ring-primary">Retry saved choices</button></p>}
  </div>;
}
