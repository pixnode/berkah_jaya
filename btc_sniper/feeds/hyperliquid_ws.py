# ═══ FILE: btc_sniper/feeds/hyperliquid_ws.py ═══
"""
Hyperliquid WebSocket Feed — streams BTC price and trade data.
Emits PriceEvent and TradeEvent to the shared asyncio.Queue.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Optional

import websockets
import websockets.exceptions

from config import BotConfig
from feeds import DataStaleEvent, PriceEvent, TradeEvent

logger = logging.getLogger("btc_sniper.feeds.hyperliquid")


class HyperliquidFeed:
    """WebSocket client for Hyperliquid BTC price and trade feed."""

    def __init__(self, cfg: BotConfig, event_logger: Optional[object] = None) -> None:
        self._cfg = cfg
        self._event_logger = event_logger
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._connected: bool = False
        self._last_message_at: float = 0.0
        self._running: bool = False
        self._reconnect_count: int = 0
        self._queue: Optional[asyncio.Queue] = None

    @property
    def is_connected(self) -> bool:
        """Whether the WebSocket is currently connected and receiving data."""
        return self._connected

    @property
    def last_message_at(self) -> float:
        """Unix timestamp of the last received message."""
        return self._last_message_at

    async def start(self, queue: asyncio.Queue) -> None:
        """Start the feed — connect and begin streaming to queue."""
        self._queue = queue
        self._running = True
        self._reconnect_count = 0

        while self._running:
            try:
                await self._connect_and_stream()
            except websockets.exceptions.ConnectionClosed as exc:
                logger.warning("Hyperliquid WS connection closed: %s", exc)
                self._connected = False
                if not self._running:
                    break
                await self._reconnect_with_backoff()
            except asyncio.CancelledError:
                logger.info("Hyperliquid feed task cancelled.")
                break
            except Exception as exc:
                logger.error("Hyperliquid WS unexpected error: %s", exc, exc_info=True)
                self._connected = False
                if not self._running:
                    break
                await self._reconnect_with_backoff()

        self._connected = False
        logger.info("Hyperliquid feed stopped.")

    async def stop(self) -> None:
        """Stop the feed and close the WebSocket."""
        self._running = False
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
        self._connected = False

    async def _connect_and_stream(self) -> None:
        """Establish connection, subscribe, and process messages."""
        url = self._cfg.HYPERLIQUID_WS_URL
        logger.info("Connecting to Hyperliquid WS: %s", url)

        async with websockets.connect(
            url,
            ping_interval=None,  # We handle our own heartbeat
            close_timeout=5,
            max_size=10 * 1024 * 1024,  # 10MB max message
        ) as ws:
            self._ws = ws
            self._connected = True
            self._reconnect_count = 0
            self._last_message_at = time.time()
            logger.info("Hyperliquid WS connected.")

            # Log reconnect event
            await self._log_event("WS_RECONNECT", "hyperliquid", "connected", 0)

            # Subscribe to trades channel
            await ws.send(json.dumps({
                "method": "subscribe",
                "subscription": {"type": "trades", "coin": "BTC"},
            }))

            # Subscribe to l2Book channel
            await ws.send(json.dumps({
                "method": "subscribe",
                "subscription": {"type": "l2Book", "coin": "BTC"},
            }))

            logger.info("Subscribed to Hyperliquid BTC trades + l2Book channels.")

            # Start heartbeat task
            heartbeat_task = asyncio.create_task(self._heartbeat_loop(ws))

            try:
                async for raw_msg in ws:
                    if not self._running:
                        break
                    self._last_message_at = time.time()
                    await self._process_message(raw_msg)
            finally:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass

    async def _heartbeat_loop(self, ws: websockets.WebSocketClientProtocol) -> None:
        """Send periodic pings and check for pong responses."""
        interval = self._cfg.WS_HEARTBEAT_INTERVAL_SEC
        while self._running and self._connected:
            try:
                await asyncio.sleep(interval)
                pong_waiter = await ws.ping()
                try:
                    await asyncio.wait_for(pong_waiter, timeout=3.0)
                except asyncio.TimeoutError:
                    logger.warning("Hyperliquid WS heartbeat timeout — no pong in 3s")
                    await self._log_event(
                        "WS_HEARTBEAT_TIMEOUT", "hyperliquid",
                        "No pong received within 3 seconds", 0,
                    )
                    # Force reconnect by closing
                    await ws.close()
                    return
            except asyncio.CancelledError:
                return
            except websockets.exceptions.ConnectionClosed:
                return
            except Exception as exc:
                logger.error("Heartbeat error: %s", exc)
                return

    async def _process_message(self, raw_msg: str) -> None:
        """Parse and dispatch a WebSocket message."""
        try:
            data = json.loads(raw_msg)
        except json.JSONDecodeError:
            logger.warning("Hyperliquid: invalid JSON message, skipping")
            return

        channel = data.get("channel", "")

        if channel == "trades":
            trades_data = data.get("data", [])
            for trade in trades_data:
                await self._handle_trade(trade)
        elif channel == "l2Book":
            book_data = data.get("data", {})
            await self._handle_l2book(book_data)

    async def _handle_trade(self, trade: dict) -> None:
        """Parse a trade message and emit TradeEvent + PriceEvent."""
        try:
            price = float(trade.get("px", 0))
            size = float(trade.get("sz", 0))
            raw_side = trade.get("side", "").upper()

            if raw_side == "A":
                side = "sell"
            elif raw_side == "B":
                side = "buy"
            else:
                side = "buy" if raw_side == "BUY" else "sell"

            now = time.time()

            trade_event = TradeEvent(
                timestamp=now,
                price=price,
                size=size,
                side=side,
            )

            price_event = PriceEvent(
                timestamp=now,
                price=price,
            )

            await self._emit(trade_event)
            await self._emit(price_event)

        except (KeyError, ValueError, TypeError) as exc:
            logger.debug("Hyperliquid: failed to parse trade: %s — %s", trade, exc)

    async def _handle_l2book(self, book_data: dict) -> None:
        """Parse l2Book and emit PriceEvent from mid price."""
        try:
            levels = book_data.get("levels", [])
            if len(levels) >= 2:
                bids = levels[0]
                asks = levels[1]
                if bids and asks:
                    best_bid = float(bids[0].get("px", 0))
                    best_ask = float(asks[0].get("px", 0))
                    if best_bid > 0 and best_ask > 0:
                        mid_price = (best_bid + best_ask) / 2.0
                        price_event = PriceEvent(
                            timestamp=time.time(),
                            price=mid_price,
                        )
                        await self._emit(price_event)
        except (KeyError, ValueError, TypeError, IndexError) as exc:
            logger.debug("Hyperliquid: failed to parse l2Book: %s", exc)

    async def _emit(self, event: object) -> None:
        """Put event into the queue with smart backpressure logic."""
        if self._queue is None:
            return

        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            q_size = self._queue.qsize()
            max_size = self._queue.maxsize or 1
            fill_pct = (q_size / max_size) * 100

            # Informative logging based on severity
            if fill_pct >= 90:
                logger.error(
                    "QUEUE_CRITICAL: %d%% full — processor too slow, "
                    "consider increasing CVD_CALC_INTERVAL_MS", int(fill_pct)
                )
            elif fill_pct >= 70:
                logger.warning("QUEUE_HIGH: %d%% full", int(fill_pct))

            # Smart Drop Logic
            if isinstance(event, TradeEvent):
                # TradeEvents are okay to drop under pressure (CVD will be slightly less accurate)
                pass
            else:
                # PriceEvent and ChainlinkEvent: never drop. Block briefly to ensure delivery.
                try:
                    await asyncio.wait_for(self._queue.put(event), timeout=0.1)
                except asyncio.TimeoutError:
                    logger.error("CRITICAL: Non-trade event dropped after timeout — %s", type(event).__name__)

    async def _reconnect_with_backoff(self) -> None:
        """Reconnect with exponential backoff. Emits DataStaleEvent if max retries exceeded."""
        self._reconnect_count += 1
        max_retry = self._cfg.WS_RECONNECT_MAX_RETRY

        if self._reconnect_count > max_retry:
            logger.critical(
                "Hyperliquid WS: max reconnect attempts (%d) exceeded — emitting DataStaleEvent",
                max_retry,
            )
            if self._queue is not None:
                stale_event = DataStaleEvent(timestamp=time.time(), source="hyperliquid")
                try:
                    self._queue.put_nowait(stale_event)
                except asyncio.QueueFull:
                    pass
            await self._log_event(
                "WS_RECONNECT", "hyperliquid",
                f"Max retries ({max_retry}) exceeded — LOCKDOWN",
                self._reconnect_count,
            )
            self._running = False
            return

        # Exponential backoff: 1s, 2s, 4s, 8s, ... capped at 30s
        delay = min(2 ** (self._reconnect_count - 1), 30)
        logger.info(
            "Hyperliquid WS reconnecting in %ds (attempt %d/%d)...",
            delay, self._reconnect_count, max_retry,
        )
        await self._log_event(
            "WS_RECONNECT", "hyperliquid",
            f"Reconnecting attempt {self._reconnect_count}/{max_retry}, delay {delay}s",
            self._reconnect_count,
        )
        await asyncio.sleep(delay)

    async def _log_event(self, event_type: str, source: str, details: str, attempt: int) -> None:
        """Log event via the injected event logger (if available)."""
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
            except Exception:
                pass  # Don't let logging failures crash the feed
