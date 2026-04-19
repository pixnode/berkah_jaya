# ═══ FILE: btc_sniper/core/engine.py ═══
"""BotEngine — main orchestrator. Startup, main loop, shutdown."""

from __future__ import annotations
import asyncio, json, logging, time, os
from datetime import datetime, timezone
from typing import Optional, Set
from config import BotConfig

logger = logging.getLogger("btc_sniper.core.engine")

def get_current_window_slug() -> str:
    now = int(time.time()); ws = now - (now % 300)
    return f"btc-updown-5m-{ws}"

def get_time_remaining() -> int:
    now = int(time.time()); ws = now - (now % 300)
    return (ws + 300) - now


class BotEngine:
    """Core trading engine coordinating all feeds, processors, and safety modules."""

    def __init__(self, cfg: BotConfig) -> None:
        self._cfg = cfg
        self._queue = asyncio.Queue(maxsize=cfg.QUEUE_HL_MAXSIZE)
        self._shutdown = asyncio.Event()
        self._tasks: Set[asyncio.Task] = set()
        self._session_id = f"SES-{int(time.time())}"
        self._order_sent = False
        self._stopping = False  # Flag to prevent redundant stop calls

        # State for monitoring
        self._engine_state = {"window_id": "—", "t_remaining": 0, "bot_mode": "INIT"}

        # Components
        from logs.audit_logger import AuditLogger
        from feeds.hyperliquid_ws import HyperliquidFeed
        from feeds.polymarket_ws import PolymarketFeed
        from feeds.chainlink_feed import ChainlinkFeed
        from core.signal_processor import SignalProcessor
        from core.claim_manager import ClaimManager
        from core.circuit_breaker import CircuitBreaker
        from risk.safety_monitor import SafetyMonitor
        from cli.dashboard import Dashboard
        from core.order_executor import OrderExecutor

        # Ensure output directory exists
        os.makedirs(cfg.OUTPUT_DIR, exist_ok=True)

        self._audit_logger = AuditLogger(cfg)
        self._hl_feed = HyperliquidFeed(cfg, self._audit_logger)
        self._poly_feed = PolymarketFeed(cfg, self._audit_logger)
        self._chainlink_feed = ChainlinkFeed(cfg, self._audit_logger)
        self._signal_processor = SignalProcessor(cfg, self._audit_logger)
        self._order_executor = OrderExecutor(cfg, self._audit_logger)
        self._claim_manager = ClaimManager(cfg, self._audit_logger)
        self._circuit_breaker = CircuitBreaker(cfg, self._audit_logger)
        self._safety_monitor = SafetyMonitor(cfg, self._audit_logger)
        self._dashboard = Dashboard(cfg)

    async def start(self) -> None:
        """Initialize all feeds and start the main event loop."""
        from logs.audit_logger import EventRecord
        
        await self._claim_manager.check_wallet_type()
        self._claim_manager.set_chainlink_feed(self._chainlink_feed)
        await self._claim_manager._init_clob_client()
        
        if not self._cfg.PAPER_TRADING_MODE:
            import aiohttp
            logger.info("Performing live mode startup health checks...")
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"{self._cfg.CLOB_HOST}/auth/api-key", timeout=5) as resp:
                        pass
                    async with session.get(f"{self._cfg.RELAYER_URL}/health", timeout=5) as resp:
                        if resp.status == 200:
                            logger.info("CLOB connected ✓  Relayer: OK")
            except Exception as e:
                raise RuntimeError(f"CLOB API connection failed — {e}")

        self._safety_monitor.set_components(
            self._hl_feed, self._poly_feed, self._chainlink_feed,
            self._circuit_breaker, self._signal_processor,
        )
        self._safety_monitor.set_engine_state(self._engine_state)

        # Launch tasks
        coros = [
            self._hl_feed.start(self._queue),
            self._poly_feed.start(self._queue),
            self._chainlink_feed.start_polling(self._queue),
            self._signal_processor.run(self._queue),
            self._safety_monitor.run(),
            self._dashboard.run(),
            self._ui_exporter_loop(),
            self._periodic_state_flush(),
            self._periodic_snapshot_writer(),
        ]
        
        for coro in coros:
            t = asyncio.create_task(coro)
            self._tasks.add(t)
            t.add_done_callback(self._tasks.discard)

        await self._audit_logger.log_event(EventRecord(time.time(),"STARTUP","","engine","","All tasks launched",None,"{}"))
        logger.info("═══ BTC SNIPER v%s STARTED ═══", self._cfg.BOT_VERSION)
        
        try:
            await self.main_loop()
        finally:
            await self.stop()

    async def main_loop(self) -> None:
        """Primary state machine coordinating window-based trading."""
        from logs.audit_logger import EventRecord, SkipRecord, TradeRecord
        from feeds import ChainlinkEvent
        
        while not self._shutdown.is_set():
            slug = get_current_window_slug()
            t_rem = get_time_remaining()
            
            # Update state for dashboard
            self._engine_state.update({"window_id": slug, "t_remaining": t_rem})
            self._dashboard.state.window_id = slug
            self._dashboard.state.time_remaining = t_rem
            
            # Mode selection
            if t_rem > self._cfg.WINDOW_ARMED_T_SEC:
                mode = "INIT"
            elif t_rem > self._cfg.WINDOW_EXECUTE_T_START:
                mode = "ARMED"
            elif t_rem >= self._cfg.WINDOW_EXECUTE_T_END:
                mode = "EXECUTE"
            else:
                mode = "SETTLE"

            self._engine_state["bot_mode"] = mode
            self._dashboard.state.bot_mode = mode

            # Reset order flag on new window
            if t_rem > 295: self._order_sent = False

            # Update dashboard state from components
            self._sync_dashboard()

            # Execution logic
            if mode == "EXECUTE" and not self._order_sent and not self._circuit_breaker.is_lockdown:
                await self._handle_execution(slug)

            if self._dashboard.quit_requested:
                self._shutdown.set()

            await asyncio.sleep(0.5)

    async def _handle_execution(self, slug: str) -> None:
        """Evaluate gates and execute order if all pass."""
        from risk.gates import evaluate_all_gates
        from logs.audit_logger import TradeRecord, SkipRecord
        
        gate_res = evaluate_all_gates(
            self._cfg, self._signal_processor.state, self._dashboard.state
        )
        
        if gate_res.all_passed:
            self._order_sent = True
            logger.info("🎯 TARGET ACQUIRED: %s at odds %.3f", gate_res.side, gate_res.target_ask)
            
            order_res = await self._order_executor.execute(gate_res, slug)
            
            if order_res.status in ("FILLED", "PARTIAL", "PAPER_FILL"):
                # Log trade
                trade = TradeRecord(
                    time.time(), slug, order_res.side or "", order_res.entry_odds or 0,
                    order_res.shares_bought or 0, order_res.cost_usd or 0,
                    order_res.status, order_res.tx_hash or "", 0, 0, ""
                )
                await self._audit_logger.log_trade(trade)
                
                # Update dashboard history
                from cli.dashboard import TradeHistoryEntry
                entry = TradeHistoryEntry(
                    number=len(self._dashboard.state.trade_history)+1,
                    time_str=datetime.now().strftime("%H:%M:%S"),
                    result="OPEN", side=order_res.side or "",
                    odds=order_res.entry_odds or 0, gap=self._signal_processor.state.gap,
                    cvd_pct=0, velocity=self._signal_processor.state.velocity,
                    spread=0, slippage=order_res.slippage_delta, claim="WAIT"
                )
                self._dashboard.state.trade_history.append(entry)
                
                # Start claim task
                asyncio.create_task(self._claim_and_finalize(slug, order_res, entry))
            else:
                logger.warning("Order failed: %s - %s", order_res.status, order_res.error_msg)
        else:
            # Skip record
            skip = SkipRecord(time.time(), slug, gate_res.failed_gate_id or 0, gate_res.details)
            await self._audit_logger.log_skip(skip)

    async def _claim_and_finalize(self, slug, order_res, history_entry):
        """Wait for resolution and claim."""
        claim_res = await self._claim_manager.claim(slug, order_res)
        history_entry.result = claim_res.status
        history_entry.claim = "DONE"
        # Update dashboard P&L
        if claim_res.status in ("AUTO", "PAPER"):
            self._dashboard.state.wins += 1
            self._dashboard.state.total_pnl += (claim_res.payout_usd - (order_res.cost_usd or 0))
        elif claim_res.status == "LOSS":
            self._dashboard.state.losses += 1
            self._dashboard.state.total_pnl -= (order_res.cost_usd or 0)

    def _sync_dashboard(self):
        """Sync component states to dashboard."""
        ds = self._dashboard.state
        ss = self._signal_processor.state
        
        ds.hl_price = ss.hl_price
        ds.strike_price = ss.strike_price
        ds.gap = ss.gap
        ds.gap_direction = ss.gap_direction
        ds.gap_threshold = ss.gap_threshold
        ds.velocity = ss.velocity
        ds.atr = ss.atr
        ds.vol_regime = ss.vol_regime
        
        ds.buy_volume = ss.buy_volume
        ds.sell_volume = ss.sell_volume
        ds.cvd_net = ss.cvd_net
        ds.avg_vol_per_min = ss.avg_vol_per_min
        ds.cvd_threshold = ss.cvd_threshold
        ds.cvd_aligned = ss.cvd_aligned
        ds.cvd_direction = ss.cvd_direction
        
        if ss.latest_odds:
            ds.up_ask = ss.latest_odds.up_odds
            ds.up_bid = ss.latest_odds.up_odds - 0.01 # Mock
            ds.down_ask = ss.latest_odds.down_odds
            ds.down_bid = ss.latest_odds.down_odds - 0.01
            
        ds.is_lockdown = self._circuit_breaker.is_lockdown
        ds.lockdown_reason = self._circuit_breaker.lockdown_reason

    async def stop(self) -> None:
        """Graceful shutdown of all components."""
        if self._stopping: return
        self._stopping = True
        
        logger.info("Stopping engine...")
        self._shutdown.set()
        
        # Stop components with sessions
        await self._hl_feed.stop()
        await self._poly_feed.stop()
        await self._chainlink_feed.stop()
        self._safety_monitor.stop()
        self._dashboard.stop()
        await self._order_executor.stop()
        await self._claim_manager.stop()
        
        # Cancel all tasks
        for t in self._tasks:
            t.cancel()
        
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        
        if hasattr(self, "_audit_logger") and self._audit_logger:
            if hasattr(self._audit_logger, "close"):
                await self._audit_logger.close()
                
        logger.info("═══ SHUTDOWN COMPLETE ═══")

    async def _ui_exporter_loop(self) -> None:
        """Saves a JSON snapshot of the dashboard state for external viewers."""
        import dataclasses
        ui_file = os.path.join(self._cfg.OUTPUT_DIR, "dashboard_ui.json")
        while not self._shutdown.is_set():
            try:
                def d_to_dict(obj):
                    if dataclasses.is_dataclass(obj):
                        return {f.name: d_to_dict(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
                    elif isinstance(obj, list): return [d_to_dict(i) for i in obj]
                    elif isinstance(obj, dict): return {k: d_to_dict(v) for k, v in obj.items()}
                    else: return obj
                state_dict = d_to_dict(self._dashboard.state)
                with open(ui_file, "w") as f: json.dump(state_dict, f)
            except Exception: pass
            await asyncio.sleep(1.0)

    async def _periodic_state_flush(self) -> None:
        while not self._shutdown.is_set():
            await asyncio.sleep(self._cfg.LOG_FLUSH_INTERVAL_SEC)
            if self._audit_logger: await self._audit_logger.flush_state(dict(self._engine_state))

    async def _periodic_snapshot_writer(self) -> None:
        while not self._shutdown.is_set():
            await asyncio.sleep(self._cfg.STATE_SNAPSHOT_INTERVAL_SEC)
            await self._audit_logger.save_snapshot(dict(self._engine_state))
