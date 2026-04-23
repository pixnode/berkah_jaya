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
        self._client_v1 = None
        self._client_v2 = None

        if not self._cfg.PAPER_TRADING_MODE:
            self._init_clob_client()

    def _init_clob_client(self) -> None:
        """Initialize the specific CLOB client based on API version.
        
        MUST use Level 2 Auth (key + creds) for create_and_post_order().
        MUST set signature_type=1 and funder for SAFE wallet gasless trades.
        """
        from py_clob_client.clob_types import ApiCreds
        
        funder = self._cfg.POLYMARKET_PROXY_WALLET if self._cfg.POLY_WALLET_TYPE == "safe" else None
        sig_type = 1 if self._cfg.POLY_WALLET_TYPE == "safe" else 2
        
        creds = ApiCreds(
            api_key=self._cfg.POLY_API_KEY,
            api_secret=self._cfg.POLY_API_SECRET,
            api_passphrase=self._cfg.POLY_API_PASSPHRASE,
        )
        
        if self._cfg.CLOB_API_VERSION == "v2":
            try:
                from py_clob_client_v2.client import ClobClient as ClobClientV2
                self._client_v2 = ClobClientV2(
                    self._cfg.CLOB_HOST,
                    key=self._cfg.POLYMARKET_PRIVATE_KEY,
                    chain_id=self._cfg.POLY_CHAIN_ID,
                    signature_type=sig_type,
                    funder=funder,
                    creds=creds,
                )
                logger.info("Initialized CLOB Client V2 (L2 Auth, Safe: %s)", self._cfg.POLY_WALLET_TYPE == "safe")
            except ImportError as e:
                logger.error("py-clob-client-v2 not installed: %s", e)
        else:
            try:
                from py_clob_client.client import ClobClient as ClobClientV1
                self._client_v1 = ClobClientV1(
                    self._cfg.CLOB_HOST,
                    key=self._cfg.POLYMARKET_PRIVATE_KEY,
                    chain_id=self._cfg.POLY_CHAIN_ID,
                    signature_type=sig_type,
                    funder=funder,
                    creds=creds,
                )
                logger.info("Initialized CLOB Client V1 (L2 Auth, Safe: %s)", self._cfg.POLY_WALLET_TYPE == "safe")
            except ImportError as e:
                logger.error("py-clob-client not installed: %s", e)

    async def execute(self, gate_result: GateResult, token_id: str, window_id: str) -> OrderResult:
        """Execute an order based on gate evaluation result."""
        side = gate_result.side
        signal_odds = gate_result.target_ask
        vol_regime = gate_result.signal_snapshot.vol_regime

        if self._cfg.PAPER_TRADING_MODE:
            simulated_cost = self._cfg.BASE_SHARES * signal_odds
            logger.info("[PAPER] Simulated %s fill on Token %s: odds=%.3f, cost=$%.4f", side, token_id[:8], signal_odds, simulated_cost)
            return OrderResult("PAPER_FILL", window_id, side, signal_odds, self._cfg.BASE_SHARES, simulated_cost, 0.0, self._get_slippage_threshold(vol_regime), None, time.time(), 0, None, True)

        try:
            live_odds = await self._fetch_live_odds(token_id)
        except Exception as exc:
            logger.error("Failed to fetch live odds for token %s: %s", token_id[:8], exc)
            return OrderResult("ERROR", window_id, side, signal_odds, None, None, 0.0, self._get_slippage_threshold(vol_regime), None, None, None, str(exc), False)

        slippage_delta = abs(live_odds - signal_odds) / signal_odds * 100.0 if signal_odds > 0 else 0.0
        slippage_threshold = self._get_slippage_threshold(vol_regime)

        if slippage_delta > slippage_threshold:
            logger.warning("SLIPPAGE_EXCEEDED: %.2f%% > %.2f%%", slippage_delta, slippage_threshold)
            await self._log_event("SLIPPAGE_EXCEEDED", window_id, f"delta={slippage_delta:.2f}% > threshold={slippage_threshold:.2f}%")
            return OrderResult("SLIPPAGE_EXCEEDED", window_id, side, live_odds, None, None, slippage_delta, slippage_threshold, None, None, None, "Slippage exceeded", False)

        cost_estimate = self._cfg.BASE_SHARES * live_odds
        if cost_estimate > self._cfg.MAX_POSITION_USD:
            logger.warning("POSITION_TOO_LARGE: $%.4f > max $%.2f", cost_estimate, self._cfg.MAX_POSITION_USD)
            return OrderResult("POSITION_TOO_LARGE", window_id, side, live_odds, None, cost_estimate, slippage_delta, slippage_threshold, None, None, None, "Position too large", False)

        t_submit = time.time()
        try:
            tx_result = await self._submit_order(live_odds, token_id)
        except Exception as exc:
            logger.error("Order submission error: %s", exc)
            return OrderResult("ERROR", window_id, side, live_odds, None, None, slippage_delta, slippage_threshold, None, None, None, str(exc), False)

        t_confirmed = time.time()
        latency_ms = int((t_confirmed - t_submit) * 1000)

        return OrderResult(tx_result.get("status", "FILLED"), window_id, side, live_odds, self._cfg.BASE_SHARES, cost_estimate, slippage_delta, slippage_threshold, tx_result.get("tx_hash"), t_confirmed, latency_ms, tx_result.get("error"), False)

    def _get_slippage_threshold(self, vol_regime: str) -> float:
        if vol_regime == "HIGH": return self._cfg.SLIPPAGE_THRESHOLD_HIGH
        return self._cfg.SLIPPAGE_THRESHOLD_NORMAL

    async def _fetch_live_odds(self, token_id: str) -> float:
        """Re-fetch current odds from Polymarket CLOB API using specific Token ID."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5))
        url = f"{self._cfg.CLOB_HOST}/book"
        params = {"token_id": token_id}
        async with self._session.get(url, params=params) as resp:
            if resp.status == 200:
                data = await resp.json()
                asks = data.get("asks", [])
                if asks:
                    return float(asks[0].get("price", 0))
            raise RuntimeError(f"HTTP {resp.status} fetching odds for token {token_id[:8]}")

    async def _submit_order(self, odds: float, token_id: str) -> dict:
        """Build, sign, and submit BUY order to Polymarket CLOB API.
        
        Uses create_and_post_order() which requires Level 2 Auth.
        All sniper orders are BUY (buying outcome shares).
        """
        try:
            if self._cfg.CLOB_API_VERSION == "v2" and self._client_v2:
                from py_clob_client_v2.clob_types import OrderArgs
                order_args = OrderArgs(token_id=token_id, price=odds, size=self._cfg.BASE_SHARES, side="BUY")
                signed_order = self._client_v2.create_and_post_order(order_args)
                logger.info("Order posted via CLOB V2: %s", signed_order)
                return {"status": "FILLED", "tx_hash": signed_order.get("orderID", ""), "error": None}
            elif self._client_v1:
                from py_clob_client.clob_types import OrderArgs
                order_args = OrderArgs(token_id=token_id, price=odds, size=self._cfg.BASE_SHARES, side="BUY")
                signed_order = self._client_v1.create_and_post_order(order_args)
                logger.info("Order posted via CLOB V1: %s", signed_order)
                return {"status": "FILLED", "tx_hash": signed_order.get("orderID", ""), "error": None}
            else:
                logger.error("CLOB client not initialized — cannot submit order")
                return {"status": "REJECTED", "tx_hash": None, "error": "CLOB client not initialized"}
        except Exception as exc:
            logger.error("Order submission failed: %s", exc)
            return {"status": "REJECTED", "tx_hash": None, "error": str(exc)}

    async def stop(self) -> None:
        """Close HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            logger.info("OrderExecutor session closed.")

    async def _log_event(self, event_type: str, window_id: str, details: str) -> None:
        """Log event via injected logger."""
        if self._event_logger is not None and hasattr(self._event_logger, "log_event"):
            try:
                from logs.audit_logger import EventRecord
                record = EventRecord(time.time(), event_type, window_id, "order_executor", "", details, None, "{}")
                await self._event_logger.log_event(record)
            except Exception: pass
