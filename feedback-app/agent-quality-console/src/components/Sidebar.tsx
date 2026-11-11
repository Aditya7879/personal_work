import React from 'react';
import { ViewPath } from '../types';

interface SidebarProps {
  activeView: ViewPath;
  onNavigate: (view: ViewPath) => void;
  feedbackCount?: number;
  role?: 'reporter' | 'reviewer';
}

export const Sidebar: React.FC<SidebarProps> = ({
  activeView,
  onNavigate,
  feedbackCount = 0,
  role = 'reviewer',
}) => {
  const reviewerItems = [
    { path: 'overview' as ViewPath, label: 'Overview', icon: 'dashboard' },
    {
      path: 'feedback-inbox' as ViewPath,
      label: 'Feedback inbox',
      icon: 'inbox',
      badge: feedbackCount
    },
    { path: 'triage-queue' as ViewPath, label: 'Triage queue', icon: 'filter_list' },
    { path: 'golden-datasets' as ViewPath, label: 'Golden datasets', icon: 'database' },
    { path: 'evaluation-runs' as ViewPath, label: 'Evaluation runs', icon: 'play_circle' },
    { path: 'release-comparisons' as ViewPath, label: 'Release comparisons', icon: 'compare_arrows' }
  ];
  const navItems = role === 'reporter'
    ? [{ path: 'my-feedback' as ViewPath, label: 'My feedback', icon: 'assignment' }]
    : reviewerItems;

  return (<>
    <nav aria-label="Mobile workspace" className="fixed inset-x-0 top-14 z-30 flex h-12 items-center gap-1 overflow-x-auto border-b border-surface-border bg-surface px-3 sm:hidden">
      {[...navItems, ...(role === 'reviewer' ? [{ path: 'settings' as ViewPath, label: 'Settings', icon: 'settings' }] : [])].map((item) => <button key={item.path} type="button" onClick={() => onNavigate(item.path)} aria-current={activeView === item.path ? 'page' : undefined} className={`shrink-0 rounded-md px-3 py-2 text-label-sm outline-none focus-visible:ring-2 focus-visible:ring-primary ${activeView === item.path || item.path === 'feedback-inbox' && activeView === 'feedback-detail' ? 'bg-state-gray-soft font-semibold text-ink-primary' : 'text-ink-secondary'}`}>{item.label}</button>)}
    </nav>
    <aside aria-label="Workspace navigation" className="fixed left-0 top-14 bottom-0 w-60 bg-surface border-r border-surface-border z-30 hidden flex-col justify-between py-space-md select-none sm:flex">
      {/* Primary Workspace Nav */}
      <div className="flex flex-col gap-space-xs px-space-sm">
        <div className="px-space-sm py-1">
          <span className="font-metadata text-metadata uppercase tracking-wider text-ink-muted font-semibold">
            {role === 'reporter' ? 'Feedback' : 'Quality Workspace'}
          </span>
        </div>

        <nav className="flex flex-col gap-0.5">
          {navItems.map((item) => {
            const isActive = activeView === item.path || (item.path === 'feedback-inbox' && activeView === 'feedback-detail');
            return (
              <button
                key={item.path}
                 type="button"
                 aria-label={item.label}
                 onClick={() => onNavigate(item.path)}
                 aria-current={isActive ? 'page' : undefined}
                className={`flex items-center justify-between px-space-sm py-2 rounded text-left transition-colors cursor-pointer ${
                  isActive
                    ? 'bg-indigo-soft text-primary-container font-semibold border-l-2 border-primary-container'
                    : 'text-ink-secondary hover:bg-state-gray-soft hover:text-ink-primary'
                }`}
              >
                <div className="flex items-center gap-space-sm">
                  <span aria-hidden="true" className={`material-symbols-outlined text-[20px] ${isActive ? 'text-primary-container' : 'text-ink-muted'}`}>
                    {item.icon}
                  </span>
                  <span className="font-label-md text-label-md">{item.label}</span>
                </div>

                {item.badge !== undefined && (
                  <span className="px-1.5 py-0.5 rounded-md bg-state-gray-soft text-ink-secondary font-label-sm font-medium tabular-nums">
                    {item.badge}
                  </span>
                )}
              </button>
            );
          })}
        </nav>
      </div>

      {/* Bottom Settings & Build Info */}
      {role === 'reviewer' && <div className="px-space-sm border-t border-surface-border pt-space-sm">
        {role === 'reviewer' && <nav className="flex flex-col gap-0.5">
          <button
            type="button"
             onClick={() => onNavigate('settings')}
             aria-label="Settings"
             aria-current={activeView === 'settings' ? 'page' : undefined}
            className={`flex items-center justify-between px-space-sm py-2 rounded text-left transition-colors cursor-pointer ${
              activeView === 'settings'
                ? 'bg-indigo-soft text-primary-container font-semibold border-l-2 border-primary-container'
                : 'text-ink-secondary hover:bg-state-gray-soft hover:text-ink-primary'
            }`}
          >
            <div className="flex items-center gap-space-sm">
              <span className={`material-symbols-outlined text-[20px] ${activeView === 'settings' ? 'text-primary-container' : 'text-ink-muted'}`}>
                settings
              </span>
              <span className="font-label-md text-label-md">Settings</span>
            </div>
          </button>
        </nav>}

        {/* Build Badge */}
        <div className="mt-space-sm px-space-sm py-space-xs rounded bg-state-gray-soft/60 flex items-center justify-between">
          <div className="flex flex-col">
            <span className="font-metadata text-metadata text-ink-muted">Agent Build</span>
            <span className="font-label-sm text-ink-primary">local-dev</span>
          </div>
          <span className="w-2 h-2 rounded-full bg-evidence-teal animate-pulse" title="Operational"></span>
        </div>
      </div>}
    </aside></>
  );
};
