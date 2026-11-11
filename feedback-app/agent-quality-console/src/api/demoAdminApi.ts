import { ApiError, AuthUser, clearReadCache } from './feedbackApi';

export type DemoAdminSession = {
  enabled: boolean;
  active: boolean;
  admin?: { username: string; displayName: string };
  personas: AuthUser[];
  user: AuthUser | null;
  realUser: AuthUser;
  simulatedAi: boolean;
};

const base = (import.meta.env?.VITE_API_URL || '').replace(/\/$/, '');

async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${base}/api/demo-admin/${path}`, {
    method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin', cache: 'no-store',
    headers: body === undefined ? { Accept: 'application/json' } : {
      Accept: 'application/json', 'Content-Type': 'application/json',
      'X-Requested-With': 'XMLHttpRequest', 'X-Feedback-CSRF': '1',
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const value = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(typeof value.detail === 'string' ? value.detail : 'Demo administration is unavailable', response.status);
  if (body !== undefined) clearReadCache();
  return value as T;
}

export async function getDemoAdminSession(): Promise<DemoAdminSession> {
  return request('session');
}

export const selectDemoPersona = (email: string) => request<DemoAdminSession>('persona', { email });
export const logoutDemoAdmin = () => request<DemoAdminSession>('logout', {});
export const resetAdminDemo = () => request<{ reset: boolean; seededFeedback: number; session: DemoAdminSession }>('reset', { confirmation: 'RESET DEMO' });
