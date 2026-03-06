
import asyncio
import ccxt.async_support as ccxt
import time
import logging
import aiohttp
import json
from collections import deque
from datetime import datetime
from typing import Dict, List, Optional

# ==========================================
# 1. 配置区域 (Config)
# ==========================================
class Config:
    # 交易所配置
    EXCHANGE_ID = 'binance'
    MARKET_TYPE = 'future'  # 'spot' 或 'future' (合约)

    # 策略参数
    TIMEFRAME = '1m'
    HISTORY_LIMIT = 1440  # 过去 24h (1440分钟)
    AMPLITUDE_THRESHOLD = 0.005  # 0.5% 振幅阈值
    MIN_24H_VOLUME_USDT = 500_000  # 24H成交额过滤阈值 (50万 U)

    # 系统参数
    CONCURRENT_REQUESTS = 10  # 初始化时的并发请求限制
    UPDATE_INTERVAL = 60  # 每60秒检查一次

    # 报警配置 (请替换为您实际的 Webhook URL)
    # 例如 DingTalk: "https://oapi.dingtalk.com/robot/send?access_token=..."
    # 例如 Lark: "https://open.feishu.cn/open-apis/bot/v2/hook/..."
    # 报警配置
    # 优先从环境变量读取，如果没有则使用下方默认值
    import os
    WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")
    WEBHOOK_TYPE = "lark" # 'dingtalk' or 'lark'

    # 代理配置 (如果需要翻墙请配置，例如 "http://127.0.0.1:7890")
    # 如果不需要代理，请保持为空字符串 ""
    PROXY_URL = "http://127.0.0.1:2333"

    # [高级] 自定义 API 域名 (如果使用反代或加速域名)
    # 例如: "fapi.binance.com" (默认) 或某些加速域名
    API_HOSTNAME = ""

# ==========================================
# 2. 日志配置
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('wyckoff_monitor.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# ==========================================
# 3. 核心监控类 (WyckoffMonitor)
# ==========================================
class WyckoffMonitor:
    def __init__(self):
        self.config = Config()
        self.exchange = None
        # 核心数据结构: {symbol: deque([ohlcv_1, ohlcv_2, ...], maxlen=1440)}
        self.market_data: Dict[str, deque] = {}
        # 用来存储每个币种的 24h 成交额，用于过滤
        self.symbol_volumes: Dict[str, float] = {}
        self.semaphore = asyncio.Semaphore(self.config.CONCURRENT_REQUESTS)
        self.session = None

    async def _init_exchange(self):
        """初始化交易所连接"""
        exchange_class = getattr(ccxt, self.config.EXCHANGE_ID)
        exchange_options = {
            'enableRateLimit': True,  # 开启 ccxt 内置限流
            'options': {'defaultType': self.config.MARKET_TYPE}
        }

        # 如果配置了代理，添加到 options 中
        if self.config.PROXY_URL:
            exchange_options['proxies'] = {
                'http': self.config.PROXY_URL,
                'https': self.config.PROXY_URL
            }
            logger.info(f"已启用代理: {self.config.PROXY_URL}")

        self.exchange = exchange_class(exchange_options)
        if self.config.PROXY_URL:
            self.exchange.aiohttp_proxy = self.config.PROXY_URL

        if self.config.API_HOSTNAME:
            self.exchange.hostname = self.config.API_HOSTNAME
            logger.info(f"已使用自定义 API 域名: {self.config.API_HOSTNAME}")

        # 加载市场信息 (获取所有交易对)
        logger.info("正在加载市场信息...")
        await self.exchange.load_markets()
        logger.info(f"市场加载完毕，共 {len(self.exchange.symbols)} 个交易对")

    async def _fetch_ohlcv_safe(self, symbol: str, limit: int = 1440) -> List:
        """安全获取 K 线数据 (带并发限制和重试)"""
        async with self.semaphore:
            retries = 3
            for i in range(retries):
                try:
                    # 获取 K 线
                    ohlcv = await self.exchange.fetch_ohlcv(symbol, self.config.TIMEFRAME, limit=limit)
                    return ohlcv
                except Exception as e:
                    if i == retries - 1:
                        logger.error(f"[{symbol}] 获取 K 线失败 (重试耗尽): {e}")
                        return []
                    await asyncio.sleep(1 * (i + 1)) # 指数退避
            return []

    async def _send_alert(self, message: dict):
        """发送报警消息到 Webhook"""
        if not self.config.WEBHOOK_URL:
            logger.warning("未配置 Webhook URL，无法发送报警")
            logger.info(f"报警内容: {message}")
            return

        try:
            async with aiohttp.ClientSession() as session:
                payload = {}
                if self.config.WEBHOOK_TYPE == 'dingtalk':
                    payload = {
                        "msgtype": "text",
                        "text": {"content": f"【威科夫异动监控】\n{message['text']}"}
                    }
                elif self.config.WEBHOOK_TYPE == 'lark':
                     payload = {
                        "msg_type": "text",
                        "content": {"text": f"【威科夫异动监控】\n{message['text']}"}
                    }

                async with session.post(self.config.WEBHOOK_URL, json=payload) as resp:
                    if resp.status != 200:
                        logger.error(f"报警发送失败 Status: {resp.status}")
        except Exception as e:
            logger.error(f"报警发送异常: {e}")

    def _check_anomaly(self, symbol: str, latest_k: list, history: deque):
        """
        核心检测逻辑:
        latest_k: [timestamp, open, high, low, close, volume]
        """
        if not latest_k or len(history) < 100: # 历史数据太少不检测
            return

        # 获取最新的一根K线数据
        ts, o, h, l, c, v = latest_k

        # 0. 基础数据校验
        if o == 0: return

        # 1. 窄幅检测: 振幅 < 0.5%
        amplitude = (h - l) / o
        if amplitude >= self.config.AMPLITUDE_THRESHOLD:
            return # 振幅过大，不符合条件

        # 2. 巨量检测: 当前成交量 > 过去 24h 所有 K 线成交量
        # history 中包含 latest_k 本身，所以要排除它自己进行比较，或者取 max 时注意
        # 这里的 history 是已经 append 了 latest_k 的，所以我们要看它是否比之前的所有都大
        # 也就是它是 max(history)

        # 提取历史成交量 (排除刚进来的这一根，或者直接比对)
        # 为了严谨，我们找出 history 中最大的成交量
        max_vol = 0
        sum_vol = 0
        count = 0
        for candle in history:
            vol = candle[5]
            if candle[0] != ts: # 排除当前这根，和过去的比
                if vol > max_vol:
                    max_vol = vol
                sum_vol += vol
                count += 1

        if count == 0: return

        avg_vol = sum_vol / count

        # 核心判断: 当前量 > 历史最大量
        if v > max_vol:
            # 触发异动！
            vol_ratio = v / avg_vol if avg_vol > 0 else 0

            title_tag = "[ANOMALY]"
            logger.info(f"{title_tag} 发现异动: {symbol} | 振幅: {amplitude*100:.2f}% | 现量: {v:.2f} (历史最大: {max_vol:.2f})")

            dt_str = datetime.fromtimestamp(ts/1000).strftime('%Y-%m-%d %H:%M:%S')
            alert_text = (
                f"币种: {symbol}\n"
                f"时间: {dt_str}\n"
                f"价格: {c}\n"
                f"振幅: {amplitude*100:.2f}%\n"
                f"成交量倍数: {vol_ratio:.1f}x (较24h平均)\n"
                f"状态: 巨量窄幅 (Effort vs Result)"
            )

            asyncio.create_task(self._send_alert({'text': alert_text}))

    async def initialize_data(self):
        """启动时初始化: 拉取符合条件的币种历史以填充缓存"""
        await self._init_exchange()

        symbols_to_monitor = []

        # 1. 筛选活跃币种 (先获取 24h Ticker 用于过滤)
        logger.info("正在筛选活跃币种...")
        tickers = await self.exchange.fetch_tickers()
        for symbol, ticker in tickers.items():
            # 过滤掉非 USDT 交易对
            if '/USDT' not in symbol:
                continue
            # 过滤掉成交额过小的
            quote_volume = ticker.get('quoteVolume') or 0
            if quote_volume < self.config.MIN_24H_VOLUME_USDT:
                continue

            symbols_to_monitor.append(symbol)
            self.symbol_volumes[symbol] = quote_volume

        logger.info(f"筛选共 {len(symbols_to_monitor)} 个活跃 USDT 交易对，准备初始化历史数据...")

        # 2. 并发初始化历史 K 线
        tasks = []
        for symbol in symbols_to_monitor:
            tasks.append(self._fetch_ohlcv_safe(symbol, limit=self.config.HISTORY_LIMIT))

        # 使用 asyncio.gather 并发执行，利用 semaphore 限制并发数
        results = await asyncio.gather(*tasks)

        # 3. 填充本地缓存
        for symbol, ohlcvs in zip(symbols_to_monitor, results):
            if ohlcvs and len(ohlcvs) > 0:
                # 使用 deque 固定长度，自动挤出旧数据
                self.market_data[symbol] = deque(ohlcvs, maxlen=self.config.HISTORY_LIMIT)

        logger.info(f"历史数据初始化完成，成功缓存 {len(self.market_data)} 个币种。")

    async def run(self):
        """主运行循环"""
        try:
            await self.initialize_data()

            logger.info("[STARTED] 实时监控已启动...")

            while True:
                start_time = time.time()

                # 1. 计算需要等待的时间，对齐到下一分钟的 05 秒 (给交易所一点结算是时间)
                # 比如现在是 12:00:30，我们等到 12:01:05 再请求
                now = time.time()
                next_minute = (int(now) // 60 + 1) * 60
                wait_seconds = next_minute - now + 5 # 延迟5秒确保K线收盘

                logger.info(f"等待 {wait_seconds:.2f} 秒后开始下一轮扫描...")
                await asyncio.sleep(wait_seconds)

                logger.info(">> 开始本轮扫描...")

                # 2. 并发拉取最新 1 根 K 线
                # 我们只需要监控已经在 market_data 里的币种 (活跃币种)
                targets = list(self.market_data.keys())
                tasks = []
                for symbol in targets:
                    tasks.append(self._fetch_ohlcv_safe(symbol, limit=2)) # 拉2根防止刚收盘那一瞬间没拿到

                results = await asyncio.gather(*tasks)

                # 3. 更新数据并检测
                check_count = 0
                for symbol, ohlcvs in zip(targets, results):
                    if not ohlcvs: continue

                    # 取最新的一根收盘K线 (ohlcvs[-1] 可能是当前进行中的，我们要取倒数第二根如果是刚刚收盘的话)
                    # 这里的逻辑需要细致：
                    # Binance fetch_ohlcv 默认包含当前未收盘的 K 线。
                    # 如果我们是在 xx:xx:05 请求，理论上倒数第二根 (ohlcvs[-2]) 是刚刚收盘的那根 xx:xx-1:00 的K线
                    # 倒数第一根 (ohlcvs[-1]) 是新的 xx:xx:00 开始的K线

                    if len(ohlcvs) < 2: continue

                    just_closed_candle = ohlcvs[-2]
                    current_ts = just_closed_candle[0]

                    # 检查是否已经处理过这根K线 (防止重复处理)
                    last_stored_candle = self.market_data[symbol][-1]
                    if last_stored_candle[0] == current_ts:
                         # 已经存过了，不用再处理
                         continue

                    # 4. 更新队列
                    self.market_data[symbol].append(just_closed_candle)

                    # 5. 检测异动
                    self._check_anomaly(symbol, just_closed_candle, self.market_data[symbol])
                    check_count += 1

                logger.info(f"<< 本轮扫描结束，更新并检测了 {check_count} 个币种。")

        except Exception as e:
            logger.error(f"主循环发生严重错误: {e}", exc_info=True)
            # 简单的错误恢复，防止程序完全崩溃
            await asyncio.sleep(10)
        finally:
            if self.exchange:
                await self.exchange.close()

if __name__ == "__main__":
    try:
        # Windows 下 asyncio SelectorEventLoop 警告解决
        if 'win32' in str(asyncio.get_event_loop_policy()):
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

        monitor = WyckoffMonitor()
        asyncio.run(monitor.run())
    except KeyboardInterrupt:
        print("程序已停止")
