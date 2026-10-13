/// <reference types="@tarojs/taro" />

declare module '*.png';
declare module '*.gif';
declare module '*.jpg';
declare module '*.jpeg';
declare module '*.svg';
declare module '*.css';
declare module '*.less';

// Taro 会在构建时把 process.env.* 替换成字面量，但类型得自己声明——
// 不装 @types/node（这是个前端项目，不该把 node 的类型拖进来）。
declare const process: {
  env: NodeJS.ProcessEnv;
};

declare namespace NodeJS {
  interface ProcessEnv {
    NODE_ENV: 'development' | 'production' | 'test';
    TARO_ENV: 'weapp' | 'h5' | 'swan' | 'alipay' | 'rn' | 'tt' | 'quickapp' | 'qq' | 'jd';
    TARO_APP_ID: string;
    /** 生产环境的业务后端地址，见 .env.production */
    TARO_APP_BASE_URL: string;
    /** 生产环境的认证中心地址（call-auth），见 .env.production */
    TARO_APP_AUTH_URL: string;
  }
}
