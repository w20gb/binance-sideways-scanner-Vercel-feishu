
import asyncio
import aiohttp
import json
import sys

# 代理配置 (必须与 wyckoff_monitor.py 一致)
PROXY_URL = "http://127.0.0.1:2333"

async def check_region():
    print("------------------------------------------------")
    print("[DIAGNOSTIC] Checking Proxy Region & Binance Access")
    print(f"Proxy: {PROXY_URL}")
    print("------------------------------------------------")

    timeout = aiohttp.ClientTimeout(total=10)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        # 1. 检查 IP 归属地
        print("\n[1/3] Checking Proxy Location...")
        try:
            # ip-api.com returns JSON with countryCode
            # We use http to avoid SSL handshake issues on some proxies, or https if stable
            async with session.get("http://ip-api.com/json/", proxy=PROXY_URL) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    country = data.get("country", "Unknown")
                    country_code = data.get("countryCode", "??")
                    ip = data.get("query", "0.0.0.0")
                    print(f"[OK] Your Proxy IP: {ip}")
                    print(f"[OK] Detected Location: {country} ({country_code})")

                    if country_code in ["US", "SG", "CN"]:
                        print(f"[WARNING] Location '{country_code}' might be restricted by Binance!")
                    else:
                        print("[OK] Location seems SAFE (Non-US/CN).")
                else:
                    print(f"[FAIL] Failed to get location. Status: {resp.status}")
        except Exception as e:
            print(f"[FAIL] Proxy connectivity failed: {e}")
            print("   -> Is your proxy software running?")
            print("   -> Is the port 2333 correct?")
            return

        # 2. 检查 Binance 现货 API
        print("\n[2/3] Checking Binance Spot API (api.binance.com)...")
        try:
            async with session.get("https://api.binance.com/api/v3/ping", proxy=PROXY_URL) as resp:
                if resp.status == 200:
                    print("[OK] Spot API is ACCESSIBLE.")
                elif resp.status == 451:
                    print("[FAIL] Spot API Restricted (Error 451). Region blocked.")
                else:
                    print(f"[WARN] Spot API Status: {resp.status}")
        except Exception as e:
            print(f"[FAIL] Spot API Connect Failed: {e}")

        # 3. 检查 Binance 合约 API
        print("\n[3/3] Checking Binance Futures API (fapi.binance.com)...")
        try:
            async with session.get("https://fapi.binance.com/fapi/v1/ping", proxy=PROXY_URL) as resp:
                if resp.status == 200:
                    print("[OK] Futures API is ACCESSIBLE.")
                elif resp.status == 451:
                    print("[FAIL] Futures API Restricted (Error 451). Region blocked.")
                else:
                    print(f"[WARN] Futures API Status: {resp.status}")
        except Exception as e:
            print(f"[FAIL] Futures API Connect Failed: {e}")

    print("\n------------------------------------------------")
    print("SUMMARY")
    print("If you see [OK] for Location and APIs, you are good to go.")
    print("If you see [FAIL] Error 451, switch your proxy node.")
    print("------------------------------------------------")

if __name__ == "__main__":
    if 'win32' in str(asyncio.get_event_loop_policy()):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(check_region())
