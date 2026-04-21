# === FILE: btc_sniper/core/claim_manager.py ===
"""
Claim Manager — auto-claim winning shares via Polymarket Gasless Relayer.
Retry queue with exponential backoff. Supports paper trading simulation.
Recognizes SAFE/Gnosis/Proxy wallets for auto-claim.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Literal, Optional

import aiohttp

from config import BotConfig
from core.order_executor import OrderResult

try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import ApiCreds
except ImportError:
    ClobClient = None
    ApiCreds = None

logger = logging.getLogger("btc_sniper.core.claim_manager")


@dataclass
class ClaimResult:
    """Result of a claim attempt."""
    status: Literal["AUTO", "PENDING_RETRY", "PENDING_MANUAL", "LOSS", "NOT_APPLICABLE", "PAPER"]
    window_id: str
    payout_usd: float
    claim_method: Literal["AUTO", "MANUAL", "PENDING", "N-A", "PAPER"]
    claimed_at: Optional[float]
    retry_count: int
    is_paper: bool


class ClaimManager:
    """Handles auto-claiming of winning Polymarket shares."""

    def __init__(self, cfg: BotConfig, event_logger: Optional[object] = None) -> None:
        self._cfg = cfg
        self._event_logger = event_logger
        self._session: Optional[aiohttp.ClientSession] = None
        self._eoa_warning: bool = False
        self._wallet_type: str = "PROXY"
        self._unclaimed_balance: float = 0.0
        self._unclaimed_since: float = 0.0
        self._clob_client: Optional[object] = None
        self._chainlink_feed: Optional[object] = None

    def set_chainlink_feed(self, feed: object) -> None:
        """Inject chainlink feed for paper mode simulation."""
        self._chainlink_feed = feed

    async def _init_clob_client(self) -> None:
        """Initialize CLOB client dengan API credentials."""
        if self._cfg.PAPER_TRADING_MODE:
            logger.info("Paper mode: CLOB client tidak diinisialisasi")
            return
        if ClobClient is None:
            logger.error("py_clob_client is not installed!")
            return
        self._clob_client = ClobClient(
            host=self._cfg.CLOB_HOST,
            key=self._cfg.POLYMARKET_PRIVATE_KEY,
            chain_id=self._cfg.POLY_CHAIN_ID,
            creds=ApiCreds(
                api_key=self._cfg.POLY_API_KEY,
                api_secret=self._cfg.POLY_API_SECRET,
                api_passphrase=self._cfg.POLY_API_PASSPHRASE,
            ),
        )
        logger.info("CLOB client initialized successfully")

    @property
    def eoa_warning(self) -> bool:
        """Whether wallet is EOA (no auto-claim support)."""
        return self._eoa_warning

    @property
    def wallet_type(self) -> str:
        """Detected wallet type: PROXY or EOA."""
        return self._wallet_type

    @property
    def unclaimed_balance(self) -> float:
        """Total USDC pending claim."""
        return self._unclaimed_balance

    @property
    def unclaimed_since(self) -> float:
        """Seconds since oldest unclaimed balance."""
        if self._unclaimed_since <= 0:
            return 0.0
        return time.time() - self._unclaimed_since

    async def check_wallet_type(self) -> str:
        """Check wallet type using POLY_WALLET_TYPE from config.
        Recognizes: proxy, safe, gnosis → auto-claim enabled.
        Recognizes: eoa → auto-claim NOT supported.
        """
        wallet_type = self._cfg.POLY_WALLET_TYPE.lower().strip()

        if wallet_type in ("proxy", "safe", "gnosis"):
            self._wallet_type = "PROXY"
            self._eoa_warning = False
            logger.info("%s wallet detected — auto-claim enabled.", wallet_type.upper())
        elif wallet_type == "eoa":
            self._wallet_type = "EOA"
            self._eoa_warning = True
            logger.warning("EOA wallet detected — auto-claim NOT supported.")
        else:
            self._wallet_type = "EOA"
            self._eoa_warning = True
            logger.warning("Unknown wallet type '%s' — defaulting to EOA.", wallet_type)

        return self._wallet_type

    async def claim(self, window_id: str, order_result: OrderResult) -> ClaimResult:
        """Attempt to claim winning shares after resolution."""
        if self._cfg.PAPER_TRADING_MODE:
            return await self._simulate_claim(window_id, order_result)

        if order_result.status not in ("FILLED", "PARTIAL"):
            return ClaimResult("NOT_APPLICABLE", window_id, 0.0, "N-A", None, 0, False)

        if self._eoa_warning:
            logger.warning("MANUAL_CLAIM_REQUIRED for window %s (EOA wallet)", window_id)
            payout = order_result.shares_bought or 0.0
            self._unclaimed_balance += payout
            if self._unclaimed_since <= 0:
                self._unclaimed_since = time.time()
            await self._log_event("CLAIM_PENDING_MANUAL", window_id, "EOA wallet manual claim required")
            return ClaimResult("PENDING_MANUAL", window_id, payout, "MANUAL", None, 0, False)

        won = await self._wait_for_resolution(window_id)
        if not won:
            return ClaimResult("LOSS", window_id, 0.0, "N-A", None, 0, False)

        payout = order_result.shares_bought or 0.0
        self._unclaimed_balance += payout
        if self._unclaimed_since <= 0:
            self._unclaimed_since = time.time()

        max_retries = self._cfg.CLAIM_RETRY_MAX
        base_interval = self._cfg.CLAIM_RETRY_INTERVAL_SEC

        for attempt in range(max_retries):
            try:
                success = await self._send_redeem(window_id)
                if success:
                    self._unclaimed_balance = max(0, self._unclaimed_balance - payout)
                    if self._unclaimed_balance <= 0:
                        self._unclaimed_since = 0.0
                    logger.info("Auto-claim successful for %s (attempt %d)", window_id, attempt + 1)
                    await self._log_event("CLAIM_SUCCESS", window_id, f"Auto-claimed ${payout:.4f}")
                    return ClaimResult("AUTO", window_id, payout, "AUTO", time.time(), attempt, False)
            except Exception as exc:
                logger.warning("Claim retry %d/%d error for %s: %s", attempt + 1, max_retries, window_id, exc)

            if attempt < max_retries - 1:
                delay = min(base_interval * (2 ** attempt), 120)
                await asyncio.sleep(delay)

        logger.error("All claim retries failed for %s", window_id)
        return ClaimResult("PENDING_MANUAL", window_id, payout, "PENDING", None, max_retries, False)

    async def _simulate_claim(self, window_id: str, order_result: OrderResult) -> ClaimResult:
        """Simulate claim for paper trading mode dengan mengecek hasil asli market."""
        logger.info("[PAPER] Menunggu resolusi market untuk %s...", window_id)
        
        # 1. Tunggu hasil asli dari API Polymarket
        up_won = await self._wait_for_resolution(window_id)
        
        # 2. Tentukan apakah trade ini menang berdasarkan side-nya
        # OrderResult side bisa "UP", "DOWN", "YES", atau "NO"
        side = (order_result.side or "").upper()
        if side in ("UP", "YES"):
            won = up_won
        else:
            won = not up_won
            
        # 3. Hitung payout ($1.00 per share jika menang, 0 jika kalah)
        payout = order_result.shares_bought if won else 0.0
        status = "PAPER" if won else "LOSS"
        
        logger.info("[PAPER] Hasil %s: %s | Payout: $%.2f | Cost: $%.2f", 
                    window_id, "WIN" if won else "LOSS", payout, order_result.cost_usd)
        
        return ClaimResult(status, window_id, payout, "PAPER", time.time(), 0, True)

    async def _wait_for_resolution(self, window_id: str) -> bool:
        """Poll for on-chain resolution. Returns True if we won."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))

        max_polls = 180
        for poll in range(max_polls):
            try:
                url = f"https://clob.polymarket.com/markets/{window_id}"
                async with self._session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("resolved", False):
                            return data.get("winning_outcome", "").upper() in ("YES", "UP")
            except Exception as exc:
                logger.debug("Resolution poll error: %s", exc)
            await asyncio.sleep(5.0)
        return False

    async def _send_redeem(self, window_id: str) -> bool:
        """Send redeem request via Polymarket Gasless Relayer."""
        if self._clob_client is None:
            raise RuntimeError("CLOB client belum diinisialisasi")
        try:
            positions = await asyncio.wait_for(
                asyncio.to_thread(self._clob_client.get_positions), timeout=30
            )
            winning = [
                p for p in positions
                if getattr(p, "market_id", "") == window_id and float(getattr(p, "size", 0)) > 0
            ]
            if not winning:
                return False
            position_ids = [getattr(p, "position_id", "") for p in winning]
            await asyncio.wait_for(
                asyncio.to_thread(self._clob_client.redeem_positions, position_ids), timeout=30
            )
            return True
        except Exception as exc:
            logger.warning("Redeem failed: %s", exc)
            return False

    async def stop(self) -> None:
        """Close HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            logger.info("ClaimManager session closed.")

    async def _log_event(self, event_type: str, window_id: str, details: str) -> None:
        """Log event via injected logger."""
        if self._event_logger is not None and hasattr(self._event_logger, "log_event"):
            try:
                from logs.audit_logger import EventRecord
                record = EventRecord(
                    time.time(), event_type, window_id, "claim_manager", "", details, None, "{}"
                )
                await self._event_logger.log_event(record)
            except Exception:
                pass
