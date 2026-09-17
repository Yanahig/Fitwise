/**
 * 前后端的两个约定值，单独放一个模块。
 *
 * 为什么单独放：`client.ts`（发业务请求）与 `telemetry.ts`（发诊断事件）都要用它们，
 * 而 client 里又要调 telemetry 记失败 —— 放一起会形成循环 import，运行时容易踩坑。
 */

export const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? 'http://127.0.0.1:8000';
export const TOKEN_KEY = 'fitwise.token';
export const USER_KEY = 'fitwise.user';
