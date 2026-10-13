import Taro from '@tarojs/taro';

/**
 * 登录态的本地存储。
 *
 * 单独抽出来是因为「哪些键存在哪」有多处要用（请求层的自动续期、SSO 回调页、
 * 路由守卫），各写一份迟早会漏掉 refresh_token，而漏掉的后果是用户被
 * 莫名其妙登出，且很难查。
 */

const ACCESS_KEY = 'learn_token';
const REFRESH_KEY = 'learn_refresh_token';
const USER_KEY = 'learn_user';

/** 进行中的一次 SSO 登录握手（CSRF 用的 state），见 utils/sso.ts */
const SSO_FLOW_KEY = 'learn_sso_flow';

function read(key: string): string {
  try {
    return Taro.getStorageSync(key) || '';
  } catch {
    return '';
  }
}

function write(key: string, value: string): void {
  try {
    Taro.setStorageSync(key, value);
  } catch (error) {
    console.error(`写本地存储 ${key} 失败:`, error);
  }
}

function remove(key: string): void {
  try {
    Taro.removeStorageSync(key);
  } catch {
    // 清不掉也无所谓，下次写入会覆盖
  }
}

export function getAccessToken(): string | null {
  return read(ACCESS_KEY) || null;
}

export function getRefreshToken(): string | null {
  return read(REFRESH_KEY) || null;
}

export function getUser<T>(): T | null {
  const raw = read(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

export function saveTokens(accessToken: string, refreshToken?: string): void {
  write(ACCESS_KEY, accessToken);
  if (refreshToken) write(REFRESH_KEY, refreshToken);
}

export function saveUser(user: unknown): void {
  write(USER_KEY, JSON.stringify(user));
}

/**
 * 清空登录态。
 *
 * 三样必须一起清：只清 access 会留下一个永远换不出新令牌的 refresh，
 * 下次启动会拿它去换、失败、再清一次，多绕一圈
 *
 * ⚠️ **刻意不清 `sso_flow`**。它是"进行中的一次登录握手"，而本函数会在
 * 续期失败时被调用 —— 那一刻常与一次跳转重叠（守卫在跳认证中心，业务请求
 * 同时撞 401），一清就抹掉了回程要比对的 state，表现是"登录成功却提示校验失败"。
 * call-front 真机踩过这个坑
 */
export function clearSession(): void {
  remove(ACCESS_KEY);
  remove(REFRESH_KEY);
  remove(USER_KEY);
}

// ---------- SSO 登录握手 ----------

/**
 * 进行中的一次登录握手。
 *
 * 只剩 state 一个字段了。以前还有一个 `returnTo`（记"用户原本在哪一页"），
 * 现在**目标页面直接由认证中心跳回来时的地址决定** —— 前端把那一页作为
 * `redirect_uri` 传过去，ticket 就拼在那一页的 URL 上（见 utils/sso.ts），
 * 不需要再在本地记一份。少一份状态就少一处能对不上的地方
 */
export interface SSOFlow {
  /** 本次跳转的 CSRF 随机值，回来时必须原样对上 */
  state: string;
}

export function saveSSOFlow(flow: SSOFlow): void {
  write(SSO_FLOW_KEY, JSON.stringify(flow));
}

export function clearSSOFlow(): void {
  remove(SSO_FLOW_KEY);
}

/** 读一次就清掉 —— 同一个 state 不能用第二次 */
export function takeSSOFlow(): SSOFlow | null {
  const raw = read(SSO_FLOW_KEY);
  remove(SSO_FLOW_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as SSOFlow;
  } catch {
    return null;
  }
}
