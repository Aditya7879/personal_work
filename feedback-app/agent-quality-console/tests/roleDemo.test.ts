import assert from 'node:assert/strict';
import { once } from 'node:events';
import { mkdtemp, rm, writeFile, readFile } from 'node:fs/promises';
import { join } from 'node:path';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createApp } from '../server.mjs';
import { DemoAdminControls } from '../src/components/DemoAdminControls';
import { AccessGrantForm } from '../src/components/AccessManagementView';
import { getDemoAdminSession, logoutDemoAdmin, selectDemoPersona } from '../src/api/demoAdminApi';
import { ApiError, clearAuthSession, createMyFeedback, listMyFeedback, saveAuthSession, type AuthUser } from '../src/api/feedbackApi';

const audience = '/projects/411502743425/locations/europe-west1/services/neo-feedback-ui';
const origin = 'https://feedback-ui.example.test';
const assertion = 'complete.signed.assertion';
const cookie = `neo_role_demo=e30.${'A'.repeat(43)}`;
const iap = { 'X-Goog-IAP-JWT-Assertion': assertion };
const actions = { ...iap, Origin: origin, 'Content-Type': 'application/json', 'X-Feedback-CSRF': '1', 'X-Requested-With': 'XMLHttpRequest' };
const real: AuthUser = { email: 'admin@company.example', displayName: 'Real Admin', role: 'reviewer', accessRole: 'demo_admin', canSwitchDemoViews: true, cacheScope: 'real-scope' };
const sample: AuthUser = { email: 'alex.requester@example.test', displayName: 'Alex Reporter', role: 'reporter', accessRole: 'demo_admin', canSwitchDemoViews: true, demoMode: 'demo_admin', cacheScope: 'demo-scope' };

async function server(options: { fetchImpl?: typeof fetch; getWorkloadToken?: () => Promise<string>; roleDemoEnabled?: boolean }, run: (url: string) => Promise<void>) {
  const directory = await mkdtemp('/tmp/opencode/feedback-role-demo-proxy-test-');
  await writeFile(join(directory, 'index.html'), '<html>IAP-protected application</html>');
  const app = createApp({ backendUrl: 'https://neo-feedback-api-fixture.run.app', frontendOrigin: origin, distDir: directory,
    iapAudience: audience, verifyIapAssertion: async (value: string) => { if (value !== assertion) throw new Error('Invalid IAP'); },
    roleDemoEnabled: true, getWorkloadToken: async () => 'runtime.workload.token', fetchImpl: async () => Response.json({}), ...options });
  const instance = app.listen(0, '127.0.0.1'); await once(instance, 'listening');
  const address = instance.address(); assert.ok(address && typeof address !== 'string');
  try { await run(`http://127.0.0.1:${address.port}`); }
  finally { instance.closeAllConnections(); await new Promise<void>(resolve => instance.close(() => resolve())); await rm(directory, { recursive: true, force: true }); }
}

test('role-demo feature requires existing IAP and explicitly rejects the obsolete public password mode', () => {
  const options = { backendUrl: 'https://neo-feedback-api-fixture.run.app', frontendOrigin: origin };
  assert.throws(() => createApp({ ...options, roleDemoEnabled: true }), /IAP-authenticated/);
  assert.throws(() => createApp({ ...options, demoAdmin: true }), /retired/);
});

test('demo controllers and data are never an anonymous or forged-IAP login bypass', async () => {
  let calls = 0;
  await server({ getWorkloadToken: async () => { calls++; return 'runtime'; } }, async url => {
    for (const path of ['/', '/api/demo-admin/session', '/api/feedback']) {
      assert.equal((await fetch(url + path, { headers: { Cookie: cookie, 'X-Feedback-Demo-View': '1' } })).status, 401);
      assert.equal((await fetch(url + path, { headers: { 'X-Goog-IAP-JWT-Assertion': 'forged', Cookie: cookie } })).status, 401);
    }
  });
  assert.equal(calls, 0);
});

test('only the single signed role-demo cookie and marker follow verified IAP; caller roles and other cookies do not', async () => {
  let seen: Headers | undefined;
  await server({ fetchImpl: async (_url, init) => { seen = new Headers(init?.headers); return Response.json({}); } }, async url => {
    const response = await fetch(url + '/api/my/feedback', { headers: { ...iap, Cookie: `iap=private; neo_demo_admin_session=obsolete; ${cookie}`,
      'X-Feedback-Demo-View': '1', 'X-Feedback-Role': 'reviewer', 'X-Feedback-Demo-Authorization': 'Bearer forged',
      Authorization: 'Bearer forged.user.token', 'X-Feedback-User-Authorization': 'Bearer forged.user.token',
      'X-Feedback-IAP-Assertion': 'FORGED-FORWARDED', 'X-Serverless-Authorization': 'Bearer forged.workload.token' } });
    assert.equal(response.status, 200);
    assert.deepEqual(await (await fetch(url + '/auth/config', { headers: iap })).json(), { managedBrowserSignIn: true });
  });
  assert.equal(seen?.get('Cookie'), cookie); assert.equal(seen?.get('X-Feedback-Demo-View'), '1');
  assert.equal(seen?.get('X-Feedback-IAP-Assertion'), assertion); assert.equal(seen?.get('X-Serverless-Authorization'), 'Bearer runtime.workload.token');
  for (const name of ['Authorization', 'X-Feedback-Role', 'X-Feedback-Demo-Authorization', 'X-Feedback-User-Authorization']) assert.equal(seen?.get(name), null);
});

test('missing expired malformed or duplicate cookies reject demo-marked requests before any backend call', async () => {
  let calls = 0;
  await server({ getWorkloadToken: async () => { calls++; return 'runtime'; } }, async url => {
    for (const value of ['', 'other=private', 'neo_role_demo=forged', `${cookie}; ${cookie}`, 'neo_demo_admin_session=obsolete']) {
      assert.equal((await fetch(url + '/api/my/feedback', { method: 'POST', headers: { ...actions, 'X-Feedback-Demo-View': '1', Cookie: value }, body: '{}' })).status, 401);
    }
    assert.equal((await fetch(url + '/api/my/feedback', { method: 'POST', headers: { ...actions, 'X-Feedback-Demo-View': '0' }, body: '{}' })).status, 400);
  });
  assert.equal(calls, 0);
});

test('a demo cookie without its marker cannot accidentally access the live workspace', async () => {
  let calls = 0;
  await server({ fetchImpl: async () => { calls++; return Response.json({}); } }, async url => {
    assert.equal((await fetch(url + '/api/feedback', { headers: { ...iap, Cookie: cookie } })).status, 409);
    assert.equal((await fetch(url + '/api/my/feedback', { method: 'POST', headers: { ...actions, Cookie: cookie }, body: '{}' })).status, 409);
    assert.equal((await fetch(url + '/api/auth/me', { headers: { ...iap, Cookie: cookie } })).status, 200);
  });
  assert.equal(calls, 1);
});

test('new demo actions keep IAP CSRF protections and forward exact action headers once', async () => {
  let calls = 0; let seen: Headers | undefined;
  await server({ fetchImpl: async (_url, init) => { calls++; seen = new Headers(init?.headers); return Response.json({}); } }, async url => {
    for (const headers of [{ ...actions, Origin: 'https://evil.example' }, { ...actions, 'X-Requested-With': '' },
      { ...actions, 'X-Feedback-CSRF': '' }, { ...actions, 'Sec-Fetch-Site': 'cross-site' }]) {
      assert.equal((await fetch(url + '/api/demo-admin/persona', { method: 'POST', headers, body: '{}' })).status, 403);
    }
    assert.equal(calls, 0);
    assert.equal((await fetch(url + '/api/demo-admin/persona', { method: 'POST', headers: actions, body: '{"email":"alex.requester@example.test"}' })).status, 200);
  });
  assert.equal(calls, 1); assert.equal(seen?.get('Origin'), origin); assert.equal(seen?.get('X-Feedback-CSRF'), '1');
});

test('only the role cookie may be returned, never IAP/provider/legacy cookies or a cross-domain cookie', async () => {
  const headers = new Headers();
  for (const value of [`${cookie}; HttpOnly; Secure; SameSite=Strict; Path=/`, 'unrelated=secret; Path=/',
    'neo_demo_admin_session=legacy; HttpOnly', `${cookie}; Domain=attacker.example; Path=/`]) headers.append('Set-Cookie', value);
  await server({ fetchImpl: async () => Response.json({}, { headers }) }, async url => {
    const response = await fetch(url + '/api/demo-admin/persona', { method: 'POST', headers: actions, body: '{}' });
    assert.deepEqual(response.headers.getSetCookie(), [`${cookie}; HttpOnly; Secure; SameSite=Strict; Path=/`]);
  });
  await server({ fetchImpl: async () => Response.json({}, { headers: { 'Set-Cookie': 'neo_role_demo=""; Max-Age=0; Path=/; HttpOnly; SameSite=strict' } }) }, async url => {
    const response = await fetch(url + '/api/demo-admin/logout', { method: 'POST', headers: actions, body: '{}' });
    assert.match(response.headers.get('Set-Cookie') || '', /Max-Age=0/);
  });
});

test('disabled role-demo feature denies markers instead of forwarding live requests, and mutations are never retried', async () => {
  let calls = 0;
  await server({ roleDemoEnabled: false, fetchImpl: async () => { calls++; return Response.json({}); } }, async url => {
    assert.equal((await fetch(url + '/api/my/feedback', { headers: { ...iap, Cookie: cookie, 'X-Feedback-Demo-View': '1' } })).status, 404);
  });
  assert.equal(calls, 0);
  await server({ fetchImpl: async () => { calls++; throw new Error('PRIVATE-DETAIL'); } }, async url => {
    const response = await fetch(url + '/api/demo-admin/persona', { method: 'POST', headers: actions, body: '{}' });
    assert.equal(response.status, 502); assert.doesNotMatch(await response.text(), /PRIVATE-DETAIL|workload.token/);
  });
  assert.equal(calls, 1);
});

test('Demo Admin controls are capability-gated and distinguish real live data from an active simulated persona', () => {
  const props = { session: null, busy: false, onSwitch() {}, onReset() {}, onExit() {} };
  assert.equal(renderToStaticMarkup(React.createElement(DemoAdminControls, { ...props, user: { ...real, canSwitchDemoViews: false, accessRole: undefined } })), '');
  const live = renderToStaticMarkup(React.createElement(DemoAdminControls, { ...props, user: real }));
  assert.match(live, /Demo Admin · Reviewer permissions/); assert.match(live, /Your real account and live workspace/);
  assert.match(live, /aria-label="Switch demo view"/); assert.doesNotMatch(live, /Reset demo data|aria-label="Exit demo"/);
  const demo = renderToStaticMarkup(React.createElement(DemoAdminControls, { ...props, user: sample,
    session: { enabled: true, active: true, personas: [sample], user: sample, realUser: real, simulatedAi: true } }));
  assert.match(demo, /sample data · simulated AI/); assert.match(demo, /Signed in as Real Admin/); assert.match(demo, /Viewing as Alex Reporter/);
  assert.match(demo, /aria-label="Exit demo"/); assert.match(demo, /aria-label="Reset demo data"/);
});

test('view-switch reset and exit controls keep full stable labels instead of moving on pointer hover', () => {
  const html = renderToStaticMarkup(React.createElement(DemoAdminControls, { user: sample, busy: false,
    session: { enabled: true, active: true, personas: [sample], user: sample, realUser: real, simulatedAi: true },
    onSwitch() {}, onReset() {}, onExit() {} }));
  assert.equal((html.match(/data-action-expanded="true"/g) || []).length, 3);
  assert.match(html, /flex w-full flex-wrap gap-2 sm:w-auto/);
});

test('stored application roles expose Demo Admin explicitly without changing the effective Reporter/Reviewer roles', () => {
  const html = renderToStaticMarkup(React.createElement(AccessGrantForm, { allowedDomains: ['company.example'], onCancel() {}, onSaved() {},
    grant: { email: real.email, displayName: real.displayName, role: 'demo_admin', active: true, expiresAt: null, createdAt: '2026-10-29T00:00:00Z', updatedAt: '2026-10-29T00:00:00Z', updatedBy: real.email, canEdit: false, status: 'active' } }));
  assert.match(html, /value="demo_admin" selected="">Demo Admin/); assert.match(html, /no employee impersonation, cloud IAM/);
});

test('in-app chooser uses accessible bounded dialogs and no password/login build branch remains in App', async () => {
  const chooser = await readFile(new URL('../src/components/DemoViewChooser.tsx', import.meta.url), 'utf8');
  assert.match(chooser, /useDialogFocus/); assert.match(chooser, /containDialogFocus/); assert.match(chooser, /aria-modal="true"/);
  assert.match(chooser, /max-h-\[90dvh\]/); assert.match(chooser, /overflow-y-auto/);
  const app = await readFile(new URL('../src/App.tsx', import.meta.url), 'utf8');
  assert.doesNotMatch(app, /DemoAdminLogin|demoAdminDeployment|VITE_AUTH_MODE === 'demo_admin'/);
  assert.match(app, /mode: 'google_iam'/); assert.match(app, /confirmDemoNavigation/);
});

test('demo controller APIs use the existing IAP cookie and explicit actions, not a password or alternate browser bearer', async t => {
  const original = globalThis.fetch; const calls: Array<{ url: string; init?: RequestInit }> = [];
  globalThis.fetch = async (url, init) => { calls.push({ url: String(url), init }); return Response.json({}); };
  t.after(() => { globalThis.fetch = original; });
  await getDemoAdminSession(); await selectDemoPersona(sample.email); await logoutDemoAdmin();
  assert.deepEqual(calls.map(call => call.url), ['/api/demo-admin/session', '/api/demo-admin/persona', '/api/demo-admin/logout']);
  for (const call of calls) {
    const headers = new Headers(call.init?.headers);
    assert.equal(call.init?.credentials, 'same-origin'); assert.equal(headers.get('Authorization'), null);
    assert.equal(headers.get('X-Feedback-Demo-View'), null);
    if (call.init?.method === 'POST') assert.equal(headers.get('X-Feedback-CSRF'), '1');
  }
});

function clientFixture(t: { after: (fn: () => void) => void }) {
  const original = globalThis.fetch;
  const descriptors = new Map(['localStorage', 'window'].map(name => [name, Object.getOwnPropertyDescriptor(globalThis, name)]));
  const storage = new Map<string, string>(); const events: string[] = [];
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: { getItem: (key: string) => storage.get(key) || null,
    setItem: (key: string, value: string) => storage.set(key, value), removeItem: (key: string) => storage.delete(key) } });
  Object.defineProperty(globalThis, 'window', { configurable: true, value: { dispatchEvent: (event: Event) => { events.push(event.type); } } });
  t.after(() => { clearAuthSession(); globalThis.fetch = original; for (const [name, descriptor] of descriptors) { if (descriptor) Object.defineProperty(globalThis, name, descriptor); else Reflect.deleteProperty(globalThis, name); } });
  saveAuthSession({ mode: 'google_iam', accessToken: '', user: sample, expiresIn: 0 });
  return { storage, events };
}

test('every demo data read and mutation carries its marker, same-origin cookies and unchanged primary Google session mode', async t => {
  const { storage } = clientFixture(t); const calls: RequestInit[] = [];
  globalThis.fetch = async (_url, init) => { calls.push(init || {}); return Response.json({ items: [], total: 0 }); };
  await listMyFeedback(); await createMyFeedback({ feedback_text: 'Demo only', user_verdict: 'Incorrect', issue_categories: [], impact: 'Low' });
  assert.equal(calls.length, 2);
  for (const init of calls) {
    assert.equal(new Headers(init.headers).get('X-Feedback-Demo-View'), '1');
    assert.equal(new Headers(init.headers).get('Authorization'), null); assert.equal(init.credentials, 'same-origin');
  }
  assert.equal(new Headers(calls[1].headers).get('X-Feedback-CSRF'), '1');
  assert.equal(JSON.parse(storage.get('agent-quality-auth-v1')!).mode, 'google_iam');
});

test('demo expiry never drops the marker or automatically retries into live data', async t => {
  clientFixture(t); const calls: RequestInit[] = [];
  globalThis.fetch = async (_url, init) => { calls.push(init || {}); return Response.json({ detail: 'Demo view expired' }, { status: 401 }); };
  const payload = { feedback_text: 'Demo only', user_verdict: 'Incorrect' as const, issue_categories: [], impact: 'Low' as const };
  await assert.rejects(createMyFeedback(payload), error => error instanceof ApiError && error.status === 401);
  assert.equal(calls.length, 1);
  await assert.rejects(createMyFeedback(payload)); assert.equal(calls.length, 2);
  assert.ok(calls.every(init => new Headers(init.headers).get('X-Feedback-Demo-View') === '1'));
});

test('another tab exiting demo cannot make a stale demo form send even one live mutation', async t => {
  const { storage, events } = clientFixture(t); let calls = 0;
  globalThis.fetch = async () => { calls++; return Response.json({}); };
  storage.set('agent-quality-auth-v1', JSON.stringify({ mode: 'google_iam', accessToken: '', user: real, expiresIn: 0 }));
  await assert.rejects(createMyFeedback({ feedback_text: 'Stale demo', user_verdict: 'Incorrect', issue_categories: [], impact: 'Low' }), error => error instanceof ApiError && error.status === 499);
  assert.equal(calls, 0); assert.ok(events.length);
});

test('an in-flight demo read is discarded if another tab changes its identity or demo view', async t => {
  const { storage } = clientFixture(t); let complete: ((value: Response) => void) | undefined;
  globalThis.fetch = async () => new Promise(resolve => { complete = resolve; });
  const pending = listMyFeedback();
  storage.set('agent-quality-auth-v1', JSON.stringify({ mode: 'google_iam', accessToken: '', user: real, expiresIn: 0 }));
  complete!(Response.json({ items: [], total: 0 }));
  await assert.rejects(pending, error => error instanceof ApiError && error.status === 499);
});

test('an intentional same-tab view switch discards old responses without marking the new view expired', async t => {
  const { events } = clientFixture(t); let complete: ((value: Response) => void) | undefined;
  globalThis.fetch = async () => new Promise(resolve => { complete = resolve; });
  const pending = listMyFeedback();
  saveAuthSession({ mode: 'google_iam', accessToken: '', user: real, expiresIn: 0 });
  complete!(Response.json({ items: [], total: 0 }));
  await assert.rejects(pending, error => error instanceof ApiError && error.status === 499);
  assert.equal(events.length, 0);
});
