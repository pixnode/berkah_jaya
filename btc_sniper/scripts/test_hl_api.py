import aiohttp
import asyncio
import json
import time

async def get_hyperliquid_midprice():
    url = "https://api.hyperliquid.xyz/info"
    headers = {"Content-Type": "application/json"}
    payload = {
        "type": "l2Book",
        "coin": "BTC"
    }

    start_time = time.time()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    data = await response.json()
                    levels = data.get("levels", [])
                    if len(levels) >= 2:
                        best_bid = float(levels[0][0]["px"])
                        best_ask = float(levels[1][0]["px"])
                        mid_price = (best_bid + best_ask) / 2.0
                        latency = (time.time() - start_time) * 1000
                        
                        print(f"--- HYPERLIQUID API RESULT ---")
                        print(f"BTC Mid Price: ${mid_price:,.2f}")
                        print(f"Bid: ${best_bid:,.2f} | Ask: ${best_ask:,.2f}")
                        print(f"Latency: {latency:.1f}ms")
                        return mid_price
                else:
                    print(f"Error: HTTP {response.status}")
    except Exception as e:
        print(f"API Connection Failed: {e}")

if __name__ == "__main__":
    asyncio.run(get_hyperliquid_midprice())
