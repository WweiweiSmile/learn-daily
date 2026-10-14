import { useEffect } from 'react';
import { useRouter } from '@tarojs/taro';

import { getAccessToken } from '../utils/authStorage';
import { awaitPendingTicket, startSSO } from '../utils/sso';

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
 * 恰恰还没有登录态。现在票据由入口处的 TicketHandler 处理，守卫跑到的时候
 * 要么已登录、要么真该跳登录，不需要给谁开例外
 *
 * ## 为什么判定之前要先 `awaitPendingTicket()`
 *
 * SSO 回程那一页现在**真的会挂载**（票据处理不能再靠"不渲染 children"
 * 挡住 Taro 的页面挂载，见 TicketHandler 里的说明），所以本 hook 会在
 * **票据还在换**的时候跑起来。这时候直接判"没登录"就跳，
 * `startSSO()` 会把回程地址连着票据整个替换掉 —— 这次登录白跑。
 *
 * 等一等是安全的，而且两种结果都对：
 *   - 换成了 → 本地已经有令牌，直接放行
 *   - 没换成（票据过期、被用过、网络断）→ 才真的该跳
 *     （TicketHandler 在失败路径上已经清掉本地态）
 *
 * 用法：在页面组件顶层调用一次即可。
 */
export function useRequireAuth(): void {
  const router = useRouter();
  const currentPath = router.path;

  useEffect(() => {
    if (getAccessToken()) return;

    let cancelled = false;

    // 没登录 → 跳认证中心做 SSO。**当前这一页就是落点**：
    // startSSO 会把它拼成 redirect_uri 带上，登录完原样跳回来
    void awaitPendingTicket().then(() => {
      if (cancelled) return;
      // 读**最新**的本地态，而不是前面那次判断的结果：换票成功的话
      // 令牌已经在这几十毫秒里写进去了
      if (getAccessToken()) return;
      startSSO();
    });

    return () => {
      cancelled = true;
    };
  }, [currentPath]);
}
