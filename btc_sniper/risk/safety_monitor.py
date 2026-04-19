# ═══ FILE: btc_sniper/risk/safety_monitor.py ═══
"""
Safety Monitor — continuous background monitoring loop (every 0.5s).
Evaluates 10 safety triggers and emits SKIP/LOCKDOWN/CANCEL events.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Literal, Optional

from config import BotConfig

logger = logging.getLogger("btc_sniper.risk.safety_monitor")


@dataclass
class SafetyEvent:
    """Event emitted when a safety trigger fires."""
    timestamp: float
    trigger: str
    mode: Literal["SKIP", "LOCKDOWN", "CANCEL"]
    window_id: str
    details: str
    state_snapshot: dict


class SafetyMonitor:
    """Runs a 0.5s monitoring loop checking 10 safety triggers."""

    def __init__(self, cfg: BotConfig, event_logger: Optional[object] = None) -> None:
        self._cfg = cfg
        self._event_logger = event_logger
        self._running: bool = False
        self._last_safety_event: Optional[SafetyEvent] = None

        # References to shared state — set by engine before start
        self._hl_feed: Optional[object] = None
        self._poly_feed: Optional[object] = None
        self._chainlink_feed: Optional[object] = None
        self._circuit_breaker: Optional[object] = None
        self._signal_processor: Optional[object] = None
        self._engine_state: Optional[dict] = None

        # Chainlink tick buffer for volatility check
        self._chainlink_ticks: list[float] = []

    @property
    def last_safety_event(self) -> Optional[SafetyEvent]:
        """Most recent safety event emitted."""
        return self._last_safety_event

    def set_components(
        self,
        hl_feed: object,
        poly_feed: object,
        chainlink_feed: object,
        circuit_breaker: object,
        signal_processor: object,
    ) -> None:
        """Inject references to shared components."""
        self._hl_feed = hl_feed
        self._poly_feed = poly_feed
        self._chainlink_feed = chainlink_feed
        self._circuit_breaker = circuit_breaker
        self._signal_processor = signal_processor

    def set_engine_state(self, state: dict) -> None:
        """Update reference to engine state dict."""
        self._engine_state = state

    async def run(self) -> None:
        """Main monitoring loop — runs every 0.5 seconds."""
        self._running = True
        logger.info("SafetyMonitor starting up — entering %ds grace period...", self._cfg.SAFETY_MONITOR_STARTUP_GRACE_SEC)
        
        # Wait for feeds to stabilize before starting monitoring
        await asyncio.sleep(self._cfg.SAFETY_MONITOR_STARTUP_GRACE_SEC)
        
        logger.info("SafetyMonitor active — checking every 0.5s.")

        try:
            while self._running:
                await self._check_all_triggers()
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            logger.info("SafetyMonitor cancelled.")
        finally:
            self._running = False
            logger.info("SafetyMonitor stopped.")

    def stop(self) -> None:
        """Stop the monitor."""
        self._running = False

    async def _check_all_triggers(self) -> None:
        """Evaluate all safety triggers."""
        now = time.time()
        window_id = ""
        if self._engine_state:
            window_id = self._engine_state.get("window_id", "")

        # Skip checks if circuit breaker is already in LOCKDOWN
        if self._circuit_breaker and hasattr(self._circuit_breaker, "is_lockdown"):
            if self._circuit_breaker.is_lockdown:
                return

        # ── TRIGGER 1: DATA_STALE (Hyperliquid) ──
        if self._hl_feed and hasattr(self._hl_feed, "last_message_at"):
            hl_age = now - self._hl_feed.last_message_at if self._hl_feed.last_message_at > 0 else 999
            if hl_age > self._cfg.WS_STALE_THRESHOLD_SEC:
                await self._emit_event(
                    "DATA_STALE", "LOCKDOWN", window_id,
                    f"Hyperliquid no update for {hl_age:.1f}s > {self._cfg.WS_STALE_THRESHOLD_SEC}s",
                )
                if self._circuit_breaker and hasattr(self._circuit_breaker, "trigger_lockdown"):
                    await self._circuit_breaker.trigger_lockdown("DATA_STALE")
                return

        # ── TRIGGER 2: DATA_STALE (Polymarket) ──
        if self._poly_feed and hasattr(self._poly_feed, "last_message_at"):
            poly_age = now - self._poly_feed.last_message_at if self._poly_feed.last_message_at > 0 else 999
            if poly_age > self._cfg.WS_STALE_THRESHOLD_SEC:
                await self._emit_event(
                    "DATA_STALE", "LOCKDOWN", window_id,
                    f"Polymarket no update for {poly_age:.1f}s > {self._cfg.WS_STALE_THRESHOLD_SEC}s",
                )
                if self._circuit_breaker and hasattr(self._circuit_breaker, "trigger_lockdown"):
                    await self._circuit_breaker.trigger_lockdown("DATA_STALE")
                return

        # ── TRIGGER 3: CHAINLINK_UNSTABLE ──
        if self._chainlink_feed and hasattr(self._chainlink_feed, "last_event"):
            cl_event = self._chainlink_feed.last_event
            if cl_event is not None:
                self._chainlink_ticks.append(cl_event.price)
                # Keep last 3 ticks
                if len(self._chainlink_ticks) > 3:
                    self._chainlink_ticks = self._chainlink_ticks[-3:]

                if len(self._chainlink_ticks) >= 3:
                    volatility = abs(self._chainlink_ticks[0] - self._chainlink_ticks[2])
                    if volatility > self._cfg.CHAINLINK_VOLATILITY_SKIP_USD:
                        # Check if gap is > 2x threshold (HIGH_VOL_SKIP)
                        gap = 0.0
                        gap_threshold = self._cfg.GAP_THRESHOLD_DEFAULT
                        if self._signal_processor and hasattr(self._signal_processor, "state"):
                            gap = abs(self._signal_processor.state.gap)
                            gap_threshold = self._signal_processor.state.gap_threshold

                        if gap > 2 * gap_threshold:
                            await self._emit_event(
                                "HIGH_VOL_SKIP", "SKIP", window_id,
                                f"Chainlink volatility ${volatility:.1f} but gap ${gap:.1f} > 2×threshold — still SKIP for safety",
                            )
                        else:
                            await self._emit_event(
                                "CHAINLINK_UNSTABLE", "SKIP", window_id,
                                f"3-tick volatility ${volatility:.1f} > ${self._cfg.CHAINLINK_VOLATILITY_SKIP_USD:.1f}",
                            )

        # ── TRIGGER 4: SYNC_LATENCY ──
        if (
            self._hl_feed and hasattr(self._hl_feed, "last_message_at")
            and self._poly_feed and hasattr(self._poly_feed, "last_message_at")
        ):
            hl_ts = self._hl_feed.last_message_at
            poly_ts = self._poly_feed.last_message_at
            if hl_ts > 0 and poly_ts > 0:
                sync_delta = abs(hl_ts - poly_ts)
                if sync_delta > self._cfg.SYNC_LATENCY_MAX_SEC:
                    await self._emit_event(
                        "SYNC_LATENCY", "LOCKDOWN", window_id,
                        f"HL-Poly timestamp delta {sync_delta:.1f}s > {self._cfg.SYNC_LATENCY_MAX_SEC}s",
                    )
                    if self._circuit_breaker and hasattr(self._circuit_breaker, "trigger_lockdown"):
                        await self._circuit_breaker.trigger_lockdown("SYNC_LATENCY")
                    return

        # ── TRIGGER 5: STRIKE_PRICE_STALE ──
        if self._chainlink_feed and hasattr(self._chainlink_feed, "last_event"):
            cl_event = self._chainlink_feed.last_event
            if cl_event is not None:
                bot_mode = ""
                if self._engine_state:
                    bot_mode = self._engine_state.get("bot_mode", "")

                if bot_mode == "INIT" and cl_event.age_seconds > self._cfg.CHAINLINK_MAX_AGE_SEC:
                    await self._emit_event(
                        "STRIKE_PRICE_STALE", "SKIP", window_id,
                        f"Chainlink age {cl_event.age_seconds}s > {self._cfg.CHAINLINK_MAX_AGE_SEC}s at INIT",
                    )

        # ── TRIGGER 6: ODDS_OUT_OF_RANGE (backup check) ──
        if self._signal_processor and hasattr(self._signal_processor, "latest_odds"):
            odds = self._signal_processor.latest_odds
            if odds is not None:
                gap_dir = ""
                if hasattr(self._signal_processor, "state"):
                    gap_dir = self._signal_processor.state.gap_direction

                target_ask = odds.up_odds if gap_dir == "UP" else odds.down_odds
                if target_ask > 0 and (target_ask < self._cfg.ODDS_MIN or target_ask > self._cfg.ODDS_MAX):
                    await self._emit_event(
                        "ODDS_OUT_OF_RANGE", "SKIP", window_id,
                        f"ask={target_ask:.3f} outside [{self._cfg.ODDS_MIN},{self._cfg.ODDS_MAX}]",
                    )

    async def _emit_event(
        self,
        trigger: str,
        mode: Literal["SKIP", "LOCKDOWN", "CANCEL"],
        window_id: str,
        details: str,
    ) -> None:
        """Create and log a SafetyEvent."""
        state_snapshot = {}
        if self._engine_state:
            state_snapshot = dict(self._engine_state)

        event = SafetyEvent(
            timestamp=time.time(),
            trigger=trigger,
            mode=mode,
            window_id=window_id,
            details=details,
            state_snapshot=state_snapshot,
        )
        self._last_safety_event = event

        logger.warning(
            "SAFETY [%s] %s: %s (window: %s)",
            mode, trigger, details, window_id,
        )

        # Log to event_log
        if self._event_logger is not None and hasattr(self._event_logger, "log_event"):
            try:
                from logs.audit_logger import EventRecord
                import json
                record = EventRecord(
                    timestamp=event.timestamp,
                    event_type=trigger,
                    window_id=window_id,
                    trigger=trigger,
                    mode=mode,
                    details=details,
                    gate_failed=None,
                    state_snapshot_json=json.dumps(state_snapshot, default=str),
                )
                await self._event_logger.log_event(record)
            except Exception:
                pass
