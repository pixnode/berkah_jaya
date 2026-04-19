# ═══ FILE: btc_sniper/core/signal_processor.py ═══
"""
Signal Processor — CVD, ATR, Gap, Velocity calculations.
All rolling windows use collections.deque for O(1) append/pop.
Pure Python — no numpy/pandas.
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
    """Consumes feed events from asyncio.Queue and maintains real-time signal state."""

    def __init__(self, cfg: BotConfig) -> None:
        self._cfg = cfg

        # ── CVD rolling window ────────────────────────
        # Each entry: (timestamp, net_delta) where net_delta = +size for buy, -size for sell
        self._cvd_deque: Deque[tuple[float, float]] = collections.deque()
        # Volume tracking for avg_volume_per_min
        self._volume_deque: Deque[tuple[float, float]] = collections.deque()

        # ── Running totals for O(1) performance ──────
        self._running_cvd: float = 0.0
        self._running_volume: float = 0.0

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

        # ── Running flag ──────────────────────────────
        self._running: bool = False

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
        """Main loop — consume events from queue and dispatch to handlers."""
        self._running = True
        logger.info("SignalProcessor started — consuming from queue.")

        try:
            while self._running:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                if isinstance(event, TradeEvent):
                    self._handle_trade_event(event)
                elif isinstance(event, PriceEvent):
                    self._handle_price_event(event)
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

    def stop(self) -> None:
        """Stop the processor."""
        self._running = False

    def _handle_trade_event(self, event: TradeEvent) -> None:
        """Update CVD rolling window and volume tracking.

        CVD = Σ(buy_volume) - Σ(sell_volume) over rolling 60 seconds.
        Volume tracking uses CVD_VOLUME_WINDOW_MINUTES for avg calculation.

        >>> sp = SignalProcessor.__new__(SignalProcessor)
        >>> import collections
        >>> sp._cvd_deque = collections.deque()
        >>> sp._volume_deque = collections.deque()
        >>> sp._velocity_deque = collections.deque()
        >>> sp._cfg = type('C', (), {'CVD_THRESHOLD_PCT': 25.0, 'CVD_VOLUME_WINDOW_MINUTES': 30})()
        >>> sp._state = SignalState()
        >>> sp._state.cvd_threshold_pct = 25.0
        >>> sp._current_candle = None
        >>> sp._current_candle_start = 0.0
        >>> sp._candle_deque = collections.deque(maxlen=12)
        """
        now = event.timestamp

        # Net delta: positive for buy, negative for sell
        net_delta = event.size if event.side == "buy" else -event.size
        self._cvd_deque.append((now, net_delta))
        self._running_cvd += net_delta

        # Track absolute volume for avg calculation
        self._volume_deque.append((now, event.size))
        self._running_volume += event.size

        # ── Purge expired CVD entries (older than 60s) ──
        cutoff_cvd = now - 60.0
        while self._cvd_deque and self._cvd_deque[0][0] < cutoff_cvd:
            old_ts, old_delta = self._cvd_deque.popleft()
            self._running_cvd -= old_delta

        # ── Purge expired volume entries ──
        cutoff_vol = now - (self._cfg.CVD_VOLUME_WINDOW_MINUTES * 60.0)
        while self._volume_deque and self._volume_deque[0][0] < cutoff_vol:
            old_ts, old_sz = self._volume_deque.popleft()
            self._running_volume -= old_sz

        # ── Calculate CVD (60s rolling) ──
        self._state.cvd_60s = self._running_cvd

        # ── Calculate avg volume per minute ──
        window_minutes = self._cfg.CVD_VOLUME_WINDOW_MINUTES
        if self._volume_deque:
            elapsed_minutes = (now - self._volume_deque[0][0]) / 60.0
            effective_minutes = max(min(elapsed_minutes, window_minutes), 1.0)
            avg_volume_per_min = self._running_volume / effective_minutes
        else:
            avg_volume_per_min = 0.0

        self._state.avg_volume_per_min = avg_volume_per_min

        # ── Calculate CVD threshold ──
        cvd_threshold = avg_volume_per_min * (self._cfg.CVD_THRESHOLD_PCT / 100.0)
        self._state.cvd_threshold = cvd_threshold

        # ── Check CVD alignment ──
        gap_dir = self._state.gap_direction
        if gap_dir == "UP" and cvd_current > cvd_threshold:
            self._state.cvd_aligned = True
        elif gap_dir == "DOWN" and cvd_current < -cvd_threshold:
            self._state.cvd_aligned = True
        else:
            self._state.cvd_aligned = False

        # ── Update candle aggregation ──
        self._aggregate_candle(event)

    def _handle_price_event(self, event: PriceEvent) -> None:
        """Update price, gap, velocity, and ATR regime.

        Velocity = price change over cfg.VELOCITY_WINDOW_SECONDS.
        Gap = current_hl_price - strike_price.

        >>> sp = SignalProcessor.__new__(SignalProcessor)
        >>> import collections
        >>> sp._velocity_deque = collections.deque()
        >>> sp._candle_deque = collections.deque(maxlen=12)
        >>> sp._cfg = type('C', (), {
        ...     'VELOCITY_WINDOW_SECONDS': 1.5, 'VELOCITY_MIN_DELTA': 15.0,
        ...     'VELOCITY_ENABLED': True, 'ATR_LOW_THRESHOLD': 50.0,
        ...     'ATR_HIGH_THRESHOLD': 150.0, 'GAP_THRESHOLD_DEFAULT': 45.0,
        ...     'GAP_THRESHOLD_LOW_VOL': 60.0, 'GAP_THRESHOLD_HIGH_VOL': 35.0,
        ... })()
        >>> sp._state = SignalState(strike_price=84000.0)
        """
        now = event.timestamp
        price = event.price

        self._state.current_hl_price = price
        self._state.timestamp = now

        # ── Velocity calculation ──
        self._velocity_deque.append((now, price))

        # Purge entries older than velocity window
        cutoff = now - self._cfg.VELOCITY_WINDOW_SECONDS
        while self._velocity_deque and self._velocity_deque[0][0] < cutoff:
            self._velocity_deque.popleft()

        # Calculate velocity from oldest remaining entry
        if len(self._velocity_deque) >= 2:
            oldest_price = self._velocity_deque[0][1]
            velocity = abs(price - oldest_price)
        else:
            velocity = 0.0

        self._state.velocity_1_5s = velocity
        if self._cfg.VELOCITY_ENABLED:
            self._state.velocity_pass = velocity >= self._cfg.VELOCITY_MIN_DELTA
        else:
            self._state.velocity_pass = True  # Disabled = always pass

        # ── Gap calculation ──
        if self._state.strike_price > 0:
            gap = price - self._state.strike_price
            self._state.gap = gap
            if gap > 0:
                self._state.gap_direction = "UP"
            elif gap < 0:
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
        """Aggregate tick data into 5-minute candles and update ATR.

        Detects new candle boundary based on 300-second windows.
        """
        # Determine which 5-min window this trade belongs to
        candle_start = trade.timestamp - (trade.timestamp % 300.0)

        if self._current_candle is None or candle_start > self._current_candle_start:
            # Finalize previous candle
            if self._current_candle is not None:
                self._candle_deque.append(self._current_candle)
                self._update_atr()

            # Start new candle
            self._current_candle = Candle(
                timestamp=candle_start,
                open=trade.price,
                high=trade.price,
                low=trade.price,
                close=trade.price,
                volume=trade.size,
            )
            self._current_candle_start = candle_start
        else:
            # Update current candle
            c = self._current_candle
            c.high = max(c.high, trade.price)
            c.low = min(c.low, trade.price)
            c.close = trade.price
            c.volume += trade.size

    def _update_atr(self) -> None:
        """Calculate ATR from completed candles using True Range.

        True Range = max(high-low, abs(high-prev_close), abs(low-prev_close))
        ATR = mean of all True Ranges in deque.

        >>> sp = SignalProcessor.__new__(SignalProcessor)
        >>> import collections
        >>> sp._candle_deque = collections.deque(maxlen=12)
        >>> sp._state = SignalState()
        >>> c1 = Candle(0, 100, 110, 95, 105, 10)
        >>> c2 = Candle(300, 105, 120, 100, 115, 12)
        >>> sp._candle_deque.append(c1)
        >>> sp._candle_deque.append(c2)
        >>> sp._update_atr()
        >>> sp._state.atr > 0
        True
        """
        if len(self._candle_deque) < 2:
            if len(self._candle_deque) == 1:
                c = self._candle_deque[0]
                self._state.atr = c.high - c.low
            return

        true_ranges: list[float] = []

        candles = list(self._candle_deque)
        # First candle: TR = high - low
        true_ranges.append(candles[0].high - candles[0].low)

        for i in range(1, len(candles)):
            c = candles[i]
            prev_close = candles[i - 1].close
            tr = max(
                c.high - c.low,
                abs(c.high - prev_close),
                abs(c.low - prev_close),
            )
            true_ranges.append(tr)

        self._state.atr = sum(true_ranges) / len(true_ranges)

    def reset_cvd(self) -> None:
        """Reset CVD accumulator — called during LOCKDOWN Resume Protocol.

        >>> sp = SignalProcessor.__new__(SignalProcessor)
        >>> import collections
        >>> sp._cvd_deque = collections.deque([(1.0, 100.0), (2.0, -50.0)])
        >>> sp._state = SignalState(cvd_60s=50.0, cvd_aligned=True)
        >>> sp.reset_cvd()
        >>> sp._state.cvd_60s
        0.0
        >>> sp._state.cvd_aligned
        False
        >>> len(sp._cvd_deque)
        0
        """
        self._cvd_deque.clear()
        self._running_cvd = 0.0
        self._state.cvd_60s = 0.0
        self._state.cvd_aligned = False
        logger.info("CVD accumulator reset (LOCKDOWN resume).")

    def reset_velocity(self) -> None:
        """Clear velocity buffer — called at window init."""
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
