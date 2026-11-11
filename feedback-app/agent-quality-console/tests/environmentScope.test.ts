import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import type { AgentEnvironmentConfig, AnswerVersion, FeedbackHistory } from '../src/api/feedbackApi';
import { answerEnvironmentId, answersInEnvironment } from '../src/utils/environmentScope';
import { EnvironmentSwitcher } from '../src/components/EnvironmentSwitcher';

const dev: AnswerVersion = { id: 'answer:dev', kind: 'retest', answer: 'DEV response', environment: 'nonprod', environmentId: 'dev', revision: 1, createdAt: '2026-10-23T00:00:00Z' };
const uat: AnswerVersion = { ...dev, id: 'answer:uat', answer: 'UAT response', environmentId: 'uat' };
const original: AnswerVersion = { ...dev, id: 'original:1', kind: 'original', environmentId: undefined };
const history: FeedbackHistory = { answers: [original, dev, uat], diagnoses: [], attempts: [] };

test('DEV and UAT remain separate even when both are non-production', () => {
  assert.deepEqual(answersInEnvironment(history, { environmentId: 'dev', environment: 'nonprod', revision: 1 }, 'uat').map((row) => row.id), ['answer:uat']);
  assert.equal(answerEnvironmentId(dev, history, {}), 'dev');
});

test('a promoted main environment scopes the owner history without relabelling the original response', () => {
  const main = { environment: 'prod' as const, environmentId: 'neo-prod', revision: 1 };
  assert.deepEqual(answersInEnvironment(history, main, main.environmentId).map((row) => row.id), []);
  const promoted: FeedbackHistory = { ...history, answers: [...history.answers, { ...dev, id: 'answer:prod', answer: 'Production response', environment: 'prod', environmentId: 'neo-prod' }] };
  assert.deepEqual(answersInEnvironment(promoted, main, main.environmentId).map((row) => row.id), ['answer:prod']);
  assert.equal(promoted.answers.find((row) => row.kind === 'original')?.environment, 'nonprod');
});

test('an untested environment never borrows another response or original capture', () => {
  assert.deepEqual(answersInEnvironment(history, { environmentId: 'dev', environment: 'nonprod', revision: 1 }, 'staging'), []);
  assert.deepEqual(answersInEnvironment(history, {}, 'uat').map((row) => row.id), ['answer:uat']);
});

test('all-environment history preserves every immutable answer', () => {
  assert.deepEqual(answersInEnvironment(history, {}).map((row) => row.id), history.answers.map((row) => row.id));
});

test('legacy retest answers use the recorded attempt target ID, not the nonprod label', () => {
  const legacy = { ...dev, environmentId: undefined, attemptId: 'JOB-1' };
  const value: FeedbackHistory = { ...history, answers: [legacy], attempts: [{ id: 'JOB-1', kind: 'retest', status: 'completed', environment: 'nonprod', environmentId: 'dev', revision: 1, createdAt: dev.createdAt }] };
  assert.deepEqual(answersInEnvironment(value, {}, 'uat'), []);
  assert.equal(answersInEnvironment(value, {}, 'dev')[0].id, dev.id);
});

test('a corrected source revision does not relabel a historical original answer', () => {
  assert.equal(answerEnvironmentId(original, history, { environment: 'nonprod', environmentId: 'uat', revision: 2 }), undefined);
});

test('environment selector renders the selected name with a themed listbox trigger, never endpoint configuration', () => {
  const value = { id: 'uat', agentId: 'neo-rules-agent', name: 'UAT', kind: 'nonprod', enabled: true,
    revision: 1, configured: true, canRetest: false, canManage: true, persisted: true, accessStatus: 'unverified', url: 'https://private.example/secret-endpoint' } as AgentEnvironmentConfig;
  const html = renderToStaticMarkup(React.createElement(EnvironmentSwitcher, { environments: [value], environmentId: 'uat', onEnvironmentChange() {} }));
  assert.match(html, /Workspace environment/);
  assert.match(html, /role="combobox"/);
  assert.match(html, /aria-haspopup="listbox"/);
  assert.match(html, /aria-expanded="false"/);
  assert.match(html, />UAT<\/span>/);
  assert.doesNotMatch(html, /<select|<option/);
  assert.doesNotMatch(html, /private\.example|secret-endpoint|Create agent/);
});

test('All environments remains the default header scope', () => {
  const html = renderToStaticMarkup(React.createElement(EnvironmentSwitcher, {}));
  assert.match(html, />All environments<\/span>/);
  assert.doesNotMatch(html, /\sdisabled=/);
});

test('disabled environments remain selectable views and have a subtle neutral status label', () => {
  const value = { id: 'prod', name: 'Production', enabled: false } as AgentEnvironmentConfig;
  const html = renderToStaticMarkup(React.createElement(EnvironmentSwitcher, { environments: [value], environmentId: 'prod' }));
  assert.match(html, /Current environment: Production · disabled/);
  assert.match(html, /title="Production · disabled"/);
  assert.match(html, />Disabled<\/span>/);
  assert.doesNotMatch(html, /\sdisabled=/);
});

test('environment loading disables the trigger without replacing the current environment label', () => {
  const value = { id: 'uat', name: 'UAT', enabled: true } as AgentEnvironmentConfig;
  const html = renderToStaticMarkup(React.createElement(EnvironmentSwitcher, { environments: [value], environmentId: 'uat', environmentsLoading: true }));
  assert.match(html, /aria-busy="true"/);
  assert.match(html, /\sdisabled=""/);
  assert.match(html, />UAT<\/span>/);
});
