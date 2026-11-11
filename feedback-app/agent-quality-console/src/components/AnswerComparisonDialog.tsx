import React, { useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import { AnswerVersion } from '../api/feedbackApi';
import { AnswerMarkdown } from './AnswerMarkdown';
import { AnimatedDiv, AnimatedSection } from './UiMotion';
import { containDialogFocus, useDialogFocus } from '../utils/dialogFocus';

function environmentLabel(value?: string) {
  return value === 'prod' ? 'Production' : value === 'nonprod' ? 'Non-production' : 'Environment not recorded';
}

function versionLabel(answer: AnswerVersion) {
  const date = new Date(answer.createdAt);
  const stamp = Number.isNaN(date.getTime()) ? 'Time not recorded' : date.toLocaleString();
  return `${answer.kind === 'submission_edit' ? 'Submission correction' : 'Retest'} · r${answer.revision} · ${environmentLabel(answer.environment)} · ${stamp}`;
}

export const AnswerComparisonDialog: React.FC<{
  feedbackId: string;
  original?: AnswerVersion;
  selected?: AnswerVersion;
  versions: AnswerVersion[];
  onSelectVersion: (id: string) => void;
  onClose: () => void;
}> = ({ feedbackId, original, selected, versions, onSelectVersion, onClose }) => {
  const id = useId();
  const dialog = useRef<HTMLElement>(null);
  useDialogFocus(dialog);
  const [mobileAnswer, setMobileAnswer] = useState<'original' | 'updated'>(selected ? 'updated' : 'original');
  const differentContext = Boolean(original && selected && (original.question !== selected.question || original.environment !== selected.environment || (original.environmentId && selected.environmentId && original.environmentId !== selected.environmentId)));
  const note = selected?.kind === 'submission_edit' ? 'Reporter correction · not an agent rerun' : 'Automatically visible to reporter · AI assessment unverified';

  return createPortal(<AnimatedDiv surface="backdrop" className="fixed inset-0 z-[80] flex items-center justify-center bg-black/45 p-0 sm:p-4" onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <AnimatedSection ref={dialog} role="dialog" aria-modal="true" aria-labelledby={`${id}-title`} aria-describedby={`${id}-description`} className="flex h-full max-h-dvh w-full max-w-[1500px] flex-col overflow-hidden border border-surface-border bg-surface text-ink-primary shadow-2xl sm:h-[92dvh] sm:rounded-xl" onKeyDown={(event) => containDialogFocus(event, onClose)}>
      <header className="flex shrink-0 items-start justify-between gap-4 border-b border-surface-border px-4 py-4 sm:px-5">
        <div className="min-w-0"><h2 id={`${id}-title`} className="font-headline-md">Answer comparison</h2><p id={`${id}-description`} className="mt-1 text-body-sm text-ink-muted">Full saved responses · read-only · <span className="font-code-xs">{feedbackId}</span></p></div>
        <button data-dialog-autofocus type="button" aria-label="Close answer comparison" onClick={onClose} className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-surface-border text-ink-secondary outline-none hover:bg-canvas focus-visible:ring-2 focus-visible:ring-primary"><X size={18} aria-hidden="true" /></button>
      </header>
      {(versions.length > 0 || differentContext) && <div className="shrink-0 space-y-2 border-b border-surface-border px-4 py-3 sm:px-5">
        {!!versions.length && <label className="flex min-w-0 flex-wrap items-center gap-2 text-label-sm text-ink-secondary"><span>Compare original with</span><select aria-label="Comparison answer version" value={selected?.id || ''} onChange={(event) => onSelectVersion(event.target.value)} className="min-w-0 max-w-full rounded-lg border border-surface-border bg-canvas px-3 py-2 text-body-sm text-ink-primary outline-none focus-visible:ring-2 focus-visible:ring-primary">{versions.map((answer) => <option key={answer.id} value={answer.id}>{versionLabel(answer)}</option>)}</select></label>}
        {differentContext && <p className="text-metadata text-ink-muted">The recorded question or environment differs between these versions. This historical comparison is not proof of a fix.</p>}
      </div>}
      <div role="group" aria-label="Choose answer to read" className="mx-4 mt-3 flex shrink-0 gap-1 rounded-lg bg-canvas p-1 sm:hidden">
        {(['original', 'updated'] as const).map((side) => <button key={side} type="button" aria-controls={`${id}-${side}`} aria-pressed={mobileAnswer === side} onClick={() => setMobileAnswer(side)} className={`flex-1 rounded-md px-3 py-2 text-label-sm outline-none focus-visible:ring-2 focus-visible:ring-primary ${mobileAnswer === side ? 'border border-surface-border bg-surface font-semibold' : 'border border-transparent text-ink-secondary'}`}>{side === 'original' ? 'Original answer' : 'Updated answer'}</button>)}
      </div>
      <div className="grid min-h-0 flex-1 gap-4 p-4 sm:grid-cols-2 sm:p-5">
        <ComparisonPane key={original?.id || 'original'} id={`${id}-original`} title="Original answer" answer={original} note="Preserved original submission" hiddenOnMobile={mobileAnswer !== 'original'} />
        <ComparisonPane key={selected?.id || 'updated'} id={`${id}-updated`} title={selected?.kind === 'submission_edit' ? 'Corrected submitted response' : 'Updated answer'} answer={selected} note={selected ? note : ''} hiddenOnMobile={mobileAnswer !== 'updated'} empty="No refreshed response has been saved yet. Retest answers appear automatically when available." />
      </div>
    </AnimatedSection>
  </AnimatedDiv>, document.body);
};

function ComparisonPane({ id, title, answer, note, hiddenOnMobile, empty }: { id: string; title: string; answer?: AnswerVersion; note: string; hiddenOnMobile: boolean; empty?: string }) {
  return <article id={id} className={`${hiddenOnMobile ? 'hidden sm:flex' : 'flex'} min-h-0 min-w-0 flex-col overflow-hidden rounded-lg border border-surface-border`}>
    <div className="shrink-0 border-b border-surface-border bg-canvas/50 p-3 sm:p-4">
      <h3 className="font-title-md">{title}</h3>
      <p className="mt-1 text-metadata text-ink-muted">{note}</p>
      {answer && <p className="mt-1 text-label-sm text-ink-secondary">Reporter verdict for this version: <strong>{answer.userVerdict || 'Not recorded'}</strong></p>}
      {answer && <><p className="mt-1 text-metadata text-ink-secondary">{answer.environmentLabel || environmentLabel(answer.environment)} · revision {answer.revision} · {answer.agentVersion || 'agent version not recorded'}</p>{answer.question && <details className="mt-2"><summary className="cursor-pointer text-label-sm text-ink-secondary">Question</summary><p tabIndex={0} className="mt-2 max-h-24 overflow-auto whitespace-pre-wrap text-body-sm text-ink-secondary">{answer.question}</p></details>}</>}
    </div>
    <div role="region" aria-label={`${title} full text`} tabIndex={0} className="comparison-answer-content min-h-0 flex-1 overflow-auto overscroll-contain p-4 outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary sm:p-5" style={{ scrollbarGutter: 'stable' }}>
      {answer?.answer ? <AnswerMarkdown content={answer.answer} /> : <p className="text-body-sm text-ink-muted">{empty || 'No original answer snapshot was captured.'}</p>}
    </div>
  </article>;
}
