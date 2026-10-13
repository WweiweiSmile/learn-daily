import { requestAuth, requestAuthAuthed } from './request';

export interface UserInfo {
  id: number;
  username: string;
  nickname: string;
  avatar: string;
  role: 'user' | 'admin';
}

/** 换票/续期的统一响应（认证中心对换票和登录返回同一个结构） */
export interface TokenResponse {
  access_token: string;
  /** 只在签发时返回这一次。丢了就只能重新登录，所以必须持久化 */
  refresh_token: string;
  expires_in: number;
  token_type: string;
  user?: UserInfo;
}

/**
 * 认证 API。全部打**认证中心 call-auth**（:8020）——
 * learn-daily 的后端只验签，不提供登录接口。
 *
 * 注意这里**没有 login/register/logout**：登录页已经搬到认证中心，
 * 本应用不再直接提交账号密码；登出走全局退出（`utils/sso.ts` 的
 * `globalLogout`，整页跳认证中心），不走 XHR。
 */
export const authApi = {
  /** 用一次性票据换令牌。这是 SSO 回调页唯一要做的事 */
  exchangeTicket: (ticket: string, clientId: string) =>
    requestAuth<TokenResponse>('/auth/ticket', {
      method: 'POST',
      data: { ticket, client_id: clientId },
    }),

  /** 当前登录用户。要带 Bearer，所以走带登录态的入口 */
  me: () => requestAuthAuthed<UserInfo>('/auth/me'),
};
