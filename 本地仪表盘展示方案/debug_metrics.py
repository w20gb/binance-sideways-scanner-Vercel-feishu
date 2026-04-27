
import asyncio
import json
from playwright.async_api import async_playwright

async def debug_coinglass():
    target_url = "https://www.coinglass.com/zh/exchanges/Binance"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        captured = []

        async def handle_response(response):
            try:
                if "api" in response.url:
                    text = await response.text()
                    if len(text) > 1000:
                        data = json.loads(text)
                        if isinstance(data, dict) and (data.get('data') or data.get('list')):
                            captured.append((response.url, data))
            except:
                pass

        page.on("response", handle_response)

        print(f"Navigating to {target_url}...")
        await page.goto(target_url, wait_until="networkidle", timeout=60000)
        await asyncio.sleep(5)

        for url, data in captured:
            print(f"\nURL: {url}")
            items = data.get('data', []) or data.get('list', [])
            if isinstance(items, list) and items:
                print("First item keys:", str(items[0].keys()))
                # Find BNB
                for item in items:
                    sym = str(item.get('symbol') or item.get('uSymbol') or "").upper()
                    if 'BNB' in sym:
                        print(f"BNB Item: {item}")
                        break

        await browser.close()

if __name__ == "__main__":
    asyncio.run(debug_coinglass())
