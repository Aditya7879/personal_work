import assert from 'node:assert/strict';
import { once } from 'node:events';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import test from 'node:test';
import { browserOriginAllowed, createApp, validateBackendUrl } from '../server.mjs';

const backendUrl = 'https://private-feedback-api.run.app';
const frontendOrigin = 'https://private-feedback-ui.run.app';
const userToken = 'Bearer signed.user.credential';

type ProxyOptions = { getWorkloadToken?: () => Promise<string>; fetchImpl?: typeof fetch };

async function withServer(options: ProxyOptions, run: (url: string) => Promise<void>) {
  const directory = await mkdtemp('/tmp/opencode/feedback-private-proxy-test-');
  await writeFile(join(directory, 'index.html'), '<html><script>window.testTheme=true;</script><div>Private preview</div></html>');
  await writeFile(join(directory, '.env'), 'SENTINEL-SECRET-MUST-NOT-BE-SERVED');
  const app = createApp({ backendUrl, frontendOrigin, distDir: directory,
    getWorkloadToken: async () => 'server.workload.token', fetchImpl: async () => new Response('{}'), ...options });
  const server = app.listen(0, '127.0.0.1');
  await once(server, 'listening');
  const address = server.address();
  assert.ok(address && typeof address !== 'string');
  try { await run(`http://127.0.0.1:${address.port}`); }
  finally {
    server.closeAllConnections();
    await new Promise<void>((resolve) => server.close(() => resolve()));
    await rm(directory, { recursive: true, force: true });
  }
}

test('the API backend origin is fixed and rejects URL credentials, redirects and arbitrary destinations', () => {
  assert.equal(validateBackendUrl(backendUrl), backendUrl);
  for (const value of ['http://external.example', 'https://evil.example', 'https://user:secret@api.run.app',
    'https://api.run.app/path', 'https://api.run.app?target=evil', 'https://api.run.app#secret', 'https://api.run.app.evil.example']) {
    assert.throws(() => validateBackendUrl(value));
  }
  assert.equal(validateBackendUrl('http://127.0.0.1:8001', true), 'http://127.0.0.1:8001');
});

test('browser origins allow the exact cloud origin and loopback only, not hostile lookalikes', () => {
  assert.equal(browserOriginAllowed(undefined, frontendOrigin), true);
  assert.equal(browserOriginAllowed(frontendOrigin, frontendOrigin), true);
  assert.equal(browserOriginAllowed('http://localhost:8080', frontendOrigin), true);
  assert.equal(browserOriginAllowed('http://127.0.0.1:8085', frontendOrigin), true);
  for (const origin of ['https://attacker.example', 'http://localhost.attacker.example', 'null', 'file:///tmp/test', 'http://user:secret@localhost:8080']) {
    assert.equal(browserOriginAllowed(origin, frontendOrigin), false);
  }
});

test('API requests without a complete user credential never invoke the private backend', async () => {
  let calls = 0;
  await withServer({ fetchImpl: async () => { calls++; return new Response('{}'); } }, async (url) => {
    for (const authorization of ['', 'Bearer mock.signature', 'Bearer stripped.jwt.']) {
      const response = await fetch(url + '/api/auth/me', { headers: { Authorization: authorization } });
      assert.equal(response.status, 401);
    }
  });
  assert.equal(calls, 0);
});

test('private proxy preserves the signed user credential but replaces all caller workload/identity headers', async () => {
  let seen: { target: string; init?: RequestInit } | undefined;
  await withServer({ fetchImpl: async (target, init) => {
    seen = { target: target.toString(), init };
    return new Response('{"role":"reviewer"}', { headers: { 'Content-Type': 'application/json',
      'Authorization': 'Bearer NEVER-RETURN-WORKLOAD', 'Set-Cookie': 'NEVER-FORWARD', 'X-Feedback-Cache': 'MISS' } });
  } }, async (url) => {
    const response = await fetch(url + '/api/auth/me', { headers: { Authorization: 'Bearer stripped.jwt.',
      'X-Feedback-User-Authorization': userToken, 'X-Serverless-Authorization': 'Bearer FORGED-WORKLOAD',
      'X-Feedback-Demo-Authorization': 'Bearer signed.demo-session',
      'X-Goog-Authenticated-User-Email': 'spoofed@example.test', 'Cookie': 'unsafe=caller' } });
    assert.equal(response.status, 200);
    assert.equal(response.headers.get('authorization'), null);
    assert.equal(response.headers.get('set-cookie'), null);
    assert.equal(response.headers.get('cache-control'), 'private, no-store');
  });
  assert.ok(seen);
  assert.equal(seen.target, backendUrl + '/api/auth/me');
  const forwarded = new Headers(seen.init?.headers);
  assert.equal(forwarded.get('Authorization'), userToken);
  assert.equal(forwarded.get('X-Feedback-User-Authorization'), userToken);
  assert.equal(forwarded.get('X-Feedback-Demo-Authorization'), 'Bearer signed.demo-session');
  assert.equal(forwarded.get('X-Serverless-Authorization'), 'Bearer server.workload.token');
  assert.equal(forwarded.get('X-Goog-Authenticated-User-Email'), null);
  assert.equal(forwarded.get('Cookie'), null);
  assert.equal(seen.init?.redirect, 'manual');
});

test('cross-site API mutations are rejected before contacting metadata or the backend', async () => {
  let calls = 0;
  await withServer({ getWorkloadToken: async () => { calls++; return 'server.workload.token'; } }, async (url) => {
    const response = await fetch(url + '/api/feedback/FDB-1/retests', { method: 'POST',
      headers: { Authorization: userToken, Origin: 'https://attacker.example', 'Content-Type': 'application/json' }, body: '{}' });
    assert.equal(response.status, 403);
  });
  assert.equal(calls, 0);
});

test('mutations are sent once and a transport failure neither leaks credentials nor retries', async () => {
  let calls = 0;
  await withServer({ fetchImpl: async () => { calls++; throw new Error('SENSITIVE-TOKEN-DETAIL'); } }, async (url) => {
    const response = await fetch(url + '/api/feedback/FDB-1/retests', { method: 'POST',
      headers: { Authorization: userToken, 'Content-Type': 'application/json' }, body: '{"target_id":"nonprod"}' });
    assert.equal(response.status, 502);
    const body = await response.text();
    assert.match(body, /no request was automatically replayed/);
    assert.doesNotMatch(body, /SENSITIVE-TOKEN-DETAIL|server.workload.token/);
  });
  assert.equal(calls, 1);
});

test('backend redirects are not followed to another origin', async () => {
  let calls = 0;
  await withServer({ fetchImpl: async () => { calls++; return new Response(null, { status: 302, headers: { Location: 'https://attacker.example' } }); } }, async (url) => {
    const response = await fetch(url + '/api/auth/me', { headers: { Authorization: userToken } });
    assert.equal(response.status, 502);
    assert.equal(response.headers.get('location'), null);
  });
  assert.equal(calls, 1);
});

test('only built static files are served; private files and credentials are not exposed', async () => {
  await withServer({}, async (url) => {
    const page = await fetch(url + '/');
    assert.match(await page.text(), /Private preview/);
    assert.match(page.headers.get('content-security-policy') || '', /script-src 'self' 'sha256-/);
    assert.equal(page.headers.get('x-frame-options'), 'DENY');
    const hidden = await fetch(url + '/.env');
    assert.doesNotMatch(await hidden.text(), /SENTINEL-SECRET/);
    const health = await fetch(url + '/healthz');
    assert.deepEqual(await health.json(), { status: 'ok' });
  });
});
