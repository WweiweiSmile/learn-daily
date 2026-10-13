import { useEffect } from 'react';
import { useRouter } from '@tarojs/taro';

import { getAccessToken } from '../utils/authStorage';
import { startSSO } from '../utils/sso';

/**
 * 页面级登录守卫。
 *
 * 判据只看**本地有没有 access token**，不再维护一份响应式状态 ——
 * 登出和令牌失效都是整页跳转（startSSO / globalLogout），页面根本不会
 * 带着旧状态继续渲染，所以没有"要让 React 知道"的时机。
 *
 * token 存在但已过期的情况这里不管：那种由请求层的 401 自动续期兜底。
 *
 * 没有白名单了：以前需要它是因为有个专门的回调页，而它渲染的那一刻用户
 * 恰恰还没有登录态。现在票据由入口处的 TicketHandler 处理完才放行，
 * 守卫跑到的时候要么已登录、要么真该跳登录，不需要给谁开例外
 *
 * 用法：在页面组件顶层调用一次即可。
 */
export function useRequireAuth(): void {
  const router = useRouter();
  const currentPath = router.path;

  useEffect(() => {
    if (getAccessToken()) return;
    // 没登录 → 跳认证中心做 SSO。**当前这一页就是落点**：
    // startSSO 会把它拼成 redirect_uri 带上，登录完原样跳回来
    startSSO();
  }, [currentPath]);
}
