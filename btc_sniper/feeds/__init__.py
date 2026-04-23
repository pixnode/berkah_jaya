# ═══ FILE: btc_sniper/feeds/__init__.py ═══
"""Feed module — WebSocket feeds and event dataclasses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class TradeEvent:
    """A single trade from Hyperliquid trade feed."""
    timestamp: float
    price: float
    size: float
    side: Literal["buy", "sell"]


@dataclass(frozen=True, slots=True)
class PriceEvent:
    """Latest BTC price update from Hyperliquid."""
    timestamp: float
    price: float


@dataclass(frozen=True, slots=True)
class OrderBookEvent:
    """Order book snapshot from Polymarket CLOB."""
    timestamp: float
    up_ask: float
    up_bid: float
    down_ask: float
    down_bid: float
    spread_pct: float
    up_ask_depth_usdc: float
    down_ask_depth_usdc: float


@dataclass(frozen=True, slots=True)
class OddsEvent:
    """Odds update from Polymarket CLOB."""
    timestamp: float
    up_odds: float
    down_odds: float


@dataclass(frozen=True, slots=True)
class ChainlinkEvent:
    """Chainlink BTC/USD price update from Polygon RPC."""
    timestamp: float
    price: float
    updated_at: float
    age_seconds: int
    is_stale: bool


@dataclass(frozen=True, slots=True)
class DataStaleEvent:
    """Emitted when a data source has gone stale (no updates)."""
    timestamp: float
    source: Literal["hyperliquid", "polymarket", "chainlink"]


__all__ = [
    "TradeEvent",
    "PriceEvent",
    "OrderBookEvent",
    "OddsEvent",
    "ChainlinkEvent",
    "DataStaleEvent",
]
