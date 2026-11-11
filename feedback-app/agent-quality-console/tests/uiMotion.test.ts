import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import type { TargetAndTransition } from 'motion/react';
import { surfaceMotion, type SurfaceMotion } from '../src/utils/uiMotion';
import { CollapsibleSection } from '../src/components/CollapsibleSection';

const kinds: SurfaceMotion[] = ['backdrop', 'dialog', 'drawer', 'popover', 'notice', 'editor'];
const target = (kind: SurfaceMotion, state: string, reduced = false) => surfaceMotion(kind, reduced).variants![state] as TargetAndTransition;

test('surfaces enter and exit with short, non-bouncy tweens', () => {
  for (const kind of kinds) {
    const enter = target(kind, 'open');
    const leave = target(kind, 'closing');
    assert.equal(enter.opacity, 1);
    assert.equal(leave.opacity, 0);
    assert.equal(enter.transition?.type, 'tween');
    assert.equal(leave.transition?.type, 'tween');
    assert.ok(Number(enter.transition?.duration) <= 0.22);
    assert.ok(Number(leave.transition?.duration) < Number(enter.transition?.duration));
    assert.equal(enter.transition?.delay, undefined);
  }
});

test('reduced motion makes entry immediate and exits without spatial movement', () => {
  for (const kind of kinds) {
    assert.equal(surfaceMotion(kind, true).initial, false);
    assert.equal(target(kind, 'open', true).transition?.duration, 0);
    const closing = target(kind, 'closing', true);
    assert.equal(closing.transition?.duration, 0);
    assert.equal(closing.opacity, 0);
    if ('x' in closing) assert.equal(closing.x, 0);
    if ('y' in closing) assert.equal(closing.y, 0);
    if ('scale' in closing) assert.equal(closing.scale, 1);
  }
});

test('editor/backdrop animations never create a transformed containing block', () => {
  for (const kind of ['editor', 'backdrop'] as const) {
    for (const state of ['closed', 'open', 'closing']) {
      const value = target(kind, state);
      assert.ok(!('x' in value) && !('y' in value) && !('scale' in value) && !('transform' in value));
    }
  }
});

test('closed disclosures are inert and hidden from assistive technology without an instant display toggle', () => {
  const html = renderToStaticMarkup(React.createElement(CollapsibleSection, { title: 'Review notes', children: React.createElement('textarea', { defaultValue: 'Draft' }) }));
  assert.match(html, /aria-expanded="false"/);
  assert.match(html, /aria-hidden="true"/);
  assert.match(html, /inert=""/);
  assert.match(html, /height:0/);
  assert.doesNotMatch(html, /\shidden=""/);
});

test('initially open disclosures render their content and keep normal region semantics', () => {
  const html = renderToStaticMarkup(React.createElement(CollapsibleSection, { title: 'Review notes', defaultOpen: true, children: React.createElement('textarea', { defaultValue: 'Draft' }) }));
  assert.match(html, /aria-expanded="true"/);
  assert.match(html, /role="region"/);
  assert.match(html, /height:auto/);
  assert.match(html, />Draft<\/textarea>/);
  assert.doesNotMatch(html, /inert=""/);
});
