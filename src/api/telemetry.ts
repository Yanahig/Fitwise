/**
 * 前端诊断埋点：出问题时用来还原"用户当时在哪、点了什么、什么状态"。
 *
 * 三条规矩（和后端 `models.Event` 一一对应）：
 * 1. **只记元数据** —— 材料原文、需求描述、聊天内容、请求体都不进这里；
 * 2. **失败静默** —— 上报不上去就丢掉，绝不弹提示、绝不重试打扰用户；
 * 3. **不接第三方** —— 只发到自己的后端（`POST /api/events`），数据留在自己的库里
 *    （产品的承诺是"材料不出内网"，诊断数据也一样）。
 *
 * 五个事件：`client_boot` / `page_view` / `api_failed` / `action_finished` / `client_error`。
 */

import { API_BASE, TOKEN_KEY } from './base';

/** 攒多久发一次；满了就立刻发 */
const FLUSH_MS = 4000;
const MAX_BUFFER = 30;

type Value = string | number | boolean | null;
type Payload = Record<string, Value>;

interface Entry {
  name: string;
  payload: Payload;
  /** 事件发生那一刻所在的项目：不能等到上报时再算，否则"在 A 项目出错、切回 B 项目"会记错项目 */
  projectId: number | null;
}

let buffer: Entry[] = [];
let timer: number | null = null;
let currentRoute = '';
let routeEnteredAt = Date.now();

function routeOf(): string {
  return window.location.hash.replace(/^#/, '') || '/';
}

function projectIdFromRoute(): number | null {
  const matched = window.location.hash.match(/\/projects\/(\d+)/);
  return matched ? Number(matched[1]) : null;
}

/** 记一条事件。任何时候都不抛错 —— 埋点坏了是埋点的事，不能让用户看到。 */
export function track(name: string, payload: Payload = {}): void {
  try {
    buffer.push({ name, payload, projectId: projectIdFromRoute() });
    if (buffer.length >= MAX_BUFFER) {
      void flush();
    } else if (timer === null) {
      timer = window.setTimeout(() => void flush(), FLUSH_MS);
    }
  } catch {
    /* 静默 */
  }
}

/**
 * 页面切换：记下"去了哪一页、从哪来、上一页停了多久"。
 * 排查"他在哪一步卡住"时最有用的一条 —— 用户说"我点不动"，先看他停在哪、停了多久。
 */
export function trackPageView(route = routeOf()): void {
  if (route === currentRoute) return;
  const now = Date.now();
  track('page_view', {
    route,
    from: currentRoute || '(first)',
    seconds: Math.round((now - routeEnteredAt) / 1000),
  });
  currentRoute = route;
  routeEnteredAt = now;
}

/** 把缓冲区发出去。失败静默：诊断数据丢了就丢了，绝不重试、绝不弹提示。 */
export async function flush(): Promise<void> {
  if (timer !== null) {
    window.clearTimeout(timer);
    timer = null;
  }
  if (!buffer.length) return;
  const events = buffer;
  buffer = [];
  try {
    const token = window.localStorage.getItem(TOKEN_KEY);
    await fetch(`${API_BASE}/api/events`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({
        events: events.map((item) => ({
          name: item.name,
          payload: item.payload,
          project_id: item.projectId,
        })),
      }),
      keepalive: true,
    });
  } catch {
    /* 静默 */
  }
}

/** 装上全局钩子：启动信息、前端崩了、页面切走时把缓冲区刷出去。App 启动时调一次。 */
export function installDiagnostics(): void {
  track('client_boot', {
    build: __BUILD_ID__,
    api: API_BASE,
    route: routeOf(),
    ua: navigator.userAgent.slice(0, 120),
    viewport: `${window.innerWidth}x${window.innerHeight}`,
  });

  window.addEventListener('error', (event) => {
    track('client_error', {
      kind: 'error',
      message: String(event.message ?? '').slice(0, 120),
      source: String(event.filename ?? '').slice(0, 80),
    });
  });

  window.addEventListener('unhandledrejection', (event) => {
    const reason = event.reason as { message?: string } | undefined;
    track('client_error', {
      kind: 'unhandledrejection',
      message: String(reason?.message ?? event.reason ?? '').slice(0, 120),
    });
  });

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') void flush();
  });
}
