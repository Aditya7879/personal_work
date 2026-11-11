import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { shouldShowDemoPicker } from '../src/utils/demoAuth';
import { DemoUserSwitch } from '../src/components/DemoUserSwitch';
import { MockSignInView } from '../src/components/MockSignInView';

test('an explicit local demo entry always returns to the original role picker', () => {
  assert.equal(shouldShowDemoPicker(false, '?demo=login'), true);
  assert.equal(shouldShowDemoPicker(false, '?demo=login&view=overview', 'mock'), true);
});

test('a cached private-IAM session is not reused by a local mock demo', () => {
  assert.equal(shouldShowDemoPicker(false, '', 'google_iam'), true);
  assert.equal(shouldShowDemoPicker(false, '', 'mock'), false);
  assert.equal(shouldShowDemoPicker(false, ''), false);
});

test('demo URLs and cached mock sessions never override deployed IAM mode', () => {
  assert.equal(shouldShowDemoPicker(true, '?demo=login', 'mock'), false);
  assert.equal(shouldShowDemoPicker(true, '?demo=login', 'google_iam'), false);
  assert.equal(shouldShowDemoPicker(true, ''), false);
});

test('the local reviewer/reporter picker needs no Google sign-in and preserves public account labels', () => {
  const html = renderToStaticMarkup(React.createElement(MockSignInView, { users: [
    { email: 'reviewer@example.test', displayName: 'Quality Reviewer', role: 'reviewer' },
    { email: 'reporter@example.test', displayName: 'Sample requester (existing feedback)', role: 'reporter' },
  ], loading: false, error: null, onSignIn: async () => {} }));
  assert.match(html, /Quality Reviewer/);
  assert.match(html, /Sample requester \(existing feedback\)/);
  assert.match(html, /reviewer/);
  assert.match(html, /reporter/);
  assert.match(html, /No company sign-in is required/);
  assert.match(html, /Continue/);
  assert.doesNotMatch(html, /feedbackOwnerEmail|Private NEO feedback preview/);
});

test('the switch-user control is explicit and calls no API or agent itself', () => {
  const html = renderToStaticMarkup(React.createElement(DemoUserSwitch, { onClick() {} }));
  assert.match(html, /aria-label="Switch demo user"/);
  assert.match(html, /mock reviewer \/ reporter picker/);
  assert.match(html, /type="button"/);
  assert.doesNotMatch(html, /form|fetch|generations|retests/);
});
