import React, { useState } from 'react';
import { MockUser } from '../api/feedbackApi';

interface MockSignInViewProps {
  users: MockUser[];
  loading: boolean;
  error: string | null;
  onSignIn: (user: MockUser) => Promise<void>;
  privateDemo?: boolean;
}

export const MockSignInView: React.FC<MockSignInViewProps> = ({ users, loading, error, onSignIn, privateDemo = false }) => {
  const [selectedEmail, setSelectedEmail] = useState('');
  const [signingIn, setSigningIn] = useState(false);
  const selected = users.find((user) => user.email === selectedEmail) || users[0];

  const signIn = async () => {
    if (!selected) return;
    setSigningIn(true);
    try {
      await onSignIn(selected);
    } finally {
      setSigningIn(false);
    }
  };

  return (
    <main className="flex min-h-screen items-center justify-center bg-canvas px-4 py-10 text-ink-primary">
      <section className="w-full max-w-lg rounded-2xl border border-surface-border bg-surface p-6 shadow-xl sm:p-8">
        <div className="flex items-center gap-3">
          <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-primary-container text-on-primary">
            <span aria-hidden="true" className="material-symbols-outlined">fact_check</span>
          </span>
          <div>
            <h1 className="font-headline-md">NEO feedback</h1>
            <p className="text-body-sm text-ink-secondary">Choose a reviewer or reporter for the demo</p>
          </div>
        </div>

        <div className="mt-6 rounded-xl border border-review-amber/30 bg-review-soft p-3 text-body-sm text-ink-secondary">
          <strong className="text-ink-primary">Demo preview:</strong> {privateDemo ? 'choose a reviewer or reporter account. This hosted demo is restricted to authorized presenters through the private connection.' : 'choose a mock reviewer or reporter account. No company sign-in is required for this local demo.'}
        </div>

        <div className="mt-6 flex flex-col gap-2" aria-label="Choose a test identity">
          {loading ? <div className="skeleton h-16 rounded-xl" /> : users.map((user) => (
            <button
              key={user.email}
              type="button"
              aria-pressed={selected.email === user.email}
              onClick={() => setSelectedEmail(user.email)}
              className={`flex items-center justify-between rounded-xl border p-3 text-left transition-colors ${
                (selectedEmail || users[0]?.email) === user.email
                  ? 'border-primary-container bg-indigo-soft/70'
                  : 'border-surface-border hover:bg-surface-container-low'
              }`}
            >
              <span className="flex min-w-0 items-center gap-3">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary-container font-label-sm font-semibold text-on-primary">
                  {user.displayName.split(/\s+/).map((part) => part[0]).join('').slice(0, 2).toUpperCase()}
                </span>
                <span className="min-w-0">
                  <span className="block truncate font-label-md text-ink-primary">{user.displayName}</span>
                  <span className="block truncate text-body-sm text-ink-muted">{user.email}</span>
                </span>
              </span>
              <span className="ml-3 shrink-0 rounded-full bg-surface px-2 py-1 text-metadata capitalize text-ink-secondary">{user.role}</span>
            </button>
          ))}
        </div>

        {error && <p className="mt-4 rounded-lg bg-issue-soft p-3 text-body-sm text-issue-red">{error}</p>}
        <button
          type="button"
          disabled={!selected || loading || signingIn}
          onClick={() => void signIn()}
          className="mt-6 flex w-full items-center justify-center gap-2 rounded-xl bg-primary-container px-4 py-3 font-label-md font-semibold text-on-primary transition hover:bg-primary disabled:cursor-not-allowed disabled:opacity-50"
        >
          {signingIn ? 'Signing in…' : 'Continue'}
          <span aria-hidden="true" className="material-symbols-outlined text-[18px]">arrow_forward</span>
        </button>
        <p className="mt-4 text-center text-metadata text-ink-muted">{privateDemo ? 'Private sandbox demo.' : 'Mock accounts are for local demos only.'} Use Switch demo user in the header to change roles.</p>
      </section>
    </main>
  );
};
