import { useEffect, useState } from 'react';
import { Text, View } from '@tarojs/components';

import { authApi } from '../services/authApi';
import { clearSession, saveTokens, saveUser } from '../utils/authStorage';
import {
  CLIENT_ID,
  cleanAuthParams,
  isNavigating,
  readCallbackParams,
  registerTicketExchange,
  verifyState,
} from '../utils/sso';

interface TicketHandlerProps {
  children: React.ReactNode;
}

/**
 * 全局票据处理。挂在应用入口，包住所有页面（见 app.tsx）。
 *
 * 存在的理由：SSO 回程时票据是拼在**用户要去的那一页**的地址上的
 *（`/pages/library/index?ticket=..&state=..`），不再是拼在一个固定的回调页上。
 * 所以要有一个全局的东西把票换掉。
 *
 * 它做三件事，顺序不能换（见设计文档 §8.4）：
 *   1. 比对 state —— 不比对就等于可以被登成别人的账号
 *   2. 用票据换令牌并存下来
 *   3. 清掉地址栏上的 ticket，然后就地放行（**不跳转**，人已经在目标页了）
 *
 * ## children 为什么**必须**原样渲染
 *
 * 早先的写法是"换票期间不渲染 children，只渲染一个'正在登录…'占位"，
 * 想借此让页面的路由守卫连跑的机会都没有。**那个写法是错的，会直接崩**：
 *
 * Taro 的 React 运行时把**页面**当作 App 的 children 渲染
 *（`@tarojs/plugin-framework-react` 的运行时代码里：
 * `h(App, props, h(Fragment, null, elements))`），页面容器
 * `<div id={$taroPath} className="taro_page">` 就是在这串 children 里生成的。
 * 挡掉 children，页面 ONLOAD 的挂载回调里
 * `document.getElementById($taroPath)` 拿到的就是 null，直接抛
 * 「没有找到页面实例。」；而且那之后 `loadResolver` 不会被调用，
 * 这个页面实例的 `hasLoaded` 永不 resolve —— 页面就此废掉（白屏、
 * onReady/onShow 都不再触发）。
 *
 * 而且它是**必现**的：`useState` 的初值在回程地址有票时就是"未就绪"，
 * 而换票是异步网络请求、页面挂载回调是同步的，永远抢不过。
 *
 * ## 那"换完票之前别乱跳"靠什么保证
 *
 * 靠 utils/sso.ts 里那个 `ticketExchange` 信号：
 *   - `startSSO()` 在换票期间直接返回 → 守卫和请求层的 401 都跳不出去
 *   - 请求层发请求前会 `awaitPendingTicket()` → 这一发能带上刚换到的令牌
 *     （否则落点页必然是"未带令牌的请求撞 401 → 又把登录冲掉"）
 * 本文件只负责**在渲染期**把这个信号立起来
 */
function runTicketExchange({ ticket, state }: ReturnType<typeof readCallbackParams>): Promise<void> {
  return (async () => {
    try {
      // 1. 比对 state。取完即清，同一个 state 不能用第二次
      verifyState(state);

      // 2. 换令牌。票据 60 秒有效、用过即废
      const data = await authApi.exchangeTicket(ticket, CLIENT_ID);

      // 用户在换票这几十毫秒里点了登出：不要再把会话按回来（见 globalLogout）
      if (isNavigating()) return;

      saveTokens(data.access_token, data.refresh_token);
      if (data.user) saveUser(data.user);
    } catch (e) {
      // eslint-disable-next-line no-console
      console.log('[DIAG] ticket exchange failed:', e);
      // 3a. 失败就**静默重试**：清掉本地态，放行给路由守卫，
      //     由它再跳一次 /sso。认证中心那边还有会话的话会静默发一张新票，
      //     用户只看到闪一下；没会话就会落到登录页，不会死循环
      clearSession();
    } finally {
      // 3b. 无论成败都要清地址栏。**先清再放行**：留着的话
      //     守卫跳转时会把这张作废的票当成"当前页"的一部分带上
      cleanAuthParams();
    }
  })();
}

/**
 * 换票的 promise。`null` = 地址上没有票据，本次是普通访问。
 *
 * 放在模块作用域只是为了有个地方存它，**发起仍然在组件的渲染期**
 *（见下面 `useState` 的说明）—— 那时 Taro 已经完全初始化好了，
 * 而"渲染期"已经早于整棵树的 effect，够用了
 */
let ticketExchange: Promise<void> | null = null;

/** 回程参数。读一次就够：本次页面生命周期里它不会变 */
const callbackParams = readCallbackParams();
const hadTicket = !!callbackParams.ticket;

/**
 * 幂等地发起换票。（幂等是必须的：票据一次性，重复换第二张必然失败）
 */
function startTicketExchangeOnce(): void {
  if (ticketExchange || !hadTicket) return;
  ticketExchange = runTicketExchange(callbackParams);
  registerTicketExchange(ticketExchange);
}

function TicketHandler({ children }: TicketHandlerProps) {
  /**
   * ⚠️ 换票在**渲染期**发起，绝不能挪进 `useEffect`。
   *
   * React 的 effect 是**子先父后**，页面组件里的 `useRequireAuth` 会先于
   * 本组件的 effect 跑 —— 那时候票据还没开始换，守卫看到"没登录"就立刻
   * `startSSO()` 把刚拿到的票据冲掉。渲染期则是父先子后，这里一定赶在
   * 页面（和它的一切 effect）之前。这个坑和 `globalLogout` 里那面
   * `navigating` 旗是同一类（见 utils/sso.ts 的说明）
   *
   * 惰性初始化函数只在首次渲染跑一次；`startTicketExchangeOnce` 另有幂等
   * 保护，所以即使渲染两次（StrictMode）也不会换两次票
   */
  const [exchanging, setExchanging] = useState(() => {
    startTicketExchangeOnce();
    return hadTicket;
  });

  useEffect(() => {
    if (!exchanging) return;
    let cancelled = false;
    // 这个 promise 只是"什么时候算结束"，成败都由它自己处理
    void ticketExchange?.then(() => {
      if (!cancelled) setExchanging(false);
    });
    return () => {
      cancelled = true;
    };
  }, [exchanging]);

  return (
    <>
      {/* 页面照常渲染（Taro 要从这串 children 里生成页面容器），
          "正在登录…"改成盖在它上面的浮层 */}
      {children}
      {exchanging && (
        <View
          style={{
            position: 'fixed',
            left: '0',
            top: '0',
            right: '0',
            bottom: '0',
            zIndex: '9999',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            backgroundColor: '#f8f9fc',
          }}
        >
          <Text data-testid="sso-loading" style={{ fontSize: '15px', color: '#86909c' }}>
            正在登录…
          </Text>
        </View>
      )}
    </>
  );
}

export default TicketHandler;
