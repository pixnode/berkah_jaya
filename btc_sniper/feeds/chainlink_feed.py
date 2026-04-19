# ═══ FILE: btc_sniper/feeds/chainlink_feed.py ═══
"""
Chainlink BTC/USD Feed — polls on-chain price via Polygon RPC.
Emits ChainlinkEvent to the shared asyncio.Queue.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Optional

import aiohttp

from config import BotConfig
from feeds import ChainlinkEvent, DataStaleEvent

logger = logging.getLogger("btc_sniper.feeds.chainlink")

# Minimal ABI — only latestRoundData()
CHAINLINK_ABI = json.dumps([
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
])

# Function selector for latestRoundData()
LATEST_ROUND_DATA_SELECTOR = "0xfeaf968c"


class ChainlinkFeed:
    """Polls Chainlink BTC/USD on Polygon for strike price and freshness tracking."""

    def __init__(self, cfg: BotConfig, event_logger: Optional[object] = None) -> None:
        self._cfg = cfg
        self._event_logger = event_logger
        self._running: bool = False
        self._last_event: Optional[ChainlinkEvent] = None
        self._consecutive_failures: int = 0
        self._queue: Optional[asyncio.Queue] = None
        self._session: Optional[aiohttp.ClientSession] = None

    @property
    def last_event(self) -> Optional[ChainlinkEvent]:
        """Most recent ChainlinkEvent received."""
        return self._last_event

    @property
    def is_connected(self) -> bool:
        """Whether we have received at least one valid price recently."""
        if self._last_event is None:
            return False
        return (time.time() - self._last_event.timestamp) < 30.0

    async def get_strike_price(self) -> ChainlinkEvent:
        """Fetch the current Chainlink BTC/USD price (one-shot call)."""
        event = await self._poll_once()
        if event is None:
            raise RuntimeError("Failed to fetch Chainlink BTC/USD price")
        return event

    async def start_polling(self, queue: asyncio.Queue) -> None:
        """Start continuous polling loop, emitting ChainlinkEvents to queue."""
        self._queue = queue
        self._running = True
        self._consecutive_failures = 0

        # Create session if not already existing
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10),
            )

        logger.info("Chainlink feed starting — polling every %ds from %s", self._cfg.CHAINLINK_POLL_INTERVAL_SEC, self._cfg.POLYGON_RPC_URL)

        try:
            while self._running:
                event = await self._poll_once()
                if event is not None:
                    self._last_event = event
                    self._consecutive_failures = 0
                    await self._emit(event)
                else:
                    self._consecutive_failures += 1
                    if self._consecutive_failures >= 3:
                        logger.critical(
                            "Chainlink: %d consecutive RPC failures — emitting DataStaleEvent",
                            self._consecutive_failures,
                        )
                        stale_event = DataStaleEvent(
                            timestamp=time.time(),
                            source="chainlink",
                        )
                        await self._emit(stale_event)
                        await self._log_event(
                            "CHAINLINK_STALE", "chainlink",
                            f"{self._consecutive_failures} consecutive failures",
                        )
                        self._consecutive_failures = 0

                await asyncio.sleep(self._cfg.CHAINLINK_POLL_INTERVAL_SEC)

        except asyncio.CancelledError:
            logger.info("Chainlink feed task cancelled.")
        finally:
            await self.stop()

    async def stop(self) -> None:
        """Stop polling and close session."""
        self._running = False
        if self._session and not self._session.closed:
            await self._session.close()
            logger.info("Chainlink feed stopped and session closed.")

    async def _poll_once(self) -> Optional[ChainlinkEvent]:
        """Execute a single eth_call to latestRoundData() and parse the result."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10),
            )

        payload = {
            "jsonrpc": "2.0",
            "method": "eth_call",
            "params": [
                {
                    "to": self._cfg.CHAINLINK_CONTRACT_ADDRESS,
                    "data": LATEST_ROUND_DATA_SELECTOR,
                },
                "latest",
            ],
            "id": 1,
        }

        for attempt in range(3):
            try:
                async with self._session.post(
                    self._cfg.POLYGON_RPC_URL,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                ) as resp:
                    if resp.status != 200:
                        logger.warning("Chainlink RPC HTTP %d (attempt %d/3)", resp.status, attempt + 1)
                        await asyncio.sleep(2 ** attempt)
                        continue

                    result = await resp.json()
                    if "error" in result:
                        logger.warning("Chainlink RPC error: %s (attempt %d/3)", result["error"], attempt + 1)
                        await asyncio.sleep(2 ** attempt)
                        continue

                    hex_data = result.get("result", "")
                    return self._parse_round_data(hex_data)

            except asyncio.TimeoutError:
                logger.warning("CHAINLINK_RPC_TIMEOUT (attempt %d/3)", attempt + 1)
                await self._log_event("CHAINLINK_STALE", "chainlink", f"RPC timeout attempt {attempt + 1}/3")
                if attempt < 2: await asyncio.sleep(2 ** attempt)
            except aiohttp.ClientError as exc:
                logger.warning("CHAINLINK_RPC_DOWN: %s (attempt %d/3)", exc, attempt + 1)
                await self._log_event("CHAINLINK_STALE", "chainlink", f"RPC network error: {exc}")
                if attempt < 2: await asyncio.sleep(2 ** attempt)
            except Exception as exc:
                logger.error("Chainlink unexpected error: %s (attempt %d/3)", exc, attempt + 1)
                if attempt < 2: await asyncio.sleep(2 ** attempt)

        return None

    def _parse_round_data(self, hex_data: str) -> Optional[ChainlinkEvent]:
        """Parse the hex response from latestRoundData() into a ChainlinkEvent."""
        try:
            data = hex_data[2:] if hex_data.startswith("0x") else hex_data
            if len(data) < 320: return None

            answer_raw = int(data[64:128], 16)
            if answer_raw >= 2**255: answer_raw -= 2**256
            updated_at = int(data[192:256], 16)
            price = answer_raw / 1e8
            now = time.time()
            age_seconds = int(now - updated_at)

            if price <= 0 or price > 1_000_000: return None
            if age_seconds < 0: age_seconds = 0
            is_stale = age_seconds > self._cfg.CHAINLINK_MAX_AGE_SEC

            return ChainlinkEvent(
                timestamp=now,
                price=price,
                updated_at=float(updated_at),
                age_seconds=age_seconds,
                is_stale=is_stale,
            )
        except Exception as exc:
            logger.error("Chainlink: failed to parse round data: %s", exc)
            return None

    async def _emit(self, event: object) -> None:
        """Put event into the queue."""
        if self._queue is None: return
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("QUEUE_FULL: Chainlink event dropped")

    async def _log_event(self, event_type: str, source: str, details: str) -> None:
        """Log event via injected logger."""
        if self._event_logger is not None and hasattr(self._event_logger, "log_event"):
            try:
                from logs.audit_logger import EventRecord
                record = EventRecord(
                    timestamp=time.time(),
                    event_type=event_type,
                    window_id="",
                    trigger=source,
                    mode="",
                    details=details,
                    gate_failed=None,
                    state_snapshot_json="{}",
                )
                await self._event_logger.log_event(record)
            except Exception: pass
