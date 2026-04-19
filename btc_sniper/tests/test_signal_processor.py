# ═══ tests/test_signal_processor.py ═══
"""Tests for SignalProcessor — CVD, ATR, velocity, gap."""
import collections, time, pytest
from core.signal_processor import SignalProcessor, SignalState, Candle
from feeds import TradeEvent, PriceEvent
from config import load_config

@pytest.fixture
def sp(cfg):
    return SignalProcessor(cfg)

def test_cvd_rolling_window_drops_old_entries(sp):
    now = time.time()
    sp._state.gap_direction = "UP"
    sp._handle_trade_event(TradeEvent(now - 100, 84000, 10, "buy"))  # old
    sp._handle_trade_event(TradeEvent(now - 30, 84000, 20, "buy"))
    sp._handle_trade_event(TradeEvent(now, 84000, 30, "buy"))
    # Old entry (100s ago) should be dropped from 60s window
    assert len(sp._cvd_deque) == 2, "Entry >60s old should be purged"

def test_cvd_threshold_scales_with_volume(sp):
    now = time.time()
    sp._state.gap_direction = "UP"
    for i in range(100):
        sp._handle_trade_event(TradeEvent(now - 50 + i * 0.5, 84000, 100, "buy"))
    assert sp._state.cvd_threshold > 0, "CVD threshold should scale with volume"
    assert sp._state.avg_volume_per_min > 0, "Avg volume should be > 0"

def test_atr_regime_detection_low(sp):
    sp._state.atr = 30.0  # Below ATR_LOW_THRESHOLD=50
    event = PriceEvent(time.time(), 84000.0)
    sp._state.strike_price = 83900.0
    sp._handle_price_event(event)
    assert sp._state.vol_regime == "LOW"
    assert sp._state.gap_threshold == sp._cfg.GAP_THRESHOLD_LOW_VOL

def test_atr_regime_detection_high(sp):
    sp._state.atr = 200.0  # Above ATR_HIGH_THRESHOLD=150
    event = PriceEvent(time.time(), 84000.0)
    sp._state.strike_price = 83900.0
    sp._handle_price_event(event)
    assert sp._state.vol_regime == "HIGH"
    assert sp._state.gap_threshold == sp._cfg.GAP_THRESHOLD_HIGH_VOL

def test_velocity_calculation_correct_delta(sp):
    now = time.time()
    sp._state.strike_price = 84000.0
    sp._handle_price_event(PriceEvent(now - 1.0, 84000.0))
    sp._handle_price_event(PriceEvent(now, 84020.0))
    assert sp._state.velocity_1_5s == pytest.approx(20.0, abs=1.0)

def test_gap_threshold_changes_with_regime(sp):
    sp._state.strike_price = 84000.0
    sp._state.atr = 30.0
    sp._handle_price_event(PriceEvent(time.time(), 84100.0))
    assert sp._state.gap_threshold == 60.0  # LOW vol

    sp._state.atr = 100.0
    sp._handle_price_event(PriceEvent(time.time(), 84100.0))
    assert sp._state.gap_threshold == 45.0  # NORMAL

    sp._state.atr = 200.0
    sp._handle_price_event(PriceEvent(time.time(), 84100.0))
    assert sp._state.gap_threshold == 35.0  # HIGH

def test_reset_cvd_clears_accumulator(sp):
    now = time.time()
    sp._state.gap_direction = "UP"
    sp._handle_trade_event(TradeEvent(now, 84000, 100, "buy"))
    assert sp._state.cvd_60s > 0
    sp.reset_cvd()
    assert sp._state.cvd_60s == 0.0
    assert sp._state.cvd_aligned is False
    assert len(sp._cvd_deque) == 0
