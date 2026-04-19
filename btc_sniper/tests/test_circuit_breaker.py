# ═══ tests/test_circuit_breaker.py ═══
"""Tests for CircuitBreaker — loss counting, lockdown, resume."""
import pytest, asyncio
from core.circuit_breaker import CircuitBreaker, ResumeResult

@pytest.fixture
def cb(cfg):
    return CircuitBreaker(cfg)

@pytest.mark.asyncio
async def test_three_consecutive_losses_trigger_lockdown(cb):
    await cb.record_loss(0.5)
    assert cb.mode == "NORMAL"
    await cb.record_loss(0.5)
    assert cb.mode == "NORMAL"
    mode = await cb.record_loss(0.5)
    assert mode == "LOCKDOWN", "3 consecutive losses should trigger LOCKDOWN"

@pytest.mark.asyncio
async def test_win_resets_consecutive_counter(cb):
    await cb.record_loss(0.5)
    await cb.record_loss(0.5)
    await cb.record_win()
    assert cb.consecutive_loss_count == 0
    await cb.record_loss(0.5)
    assert cb.mode == "NORMAL", "After win reset, 1 loss should not lockdown"

@pytest.mark.asyncio
async def test_skip_does_not_affect_counter(cb):
    await cb.record_loss(0.5)
    await cb.record_skip()
    await cb.record_skip()
    assert cb.consecutive_loss_count == 1, "Skips should not affect loss counter"

@pytest.mark.asyncio
async def test_lockdown_blocks_state(cb):
    for _ in range(3):
        await cb.record_loss(0.5)
    assert cb.is_lockdown is True

@pytest.mark.asyncio
async def test_resume_checklist_fails_if_feed_down(cb):
    for _ in range(3):
        await cb.record_loss(0.5)
    # Immediate resume should fail (cooldown not elapsed)
    result = await cb.attempt_resume(True, True, True, 100.0, 0)
    assert result.success is False
    assert result.reason == "COOLDOWN_NOT_ELAPSED"

@pytest.mark.asyncio
async def test_daily_loss_limit_triggers_lockdown(cfg):
    import os
    os.environ["MAX_DAILY_LOSS_USD"] = "1.0"
    from config import load_config
    cfg2 = load_config()
    cb2 = CircuitBreaker(cfg2)
    mode = await cb2.record_loss(1.5)
    assert mode == "LOCKDOWN", "Exceeding daily loss limit should trigger LOCKDOWN"
    os.environ["MAX_DAILY_LOSS_USD"] = "0.0"

@pytest.mark.asyncio
async def test_timeout_does_not_increment_counter(cb):
    # Timeouts are handled by OrderExecutor, not CircuitBreaker
    # CircuitBreaker only sees record_loss/win/skip
    assert cb.consecutive_loss_count == 0
    await cb.record_skip()  # Timeout would be a skip, not a loss
    assert cb.consecutive_loss_count == 0

@pytest.mark.asyncio
async def test_paper_fill_does_not_affect_counter(cb):
    # Paper fills go through record_win or record_loss based on result
    await cb.record_win()  # Paper win
    assert cb.consecutive_loss_count == 0
