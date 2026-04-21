#!/usr/bin/env python3
# ═══ FILE: btc_sniper/main.py ═══
"""
Polymarket BTC Sniper v2.3 — Entry Point.
Iterasi 0: scaffold with argparse and signal handling.
Full integration in Iterasi 8.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys

# Force UTF-8 for Windows consoles to avoid cp1252 UnicodeEncodeError
if sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from config import BotConfig, ConfigurationError, load_config

logger = logging.getLogger("btc_sniper")


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Polymarket BTC Sniper v2.3 — Latency Arbitrage System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--paper",
        action="store_true",
        default=False,
        help="Override PAPER_TRADING_MODE=True regardless of .env setting",
    )
    parser.add_argument(
        "--env",
        type=str,
        default=None,
        help="Path to .env file (default: .env in current directory)",
    )
    return parser.parse_args()


def setup_logging(level_str: str = "INFO") -> None:
    """Configure structured logging for the bot."""
    level = getattr(logging, level_str.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s.%(msecs)03d │ %(name)-20s │ %(levelname)-7s │ %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Reduce noise from third-party libraries
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("web3").setLevel(logging.WARNING)
    logging.getLogger("aiohttp").setLevel(logging.WARNING)


async def async_main(cfg: BotConfig) -> None:
    """Async entry point — starts the BotEngine."""
    from core.engine import BotEngine

    engine = BotEngine(cfg)

    # Graceful shutdown on SIGINT/SIGTERM
    loop = asyncio.get_running_loop()
    shutdown_initiated = False

    def _signal_handler() -> None:
        nonlocal shutdown_initiated
        if shutdown_initiated:
            return
        shutdown_initiated = True
        logger.info("Shutdown signal received — initiating graceful shutdown...")
        # Create task to stop the engine
        loop.create_task(engine.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            # Windows workaround: signals are handled via KeyboardInterrupt in main()
            pass

    try:
        await engine.start()
    except Exception as exc:
        if not shutdown_initiated:
            logger.critical("Uncaught exception in engine: %s", exc, exc_info=True)
    finally:
        # engine.stop() will be called here if start() returns naturally
        # or if an exception occurs. If triggered by signal, stop() was 
        # already tasked, but BotEngine.stop() is safe to call twice.
        if not shutdown_initiated:
            await engine.stop()
        else:
            # Wait a bit for the signal-triggered stop() task to complete if needed
            await asyncio.sleep(0.5)
        logger.info("Shutdown complete.")


def main() -> None:
    """Synchronous entry point."""
    args = parse_args()

    # Apply --paper override before loading config
    if args.paper:
        os.environ["PAPER_TRADING_MODE"] = "True"

    setup_logging(os.getenv("LOG_LEVEL", "INFO"))

    try:
        print("[1/3] Loading Configuration...")
        cfg = load_config(env_path=args.env)
        print(f"[2/3] Config Loaded. Mode: {'PAPER' if cfg.PAPER_TRADING_MODE else 'LIVE'}")
    except ConfigurationError as exc:
        logger.critical("Configuration error: %s", exc)
        sys.exit(1)

    try:
        print("[3/3] Starting Bot Engine... (Press Ctrl+C to stop)")
        asyncio.run(async_main(cfg))
    except KeyboardInterrupt:
        logger.info("Process interrupted.")
        sys.exit(0)


if __name__ == "__main__":
    main()
