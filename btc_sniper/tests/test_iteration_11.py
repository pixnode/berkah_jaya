# ═══ FILE: btc_sniper/tests/test_iteration_11.py ═══
import asyncio
import unittest
import time
from unittest.mock import MagicMock
from core.signal_processor import SignalProcessor, SignalState
from feeds import TradeEvent, PriceEvent
from config import BotConfig

class TestIteration11(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cfg = MagicMock(spec=BotConfig)
        self.cfg.CVD_THRESHOLD_PCT = 25.0
        self.cfg.CVD_VOLUME_WINDOW_MINUTES = 30
        self.cfg.ATR_LOOKBACK_CANDLES = 12
        self.cfg.VELOCITY_WINDOW_SECONDS = 1.5
        self.cfg.VELOCITY_MIN_DELTA = 15.0
        self.cfg.VELOCITY_ENABLED = True
        self.cfg.ATR_LOW_THRESHOLD = 50.0
        self.cfg.ATR_HIGH_THRESHOLD = 150.0
        self.cfg.GAP_THRESHOLD_DEFAULT = 45.0
        self.cfg.GAP_THRESHOLD_LOW_VOL = 60.0
        self.cfg.GAP_THRESHOLD_HIGH_VOL = 35.0
        self.cfg.CVD_CALC_INTERVAL_MS = 100
        self.cfg.MIN_TRADE_SIZE_USD = 0.0
        self.sp = SignalProcessor(self.cfg)

    def test_cvd_running_total_matches_sum(self):
        """Verify _cvd_running always matches the manual sum of deque."""
        # Add some trades
        now = time.time()
        trades = [
            TradeEvent(now, 100.0, 1.0, "buy"),
            TradeEvent(now + 1, 101.0, 0.5, "sell"),
            TradeEvent(now + 2, 102.0, 2.0, "buy"),
        ]
        
        for t in trades:
            self.sp._handle_trade_event(t)
            
        # Check running total
        manual_sum = sum(entry[1] for entry in self.sp._cvd_deque)
        self.assertEqual(self.sp._cvd_running, manual_sum)
        self.assertEqual(self.sp._cvd_running, 1.0 - 0.5 + 2.0)

        # Expire some trades manually
        self.sp._cvd_deque.appendleft((now - 100, 50.0))
        self.sp._cvd_running += 50.0
        
        self.sp._recalculate_cvd_state() # This should purge the old entry
        
        manual_sum_after = sum(entry[1] for entry in self.sp._cvd_deque)
        self.assertEqual(self.sp._cvd_running, manual_sum_after)

    async def test_price_event_never_dropped(self):
        """Simulate queue full and verify PriceEvent is handled via wait."""
        from feeds.hyperliquid_ws import HyperliquidFeed
        
        queue = asyncio.Queue(maxsize=1)
        feed = HyperliquidFeed(self.cfg)
        feed._queue = queue
        feed._running = True
        feed._connected = True
        
        # Fill queue
        queue.put_nowait("dummy")
        
        # Try to emit PriceEvent — should not drop immediately, should block/wait
        price_event = PriceEvent(time.time(), 80000.0)
        
        # We use a task to send because it might block
        send_task = asyncio.create_task(feed._emit(price_event))
        
        # Wait a tiny bit to see if it's blocked
        await asyncio.sleep(0.05)
        self.assertFalse(send_task.done())
        
        # Empty queue
        queue.get_nowait()
        queue.task_done()
        
        # Now it should complete
        await asyncio.wait_for(send_task, timeout=0.2)
        self.assertTrue(send_task.done())
        self.assertEqual(queue.get_nowait(), price_event)

    def test_trade_noise_filter(self):
        """Verify small trades are ignored if MIN_TRADE_SIZE_USD > 0."""
        self.cfg.MIN_TRADE_SIZE_USD = 1000.0
        
        # Small trade: 0.01 BTC * 50k = $500
        small_trade = TradeEvent(time.time(), 50000.0, 0.01, "buy")
        # Large trade: 0.1 BTC * 50k = $5000
        large_trade = TradeEvent(time.time(), 50000.0, 0.1, "buy")
        
        self.sp._handle_trade_event(small_trade)
        self.assertEqual(self.sp._cvd_running, 0.0)
        
        self.sp._handle_trade_event(large_trade)
        self.assertEqual(self.sp._cvd_running, 0.1)

if __name__ == "__main__":
    unittest.main()
