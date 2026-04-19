# ═══ FILE: btc_sniper/core/__init__.py ═══
"""Core module — engine, signal processing, order execution, claim management, circuit breaker."""

from core.engine import BotEngine, get_current_window_slug, get_time_remaining
from core.signal_processor import SignalProcessor
from core.order_executor import OrderExecutor, OrderResult
from core.claim_manager import ClaimManager, ClaimResult
from core.circuit_breaker import CircuitBreaker

__all__ = [
    "BotEngine",
    "get_current_window_slug",
    "get_time_remaining",
    "SignalProcessor",
    "OrderExecutor",
    "OrderResult",
    "ClaimManager",
    "ClaimResult",
    "CircuitBreaker",
]
