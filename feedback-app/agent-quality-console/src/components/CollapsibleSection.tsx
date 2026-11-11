import React, { useEffect, useId, useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { AnimatedCollapse } from './UiMotion';

/** A compact disclosure that retains form state while its contents are closed. */
export const CollapsibleSection: React.FC<{
  title: string;
  summary?: string;
  badge?: React.ReactNode;
  defaultOpen?: boolean;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  onOpened?: () => void;
  className?: string;
  children: React.ReactNode;
}> = ({ title, summary, badge, defaultOpen = false, open, onOpenChange, onOpened, className = '', children }) => {
  const [localOpen, setLocalOpen] = useState(defaultOpen);
  const [visited, setVisited] = useState(defaultOpen || Boolean(open));
  const id = useId();
  const expanded = open ?? localOpen;
  useEffect(() => { if (expanded) setVisited(true); }, [expanded]);
  return <section className={`disclosure-section @container min-w-0 overflow-hidden rounded-xl border border-surface-border bg-surface ${className}`}>
    <h3>
      <button id={`${id}-trigger`} type="button" aria-label={title} aria-expanded={expanded} aria-controls={`${id}-content`} onClick={() => { const next = !expanded; setLocalOpen(next); onOpenChange?.(next); }} className="flex min-h-14 w-full items-center gap-3 px-4 py-3 text-left outline-none transition-colors hover:bg-canvas focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary">
        <span className="min-w-0 flex-1"><span className="block text-label-sm font-semibold text-ink-primary">{title}</span>{summary && <span className="mt-0.5 block truncate text-metadata font-normal text-ink-muted">{summary}</span>}</span>
        {badge && <span className="shrink-0 text-metadata font-medium text-ink-secondary">{badge}</span>}
        <ChevronDown size={16} aria-hidden="true" className={`shrink-0 text-ink-muted transition-transform ${expanded ? 'rotate-180' : ''}`} />
      </button>
    </h3>
    <AnimatedCollapse id={`${id}-content`} role="region" aria-labelledby={`${id}-trigger`} open={expanded} onAnimationComplete={() => { if (expanded) onOpened?.(); }}>
      <div className="border-t border-surface-border p-4">{(expanded || visited) && children}</div>
    </AnimatedCollapse>
  </section>;
};
