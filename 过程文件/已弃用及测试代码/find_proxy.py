
import asyncio
import aiohttp
import time
from aiohttp_socks import ProxyConnector

# Target: Binance Futures
TARGET_URL = "https://fapi.binance.com/fapi/v1/ping"

async def test_proxy(proxy_url):
    """
    Test a single proxy.
    Returns validity (bool) and latency (ms).
    """
    try:
        connector = ProxyConnector.from_url(proxy_url)
        start = time.time()
        async with aiohttp.ClientSession(connector=connector, timeout=aiohttp.ClientTimeout(total=5)) as session:
            async with session.get(TARGET_URL) as resp:
                latency = (time.time() - start) * 1000
                if resp.status == 200:
                    text = await resp.text()
                    if "{}" in text: # ping returns {}
                        return True, latency
    except Exception:
        pass
    return False, 0

async def fetch_and_test():
    print("------------------------------------------------")
    print("[AUTOPILOT] Hunting for Free Asian Proxies...")
    print("------------------------------------------------")

    # Fetch from ProxyScrape (HTTP only for simplicity first, EU/Asia)
    api_url = "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=5000&country=SG,JP,HK,TW,KR,DE,FR,NL,GB&ssl=yes&anonymity=all"

    proxies = []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    proxies = text.strip().split('\r\n')
                    proxies = [p for p in proxies if p]
    except Exception as e:
        print(f"[ERR] Failed to fetch proxy list: {e}")
        return

    print(f"Fetched {len(proxies)} candidates. Improved Testing...")

    valid_proxy = None

    # Test concurrency
    sem = asyncio.Semaphore(20) # Test 20 at a time

    async def worker(p):
        nonlocal valid_proxy
        if valid_proxy: return # Stop if found

        proxy_url = ""
        if "socks4" in p or "socks5" in p:
             proxy_url = f"{p}" # aiohttp_socks handles schema if in string, or we assume socks5?
             # actually proxyscrape returns ip:port. We need to guess or try.
             # But wait, the list is mixed?
             # Proxyscrape "protocol=http,socks4..." returns a list.
             # It's better to request separately or assume.
             # Let's simple try to prefix with http:// if not present, but aiohttp_socks needs socks5://
             pass

        # Simple heuristic: try as http proxy first (most common), then socks5
        # Actually for this script let's just use the returned list.
        # But we need schema.
        # Let's Force Protocol in API request to be single type per request?
        # No, let's just request HTTP proxies for now as they are easiest for aiohttp.
        proxy_url = f"http://{p}"

        async with sem:
            is_valid, lat = await test_proxy(proxy_url)
            if is_valid:
                print(f"[SUCCESS] Found Working Proxy: {proxy_url} (Latency: {lat:.1f}ms)")
                valid_proxy = proxy_url
            else:
                # print(f"[fail] {p}", end='\r')
                pass

    tasks = [worker(p) for p in proxies]
    # Gather but return early if found? asyncio.gather waits for all.
    # We will just run all compliant to semaphore.
    await asyncio.gather(*tasks)

    print("\n------------------------------------------------")
    if valid_proxy:
        print(f"FINAL RESULT: {valid_proxy}")
        with open("valid_proxy.txt", "w") as f:
            f.write(valid_proxy)
    else:
        print("No working proxy found in this batch.")
    print("------------------------------------------------")

if __name__ == "__main__":
    if 'win32' in str(asyncio.get_event_loop_policy()):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(fetch_and_test())
