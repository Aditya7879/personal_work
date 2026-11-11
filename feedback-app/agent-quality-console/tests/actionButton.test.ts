import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { RefreshCw } from 'lucide-react';
import { ActionButton } from '../src/components/ActionButton';

const render = (props: Partial<React.ComponentProps<typeof ActionButton>> = {}) => renderToStaticMarkup(React.createElement(ActionButton, {
  label: 'Refresh environments', icon: React.createElement(RefreshCw), ...props,
}));

test('compact actions remain native buttons with a stable full accessible name and explicit non-submit default', () => {
  const html = render();
  assert.match(html, /<button[^>]*type="button"[^>]*aria-label="Refresh environments"/);
  assert.match(html, /title="Refresh environments"/);
  assert.match(html, /class="action-button-labels" aria-hidden="true"/);
  assert.equal((html.match(/<button\b/g) || []).length, 1);
});

test('short captions do not replace the full action name', () => {
  const html = render({ compactLabel: 'Refresh' });
  assert.match(html, /action-button-prefix/);
  assert.match(html, />Refresh<\/span>/);
  assert.match(html, />environments<\/span>/);
  assert.match(html, /aria-label="Refresh environments"/);
});

test('permission and disabled-reason attributes are preserved without custom click interception', () => {
  let calls = 0;
  const html = render({ disabled: true, title: 'Save an endpoint URL before testing', onClick: () => { calls += 1; } });
  assert.match(html, /<button[^>]*disabled=""/);
  assert.match(html, /title="Save an endpoint URL before testing"/);
  assert.equal(calls, 0);
});

test('open menus and loading actions retain their expanded label', () => {
  assert.match(render({ 'aria-expanded': true }), /data-action-expanded="true"/);
  assert.match(render({ expanded: true }), /data-action-expanded="true"/);
  const html = render({ loading: true });
  assert.match(html, /aria-busy="true"/);
  assert.match(html, /data-action-expanded="true"/);
  assert.match(html, /motion-safe:animate-spin/);
  // Loading is presentation only; callers retain ownership of enabled/disabled rules.
  assert.doesNotMatch(html, /\sdisabled=/);
});

test('fixed-footprint row actions use one native button and an inaccessible layout placeholder', () => {
  const html = render({ expansion: 'overlay', align: 'end', size: 'sm' });
  assert.match(html, /data-expansion="overlay" data-align="end" data-size="sm"/);
  assert.match(html, /class="action-button-footprint" aria-hidden="true"/);
  assert.equal((html.match(/<button\b/g) || []).length, 1);
});

test('combobox semantics, menu linkage and custom accessible names pass through unchanged', () => {
  const html = render({ role: 'combobox', 'aria-label': 'Workspace environment', 'aria-expanded': false,
    'aria-controls': 'environment-options', 'aria-activedescendant': 'option-2' });
  assert.match(html, /role="combobox"/);
  assert.match(html, /aria-label="Workspace environment"/);
  assert.match(html, /aria-controls="environment-options"/);
  assert.match(html, /aria-activedescendant="option-2"/);
});

test('animations are scoped to compact actions, hover requires a real pointer, and touch/reduced-motion rules remain present', () => {
  const css = readFileSync(new URL('../src/index.css', import.meta.url), 'utf8');
  assert.match(css, /grid-template-columns 180ms cubic-bezier\(0\.22, 1, 0\.36, 1\)/);
  assert.match(css, /@media \(hover: hover\) and \(pointer: fine\)/);
  assert.match(css, /@media \(hover: none\), \(pointer: coarse\)/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(css, /\.action-button:is\(:focus-visible, \[data-action-expanded="true"\]\)/);
  assert.doesNotMatch(css, /^\s*button:hover/m);
});

test('save, endpoint-send and promotion-confirm controls remain explicitly labelled native buttons', () => {
  const editor = readFileSync(new URL('../src/components/FeedbackEditView.tsx', import.meta.url), 'utf8');
  const endpoint = readFileSync(new URL('../src/components/EndpointTestDialog.tsx', import.meta.url), 'utf8');
  const promotion = readFileSync(new URL('../src/components/PromotionDialog.tsx', import.meta.url), 'utf8');
  assert.match(editor, /<button type="submit"[^>]*form=\{formId\}/);
  assert.match(endpoint, /<button type="button" disabled=\{busy \|\| !question\.trim\(\)\}/);
  assert.match(promotion, /<button type="submit"/);
  assert.doesNotMatch(editor, /<ActionButton[^>]*label="Save changes"/);
  assert.doesNotMatch(endpoint, /<ActionButton[^>]*label="Send one test request"/);
});
