import React from 'react';
import { AuthUser } from '../api/feedbackApi';
import { FeedbackNotifications } from './FeedbackNotifications';
import { ClipboardCheck, LogOut, Plus } from 'lucide-react';
import { DemoUserSwitch } from './DemoUserSwitch';
import { EnvironmentSwitcher, EnvironmentSwitcherProps } from './EnvironmentSwitcher';
import { ActionButton } from './ActionButton';

export const PublicHeader: React.FC<EnvironmentSwitcherProps & { user: AuthUser; onSignOut: () => void; onNewFeedback: () => void; onOpenFeedback: (feedbackId: string, environmentId?: string) => void; demoMode?: boolean; signOutLabel?: string }> = ({ user, onSignOut, onNewFeedback, onOpenFeedback, demoMode = false, signOutLabel = 'Sign out', ...environmentProps }) => (
  <header className="app-header fixed left-0 right-0 top-0 z-40 flex h-14 items-center justify-between border-b border-surface-border bg-surface px-4 sm:px-6">
    <div className="flex min-w-0 items-center gap-3">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary-container text-on-primary">
        <ClipboardCheck size={19} aria-hidden="true" />
      </span>
      <span className="hidden truncate font-title-md font-semibold text-ink-primary lg:inline">NEO feedback</span>
      <EnvironmentSwitcher {...environmentProps} />
    </div>
    <div className="flex items-center gap-2 sm:gap-4">
      <button type="button" aria-label="Submit feedback" onClick={onNewFeedback} className="inline-flex items-center gap-1 rounded-lg bg-primary-container px-3 py-2 text-label-sm font-semibold text-on-primary hover:bg-primary">
        <Plus size={17} aria-hidden="true" /><span className="sm:hidden">Submit</span><span className="hidden sm:inline">Submit feedback</span>
      </button>
      <FeedbackNotifications key={`${user.email}:${user.cacheScope || ''}`} onOpen={onOpenFeedback} />
      <div className="hidden max-w-48 text-right lg:block">
        <p className="truncate text-label-sm font-semibold text-ink-primary">{user.displayName}</p>
        <p className="truncate text-metadata text-ink-muted">{user.demoMode === 'demo_admin' ? 'Isolated demo · Reporter persona' : demoMode ? user.demoMode === 'private_demo' ? 'Private demo · reporter' : 'Local demo · reporter' : 'Reporter'}</p>
      </div>
      {demoMode ? <DemoUserSwitch onClick={onSignOut} /> : <ActionButton label={signOutLabel} icon={<LogOut />} tone="ghost" onClick={onSignOut} title={`${signOutLabel}: ${user.email}`} />}
    </div>
  </header>
);
