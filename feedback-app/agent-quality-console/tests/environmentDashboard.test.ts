import assert from 'node:assert/strict';
import test, { after, before } from 'node:test';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { clearReadCache, getOverviewMetrics, testAgentEndpoint, type AgentEnvironmentConfig, type OverviewMetrics } from '../src/api/feedbackApi';
import { EnvironmentSettingsView } from '../src/components/EnvironmentSettingsView';
import { OverviewView } from '../src/components/OverviewView';
import DashboardCharts from '../src/components/DashboardCharts';

const storageDescriptor = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
before(() => Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: { getItem: () => null } }));
after(() => { if (storageDescriptor) Object.defineProperty(globalThis, 'localStorage', storageDescriptor); else Reflect.deleteProperty(globalThis, 'localStorage'); });

const production: AgentEnvironmentConfig = {
  id: 'neo-prod', agentId: 'neo-rules-agent', name: 'Production', kind: 'prod', enabled: false,
  revision: 2, configured: true, canRetest: false, canManage: true, canActivate: true, canTest: true,
  persisted: true, accessStatus: 'unverified', url: 'https://api.loreal.net/production/endpoint',
};
const metrics: OverviewMetrics = {
  feedback_total: 20, feedback_needing_review: 7, golden_dataset_count: 1, approved_case_count: 3,
  rca_runs_count: 10, auto_classified_count: 2, rca_review_count: 8,
  native_feedback_count: 0, promoted_feedback_count: 20, all_feedback_total: 156,
  feedback_trend: [], state_breakdown: [], verdict_breakdown: [], root_cause_breakdown: [],
  subcategory_breakdown: [], evaluation_trend: [], recent_feedback: [],
  assessment_breakdown: [{ verdict: 'inconclusive', count: 5 }],
  scope: { environmentId: 'uat', environmentName: 'UAT', assets: 'agent_wide', evaluations: 'agent_wide_legacy',
    quality: 'latest_saved_answer_per_environment', reviewProgress: 'source_report_workflow' },
};

test('configured Production endpoints have the same testing controls with no special warnings or permissions', () => {
  const html = renderToStaticMarkup(React.createElement(EnvironmentSettingsView, {
    environments: [production], loading: false, onRefresh: async () => {},
  }));
  const endpointTest = html.match(/<button[^>]*aria-label="Test Production endpoint"[^>]*>/)?.[0];
  assert.ok(endpointTest); assert.doesNotMatch(endpointTest, /\sdisabled=/);
  const edit = html.match(/<button[^>]*aria-label="Edit Production environment"[^>]*>/)?.[0];
  assert.ok(edit); assert.doesNotMatch(edit, /\sdisabled=/);
  assert.match(html, /test a saved endpoint while its environment is disabled/);
  assert.doesNotMatch(html, /company SSO|production grant|draft configuration|explicit production authorization/i);
});

test('last-test failures show HTTP status and safe reason rather than an unexplained disabled state', () => {
  const html = renderToStaticMarkup(React.createElement(EnvironmentSettingsView, {
    environments: [{ ...production, lastTest: { id: 'TEST-1', environmentId: 'neo-prod', configurationRevision: 2,
      status: 'failed', httpStatus: 403, elapsedMs: 270, createdAt: '2026-10-23T00:00:00Z',
      error: 'The backend identity does not have access to this agent.' } }], loading: false, onRefresh: async () => {},
  }));
  assert.match(html, /Last test: failed/); assert.match(html, /HTTP 403/); assert.match(html, /0\.27s/);
  assert.match(html, /backend identity does not have access/); assert.match(html, /Configuration r2/);
});

test('dashboard keeps linked-case counts separate from shared golden assets and source-review state', () => {
  const html = renderToStaticMarkup(React.createElement(OverviewView, {
    metrics, environmentName: 'UAT', loading: false, onNavigate() {}, onRefresh() {},
  }));
  assert.match(html, /UAT overview/); assert.match(html, /0 reported here · 20 promoted in/);
  assert.match(html, /Original report workflows, not target verdicts/);
  assert.match(html, /Agent-wide resources/); assert.match(html, /not attributed to the selected environment/);
  assert.doesNotMatch(html, /176/);
});

test('target assessments are unverified and never confused with submitted verdicts or global evaluations', () => {
  const html = renderToStaticMarkup(React.createElement(DashboardCharts, { metrics, onNavigate() {} }));
  assert.match(html, /not target-agent correctness/); assert.match(html, /never an owner confirmation/);
  assert.match(html, /Inconclusive/); assert.match(html, /Evaluation performance · agent-wide/);
  assert.match(html, /no cross-environment fallback/);
});

test('overview requests and caches remain separated by exact environment ID', async (t) => {
  const originalFetch = globalThis.fetch;
  const paths: string[] = [];
  globalThis.fetch = async (url) => {
    const path = String(url); paths.push(path);
    return Response.json({ feedback_total: path.includes('environment_id=uat') ? 20 : 156 });
  };
  t.after(() => { globalThis.fetch = originalFetch; clearReadCache(); });
  clearReadCache();
  assert.equal((await getOverviewMetrics(false, 'neo-nonprod')).feedback_total, 156);
  assert.equal((await getOverviewMetrics(false, 'uat')).feedback_total, 20);
  assert.equal((await getOverviewMetrics(false, 'All')).feedback_total, 156);
  assert.equal((await getOverviewMetrics(false, 'uat')).feedback_total, 20);
  assert.deepEqual(paths, ['/api/overview?environment_id=neo-nonprod', '/api/overview?environment_id=uat', '/api/overview']);
});

test('endpoint-test API uses the same one-shot request for Production without a special confirmation flag', async (t) => {
  const originalFetch = globalThis.fetch;
  const calls: Array<{ url: string; init: RequestInit }> = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), init: init || {} });
    return Response.json({ detail: 'Response interrupted after the test may have run' }, { status: 503 });
  };
  t.after(() => { globalThis.fetch = originalFetch; clearReadCache(); });
  await assert.rejects(testAgentEndpoint('neo-prod', 2, 'Hello', 'explicit-test-key'), /may have run/);
  assert.equal(calls.length, 1); assert.equal(calls[0].url, '/api/agent-environments/neo-prod/test');
  assert.deepEqual(JSON.parse(String(calls[0].init.body)), {
    expected_revision: 2, question: 'Hello', idempotency_key: 'explicit-test-key',
  });
  assert.doesNotMatch(String(calls[0].init.body), /url|token|credential|agent_id/);
});
