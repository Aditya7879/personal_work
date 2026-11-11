import React from 'react';
import { ArrowLeft, RefreshCw, UsersRound } from 'lucide-react';
import { AuthUser } from '../api/feedbackApi';
import { DemoAdminSession } from '../api/demoAdminApi';
import { ActionButton } from './ActionButton';

export function DemoAdminControls({ session, user, busy, onSwitch, onReset, onExit }: {
  session: DemoAdminSession | null; user: AuthUser; busy: boolean;
  onSwitch: () => void; onReset: () => void; onExit: () => void;
}) {
  if (!user.canSwitchDemoViews && user.demoMode !== 'demo_admin') return null;
  const active = user.demoMode === 'demo_admin';
  return <section aria-label="Demo administrator controls" className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-surface-border bg-surface p-3">
    <div className="min-w-0 flex-1"><p className="text-label-sm font-semibold">{active ? 'Demo view · sample data · simulated AI' : 'Demo Admin · Reviewer permissions'}</p>
      <p className="mt-1 break-words text-metadata text-ink-muted">{active ? <>Signed in as {session?.realUser.displayName || 'your Google account'} · Viewing as {user.displayName} ({user.role}). Live feedback is not shown.</> : 'Your real account and live workspace. Demo views use isolated fictional reports.'}</p></div>
    <div className="flex w-full flex-wrap gap-2 sm:w-auto">
      {user.canSwitchDemoViews && <ActionButton label="Switch demo view" icon={<UsersRound />} size="sm" expanded disabled={busy} onClick={onSwitch} />}
      {active && <><ActionButton label="Reset demo data" icon={<RefreshCw />} size="sm" expanded disabled={busy} onClick={onReset} />
      <ActionButton label="Exit demo" icon={<ArrowLeft />} size="sm" expanded disabled={busy} onClick={onExit} /></>}
    </div>
  </section>;
}
