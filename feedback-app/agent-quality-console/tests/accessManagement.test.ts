import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { AccessGrantForm, AccessManagementView, accessExpiryInput } from '../src/components/AccessManagementView';
import { SettingsView } from '../src/components/SettingsView';
import { PrivateAccessView } from '../src/components/PrivateAccessView';
import { Sidebar } from '../src/components/Sidebar';
import { clearReadCache, getAccessGrantHistory, listAccessGrants, saveAccessGrant, type AuthUser } from '../src/api/feedbackApi';

const user: AuthUser = { email: 'reviewer@company.example', displayName: 'Reviewer', role: 'reviewer', cacheScope: 'verified-scope' };

test('Settings exposes keyboard-accessible Environments and People & access tabs without starting access reads by default', () => {
  const html = renderToStaticMarkup(React.createElement(SettingsView, { environments: [], loading: false, onRefresh: async () => {}, currentUser: user, googleAuthenticated: true }));
  assert.match(html, /role="tablist" aria-label="Settings sections"/);
  assert.match(html, /role="tab"[^>]*aria-selected="true"[^>]*>Environments/);
  assert.match(html, /role="tab"[^>]*aria-selected="false"[^>]*tabindex="-1"[^>]*>People &amp; access/);
  assert.match(html, /role="tabpanel"/);
  assert.doesNotMatch(html, /Loading people|Add person/);
});

test('demo profiles cannot open the real access directory or edit company grants', () => {
  const html = renderToStaticMarkup(React.createElement(AccessManagementView, { currentUser: user, enabled: false }));
  assert.match(html, /real Google reviewer identity/);
  assert.match(html, /Demo profiles cannot view or change real company grants/);
  assert.doesNotMatch(html, /Add person|Search people/);
});

test('grant editor defaults to least-privilege Reporter with labelled expiry and an explicit review step', () => {
  const html = renderToStaticMarkup(React.createElement(AccessGrantForm, { allowedDomains: ['company.example'], onCancel() {}, onSaved() {} }));
  assert.match(html, /Company email/); assert.match(html, /type="email"/);
  assert.match(html, /value="reporter" selected=""/); assert.match(html, /value="reviewer"/);
  assert.doesNotMatch(html, /value="admin"|client.secret|access.token|feedbackOwnerEmail/i);
  assert.match(html, /Access expires/); assert.match(html, /Your local timezone/);
  assert.match(html, /type="submit"[^>]*>Review access change/);
  assert.doesNotMatch(html, /action-button-compact[^>]*>Review access change/);
});

test('managed browser access explains the real grant requirement and never asks for a local proxy', () => {
  const html = renderToStaticMarkup(React.createElement(PrivateAccessView, { managedBrowserSignIn: true, error: 'Your identity has no active application access grant', onConnect() {} }));
  assert.match(html, /Settings → People &amp; access/); assert.match(html, /Check my access again/);
  assert.match(html, /gcp-iap-mode=CLEAR_LOGIN_COOKIE/);
  assert.doesNotMatch(html, /python3|Connect through private proxy|mock identity picker/);
});

test('Settings is reachable on mobile for reviewers but never exposed as reporter navigation', () => {
  const reviewer = renderToStaticMarkup(React.createElement(Sidebar, { activeView: 'settings', role: 'reviewer', onNavigate() {} }));
  const mobile = reviewer.slice(reviewer.indexOf('aria-label="Mobile workspace"'), reviewer.indexOf('</nav>'));
  assert.match(mobile, />Settings</);
  const reporter = renderToStaticMarkup(React.createElement(Sidebar, { activeView: 'my-feedback', role: 'reporter', onNavigate() {} }));
  assert.doesNotMatch(reporter, />Settings</);
});

test('expiry input uses the viewer timezone and does not invent an expiry for missing values', () => {
  assert.equal(accessExpiryInput(null), ''); assert.equal(accessExpiryInput('invalid'), '');
  const source = new Date('2026-10-27T12:34:00Z');
  assert.equal(new Date(accessExpiryInput(source.toISOString())).getTime(), source.getTime());
});

test('people APIs send exact versions and one deliberate mutation, without browser identity credentials or automatic replay', async (t) => {
  const originalFetch = globalThis.fetch;
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  const session = JSON.stringify({ mode: 'google_iam', accessToken: '', user, expiresIn: 0 });
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: { getItem: () => session } });
  const calls: Array<{ url: string; init: RequestInit }> = [];
  globalThis.fetch = async (url, init) => { calls.push({ url: String(url), init: init || {} }); return Response.json({ detail: 'Changed concurrently' }, { status: 409 }); };
  t.after(() => { globalThis.fetch = originalFetch; clearReadCache(); if (descriptor) Object.defineProperty(globalThis, 'localStorage', descriptor); else Reflect.deleteProperty(globalThis, 'localStorage'); });
  const input = { display_name: 'Person', role: 'reporter' as const, active: false, expires_at: null, expected_updated_at: '2026-10-27T00:00:00Z' };
  await assert.rejects(saveAccessGrant(input, 'person@company.example'), /Changed concurrently/);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, '/api/access-grants/person%40company.example');
  assert.equal(calls[0].init.method, 'PATCH'); assert.deepEqual(JSON.parse(String(calls[0].init.body)), input);
  const headers = new Headers(calls[0].init.headers);
  assert.equal(headers.get('X-Feedback-CSRF'), '1'); assert.equal(headers.get('Authorization'), null);
  await assert.rejects(listAccessGrants('person', 2)); await assert.rejects(getAccessGrantHistory('person@company.example'));
  assert.equal(calls.length, 3); assert.ok(calls.every((call) => call.url.startsWith('/api/access-grants')));
});
