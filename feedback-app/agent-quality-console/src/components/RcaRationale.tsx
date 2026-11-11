import React from 'react';
import { RcaEvidence } from '../types';

/** Only supplied evidence IDs become controls. Source text is never HTML/URLs. */
export const RcaRationale: React.FC<{
  text: string;
  evidence?: RcaEvidence[];
  onCitationClick?: (id: string) => void;
}> = ({ text, evidence = [], onCitationClick }) => {
  const byId = new Map(evidence.filter((source) => source.evidence_id).map((source) => [source.evidence_id!, source]));
  if (!onCitationClick || !byId.size) return <p className="whitespace-pre-wrap">{text}</p>;
  const ids = [...byId.keys()].sort((left, right) => right.length - left.length).map((id) => id.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  const parts = text.split(new RegExp(`(?<![A-Za-z0-9_-])(${ids.join('|')})(?![A-Za-z0-9_-])`, 'g'));
  return <p className="whitespace-pre-wrap">{parts.map((part, index) => {
    const source = byId.get(part);
    return source ? <button key={index} type="button" onClick={() => onCitationClick(part)} title={`${source.source || 'Source'}${source.page != null ? ` · page ${source.page}` : ''}`} aria-label={`Review citation ${part}`} className="break-all rounded-sm font-mono text-[0.9em] text-ink-primary underline decoration-surface-border underline-offset-2 outline-none hover:decoration-ink-secondary focus-visible:ring-2 focus-visible:ring-primary">{part}</button> : <React.Fragment key={index}>{part}</React.Fragment>;
  })}</p>;
};
