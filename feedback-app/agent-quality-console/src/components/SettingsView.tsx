import React, { useId, useRef, useState } from 'react';
import { AgentEnvironmentConfig, AuthUser } from '../api/feedbackApi';
import { AccessManagementView } from './AccessManagementView';
import { EnvironmentSettingsView } from './EnvironmentSettingsView';

export function SettingsView({ environments, loading, onRefresh, currentUser, googleAuthenticated }: {
  environments: AgentEnvironmentConfig[]; loading: boolean; onRefresh: () => Promise<void>; currentUser: AuthUser; googleAuthenticated: boolean;
}) {
  const id = useId();
  const [tab, setTab] = useState(0);
  const [accessVisited, setAccessVisited] = useState(false);
  const buttons = useRef<Array<HTMLButtonElement | null>>([]);
  const select = (index: number) => { setTab(index); if (index === 1) setAccessVisited(true); };
  return <div className="space-y-5"><header><h1 className="font-headline-lg">Settings</h1><p className="mt-1 text-body-sm text-ink-secondary">Manage NEO connections and who can use this workspace.</p></header>
    <div role="tablist" aria-label="Settings sections" className="flex gap-2 border-b border-surface-border pb-2">{['Environments', 'People & access'].map((label, index) => <button key={label} ref={(button) => { buttons.current[index] = button; }} type="button" role="tab" id={`${id}-tab-${index}`} aria-controls={`${id}-panel-${index}`} aria-selected={tab === index} tabIndex={tab === index ? 0 : -1} onClick={() => select(index)} onKeyDown={(event) => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault(); const next = event.key === 'Home' ? 0 : event.key === 'End' ? 1 : 1 - index; select(next); buttons.current[next]?.focus();
    }} className={`rounded-lg px-3 py-2 text-label-sm outline-none focus-visible:ring-2 focus-visible:ring-primary ${tab === index ? 'bg-state-gray-soft font-semibold text-ink-primary' : 'text-ink-secondary hover:bg-state-gray-soft'}`}>{label}</button>)}</div>
    <section role="tabpanel" id={`${id}-panel-0`} aria-labelledby={`${id}-tab-0`} hidden={tab !== 0}><EnvironmentSettingsView environments={environments} loading={loading} onRefresh={onRefresh} embedded /></section>
    <section role="tabpanel" id={`${id}-panel-1`} aria-labelledby={`${id}-tab-1`} hidden={tab !== 1}>{accessVisited && <AccessManagementView currentUser={currentUser} enabled={googleAuthenticated && currentUser.role === 'reviewer' && !currentUser.demoMode} />}</section>
  </div>;
}
