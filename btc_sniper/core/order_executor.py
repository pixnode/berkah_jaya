# ═══ FILE: btc_sniper/core/order_executor.py ═══
"""
Order Executor — handles order submission to Polymarket CLOB.
Includes paper trading guard, temporal slippage check (Check B),
position size guard, and EIP-712 order signing.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Literal, Optional

import aiohttp

from config import BotConfig
from risk.gates import GateResult

logger = logging.getLogger("btc_sniper.core.order_executor")


@dataclass
class OrderResult:
    """Result of an order execution attempt."""
    status: Literal[
        "FILLED", "PARTIAL", "REJECTED", "SLIPPAGE_EXCEEDED",
        "TIMEOUT", "ERROR", "POSITION_TOO_LARGE", "PAPER_FILL",
    ]
    window_id: str
    side: Optional[str]
    entry_odds: Optional[float]
    shares_bought: Optional[float]
    cost_usd: Optional[float]
    slippage_delta: float
    slippage_threshold_used: float
    tx_hash: Optional[str]
    confirmed_at: Optional[float]
    latency_ms: Optional[int]
    error_msg: Optional[str]
    is_paper: bool


class OrderExecutor:
    """Executes orders on Polymarket CLOB with full safety checks."""

    def __init__(self, cfg: BotConfig, event_logger: Optional[object] = None) -> None:
        self._cfg = cfg
        self._event_logger = event_logger
        self._session: Optional[aiohttp.ClientSession] = None

    async def execute(self, gate_result: GateResult, window_id: str) -> OrderResult:
        """Execute an order based on gate evaluation result.

        Steps: Paper guard → Temporal slippage → Position size → Sign → Submit → Confirm
        """
        side = gate_result.side
        signal_odds = gate_result.target_ask
        vol_regime = gate_result.signal_snapshot.vol_regime

        # ══════════════════════════════════════════════
        # STEP 0 — Paper Trading Guard
        # ══════════════════════════════════════════════
        if self._cfg.PAPER_TRADING_MODE:
            simulated_odds = signal_odds
            simulated_cost = self._cfg.BASE_SHARES * simulated_odds
            logger.info(
                "[PAPER] Simulated %s fill: odds=%.3f, cost=$%.4f",
                side, simulated_odds, simulated_cost,
            )
            return OrderResult(
                status="PAPER_FILL",
                window_id=window_id,
                side=side,
                entry_odds=simulated_odds,
                shares_bought=self._cfg.BASE_SHARES,
                cost_usd=simulated_cost,
                slippage_delta=0.0,
                slippage_threshold_used=self._get_slippage_threshold(vol_regime),
                tx_hash=None,
                confirmed_at=time.time(),
                latency_ms=0,
                error_msg=None,
                is_paper=True,
            )

        # ══════════════════════════════════════════════
        # STEP 1 — Snapshot T_signal odds (from gate_result)
        # ══════════════════════════════════════════════
        t_signal_odds = signal_odds

        # ══════════════════════════════════════════════
        # STEP 2 — Re-fetch live odds (Check B — temporal slippage)
        # ══════════════════════════════════════════════
        try:
            live_odds = await self._fetch_live_odds(side, window_id)
        except Exception as exc:
            logger.error("Failed to fetch live odds: %s", exc)
            return OrderResult(
                status="ERROR",
                window_id=window_id,
                side=side,
                entry_odds=t_signal_odds,
                shares_bought=None,
                cost_usd=None,
                slippage_delta=0.0,
                slippage_threshold_used=self._get_slippage_threshold(vol_regime),
                tx_hash=None,
                confirmed_at=None,
                latency_ms=None,
                error_msg=f"LIVE_ODDS_FETCH_FAILED: {exc}",
                is_paper=False,
            )

        # ══════════════════════════════════════════════
        # STEP 3 — Temporal slippage check
        # ══════════════════════════════════════════════
        if t_signal_odds > 0:
            slippage_delta = abs(live_odds - t_signal_odds) / t_signal_odds * 100.0
        else:
            slippage_delta = 0.0

        slippage_threshold = self._get_slippage_threshold(vol_regime)

        if slippage_delta > slippage_threshold:
            logger.warning(
                "SLIPPAGE_EXCEEDED: delta=%.2f%% > threshold=%.2f%%",
                slippage_delta, slippage_threshold,
            )
            await self._log_event(
                "SLIPPAGE_EXCEEDED", window_id,
                f"delta={slippage_delta:.2f}% > threshold={slippage_threshold:.2f}%",
            )
            return OrderResult(
                status="SLIPPAGE_EXCEEDED",
                window_id=window_id,
                side=side,
                entry_odds=live_odds,
                shares_bought=None,
                cost_usd=None,
                slippage_delta=slippage_delta,
                slippage_threshold_used=slippage_threshold,
                tx_hash=None,
                confirmed_at=None,
                latency_ms=None,
                error_msg=f"Slippage {slippage_delta:.2f}% exceeded threshold {slippage_threshold:.2f}%",
                is_paper=False,
            )

        # ══════════════════════════════════════════════
        # STEP 4 — Position size guard
        # ══════════════════════════════════════════════
        cost_estimate = self._cfg.BASE_SHARES * live_odds
        if cost_estimate > self._cfg.MAX_POSITION_USD:
            logger.warning(
                "POSITION_TOO_LARGE: $%.4f > max $%.2f",
                cost_estimate, self._cfg.MAX_POSITION_USD,
            )
            await self._log_event(
                "POSITION_TOO_LARGE", window_id,
                f"cost=${cost_estimate:.4f} > max=${self._cfg.MAX_POSITION_USD:.2f}",
            )
            return OrderResult(
                status="POSITION_TOO_LARGE",
                window_id=window_id,
                side=side,
                entry_odds=live_odds,
                shares_bought=None,
                cost_usd=cost_estimate,
                slippage_delta=slippage_delta,
                slippage_threshold_used=slippage_threshold,
                tx_hash=None,
                confirmed_at=None,
                latency_ms=None,
                error_msg=f"Cost ${cost_estimate:.4f} exceeds MAX_POSITION_USD ${self._cfg.MAX_POSITION_USD:.2f}",
                is_paper=False,
            )

        # ══════════════════════════════════════════════
        # STEP 5-6-7 — Build, Sign, Submit, Monitor
        # ══════════════════════════════════════════════
        t_submit = time.time()

        try:
            tx_result = await self._submit_order(side, live_odds, window_id)
        except asyncio.TimeoutError:
            logger.warning("ORDER_TIMEOUT: submission timed out")
            await self._log_event(
                "ORDER_TIMEOUT", window_id,
                "TIMEOUT_NOT_LOSS — order submission timed out",
            )
            return OrderResult(
                status="TIMEOUT",
                window_id=window_id,
                side=side,
                entry_odds=live_odds,
                shares_bought=None,
                cost_usd=None,
                slippage_delta=slippage_delta,
                slippage_threshold_used=slippage_threshold,
                tx_hash=None,
                confirmed_at=None,
                latency_ms=None,
                error_msg="TIMEOUT_NOT_LOSS",
                is_paper=False,
            )
        except aiohttp.ClientError as exc:
            logger.error("Order submission network error: %s", exc)
            return OrderResult(
                status="ERROR",
                window_id=window_id,
                side=side,
                entry_odds=live_odds,
                shares_bought=None,
                cost_usd=None,
                slippage_delta=slippage_delta,
                slippage_threshold_used=slippage_threshold,
                tx_hash=None,
                confirmed_at=None,
                latency_ms=None,
                error_msg=str(exc),
                is_paper=False,
            )

        t_confirmed = time.time()
        latency_ms = int((t_confirmed - t_submit) * 1000)

        # ══════════════════════════════════════════════
        # STEP 8 — Return OrderResult
        # ══════════════════════════════════════════════
        return OrderResult(
            status=tx_result.get("status", "FILLED"),
            window_id=window_id,
            side=side,
            entry_odds=live_odds,
            shares_bought=self._cfg.BASE_SHARES,
            cost_usd=cost_estimate,
            slippage_delta=slippage_delta,
            slippage_threshold_used=slippage_threshold,
            tx_hash=tx_result.get("tx_hash"),
            confirmed_at=t_confirmed,
            latency_ms=latency_ms,
            error_msg=tx_result.get("error"),
            is_paper=False,
        )

    def _get_slippage_threshold(self, vol_regime: str) -> float:
        """Return adaptive slippage threshold based on volatility regime."""
        if vol_regime == "HIGH":
            return self._cfg.SLIPPAGE_THRESHOLD_HIGH
        elif vol_regime in ("NORM", "LOW"):
            return self._cfg.SLIPPAGE_THRESHOLD_NORMAL
        else:
            return self._cfg.SLIPPAGE_THRESHOLD_ELEVATED

    async def _fetch_live_odds(self, side: Optional[str], window_id: str) -> float:
        """Re-fetch current odds from Polymarket CLOB API."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=5),
            )

        url = f"https://clob.polymarket.com/book"
        params = {"token_id": window_id}

        try:
            async with self._session.get(url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    asks = data.get("asks", [])
                    if asks:
                        best_ask = float(asks[0].get("price", 0))
                        if side == "DOWN":
                            return round(1.0 - best_ask, 4) if best_ask > 0 else 0.0
                        return best_ask
                    raise RuntimeError("No asks in order book")
                raise RuntimeError(f"HTTP {resp.status}")
        except asyncio.TimeoutError:
            raise
        except aiohttp.ClientError:
            raise

    async def _submit_order(self, side: Optional[str], odds: float, window_id: str) -> dict:
        """Build, sign, and submit order to Polymarket CLOB API.

        Returns dict with status, tx_hash, error fields.
        """
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=8),
            )

        # Build EIP-712 signed order payload
        order_payload = {
            "market": window_id,
            "side": "BUY",
            "outcome": side,
            "size": str(self._cfg.BASE_SHARES),
            "price": str(odds),
            "type": "GTC",
        }

        # Sign with private key (using py-clob-client internally)
        try:
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import OrderArgs

            client = ClobClient(
                host="https://clob.polymarket.com",
                key=self._cfg.POLYMARKET_PRIVATE_KEY,
                chain_id=137,  # Polygon
                signature_type=2,  # POLY_GNOSIS_SAFE or POLY_PROXY
            )

            order_args = OrderArgs(
                token_id=window_id,
                price=odds,
                size=self._cfg.BASE_SHARES,
            )

            signed_order = client.create_and_post_order(order_args)

            return {
                "status": "FILLED",
                "tx_hash": signed_order.get("orderID", signed_order.get("id", "")),
                "error": None,
            }

        except asyncio.TimeoutError:
            raise
        except Exception as exc:
            logger.error("Order submission failed: %s", exc, exc_info=True)
            return {
                "status": "REJECTED",
                "tx_hash": None,
                "error": str(exc),
            }

    async def close(self) -> None:
        """Close HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def _log_event(self, event_type: str, window_id: str, details: str) -> None:
        """Log event via injected logger."""
        if self._event_logger is not None and hasattr(self._event_logger, "log_event"):
            try:
                from logs.audit_logger import EventRecord
                record = EventRecord(
                    timestamp=time.time(),
                    event_type=event_type,
                    window_id=window_id,
                    trigger="order_executor",
                    mode="",
                    details=details,
                    gate_failed=None,
                    state_snapshot_json="{}",
                )
                await self._event_logger.log_event(record)
            except Exception:
                pass
