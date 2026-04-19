# ═══ FILE: btc_sniper/logs/audit_logger.py ═══
"""
Audit Logger — 4 CSV + 1 Event Log + 1 JSON State.
Append-only CSV, atomic JSON writes, per-file asyncio.Lock.
Field counts: trade_log=32, skip_log=21, market_snapshot=23, session_summary=30, event_log=8.
"""

from __future__ import annotations

import asyncio
import csv
import json
import logging
import os
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Optional

from config import BotConfig

logger = logging.getLogger("btc_sniper.logs.audit_logger")


# ═══════════════════════════════════════════════════════
# RECORD DATACLASSES
# ═══════════════════════════════════════════════════════

@dataclass
class TradeRecord:
    """32 fields per PRD v2.3 Section 08.1."""
    session_id: str
    window_id: str
    timestamp_trigger: str
    timestamp_order_sent: str
    timestamp_confirmed: str
    side: str
    strike_price: float
    hl_price_at_trigger: float
    gap_value: float
    gap_threshold_used: float
    atr_regime: str
    cvd_60s: float
    cvd_threshold_used: float
    cvd_threshold_pct: float
    velocity: float
    entry_odds: float
    odds_in_sweet_spot: bool
    spread_pct: float
    expected_odds: float
    mispricing_delta: float
    slippage_delta: float
    slippage_threshold_used: float
    blockchain_latency_ms: int
    shares_bought: float
    cost_usdc: float
    result: str
    resolution_price: Optional[float]
    payout_usdc: Optional[float]
    pnl_usdc: Optional[float]
    claim_method: Optional[str]
    claim_timestamp: Optional[str]
    bot_version: str


@dataclass
class SkipRecord:
    """21 fields per PRD v2.3 Section 08.2."""
    session_id: str
    window_id: str
    timestamp: str
    skip_reason: str
    skip_stage: str
    gap_value: Optional[float]
    gap_threshold: Optional[float]
    gap_gate_pass: Optional[bool]
    cvd_value: Optional[float]
    cvd_gate_pass: Optional[bool]
    liquidity_gate_pass: Optional[bool]
    current_ask: Optional[float]
    min_odds: float
    max_odds: float
    odds_gate_pass: Optional[bool]
    golden_window_gate_pass: Optional[bool]
    velocity_gate_pass: Optional[bool]
    slippage_gate_pass: Optional[bool]
    t_remaining_sec: int
    would_have_won: Optional[bool]
    chainlink_age_sec: Optional[int]


@dataclass
class SnapshotRecord:
    """23 fields per PRD v2.3 Section 08.3."""
    session_id: str
    window_id: str
    timestamp: str
    t_remaining_sec: int
    strike_price: float
    hl_price: float
    gap: float
    gap_direction: str
    atr_60m: float
    atr_regime: str
    cvd_60s: float
    cvd_aligned: bool
    avg_volume_per_min: float
    poly_up_odds: float
    poly_down_odds: float
    poly_up_ask_depth: float
    poly_down_bid_depth: float
    spread_pct: float
    dual_side_ok: bool
    chainlink_age_sec: int
    bot_mode: str
    all_gates_pass: bool
    window_result: Optional[str]


@dataclass
class SessionStats:
    """30 fields per PRD v2.3 Section 08.4."""
    session_id: str
    start_time: str
    end_time: str
    duration_min: int
    bot_version: str
    bot_mode: str
    total_windows: int
    windows_traded: int
    windows_skipped: int
    windows_locked: int
    wins: int
    losses: int
    win_rate: float
    total_cost_usdc: float
    total_payout_usdc: float
    net_pnl_usdc: float
    avg_entry_odds: float
    avg_gap_at_entry: float
    avg_blockchain_latency_ms: int
    skip_gap_insufficient: int
    skip_cvd_not_aligned: int
    skip_odds_too_low: int
    skip_odds_too_high: int
    skip_no_liquidity: int
    skip_slippage: int
    skip_other: int
    lockdown_triggers: str
    unclaimed_balance_usdc: float
    auto_claimed_usdc: float
    manual_claim_required: float


@dataclass
class EventRecord:
    """8 fields for event_log.csv."""
    timestamp: float
    event_type: str
    window_id: str
    trigger: str
    mode: str
    details: str
    gate_failed: Optional[int]
    state_snapshot_json: str


# ═══════════════════════════════════════════════════════
# CSV FIELD DEFINITIONS
# ═══════════════════════════════════════════════════════

TRADE_LOG_FIELDS = [
    "session_id", "window_id", "timestamp_trigger", "timestamp_order_sent",
    "timestamp_confirmed", "side", "strike_price", "hl_price_at_trigger",
    "gap_value", "gap_threshold_used", "atr_regime", "cvd_60s",
    "cvd_threshold_used", "cvd_threshold_pct", "velocity", "entry_odds",
    "odds_in_sweet_spot", "spread_pct", "expected_odds", "mispricing_delta",
    "slippage_delta", "slippage_threshold_used", "blockchain_latency_ms",
    "shares_bought", "cost_usdc", "result", "resolution_price",
    "payout_usdc", "pnl_usdc", "claim_method", "claim_timestamp", "bot_version",
]  # 32 fields

SKIP_LOG_FIELDS = [
    "session_id", "window_id", "timestamp", "skip_reason", "skip_stage",
    "gap_value", "gap_threshold", "gap_gate_pass", "cvd_value", "cvd_gate_pass",
    "liquidity_gate_pass", "current_ask", "min_odds", "max_odds", "odds_gate_pass",
    "golden_window_gate_pass", "velocity_gate_pass", "slippage_gate_pass",
    "t_remaining_sec", "would_have_won", "chainlink_age_sec",
]  # 21 fields

SNAPSHOT_FIELDS = [
    "session_id", "window_id", "timestamp", "t_remaining_sec", "strike_price",
    "hl_price", "gap", "gap_direction", "atr_60m", "atr_regime",
    "cvd_60s", "cvd_aligned", "avg_volume_per_min", "poly_up_odds",
    "poly_down_odds", "poly_up_ask_depth", "poly_down_bid_depth", "spread_pct",
    "dual_side_ok", "chainlink_age_sec", "bot_mode", "all_gates_pass", "window_result",
]  # 23 fields

SESSION_SUMMARY_FIELDS = [
    "session_id", "start_time", "end_time", "duration_min", "bot_version",
    "bot_mode", "total_windows", "windows_traded", "windows_skipped",
    "windows_locked", "wins", "losses", "win_rate", "total_cost_usdc",
    "total_payout_usdc", "net_pnl_usdc", "avg_entry_odds", "avg_gap_at_entry",
    "avg_blockchain_latency_ms", "skip_gap_insufficient", "skip_cvd_not_aligned",
    "skip_odds_too_low", "skip_odds_too_high", "skip_no_liquidity", "skip_slippage",
    "skip_other", "lockdown_triggers", "unclaimed_balance_usdc",
    "auto_claimed_usdc", "manual_claim_required",
]  # 30 fields

EVENT_LOG_FIELDS = [
    "timestamp", "event_type", "window_id", "trigger",
    "mode", "details", "gate_failed", "state_snapshot_json",
]  # 8 fields


def _iso_now() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


class AuditLogger:
    """Manages all CSV log files and JSON engine state with per-file locking."""

    def __init__(self, cfg: BotConfig) -> None:
        self._cfg = cfg
        self._output_dir = Path(cfg.OUTPUT_DIR)
        self._output_dir.mkdir(parents=True, exist_ok=True)

        # Per-file asyncio locks
        self._trade_lock = asyncio.Lock()
        self._skip_lock = asyncio.Lock()
        self._snapshot_lock = asyncio.Lock()
        self._session_lock = asyncio.Lock()
        self._event_lock = asyncio.Lock()
        self._state_lock = asyncio.Lock()

        # Track rotation
        self._log_start_date: str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # ═══════════════════════════════════════════════════
    # PUBLIC WRITE METHODS
    # ═══════════════════════════════════════════════════

    async def log_trade(self, trade: TradeRecord) -> None:
        """Append one row to trade_log.csv (32 fields)."""
        async with self._trade_lock:
            path = self._get_log_path(self._cfg.TRADE_LOG_FILE)
            row = asdict(trade)
            await self._append_csv(path, TRADE_LOG_FIELDS, row)

    async def log_skip(self, skip: SkipRecord) -> None:
        """Append one row to skip_log.csv (21 fields)."""
        async with self._skip_lock:
            path = self._get_log_path(self._cfg.SKIP_LOG_FILE)
            row = asdict(skip)
            await self._append_csv(path, SKIP_LOG_FIELDS, row)

    async def log_snapshot(self, snapshot: SnapshotRecord) -> None:
        """Append one row to market_snapshot.csv (23 fields)."""
        async with self._snapshot_lock:
            path = self._get_log_path(self._cfg.MARKET_SNAPSHOT_FILE)
            row = asdict(snapshot)
            await self._append_csv(path, SNAPSHOT_FIELDS, row)

    async def log_event(self, event: EventRecord) -> None:
        """Append one row to event_log.csv (8 fields)."""
        async with self._event_lock:
            path = self._get_log_path(self._cfg.EVENT_LOG_FILE)
            row = {
                "timestamp": datetime.fromtimestamp(event.timestamp, tz=timezone.utc).strftime(
                    "%Y-%m-%d %H:%M:%S.%f"
                )[:-3],
                "event_type": event.event_type,
                "window_id": event.window_id,
                "trigger": event.trigger,
                "mode": event.mode,
                "details": event.details,
                "gate_failed": event.gate_failed if event.gate_failed is not None else "",
                "state_snapshot_json": event.state_snapshot_json,
            }
            await self._append_csv(path, EVENT_LOG_FIELDS, row)

    async def write_session_summary(self, stats: SessionStats) -> None:
        """Append one row to session_summary.csv (30 fields)."""
        async with self._session_lock:
            path = self._get_log_path(self._cfg.SESSION_SUMMARY_FILE)
            row = asdict(stats)
            await self._append_csv(path, SESSION_SUMMARY_FIELDS, row)

    async def flush_state(self, state: dict) -> None:
        """Atomic write engine_state.json — write to .tmp then rename."""
        async with self._state_lock:
            state_path = self._output_dir / self._cfg.STATE_FILE
            tmp_path = state_path.with_suffix(".json.tmp")

            try:
                # Add metadata
                state["_last_flush"] = _iso_now()
                state["_bot_version"] = self._cfg.BOT_VERSION

                data = json.dumps(state, indent=2, default=str)

                # Write to temp file first
                with open(tmp_path, "w", encoding="utf-8") as f:
                    f.write(data)
                    f.flush()
                    os.fsync(f.fileno())

                # Atomic rename (on same filesystem)
                if state_path.exists():
                    state_path.unlink()
                tmp_path.rename(state_path)

            except Exception as exc:
                logger.error("Failed to flush engine state: %s", exc)
                # Clean up temp file if it exists
                if tmp_path.exists():
                    try:
                        tmp_path.unlink()
                    except Exception:
                        pass

    # ═══════════════════════════════════════════════════
    # POST-HOC UPDATE METHODS
    # ═══════════════════════════════════════════════════

    async def update_trade_resolution(
        self,
        window_id: str,
        resolution_price: float,
        payout_usdc: float,
        pnl_usdc: float,
        claim_method: str,
        claim_timestamp: str,
    ) -> None:
        """Update trade_log.csv rows for a window with resolution data."""
        async with self._trade_lock:
            path = self._get_log_path(self._cfg.TRADE_LOG_FILE)
            await self._update_csv_rows(
                path, TRADE_LOG_FIELDS, "window_id", window_id,
                {
                    "resolution_price": resolution_price,
                    "payout_usdc": payout_usdc,
                    "pnl_usdc": pnl_usdc,
                    "claim_method": claim_method,
                    "claim_timestamp": claim_timestamp,
                },
            )

    async def update_skip_would_have_won(
        self, window_id: str, resolution_direction: str,
    ) -> None:
        """Update skip_log.csv — set would_have_won based on resolution."""
        async with self._skip_lock:
            path = self._get_log_path(self._cfg.SKIP_LOG_FILE)
            if not path.exists():
                return

            rows = []
            updated = False
            try:
                with open(path, "r", encoding="utf-8", newline="") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if row.get("window_id") == window_id:
                            # Determine if the skip direction matches resolution
                            gap_val = float(row.get("gap_value", 0) or 0)
                            skip_direction = "UP" if gap_val > 0 else "DOWN"
                            row["would_have_won"] = str(skip_direction == resolution_direction)
                            updated = True
                        rows.append(row)

                if updated:
                    with open(path, "w", encoding="utf-8", newline="") as f:
                        writer = csv.DictWriter(f, fieldnames=SKIP_LOG_FIELDS)
                        writer.writeheader()
                        writer.writerows(rows)
            except Exception as exc:
                logger.error("Failed to update skip would_have_won: %s", exc)

    async def update_snapshot_window_result(
        self, window_id: str, result: str,
    ) -> None:
        """Update market_snapshot.csv — fill window_result post-hoc."""
        async with self._snapshot_lock:
            path = self._get_log_path(self._cfg.MARKET_SNAPSHOT_FILE)
            if not path.exists():
                return

            rows = []
            updated = False
            try:
                with open(path, "r", encoding="utf-8", newline="") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if row.get("window_id") == window_id:
                            row["window_result"] = result
                            updated = True
                        rows.append(row)

                if updated:
                    with open(path, "w", encoding="utf-8", newline="") as f:
                        writer = csv.DictWriter(f, fieldnames=SNAPSHOT_FIELDS)
                        writer.writeheader()
                        writer.writerows(rows)
            except Exception as exc:
                logger.error("Failed to update snapshot window_result: %s", exc)

    # ═══════════════════════════════════════════════════
    # INTERNAL HELPERS
    # ═══════════════════════════════════════════════════

    async def _append_csv(
        self, path: Path, fieldnames: list[str], row: dict,
    ) -> None:
        """Append a single row to a CSV file. Creates header if file is new."""
        try:
            file_exists = path.exists() and path.stat().st_size > 0
            with open(path, "a", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                if not file_exists:
                    writer.writeheader()
                # Ensure all fields are present (fill missing with empty)
                clean_row = {k: row.get(k, "") for k in fieldnames}
                writer.writerow(clean_row)
        except Exception as exc:
            logger.error("Failed to write CSV %s: %s", path, exc)

    async def _update_csv_rows(
        self,
        path: Path,
        fieldnames: list[str],
        match_field: str,
        match_value: str,
        updates: dict,
    ) -> None:
        """Update rows in a CSV file that match a field value."""
        if not path.exists():
            return

        try:
            rows = []
            with open(path, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get(match_field) == match_value:
                        row.update({k: str(v) for k, v in updates.items()})
                    rows.append(row)

            with open(path, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
        except Exception as exc:
            logger.error("Failed to update CSV %s: %s", path, exc)

    def _get_log_path(self, base_filename: str) -> Path:
        """Get the log file path, handling rotation by date."""
        current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Check if rotation is needed
        if self._cfg.LOG_ROTATION_DAYS > 0:
            name, ext = os.path.splitext(base_filename)
            # Use date suffix for rotation
            if current_date != self._log_start_date:
                # Check if the start date is more than LOG_ROTATION_DAYS ago
                pass  # Rotation happens naturally by date-based file naming

            return self._output_dir / f"{name}_{current_date}{ext}"

        return self._output_dir / base_filename
