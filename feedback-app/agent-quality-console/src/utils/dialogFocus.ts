import { useLayoutEffect, useRef, type KeyboardEvent, type RefObject } from 'react';

export function dialogFocusTargets(dialog: HTMLElement): HTMLElement[] {
  return Array.from(dialog.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),textarea:not(:disabled),select:not(:disabled),a[href],summary,[tabindex="0"]'))
    .filter((element) => element.getClientRects().length > 0 && !element.closest('[hidden], [inert], [aria-hidden="true"]'));
}

export function containDialogFocus(event: KeyboardEvent<HTMLElement>, onClose: () => void): void {
  // React events bubble through portals; a nested comparison owns its own keyboard scope.
  if (event.defaultPrevented || !event.currentTarget.contains(event.target as Node)) return;
  if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); onClose(); return; }
  if (event.key !== 'Tab') return;
  const targets = dialogFocusTargets(event.currentTarget);
  if (!targets.length) { event.preventDefault(); event.currentTarget.focus(); return; }
  const first = targets[0], last = targets[targets.length - 1];
  if (event.shiftKey && (document.activeElement === first || !targets.includes(document.activeElement as HTMLElement))) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && (document.activeElement === last || !targets.includes(document.activeElement as HTMLElement))) { event.preventDefault(); first.focus(); }
}

/** Portal dialogs keep the background locked until their exit animation has finished. */
export function useDialogFocus(dialog: RefObject<HTMLElement | null>, enabled = true): void {
  const opener = useRef<HTMLElement | null>(null);
  useLayoutEffect(() => {
    if (!enabled) return;
    if (!opener.current && document.activeElement instanceof HTMLElement) opener.current = document.activeElement;
    const owner = opener.current?.closest<HTMLElement>('[role="dialog"][aria-modal="true"]');
    const ownerInert = owner?.inert || false;
    const root = document.getElementById('root');
    const previousInert = root?.inert || false;
    const previousHidden = root?.getAttribute('aria-hidden');
    const previousOverflow = document.body.style.overflow;
    const target = dialog.current?.querySelector<HTMLElement>('[data-dialog-autofocus]') || (dialog.current && dialogFocusTargets(dialog.current)[0]) || dialog.current;
    target?.focus({ preventScroll: true });
    if (root) { root.inert = true; root.setAttribute('aria-hidden', 'true'); }
    if (owner && owner !== dialog.current) owner.inert = true;
    document.body.style.overflow = 'hidden';
    return () => {
      if (root) { root.inert = previousInert; if (previousHidden == null) root.removeAttribute('aria-hidden'); else root.setAttribute('aria-hidden', previousHidden); }
      if (owner && owner !== dialog.current) owner.inert = ownerInert;
      document.body.style.overflow = previousOverflow;
      requestAnimationFrame(() => {
        // StrictMode replays effects without removing the dialog; don't steal its focus.
        if ((!enabled || !dialog.current?.isConnected) && opener.current?.isConnected && !opener.current.closest('[inert]')) opener.current.focus({ preventScroll: true });
      });
    };
  }, [dialog, enabled]);
}
