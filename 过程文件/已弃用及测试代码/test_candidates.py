
import asyncio
import aiohttp
import sys

# Candidates provided by user
CANDIDATES = [
    "gemini.kajasa.xyz",
    "kajasa.xyz"
]

async def test_proxy(hostname):
    print(f"------------------------------------------------")
    print(f"[TEST] Testing Hostname: {hostname}")

    # Construct a valid Binance Futures URL using this hostname
    # Endpoint: /fapi/v1/ping (Weight: 1)
    url = f"https://{hostname}/fapi/v1/ping"

    print(f"   -> Requesting: {url}")

    try:
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                print(f"   -> Status Code: {resp.status}")
                if resp.status == 200:
                    text = await resp.text()
                    # Binance ping usually returns empty JSON {} or similar
                    print(f"   -> Response: {text}")
                    print(f"   ✅ SUCCESS! {hostname} appears to be a valid Binance Proxy.")
                    return True
                else:
                    print(f"   -> Response Headers: {resp.headers}")
                    print(f"   ❌ FAILED. Status is not 200.")
                    return False
    except Exception as e:
        print(f"   ❌ CONNECTION ERROR: {e}")
        return False

async def main():
    print("Checking Custom Proxy Candidates for Binance Futures (fapi)...")
    valid_proxies = []
    for host in CANDIDATES:
        if await test_proxy(host):
            valid_proxies.append(host)

    print("\n================ RESULT ================")
    if valid_proxies:
        print(f"✅ Found working proxy: {valid_proxies[0]}")
        print(f"You can set API_HOSTNAME = '{valid_proxies[0]}' in the config.")
    else:
        print("❌ None of the provided URLs worked as a Binance Proxy.")
        print("Note: 'gemini' in the name suggests it might be for Google Gemini AI, not Binance.")

if __name__ == "__main__":
    if 'win32' in str(asyncio.get_event_loop_policy()):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
