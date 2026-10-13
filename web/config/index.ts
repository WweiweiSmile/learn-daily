import { defineConfig, type UserConfigExport } from '@tarojs/cli'
import devConfig from './dev'
import prodConfig from './prod'
import vitePluginImp from 'vite-plugin-imp'

export default defineConfig<'vite'>(async (merge) => {
  const baseConfig: UserConfigExport<'vite'> = {
    projectName: 'learn-daily-web',
    date: '2026-10-04',
    designWidth: 375,
    deviceRatio: {
      640: 2.34 / 2,
      750: 1,
      375: 2,
      828: 1.81 / 2,
    },
    sourceRoot: 'src',
    outputRoot: 'dist',
    plugins: ['@tarojs/plugin-html'],
    defineConstants: {},
    copy: { patterns: [], options: {} },
    framework: 'react',
    compiler: {
      vitePlugins: [
        vitePluginImp({
          libList: [
            {
              libName: '@nutui/nutui-react-taro',
              style: (name) => `@nutui/nutui-react-taro/dist/esm/${name}/style/css`,
              replaceOldImport: false,
              camel2DashComponentName: false,
            },
          ],
        }),
      ],
      type: 'vite',
    },
    mini: {
      postcss: {
        pxtransform: { enable: true, config: { selectorBlackList: ['nut-'] } },
        cssModules: { enable: false, config: { namingPattern: 'module' } },
      },
    },
    h5: {
      publicPath: '/',
      staticDirectory: 'static',

      // history 模式（Taro 默认是 hash）。改这个是为了让 SSO 的回调地址不带 `#`：
      // 认证中心把 ticket 拼在真正的 query 上（`/pages/library/index?ticket=..`），
      // 而不是拼进 fragment（`#/pages/library/index?ticket=..`）。
      //
      // ⚠️ **部署必须配合**：history 模式下 `/pages/library/index` 是真实路径，
      // nginx 要加 `try_files $uri $uri/ /index.html;` 回落到 index.html，
      // 否则刷新/直达会被 nginx 直接 404。publicPath 已经是 '/'，这是前提
      router: {
        mode: 'browser',
      },

      miniCssExtractPluginOption: {
        ignoreOrder: true,
        filename: 'css/[name].[hash].css',
        chunkFilename: 'css/[name].[chunkhash].css',
      },
      postcss: {
        autoprefixer: { enable: true, config: {} },
        cssModules: { enable: false, config: { namingPattern: 'module' } },
      },
    },
  }

  return process.env.NODE_ENV === 'development'
    ? merge({}, baseConfig, devConfig)
    : merge({}, baseConfig, prodConfig)
})
