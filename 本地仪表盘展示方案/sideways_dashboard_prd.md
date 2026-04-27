# 📊 币安合约【横盘爆发雷达】本地仪表盘方案 - 需求文档 (PRD)

## 0. 项目视角 (Perspective)
本项目致力于将此前在 GitHub Actions 云端运行的"异步推送式"监控，迁移至**本地高性能运行环境**。
参考"相对强弱策略 (RS Strategy)"的深色极客设计，构建一个具备**实时交互、玻璃拟态 UI、以及多维数据对齐**的桌面监控端。

---

## 1. 核心改进点 (Core Enhancements)
*   **扫描频率提升**：从云端 60 分钟/次，提升至本地 1-5 分钟/轮。
*   **前端可视化**：不再局限于飞书文本，而是使用动态表格、色彩热力值、以及趋势小图直观展示。
*   **即时操作性**：点击币种可直接在浏览器中呼出 TradingView / CoinGlass 布局。
*   **零代理零反代**：不消耗 Vercel 额度，不依赖本机代理，全部走大陆直连 + Playwright。
*   **语音播报预警**：当某币种 OI/Vol 比值出现下降时，自动朗读币种名称进行告警。

---

## 2. 功能架构 (System Architecture)

### 2.1 后端：异步扫描引擎 (Backend Core)
*   **环境**：Python 3.10+ (FastAPI + Asyncio)。
*   **数据采集（零代理方案）**：
    *   **K 线数据**：通过 `data-api.binance.vision`（大陆免翻墙直连公共 API）拉取**现货 K 线**。
        - 接口：`https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=1h&limit=200`
        - 说明：现货与合约 K 线走势高度一致（相关性 > 99%），用于计算布林带挤压不存在误差问题。
        - 合约代码转换：`BTCUSDT` (合约) -> `BTCUSDT` (现货直接匹配)；部分带前缀的如 `1000PEPEUSDT` 需要做映射去掉前缀。
    *   **OI + 24h 成交额**：通过 Playwright 静默抓取 Coinglass（已有成熟逻辑，直接复用）。
    *   **合约列表**：通过 Coinglass 或 `data-api.binance.vision/api/v3/exchangeInfo` 获取当前活跃的交易对。
*   **数据流**：定时任务（Task Loop）-> 拉取全网币种现货K线 -> 计算 BBW -> 抓取 Coinglass OI/Vol -> 计算 OI/Vol 比率 -> 更新内存缓存 -> 持久化至 `sideways_history.json`。

### 2.2 前端：玻璃拟态仪表盘 (Frontend Web UI)
*   **UI 风格**：参考 RS 策略，主打 **Glassmorphism**（磨砂玻璃质感）+ **Dark Tech Mode**。
*   **主要视图**：
    *   **仪表盘页**：
        *   **监控看板**：磁贴式展示最重要的 5-10 个"当前极致缩圈"标的。
        *   **全景列表**：数据驱动的动态表格（DataTables 样式），支持：
            - `Symbol`: 币种名（可点击跳转 CoinGlass）。
            - `Price`: 最新价。
            - `Sideways Duration`: 横盘根数（用进度条深度表示）。
            - `Tightness (BBW)`: 紧致程度（百分比，越小越红）。
            - **`OI/Vol Ratio`**：持仓价值/24h成交额 比值（核心指标，重点标注）。
            - `OI` / `Vol`: 原始值，方便校对。
        *   **交互能力**：
            - 支持手动点击列名进行任意维度排序。
            - 一键唤起 CoinGlass / TradingView 详情页。
    *   **设置页**：可直接在 Web 界面调整 `MIN_DURATION` 和 `BBW_THRESHOLD` 参数。

### 2.3 语音预警系统 (Audio Alert - TTS)
*   **触发条件**：当某个上榜币种的 **OI/Vol Ratio 较上一轮出现下降**时，视为"能量释放信号"，触发语音播报。
*   **播报方式**：通过浏览器内置 `SpeechSynthesis` API（Web TTS）朗读币种名称，例如：`"BTC ratio dropping"`。
*   **免安装**：无需额外安装任何 TTS 引擎，纯浏览器原生能力。
*   **控制面板**：前端提供 `🔊 / 🔇` 一键开关按钮，用户可随时静音/启用。

### 2.4 部署与交互 (Deployment)
*   **入口**：`本地仪表盘展示方案\dashboard_launcher.py`。
*   **启动流**：点击 `一键启动.bat` -> 启动 FastAPI -> 自动调用 `os.startfile` 启动浏览器。

---

## 3. 关键技术细节

### 3.1 合约代码到现货代码的映射规则
由于使用现货 K 线替代合约 K 线，需要处理以下映射：
| 合约代码 | 现货代码 | 说明 |
|---|---|---|
| `BTCUSDT` | `BTCUSDT` | 直接匹配 |
| `ETHUSDT` | `ETHUSDT` | 直接匹配 |
| `1000PEPEUSDT` | `PEPEUSDT` | 去掉 `1000` 前缀 |
| `1000SHIBUSDT` | `SHIBUSDT` | 去掉 `1000` 前缀 |
| `1MBABYDOGEUSDT` | `BABYDOGEUSDT` | 去掉 `1M` 前缀 |
| `1000000BOBUSDT` | - | 部分山寨币现货可能不存在，需跳过 |

### 3.2 接口限速控制
*   `data-api.binance.vision` 有公共限速（约 1200 次/分钟），拉取 200+ 币种 K 线需分批并发（每批 20 个，间隔 1 秒）。

---

## 4. UI/UX 详细规范 (参考 RS 体系)
*   **色彩**：
    - 背景: 深色磨砂 (`#0d1117` / `backdrop-filter: blur(10px)`)。
    - 强调色: 蓝宝石绿 (`#00f5d4`)。
    - 警告色: 霓虹粉 (`#ff0054`)。
*   **字体**：主打代码风格字体 `SF Mono`, `Cascadia Code` 或 `IBM Plex Mono`。
*   **动画**：数据更新时，对应单元格应具有淡入淡出的呼吸灯动效。

---

## 5. 技术路线 (Tech Stack)
*   **后端**：`FastAPI` + `uvicorn` + `playwright`。
*   **数据源**：
    - K线：`data-api.binance.vision`（大陆直连，零代理，零成本）。
    - OI/成交额：`Coinglass` Playwright 劫持。
*   **前端**：Vanilla JS + CSS Variables（无第三方框架依赖，确保秒开）。
*   **存储**：`sideways_history.json`（本地持久化最近 24 小时状态）。
*   **音频**：浏览器原生 `SpeechSynthesis` API（零依赖 TTS）。

---

## 6. 开发节奏 (Phases)
1.  **Phase 1 (基础环境)**：搭建目录结构，编写基于 `data-api.binance.vision` 的现货 K 线拉取模块（含合约->现货代码映射），移植 Coinglass Playwright 抓取逻辑。
2.  **Phase 2 (API 实现)**：编写 FastAPI 后端接口（`/api/dashboard`），实现数据下发与定时调度。
3.  **Phase 3 (前端重塑)**：仿照 RS 策略编写基于玻璃拟态的 `index.html`，加入动态表格与 TTS 语音预警。
4.  **Phase 4 (联动调优)**：集成一键启动脚本、自动锁屏展示等桌面级功能。

---

**Next Action**: 用户确认后，我将从 Phase 1 开始落地开发。
