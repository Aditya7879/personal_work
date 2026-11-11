import React, { useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { AnimatePresence } from 'motion/react';
import { Check, ChevronDown, Layers2 } from 'lucide-react';
import type { AgentEnvironmentConfig } from '../api/feedbackApi';
import { AnimatedDiv } from './UiMotion';
import { ActionButton } from './ActionButton';

export type EnvironmentSwitcherProps = { environments?: AgentEnvironmentConfig[]; environmentId?: string; onEnvironmentChange?: (id: string) => void; environmentsLoading?: boolean };

export function EnvironmentSwitcher({ environments = [], environmentId = 'All', onEnvironmentChange, environmentsLoading = false }: EnvironmentSwitcherProps) {
  const [open, setOpen] = useState(false);
  const [highlightedId, setHighlightedId] = useState(environmentId);
  const [position, setPosition] = useState({ top: 60, left: 12, width: 256, maxHeight: 320 });
  const trigger = useRef<HTMLButtonElement>(null);
  const popup = useRef<HTMLDivElement>(null);
  const typed = useRef({ value: '', at: 0 });
  const popupId = useId();
  const choices = useMemo(() => [{ id: 'All', name: 'All environments', disabled: false },
    ...environments.map((environment) => ({ id: environment.id, name: environment.name, disabled: !environment.enabled }))], [environments]);
  const selected = choices.find((choice) => choice.id === environmentId) || choices[0];
  const highlightedIndex = Math.max(0, choices.findIndex((choice) => choice.id === highlightedId));
  const optionId = (index: number) => `${popupId}-option-${index}`;

  const close = (restoreFocus = false) => {
    setOpen(false);
    typed.current = { value: '', at: 0 };
    if (restoreFocus) trigger.current?.focus();
  };
  const show = () => { setHighlightedId(selected.id); setOpen(true); };
  const choose = (id: string) => { close(true); onEnvironmentChange?.(id); };

  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const rect = trigger.current?.getBoundingClientRect();
      if (!rect) return;
      const width = Math.min(256, window.innerWidth - 24);
      const top = rect.bottom + 8;
      setPosition({ top, left: Math.max(12, Math.min(rect.left, window.innerWidth - width - 12)), width,
        maxHeight: Math.min(320, window.innerHeight - top - 12) });
    };
    place();
    const observer = new ResizeObserver(place);
    if (trigger.current) observer.observe(trigger.current);
    window.addEventListener('resize', place);
    return () => { observer.disconnect(); window.removeEventListener('resize', place); };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const dismissOutside = (event: Event) => {
      if (event.target instanceof Node && !trigger.current?.contains(event.target) && !popup.current?.contains(event.target)) close();
    };
    const dismissEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !event.defaultPrevented) { event.preventDefault(); close(true); }
    };
    document.addEventListener('pointerdown', dismissOutside);
    document.addEventListener('focusin', dismissOutside);
    document.addEventListener('keydown', dismissEscape);
    return () => {
      document.removeEventListener('pointerdown', dismissOutside);
      document.removeEventListener('focusin', dismissOutside);
      document.removeEventListener('keydown', dismissEscape);
    };
  }, [open]);

  useEffect(() => { if (open && environmentsLoading) close(); }, [open, environmentsLoading]);
  useEffect(() => {
    if (open) document.getElementById(optionId(highlightedIndex))?.scrollIntoView({ block: 'nearest' });
  }, [open, highlightedIndex]);

  const onKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === 'Escape' && open) { event.preventDefault(); event.stopPropagation(); close(true); return; }
    if (event.key === 'Tab') { if (open) close(); return; }
    if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
      event.preventDefault();
      if (event.key === 'Home' || event.key === 'End') {
        setHighlightedId(choices[event.key === 'Home' ? 0 : choices.length - 1].id); setOpen(true);
      } else if (!open) show();
      else setHighlightedId(choices[Math.max(0, Math.min(choices.length - 1, highlightedIndex + (event.key === 'ArrowDown' ? 1 : -1)))].id);
      return;
    }
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      if (open) choose(choices[highlightedIndex].id); else show();
      return;
    }
    if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
      event.preventDefault();
      const now = Date.now();
      const value = (now - typed.current.at < 650 ? typed.current.value : '') + event.key.toLocaleLowerCase();
      typed.current = { value, at: now };
      const query = [...value].every((character) => character === value[0]) ? value[0] : value;
      const start = open ? highlightedIndex : choices.indexOf(selected);
      const next = query.length === 1 ? 1 : 0;
      const offset = choices.findIndex((_, index) => choices[(start + index + next) % choices.length].name.toLocaleLowerCase().startsWith(query));
      if (offset >= 0) {
        setHighlightedId(choices[(start + offset + next) % choices.length].id);
        setOpen(true);
      }
    }
  };

  return <>
    <div className="flex min-w-0 items-center gap-1.5">
      <span className="hidden text-label-sm font-semibold text-ink-secondary xl:inline">NEO</span>
      <ActionButton ref={trigger} role="combobox" aria-label="Workspace environment" aria-haspopup="listbox"
        label={selected.name} icon={<Layers2 />} tone="ghost" loading={environmentsLoading} aria-describedby={`${popupId}-selected`}
        labelAdornment={selected.disabled ? <span className="ml-1.5 rounded bg-state-gray-soft px-1.5 py-0.5 text-[10px] font-medium leading-4 text-ink-muted">Disabled</span> : undefined}
        trailingIcon={!environmentsLoading && <ChevronDown size={13} className={`transition-transform duration-150 motion-reduce:transition-none ${open ? 'rotate-180' : ''}`} />}
        aria-expanded={open} aria-controls={open ? popupId : undefined} aria-activedescendant={open ? optionId(highlightedIndex) : undefined}
        aria-busy={environmentsLoading} disabled={environmentsLoading} onKeyDown={onKeyDown} onClick={() => open ? close() : show()}
        title={environmentsLoading ? 'Loading environments…' : `${selected.name}${selected.disabled ? ' · disabled' : ''}`}
        className={`max-w-40 sm:max-w-56 ${open ? 'border-surface-border bg-state-gray-soft text-ink-primary' : ''}`} />
      <span id={`${popupId}-selected`} className="sr-only">Current environment: {selected.name}{selected.disabled ? ' · disabled' : ''}</span>
    </div>
    {typeof document !== 'undefined' && createPortal(<AnimatePresence>{open && <AnimatedDiv ref={popup}
      id={popupId} role="listbox" aria-label="Workspace environments" className="fixed z-[70] flex flex-col overflow-hidden rounded-xl border border-surface-border bg-surface text-ink-primary shadow-lg"
      style={position}>
      <div className="flex shrink-0 items-center gap-2 border-b border-surface-border px-3 py-2.5 text-metadata font-medium text-ink-muted"><Layers2 size={14} aria-hidden="true" />NEO environments</div>
      <div className="min-h-0 overflow-y-auto p-1.5">
        {choices.map((choice, index) => <div key={choice.id} id={optionId(index)} role="option" aria-selected={choice.id === environmentId}
          onClick={() => choose(choice.id)} onPointerMove={(event) => { if (event.pointerType !== 'touch') setHighlightedId(choice.id); }}
          className={`flex min-h-9 cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2 text-label-sm ${index === highlightedIndex ? 'bg-state-gray-soft' : 'hover:bg-canvas'} ${choice.id === environmentId ? 'font-semibold text-ink-primary' : 'text-ink-secondary'}`}>
          <span className="min-w-0 flex-1 break-words">{choice.name}</span>
          {choice.disabled && <span className="shrink-0 rounded-md border border-surface-border px-1.5 py-0.5 text-[10px] font-normal leading-4 text-ink-muted">Disabled</span>}
          <span className="flex w-4 shrink-0 justify-center">{choice.id === environmentId && <Check size={14} aria-hidden="true" />}</span>
        </div>)}
      </div>
    </AnimatedDiv>}</AnimatePresence>, document.body)}
  </>;
}
