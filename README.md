# learn-daily

把一本书切成每天一课：上传 → 解析 → 按天分块 → AI 讲解 → 出题 → 作答 → AI 批改 →
长期记忆与诊断（我学到了什么、我还差什么）。

自用工具，单用户，没有登录。

## 目录

```
server/   FastAPI + SQLite + pymupdf。解析、切分、调模型、记忆与诊断都在这里
web/      Taro4 + React18 + NutUI（H5 为主）
```

## 跑起来

后端（端口 **8010**，避开 call-back 的 8080/8090 和 poker-ocr 的 8000）：

```bash
cd server
cp .env.example .env   # 填 LLM_API_KEY
uv run uvicorn app.main:app --reload --port 8010
```

前端（端口 **3010**，避开 call-front 的 3000；`/api` 已代理到 8010）：

```bash
cd web
pnpm install
pnpm run dev:h5        # 打开 http://localhost:3010
```

测试与冒烟：

```bash
cd server
uv run pytest -q                  # 37 个测试，全部打桩，不花钱
uv run python scripts/smoke.py    # 打真模型跑一遍完整闭环，评估提示词质量用

cd web
pnpm run build:h5                 # 生产构建
npx tsc --noEmit                  # 类型检查
```

## 几个刻意的取舍

- **不做 RAG、不接向量库。** 「今天读这一章」整章直接进上下文就够了，检索反而会引入
  切分错误和召回丢失。DeepSeek 也没有 embedding 接口。
- **上游一律流式。** 非流式在模型写完之前一个字节都不发，K3 这类推理模型会把请求拖死
  （服务端还照常计费）。见 `server/app/llm.py`。
- **长任务全部异步 + 轮询。** 讲解 / 出题 / 批改 / 诊断都落库状态，前端轮询。
  一个模型调用可能跑几分钟，同步请求扛不住。
- **诊断不用「掌握度百分比」。** 错题按证据行累加：同一个概念错三次就该看到三条，
  那三条本身就是「反复出错」这个信号；压成一个 60% 反而把它抹平了。
- **批改时把当天已沉淀的概念喂进去。** 不然模型每次自己起名（「注意力位置」vs
  「注意力位置决定效果」），诊断就没法把作答按概念归拢。
- **尺寸按 375 设计稿的真实 CSS 像素写。** Taro 的 `designWidth` 是 375，
  写 15px 在 375 宽的屏上就是 15px。别按 750 的稿子写双倍数值，
  字号会大一倍、一屏放不下几个字。见 `web/src/styles/theme.less`。

## 数据与迁移

SQLite 库在 `server/data/learn.db`（已 gitignore）。**加字段不用删库**：
启动时会自动把模型里有、库里没有的列 ALTER 进去（`app/migrate.py`）。
它只管新增列——改类型、删列、动数据仍需手写迁移脚本。
数据变得值得保留之后，建议照 call-back 的做法写带日期的 SQL 迁移。

## 现状

- M1 学习闭环：完成。后端 37 个测试 + 真模型冒烟 + 浏览器端到端验证。
- M2 AI 记忆与诊断：完成。概念沉淀、错题证据、诊断（已建立 / 还差 / 盲区 / 下一步）。
- 未做：微信小程序端的文件上传（`Taro.chooseMessageFile` + `Taro.uploadFile` 是另一条路径）、
  间隔重复排期、多用户。
