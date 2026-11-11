import React, { useId, useLayoutEffect, useRef, useState } from 'react';
import { ArrowLeft, ArrowLeftRight, ArrowRight } from 'lucide-react';

/** Top scrollbar and column navigation synchronized with the actual table. */
export const HorizontalTableScroll: React.FC<{ children: React.ReactNode; label: string }> = ({ children, label }) => {
  const viewport = useRef<HTMLDivElement>(null);
  const topBar = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const id = useId();
  const [metrics, setMetrics] = useState({ width: 0, visible: 0, left: 0 });
  useLayoutEffect(() => {
    const measure = () => {
      const element = viewport.current;
      if (!element) return;
      const width = element.scrollWidth;
      const visible = element.clientWidth;
      const left = element.scrollLeft;
      setMetrics((old) => old.width === width && old.visible === visible && old.left === left ? old : { width, visible, left });
      if (topBar.current && Math.abs(topBar.current.scrollLeft - left) > 1) topBar.current.scrollLeft = left;
    };
    const observer = new ResizeObserver(measure);
    if (viewport.current) observer.observe(viewport.current);
    if (content.current) observer.observe(content.current);
    if (content.current?.firstElementChild) observer.observe(content.current.firstElementChild);
    measure();
    return () => observer.disconnect();
  }, []);
  const sync = (from: HTMLDivElement, to: HTMLDivElement | null) => {
    if (to && Math.abs(to.scrollLeft - from.scrollLeft) > 1) to.scrollLeft = from.scrollLeft;
    const left = from.scrollLeft;
    setMetrics((old) => old.left === left ? old : { ...old, left });
  };
  const overflow = metrics.width > metrics.visible + 1;
  const move = (direction: number) => viewport.current?.scrollBy({ left: direction * Math.max(240, metrics.visible * 0.65), behavior: 'smooth' });
  return <>
    <div className="flex items-center gap-3 border-b border-surface-border bg-surface px-3 py-2">
      <span className="inline-flex shrink-0 items-center gap-1.5 text-metadata font-medium text-ink-muted"><ArrowLeftRight size={14} aria-hidden="true" /><span>Columns</span></span>
      <button type="button" aria-label="Scroll columns left" aria-controls={id} disabled={!overflow || metrics.left <= 1} onClick={() => move(-1)} className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-surface-border bg-surface text-ink-secondary outline-none hover:bg-indigo-soft focus-visible:ring-2 focus-visible:ring-primary disabled:opacity-30"><ArrowLeft size={14} aria-hidden="true" /></button>
      <div ref={topBar} role="region" aria-label={`${label} horizontal scrollbar`} tabIndex={overflow ? 0 : -1} onScroll={(event) => sync(event.currentTarget, viewport.current)} className="table-column-scrollbar min-w-0 flex-1 rounded-full outline-none focus-visible:ring-2 focus-visible:ring-primary" style={{ visibility: overflow ? 'visible' : 'hidden' }}><div style={{ width: metrics.width, height: 1 }} /></div>
      <button type="button" aria-label="Scroll columns right" aria-controls={id} disabled={!overflow || metrics.left >= metrics.width - metrics.visible - 1} onClick={() => move(1)} className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-surface-border bg-surface text-ink-secondary outline-none hover:bg-indigo-soft focus-visible:ring-2 focus-visible:ring-primary disabled:opacity-30"><ArrowRight size={14} aria-hidden="true" /></button>
    </div>
    <div ref={viewport} id={id} role="region" aria-label={`${label} table scroll area`} tabIndex={0} onScroll={(event) => sync(event.currentTarget, topBar.current)} className="overflow-auto outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary" style={{ maxHeight: 'min(65dvh, 720px)' }}><div ref={content} className="min-w-full">{children}</div></div>
  </>;
};
