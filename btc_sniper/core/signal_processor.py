# ═══ FILE: btc_sniper/core/signal_processor.py ═══
"""
Signal Processor — CVD, ATR, Gap, Velocity calculations.
Iteration 11: Tiered Processing + Smart Backpressure.
Tier 1: Instant Price/Velocity/Gap updates.
Tier 2: Periodic CVD calculation via background task.
"""

from __future__ import annotations

import asyncio
import collections
import logging
import time
from dataclasses import dataclass, field
from typing import Deque, Literal, Optional

from config import BotConfig
from feeds import (
    ChainlinkEvent,
    DataStaleEvent,
    OddsEvent,
    OrderBookEvent,
    PriceEvent,
    TradeEvent,
)

logger = logging.getLogger("btc_sniper.core.signal_processor")


@dataclass
class Candle:
    """A single 5-minute OHLC candle."""
    timestamp: float
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class SignalState:
    """Snapshot of all signal values at a point in time."""
    timestamp: float = 0.0
    current_hl_price: float = 0.0
    strike_price: float = 0.0
    gap: float = 0.0
    gap_direction: Literal["UP", "DOWN", "NEUTRAL"] = "NEUTRAL"
    gap_threshold: float = 45.0
    vol_regime: Literal["LOW", "NORM", "HIGH"] = "NORM"
    atr: float = 0.0
    cvd_60s: float = 0.0
    cvd_threshold: float = 0.0
    cvd_threshold_pct: float = 25.0
    avg_volume_per_min: float = 0.0
    cvd_aligned: bool = False
    velocity_1_5s: float = 0.0
    velocity_pass: bool = False


class SignalProcessor:
    """Consumes feed events and maintains real-time signal state with tiered processing."""

    def __init__(self, cfg: BotConfig) -> None:
        self._cfg = cfg

        # ── CVD rolling window ────────────────────────
        # Each entry: (timestamp, net_delta)
        self._cvd_deque: Deque[tuple[float, float]] = collections.deque()
        self._cvd_running: float = 0.0  # O(1) running total
        
        # Volume tracking for avg_volume_per_min
        self._volume_deque: Deque[tuple[float, float]] = collections.deque()
        self._volume_running: float = 0.0  # O(1) running total

        # ── Velocity tracking ─────────────────────────
        # Each entry: (timestamp, price)
        self._velocity_deque: Deque[tuple[float, float]] = collections.deque()

        # ── ATR candle tracking ───────────────────────
        self._candle_deque: Deque[Candle] = collections.deque(maxlen=cfg.ATR_LOOKBACK_CANDLES)
        self._current_candle: Optional[Candle] = None
        self._current_candle_start: float = 0.0

        # ── Current state ─────────────────────────────
        self._state = SignalState()
        self._state.cvd_threshold_pct = cfg.CVD_THRESHOLD_PCT

        # ── Latest order book / odds ──────────────────
        self._latest_book: Optional[OrderBookEvent] = None
        self._latest_odds: Optional[OddsEvent] = None
        self._latest_chainlink: Optional[ChainlinkEvent] = None

        # ── Running flag & Tasks ──────────────────────
        self._running: bool = False
        self._cvd_task: Optional[asyncio.Task] = None

    @property
    def state(self) -> SignalState:
        """Current signal state snapshot."""
        return self._state

    @property
    def latest_book(self) -> Optional[OrderBookEvent]:
        """Latest order book event."""
        return self._latest_book

    @property
    def latest_odds(self) -> Optional[OddsEvent]:
        """Latest odds event."""
        return self._latest_odds

    @property
    def latest_chainlink(self) -> Optional[ChainlinkEvent]:
        """Latest Chainlink event."""
        return self._latest_chainlink

    def set_strike_price(self, strike: float) -> None:
        """Set the strike price for the current window."""
        self._state.strike_price = strike
        logger.info("Strike price set: $%.2f", strike)

    async def run(self, queue: asyncio.Queue) -> None:
        """Main loop — Tier 1 processing (instant price updates)."""
        self._running = True
        logger.info("SignalProcessor Tier 1 started.")

        # Start Tier 2 task (Periodic CVD)
        self._cvd_task = asyncio.create_task(self._cvd_background_loop())

        try:
            while self._running:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                if isinstance(event, PriceEvent):
                    # TIER 1: Price events are processed immediately
                    self._handle_price_event(event)
                elif isinstance(event, TradeEvent):
                    # TIER 2 helper: Trades update running totals but NOT state
                    self._handle_trade_event(event)
                elif isinstance(event, OrderBookEvent):
                    self._latest_book = event
                elif isinstance(event, OddsEvent):
                    self._latest_odds = event
                elif isinstance(event, ChainlinkEvent):
                    self._latest_chainlink = event
                elif isinstance(event, DataStaleEvent):
                    logger.warning("DataStaleEvent from %s", event.source)

                queue.task_done()

        except asyncio.CancelledError:
            logger.info("SignalProcessor cancelled.")
        finally:
            self._running = False
            if self._cvd_task:
                self._cvd_task.cancel()

    async def _cvd_background_loop(self) -> None:
        """TIER 2: Periodic CVD calculation loop."""
        interval_sec = self._cfg.CVD_CALC_INTERVAL_MS / 1000.0
        while self._running:
            try:
                await asyncio.sleep(interval_sec)
                self._recalculate_cvd_state()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Error in CVD background loop: %s", exc)

    def stop(self) -> None:
        """Stop the processor."""
        self._running = False

    def _handle_trade_event(self, event: TradeEvent) -> None:
        """TIER 2 Helper: Update CVD running totals. FAST O(1)."""
        # Filter noise if enabled
        if self._cfg.MIN_TRADE_SIZE_USD > 0:
            trade_value = event.size * event.price
            if trade_value < self._cfg.MIN_TRADE_SIZE_USD:
                return

        now = event.timestamp

        # Update CVD running total
        net_delta = event.size if event.side == "buy" else -event.size
        self._cvd_deque.append((now, net_delta))
        self._cvd_running += net_delta

        # Update Volume running total
        self._volume_deque.append((now, event.size))
        self._volume_running += event.size

        # Aggregation for candles still happens here (needed for ATR)
        self._aggregate_candle(event)

    def _recalculate_cvd_state(self) -> None:
        """Perform periodic purge of old entries and update SignalState. FAST O(1)."""
        now = time.time()

        # ── Purge expired CVD entries (older than 60s) ──
        cutoff_cvd = now - 60.0
        while self._cvd_deque and self._cvd_deque[0][0] < cutoff_cvd:
            _, old_delta = self._cvd_deque.popleft()
            self._cvd_running -= old_delta

        # ── Purge expired volume entries ──
        cutoff_vol = now - (self._cfg.CVD_VOLUME_WINDOW_MINUTES * 60.0)
        while self._volume_deque and self._volume_deque[0][0] < cutoff_vol:
            _, old_sz = self._volume_deque.popleft()
            self._volume_running -= old_sz

        # ── Update SignalState ──
        self._state.cvd_60s = self._cvd_running
        
        window_minutes = self._cfg.CVD_VOLUME_WINDOW_MINUTES
        if self._volume_deque:
            elapsed_minutes = (now - self._volume_deque[0][0]) / 60.0
            effective_minutes = max(min(elapsed_minutes, window_minutes), 1.0)
            avg_volume_per_min = self._volume_running / effective_minutes
            self._state.avg_volume_per_min = avg_volume_per_min
            
            # CVD Threshold
            cvd_threshold = avg_volume_per_min * (self._cfg.CVD_THRESHOLD_PCT / 100.0)
            self._state.cvd_threshold = cvd_threshold

            # CVD Alignment
            gap_dir = self._state.gap_direction
            if gap_dir == "UP" and self._cvd_running > cvd_threshold:
                self._state.cvd_aligned = True
            elif gap_dir == "DOWN" and self._cvd_running < -cvd_threshold:
                self._state.cvd_aligned = True
            else:
                self._state.cvd_aligned = False
        else:
            self._state.avg_volume_per_min = 0.0
            self._state.cvd_threshold = 0.0
            self._state.cvd_aligned = False

    def _handle_price_event(self, event: PriceEvent) -> None:
        """TIER 1: Instant updates for price, gap, velocity. FAST O(1)."""
        now = event.timestamp
        price = event.price

        self._state.current_hl_price = price
        self._state.timestamp = now

        # ── Velocity calculation ──
        self._velocity_deque.append((now, price))
        cutoff = now - self._cfg.VELOCITY_WINDOW_SECONDS
        while self._velocity_deque and self._velocity_deque[0][0] < cutoff:
            self._velocity_deque.popleft()

        if len(self._velocity_deque) >= 2:
            self._state.velocity_1_5s = abs(price - self._velocity_deque[0][1])
        else:
            self._state.velocity_1_5s = 0.0

        if self._cfg.VELOCITY_ENABLED:
            self._state.velocity_pass = self._state.velocity_1_5s >= self._cfg.VELOCITY_MIN_DELTA
        else:
            self._state.velocity_pass = True

        # ── Gap calculation ──
        if self._state.strike_price > 0:
            self._state.gap = price - self._state.strike_price
            if self._state.gap > 0:
                self._state.gap_direction = "UP"
            elif self._state.gap < 0:
                self._state.gap_direction = "DOWN"
            else:
                self._state.gap_direction = "NEUTRAL"

        # ── ATR regime determination ──
        atr = self._state.atr
        if atr < self._cfg.ATR_LOW_THRESHOLD:
            self._state.vol_regime = "LOW"
            self._state.gap_threshold = self._cfg.GAP_THRESHOLD_LOW_VOL
        elif atr > self._cfg.ATR_HIGH_THRESHOLD:
            self._state.vol_regime = "HIGH"
            self._state.gap_threshold = self._cfg.GAP_THRESHOLD_HIGH_VOL
        else:
            self._state.vol_regime = "NORM"
            self._state.gap_threshold = self._cfg.GAP_THRESHOLD_DEFAULT

    def _aggregate_candle(self, trade: TradeEvent) -> None:
        """Aggregate tick data into 5-minute candles and update ATR."""
        candle_start = trade.timestamp - (trade.timestamp % 300.0)

        if self._current_candle is None or candle_start > self._current_candle_start:
            if self._current_candle is not None:
                self._candle_deque.append(self._current_candle)
                self._update_atr()
            self._current_candle = Candle(candle_start, trade.price, trade.price, trade.price, trade.price, trade.size)
            self._current_candle_start = candle_start
        else:
            c = self._current_candle
            c.high = max(c.high, trade.price)
            c.low = min(c.low, trade.price)
            c.close = trade.price
            c.volume += trade.size

    def _update_atr(self) -> None:
        """Calculate ATR from completed candles."""
        if len(self._candle_deque) < 2:
            if len(self._candle_deque) == 1:
                self._state.atr = self._candle_deque[0].high - self._candle_deque[0].low
            return

        true_ranges: list[float] = []
        candles = list(self._candle_deque)
        true_ranges.append(candles[0].high - candles[0].low)

        for i in range(1, len(candles)):
            c = candles[i]
            prev_close = candles[i - 1].close
            tr = max(c.high - c.low, abs(c.high - prev_close), abs(c.low - prev_close))
            true_ranges.append(tr)

        self._state.atr = sum(true_ranges) / len(true_ranges)

    def reset_cvd(self) -> None:
        """Reset CVD accumulator."""
        self._cvd_deque.clear()
        self._cvd_running = 0.0
        self._state.cvd_60s = 0.0
        self._state.cvd_aligned = False
        logger.info("CVD accumulator reset.")

    def reset_velocity(self) -> None:
        """Clear velocity buffer."""
        self._velocity_deque.clear()
        self._state.velocity_1_5s = 0.0
        self._state.velocity_pass = False

    def get_state_snapshot(self) -> SignalState:
        """Return a copy of the current signal state."""
        return SignalState(
            timestamp=self._state.timestamp,
            current_hl_price=self._state.current_hl_price,
            strike_price=self._state.strike_price,
            gap=self._state.gap,
            gap_direction=self._state.gap_direction,
            gap_threshold=self._state.gap_threshold,
            vol_regime=self._state.vol_regime,
            atr=self._state.atr,
            cvd_60s=self._state.cvd_60s,
            cvd_threshold=self._state.cvd_threshold,
            cvd_threshold_pct=self._state.cvd_threshold_pct,
            avg_volume_per_min=self._state.avg_volume_per_min,
            cvd_aligned=self._state.cvd_aligned,
            velocity_1_5s=self._state.velocity_1_5s,
            velocity_pass=self._state.velocity_pass,
        )
