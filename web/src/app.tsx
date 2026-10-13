import { ConfigProvider } from '@nutui/nutui-react-taro';
import zhCN from '@nutui/nutui-react-taro/dist/locales/zh-CN';
import TicketHandler from './components/TicketHandler';
import './app.less';

function App(props) {
  return (
    <ConfigProvider locale={zhCN}>
      {/* 包一层票据处理：SSO 回来时地址上带着 ticket，要在页面（和它的
          路由守卫）渲染之前就换掉令牌，见 TicketHandler 里的说明 */}
      <TicketHandler>{props.children}</TicketHandler>
    </ConfigProvider>
  );
}

export default App;
