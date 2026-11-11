import React, { useEffect, useState } from 'react';
import { AuthUser } from '../api/feedbackApi';
import { DemoUserSwitch } from './DemoUserSwitch';
import { EnvironmentSwitcher, EnvironmentSwitcherProps } from './EnvironmentSwitcher';
import { Bell, MessageSquarePlus, Moon, Sun } from 'lucide-react';
import { ActionButton } from './ActionButton';

interface HeaderProps extends EnvironmentSwitcherProps {
  onSearch?: (query: string) => void;
  searchQuery?: string;
  onOpenGiveFeedback?: () => void;
  currentUser?: AuthUser;
  onSignOut?: () => void;
  demoMode?: boolean;
  signOutLabel?: string;
}

export const Header: React.FC<HeaderProps> = ({
  onSearch,
  searchQuery = '',
  onOpenGiveFeedback,
  currentUser,
  onSignOut,
  demoMode = false,
  signOutLabel = 'Sign out',
  ...environmentProps
}) => {
  const [showNotifications, setShowNotifications] = useState(false);
  const [showUserMenu, setShowUserMenu] = useState(false);
  const [isDarkMode, setIsDarkMode] = useState(() => document.documentElement.classList.contains('dark'));

  useEffect(() => {
    const root = document.documentElement;
    root.classList.toggle('dark', isDarkMode);
    root.style.colorScheme = isDarkMode ? 'dark' : 'light';
    try {
      localStorage.setItem('agent-quality-theme', isDarkMode ? 'dark' : 'light');
    } catch {
      // The theme remains active for this session if storage is unavailable.
    }
  }, [isDarkMode]);

  return (
    <header className="app-header fixed top-0 left-0 right-0 h-14 bg-surface border-b border-surface-border z-40 flex items-center justify-between gap-3 px-4 sm:px-6">
      {/* Brand & Agent Selector */}
      <div className="flex min-w-0 items-center gap-3">
        <div className="flex items-center gap-space-sm cursor-pointer select-none">
          <span aria-hidden="true" className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary-container text-on-primary">
            <svg viewBox="0 0 32 32" className="h-6 w-6" fill="none">
              <rect x="6.5" y="6.5" width="19" height="19" rx="5" stroke="currentColor" strokeWidth="1.8" opacity="0.9" />
              <path d="M10 20.5 14 16l3 2.5 5-7" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              <circle cx="22" cy="11.5" r="1.4" fill="currentColor" />
            </svg>
          </span>
          <span className="hidden whitespace-nowrap font-title-md text-ink-primary tracking-tight font-semibold xl:inline">
            Agent Quality Console
          </span>
        </div>

        <span className="hidden text-outline-variant select-none xl:inline">/</span>

        <EnvironmentSwitcher {...environmentProps} />
      </div>

      {/* Global Search */}
      <div className="hidden min-w-0 flex-1 max-w-lg mx-3 md:block">
        <div className="relative flex items-center w-full">
          <span className="material-symbols-outlined absolute left-space-sm text-ink-muted text-[18px]">search</span>
          <input
            className="w-full h-9 pl-8 pr-14 bg-state-gray-soft/60 border border-surface-border rounded-lg text-body-sm font-body-sm text-ink-primary placeholder:text-ink-muted focus:bg-surface focus:outline-none focus:border-primary-container transition-all"
            placeholder="Search feedback, runs, claims, citations..."
            type="text"
            value={searchQuery}
            onChange={(e) => onSearch?.(e.target.value)}
          />
          <div className="absolute right-space-sm flex items-center gap-0.5 px-1.5 py-0.5 bg-surface rounded border border-surface-border text-code-xs font-code-xs text-ink-muted select-none">
            <span className="text-[10px]">⌘</span>
            <span>K</span>
          </div>
        </div>
      </div>

      {/* Actions & Profile */}
      <div className="flex shrink-0 items-center gap-2 sm:gap-3">
        {demoMode && onSignOut && <DemoUserSwitch onClick={onSignOut} />}
        {/* Quick New Feedback Action */}
        {onOpenGiveFeedback && (
          <ActionButton
            label="Feedback" icon={<MessageSquarePlus />} tone="soft" containerClassName="hidden md:inline-flex"
            onClick={onOpenGiveFeedback}
            title="Log new agent answer feedback"
          />
        )}

        <ActionButton
          label={isDarkMode ? 'Light mode' : 'Dark mode'} icon={isDarkMode ? <Sun /> : <Moon />} tone="ghost"
          aria-label={isDarkMode ? 'Switch to light mode' : 'Switch to dark mode'}
          aria-pressed={isDarkMode}
          title={isDarkMode ? 'Switch to light mode' : 'Switch to dark mode'}
          onClick={() => setIsDarkMode((current) => !current)}
        />

        {/* Notifications */}
        <div className="relative hidden sm:block">
          <ActionButton label="Updates" icon={<Bell />} tone="ghost" aria-expanded={showNotifications}
            aria-label="Notifications"
            onClick={() => setShowNotifications(!showNotifications)}
          />

          {showNotifications && (
            <div className="absolute right-0 mt-2 w-80 bg-surface rounded-xl shadow-xl border border-surface-border p-space-md z-50">
              <div className="flex items-center justify-between pb-2 border-b border-surface-border">
                <span className="font-title-md text-title-md text-ink-primary font-semibold">Notifications</span>
                <span className="font-metadata text-metadata text-primary cursor-pointer hover:underline">Mark all read</span>
              </div>
              <div className="pt-3 text-body-sm text-ink-muted">No live notifications yet.</div>
            </div>
          )}
        </div>

        <div className="hidden h-5 w-px bg-surface-border sm:block"></div>

        {/* User Profile */}
        <div className="relative">
          <button
            type="button"
            aria-label="Account menu"
            aria-expanded={showUserMenu}
            onClick={() => setShowUserMenu(!showUserMenu)}
            className="flex items-center gap-space-sm pl-space-xs cursor-pointer group"
          >
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary-container font-label-sm font-semibold text-on-primary">{(currentUser?.displayName || 'Reviewer').split(/\s+/).map((part) => part[0]).join('').slice(0, 2).toUpperCase()}</div>
            <div className="hidden xl:flex flex-col text-left">
              <span className="font-label-sm text-label-sm text-ink-primary group-hover:text-primary transition-colors font-medium">
                  {currentUser?.displayName || 'Reviewer'}
              </span>
              <span className="font-metadata text-metadata text-ink-muted">
                  {currentUser?.email || 'Development account'}
              </span>
            </div>
            <span className="material-symbols-outlined text-[16px] text-ink-muted group-hover:text-ink-primary transition-colors">
              expand_more
            </span>
          </button>

          {showUserMenu && (
            <div className="absolute right-0 mt-2 w-56 bg-surface rounded-xl shadow-lg border border-surface-border py-1 z-50">
              <div className="px-3 py-2 border-b border-surface-border">
                <span className="font-label-sm font-semibold text-ink-primary block">{currentUser?.displayName || 'Reviewer'}</span>
                <span className="font-metadata text-ink-muted block">{currentUser?.email || 'Development account'}</span>
              </div>
              <p className="px-3 py-2 text-metadata text-ink-muted">{currentUser?.demoMode === 'demo_admin' ? 'Isolated demo · simulated Reviewer persona' : demoMode ? currentUser?.demoMode === 'private_demo' ? 'Private demo · reviewer account' : 'Local demo · mock reviewer account' : 'Google identity · verified access grant'}</p>
              {onSignOut && <button type="button" onClick={onSignOut} className="w-full px-3 py-2 text-left text-label-sm font-semibold text-ink-secondary hover:bg-state-gray-soft">{signOutLabel}</button>}
            </div>
          )}
        </div>
      </div>
    </header>
  );
};
