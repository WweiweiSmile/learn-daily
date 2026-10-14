import { clearSession, saveSSOFlow, takeSSOFlow } from './authStorage';

/**
 * 跨应用登录（SSO）的浏览器侧编排。
 *
 * 整个方案里前端只做三件事：**跳过去**、**带着票据回来换令牌**、**退出去**。
 * 判断"有没有登录态""要不要发票据"全在认证中心，前端不掺和 ——
 * 它连认证中心域的 cookie 都读不到（HttpOnly），想掺和也掺和不了。
 *
 * 跳过去时把**用户当时所在的那一页**作为 `redirect_uri` 带上；认证中心登录完
 * 把一次性 `ticket` 拼在那一页的地址后面跳回来，全局的 TicketHandler 就地
 * 换令牌并清掉地址栏参数（见 components/TicketHandler.tsx）。
 * 所以**没有专门的回调页了**，落点就是用户本来要去的那一页。
 *
 * 与 call-front 的实现是同一套，只是 client_id、存储键名和默认落点不同。
 * 设计文档：call-back/认证中心设计文档.md 的 §4.5、§6.2.1、§8.4
 */

/**
 * 认证中心的地址。**必须是绝对地址**，不能走 dev server 的 /authsvc 代理 ——
 * 代理只能转发 XHR，而这里是浏览器整页跳转，跳过去必须是真的认证中心域
 *（登录页和 cookie 都在那个域下）
 */
const AUTH_ORIGIN = process.env.TARO_APP_AUTH_URL || '';

/** 登录完成后默认回落到哪一页 */
const DEFAULT_ROUTE = '/pages/library/index';

/** 本应用在认证中心注册的 client_id。必须与 sso_clients 表里的一致 */
export const CLIENT_ID = 'learn-daily';

/**
 * 已经在跳转途中（去 `/sso` 或去 `/logout`）。
 *
 * 两个作用：一是防重复跳转（effect 可能跑多次，跳多次会刷历史）；
 * 二是**让登出和 SSO 互斥** —— 这两者会互相覆盖，见 globalLogout 里的说明
 */
let navigating = false;

/**
 * 正在进行中的换票。
 *
 * 存在的理由是**"先别跳"**：SSO 回程时页面是真的挂载了的（票据处理不能
 * 再靠"不渲染 children"把它挡住 —— 那会让 Taro 找不到页面实例，见
 * components/TicketHandler.tsx），于是守卫和页面自己的请求都会在票据换完
 * 之前跑起来，两边都会把这次登录冲掉：
 *   - 守卫判定"未登录" → `startSSO()`，把回程地址整个替换掉
 *   - 页面首个请求没带令牌 → 401 → 请求层也是 `clearSession()` + `startSSO()`
 *
 * 所以换票期间 `startSSO()` 必须直接返回（一处改动同时堵住上面两条路），
 * 等它落地再按结果决定跳不跳（见 components/RequireAuth.tsx）。
 *
 * 请求层另外会 `awaitPendingTicket()` —— 那一等让页面首个请求能带着
 * 刚换到的令牌发出去（见 services/request.ts）
 */
let ticketExchange: Promise<void> | null = null;

/** 递增序号：落地时只清自己那一份，避免把后来登记的覆盖掉 */
let exchangeSeq = 0;

/**
 * 登记一次换票。
 *
 * **必须在任何页面 effect 之前调用**，晚了页面已经跳走了 —— 调用点在
 * components/TicketHandler.tsx 的渲染期（不是它的 effect 里）
 */
export function registerTicketExchange(exchange: Promise<void>): void {
  const seq = ++exchangeSeq;
  ticketExchange = exchange
    // 成败都不关心：这里只回答"什么时候算结束"。失败由换票自己处理，
    // 更不能让一个 rejected 的 promise 顺着 await 传到调用方去
    .catch(() => {})
    .then(() => {
      if (exchangeSeq === seq) ticketExchange = null;
    });
}

/**
 * 等换票落地。没有票据在换时是一个已 resolve 的 promise，等于空操作。
 *
 * ⚠️ **换票请求自己不能走这里** —— 它就是 `ticketExchange` 本身，等它就是
 * 自己等自己（见 services/request.ts 的 `waitForTicket`）
 */
export function awaitPendingTicket(): Promise<void> {
  return ticketExchange ?? Promise.resolve();
}

/**
 * 是否已经在跳转途中。换票成功后用它确认"用户没有在这期间点登出" ——
 * 否则会把刚登出的会话又按回来（见 globalLogout）
 */
export function isNavigating(): boolean {
  return navigating;
}

/**
 * 生成 state。
 *
 * 用 `crypto.getRandomValues` 而不是 `crypto.randomUUID()` —— 后者在
 * **非安全上下文（http 页面）下根本不存在**，本机 dev 会直接抛错。
 * `getRandomValues` 没有这个限制
 */
function randomState(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

/**
 * 当前页面路径，用来在登录后把用户送回来。
 *
 * history 模式（config/index.ts 的 h5.router.mode = 'browser'）：
 * 路径就是 `window.location.pathname`，**不再读 hash**。
 *
 * 顺手把地址上可能残留的 ticket / state 剥掉 —— 否则它会被当成"目标页"的
 * 一部分传给认证中心，下次回来又带着一张旧票
 */
function currentRoute(): string {
  try {
    if (typeof window !== 'undefined' && window.location) {
      const url = new URL(window.location.href);
      url.searchParams.delete('ticket');
      url.searchParams.delete('state');
      // 根路径没有可回的目标：history 模式下 '/' 不会自动路由到 entryPagePath
      if (url.pathname && url.pathname !== '/') {
        return `${url.pathname}${url.search}`;
      }
    }
  } catch {
    // 取不到就回默认页，不该因为一个页面路径把登录流程搞挂
  }
  return DEFAULT_ROUTE;
}

/**
 * 只接受本应用内的相对路径。
 *
 * 必须排除 `//evil.com`（协议相对 URL，浏览器会当成 https://evil.com）——
 * 只判断"以 / 开头"是不够的
 */
function sanitizeReturnTo(route: string): string {
  if (!route || !route.startsWith('/') || route.startsWith('//')) return DEFAULT_ROUTE;
  return route;
}

/**
 * 未登录时跳认证中心做 SSO。
 *
 * `returnTo` 是登录成功后要落回的那一页，**默认就是当前页**。需要显式指定的
 * 调用方（比如某个页面上的"去登录"按钮）传一个路径进来即可。
 *
 * 用 `replace` 而不是 `assign`：这些中间态（认证中心、登录页）不该进浏览历史 ——
 * 否则用户点一次后退就回到 `/sso`，被再弹一遍登录页
 */
export function startSSO(returnTo?: string): void {
  if (navigating) return;
  // 换票期间不许跳：这一跳会把回程地址（连着票据）整个替换掉，
  // 这次登录就白跑了。守卫和请求层的 401 都会走到这里，一处堵住两条路
  if (ticketExchange) return;
  if (typeof window === 'undefined' || !AUTH_ORIGIN) return;
  navigating = true;

  const state = randomState();
  saveSSOFlow({ state });

  const target = sanitizeReturnTo(returnTo || currentRoute());
  // 落点必须是**绝对地址**：认证中心按 scheme+host 与登记的白名单比对，
  // 同源才放行（见 call-auth 的 models.ResolveRedirectURI）
  const redirectURI = `${window.location.origin}${target}`;

  // redirect_uri 必须 encode：它自身带 `:` `/`，不编码会被 query 解析截断
  const url =
    `${AUTH_ORIGIN}/sso` +
    `?client_id=${encodeURIComponent(CLIENT_ID)}` +
    `&redirect_uri=${encodeURIComponent(redirectURI)}` +
    `&state=${encodeURIComponent(state)}`;
  window.location.replace(url);
}

/**
 * 读地址上的 ticket 和 state。
 *
 * **直接读 location，不用 Taro 的 router.params**：这一步必须稳，读错了就是
 * "登录成功但前端说没拿到 ticket"。history 模式下参数在 search 里；
 * hash 分支保留是为了兼容老形态的地址（以及万一哪天又切回去）
 */
export function readCallbackParams(): { ticket: string; state: string } {
  if (typeof window === 'undefined') return { ticket: '', state: '' };

  const sources: string[] = [];
  // history 模式：参数在真正的 query 上
  if (window.location.search) sources.push(window.location.search);
  // hash 模式（或老形态的地址）：参数在 fragment 的 query 段
  const hash = window.location.hash;
  const queryStart = hash.indexOf('?');
  if (queryStart >= 0) sources.push(hash.slice(queryStart));

  for (const source of sources) {
    const params = new URLSearchParams(source);
    const ticket = params.get('ticket') || '';
    if (ticket) {
      return { ticket, state: params.get('state') || '' };
    }
  }
  return { ticket: '', state: '' };
}

/**
 * 比对 state。
 *
 * **不比对 state 就等于不设防**：攻击者可以构造一个带自己 ticket 的回调链接
 * 骗用户点，把用户登成攻击者的账号，之后用户在这个应用里干的一切都记在
 * 攻击者名下。取完即清，同一个 state 不能用第二次
 *
 * 不返回"回到哪一页"了 —— 落点就是当前地址本身（startSSO 把它作为
 * redirect_uri 传给了认证中心，认证中心原样跳回来）
 */
export function verifyState(state: string): void {
  const flow = takeSSOFlow();
  if (!flow || !state || flow.state !== state) {
    throw new Error('登录校验失败（state 不匹配），请重新登录');
  }
}

/**
 * 清掉地址栏上的 ticket / state。
 *
 * 不清的话它会被留在浏览历史里、被复制、被收藏。这一步用 replaceState，
 * 不会多出一条历史记录。
 *
 * **只删这两个参数，其余 query 保留**：目标页自己可能有别的参数，
 * 那是它渲染所需要的，整体清空会把页面搞成空的
 */
export function cleanAuthParams(): void {
  if (typeof window === 'undefined' || !window.history?.replaceState) return;
  const url = new URL(window.location.href);
  url.searchParams.delete('ticket');
  url.searchParams.delete('state');
  window.history.replaceState(null, '', `${url.pathname}${url.search}`);
}

/**
 * 全局退出。
 *
 * **必须跳认证中心，不能只清本地**：清掉本地 storage 之后路由守卫会判定
 * "没登录"并再跳一次 `/sso`，而认证中心域下的会话 cookie 前端删不掉 ——
 * 于是立刻又被静默登回去，登出按钮等于没用（见设计文档 §6.2.2）。
 * 只有认证中心自己能把那个 cookie 删掉。
 *
 * `next` 用本应用的 origin：认证中心只接受登记过的 origin，
 * 带路径会被拒（那是它防开放重定向的一部分）
 */
export function globalLogout(): void {
  // ⚠️ **先立旗，再清本地**。
  //
  // 清掉本地令牌之后，路由守卫会立刻判定"未登录"并开始一次 `startSSO()`。
  // 那次跳转会**覆盖掉这里的 /logout** —— 结果就是"点了登出，人却被静默登回去"。
  // call-front 真机实测踩到过，所以这面旗必须在 clearSession 之前立起来
  navigating = true;

  clearSession();

  if (typeof window === 'undefined' || !AUTH_ORIGIN) return;
  const next = encodeURIComponent(window.location.origin);
  window.location.replace(`${AUTH_ORIGIN}/logout?next=${next}`);
}
