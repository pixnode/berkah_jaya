# === FILE: btc_sniper/core/order_executor.py ===
"""
Order Executor: handles order submission to Polymarket CLOB.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Literal, Optional

from py_clob_client.client import ClobClient as ClobClientV1
from py_clob_client.clob_types import ApiCreds, OrderArgs

from config import BotConfig
from risk.gates import GateResult

logger = logging.getLogger("btc_sniper.core.order_executor")


@dataclass
class OrderResult:
    """Result of an order execution attempt."""

    status: Literal[
        "FILLED",
        "PARTIAL",
        "REJECTED",
        "SLIPPAGE_EXCEEDED",
        "TIMEOUT",
        "ERROR",
        "POSITION_TOO_LARGE",
        "PAPER_FILL",
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
    """Executes orders on Polymarket CLOB with safety checks."""

    def __init__(self, cfg: BotConfig, event_logger: Optional[object] = None) -> None:
        self._cfg = cfg
        self._event_logger = event_logger
        self._client_v1: Optional[ClobClientV1] = None
        self._circuit_breaker: Optional[object] = None

        if not self._cfg.PAPER_TRADING_MODE:
            self._init_clob_client()

    def set_circuit_breaker(self, circuit_breaker: object) -> None:
        """Inject circuit breaker reference for last-moment lockdown guard."""
        self._circuit_breaker = circuit_breaker

    def _init_clob_client(self) -> None:
        """Initialize V1 CLOB client only."""
        funder = self._cfg.POLYMARKET_PROXY_WALLET if self._cfg.POLY_WALLET_TYPE == "safe" else None
        sig_type = 1 if self._cfg.POLY_WALLET_TYPE == "safe" else 2

        if self._cfg.CLOB_API_VERSION != "v1":
            logger.warning(
                "CLOB_API_VERSION=%s ignored: forcing py_clob_client V1 until V2 rollout is available.",
                self._cfg.CLOB_API_VERSION,
            )

        creds = ApiCreds(
            api_key=self._cfg.POLY_API_KEY,
            api_secret=self._cfg.POLY_API_SECRET,
            api_passphrase=self._cfg.POLY_API_PASSPHRASE,
        )

        self._client_v1 = ClobClientV1(
            self._cfg.CLOB_HOST,
            key=self._cfg.POLYMARKET_PRIVATE_KEY,
            chain_id=self._cfg.POLY_CHAIN_ID,
            signature_type=sig_type,
            funder=funder,
            creds=creds,
        )
        logger.info("Initialized CLOB Client V1 (L2 Auth, Safe: %s)", self._cfg.POLY_WALLET_TYPE == "safe")

    async def execute(self, gate_result: GateResult, token_id: str, window_id: str) -> OrderResult:
        """Execute an order based on gate evaluation result."""
        side = gate_result.side
        signal_odds = gate_result.target_ask
        vol_regime = gate_result.signal_snapshot.vol_regime

        if self._cfg.PAPER_TRADING_MODE:
            simulated_cost = self._cfg.BASE_SHARES * signal_odds
            logger.info(
                "[PAPER] Simulated %s fill on Token %s: odds=%.3f, cost=$%.4f",
                side,
                token_id[:8],
                signal_odds,
                simulated_cost,
            )
            return OrderResult(
                status="PAPER_FILL",
                window_id=window_id,
                side=side,
                entry_odds=signal_odds,
                shares_bought=self._cfg.BASE_SHARES,
                cost_usd=simulated_cost,
                slippage_delta=0.0,
                slippage_threshold_used=0.0,
                tx_hash=None,
                confirmed_at=time.time(),
                latency_ms=0,
                error_msg=None,
                is_paper=True,
            )

        if signal_odds < 0.10:
            slippage_threshold = self._cfg.SLIPPAGE_THRESHOLD_ABS_LOW_ODDS
            price_buffer = slippage_threshold
        else:
            slippage_threshold = self._get_slippage_threshold(vol_regime)
            price_buffer = signal_odds * (slippage_threshold / 100.0)

        worst_acceptable_price = min(0.99, max(0.01, signal_odds + max(price_buffer, 0.0)))
        slippage_delta = max(0.0, worst_acceptable_price - signal_odds)

        cost_estimate = self._cfg.BASE_SHARES * worst_acceptable_price
        if cost_estimate > self._cfg.MAX_POSITION_USD:
            logger.warning("POSITION_TOO_LARGE: $%.4f > max $%.2f", cost_estimate, self._cfg.MAX_POSITION_USD)
            return OrderResult(
                status="POSITION_TOO_LARGE",
                window_id=window_id,
                side=side,
                entry_odds=worst_acceptable_price,
                shares_bought=None,
                cost_usd=cost_estimate,
                slippage_delta=slippage_delta,
                slippage_threshold_used=slippage_threshold,
                tx_hash=None,
                confirmed_at=None,
                latency_ms=None,
                error_msg="Position too large",
                is_paper=False,
            )

        if self._circuit_breaker is not None and getattr(self._circuit_breaker, "is_lockdown", False):
            msg = "Order rejected: circuit breaker lockdown active"
            logger.warning(msg)
            return OrderResult(
                status="REJECTED",
                window_id=window_id,
                side=side,
                entry_odds=worst_acceptable_price,
                shares_bought=None,
                cost_usd=None,
                slippage_delta=slippage_delta,
                slippage_threshold_used=slippage_threshold,
                tx_hash=None,
                confirmed_at=None,
                latency_ms=None,
                error_msg=msg,
                is_paper=False,
            )

        t_submit = time.time()
        try:
            tx_result = await self._submit_order(worst_acceptable_price, token_id)
        except Exception as exc:
            logger.error("Order submission error: %s", exc)
            return OrderResult(
                status="ERROR",
                window_id=window_id,
                side=side,
                entry_odds=worst_acceptable_price,
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

        return OrderResult(
            status=tx_result.get("status", "FILLED"),
            window_id=window_id,
            side=side,
            entry_odds=worst_acceptable_price,
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
        if vol_regime == "HIGH":
            return self._cfg.SLIPPAGE_THRESHOLD_HIGH
        return self._cfg.SLIPPAGE_THRESHOLD_NORMAL

    async def _submit_order(self, worst_acceptable_price: float, token_id: str) -> dict:
        """Build, sign, and submit BUY order to Polymarket CLOB V1."""
        if not self._client_v1:
            logger.error("CLOB client not initialized: cannot submit order")
            return {"status": "REJECTED", "tx_hash": None, "error": "CLOB client not initialized"}

        try:
            order_args = OrderArgs(
                token_id=token_id,
                price=worst_acceptable_price,
                size=self._cfg.BASE_SHARES,
                side="BUY",
            )
            signed_order = self._client_v1.create_and_post_order(order_args)
            logger.info("Order posted via CLOB V1: %s", signed_order)
            return {
                "status": "FILLED",
                "tx_hash": signed_order.get("orderID", ""),
                "error": None,
            }
        except Exception as exc:
            logger.error("Order submission failed: %s", exc)
            return {"status": "REJECTED", "tx_hash": None, "error": str(exc)}

    async def stop(self) -> None:
        """OrderExecutor has no persistent async resources to close."""
        return

    async def _log_event(self, event_type: str, window_id: str, details: str) -> None:
        """Log event via injected logger."""
        if self._event_logger is not None and hasattr(self._event_logger, "log_event"):
            try:
                from logs.audit_logger import EventRecord

                record = EventRecord(time.time(), event_type, window_id, "order_executor", "", details, None, "{}")
                await self._event_logger.log_event(record)
            except Exception:
                pass
