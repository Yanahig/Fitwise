/** 统一 API 客户端：注入 JWT、解析错误、401 自动登出。 */

const BASE_URL = (import.meta.env.VITE_API_BASE as string | undefined) ?? 'http://127.0.0.1:8000';
const TOKEN_KEY = 'fitwise.token';
const USER_KEY = 'fitwise.user';

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
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      method: options.method ?? (body ? 'POST' : 'GET'),
      headers,
      body,
      signal: options.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError(0, '连接不上 Fitwise 服务，请稍后重试或联系管理员');
  }

  if (response.status === 401) {
    session.clear();
    if (!window.location.hash.startsWith('#/login')) window.location.hash = '/login';
    throw new ApiError(401, '登录状态已过期，请重新登录');
  }

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;
  if (!response.ok) {
    const detail = (payload && (payload.detail || payload.message)) || `请求失败（${response.status}）`;
    throw new ApiError(response.status, typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return payload as T;
}
