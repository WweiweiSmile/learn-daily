export default defineAppConfig({
  pages: [
    // 没有 SSO 回调页：登录页在认证中心（call-auth），票据由入口处的
    // TicketHandler 在**用户本来要去的那一页**上就地处理（见 src/app.tsx）
    'pages/library/index',
    'pages/book/index',
    'pages/study/index',
    'pages/diagnosis/index',
  ],
  entryPagePath: 'pages/library/index',
  window: {
    backgroundTextStyle: 'light',
    navigationBarBackgroundColor: '#ffffff',
    navigationBarTitleText: '按天学',
    navigationBarTextStyle: 'black',
  },
});
