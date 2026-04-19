# ═══ FILE: btc_sniper/core/signal_processor.py ═══
"""
Signal Processor — consumes feed events and maintains real-time signal state.
Tiered processing: Tier 1 (Price/Gap) is instant, Tier 2 (CVD/ATR) is periodic.
"""

from __future__ import annotations

import asyncio
import collections
import logging
import time
from dataclasses import dataclass
from typing import Deque, Literal, Optional, Dict

from config import BotConfig
from feeds import (
    PriceEvent, TradeEvent, OrderBookEvent, OddsEvent, ChainlinkEvent, DataStaleEvent
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
    cvd_direction: Literal["UP", "DOWN", "MIXED"] = "MIXED"
    velocity: float = 0.0


class SignalProcessor:
    """Consumes feed events and maintains real-time signal state with tiered processing."""

    def __init__(self, cfg: BotConfig, event_logger: Optional[object] = None) -> None:
        self._cfg = cfg
        self._event_logger = event_logger

        # ── CVD rolling window ────────────────────────
        self._cvd_deque: Deque[tuple[float, float]] = collections.deque()
        self._cvd_running: float = 0.0  # O(1) running total
        
        # Volume tracking for avg_volume_per_min
        self._volume_deque: Deque[tuple[float, float]] = collections.deque()
        self._volume_running: float = 0.0  # O(1) running total

        # ── Velocity tracking ─────────────────────────
        self._velocity_deque: Deque[tuple[float, float]] = collections.deque()

        # ── ATR candle tracking ───────────────────────
        self._candle_deque: Deque[Candle] = collections.deque(maxlen=cfg.ATR_LOOKBACK_CANDLES)
        self._current_candle: Optional[Candle] = None
        self._current_candle_start: float = 0.0

        # ── Current state ─────────────────────────────
        self._state = SignalState()
        self._state.cvd_threshold_pct = cfg.CVD_THRESHOLD_PCT

        # ── Latest events ─────────────────────────────
        self._latest_book: Optional[OrderBookEvent] = None
        self._latest_odds: Optional[OddsEvent] = None
        self._latest_chainlink: Optional[ChainlinkEvent] = None

        # ── Running flag & Tasks ──────────────────────
        self._running: bool = False
        self._bg_task: Optional[asyncio.Task] = None

    @property
    def state(self) -> SignalState:
        """Current signal state snapshot."""
        return self._state

    @property
    def latest_book(self) -> Optional[OrderBookEvent]:
        return self._latest_book

    @property
    def latest_odds(self) -> Optional[OddsEvent]:
        return self._latest_odds

    async def run(self, queue: asyncio.Queue) -> None:
        """Main event consumption loop (Tier 1)."""
        self._running = True
        logger.info("SignalProcessor Tier 1 started.")

        # Start background task for Tier 2 (CVD/ATR calculations)
        self._bg_task = asyncio.create_task(self._background_calculations())

        try:
            while self._running:
                event = await queue.get()
                await self._process_event(event)
                queue.task_done()
        except asyncio.CancelledError:
            logger.info("SignalProcessor cancelled.")
        finally:
            self._running = False
            if self._bg_task:
                self._bg_task.cancel()
            logger.info("SignalProcessor stopped.")

    async def _process_event(self, event: object) -> None:
        """Tier 1: Instant price and gap updates."""
        now = time.time()

        if isinstance(event, PriceEvent):
            self._state.timestamp = now
            self._state.current_hl_price = event.price
            self._update_gap()
            # Update velocity deque
            self._velocity_deque.append((now, event.price))
            # Clean old velocity data (> 5s)
            while self._velocity_deque and now - self._velocity_deque[0][0] > 5.0:
                self._velocity_deque.popleft()
            
            # Update current candle
            self._update_candle(event.price, 0)

        elif isinstance(event, TradeEvent):
            # Noise filter
            if event.size_usd < self._cfg.MIN_TRADE_SIZE_USD:
                return
                
            # Add to rolling CVD window (processed in background)
            delta = event.size_usd if event.side == "BUY" else -event.size_usd
            self._cvd_deque.append((now, delta))
            self._cvd_running += delta
            
            # Add to volume window
            self._volume_deque.append((now, event.size_usd))
            self._volume_running += event.size_usd
            
            # Update current candle volume
            self._update_candle(event.price, event.size_usd)

        elif isinstance(event, ChainlinkEvent):
            self._latest_chainlink = event
            self._state.strike_price = event.price
            self._update_gap()

        elif isinstance(event, OrderBookEvent):
            self._latest_book = event

        elif isinstance(event, OddsEvent):
            self._latest_odds = event

    def _update_gap(self) -> None:
        """Calculate gap and direction."""
        if self._state.current_hl_price > 0 and self._state.strike_price > 0:
            self._state.gap = self._state.current_hl_price - self._state.strike_price
            if self._state.gap > 0:
                self._state.gap_direction = "UP"
            elif self._state.gap < 0:
                self._state.gap_direction = "DOWN"
            else:
                self._state.gap_direction = "NEUTRAL"

    def _update_candle(self, price: float, volume: float) -> None:
        """Update 5m candle for ATR calculation."""
        now = time.time()
        # Align to 5m window
        window_start = now - (now % 300)
        
        if window_start != self._current_candle_start:
            # New candle starts
            if self._current_candle:
                self._candle_deque.append(self._current_candle)
                self._update_atr()
            
            self._current_candle = Candle(window_start, price, price, price, price, volume)
            self._current_candle_start = window_start
        else:
            # Update existing candle
            c = self._current_candle
            c.high = max(c.high, price)
            c.low = min(c.low, price)
            c.close = price
            c.volume += volume

    def _update_atr(self) -> None:
        """Calculate ATR and set volume regime."""
        if len(self._candle_deque) < 2:
            return
            
        ranges = []
        for i in range(1, len(self._candle_deque)):
            c1 = self._candle_deque[i-1]
            c2 = self._candle_deque[i]
            tr = max(c2.high - c2.low, abs(c2.high - c1.close), abs(c2.low - c1.close))
            ranges.append(tr)
            
        self._state.atr = sum(ranges) / len(ranges)
        
        # Determine regime
        if self._state.atr > self._cfg.ATR_HIGH_THRESHOLD:
            self._state.vol_regime = "HIGH"
            self._state.gap_threshold = self._cfg.GAP_THRESHOLD_HIGH
        elif self._state.atr < self._cfg.ATR_LOW_THRESHOLD:
            self._state.vol_regime = "LOW"
            self._state.gap_threshold = self._cfg.GAP_THRESHOLD_NORMAL
        else:
            self._state.vol_regime = "NORM"
            self._state.gap_threshold = self._cfg.GAP_THRESHOLD_NORMAL

    async def _background_calculations(self) -> None:
        """Tier 2: Periodic CVD and Velocity calculations (500ms)."""
        interval = self._cfg.CVD_CALC_INTERVAL_MS / 1000.0
        
        while self._running:
            try:
                now = time.time()
                
                # 1. Purge old CVD data (> 60s)
                while self._cvd_deque and now - self._cvd_deque[0][0] > 60.0:
                    _, delta = self._cvd_deque.popleft()
                    self._cvd_running -= delta
                
                # 2. Purge old volume data (> 60s)
                while self._volume_deque and now - self._volume_deque[0][0] > 60.0:
                    _, vol = self._volume_deque.popleft()
                    self._volume_running -= vol
                
                # 3. Update CVD state
                self._state.cvd_60s = self._cvd_running
                self._state.avg_volume_per_min = self._volume_running
                self._state.cvd_threshold = self._state.avg_volume_per_min * (self._state.cvd_threshold_pct / 100.0)
                
                if abs(self._state.cvd_60s) >= self._state.cvd_threshold:
                    self._state.cvd_aligned = True
                    self._state.cvd_direction = "UP" if self._state.cvd_60s > 0 else "DOWN"
                else:
                    self._state.cvd_aligned = False
                    self._state.cvd_direction = "MIXED"
                
                # 4. Calculate Velocity ($/5s)
                if len(self._velocity_deque) >= 2:
                    self._state.velocity = self._velocity_deque[-1][1] - self._velocity_deque[0][1]
                else:
                    self._state.velocity = 0.0

                # 5. Log Snapshot (Optional)
                if self._event_logger and hasattr(self._event_logger, "log_snapshot"):
                    # We will implement this if needed for audit
                    pass

            except Exception as exc:
                logger.error("Error in background calculations: %s", exc)
                
            await asyncio.sleep(interval)
