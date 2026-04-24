# ═══ FILE: btc_sniper/risk/gates.py ═══
"""
7-Gate AND Logic Entry Evaluation — PRD v2.3 Section 04.
Gate 1: Gap Threshold, Gate 2: CVD, Gate 3: Liquidity/Mispricing,
Gate 4: Odds Boundary, Gate 5: Golden Window, Gate 6: Velocity, Gate 7: No Duplicate.
Short-circuit: stops at first FAIL.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Literal, Optional

from config import BotConfig
from core.signal_processor import SignalState
from feeds import OddsEvent, OrderBookEvent

TOTAL_GATES = 7


@dataclass
class GateResult:
    """Result of 7-gate evaluation. Always contains exactly 7 gate statuses."""
    all_pass: bool
    failed_gate: Optional[int]
    fail_reason: Optional[str]
    gate_statuses: dict[int, bool]
    evaluated_at: float
    signal_snapshot: SignalState
    target_ask: float
    expected_odds: float
    in_sweet_spot: bool
    side: Optional[Literal["UP", "DOWN"]]

    def to_csv_row(self) -> dict:
        """Serialize to dict for skip_log.csv and event_log.csv."""
        snap = self.signal_snapshot
        return {
            "timestamp": self.evaluated_at,
            "skip_reason": self.fail_reason or "",
            "skip_stage": "EVALUATE",
            "gap_value": snap.gap,
            "gap_threshold": snap.gap_threshold,
            "gap_gate_pass": self.gate_statuses.get(1, False),
            "cvd_value": snap.cvd_60s,
            "cvd_gate_pass": self.gate_statuses.get(2, False),
            "liquidity_gate_pass": self.gate_statuses.get(3, False),
            "current_ask": self.target_ask,
            "min_odds": 0.0,  # Filled by caller from cfg
            "max_odds": 0.0,  # Filled by caller from cfg
            "odds_gate_pass": self.gate_statuses.get(4, False),
            "golden_window_gate_pass": self.gate_statuses.get(5, False),
            "velocity_gate_pass": self.gate_statuses.get(6, False),
            "slippage_gate_pass": self.gate_statuses.get(7, False),
            "side": self.side or "",
            "in_sweet_spot": self.in_sweet_spot,
            "expected_odds": self.expected_odds,
            "atr_regime": snap.vol_regime,
            "velocity": snap.velocity_1_5s,
        }


class GateEvaluator:
    """Evaluates 7 AND-logic entry gates. Short-circuits at first failure."""

    def __init__(self, cfg: BotConfig) -> None:
        self._cfg = cfg

    def evaluate(
        self,
        signal: SignalState,
        book: Optional[OrderBookEvent],
        odds: Optional[OddsEvent],
        time_remaining: int,
        order_sent: bool,
    ) -> GateResult:
        """Run all 7 gates. Returns GateResult with detailed status.

        Gate order per PRD v2.3 Section 04:
        1=Gap, 2=CVD, 3=Liquidity, 4=Odds, 5=Timing, 6=Velocity, 7=NoDuplicate
        """
        now = time.time()
        gate_statuses: dict[int, bool] = {i: False for i in range(1, TOTAL_GATES + 1)}
        failed_gate: Optional[int] = None
        fail_reason: Optional[str] = None

        # Determine side from gap direction
        side: Optional[Literal["UP", "DOWN"]] = None
        if signal.gap_direction == "UP":
            side = "UP"
        elif signal.gap_direction == "DOWN":
            side = "DOWN"

        # Determine target ask based on side
        target_ask = 0.0
        if odds is not None and side is not None:
            target_ask = odds.up_odds if side == "UP" else odds.down_odds

        # Expected odds for mispricing check (Gate 3)
        k = self._cfg.MISPRICING_MULTIPLIER / max(signal.atr, 1.0)
        expected_odds_raw = 1.0 / (1.0 + math.exp(-k * signal.gap))
        expected_odds = min(0.99, max(0.01, expected_odds_raw))

        # Sweet spot check
        in_sweet_spot = (
            self._cfg.ODDS_SWEET_SPOT_LOW <= target_ask <= self._cfg.ODDS_SWEET_SPOT_HIGH
        )

        # Helper for short-circuit
        def _fail(gate: int, reason: str) -> GateResult:
            nonlocal failed_gate, fail_reason
            failed_gate = gate
            fail_reason = reason
            return GateResult(
                all_pass=False,
                failed_gate=gate,
                fail_reason=reason,
                gate_statuses=gate_statuses,
                evaluated_at=now,
                signal_snapshot=signal,
                target_ask=target_ask,
                expected_odds=expected_odds,
                in_sweet_spot=in_sweet_spot,
                side=side,
            )

        # ══════════════════════════════════════════════
        # GATE 1 — Gap Threshold (Dynamic ATR-based)
        # ══════════════════════════════════════════════
        if abs(signal.gap) > signal.gap_threshold:
            gate_statuses[1] = True
        else:
            return _fail(
                1,
                f"GAP_INSUFFICIENT: {signal.gap:.1f} < threshold {signal.gap_threshold:.1f}",
            )

        # ══════════════════════════════════════════════
        # GATE 2 — CVD Alignment
        # ══════════════════════════════════════════════
        if signal.cvd_aligned:
            gate_statuses[2] = True
        else:
            return _fail(
                2,
                f"CVD_MISALIGNED: cvd={signal.cvd_60s:.0f}, threshold={signal.cvd_threshold:.0f}",
            )

        # ══════════════════════════════════════════════
        # GATE 3 — Dual Side Liquidity + Mispricing
        # ══════════════════════════════════════════════
        if not self._cfg.GATE3_ENABLED:
            gate_statuses[3] = True
        else:
            if book is None:
                return _fail(3, "NO_LIQUIDITY: order book data unavailable")

            # Check dual side availability
            if book.up_ask <= 0:
                return _fail(3, "NO_LIQUIDITY: UP ask not available")
            if book.down_bid <= 0:
                return _fail(3, "NO_LIQUIDITY: DOWN bid not available")

            # Spread check
            if book.spread_pct > self._cfg.SPREAD_MAX_PCT:
                return _fail(
                    3,
                    f"SPREAD_TOO_WIDE: {book.spread_pct:.1f}% > max {self._cfg.SPREAD_MAX_PCT:.1f}%",
                )

            # Mispricing check: current_ask must be cheaper than expected
            current_ask = target_ask
            mispricing_edge = expected_odds - self._cfg.MISPRICING_MIN_EDGE
            if current_ask >= mispricing_edge:
                return _fail(
                    3,
                    f"NO_MISPRICING: ask={current_ask:.3f} >= expected={expected_odds:.3f}-{self._cfg.MISPRICING_MIN_EDGE}",
                )

            gate_statuses[3] = True

        # ══════════════════════════════════════════════
        # GATE 4 — Odds Boundary (MIN/MAX) — NEW in v2.3
        # ══════════════════════════════════════════════
        if odds is None:
            return _fail(4, "ODDS_OUT_OF_RANGE: odds data unavailable")

        if self._cfg.ODDS_MIN <= target_ask <= self._cfg.ODDS_MAX:
            gate_statuses[4] = True
        else:
            return _fail(
                4,
                f"ODDS_OUT_OF_RANGE: {target_ask:.3f} not in [{self._cfg.ODDS_MIN},{self._cfg.ODDS_MAX}]",
            )

        # ══════════════════════════════════════════════
        # GATE 5 — Golden Window Timing
        # ══════════════════════════════════════════════
        if self._cfg.GOLDEN_WINDOW_END <= time_remaining <= self._cfg.GOLDEN_WINDOW_START:
            gate_statuses[5] = True
        else:
            return _fail(
                5,
                f"OUTSIDE_GOLDEN_WINDOW: T-{time_remaining}s",
            )

        # ══════════════════════════════════════════════
        # GATE 6 — Velocity Filter
        # ══════════════════════════════════════════════
        if not self._cfg.VELOCITY_ENABLED:
            gate_statuses[6] = True  # Disabled = always pass
        elif signal.velocity_pass:
            gate_statuses[6] = True
        else:
            return _fail(
                6,
                f"VELOCITY_LOW: {signal.velocity_1_5s:.1f} < {self._cfg.VELOCITY_MIN_DELTA}",
            )

        # ══════════════════════════════════════════════
        # GATE 7 — No Duplicate Order
        # ══════════════════════════════════════════════
        if not order_sent:
            gate_statuses[7] = True
        else:
            return _fail(7, "ORDER_ALREADY_SENT_THIS_WINDOW")

        # ── All gates passed ──────────────────────────
        return GateResult(
            all_pass=True,
            failed_gate=None,
            fail_reason=None,
            gate_statuses=gate_statuses,
            evaluated_at=now,
            signal_snapshot=signal,
            target_ask=target_ask,
            expected_odds=expected_odds,
            in_sweet_spot=in_sweet_spot,
            side=side,
        )
