import { useEffect, useState } from 'react';
import { Text, View } from '@tarojs/components';

import { authApi } from '../services/authApi';
import { clearSession, saveTokens, saveUser } from '../utils/authStorage';
import {
  CLIENT_ID,
  cleanAuthParams,
  readCallbackParams,
  verifyState,
} from '../utils/sso';

interface TicketHandlerProps {
  children: React.ReactNode;
}

/**
 * 全局票据处理。挂在应用入口，包住所有页面（见 app.tsx）。
 *
 * 存在的理由：SSO 回程时票据是拼在**用户要去的那一页**的地址上的
 *（`/pages/study/index?ticket=..&state=..`），不再是拼在一个固定的回调页上。
 * 所以要有一个全局的东西，在任意页面被渲染出来之前先把票换掉。
 *
 * 它做三件事，顺序不能换（见设计文档 §8.4）：
 *   1. 比对 state —— 不比对就等于可以被登成别人的账号
 *   2. 用票据换令牌并存下来
 *   3. 清掉地址栏上的 ticket，然后就地放行（**不跳转**，人已经在目标页了）
 *
 * ## 为什么要有 `ready` 这道门
 *
 * React 的 effect 是**子先父后**：页面组件里的 `useRequireAuth` 会先于本组件
 * 的 effect 跑。如果 children 先挂载，守卫会看到"还没登录"就立刻 `startSSO()`，
 * 把刚拿到的票据冲掉。所以处理票据期间**根本不渲染 children**，页面守卫连跑的
 * 机会都没有。这个坑和 `globalLogout` 里那面 `navigating` 旗是同一类
 *（见 utils/sso.ts 的说明）
 */
function TicketHandler({ children }: TicketHandlerProps) {
  // 同步读一次当作初值：地址上没有票就是普通访问，第一帧就直接渲染 children，
  // 不闪任何东西。有票才启动流程
  const [ready, setReady] = useState(() => !readCallbackParams().ticket);

  useEffect(() => {
    const { ticket, state } = readCallbackParams();
    if (!ticket) return;

    let cancelled = false;

    (async () => {
      try {
        // 1. 比对 state。取完即清，同一个 state 不能用第二次
        verifyState(state);

        // 2. 换令牌。票据 60 秒有效、用过即废
        const data = await authApi.exchangeTicket(ticket, CLIENT_ID);
        saveTokens(data.access_token, data.refresh_token);
        if (data.user) saveUser(data.user);
      } catch {
        // 3a. 失败就**静默重试**：清掉本地态，放行给路由守卫，
        //     由它再跳一次 /sso。认证中心那边还有会话的话会静默发一张新票，
        //     用户只看到闪一下；没会话就会落到登录页，不会死循环
        clearSession();
      } finally {
        // 3b. 无论成败都要清地址栏。**先清再放行**：留着的话
        //     守卫跳转时会把这张作废的票当成"当前页"的一部分带上
        if (!cancelled) {
          cleanAuthParams();
          setReady(true);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  if (!ready) {
    return (
      <View
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: '100vh',
          backgroundColor: '#f8f9fc',
        }}
      >
        <Text data-testid="sso-loading" style={{ fontSize: '15px', color: '#86909c' }}>
          正在登录…
        </Text>
      </View>
    );
  }

  return <>{children}</>;
}

export default TicketHandler;
