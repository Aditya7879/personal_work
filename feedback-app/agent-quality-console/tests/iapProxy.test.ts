import assert from 'node:assert/strict';
import { generateKeyPairSync, sign } from 'node:crypto';
import { once } from 'node:events';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import test from 'node:test';
import { createApp, createIapVerifier } from '../server.mjs';

const audience = '/projects/411502743425/locations/europe-west1/services/neo-feedback-ui';
const origin = 'https://feedback-ui.run.app';
const assertion = 'complete.signed.assertion';

function identityFixture() {
  const { privateKey, publicKey } = generateKeyPairSync('ec', { namedCurve: 'P-256' });
  const pubkeys = { 'test-iap-key': publicKey.export({ type: 'spki', format: 'pem' }).toString() };
  const jwt = (changes: Record<string, unknown> = {}) => {
    const now = Math.floor(Date.now() / 1000);
    const header = Buffer.from(JSON.stringify({ alg: 'ES256', kid: 'test-iap-key' })).toString('base64url');
    const payload = Buffer.from(JSON.stringify({ iss: 'https://cloud.google.com/iap', aud: audience,
      sub: 'accounts.google.com:verified-user', email: 'reviewer@company.example', iat: now, exp: now + 600, ...changes })).toString('base64url');
    const signature = sign('sha256', Buffer.from(header + '.' + payload), { key: privateKey, dsaEncoding: 'ieee-p1363' }).toString('base64url');
    return header + '.' + payload + '.' + signature;
  };
  return { pubkeys, jwt };
}

test('IAP signatures, exact resource audience and company identity are verified with cached Google keys', async () => {
  const { pubkeys, jwt } = identityFixture(); let keyReads = 0;
  const verify = createIapVerifier(audience, { domains: ['company.example'], getPublicKeys: async () => { keyReads++; return { pubkeys }; } });
  assert.equal((await verify(jwt())).email, 'reviewer@company.example');
  assert.equal((await verify(jwt())).sub, 'accounts.google.com:verified-user');
  assert.equal(keyReads, 1);
  for (const changes of [{ aud: '/projects/other/locations/elsewhere/services/attacker' }, { iss: 'https://attacker.example' },
    { email: 'person@outside.example' }, { sub: 'service-account:runtime' }, { exp: 1 },
    { iat: Math.floor(Date.now() / 1000) + 60 }, { exp: Math.floor(Date.now() / 1000) - 60 }]) {
    await assert.rejects(verify(jwt(changes)));
  }
  const token = jwt(); const pieces = token.split('.');
  await assert.rejects(verify(pieces[0] + '.' + pieces[1] + '.'));
  pieces[2] = (pieces[2][0] === 'A' ? 'B' : 'A') + pieces[2].slice(1);
  await assert.rejects(verify(pieces.join('.')));
  assert.throws(() => createIapVerifier('https://arbitrary.example'));
});

async function withIapServer(options: { fetchImpl?: typeof fetch; getWorkloadToken?: () => Promise<string> }, run: (url: string) => Promise<void>) {
  const directory = await mkdtemp('/tmp/opencode/feedback-iap-proxy-test-');
  await writeFile(join(directory, 'index.html'), '<html>Authenticated app shell</html>');
  const app = createApp({ backendUrl: 'https://private-feedback-api.run.app', frontendOrigin: origin, distDir: directory,
    iapAudience: audience, verifyIapAssertion: async (value: string) => { if (value !== assertion) throw new Error('PRIVATE-ASSERTION-DETAIL'); },
    getWorkloadToken: async () => 'runtime.workload.token', fetchImpl: async () => Response.json({ role: 'reviewer' }), ...options });
  const server = app.listen(0, '127.0.0.1'); await once(server, 'listening');
  const address = server.address(); assert.ok(address && typeof address !== 'string');
  try { await run(`http://127.0.0.1:${address.port}`); }
  finally { server.closeAllConnections(); await new Promise<void>((resolve) => server.close(() => resolve())); await rm(directory, { recursive: true, force: true }); }
}

test('IAP frontend fails closed for anonymous or forged traffic even if its outer Cloud Run setting is public', async () => {
  let workloadCalls = 0; let backendCalls = 0;
  await withIapServer({ getWorkloadToken: async () => { workloadCalls++; return 'runtime'; }, fetchImpl: async () => { backendCalls++; return Response.json({}); } }, async (url) => {
    for (const path of ['/', '/auth/config', '/api/auth/me']) {
      assert.equal((await fetch(url + path)).status, 401);
      const bad = await fetch(url + path, { headers: { 'X-Goog-IAP-JWT-Assertion': 'forged', 'X-Goog-Authenticated-User-Email': 'accounts.google.com:reviewer@company.example' } });
      assert.equal(bad.status, 401); assert.doesNotMatch(await bad.text(), /PRIVATE-ASSERTION-DETAIL/);
    }
    assert.equal((await fetch(url + '/healthz')).status, 200);
  });
  assert.equal(workloadCalls, 0); assert.equal(backendCalls, 0);
});

test('IAP forwarding uses only the verified signed assertion plus the runtime workload token', async () => {
  let seen: Headers | undefined;
  await withIapServer({ fetchImpl: async (_url, init) => { seen = new Headers(init?.headers); return Response.json({ role: 'reviewer' }); } }, async (url) => {
    const headers = { 'X-Goog-IAP-JWT-Assertion': assertion, 'X-Feedback-IAP-Assertion': 'FORGED-FORWARDED',
      Authorization: 'Bearer FORGED-USER', 'X-Feedback-User-Authorization': 'Bearer FORGED-USER',
      'X-Feedback-Demo-Authorization': 'Bearer FORGED-DEMO', 'X-Serverless-Authorization': 'Bearer FORGED-WORKLOAD', Cookie: 'iap=cookie' };
    const response = await fetch(url + '/api/auth/me', { headers });
    assert.equal(response.status, 200); assert.equal(response.headers.get('x-feedback-iap-assertion'), null);
    assert.deepEqual(await (await fetch(url + '/auth/config', { headers })).json(), { managedBrowserSignIn: true });
  });
  assert.ok(seen);
  assert.equal(seen.get('X-Feedback-IAP-Assertion'), assertion);
  assert.equal(seen.get('X-Serverless-Authorization'), 'Bearer runtime.workload.token');
  for (const name of ['Authorization', 'X-Feedback-User-Authorization', 'X-Feedback-Demo-Authorization', 'Cookie', 'X-Goog-Authenticated-User-Email']) assert.equal(seen.get(name), null);
});

test('IAP cookie-authenticated mutations require exact Origin and a same-origin action header', async () => {
  let calls = 0;
  await withIapServer({ fetchImpl: async () => { calls++; return Response.json({}); } }, async (url) => {
    const headers = { 'X-Goog-IAP-JWT-Assertion': assertion, 'Content-Type': 'application/json' };
    const variants: Array<Record<string, string>> = [{}, { Origin: origin }, { Origin: 'https://attacker.example', 'X-Feedback-CSRF': '1' },
      { Origin: 'http://localhost:3000', 'X-Feedback-CSRF': '1' }, { Origin: origin, 'X-Feedback-CSRF': '1', 'Sec-Fetch-Site': 'cross-site' }];
    for (const extra of variants) {
      assert.equal((await fetch(url + '/api/access-grants', { method: 'POST', headers: { ...headers, ...extra }, body: '{}' })).status, 403);
    }
    assert.equal(calls, 0);
    assert.equal((await fetch(url + '/api/access-grants', { method: 'POST', headers: { ...headers, Origin: origin, 'X-Feedback-CSRF': '1' }, body: '{}' })).status, 200);
  });
  assert.equal(calls, 1);
});
