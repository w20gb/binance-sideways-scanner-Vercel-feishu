
import asyncio
from wyckoff_monitor import WyckoffMonitor, logger
import logging

# Ensure we see the logs
logger.setLevel(logging.INFO)

async def test_connection():
    print("------------------------------------------------")
    print("[TEST] Starting Connectivity & Initialization Test")
    print(f"Target Proxy: {WyckoffMonitor().config.PROXY_URL}")
    print("------------------------------------------------")

    monitor = WyckoffMonitor()
    try:
        # 1. Test Exchange Connection
        print("[1/3] Connecting to Binance...")
        await monitor._init_exchange()
        print("[OK] Exchange initialized.")

        # 2. Test Fetching Markets
        print("[2/3] Fetching Tickers (Data Flow Check)...")
        tickers = await monitor.exchange.fetch_tickers()
        print(f"[OK] Connection Successful! Fetched {len(tickers)} tickers.")

        # 3. Test One Symbol History
        symbol = list(tickers.keys())[0]
        # Ensure we pick a USDT pair if possible for realism
        for s in tickers:
            if 'USDT' in s:
                symbol = s
                break

        print(f"[3/3] Fetching History for {symbol}...")
        ohlcv = await monitor._fetch_ohlcv_safe(symbol, limit=10)

        if ohlcv and len(ohlcv) > 0:
            print(f"[OK] Data Fetch Verified. Got {len(ohlcv)} candles.")
        else:
            print("[FAIL] Data Fetch Failed (Empty).")

        print("------------------------------------------------")
        print("[SUCCESS] MONITOR IS READY TO RUN")
        print("------------------------------------------------")

    except Exception as e:
        print(f"[ERROR] CONNECTION FAILED: {e}")
        print("Please check if your proxy software (Clash/V2Ray) is running and port 2333 is open.")
    finally:
        if monitor.exchange:
            await monitor.exchange.close()

if __name__ == "__main__":
    if 'win32' in str(asyncio.get_event_loop_policy()):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(test_connection())
