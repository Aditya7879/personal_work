import React, { useId, useLayoutEffect, useRef, useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';

/** Read the entire content inside a bounded, keyboard-scrollable viewport. */
export const ContentPreview: React.FC<{ label: string; children: React.ReactNode; compact?: boolean }> = ({ label, children, compact = false }) => {
  const viewport = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [overflows, setOverflows] = useState(false);
  const id = useId();
  useLayoutEffect(() => {
    const measure = () => {
      if (expanded || !viewport.current || !content.current || !viewport.current.clientHeight) return;
      setOverflows(content.current.scrollHeight > viewport.current.clientHeight + 2);
    };
    measure();
    const observer = new ResizeObserver(measure);
    if (viewport.current) observer.observe(viewport.current);
    if (content.current) observer.observe(content.current);
    return () => observer.disconnect();
  }, [children, expanded]);

  return <div className="content-preview min-w-0 overflow-hidden rounded-lg border border-surface-border bg-canvas/60">
    <div id={id} ref={viewport} role="region" aria-label={`${label} content`} tabIndex={overflows ? 0 : undefined} className={`overscroll-contain overflow-auto outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary ${expanded ? 'max-h-[min(60vh,36rem)]' : compact ? 'max-h-28' : 'max-h-44'}`} style={{ scrollbarGutter: 'stable' }}>
      <div ref={content} className="p-3 text-body-sm text-ink-secondary">{children}</div>
    </div>
    {overflows && <div className="flex items-center justify-between gap-3 border-t border-surface-border px-3 py-1.5">
      <span className="text-metadata text-ink-muted">Scroll to read the full content</span>
      <button type="button" aria-label={`${expanded ? 'Show less' : 'See more'} of ${label.toLowerCase()}`} aria-expanded={expanded} aria-controls={id} onClick={() => { if (expanded) viewport.current?.scrollTo({ top: 0 }); setExpanded((value) => !value); }} className="inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-label-sm font-medium text-ink-primary outline-none hover:bg-state-gray-soft focus-visible:ring-2 focus-visible:ring-primary">
        {expanded ? 'Show less' : 'See more'}{expanded ? <ChevronUp size={14} aria-hidden="true" /> : <ChevronDown size={14} aria-hidden="true" />}
      </button>
    </div>}
  </div>;
};
