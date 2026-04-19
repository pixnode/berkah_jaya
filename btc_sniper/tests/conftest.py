# ═══ tests/conftest.py ═══
"""Shared fixtures for all tests."""
import os, sys, pytest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.update({
    "POLYMARKET_PRIVATE_KEY": "0xTEST_KEY_DO_NOT_USE",
    "POLYMARKET_PROXY_WALLET": "0xTEST_WALLET",
    "POLYMARKET_API_KEY": "test-api-key",
    "POLYGON_RPC_URL": "https://polygon-rpc.com",
    "PAPER_TRADING_MODE": "True",
    "OUTPUT_DIR": "./test_output",
    "BOT_VERSION": "2.3",
})

from config import BotConfig, load_config

@pytest.fixture
def cfg() -> BotConfig:
    return load_config()

@pytest.fixture
def signal_state():
    from core.signal_processor import SignalState
    return SignalState(
        timestamp=1000.0, current_hl_price=84200.0, strike_price=84000.0,
        gap=200.0, gap_direction="UP", gap_threshold=45.0, vol_regime="NORM",
        atr=100.0, cvd_60s=1500000.0, cvd_threshold=1050000.0,
        cvd_threshold_pct=25.0, avg_volume_per_min=4200000.0,
        cvd_aligned=True, velocity_1_5s=20.0, velocity_pass=True,
    )

@pytest.fixture
def book_event():
    from feeds import OrderBookEvent
    return OrderBookEvent(timestamp=1000.0, up_ask=0.70, up_bid=0.68, down_ask=0.32, down_bid=0.30, spread_pct=1.5)

@pytest.fixture
def odds_event():
    from feeds import OddsEvent
    return OddsEvent(timestamp=1000.0, up_odds=0.70, down_odds=0.30)
