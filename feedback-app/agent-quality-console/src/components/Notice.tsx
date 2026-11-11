import React from 'react';
import { createPortal } from 'react-dom';
import { AnimatePresence } from 'motion/react';
import { AlertCircle, AlertTriangle, Info, X } from 'lucide-react';
import { AnimatedSection } from './UiMotion';

interface NoticeProps {
  title: string;
  message: string;
  tone?: 'error' | 'warning' | 'info';
  onDismiss: () => void;
  actionLabel?: string;
  onAction?: () => void;
}

export const Notice: React.FC<NoticeProps> = ({ title, message, tone = 'error', onDismiss, actionLabel, onAction }) => {
  const Icon = tone === 'warning' ? AlertTriangle : tone === 'info' ? Info : AlertCircle;
  const color = tone === 'warning' ? 'bg-review-soft text-review-amber' : tone === 'info' ? 'bg-indigo-soft text-primary' : 'bg-issue-soft text-issue-red';
  return <AnimatedSection surface="notice" layout="position" role={tone === 'info' ? 'status' : 'alert'} aria-label={title} aria-atomic="true" className="pointer-events-auto flex items-start gap-3 rounded-2xl border border-surface-border bg-surface p-4 text-left shadow-[0_12px_40px_-12px_rgba(16,24,40,0.28)]">
    <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${color}`}><Icon size={18} aria-hidden="true" /></span>
    <div className="min-w-0 flex-1"><h2 className="font-label-md font-semibold text-ink-primary">{title}</h2><p className="mt-1 break-words text-body-sm leading-relaxed text-ink-secondary">{message}</p>{actionLabel && onAction && <button type="button" onClick={onAction} className="mt-2.5 rounded-md px-1 py-1 text-label-sm font-semibold text-primary outline-none hover:bg-indigo-soft focus-visible:ring-2 focus-visible:ring-primary">{actionLabel}<span aria-hidden="true" className="ml-1">→</span></button>}</div>
    <button type="button" aria-label={`Dismiss ${title.toLowerCase()}`} onClick={onDismiss} className="-mr-1 -mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-ink-muted outline-none transition-colors hover:bg-state-gray-soft hover:text-ink-primary focus-visible:ring-2 focus-visible:ring-primary"><X size={16} aria-hidden="true" /></button>
  </AnimatedSection>;
};

export const NoticeViewport: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const notices = React.Children.toArray(children).filter(Boolean);
  return createPortal(<div aria-label="Notifications" className="pointer-events-none fixed right-4 top-20 z-[80] flex w-[calc(100vw-2rem)] max-w-[400px] flex-col gap-3 sm:right-6"><AnimatePresence initial={false}>{notices}</AnimatePresence></div>, document.body);
};
