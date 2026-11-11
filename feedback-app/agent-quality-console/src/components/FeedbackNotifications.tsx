import React, { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { AnimatePresence } from 'motion/react';
import { Bell, ChevronRight, RefreshCw, X } from 'lucide-react';
import { FeedbackNotification, clearReadCache, getNotifications, isAuthenticationError, readNotification } from '../api/feedbackApi';
import { AnimatedDiv } from './UiMotion';
import { ActionButton } from './ActionButton';

function notificationTime(value: string): string {
  const date = new Date(value.replace(' ', 'T'));
  return Number.isNaN(date.getTime()) ? 'Time not recorded' : new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

export const FeedbackNotifications: React.FC<{ onOpen: (feedbackId: string, environmentId?: string) => void }> = ({ onOpen }) => {
  const [items, setItems] = useState<FeedbackNotification[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [openingId, setOpeningId] = useState<string | null>(null);
  const [position, setPosition] = useState({ top: 64, left: 12, width: 384, maxHeight: 520 });
  const trigger = useRef<HTMLButtonElement>(null);
  const popup = useRef<HTMLDivElement>(null);
  const mounted = useRef(true);
  const inFlight = useRef<Promise<void> | null>(null);
  const opening = useRef<string | null>(null);
  const navigationEpoch = useRef(0);
  const readOverrides = useRef(new Map<string, string>());
  const id = useId();

  const load = useCallback((refresh = false): Promise<void> => {
    if (inFlight.current) return inFlight.current;
    if (!mounted.current) return Promise.resolve();
    setLoading(true);
    const request = getNotifications(refresh).then((values) => {
      if (!mounted.current) return;
      setItems(values.map((item) => !item.readAt && readOverrides.current.has(item.id) ? { ...item, readAt: readOverrides.current.get(item.id) } : item));
      setError(null);
    }).catch((error) => {
      if (mounted.current) setError(isAuthenticationError(error) ? 'Sign in again to load answer updates.' : error instanceof Error ? error.message : 'Could not load notifications');
    }).finally(() => {
      if (inFlight.current === request) inFlight.current = null;
      if (mounted.current) setLoading(false);
    });
    inFlight.current = request;
    return request;
  }, []);

  useEffect(() => {
    mounted.current = true;
    void load();
    const timer = window.setInterval(() => { if (document.visibilityState === 'visible') void load(); }, 30_000);
    return () => { mounted.current = false; window.clearInterval(timer); };
  }, [load]);

  const close = (restoreFocus = true) => {
    navigationEpoch.current += 1;
    setOpen(false);
    if (restoreFocus) trigger.current?.focus({ preventScroll: true });
  };

  useLayoutEffect(() => {
    if (!open) return;
    const place = () => {
      const rect = trigger.current?.getBoundingClientRect();
      if (!rect || !rect.width) { setOpen(false); return; }
      const margin = 12;
      const width = Math.min(384, window.innerWidth - margin * 2);
      const top = Math.max(64, rect.bottom + 8);
      const left = Math.max(margin, Math.min(rect.right - width, window.innerWidth - width - margin));
      const maxHeight = Math.max(0, Math.min(520, window.innerHeight - top - margin));
      setPosition((old) => old.top === top && old.left === left && old.width === width && old.maxHeight === maxHeight ? old : { top, left, width, maxHeight });
    };
    place();
    const observer = new ResizeObserver(place);
    if (trigger.current) observer.observe(trigger.current);
    window.addEventListener('resize', place);
    return () => { observer.disconnect(); window.removeEventListener('resize', place); };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    popup.current?.focus({ preventScroll: true });
    const outside = (target: EventTarget | null) => target instanceof Node && !trigger.current?.contains(target) && !popup.current?.contains(target);
    const dismissOutside = (event: Event) => { if (outside(event.target)) close(false); };
    const dismissEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault(); event.stopPropagation(); close();
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

  const openUpdate = async (item: FeedbackNotification) => {
    if (opening.current) return;
    const epoch = navigationEpoch.current;
    opening.current = item.id; setOpeningId(item.id); setError(null);
    try {
      if (!item.readAt && !readOverrides.current.has(item.id)) await readNotification(item.id);
      if (!mounted.current) return;
      const readAt = item.readAt || new Date().toISOString();
      readOverrides.current.set(item.id, readAt);
      setItems((values) => values.map((value) => value.id === item.id ? { ...value, readAt } : value));
      clearReadCache();
      if (epoch !== navigationEpoch.current) return;
      close(false); onOpen(item.feedbackId, item.environmentId || undefined);
    } catch (error) {
      if (mounted.current) setError(isAuthenticationError(error) ? 'Sign in again to open this update.' : error instanceof Error ? error.message : 'Could not open this notification');
    } finally {
      opening.current = null;
      if (mounted.current) setOpeningId(null);
    }
  };

  const unread = items.filter((item) => !item.readAt);
  const ordered = [...items].sort((a, b) => Number(Boolean(a.readAt)) - Number(Boolean(b.readAt)) || b.createdAt.localeCompare(a.createdAt));
  return <>
    <ActionButton ref={trigger} label="Your answer updates" aria-label="Notifications" icon={<Bell />} tone="ghost" aria-describedby={`${id}-count`} aria-haspopup="dialog" aria-expanded={open} aria-controls={open ? `${id}-popup` : undefined} title={error ? 'Answer updates unavailable' : loading && !items.length ? 'Loading answer updates…' : `${unread.length} unread answer updates`} onClick={() => { if (open) close(); else { setOpen(true); void load(true); } }}>
      {!!unread.length && <span aria-hidden="true" className="absolute -right-1 -top-0.5 flex h-[18px] min-w-[18px] items-center justify-center rounded-full border-2 border-surface bg-primary-container px-1 text-[10px] font-semibold leading-none text-on-primary">{unread.length > 99 ? '99+' : unread.length}</span>}
    </ActionButton>
    <span id={`${id}-count`} role="status" className="sr-only">{loading && !items.length ? 'Loading answer updates' : error && !items.length ? 'Answer updates unavailable' : `${unread.length} unread answer updates`}</span>
    {createPortal(<AnimatePresence>{open && <AnimatedDiv key="updates" ref={popup} id={`${id}-popup`} role="dialog" aria-modal="false" aria-labelledby={`${id}-title`} tabIndex={-1} aria-busy={loading} className="fixed z-[70] flex flex-col overflow-hidden rounded-xl border border-surface-border bg-surface text-ink-primary shadow-xl outline-none" style={{ ...position, transformOrigin: 'top right' }}>
      <div className="flex shrink-0 items-start justify-between gap-3 border-b border-surface-border px-4 py-3">
        <div><h2 id={`${id}-title`} className="font-title-md">Answer updates</h2><p className="mt-0.5 text-metadata text-ink-muted">{loading && !items.length ? 'Loading…' : unread.length ? `${unread.length} unread` : 'No unread updates'}</p></div>
        <div className="flex items-center gap-1"><ActionButton label="Refresh answer updates" icon={<RefreshCw />} tone="ghost" size="sm" loading={loading} disabled={loading || Boolean(openingId)} onClick={() => void load(true)} /><button type="button" aria-label="Close answer updates" onClick={() => close()} className="rounded-md p-1.5 text-ink-muted outline-none hover:bg-canvas focus-visible:ring-2 focus-visible:ring-primary"><X size={17} aria-hidden="true" /></button></div>
      </div>
      {error && <p role="alert" className="shrink-0 border-b border-surface-border px-4 py-3 text-body-sm text-issue-red">{error}</p>}
      <div className="min-h-0 max-h-96 overflow-y-auto overscroll-contain p-2">
        {!items.length ? <div className="px-3 py-6 text-center"><Bell size={22} aria-hidden="true" className="mx-auto text-ink-muted" /><p className="mt-3 text-body-sm font-medium text-ink-secondary">{loading ? 'Loading answer updates…' : error ? 'Updates could not be loaded' : 'No answer updates yet'}</p><p className="mt-1 text-metadata text-ink-muted">New results will appear here automatically.</p></div> : <ul className="space-y-1">{ordered.map((item) => <li key={item.id}><button type="button" data-notification-id={item.id} disabled={Boolean(openingId)} aria-label={`View result for feedback ${item.feedbackId}`} onClick={() => void openUpdate(item)} className={`flex w-full items-start gap-2.5 rounded-lg px-3 py-3 text-left outline-none transition-colors hover:bg-state-gray-soft focus-visible:ring-2 focus-visible:ring-primary disabled:opacity-60 ${item.readAt ? 'bg-surface' : 'bg-canvas'}`}>
          <span aria-hidden="true" className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${item.readAt ? 'bg-transparent' : 'bg-primary-container'}`} />
          <span className="min-w-0 flex-1"><span className="block break-words text-body-sm text-ink-secondary [overflow-wrap:anywhere]">{item.message}</span><span className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-metadata text-ink-muted"><span className="font-code-xs">{item.feedbackId}</span><span>{notificationTime(item.createdAt)}</span>{item.readAt && <span>Read</span>}</span><span className="mt-2 block text-label-sm font-medium text-ink-primary">{openingId === item.id ? 'Opening…' : 'View result'}</span></span><ChevronRight size={15} aria-hidden="true" className="mt-1 shrink-0 text-ink-muted" />
        </button></li>)}</ul>}
      </div>
    </AnimatedDiv>}</AnimatePresence>, document.body)}
  </>;
};
