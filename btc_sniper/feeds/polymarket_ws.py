# === FILE: btc_sniper/feeds/polymarket_ws.py ===
"""
Polymarket CLOB WebSocket Feed — streams order book and odds data.
Emits OrderBookEvent and OddsEvent to the shared asyncio.Queue.
Auto-subscribes to the active window on first connect.
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
from feeds import DataStaleEvent, OddsEvent, OrderBookEvent

logger = logging.getLogger("btc_sniper.feeds.polymarket")


class PolymarketFeed:
    """WebSocket client for Polymarket CLOB order book and odds feed."""

    def __init__(self, cfg: BotConfig, event_logger: Optional[object] = None) -> None:
        self._cfg = cfg
        self._event_logger = event_logger
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._connected: bool = False
        self._last_message_at: float = 0.0
        self._running: bool = False
        self._reconnect_count: int = 0
        self._queue: Optional[asyncio.Queue] = None
        self._current_slug: Optional[str] = None
        self._up_depth_usdc: float = 0.0
        self._down_depth_usdc: float = 0.0

    @property
    def is_connected(self) -> bool:
        """Whether the WebSocket is currently connected."""
        return self._connected

    @property
    def is_subscribed(self) -> bool:
        """Whether the feed is subscribed to a market slug."""
        return self._current_slug is not None

    @property
    def sync_latency(self) -> float:
        """Time in seconds since the last message was received."""
        if self._last_message_at <= 0:
            return 0.0
        return time.time() - self._last_message_at

    @property
    def last_message_at(self) -> float:
        """Unix timestamp of the last received message.
        Returns current time if not yet subscribed (= not stale)."""
        if not self.is_subscribed:
            return time.time()
        return self._last_message_at

    async def subscribe(self, market_slug: str) -> None:
        """Subscribe to a specific market window slug."""
        self._current_slug = market_slug
        self._last_message_at = time.time()  # Reset stale timer on subscribe
        if self._ws is not None and self._connected:
            await self._send_subscribe(market_slug)

    async def unsubscribe(self) -> None:
        """Unsubscribe from the current market."""
        if self._ws is not None and self._connected and self._current_slug:
            try:
                await self._ws.send(json.dumps({
                    "type": "unsubscribe",
                    "market": self._current_slug,
                }))
                logger.info("Unsubscribed from Polymarket market: %s", self._current_slug)
            except Exception as exc:
                logger.warning("Failed to unsubscribe: %s", exc)
        self._current_slug = None

    def set_active_tokens(self, up_id: str, down_id: str) -> None:
        """Inject active Token IDs from the engine to avoid redundant API calls."""
        self._up_token_id = str(up_id).strip()
        self._down_token_id = str(down_id).strip()
        logger.info("PolymarketFeed: Active tokens injected (UP: %s, DOWN: %s)", up_id, down_id)

    async def start(self, queue: asyncio.Queue) -> None:
        """Start the feed — connect and begin streaming to queue."""
        self._queue = queue
        self._running = True
        self._reconnect_count = 0

        while self._running:
            try:
                await self._connect_and_stream()
            except websockets.exceptions.ConnectionClosed as exc:
                logger.warning("Polymarket WS connection closed: %s", exc)
                self._connected = False
                self._current_slug = None
                if not self._running:
                    break
                await self._reconnect_with_backoff()
            except asyncio.CancelledError:
                logger.info("Polymarket feed task cancelled.")
                break
            except Exception as exc:
                logger.error("Polymarket WS unexpected error: %s", exc, exc_info=True)
                self._connected = False
                self._current_slug = None
                if not self._running:
                    break
                await self._reconnect_with_backoff()

        self._connected = False
        logger.info("Polymarket feed stopped.")

    async def stop(self) -> None:
        """Stop the feed and close the WebSocket."""
        self._running = False
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
        self._connected = False
        self._current_slug = None

    async def _connect_and_stream(self) -> None:
        """Establish connection and process messages."""
        url = self._cfg.POLY_WS_URL
        logger.info("Connecting to Polymarket WS: %s", url)

        async with websockets.connect(
            url,
            ping_interval=None,
            close_timeout=5,
            max_size=10 * 1024 * 1024,
        ) as ws:
            self._ws = ws
            self._connected = True
            self._reconnect_count = 0
            self._last_message_at = time.time()
            logger.info("Polymarket WS connected.")

            await self._log_event("WS_RECONNECT", "polymarket", "connected", 0)

            # Auto-subscribe to the active window on first connect
            now = int(time.time())
            window_start = now - (now % 300)
            initial_slug = f"btc-updown-5m-{window_start}"
            await self.subscribe(initial_slug)
            logger.info("Polymarket: auto-subscribed to initial window %s", initial_slug)

            # Start heartbeat
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

    async def _send_subscribe(self, market_slug: str) -> None:
        """Send subscription message for a market using injected or known IDs."""
        if self._ws is None:
            return
            
        try:
            # Use injected IDs if available, otherwise fallback to slug
            up_id = getattr(self, "_up_token_id", "")
            down_id = getattr(self, "_down_token_id", "")
            
            ids_to_sub = []
            if up_id: ids_to_sub.append(up_id)
            if down_id: ids_to_sub.append(down_id)
            
            if not ids_to_sub:
                # If no IDs yet, we subscribe to the market slug as fallback
                logger.warning("No token IDs available for %s yet, subscribing to slug", market_slug)
                payload = {
                    "type": "subscribe",
                    "assets_ids": [market_slug],
                    "channels": ["book"]
                }
            else:
                logger.info("Subscribing to WebSocket for tokens: %s", ids_to_sub)
                payload = {
                    "type": "subscribe",
                    "assets_ids": ids_to_sub,
                    "channels": ["book"]
                }

            await self._ws.send(json.dumps(payload))
            
        except Exception as exc:
            logger.error("Failed to send WS subscribe for %s: %s", market_slug, exc)

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
                    logger.warning("Polymarket WS heartbeat timeout — no pong in 3s")
                    await self._log_event(
                        "WS_HEARTBEAT_TIMEOUT", "polymarket",
                        "No pong received within 3 seconds", 0,
                    )
                    await ws.close()
                    return
            except asyncio.CancelledError:
                return
            except websockets.exceptions.ConnectionClosed:
                return
            except Exception as exc:
                logger.error("Polymarket heartbeat error: %s", exc)
                return

    async def _process_message(self, raw_msg: str) -> None:
        """Parse and dispatch a Polymarket WebSocket message."""
        if not raw_msg or raw_msg.strip() == "":
            return

        try:
            data = json.loads(raw_msg)
        except json.JSONDecodeError:
            logger.debug("Polymarket: non-JSON message received, skipping")
            return

        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    await self._dispatch_single_message(item)
        elif isinstance(data, dict):
            await self._dispatch_single_message(data)

    async def _dispatch_single_message(self, data: dict) -> None:
        """Helper to route a single dictionary payload."""
        msg_type = data.get("type", "")
        event_type = data.get("event_type", "")

        if msg_type == "book" or event_type == "book":
            await self._handle_book_update(data)
        elif msg_type in ("price_change", "last_trade_price") or event_type in ("price_change", "last_trade_price"):
            pass  # Diabaikan — kita hanya pakai order book untuk pricing
        elif msg_type == "tick_size_change":
            pass
        elif msg_type == "error":
            logger.error("Polymarket WS error: %s", data.get("message", "unknown"))

    async def _handle_book_update(self, data: dict) -> None:
        """Parse order book update and emit OrderBookEvent."""
        try:
            market = data.get("market", data.get("asset_id", ""))
            bids = data.get("bids", [])
            asks = data.get("asks", [])

            up_ask = 0.0
            up_bid = 0.0
            down_ask = 0.0
            down_bid = 0.0

            raw_ask = 0.0
            raw_bid = 0.0
            current_depth = 0.0
            
            if asks:
                raw_ask = float(asks[0].get("price", asks[0].get("px", 0)))
                # Calculate depth USDC (Σ price * size) for top 10 asks within price range
                for a in asks[:10]:
                    p = float(a.get("price", a.get("px", 0)))
                    s = float(a.get("size", a.get("sz", 0)))
                    if 0.01 <= p <= 0.50:
                        current_depth += (p * s)
            
            if bids:
                raw_bid = float(bids[0].get("price", bids[0].get("px", 0)))
                
            # Flexible ID identification
            asset_id = str(data.get("market", data.get("asset_id", ""))).strip()
            up_id = str(getattr(self, "_up_token_id", "")).strip()
            down_id = str(getattr(self, "_down_token_id", "")).strip()

            # If IDs are not set, we try to guess based on order of arrival (fallback)
            if not up_id and not down_id:
                # No IDs injected yet, but we got a message? Use it.
                self._up_token_id = asset_id
                up_id = asset_id
                logger.info("PolymarketFeed: Auto-assigned unknown ID to UP slot: %s", asset_id)

            if asset_id == down_id:
                self._down_depth_usdc = current_depth
                down_ask = raw_ask
                down_bid = raw_bid
                up_bid = round(1.0 - down_ask, 4) if down_ask > 0 else 0.0
                up_ask = round(1.0 - down_bid, 4) if down_bid > 0 else 0.0
            elif asset_id == up_id:
                self._up_depth_usdc = current_depth
                up_ask = raw_ask
                up_bid = raw_bid
                down_bid = round(1.0 - up_ask, 4) if up_ask > 0 else 0.0
                down_ask = round(1.0 - up_bid, 4) if up_bid > 0 else 0.0
            else:
                # If we have IDs but this one doesn't match, maybe it's the OTHER one we missed?
                # Let's be aggressive: if we only have UP and this is different, assume it's DOWN.
                if up_id and not down_id:
                    self._down_token_id = asset_id
                    down_id = asset_id
                    logger.info("PolymarketFeed: Auto-assigned unknown ID to DOWN slot: %s", asset_id)
                elif down_id and not up_id:
                    self._up_token_id = asset_id
                    up_id = asset_id
                    logger.info("PolymarketFeed: Auto-assigned unknown ID to UP slot: %s", asset_id)
                else:
                    # Diagnostics: log mismatch
                    now = time.time()
                    if not hasattr(self, "_last_unknown_log"): self._last_unknown_log = 0
                    if now - self._last_unknown_log > 10:
                        self._last_unknown_log = now
                        logger.info("Polymarket: Asset ID mismatch. Received: %s | Expected UP: %s, DOWN: %s", asset_id, up_id, down_id)
                    return

            mid = (up_ask + up_bid) / 2.0 if (up_ask > 0 and up_bid > 0) else 1.0
            spread_pct = ((up_ask - up_bid) / mid * 100.0) if mid > 0 else 0.0

            now = time.time()
            book_event = OrderBookEvent(
                timestamp=now,
                up_ask=up_ask,
                up_bid=up_bid,
                down_ask=down_ask,
                down_bid=down_bid,
                spread_pct=round(spread_pct, 4),
                up_ask_depth_usdc=self._up_depth_usdc,
                down_ask_depth_usdc=self._down_depth_usdc
            )
            await self._emit(book_event)

            # Signal Odds is now strictly from BEST ASK
            odds_event = OddsEvent(timestamp=now, up_odds=up_ask, down_odds=down_ask)
            await self._emit(odds_event)

        except (KeyError, ValueError, TypeError, IndexError) as exc:
            logger.debug("Polymarket: failed to parse book update: %s", exc)

    async def _emit(self, event: object) -> None:
        """Put event into the queue."""
        if self._queue is None:
            return
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("QUEUE_FULL: Polymarket event dropped — queue at capacity")
            await self._log_event("QUEUE_FULL", "polymarket", "Event dropped", 0)

    async def _reconnect_with_backoff(self) -> None:
        """Reconnect with exponential backoff."""
        self._reconnect_count += 1
        max_retry = self._cfg.WS_RECONNECT_MAX_RETRY

        if self._reconnect_count > max_retry:
            logger.critical(
                "Polymarket WS: max reconnect attempts (%d) exceeded — emitting DataStaleEvent",
                max_retry,
            )
            if self._queue is not None:
                stale_event = DataStaleEvent(timestamp=time.time(), source="polymarket")
                try:
                    self._queue.put_nowait(stale_event)
                except asyncio.QueueFull:
                    pass
            await self._log_event(
                "WS_RECONNECT", "polymarket",
                f"Max retries ({max_retry}) exceeded — LOCKDOWN",
                self._reconnect_count,
            )
            self._running = False
            return

        delay = min(2 ** (self._reconnect_count - 1), 30)
        logger.info(
            "Polymarket WS reconnecting in %ds (attempt %d/%d)...",
            delay, self._reconnect_count, max_retry,
        )
        await self._log_event(
            "WS_RECONNECT", "polymarket",
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
                    window_id=self._current_slug or "",
                    trigger=source,
                    mode="",
                    details=details,
                    gate_failed=None,
                    state_snapshot_json="{}",
                )
                await self._event_logger.log_event(record)
            except Exception:
                pass
