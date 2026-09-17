/** 统一 API 客户端：注入 JWT、解析错误、401 自动登出、失败时记一条诊断事件。 */

import { API_BASE, TOKEN_KEY, USER_KEY } from './base';
import { track } from './telemetry';

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export const session = {
  get token(): string | null {
    return window.localStorage.getItem(TOKEN_KEY);
  },
  get user() {
    const raw = window.localStorage.getItem(USER_KEY);
    return raw ? (JSON.parse(raw) as { id: number; name: string; role: string; email: string }) : null;
  },
  save(token: string, user: unknown) {
    window.localStorage.setItem(TOKEN_KEY, token);
    window.localStorage.setItem(USER_KEY, JSON.stringify(user));
  },
  clear() {
    window.localStorage.removeItem(TOKEN_KEY);
    window.localStorage.removeItem(USER_KEY);
  },
};

type RequestOptions = {
  method?: string;
  body?: unknown;
  formData?: FormData;
  signal?: AbortSignal;
};

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = {};
  if (session.token) headers.Authorization = `Bearer ${session.token}`;
  let body: BodyInit | undefined;
  if (options.formData) {
    body = options.formData;
  } else if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(options.body);
  }

  let response: Response;
  const startedAt = Date.now();
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method: options.method ?? (body ? 'POST' : 'GET'),
      headers,
      body,
      signal: options.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    trackFailure(path, 'network', startedAt);
    throw new ApiError(0, '连接不上 Fitwise 服务，请稍后重试或联系管理员');
  }

  if (response.status === 401) {
    trackFailure(path, 'session_expired', startedAt, 401);
    session.clear();
    if (!window.location.hash.startsWith('#/login')) window.location.hash = '/login';
    throw new ApiError(401, '登录状态已过期，请重新登录');
  }

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;
  if (!response.ok) {
    const detail = (payload && (payload.detail || payload.message)) || `请求失败（${response.status}）`;
    trackFailure(path, 'http', startedAt, response.status, typeof detail === 'string' ? detail : '');
    throw new ApiError(response.status, typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return payload as T;
}

/**
 * 记一条接口失败。
 *
 * 两道防线：**不记请求体**（里面可能有需求描述这类正文），**不记埋点接口自己**
 * （上报失败再触发上报，会变成死循环）。
 */
function trackFailure(path: string, kind: string, startedAt: number, status?: number, message?: string): void {
  if (path.startsWith('/api/events')) return;
  track('api_failed', {
    path: path.split('?')[0].slice(0, 80),
    kind,
    status: status ?? 0,
    ms: Date.now() - startedAt,
    message: (message ?? '').slice(0, 120),
  });
}
