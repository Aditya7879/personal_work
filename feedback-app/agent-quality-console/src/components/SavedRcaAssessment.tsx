import React from 'react';
import { AnswerVersion, DiagnosisVersion } from '../api/feedbackApi';
import { formatRcaLabel } from '../utils/formatRcaLabel';
import { ContentPreview } from './ContentPreview';
import { RcaRationale } from './RcaRationale';
import { BookOpen } from 'lucide-react';
import { ActionButton } from './ActionButton';

/** Saved diagnoses are immutable; never reuse the original-submission editors. */
export const SavedRcaAssessment: React.FC<{
  answer: AnswerVersion;
  diagnosis?: DiagnosisVersion;
  pending: boolean;
  onReviewEvidence: (evidenceId?: string) => void;
}> = ({ answer, diagnosis, pending, onReviewEvidence }) => <div className="space-y-4" data-answer-id={answer.id}>
  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
    <label className="flex flex-col gap-1 text-label-sm font-medium text-ink-secondary">RCA category
      <input aria-label="RCA category" readOnly value={diagnosis ? formatRcaLabel(diagnosis.category) : pending ? 'Analysis in progress' : 'No saved diagnosis'} className="min-w-0 rounded-lg border border-surface-border bg-canvas p-2.5 text-label-md font-semibold text-ink-primary" />
    </label>
    <label className="flex flex-col gap-1 text-label-sm font-medium text-ink-secondary">RCA subcategory
      <input aria-label="RCA subcategory" readOnly value={diagnosis?.defect || ''} title={diagnosis?.defect || undefined} placeholder="No defect label recorded" className="min-w-0 rounded-lg border border-surface-border bg-canvas p-2.5 text-body-sm text-ink-primary" />
    </label>
  </div>
  <p className="text-metadata text-ink-muted">Saved diagnosis for this answer only · read-only · {diagnosis?.verified ? 'reviewer verified' : 'AI, not verified'}. It does not replace the original submission’s classification.</p>
  {diagnosis ? <div className="rounded-lg border border-surface-border bg-canvas/60 p-3">
    <div className="flex flex-wrap items-center gap-2 text-metadata text-ink-muted">
      <span>{diagnosis.verified ? 'Reviewer verified' : 'AI suggestion · review recommended'}</span>
      {answer.configurationRevision && <span>{answer.environmentLabel || 'Environment'} configuration r{answer.configurationRevision}</span>}
      {diagnosis.confidence != null && <span>Confidence {(diagnosis.confidence * 100).toFixed(0)}%</span>}
      {diagnosis.evidenceBackend && <span>{diagnosis.evidenceBackend === 'neo4j' ? 'Neo4j evidence' : formatRcaLabel(diagnosis.evidenceBackend)}</span>}
      {diagnosis.createdAt && <span>Assessed {Number.isNaN(Date.parse(diagnosis.createdAt)) ? 'time not recorded' : new Date(diagnosis.createdAt).toLocaleString()}</span>}
    </div>
    <div className="mt-2 text-body-sm text-ink-secondary"><ContentPreview key={diagnosis.id} label="RCA rationale" compact><RcaRationale text={diagnosis.rationale} evidence={diagnosis.evidence} onCitationClick={onReviewEvidence} /></ContentPreview></div>
    {diagnosis.evidence?.length ? <ActionButton label={`Review ${diagnosis.evidence.length} cited source passages`} compactLabel={`${diagnosis.evidence.length} sources`} icon={<BookOpen />} tone="ghost" size="sm" containerClassName="mt-3" onClick={() => onReviewEvidence()} /> : <p className="mt-2 text-body-sm text-ink-muted">{diagnosis.retrievalStatus === 'unavailable' ? 'Source retrieval was unavailable for this saved assessment.' : 'No supporting source passages were saved with this diagnosis.'}</p>}
    {!!diagnosis.remainingClaims?.length && <p className="mt-3 text-body-sm text-review-amber"><strong>Remaining:</strong> {diagnosis.remainingClaims.join(' · ')}</p>}
  </div> : <p role="status" className="text-body-sm text-ink-muted">{pending ? 'The answer is saved. Its evidence/RCA assessment will appear automatically when processing finishes.' : 'No RCA was saved for this answer version. Select a version with a completed diagnosis or review its job status in answer history.'}</p>}
</div>;
