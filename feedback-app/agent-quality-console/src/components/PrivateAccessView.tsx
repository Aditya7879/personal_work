import React from 'react';

export const PrivateAccessView: React.FC<{ error: string | null; onConnect: () => void; managedBrowserSignIn?: boolean }> = ({ error, onConnect, managedBrowserSignIn = false }) => <main className="flex min-h-screen items-center justify-center bg-canvas p-6 text-ink-primary">
  <section className="w-full max-w-lg space-y-4 rounded-xl border border-surface-border bg-surface p-6">
    <h1 className="font-headline-md">{managedBrowserSignIn ? 'NEO feedback access' : 'Private NEO feedback preview'}</h1>
    {managedBrowserSignIn ? <><p className="text-body-sm text-ink-secondary">Google sign-in verifies your identity. A reviewer must also give your company email an active application grant in Settings → People &amp; access.</p><p className="text-metadata text-ink-muted">If access was just granted, allow up to 30 seconds, then check again. No local proxy or cloud console access is needed.</p></> : <><p className="text-body-sm text-ink-secondary">Both cloud services require Google IAM authentication. Open this app through the authenticated loopback proxy; your verified Google identity must also have an explicit application grant.</p><p className="text-metadata text-ink-muted">Run <code>python3 deploy/proxy.py</code> from the feedback-app directory. There is no mock identity picker or public sign-in in this deployment.</p></>}
    {error && <p role="alert" className="rounded-lg border border-surface-border bg-canvas p-3 text-body-sm text-ink-secondary">{error}</p>}
    <div className="flex flex-wrap gap-3"><button type="button" onClick={onConnect} className="rounded-lg bg-primary-container px-4 py-2 text-label-sm font-semibold text-on-primary">{managedBrowserSignIn ? 'Check my access again' : 'Connect through private proxy'}</button>{managedBrowserSignIn && <a href="/?gcp-iap-mode=CLEAR_LOGIN_COOKIE" className="rounded-lg border border-surface-border px-4 py-2 text-label-sm">Switch Google account</a>}</div>
  </section>
</main>;
