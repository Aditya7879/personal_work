import React, { useState } from 'react';

interface HeaderProps {
  onSearch?: (query: string) => void;
  searchQuery?: string;
  onOpenGiveFeedback?: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  onSearch,
  searchQuery = '',
  onOpenGiveFeedback
}) => {
  const [showAgentMenu, setShowAgentMenu] = useState(false);
  const [selectedAgent, setSelectedAgent] = useState('NEO Rules Agent');
  const [showNotifications, setShowNotifications] = useState(false);
  const [showUserMenu, setShowUserMenu] = useState(false);

  const agents = ['NEO Rules Agent'];

  return (
    <header className="fixed top-0 left-0 right-0 h-14 bg-surface border-b border-surface-border z-40 flex items-center justify-between px-space-lg">
      {/* Brand & Agent Selector */}
      <div className="flex items-center gap-space-md">
        <div className="flex items-center gap-space-sm cursor-pointer select-none">
          <img
            alt="Agent Quality Console Emblem"
            className="h-8 w-auto object-contain"
            src="https://lh3.googleusercontent.com/aida/AEtjO1Vh3UBjxq1HQ_Bh9rTR9FZW9FuJCrHMAOtJmAvffBcN_zND_W1SIlx66_NXIXqN2DCd2fRpa0XG7rMKipGFnwhCowzmU_GAqiJ35jbus_LljO5QD9k4qb1holEoQmj_5TKdlHKANR9TK1TksxRNI0rXi9fWj9rPvgSkq01pUDFYi7rglllEZzK-2gA4zrayEezKqr7HtwRtwejlNBDz00evLHLDMJO5YjnehNWIdjcO3LFBWlsjW66B-4oz"
          />
          <span className="font-title-md text-title-md text-ink-primary tracking-tight font-semibold">
            Agent Quality Console
          </span>
        </div>

        <span className="text-outline-variant select-none">/</span>

        {/* Agent Switcher Dropdown */}
        <div className="relative">
          <button
            type="button"
            onClick={() => setShowAgentMenu(!showAgentMenu)}
            className="flex items-center gap-space-xs px-space-sm py-1 bg-surface-container-low rounded border border-surface-border text-label-sm font-label-sm text-ink-secondary hover:text-ink-primary hover:border-outline-variant cursor-pointer transition-colors"
          >
            <span className="w-2 h-2 rounded-full bg-evidence-teal"></span>
            <span className="font-code-sm text-code-sm text-ink-primary font-semibold">
              {selectedAgent}
            </span>
            <span className="material-symbols-outlined text-[16px] text-ink-muted">arrow_drop_down</span>
          </button>

          {showAgentMenu && (
            <div className="absolute left-0 mt-1 w-64 bg-surface rounded-xl shadow-lg border border-surface-border py-1 z-50 animate-in fade-in zoom-in-95">
              <div className="px-3 py-1.5 text-metadata font-metadata text-ink-muted uppercase tracking-wider">
                Select Connected Agent
              </div>
              {agents.map((agent) => (
                <button
                  key={agent}
                  type="button"
                  onClick={() => {
                    setSelectedAgent(agent);
                    setShowAgentMenu(false);
                  }}
                  className={`w-full flex items-center justify-between px-3 py-2 text-left text-body-sm transition-colors ${
                    selectedAgent === agent ? 'bg-indigo-soft text-primary font-medium' : 'text-ink-primary hover:bg-state-gray-soft'
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <span className={`w-2 h-2 rounded-full ${selectedAgent === agent ? 'bg-evidence-teal' : 'bg-state-gray'}`}></span>
                    <span>{agent}</span>
                  </div>
                  {selectedAgent === agent && (
                    <span className="material-symbols-outlined text-primary text-[16px]">check</span>
                  )}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Global Search */}
      <div className="flex-1 max-w-lg mx-space-lg">
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
      <div className="flex items-center gap-space-md">
        {/* Quick New Feedback Action */}
        {onOpenGiveFeedback && (
          <button
            type="button"
            onClick={onOpenGiveFeedback}
            className="hidden md:flex items-center gap-1 px-3 py-1.5 bg-indigo-soft hover:bg-primary/10 text-primary-container rounded-lg text-label-sm font-label-sm font-medium transition-colors"
            title="Log new agent answer feedback"
          >
            <span className="material-symbols-outlined text-[16px]">rate_review</span>
            <span>Feedback</span>
          </button>
        )}

        {/* Notifications */}
        <div className="relative">
          <button
            aria-label="Notifications"
            onClick={() => setShowNotifications(!showNotifications)}
            className="relative p-1.5 rounded-lg text-ink-secondary hover:text-ink-primary hover:bg-state-gray-soft transition-colors cursor-pointer"
            type="button"
          >
            <span className="material-symbols-outlined text-[20px]">notifications</span>
          </button>

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

        <div className="h-5 w-px bg-surface-border"></div>

        {/* User Profile */}
        <div className="relative">
          <div
            onClick={() => setShowUserMenu(!showUserMenu)}
            className="flex items-center gap-space-sm pl-space-xs cursor-pointer group"
          >
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-primary-container font-code-xs font-semibold text-on-primary">LR</div>
            <div className="hidden xl:flex flex-col text-left">
              <span className="font-label-sm text-label-sm text-ink-primary group-hover:text-primary transition-colors font-medium">
                 Local reviewer
              </span>
              <span className="font-metadata text-metadata text-ink-muted">
                 Authentication not configured
              </span>
            </div>
            <span className="material-symbols-outlined text-[16px] text-ink-muted group-hover:text-ink-primary transition-colors">
              expand_more
            </span>
          </div>

          {showUserMenu && (
            <div className="absolute right-0 mt-2 w-56 bg-surface rounded-xl shadow-lg border border-surface-border py-1 z-50">
              <div className="px-3 py-2 border-b border-surface-border">
                <span className="font-label-sm font-semibold text-ink-primary block">Local reviewer</span>
                <span className="font-metadata text-ink-muted block">Identity provider not connected</span>
              </div>
              <p className="px-3 py-2 text-metadata text-ink-muted">Sign-in and reviewer roles will be connected before shared deployment.</p>
            </div>
          )}
        </div>
      </div>
    </header>
  );
};
