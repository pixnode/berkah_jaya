#!/usr/bin/env python3
"""
Connection health check untuk Polymarket BTC Sniper.
Jalankan sebelum start bot:
  python scripts/check_connections.py

Checks semua koneksi dan print status.
Exit code 0 = semua OK, 1 = ada yang gagal.
"""

import asyncio
import os
import sys
import time

import aiohttp
import websockets

try:
    from web3 import AsyncWeb3, AsyncHTTPProvider
    WEB3_AVAILABLE = True
except ImportError:
    WEB3_AVAILABLE = False

try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import ApiCreds
    CLOB_AVAILABLE = True
except ImportError:
    CLOB_AVAILABLE = False


async def check_all_connections(cfg) -> dict[str, bool]:
    results = {}
    
    # 1. Polygon RPC + Chainlink
    print("Checking Polygon RPC + Chainlink...", end=" ", flush=True)
    if not WEB3_AVAILABLE:
        print("✗  FAILED: web3 not installed")
        results["polygon_rpc"] = False
    else:
        try:
            w3 = AsyncWeb3(AsyncHTTPProvider(cfg.POLYGON_RPC_URL))
            connected = await asyncio.wait_for(w3.is_connected(), timeout=10)
            if not connected:
                raise RuntimeError("w3.is_connected() returned False")
                
            block = await asyncio.wait_for(w3.eth.block_number, timeout=10)
            
            # Test Chainlink read
            CHAINLINK_ABI = [
                {
                    "inputs": [],
                    "name": "latestRoundData",
                    "outputs": [
                        {"name": "roundId", "type": "uint80"},
                        {"name": "answer", "type": "int256"},
                        {"name": "startedAt", "type": "uint256"},
                        {"name": "updatedAt", "type": "uint256"},
                        {"name": "answeredInRound", "type": "uint80"},
                    ],
                    "stateMutability": "view",
                    "type": "function",
                }
            ]
            from web3 import Web3
            contract = w3.eth.contract(
                address=Web3.to_checksum_address(cfg.CHAINLINK_CONTRACT_ADDRESS),
                abi=CHAINLINK_ABI
            )
            start_t = time.time()
            data = await asyncio.wait_for(
                contract.functions.latestRoundData().call(), timeout=10
            )
            lat = (time.time() - start_t) * 1000
            price = data[1] / 1e8
            age = int(time.time()) - data[3]
            print(f"v  BTC=${price:,.0f}  age={age}s  block={block}  latency={lat:.0f}ms")
            results["polygon_rpc"] = True
        except Exception as e:
            print(f"x  FAILED: {e}")
            results["polygon_rpc"] = False

    # 2. Hyperliquid WebSocket
    print("Checking Hyperliquid WebSocket...", end=" ", flush=True)
    try:
        async with websockets.connect(cfg.HYPERLIQUID_WS_URL, open_timeout=10) as ws:
            sub_msg = '{"method":"subscribe","subscription":{"type":"trades","coin":"BTC"}}'
            start_t = time.time()
            await asyncio.wait_for(ws.send(sub_msg), timeout=5)
            msg = await asyncio.wait_for(ws.recv(), timeout=10)
            lat = (time.time() - start_t) * 1000
            print(f"v  Connected, latency={lat:.0f}ms")
            results["hyperliquid_ws"] = True
    except Exception as e:
        print(f"x  FAILED: {e}")
        results["hyperliquid_ws"] = False

    # 3. Polymarket CLOB WebSocket
    print("Checking Polymarket CLOB WebSocket...", end=" ", flush=True)
    try:
        async with websockets.connect(cfg.POLY_WS_URL, open_timeout=10) as ws:
            start_t = time.time()
            ping_waiter = await ws.ping()
            await asyncio.wait_for(ping_waiter, timeout=5)
            lat = (time.time() - start_t) * 1000
            print(f"v  Connected, ping latency={lat:.0f}ms")
            results["polymarket_ws"] = True
    except Exception as e:
        print(f"x  FAILED: {e}")
        results["polymarket_ws"] = False

    # 4. Polymarket CLOB REST API
    print("Checking Polymarket CLOB API...", end=" ", flush=True)
    try:
        async with aiohttp.ClientSession() as session:
            # Polymarket api endpoint
            start_t = time.time()
            async with session.get(
                f"{cfg.CLOB_HOST}/health",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                status = resp.status
                if status == 404: 
                    # fallback check
                    start_t2 = time.time()
                    async with session.get(f"{cfg.CLOB_HOST}/auth/api-key", timeout=10) as fallback_resp:
                        lat = (time.time() - start_t2) * 1000
                        print(f"v  HTTP {fallback_resp.status} (reachable), latency={lat:.0f}ms")
                        results["clob_api"] = fallback_resp.status in (200, 401, 404, 405)
                else:
                    lat = (time.time() - start_t) * 1000
                    print(f"v  HTTP {status}, latency={lat:.0f}ms")
                    results["clob_api"] = status == 200
    except Exception as e:
        print(f"x  FAILED: {e}")
        results["clob_api"] = False

    # 5. Relayer (hanya jika live mode)
    if not cfg.PAPER_TRADING_MODE:
        print("Checking Polymarket Relayer...", end=" ", flush=True)
        try:
            async with aiohttp.ClientSession() as session:
                start_t = time.time()
                async with session.get(
                    f"{cfg.RELAYER_URL}/health",
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    lat = (time.time() - start_t) * 1000
                    print(f"v  HTTP {resp.status}, latency={lat:.0f}ms")
                    results["relayer"] = resp.status == 200
        except Exception as e:
            print(f"x  FAILED: {e}")
            results["relayer"] = False

        # 6. CLOB API credentials (hanya live mode)
        print("Checking CLOB API credentials...", end=" ", flush=True)
        if not CLOB_AVAILABLE:
             print("x  FAILED: py_clob_client not installed")
             results["clob_credentials"] = False
        else:
            try:
                client = ClobClient(
                    host=cfg.CLOB_HOST,
                    key=cfg.POLYMARKET_PRIVATE_KEY,
                    chain_id=cfg.POLY_CHAIN_ID,
                    creds=ApiCreds(
                        api_key=cfg.POLY_API_KEY,
                        api_secret=cfg.POLY_API_SECRET,
                        api_passphrase=cfg.POLY_API_PASSPHRASE,
                    ),
                )
                # Test API keys
                api_keys = client.get_api_keys()
                print(f"v  Authenticated")
                results["clob_credentials"] = True
            except Exception as e:
                print(f"x  FAILED: {e}")
                results["clob_credentials"] = False
    else:
        print("Relayer & credentials check: SKIPPED (paper mode)")

    return results


if __name__ == "__main__":
    # Force UTF-8 for Windows consoles
    if sys.stdout.encoding.lower() != 'utf-8':
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            pass

    # Add parent dir to path to import config
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    try:
        from config import load_config
        cfg = load_config()
    except Exception as e:
        print(f"Failed to load config: {e}")
        exit(1)

    print("\n" + "="*55)
    print("  POLYMARKET BTC SNIPER v2.3 — CONNECTION CHECK")
    mode = "[PAPER MODE]" if cfg.PAPER_TRADING_MODE else "[LIVE MODE]"
    print(f"  {mode}")
    print("="*55 + "\n")

    results = asyncio.run(check_all_connections(cfg))

    print("\n" + "="*55)
    all_ok = all(results.values())
    for name, ok in results.items():
        icon = "v" if ok else "x"
        print(f"  {icon}  {name}")
    print("="*55)

    if all_ok:
        print("  STATUS: ALL CONNECTIONS OK — siap start bot\n")
        exit(0)
    else:
        failed = [k for k, v in results.items() if not v]
        print(f"  STATUS: FAILED — {', '.join(failed)}")
        print("  Perbaiki koneksi di .env sebelum start bot\n")
        exit(1)
