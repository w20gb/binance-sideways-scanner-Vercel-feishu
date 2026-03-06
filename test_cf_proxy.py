
import asyncio
import aiohttp
import time

async def test_proxy(url_base):
    print(f"Testing Base URL: {url_base}")

    # Construct potential endpoints
    # Common CF worker proxy patterns:
    # 1. Direct replacement of hostname: https://custom.com/fapi/v1/ping
    # 2. Path prefix: https://custom.com/binance/fapi/v1/ping (less common for raw replacement)

    endpoints = [
        f"{url_base}/fapi/v1/ping",
        f"{url_base}/api/v3/ping",
        f"{url_base}/fapi/v1/time",
        f"{url_base}/api/v3/time"
    ]

    async with aiohttp.ClientSession() as session:
        for ep in endpoints:
            try:
                start = time.time()
                async with session.get(ep, timeout=5) as resp:
                    latency = (time.time() - start) * 1000
                    text = await resp.text()
                    print(f"  [{resp.status}] {ep} - {latency:.1f}ms")
                    if resp.status == 200:
                        print(f"     -> Response: {text[:100]}")
                        if "{}" in text or "serverTime" in text:
                            print("     -> LOOKS LIKE A VALID BINANCE PROXY!")
                    else:
                         print(f"     -> Error Response: {text[:100]}")
            except Exception as e:
                print(f"  [ERR] {ep} - {e}")

async def main():
    urls = [
        "https://binance-proxy.3046790769.workers.dev"
    ]

    for u in urls:
        await test_proxy(u)
        print("-" * 30)

if __name__ == "__main__":
    if 'win32' in str(asyncio.get_event_loop_policy()):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
