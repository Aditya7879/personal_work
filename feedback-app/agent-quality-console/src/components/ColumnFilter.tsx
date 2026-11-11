import React, { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { AnimatePresence } from 'motion/react';
import { AnimatedDiv } from './UiMotion';

export interface ColumnFilterOption {
  value: string;
  label: string;
}

interface ColumnFilterProps {
  label: string;
  value: string;
  options: ColumnFilterOption[];
  allLabel: string;
  loading?: boolean;
  onChange: (value: string) => void;
}

export const ColumnFilter: React.FC<ColumnFilterProps> = ({ label, value, options, allLabel, loading = false, onChange }) => {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState('');
  const [position, setPosition] = useState({ top: 0, left: 0, width: 320 });
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popupRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const popupId = useId();
  const active = value !== 'All';
  const selectedLabel = options.find((option) => option.value === value)?.label || value;
  const hasSearch = options.length > 6;
  const query = search.trim().toLocaleLowerCase();
  const visibleOptions = options.filter((option) => option.label.toLocaleLowerCase().includes(query));

  const close = (restoreFocus = true) => {
    setOpen(false);
    setSearch('');
    if (restoreFocus) triggerRef.current?.focus();
  };

  const choose = (nextValue: string) => {
    close();
    onChange(nextValue);
  };

  useLayoutEffect(() => {
    if (!open) return;
    const placePopup = () => {
      const rect = triggerRef.current?.getBoundingClientRect();
      if (!rect) return;
      if (rect.width === 0 || rect.right < 0 || rect.left > window.innerWidth || rect.bottom < 0 || rect.top > window.innerHeight) {
        close(false);
        return;
      }
      const margin = 12;
      const width = Math.min(320, window.innerWidth - margin * 2);
      const height = popupRef.current?.offsetHeight || 360;
      const below = rect.bottom + 8;
      const top = below + height <= window.innerHeight - margin ? below : Math.max(margin, rect.top - height - 8);
      const left = Math.max(margin, Math.min(rect.left, window.innerWidth - width - margin));
      setPosition((current) => current.top === top && current.left === left && current.width === width ? current : { top, left, width });
    };
    const onScroll = (event: Event) => {
      if (event.target instanceof Node && popupRef.current?.contains(event.target)) return;
      placePopup();
    };
    placePopup();
    window.addEventListener('resize', placePopup);
    document.addEventListener('scroll', onScroll, true);
    return () => {
      window.removeEventListener('resize', placePopup);
      document.removeEventListener('scroll', onScroll, true);
    };
  }, [open, visibleOptions.length, hasSearch, position.width]);

  useEffect(() => {
    if (!open) return;
    if (hasSearch) searchRef.current?.focus();
    else popupRef.current?.querySelector<HTMLButtonElement>('[aria-pressed="true"]')?.focus();
    const isOutside = (target: EventTarget | null) => target instanceof Node && !triggerRef.current?.contains(target) && !popupRef.current?.contains(target);
    const dismissOutside = (event: Event) => { if (isOutside(event.target)) close(false); };
    const dismissEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      close();
    };
    document.addEventListener('pointerdown', dismissOutside);
    document.addEventListener('focusin', dismissOutside);
    document.addEventListener('keydown', dismissEscape);
    return () => {
      document.removeEventListener('pointerdown', dismissOutside);
      document.removeEventListener('focusin', dismissOutside);
      document.removeEventListener('keydown', dismissEscape);
    };
  }, [open, hasSearch]);

  return <>
    <button
      ref={triggerRef}
      type="button"
      disabled={loading}
      aria-label={`Filter by ${label.toLowerCase()}`}
      aria-haspopup="dialog"
      aria-expanded={open}
      aria-controls={open ? popupId : undefined}
      title={loading ? `Loading ${label.toLowerCase()} choices…` : active ? `${label}: ${selectedLabel}` : `Filter by ${label.toLowerCase()}`}
      onClick={() => { if (open) close(); else { setSearch(''); setOpen(true); } }}
      className={`inline-flex max-w-full flex-col items-start gap-1 rounded-md py-1 text-left outline-none transition-colors focus-visible:ring-2 focus-visible:ring-primary-container disabled:opacity-50 ${active || open ? 'text-primary-container' : 'hover:text-primary-container'}`}
    >
      <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
        <span>{label}</span>
        <span aria-hidden="true" className="material-symbols-outlined text-[15px]">filter_list</span>
        {active && <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-primary-container" />}
      </span>
      {active && <span className="max-w-[180px] truncate rounded bg-indigo-soft px-1.5 py-0.5 text-metadata font-medium normal-case tracking-normal">{selectedLabel}</span>}
    </button>
    {createPortal(<AnimatePresence>{open &&
      <AnimatedDiv
        key="filter"
        ref={popupRef}
        id={popupId}
        role="dialog"
        aria-labelledby={`${popupId}-title`}
        className="fixed z-[70] flex flex-col overflow-hidden rounded-xl border border-surface-border bg-surface text-left font-body text-ink-primary shadow-xl"
        style={{ ...position, maxHeight: 'calc(100vh - 24px)' }}
      >
        <div className="flex shrink-0 items-center justify-between gap-3 border-b border-surface-border px-3 py-2.5">
          <h2 id={`${popupId}-title`} className="font-label-md font-semibold">{label} filter</h2>
          <button type="button" onClick={() => close()} aria-label={`Close ${label.toLowerCase()} filter`} className="rounded-md p-1 text-ink-muted hover:bg-state-gray-soft hover:text-ink-primary">
            <span aria-hidden="true" className="material-symbols-outlined text-[18px]">close</span>
          </button>
        </div>
        {hasSearch && <div className="relative mx-3 my-2 shrink-0">
          <span aria-hidden="true" className="material-symbols-outlined absolute left-2.5 top-1/2 -translate-y-1/2 text-[17px] text-ink-muted">search</span>
          <input ref={searchRef} value={search} onChange={(event) => setSearch(event.target.value)} aria-label={`Search ${label.toLowerCase()} options`} placeholder="Search values…" className="h-9 w-full rounded-lg border border-surface-border bg-canvas pl-8 pr-2 text-body-sm outline-none focus:border-primary-container" />
        </div>}
        <button type="button" aria-pressed={!active} onClick={() => choose('All')} className={`mx-2 my-1 flex shrink-0 items-center justify-between gap-3 rounded-lg px-3 py-2 text-body-sm ${!active ? 'bg-indigo-soft font-semibold text-primary' : 'hover:bg-canvas'}`}>
          <span>{allLabel}</span><span aria-hidden="true" className="material-symbols-outlined text-[17px]">{!active ? 'check' : ''}</span>
        </button>
        <div className="min-h-0 max-h-64 overflow-y-auto border-t border-surface-border px-2 py-1">
          {visibleOptions.map((option) => <button key={option.value} type="button" aria-pressed={value === option.value} onClick={() => choose(option.value)} className={`flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-left text-body-sm ${value === option.value ? 'bg-indigo-soft font-semibold text-primary' : 'hover:bg-canvas'}`}>
            <span className="min-w-0 break-words">{option.label}</span>
            {value === option.value && <span aria-hidden="true" className="material-symbols-outlined shrink-0 text-[17px]">check</span>}
          </button>)}
          {!visibleOptions.length && <p className="px-3 py-4 text-body-sm text-ink-muted">{query ? 'No matching values.' : 'No values available yet.'}</p>}
        </div>
      </AnimatedDiv>
    }</AnimatePresence>, document.body)}
  </>;
};
