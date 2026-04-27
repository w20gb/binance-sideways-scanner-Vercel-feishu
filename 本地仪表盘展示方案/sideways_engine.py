"""
sideways_engine.py

Direct-connect squeeze scanner:
1. Binance Vision spot 1h candles are the primary source.
2. Gate.io futures 1h candles are the secondary fallback.
3. Coinglass provides OI and 24h volume with local cache fallback.
"""

import asyncio
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import sys
import os
# 将上级目录加入路径以导入 binance_gateway
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import binance_gateway as bg
import pandas as pd
import requests
from playwright.async_api import async_playwright

VISION_BASE = "https://data-api.binance.vision"
INTERVAL = "1h"
LIMIT = 200
BBW_THRESHOLD = 0.05
BB_WINDOW = 20
BB_TOLERANCE = 1
MIN_DURATION = 6

BLACKLIST = {"USDCUSDT", "BTCDOMUSDT", "DEFIUSDT", "BLUEBIRDUSDT", "FOOTBALLUSDT"}
HISTORY_FILE = os.path.join(os.path.dirname(__file__), "sideways_history.json")
METRICS_CACHE_FILE = os.path.join(os.path.dirname(__file__), "coinglass_metrics_snapshot.json")
SPOT_SYMBOLS_CACHE_FILE = os.path.join(os.path.dirname(__file__), "spot_symbols_snapshot.json")

METRIC_ALERT_MAX_STALE = 3600
METRIC_CACHE_MAX_STALE = 21600
REQUEST_TIMEOUT = 15
PREFIX_RULES = ["1000000", "10000", "1000", "1M"]


def safe_float(value):
    try:
        return float(value)
    except Exception:
        return 0.0


def load_json_file(file_path, default_value):
    if not os.path.exists(file_path):
        return default_value
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default_value


def save_json_file(file_path, payload):
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        print(f"save failed {os.path.basename(file_path)}: {exc}")


def normalize_contract_symbol(raw_symbol):
    symbol = str(raw_symbol or "").upper().strip()
    if not symbol:
        return ""

    symbol = symbol.replace("/", "").replace("_", "").replace("-", "")
    if symbol.endswith("PERP"):
        symbol = symbol[:-4]
    if not symbol.endswith("USDT"):
        if symbol.endswith("USD"):
            symbol += "T"
        else:
            symbol += "USDT"
    return symbol


def derive_spot_symbol(contract_symbol):
    for prefix in PREFIX_RULES:
        if contract_symbol.startswith(prefix):
            return contract_symbol[len(prefix):]
    return contract_symbol


def build_symbol_profile(contract_symbol, tradable_spot_symbols):
    spot_candidate = derive_spot_symbol(contract_symbol)
    has_spot = spot_candidate in tradable_spot_symbols
    mapping_status = "direct" if spot_candidate == contract_symbol else "mapped"
    if not has_spot:
        mapping_status = "no_spot"

    return {
        "contract_symbol": contract_symbol,
        "spot_symbol": spot_candidate if has_spot else None,
        "spot_candidate": spot_candidate,
        "display_name": contract_symbol.replace("USDT", ""),
        "mapping_status": mapping_status,
    }


def compute_confidence(board_type, metric_source, metric_freshness_sec):
    freshness = metric_freshness_sec if metric_freshness_sec is not None else 999999
    if board_type == "primary" and metric_source == "coinglass" and freshness <= METRIC_ALERT_MAX_STALE:
        return "high"
    if board_type == "primary":
        return "medium"
    if metric_source == "missing":
        return "low"
    return "medium"


def merge_metric_fields(item, metrics_data, binance_metrics, mc_map, cexscan_data, source, freshness):
    symbol = item["contract_symbol"]
    # 优先从币安原生数据读取成交量（最准）
    b_data = binance_metrics.get(symbol, {})
    vol_24h = b_data.get("vol_24h", 0)

    # 从 CEXScan 获取 12h 涨跌幅
    cex_item = cexscan_data.get(symbol.lower(), {})
    item["price_change_12h"] = safe_float(cex_item.get("_12hpricechange", 0))

    # 从Coinglass读取持仓（如果Coinglass没抓到，尝试单独抓币安）
    metric = metrics_data.get(symbol, {})
    oi_val = metric.get("oi", 0)

    # 强制对大盘币（权重币）直连币安抓最准的OI，防止Coinglass数据滞后或单位错误
    if symbol in ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "TRXUSDT", "XRPUSDT"]:
        oi_coins = fetch_binance_oi(symbol)
        price = b_data.get("price") or item.get("price", 0)
        if oi_coins > 0 and price > 0:
            oi_val = oi_coins * price

    # 填充结果
    item["oi_value"] = oi_val
    item["vol_value"] = vol_24h if vol_24h > 0 else metric.get("vol", 0)

    # 增加通过 Gate 获取的流通市值
    market_cap = mc_map.get(item["display_name"], 0)

    # 🚨 终极防线：能上币安合约的币，其真实流通市值绝不可能低于 1000 万刀！
    # 如果低于此数值，必定是 Gate.io 的 API 数据发生故障（如 USTC 返回 42万刀的 Bug）
    # 此时将其市值强行修改为极高值，防止产生虚假的巨额得分。
    if 0 < market_cap < 10_000_000:
        market_cap = float('inf')

    item["market_cap"] = market_cap if market_cap != float('inf') else 0
    item["oi_mc_ratio"] = (oi_val / market_cap) if market_cap > 0 else 0

    # 计算 Ratio
    if item["vol_value"] > 0:
        item["oi_vol_ratio"] = item["oi_value"] / item["vol_value"]
    else:
        item["oi_vol_ratio"] = 0.0

    # 做多评分逻辑: 评分 = (持仓/市值占比极大值 * 50) + (持仓/24h成交额占比极大值 * 10) + 横盘极长值
    dist_percent = item["oi_mc_ratio"] * 100
    long_score = dist_percent * 50 + item["oi_vol_ratio"] * 10 + item.get("duration_bars", 0)
    item["long_score"] = long_score

    item["metric_source"] = "binance+cg" if oi_val > 0 and vol_24h > 0 else source
    item["metric_freshness_sec"] = freshness if freshness is not None else 999999

    item["alert_eligible"] = (
        item["board_type"] == "primary"
        and item["metric_source"] != "missing"
        and item["metric_freshness_sec"] <= METRIC_ALERT_MAX_STALE
        and item["oi_vol_ratio"] > 0
    )
    item["confidence"] = compute_confidence(item["board_type"], item["metric_source"], item["metric_freshness_sec"])
    return item


def load_cached_spot_symbols():
    data = load_json_file(SPOT_SYMBOLS_CACHE_FILE, {})
    return set(data.get("symbols", [])) if isinstance(data, dict) else set()


def save_cached_spot_symbols(symbols):
    save_json_file(
        SPOT_SYMBOLS_CACHE_FILE,
        {"timestamp": int(time.time()), "symbols": sorted(symbols)},
    )


def fetch_spot_exchange_symbols():
    url = f"{VISION_BASE}/api/v3/exchangeInfo"
    try:
        res = requests.get(url, timeout=REQUEST_TIMEOUT)
        if res.status_code == 200:
            data = res.json()
            symbols = {
                item.get("symbol")
                for item in data.get("symbols", [])
                if item.get("symbol") and item.get("status") == "TRADING"
            }
            if symbols:
                save_cached_spot_symbols(symbols)
                return symbols
    except Exception as exc:
        print(f"spot exchangeInfo fetch failed: {exc}")
    return load_cached_spot_symbols()

def fetch_gate_spot_currencies():
    """从 Gate 获取现货币种详情，以拿到最原生的流通市值 market_cap"""
    url = "https://api.gateio.ws/api/v4/spot/currencies"
    try:
        res = requests.get(url, timeout=REQUEST_TIMEOUT)
        if res.status_code == 200:
            return {item["currency"]: safe_float(item.get("market_cap", 0)) for item in res.json()}
    except Exception as exc:
        print(f"gate currencies fetch failed: {exc}")
    return {}

def fetch_binance_ticker_metrics():
    """从币安期货获取所有币种的24h成交额（美元）- 走网关线路"""
    results = {}
    data = bg.fetch_futures_ticker() # 这会走 Vercel 线路
    if data:
        for item in data:
            symbol = item.get("symbol")
            if symbol and symbol.endswith("USDT"):
                results[symbol] = {
                    "vol_24h": safe_float(item.get("quoteVolume")),
                    "price": safe_float(item.get("lastPrice"))
                }
    return results

def fetch_cexscan_data():
    """从 CEXScan 获取全量币种 12h 涨跌幅和期货状态"""
    url = "https://www.cexscan.com/api/_dumpsymbols"
    params = {"exchange": "binance", "length": 1000}
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, params=params, headers=headers, timeout=10)
        if res.status_code == 200:
            items = res.json().get("data", [])
            # 建立以 symbol(小写) 为 key 的映射包
            return {item["symbol"].lower(): item for item in items}
    except Exception as exc:
        print(f"cexscan fetch failed: {exc}")
    return {}


def fetch_binance_oi(symbol):
    """从币安期货获取单个币种的实时持仓量 - 走网关线路"""
    # 这个网关里正好有现成的函数
    return bg.fetch_open_interest(symbol)


def fetch_spot_klines(symbol, interval="1h", limit=200):
    url = f"{VISION_BASE}/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    try:
        res = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        if res.status_code == 200:
            return symbol, res.json()
        return symbol, None
    except Exception:
        return symbol, None


def fetch_gate_ohlc(contract_symbol):
    gate_symbol = f"{contract_symbol.replace('USDT', '')}_USDT"
    url = "https://api.gateio.ws/api/v4/futures/usdt/candlesticks"
    params = {"contract": gate_symbol, "interval": "1h", "limit": LIMIT}
    try:
        res = requests.get(url, params=params, timeout=10)
        if res.status_code == 200:
            data = res.json()
            if data and len(data) >= 5:
                klines = []
                for row in data:
                    klines.append([
                        int(row["t"]) * 1000,
                        row["o"],
                        row["h"],
                        row["l"],
                        row["c"],
                        row["v"],
                        0,
                        0,
                        0,
                        0,
                        0,
                        0,
                    ])
                return contract_symbol, klines
    except Exception:
        pass
    return contract_symbol, None


def calc_bollinger_squeeze(klines):
    if not klines or len(klines) < BB_WINDOW:
        return 0, 0, 0

    closes = [float(k[4]) for k in klines]
    df = pd.DataFrame({"close": closes})
    df["ma"] = df["close"].rolling(window=BB_WINDOW).mean()
    df["std"] = df["close"].rolling(window=BB_WINDOW).std(ddof=0)
    df["upper"] = df["ma"] + 2 * df["std"]
    df["lower"] = df["ma"] - 2 * df["std"]
    df["bbw"] = (df["upper"] - df["lower"]) / df["ma"]
    bbw_series = df["bbw"].dropna().tolist()

    if not bbw_series:
        return 0, 0, 0

    bbw_reversed = list(reversed(bbw_series))
    duration = 0
    violations = 0

    for bw in bbw_reversed:
        if bw <= BBW_THRESHOLD:
            duration += 1
            violations = 0
        else:
            violations += 1
            if violations > BB_TOLERANCE:
                break
            duration += 1

    return duration, bbw_reversed[0], closes[-1]


async def fetch_coinglass_market_data():
    target_url = "https://www.coinglass.com/zh/exchanges/Binance"
    results = {}

    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=True, channel="msedge")
        except Exception:
            browser = await p.chromium.launch(headless=True)

        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = await context.new_page()

        inject_js = """
        (function() {
            if (window.__coinglassHookInstalled) return;
            window.__coinglassHookInstalled = true;
            window.__capturedMarketData = null;

            const originalParse = JSON.parse;
            JSON.parse = function(text) {
                const result = originalParse.apply(this, arguments);
                try {
                    if (text && text.length > 500 && result && typeof result === 'object') {
                        let list = null;
                        if (Array.isArray(result)) list = result;
                        else if (result.data && Array.isArray(result.data)) list = result.data;
                        else if (result.list && Array.isArray(result.list)) list = result.list;
                        else if (result.data && result.data.list && Array.isArray(result.data.list)) list = result.data.list;
                        if (list && list.length > 5) {
                            let first = list[0];
                            if (first && typeof first === 'object') {
                                let keys = Object.keys(first);
                                let hasSymbol = keys.includes('symbol') || keys.includes('uSymbol');
                                let hasOi = keys.includes('openInterest') || keys.includes('oi');
                                let hasVol = keys.includes('h24VolUsd') || keys.includes('vol24h') || keys.includes('volUsd') || keys.includes('volume24h');
                                if (hasSymbol && hasOi && (hasVol || keys.includes('marketCap'))) {
                                    window.__capturedMarketData = JSON.stringify(list);
                                }
                            }
                        }
                    }
                } catch(e) {}
                return result;
            };
        })();
        """
        await page.add_init_script(inject_js)

        try:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_function("() => Boolean(window.__capturedMarketData)", timeout=40000)
            raw_json = await page.evaluate("() => window.__capturedMarketData")
            data_list = json.loads(raw_json)


            if not isinstance(data_list, list):
                return results

            for item in data_list:
                if not isinstance(item, dict):
                    continue
                contract_symbol = normalize_contract_symbol(item.get("symbol") or item.get("uSymbol") or "")
                if not contract_symbol or contract_symbol in BLACKLIST:
                    continue

                oi_val = safe_float(item.get("openInterest") or item.get("oi"))
                vol_val = safe_float(
                    item.get("h24VolUsd")
                    or item.get("vol24h")
                    or item.get("volUsd")
                    or item.get("volume24h")
                    or item.get("vol")
                )
                if vol_val > 0:
                    results[contract_symbol] = {"oi": oi_val, "vol": vol_val}
        except Exception as exc:
            print(f"coinglass fetch error: {exc}")
        finally:
            await context.close()
            await browser.close()
    return results



def load_metrics_snapshot():
    data = load_json_file(METRICS_CACHE_FILE, {})
    if not isinstance(data, dict):
        return {}, None
    items = data.get("items", {}) if isinstance(data.get("items", {}), dict) else {}
    return items, data.get("timestamp")


def save_metrics_snapshot(items):
    save_json_file(METRICS_CACHE_FILE, {"timestamp": int(time.time()), "items": items})


async def get_coinglass_market_data():
    fresh_items = await fetch_coinglass_market_data()
    if fresh_items:
        save_metrics_snapshot(fresh_items)
        return fresh_items, "coinglass", 0

    cached_items, cached_ts = load_metrics_snapshot()
    if cached_items and cached_ts:
        freshness = int(time.time() - cached_ts)
        if freshness <= METRIC_CACHE_MAX_STALE:
            return cached_items, "cache", freshness

    return {}, "missing", None


def load_history():
    raw = load_json_file(HISTORY_FILE, {})
    if not isinstance(raw, dict):
        return {"primary": {}, "secondary": {}}
    if "primary" in raw or "secondary" in raw:
        return {"primary": raw.get("primary", {}), "secondary": raw.get("secondary", {})}
    return {"primary": raw, "secondary": {}}


def save_history(primary_results, secondary_results, prev_history):
    new_history = {"primary": {}, "secondary": {}}
    for board_name, valid_results in (("primary", primary_results[:25]), ("secondary", secondary_results[:25])):
        board_history = prev_history.get(board_name, {}) if isinstance(prev_history, dict) else {}
        for index, result in enumerate(valid_results):
            contract_symbol = result["contract_symbol"]
            old_item = board_history.get(contract_symbol, {})
            old_chain = old_item.get("rank_chain", [])
            new_chain = (old_chain + [index + 1])[-5:]
            new_history[board_name][contract_symbol] = {
                "rank_chain": new_chain,
                "on_board_count": old_item.get("on_board_count", 0) + 1,
                "last_bbw": result["amplitude"],
                "last_price": result["price"],
                "last_ratio": result.get("oi_vol_ratio", 0),
            }
    save_json_file(HISTORY_FILE, new_history)


def sort_board_items(items):
    return sorted(
        items,
        key=lambda item: (
            -item.get("long_score", 0),
            -item["duration_bars"],
            item["amplitude"],
            -item.get("oi_vol_ratio", 0),
            item["contract_symbol"],
        ),
    )


def build_result_item(profile, duration, amplitude, price, kline_source, board_type, comparability_group, coverage_level):
    return {
        "contract_symbol": profile["contract_symbol"],
        "spot_symbol": profile.get("spot_symbol"),
        "display_name": profile["display_name"],
        "mapping_status": profile["mapping_status"],
        "duration_bars": duration,
        "duration_hours": duration,
        "amplitude": amplitude,
        "price": price,
        "kline_source": kline_source,
        "source": kline_source,
        "board_type": board_type,
        "comparability_group": comparability_group,
        "coverage_level": coverage_level,
        "interval": INTERVAL,
        "kline_freshness_sec": 0,
    }


def build_uncovered_item(profile, reason, metric_source, metric_freshness_sec):
    return {
        "contract_symbol": profile["contract_symbol"],
        "spot_symbol": profile.get("spot_symbol"),
        "display_name": profile["display_name"],
        "mapping_status": profile["mapping_status"],
        "board_type": "uncovered",
        "coverage_level": "missing",
        "comparability_group": "uncovered",
        "kline_source": "missing",
        "metric_source": metric_source,
        "metric_freshness_sec": metric_freshness_sec if metric_freshness_sec is not None else 999999,
        "reason": reason,
    }


ALERT_HISTORY_FILE = os.path.join(os.path.dirname(__file__), "Logs", "alert_history.json")
DISAPPEARED_HISTORY_FILE = os.path.join(os.path.dirname(__file__), "Logs", "disappeared_history.json")

def load_alert_history():
    return load_json_file(ALERT_HISTORY_FILE, [])

def save_alert_to_file(text, item_data=None, timestamp=None):
    """保存报警到文本日志和结构化JSON日志"""
    # 1. 文本日志
    log_path = os.path.join(os.path.dirname(__file__), "Logs", "alert_log.txt")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    now_str = timestamp if timestamp else datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            # 修改为单行紧凑模式，减少冗余Header
            f.write(f"[{now_str}] {text}\n")
    except: pass

    # 2. 结构化JSON历史 (供前端加载历史)
    if item_data:
        history = load_alert_history()
        alert_entry = {
            "timestamp": now_str,
            "display_name": item_data["display_name"],
            "contract_symbol": item_data["contract_symbol"],
            "board_type": item_data["board_type"],
            "trend": item_data["trend"],
            "rank_change": item_data["rank_change"],
            "msg": text
        }
        history.insert(0, alert_entry)
        history = history[:100] # 保留最近100条
        save_json_file(ALERT_HISTORY_FILE, history)


def load_disappeared_history():
    return load_json_file(DISAPPEARED_HISTORY_FILE, [])


def save_disappeared_entry(entries, timestamp=None):
    """追加消失记录到JSON日志"""
    if not entries:
        return
    history = load_disappeared_history()
    history = entries + history
    history = history[:200]  # 保留最近200条
    os.makedirs(os.path.dirname(DISAPPEARED_HISTORY_FILE), exist_ok=True)
    save_json_file(DISAPPEARED_HISTORY_FILE, history)

    # 同时写入可读文本日志
    log_path = os.path.join(os.path.dirname(__file__), "Logs", "disappeared_log.txt")
    now_str = timestamp if timestamp else datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            for e in entries:
                f.write(f"[{now_str}] DISAPPEAR: {e['contract_symbol']} (Board:{e['board_type']}, Rounds:{e['on_board_count']}, LastBBW:{e['last_bbw']*100:.2f}%)\n")
    except Exception:
        pass


def detect_disappeared(current_primary_symbols, current_secondary_symbols, prev_history, timestamp=None):
    """
    检测从横盘列表中消失的币种。
    只有连续上榜 >= 2 次的币种消失时才值得记录，避免噪声。
    """
    now_str = timestamp if timestamp else datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    disappeared = []

    for board_name, current_symbols in (("primary", current_primary_symbols), ("secondary", current_secondary_symbols)):
        board_history = prev_history.get(board_name, {}) if isinstance(prev_history, dict) else {}
        for sym, hist_item in board_history.items():
            if sym not in current_symbols:
                on_board = hist_item.get("on_board_count", 0)
                if on_board >= 2:  # 只记录连续上榜>=2次后消失的
                    disappeared.append({
                        "timestamp": now_str,
                        "contract_symbol": sym,
                        "display_name": sym.replace("USDT", ""),
                        "board_type": board_name,
                        "on_board_count": on_board,
                        "last_bbw": hist_item.get("last_bbw", 0),
                        "last_price": hist_item.get("last_price", 0),
                        "last_ratio": hist_item.get("last_ratio", 0),
                        "rank_chain": hist_item.get("rank_chain", []),
                    })

    # 按霸榜次数降序排列，最值得关注的排前面
    disappeared.sort(key=lambda x: -x["on_board_count"])
    return disappeared


def finalize_board(board_items, board_history, timestamp=None):
    output_items = []
    now_str = timestamp if timestamp else datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    for index, item in enumerate(board_items[:25]):
        contract_symbol = item["contract_symbol"]
        hist = board_history.get(contract_symbol, {}) if isinstance(board_history, dict) else {}
        chain = hist.get("rank_chain", [])
        on_board = hist.get("on_board_count", 0)

        is_new = False
        if not chain:
            trend = "NEW"
            rank_change = 0
            is_new = True
        else:
            prev_rank = chain[-1]
            rank_change = prev_rank - (index + 1)
            trend = "UP" if rank_change > 0 else ("DOWN" if rank_change < 0 else "STABLE")

        # 异动报警判读: 1.新上榜币种 2.排名蹿升幅度过大(>=5)
        is_alert = False
        if is_new or rank_change >= 5:
            is_alert = True
            log_msg = f"币种: {contract_symbol} | 变动: {trend if is_new else f'提升 {rank_change} 名'} | 榜单: {item['board_type']} | 时长: {item['duration_hours']}h | BBW: {item['amplitude']*100:.2f}% | Ratio: {item.get('oi_vol_ratio',0):.2f}"

            alert_payload = {
                "display_name": item["display_name"],
                "contract_symbol": contract_symbol,
                "board_type": item["board_type"],
                "trend": trend,
                "rank_change": rank_change
            }
            save_alert_to_file(log_msg, alert_payload, timestamp=now_str)

        output_items.append(
            {
                "rank": index + 1,
                "contract_symbol": contract_symbol,
                "spot_symbol": item.get("spot_symbol"),
                "display_name": item["display_name"],
                "price": item["price"],
                "duration": item["duration_hours"],
                "duration_bars": item["duration_bars"],
                "duration_hours": item["duration_hours"],
                "bbw": round(item["amplitude"] * 100, 2),
                "price_change_12h": item.get("price_change_12h", 0),
                "oi_value": item.get("oi_value", 0),
                "vol_value": item.get("vol_value", 0),
                "market_cap": item.get("market_cap", 0),
                "oi_mc_ratio": round(item.get("oi_mc_ratio", 0), 4),
                "long_score": round(item.get("long_score", 0), 1),
                "oi_vol_ratio": round(item.get("oi_vol_ratio", 0), 2),
                "trend": trend,
                "rank_change": rank_change,
                "on_board_count": on_board,
                "rank_history": chain,
                "board_type": item["board_type"],
                "coverage_level": item["coverage_level"],
                "comparability_group": item["comparability_group"],
                "mapping_status": item["mapping_status"],
                "kline_source": item["kline_source"],
                "metric_source": item.get("metric_source", "missing"),
                "metric_freshness_sec": item.get("metric_freshness_sec", 999999),
                "confidence": item.get("confidence", "low"),
                "alert_eligible": item.get("alert_eligible", False),
                "is_alert": is_alert,
                "source": item.get("source", item["kline_source"]),
            }
        )
    return output_items


async def run_full_scan(prog_callback=None):
    def report(message):
        print(f"  {message}")
        if prog_callback:
            asyncio.create_task(prog_callback(message))

    scan_time = datetime.utcnow() + timedelta(hours=8)
    full_timestamp = scan_time.strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{scan_time.strftime('%H:%M:%S')}] start full scan")

    report("Step 1/4 loading Coinglass metrics")
    metrics_data, metric_source, metric_freshness_sec = await get_coinglass_market_data()
    report(f"metric source={metric_source}, contracts={len(metrics_data)}")
    if not metrics_data:
        report("no metrics available, returning empty boards")
        return {
            "primary_board": [],
            "secondary_board": [],
            "uncovered": [],
            "timestamp": scan_time.strftime("%H:%M:%S"),
            "total_scanned": 0,
            "total_primary": 0,
            "total_secondary": 0,
            "total_uncovered": 0,
            "total_sideways": 0,
            "ratio_drops": [],
        }

    report("Step 1.5/4 loading Gate.io Spot Market Cap")
    mc_map = fetch_gate_spot_currencies()
    report(f"market cap map loaded: {len(mc_map)} currencies")

    report("Step 2/4 loading Binance Vision spot symbols")
    tradable_spot_symbols = fetch_spot_exchange_symbols()
    report(f"spot symbols={len(tradable_spot_symbols)}")

    report("Step 2.5/4 loading CEXScan 12h market data")
    cexscan_data = fetch_cexscan_data()
    report(f"cexscan data items={len(cexscan_data)}")

    profiles = []
    for contract_symbol in sorted(metrics_data.keys()):
        if contract_symbol in BLACKLIST:
            continue
        profile = build_symbol_profile(contract_symbol, tradable_spot_symbols)
        if profile["spot_candidate"] in BLACKLIST:
            continue
        profiles.append(profile)

    report(f"contracts to scan={len(profiles)}")

    primary_results = []
    secondary_results = []
    uncovered_results = []
    gate_candidates = []

    primary_candidates = [profile for profile in profiles if profile.get("spot_symbol")]
    report(f"Step 3/4 Binance Vision candidates={len(primary_candidates)}")

    batch_size = 20
    for batch_start in range(0, len(primary_candidates), batch_size):
        batch = primary_candidates[batch_start:batch_start + batch_size]
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {
                executor.submit(fetch_spot_klines, profile["spot_symbol"], INTERVAL, LIMIT): profile
                for profile in batch
            }
            for future in as_completed(futures):
                profile = futures[future]
                _, klines = future.result()
                if klines:
                    duration, amplitude, price = calc_bollinger_squeeze(klines)
                    if duration >= MIN_DURATION:
                        primary_results.append(
                            build_result_item(
                                profile,
                                duration,
                                amplitude,
                                price,
                                "binance_vision",
                                "primary",
                                "binance_vision_spot_1h",
                                "primary",
                            )
                        )
                else:
                    gate_candidates.append(profile)
        if batch_start + batch_size < len(primary_candidates):
            await asyncio.sleep(0.5)

    gate_seen = {profile["contract_symbol"] for profile in gate_candidates}
    for profile in profiles:
        if not profile.get("spot_symbol") and profile["contract_symbol"] not in gate_seen:
            gate_candidates.append(profile)
            gate_seen.add(profile["contract_symbol"])

    report(f"Step 4/4 Gate.io candidates={len(gate_candidates)}")
    if gate_candidates:
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {
                executor.submit(fetch_gate_ohlc, profile["contract_symbol"]): profile
                for profile in gate_candidates
            }
            for future in as_completed(futures):
                profile = futures[future]
                _, klines = future.result()
                if klines:
                    duration, amplitude, price = calc_bollinger_squeeze(klines)
                    if duration >= MIN_DURATION:
                        secondary_results.append(
                            build_result_item(
                                profile,
                                duration,
                                amplitude,
                                price,
                                "gateio",
                                "secondary",
                                "gate_futures_1h",
                                "secondary",
                            )
                        )
                else:
                    reason = (
                        "no spot mapping and Gate.io failed"
                        if not profile.get("spot_symbol")
                        else "Binance Vision and Gate.io both failed"
                    )
    metrics_data, metric_source, metric_freshness_sec = await get_coinglass_market_data()
    binance_metrics = fetch_binance_ticker_metrics()

    primary_results = [merge_metric_fields(item, metrics_data, binance_metrics, mc_map, cexscan_data, metric_source, metric_freshness_sec) for item in primary_results]
    secondary_results = [merge_metric_fields(item, metrics_data, binance_metrics, mc_map, cexscan_data, metric_source, metric_freshness_sec) for item in secondary_results]

    primary_results = sort_board_items(primary_results)
    secondary_results = sort_board_items(secondary_results)
    uncovered_results = sorted(uncovered_results, key=lambda item: item["contract_symbol"])[:50]

    history = load_history()
    ratio_drops = []
    for item in primary_results[:25]:
        if not item.get("alert_eligible"):
            continue
        old_item = history.get("primary", {}).get(item["contract_symbol"], {})
        old_ratio = old_item.get("last_ratio", 0)
        new_ratio = item.get("oi_vol_ratio", 0)
        if old_ratio > 0 and new_ratio < old_ratio * 0.9:
            ratio_drops.append(item["display_name"])

    # 检测消失的币种
    current_primary_syms = {r["contract_symbol"] for r in primary_results[:25]}
    current_secondary_syms = {r["contract_symbol"] for r in secondary_results[:25]}
    newly_disappeared = detect_disappeared(current_primary_syms, current_secondary_syms, history, timestamp=full_timestamp)
    if newly_disappeared:
        save_disappeared_entry(newly_disappeared, timestamp=full_timestamp)
        report(f"detected {len(newly_disappeared)} coin(s) disappeared from boards")

    save_history(primary_results, secondary_results, history)

    return {
        "primary_board": finalize_board(primary_results, history.get("primary", {}), timestamp=full_timestamp),
        "secondary_board": finalize_board(secondary_results, history.get("secondary", {}), timestamp=full_timestamp),
        "uncovered": uncovered_results,
        "timestamp": scan_time.strftime("%H:%M:%S"),
        "total_scanned": len(profiles),
        "total_primary": len(primary_results),
        "total_secondary": len(secondary_results),
        "total_uncovered": len(uncovered_results),
        "total_sideways": len(primary_results) + len(secondary_results),
        "ratio_drops": ratio_drops,
        "alert_history": load_alert_history(),
        "disappeared": newly_disappeared,
        "disappeared_history": load_disappeared_history()[:50],
    }
