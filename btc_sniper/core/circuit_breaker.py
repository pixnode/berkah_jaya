# ═══ FILE: btc_sniper/core/circuit_breaker.py ═══
"""
Circuit Breaker — state machine: NORMAL → LOCKDOWN → COOLDOWN → NORMAL.
4-step LOCKDOWN Resume Protocol per PRD v2.3 Section 06.
Thread-safe via asyncio.Lock on all state mutations.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Literal, Optional

from config import BotConfig

logger = logging.getLogger("btc_sniper.core.circuit_breaker")

BotMode = Literal["NORMAL", "LOCKDOWN", "COOLDOWN"]


@dataclass
class ResumeResult:
    """Result of a resume attempt after LOCKDOWN."""
    success: bool
    reason: Optional[str] = None
    remaining_sec: Optional[int] = None
    failed_checks: Optional[list[str]] = None


class CircuitBreaker:
    """Manages trading circuit breaker with LOCKDOWN/resume protocol."""

    def __init__(self, cfg: BotConfig, event_logger: Optional[object] = None) -> None:
        self._cfg = cfg
        self._event_logger = event_logger
        self._lock = asyncio.Lock()

        self._mode: BotMode = "NORMAL"
        self._consecutive_loss_count: int = 0
        self._daily_loss_usd: float = 0.0
        self._lockdown_triggered_at: float = 0.0
        self._lockdown_reason: str = ""
        self._total_skips: int = 0
        self._total_wins: int = 0
        self._total_losses: int = 0

    @property
    def mode(self) -> BotMode:
        """Current circuit breaker mode."""
        return self._mode

    @property
    def consecutive_loss_count(self) -> int:
        """Number of consecutive losses."""
        return self._consecutive_loss_count

    @property
    def daily_loss_usd(self) -> float:
        """Accumulated daily loss in USD."""
        return self._daily_loss_usd

    @property
    def is_lockdown(self) -> bool:
        """Whether currently in LOCKDOWN mode."""
        return self._mode == "LOCKDOWN"

    @property
    def lockdown_reason(self) -> str:
        """Reason for current/last LOCKDOWN."""
        return self._lockdown_reason

    async def record_loss(self, loss_amount_usd: float = 0.0) -> BotMode:
        """Record a trade loss. Returns current mode (may trigger LOCKDOWN).

        Args:
            loss_amount_usd: Amount lost in this trade (positive value).
        """
        async with self._lock:
            self._consecutive_loss_count += 1
            self._total_losses += 1
            self._daily_loss_usd += abs(loss_amount_usd)

            logger.info(
                "Loss recorded: consecutive=%d/%d, daily=$%.4f",
                self._consecutive_loss_count,
                self._cfg.CIRCUIT_BREAKER_MAX_LOSS,
                self._daily_loss_usd,
            )

            # Check circuit breaker threshold
            if self._consecutive_loss_count >= self._cfg.CIRCUIT_BREAKER_MAX_LOSS:
                await self._trigger_lockdown_internal("CIRCUIT_BREAKER")
                return self._mode

            # Check daily loss limit
            if (
                self._cfg.MAX_DAILY_LOSS_USD > 0
                and self._daily_loss_usd >= self._cfg.MAX_DAILY_LOSS_USD
            ):
                await self._trigger_lockdown_internal("DAILY_LOSS_LIMIT")
                return self._mode

            return self._mode

    async def record_win(self) -> None:
        """Record a trade win. Resets consecutive loss counter."""
        async with self._lock:
            self._consecutive_loss_count = 0
            self._total_wins += 1
            logger.info("Win recorded: consecutive losses reset to 0.")

    async def record_skip(self) -> None:
        """Record a window skip. Does NOT affect consecutive loss counter."""
        async with self._lock:
            self._total_skips += 1

    async def trigger_lockdown(self, reason: str) -> None:
        """Trigger LOCKDOWN from external source (e.g., SafetyMonitor)."""
        async with self._lock:
            await self._trigger_lockdown_internal(reason)

    async def _trigger_lockdown_internal(self, reason: str) -> None:
        """Internal LOCKDOWN trigger (must be called with lock held)."""
        self._mode = "LOCKDOWN"
        self._lockdown_triggered_at = time.time()
        self._lockdown_reason = reason

        logger.critical(
            "═══ LOCKDOWN TRIGGERED ═══ Reason: %s | Consecutive losses: %d | Daily loss: $%.4f",
            reason, self._consecutive_loss_count, self._daily_loss_usd,
        )

        await self._log_event(
            "LOCKDOWN", "",
            f"Reason: {reason}, consecutive_losses={self._consecutive_loss_count}, "
            f"daily_loss=${self._daily_loss_usd:.4f}",
        )

    async def attempt_resume(
        self,
        hl_feed_connected: bool,
        poly_feed_connected: bool,
        chainlink_fresh: bool,
        wallet_balance: float,
        unclaimed_since_sec: float,
        signal_processor: Optional[object] = None,
    ) -> ResumeResult:
        """Attempt to resume from LOCKDOWN — 4-step protocol per PRD v2.3.

        Returns ResumeResult indicating success or failure with details.
        """
        async with self._lock:
            if self._mode != "LOCKDOWN":
                return ResumeResult(success=False, reason="NOT_IN_LOCKDOWN")

            # ══════════════════════════════════════════
            # STEP 1 — Cooldown Check
            # ══════════════════════════════════════════
            elapsed = time.time() - self._lockdown_triggered_at

            if self._lockdown_reason in ("CIRCUIT_BREAKER", "DAILY_LOSS_LIMIT"):
                required = self._cfg.COOLDOWN_CIRCUIT_BREAKER_SEC
            else:
                required = self._cfg.COOLDOWN_DATA_STALE_SEC

            if elapsed < required:
                remaining = int(required - elapsed)
                logger.info(
                    "Resume denied: cooldown not elapsed (%ds / %ds)",
                    int(elapsed), required,
                )
                return ResumeResult(
                    success=False,
                    reason="COOLDOWN_NOT_ELAPSED",
                    remaining_sec=remaining,
                )

            # ══════════════════════════════════════════
            # STEP 2 — Pre-resume Checklist
            # ══════════════════════════════════════════
            min_balance = (
                self._cfg.BASE_SHARES
                * self._cfg.MAX_POSITION_USD
                * self._cfg.MIN_TRADE_RESERVE
            )

            checks = {
                "hl_feed_connected": hl_feed_connected,
                "poly_feed_connected": poly_feed_connected,
                "chainlink_fresh": chainlink_fresh,
                "balance_sufficient": wallet_balance >= min_balance,
                "no_overdue_claims": unclaimed_since_sec < (30 * 60),
            }

            failed = [k for k, v in checks.items() if not v]
            if failed:
                logger.info("Resume denied: failed checks: %s", failed)
                return ResumeResult(
                    success=False,
                    reason="CHECKLIST_FAILED",
                    failed_checks=failed,
                )

            # ══════════════════════════════════════════
            # STEP 3 — State Reset
            # ══════════════════════════════════════════
            self._consecutive_loss_count = 0
            # Session P&L and trade log are NOT reset — append only

            # Reset CVD via signal processor if available
            if signal_processor is not None and hasattr(signal_processor, "reset_cvd"):
                signal_processor.reset_cvd()

            # ══════════════════════════════════════════
            # STEP 4 — Soft Start
            # ══════════════════════════════════════════
            self._mode = "NORMAL"
            self._lockdown_reason = ""

            logger.info(
                "═══ RESUME SUCCESSFUL ═══ Soft start: first window = MONITOR only",
            )

            await self._log_event(
                "RESUME", "",
                "Resume from LOCKDOWN — soft start active",
            )

            return ResumeResult(success=True)

    def reset_daily_loss(self) -> None:
        """Reset daily loss counter (call at day boundary)."""
        self._daily_loss_usd = 0.0
        logger.info("Daily loss counter reset.")

    def get_stats(self) -> dict:
        """Return current circuit breaker statistics."""
        return {
            "mode": self._mode,
            "consecutive_losses": self._consecutive_loss_count,
            "daily_loss_usd": self._daily_loss_usd,
            "total_wins": self._total_wins,
            "total_losses": self._total_losses,
            "total_skips": self._total_skips,
            "lockdown_reason": self._lockdown_reason,
            "lockdown_triggered_at": self._lockdown_triggered_at,
        }

    async def _log_event(self, event_type: str, window_id: str, details: str) -> None:
        """Log event via injected logger."""
        if self._event_logger is not None and hasattr(self._event_logger, "log_event"):
            try:
                from logs.audit_logger import EventRecord
                record = EventRecord(
                    timestamp=time.time(),
                    event_type=event_type,
                    window_id=window_id,
                    trigger="circuit_breaker",
                    mode=self._mode,
                    details=details,
                    gate_failed=None,
                    state_snapshot_json="{}",
                )
                await self._event_logger.log_event(record)
            except Exception:
                pass
