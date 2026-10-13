import type { UserConfigExport } from '@tarojs/cli'

export default {
  mini: {},
  h5: {
    devServer: {
      // 端口 3010：call-front 占着 3000，两个项目要同时开。
      port: 3010,
      proxy: {
        // learn-daily 后端，见 server/README。走代理是为了免掉跨域。
        '/api': {
          target: 'http://localhost:8010',
          changeOrigin: true,
          secure: false,
        },
        '/health': {
          target: 'http://localhost:8010',
          changeOrigin: true,
          secure: false,
        },
        // 认证中心（~/codes/call-auth，:8020）。登录/注册/续期/登出都归它，
        // learn-daily 后端只验签、不提供登录接口。
        //
        // 注意是 `rewrite` 不是 `pathRewrite`：Taro H5 的 devServer 底层是 Vite，
        // 用的是 Vite 的选项名。写成 http-proxy 那套 `pathRewrite` 不会报错，
        // 只是静默不生效 —— 请求会带着 /authsvc 前缀打到认证中心，然后 404
        '/authsvc': {
          target: 'http://localhost:8020',
          changeOrigin: true,
          secure: false,
          rewrite: (p) => p.replace(/^\/authsvc/, ''),
        },
      },
    },
  },
} satisfies UserConfigExport<'vite'>
