import Taro from '@tarojs/taro';
import { clearSession, getAccessToken, getRefreshToken, saveTokens } from '../utils/authStorage';
import { startSSO } from '../utils/sso';

const isDev = process.env.NODE_ENV === 'development';

/**
 * learn-daily 的后端返回**裸 JSON**，没有 {code, data} 信封 —— 这点和 call-back
 * 不一样，所以判断成败只看 HTTP 状态码。认证中心那边是带信封的，下面分开处理。
 */
export const BASE_URL = isDev ? '/api/v1' : `${process.env.TARO_APP_BASE_URL}/api/v1`;

/**
 * 认证中心（call-auth）。独立服务，不再由 learn-daily 后端提供登录接口。
 * 开发环境走 dev server 代理，见 config/dev.ts
 */
export const AUTH_BASE_URL = isDev
  ? '/authsvc/api/v1'
  : `${process.env.TARO_APP_AUTH_URL}/api/v1`;

export type RequestOptions = Omit<Taro.request.Option, 'url'>;

/** 带状态码的错误，让调用方能按 401 之类的状态判断，而不是去匹配文案 */
export class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly reason?: string) {
    super(message);
    this.name = 'ApiError';
  }
}

function extractDetail(body: unknown): string {
  if (body && typeof body === 'object') {
    // FastAPI 的原生错误：{detail: "..."}
    if ('detail' in body && typeof (body as { detail?: unknown }).detail === 'string') {
      return (body as { detail: string }).detail;
    }
    // 认证中心的信封：{code, message, error}
    if ('message' in body && typeof (body as { message?: unknown }).message === 'string') {
      return (body as { message: string }).message;
    }
  }
  return '';
}

async function call<T>(
  url: string,
  options: RequestOptions,
  withCredentials: boolean,
): Promise<T> {
  const { method = 'GET', data, ...rest } = options;

  const header: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(rest.header as Record<string, string> | undefined),
  };
  if (withCredentials) {
    const token = getAccessToken();
    if (token) header.Authorization = `Bearer ${token}`;
  }

  const response = await Taro.request({ ...rest, url, method, data, header });
  const body = response.data as Record<string, unknown> | undefined;

  if (response.statusCode >= 200 && response.statusCode < 300) {
    // 认证中心用 {code: 0, data} 信封；自己的后端是裸 JSON。
    // 靠 code 字段是否存在来区分，不用按 URL 硬编码
    if (body && typeof body.code === 'number') {
      if (body.code === 0) return body.data as T;
      throw new ApiError(
        String(body.message || '请求失败'),
        body.code,
        typeof body.error === 'string' ? body.error : undefined,
      );
    }
    return response.data as T;
  }

  throw new ApiError(
    extractDetail(body) || `请求失败（${response.statusCode}）`,
    response.statusCode,
    body && typeof body.error === 'string' ? body.error : undefined,
  );
}

/** 打认证中心。不带凭证 —— 换票、刷新都不需要 access token */
export async function requestAuth<T>(url: string, options: RequestOptions = {}): Promise<T> {
  return call<T>(`${AUTH_BASE_URL}${url}`, options, false);
}

/**
 * 打认证中心**且带登录态**的入口。目前只有 `/auth/me` 用。
 *
 * 单独开一个入口而不是给 requestAuth 加开关：认证域的 401 和业务域的 401
 * 处理方式不同 —— 业务域走 refresh 续期，认证域自己的 401 没有可续的东西
 */
export async function requestAuthAuthed<T>(url: string, options: RequestOptions = {}): Promise<T> {
  return call<T>(`${AUTH_BASE_URL}${url}`, options, true);
}

/**
 * 续期。**必须串行化**：并发请求同时收到 401 时只能触发一次 refresh。
 *
 * 不串行化的话，第二个请求会拿着已经被轮换掉的 refresh token 去换 ——
 * 认证中心会把它判定为「重放」（它无法区分客户端并发和 token 被盗），
 * 从而吊销该用户全部登录态，用户直接被踢下线
 */
let refreshing: Promise<string> | null = null;

export function refreshAccessToken(): Promise<string> {
  if (!refreshing) {
    refreshing = (async () => {
      try {
        const refreshToken = getRefreshToken();
        if (!refreshToken) throw new Error('本地没有 refresh token');

        const data = await requestAuth<{ access_token: string; refresh_token: string }>(
          '/auth/refresh',
          { method: 'POST', data: { refresh_token: refreshToken } },
        );
        saveTokens(data.access_token, data.refresh_token);
        return data.access_token;
      } finally {
        // 放在 finally：失败也要放开，否则一次失败会把这个 promise 永久钉死
        refreshing = null;
      }
    })();
  }
  return refreshing;
}

export async function request<T>(url: string, options: RequestOptions = {}): Promise<T> {
  try {
    return await call<T>(`${BASE_URL}${url}`, options, true);
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) {
      // access token 只有 15 分钟，撞上过期是常态。先静默续期再重放一次；
      // **只重放一次**，续期也失败就说明真登不上了，再循环只会打转
      const fresh = await refreshAccessToken().catch(() => null);
      if (fresh) return call<T>(`${BASE_URL}${url}`, options, true);

      clearSession();
      // 跳认证中心重新走 SSO。**不能只在应用内跳某页**：认证域可能还留着
      // 会话 cookie，只有走 /sso 才能判断是"直接换票"还是"要重新登录"
      startSSO();
      throw new ApiError('登录已过期，请重新登录', 401, 'token_invalid');
    }
    throw error;
  }
}

/** Taro 的网络错误挂的是 errMsg 而不是 message，统一成一个能直接显示的字符串。 */
export function errorText(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  const errMsg = (error as { errMsg?: string } | null)?.errMsg;
  return errMsg || '请求失败';
}
