import React, { useEffect, useId, useRef, useState } from 'react';
import { useReducedMotion } from 'motion/react';
import { FeedbackItem, RcaEvidence } from '../types';
import { CollapsibleSection } from './CollapsibleSection';

export type EvidenceAssessment = {
  answerId: string; label: string; diagnosisId?: string; evidence: RcaEvidence[];
  capturedEvidence?: FeedbackItem['evidence']; pending?: boolean;
  retrievalStatus?: 'available' | 'no_matches' | 'unavailable';
};
export type EvidenceFocusRequest = { answerId: string; diagnosisId?: string; evidenceId?: string; sequence: number };

export const FeedbackEvidencePanel: React.FC<{
  item: FeedbackItem; open: boolean; onOpenChange: (open: boolean) => void;
  assessment?: EvidenceAssessment; focusRequest?: EvidenceFocusRequest;
}> = ({ item, open, onOpenChange, assessment, focusRequest }) => {
  const [tab, setTab] = useState<'passages' | 'references' | 'retrieval'>('passages');
  const id = useId();
  const root = useRef<HTMLDivElement>(null);
  const articles = useRef(new Map<string, HTMLElement>());
  const wasOpen = useRef(open);
  const pendingFocus = useRef(false);
  const reducedMotion = useReducedMotion();
  const original = assessment ? assessment.capturedEvidence || [] : item.evidence || [];
  const rca = assessment ? assessment.evidence : item.suggestedRcaEvidence || [];
  const viewKey = `${assessment?.answerId || item.id}:${assessment?.diagnosisId || 'submission'}`;
  const focus = focusRequest?.answerId === assessment?.answerId && focusRequest?.diagnosisId === assessment?.diagnosisId ? focusRequest : undefined;
  const passages: Array<RcaEvidence & { id: string }> = [
    ...original.map((source, index) => ({ ...source, id: source.id || `Original ${index + 1}`, origin: 'Original capture' })),
    ...rca.map((source, index) => ({ ...source, id: source.evidence_id || `RCA ${index + 1}` })),
  ];
  const tabs = [{ id: 'passages' as const, label: 'Passages' }, { id: 'references' as const, label: 'References' }, { id: 'retrieval' as const, label: 'Retrieval' }];
  const focusPassage = () => {
    if (!open || !focus) return;
    const article = focus.evidenceId ? articles.current.get(focus.evidenceId) : null;
    (article || root.current)?.scrollIntoView({ behavior: reducedMotion ? 'instant' : 'smooth', block: 'nearest' });
    article?.focus({ preventScroll: true });
  };
  useEffect(() => { setTab('passages'); }, [viewKey]);
  useEffect(() => {
    const alreadyOpen = wasOpen.current;
    wasOpen.current = open;
    pendingFocus.current = false;
    if (!open || !focus) return;
    setTab('passages');
    if (!alreadyOpen && !reducedMotion) { pendingFocus.current = true; return; }
    const frame = requestAnimationFrame(focusPassage);
    return () => cancelAnimationFrame(frame);
  }, [open, focus?.sequence, viewKey, reducedMotion]);

  return <div ref={root} id={`feedback-evidence-${item.id}`} className="scroll-mt-20">
    <CollapsibleSection title="Evidence & citations" summary={passages.length ? `${passages.length} source passages · ${assessment?.label || 'submission'} · reviewer only` : assessment?.pending ? 'Source assessment in progress' : 'No source passages for this version'} open={open} onOpenChange={onOpenChange} onOpened={() => { if (pendingFocus.current) { pendingFocus.current = false; focusPassage(); } }}>
      {assessment && <p className="mb-3 text-metadata text-ink-muted">{assessment.label} · {assessment.diagnosisId ? 'Sources cited by the saved RCA' : 'Submission source references'} · reviewer only</p>}
      <div role="tablist" aria-label="Evidence views" className="mb-3 flex gap-1 rounded-lg bg-canvas p-1" onKeyDown={(event) => {
        const index = tabs.findIndex((entry) => entry.id === tab);
        const next = event.key === 'ArrowRight' ? (index + 1) % tabs.length : event.key === 'ArrowLeft' ? (index + tabs.length - 1) % tabs.length : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : -1;
        if (next >= 0) { event.preventDefault(); setTab(tabs[next].id); event.currentTarget.querySelectorAll<HTMLButtonElement>('button')[next]?.focus(); }
      }}>{tabs.map((entry) => <button key={entry.id} id={`${id}-${entry.id}`} type="button" role="tab" aria-selected={tab === entry.id} aria-controls={`${id}-panel`} tabIndex={tab === entry.id ? 0 : -1} onClick={() => setTab(entry.id)} className={`flex-1 rounded-md px-2 py-1.5 text-label-sm outline-none transition-colors focus-visible:ring-2 focus-visible:ring-primary ${tab === entry.id ? 'border border-surface-border bg-surface font-semibold text-ink-primary' : 'border border-transparent text-ink-muted hover:text-ink-primary'}`}>{entry.label}</button>)}</div>
      <div id={`${id}-panel`} role="tabpanel" aria-labelledby={`${id}-${tab}`} tabIndex={0} className="max-h-96 space-y-3 overflow-auto overscroll-contain outline-none focus-visible:ring-2 focus-visible:ring-primary">
        {!passages.length ? <p className="py-2 text-body-sm text-ink-muted">{assessment?.pending ? 'This answer’s evidence/RCA check is still processing. Source passages will appear automatically when saved.' : assessment?.retrievalStatus === 'unavailable' ? 'Source retrieval was unavailable for this saved diagnosis. No local fallback was used.' : 'No source passages were saved for this assessment version. Other answer versions may have their own cited evidence.'}</p> : passages.map((passage, index) => <article key={`${viewKey}-${passage.id}-${index}`} ref={(element) => { if (element) articles.current.set(passage.id, element); else articles.current.delete(passage.id); }} tabIndex={-1} data-evidence-id={passage.id} className={`scroll-mt-20 rounded-lg border p-3 outline-none focus-visible:ring-2 focus-visible:ring-primary ${focus?.evidenceId === passage.id ? 'border-ink-muted bg-canvas' : 'border-surface-border'}`}>
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1"><span className="font-code-xs text-ink-muted">{passage.id}</span><span className="text-metadata text-ink-muted">{passage.page != null ? `Page ${passage.page}` : 'Page not recorded'}</span></div>
          <p className="mt-1 break-long-source text-body-sm font-medium text-ink-primary">{passage.source || 'Source not recorded'}</p>
          {tab === 'passages' && (passage.context || passage.excerpt) && <details key={`${viewKey}-${passage.id}`} open={focus?.evidenceId === passage.id ? true : undefined} className="mt-2"><summary className="cursor-pointer text-label-sm text-ink-secondary">Read passage</summary><p tabIndex={0} className="mt-2 max-h-48 overflow-auto overscroll-contain whitespace-pre-wrap text-body-sm text-ink-secondary">{passage.context || passage.excerpt}</p></details>}
          {tab === 'references' && !!passage.source_uris?.length && <div className="mt-2 space-y-1 text-metadata text-ink-muted"><p>Parsed source artifacts (not original PDF/PPTX downloads):</p>{passage.source_uris.map((uri, uriIndex) => <p key={uriIndex} className="break-all">{uri}</p>)}</div>}
          {tab === 'retrieval' && <div className="mt-2 space-y-1 text-metadata text-ink-muted"><p>{passage.origin === 'neo4j' ? 'Neo4j' : passage.origin || 'Source record'}{passage.score != null ? ` · ranking score ${passage.score.toFixed(passage.origin === 'neo4j' ? 6 : 2)}` : ''}</p>{!!passage.retrieval_methods?.length && <p>Retrieval: {passage.retrieval_methods.join(' · ')}</p>}{passage.document_id && <p className="break-all">Document: {passage.document_id}</p>}{(passage.chunk_id || passage.element_id) && <p className="break-all">Chunk / element: {passage.chunk_id || passage.element_id}{passage.chunk_position != null ? ` · position ${passage.chunk_position}` : ''}</p>}{passage.parser_origin && <p>Parser: {passage.parser_origin}</p>}{passage.corpus_version && <p className="break-all">Source manifest: {passage.corpus_version}</p>}{passage.chunk_content_sha256 && <p className="break-all">Chunk SHA-256: {passage.chunk_content_sha256}</p>}</div>}
        </article>)}
      </div>
      {tab === 'retrieval' && <p className="mt-3 text-metadata text-ink-muted">These are the sources saved for this assessment, not a reconstruction of the agent’s retrieval trace. Graph expansion is a retrieval hint, not a verified relationship. Private agent diagnostics are separate in answer history.</p>}
    </CollapsibleSection>
  </div>;
};
