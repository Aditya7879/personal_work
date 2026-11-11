import React, { useId, useRef } from 'react';
import { createPortal } from 'react-dom';
import { X } from 'lucide-react';
import { DemoAdminSession } from '../api/demoAdminApi';
import { AnimatedDiv, AnimatedSection } from './UiMotion';
import { containDialogFocus, useDialogFocus } from '../utils/dialogFocus';

export function DemoViewChooser({ session, busy, error, onSelect, onClose }: {
  session: DemoAdminSession; busy: boolean; error: string | null;
  onSelect: (email: string) => void; onClose: () => void;
}) {
  const id = useId();
  const dialog = useRef<HTMLElement>(null);
  useDialogFocus(dialog);
  const close = () => { if (!busy) onClose(); };
  return createPortal(<AnimatedDiv surface="backdrop" className="fixed inset-0 z-[90] flex items-center justify-center bg-ink-primary/35 p-4" onClick={event => { if (event.target === event.currentTarget) close(); }}>
    <AnimatedSection ref={dialog} role="dialog" aria-modal="true" aria-labelledby={`${id}-title`} aria-describedby={`${id}-description`} onKeyDown={event => containDialogFocus(event, close)} className="flex max-h-[90dvh] w-full max-w-lg flex-col overflow-hidden rounded-xl border border-surface-border bg-surface shadow-2xl">
      <header className="flex items-start justify-between gap-3 border-b border-surface-border p-5"><div><h2 id={`${id}-title`} className="font-headline-md">Switch demo view</h2><p id={`${id}-description`} className="mt-2 text-body-sm text-ink-secondary">Your Google/IAP sign-in stays active. Choose a fictional Reporter or Reviewer; no employee is impersonated.</p></div><button type="button" aria-label="Close demo view chooser" disabled={busy} onClick={close} className="rounded-lg p-2 text-ink-muted focus-visible:ring-2 focus-visible:ring-primary"><X size={18} aria-hidden="true" /></button></header>
      <div className="space-y-3 overflow-y-auto p-5"><p className="rounded-lg border border-surface-border bg-canvas p-3 text-metadata text-ink-secondary">Isolated sample data · simulated AI · no real provider calls. Only the original demo reporter can confirm their case.</p>
        {session.personas.map(persona => <button key={persona.email} type="button" disabled={busy} onClick={() => onSelect(persona.email)} className="block w-full rounded-lg border border-surface-border p-4 text-left outline-none hover:bg-canvas focus-visible:ring-2 focus-visible:ring-primary disabled:opacity-50"><span className="block text-label-md font-semibold">{persona.displayName}</span><span className="mt-1 block text-body-sm capitalize text-ink-secondary">{persona.role} view{session.user?.email === persona.email ? ' · current' : ''}</span></button>)}
        {busy && <p role="status" className="text-body-sm text-ink-secondary">Switching demo view…</p>}
        {error && <p role="alert" className="rounded-lg bg-issue-soft p-3 text-body-sm text-issue-red">{error}</p>}
      </div>
      <footer className="border-t border-surface-border p-4 text-right"><button type="button" disabled={busy} onClick={close} className="rounded-lg border border-surface-border px-3 py-2 text-label-sm">Keep current view</button></footer>
    </AnimatedSection>
  </AnimatedDiv>, document.body);
}
