import express from 'express';
import { GoogleAuth, OAuth2Client } from 'google-auth-library';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { Readable } from 'node:stream';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));

export function validateBackendUrl(value, allowLoopback = false) {
  const url = new URL(value);
  const loopback = allowLoopback && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
  if (url.username || url.password || url.search || url.hash || url.pathname !== '/' ||
      !(url.protocol === 'https:' && url.hostname.endsWith('.run.app')) && !(loopback && url.protocol === 'http:')) {
    throw new Error('A fixed, server-owned Cloud Run backend origin is required');
  }
  return url.origin;
}

export function browserOriginAllowed(origin, frontendOrigin) {
  if (!origin) return true; // CLI clients still need the complete IAM identity token.
  try {
    const url = new URL(origin);
    return origin === frontendOrigin || (url.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname) && !url.username && !url.password && url.pathname === '/' && !url.search && !url.hash);
  } catch { return false; }
}

function workloadTokenProvider(audience) {
  const auth = new GoogleAuth();
  let clientPromise;
  let cached;
  let pending;
  return async () => {
    if (cached?.until > Date.now()) return cached.token;
    if (pending) return pending;
    pending = (async () => {
      clientPromise ||= auth.getIdTokenClient(audience);
      const client = await clientPromise;
      const token = await client.idTokenProvider.fetchIdToken(audience);
      const claims = JSON.parse(Buffer.from(token.split('.')[1], 'base64url').toString());
      const until = Math.min(Number(claims.exp) * 1000 - 60_000, Date.now() + 300_000);
      if (!Number.isFinite(until) || until <= Date.now()) throw new Error('Invalid workload identity token');
      cached = { token, until };
      return token;
    })().finally(() => { pending = undefined; });
    return pending;
  };
}

/**
 * @param {string} audience
 * @param {{getPublicKeys?: () => Promise<{pubkeys: Record<string, string>, res?: any}>, domains?: string[]}} options
 */
export function createIapVerifier(audience, { getPublicKeys = undefined, domains = ['loreal.com'] } = {}) {
  if (!/^\/projects\/\d+\/locations\/[a-z0-9-]+\/services\/[a-z0-9-]+$/.test(audience)) throw new Error('An exact Cloud Run IAP audience is required');
  const client = new OAuth2Client();
  const loadKeys = getPublicKeys || (() => client.getIapPublicKeys());
  let cached; let pending;
  const keys = async () => {
    if (cached?.until > Date.now()) return cached.pubkeys;
    pending ||= (async () => {
      const { pubkeys, res } = await loadKeys();
      const maxAge = Number(res?.headers?.get?.('cache-control')?.match(/max-age=(\d+)/)?.[1] || 300);
      cached = { pubkeys, until: Date.now() + Math.min(600, Math.max(0, maxAge)) * 1000 };
      return pubkeys;
    })().finally(() => { pending = undefined; });
    return pending;
  };
  return async (assertion) => {
    if (typeof assertion !== 'string' || assertion.length > 16384 || !/^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/.test(assertion)) throw new Error('A signed IAP assertion is required');
    const ticket = await client.verifySignedJwtWithCertsAsync(assertion, await keys(), audience, ['https://cloud.google.com/iap']);
    const payload = ticket.getPayload();
    if (!payload) throw new Error('An IAP identity payload is required');
    const now = Date.now() / 1000;
    const email = String(payload?.email || '').trim().toLowerCase();
    if (!/^accounts.google.com:[^\s:]+$/.test(String(payload?.sub || '')) || email.split('@').length !== 2 || !domains.includes(email.split('@')[1]) ||
        Number(payload.exp) <= now - 30 || Number(payload.iat) > now + 30 || Number(payload.exp) - Number(payload.iat) > 660) throw new Error('A current company IAP identity is required');
    return payload;
  };
}

/**
 * @param {{backendUrl: string, frontendOrigin?: string, distDir?: string, getWorkloadToken?: () => Promise<string>, fetchImpl?: typeof fetch, allowLoopback?: boolean,
 * iapAudience?: string, iapDomains?: string[], verifyIapAssertion?: (assertion: string) => Promise<unknown>, roleDemoEnabled?: boolean, demoAdmin?: boolean}} options
 */
export function createApp({ backendUrl, frontendOrigin, distDir = join(here, 'dist'), getWorkloadToken, fetchImpl = fetch, allowLoopback = false,
  iapAudience = '', iapDomains = ['loreal.com'], verifyIapAssertion = undefined, roleDemoEnabled = false, demoAdmin = false }) {
  const backend = validateBackendUrl(backendUrl, allowLoopback);
  if (demoAdmin || process.env.FEEDBACK_DEMO_ADMIN_ENABLED === 'true') throw new Error('Standalone demo password login is retired; use the in-app Demo Admin role');
  if (roleDemoEnabled && (!iapAudience || process.env.K_SERVICE && process.env.K_SERVICE !== 'neo-feedback-ui')) throw new Error('Demo views require the existing IAP-authenticated feedback app');
  const getToken = getWorkloadToken || workloadTokenProvider(backend);
  const verifyIap = iapAudience ? verifyIapAssertion || createIapVerifier(iapAudience, { domains: iapDomains }) : null;
  if (iapAudience) {
    const origin = new URL(frontendOrigin);
    if (origin.origin !== frontendOrigin || (origin.protocol !== 'https:' && !(allowLoopback && origin.protocol === 'http:' && ['localhost', '127.0.0.1'].includes(origin.hostname)))) throw new Error('A fixed frontend origin is required for IAP CSRF protection');
  }
  const index = readFileSync(join(distDir, 'index.html'), 'utf8');
  const inlineHashes = [...index.matchAll(/<script\b(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)].map((match) => `'sha256-${createHash('sha256').update(match[1]).digest('base64')}'`);
  const app = express();
  app.disable('x-powered-by');
  app.use((_req, res, next) => {
    res.set({ 'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer', 'X-Frame-Options': 'DENY',
      'Content-Security-Policy': `default-src 'self'; script-src 'self' ${inlineHashes.join(' ')}; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'` });
    next();
  });
  app.get('/healthz', (_req, res) => res.json({ status: 'ok' }));
  if (verifyIap) app.use(async (req, res, next) => {
    res.set('Cache-Control', 'private, no-store');
    try {
      const assertion = req.get('x-goog-iap-jwt-assertion');
      if (!assertion) return res.status(401).json({ detail: 'Google browser sign-in is required' });
      await verifyIap(assertion);
      req.feedbackIapAssertion = assertion;
      next();
    } catch { res.status(401).set('Cache-Control', 'no-store').json({ detail: 'A valid signed company IAP identity is required' }); }
  });
  app.get('/auth/config', (_req, res) => res.set('Cache-Control', 'no-store').json({ managedBrowserSignIn: Boolean(verifyIap) }));
  app.use('/api', express.raw({ type: () => true, limit: '2mb' }), async (req, res) => {
    res.set('Cache-Control', 'private, no-store');
    if (!['GET', 'HEAD', 'POST', 'PATCH', 'OPTIONS'].includes(req.method)) return res.status(405).json({ detail: 'Method not allowed' });
    if (!browserOriginAllowed(req.get('origin'), frontendOrigin)) return res.status(403).json({ detail: 'Browser origin is not permitted' });
    const demoControl = req.path.startsWith('/demo-admin/');
    const demoMarker = req.get('x-feedback-demo-view');
    if (demoMarker !== undefined && demoMarker !== '1') return res.status(400).json({ detail: 'Invalid demo-view marker' });
    if ((demoMarker || demoControl) && (!roleDemoEnabled || !req.feedbackIapAssertion) && req.path !== '/demo-admin/logout') return res.status(404).json({ detail: 'Demo views are not enabled' });
    if (verifyIap && !['GET', 'HEAD', 'OPTIONS'].includes(req.method) &&
        (req.get('origin') !== frontendOrigin || req.get('x-feedback-csrf') !== '1' || req.get('sec-fetch-site') === 'cross-site' ||
         (demoControl || demoMarker) && req.get('x-requested-with') !== 'XMLHttpRequest')) {
      return res.status(403).json({ detail: 'A same-origin application action is required' });
    }
    const authorization = req.get('x-feedback-user-authorization') || req.get('authorization') || '';
    const demoCookies = roleDemoEnabled && req.feedbackIapAssertion ? String(req.get('cookie') || '').split(';').map(value => value.trim()).filter(value => value.startsWith('neo_role_demo=')) : [];
    const demoCookie = demoCookies.length === 1 && demoCookies[0].length <= 2062 && /^neo_role_demo=[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{43}$/.test(demoCookies[0]) ? demoCookies[0] : undefined;
    if (demoCookies.length && !demoCookie && req.path === '/auth/me' && !demoMarker) res.clearCookie('neo_role_demo', { httpOnly: true, secure: frontendOrigin.startsWith('https://'), sameSite: 'strict', path: '/' });
    if (demoMarker && !demoCookie) return res.status(401).json({ detail: 'Demo view expired; exit demo and choose again' });
    if (demoCookies.length && !demoMarker && !demoControl && req.path !== '/auth/me') return res.status(409).json({ detail: 'Exit demo before accessing the live workspace' });
    // The loopback deployment helper supplies Authorization (not the stripped
    // X-Serverless-Authorization used by the stock gcloud proxy).
    if (!req.feedbackIapAssertion && !/^Bearer [A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/i.test(authorization)) {
      return res.status(401).json({ detail: 'Connect using deploy/proxy.py so the complete signed Google user token is preserved' });
    }
    try {
      const target = new URL(backend + req.originalUrl);
      if (target.origin !== backend || !target.pathname.startsWith('/api/')) return res.status(400).json({ detail: 'Invalid API path' });
      const headers = new Headers({ 'X-Serverless-Authorization': `Bearer ${await getToken()}` });
      if (roleDemoEnabled && req.feedbackIapAssertion) {
        if (demoCookie) headers.set('Cookie', demoCookie);
        if (demoMarker) headers.set('X-Feedback-Demo-View', '1');
      }
      if (req.feedbackIapAssertion) headers.set('X-Feedback-IAP-Assertion', req.feedbackIapAssertion);
      else { headers.set('Authorization', authorization); headers.set('X-Feedback-User-Authorization', authorization); }
      for (const name of ['accept', 'content-type', 'cache-control', ...(!verifyIap ? ['x-feedback-demo-authorization'] : []),
        ...(verifyIap && (roleDemoEnabled || req.path === '/demo-admin/logout') ? ['origin', 'x-feedback-csrf', 'x-requested-with', 'sec-fetch-site'] : [])]) if (req.get(name)) headers.set(name, req.get(name));
      // Only a verified IAP request may forward the one role-demo cookie. Never
      // forward caller identity/role/workload headers or replay a mutation.
      const upstream = await fetchImpl(target, { method: req.method, headers, body: ['GET', 'HEAD'].includes(req.method) || !req.body?.length ? undefined : req.body,
        redirect: 'manual', signal: AbortSignal.timeout(605_000) });
      if (upstream.status >= 300 && upstream.status < 400) return res.status(502).json({ detail: 'Unexpected backend redirect' });
      res.status(upstream.status);
      for (const name of ['content-type', 'x-feedback-cache']) if (upstream.headers.get(name)) res.set(name, upstream.headers.get(name));
      if (verifyIap && (roleDemoEnabled || req.path === '/demo-admin/logout')) {
        const cookies = typeof upstream.headers.getSetCookie === 'function' ? upstream.headers.getSetCookie() : [upstream.headers.get('set-cookie')].filter(Boolean);
        const allowed = cookies.filter(value => /^neo_role_demo=(?:[A-Za-z0-9_-]+\.[A-Za-z0-9_-]{43}|"")?;/.test(value) && !/;\s*Domain\s*=|[\r\n]/i.test(value));
        if (allowed.length) res.setHeader('Set-Cookie', allowed);
      }
      if (!upstream.body) return res.end();
      const body = Readable.fromWeb(upstream.body);
      body.on('error', () => res.destroy());
      res.on('close', () => body.destroy());
      body.pipe(res);
    } catch {
      if (!res.headersSent) res.status(502).json({ detail: 'The private backend is unavailable; no request was automatically replayed' });
      else res.destroy();
    }
  });
  app.use('/assets', express.static(join(distDir, 'assets'), { dotfiles: 'deny', immutable: true, maxAge: '1y' }));
  app.get('*', (_req, res) => { res.set('Cache-Control', 'no-store'); res.type('html').send(index); });
  app.use((error, _req, res, _next) => res.status(error?.type === 'entity.too.large' ? 413 : 400).json({ detail: 'Invalid or oversized request' }));
  return app;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const app = createApp({ backendUrl: process.env.FEEDBACK_BACKEND_URL || '', frontendOrigin: process.env.FEEDBACK_FRONTEND_ORIGIN,
    iapAudience: process.env.FEEDBACK_GOOGLE_IAP_AUDIENCE || '',
    iapDomains: (process.env.FEEDBACK_GOOGLE_IAM_DOMAINS || 'loreal.com').split(',').map((value) => value.trim().toLowerCase()).filter(Boolean),
    roleDemoEnabled: process.env.FEEDBACK_ROLE_DEMO_ENABLED === 'true' });
  const server = app.listen(Number(process.env.PORT || 8080), '0.0.0.0');
  server.requestTimeout = 610_000;
}
