import { useEffect, useId } from 'react';

const drafts = new Set<string>();

export function useUnsavedDemoDraft(dirty: boolean): void {
  const id = useId();
  useEffect(() => {
    if (dirty) drafts.add(id); else drafts.delete(id);
    const warn = (event: BeforeUnloadEvent) => { if (dirty) { event.preventDefault(); event.returnValue = ''; } };
    if (dirty) window.addEventListener('beforeunload', warn);
    return () => { drafts.delete(id); window.removeEventListener('beforeunload', warn); };
  }, [dirty, id]);
}

export function confirmDemoNavigation(message: string): boolean {
  return !drafts.size || window.confirm(`${message}\n\nYou have unsaved changes. Cancel to keep editing, or continue to discard them.`);
}
