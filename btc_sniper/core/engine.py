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
        self._order_sent_up = False
        self._order_sent_down = False
        self._stopping = False

        # Ensure output directory exists
        os.makedirs(cfg.OUTPUT_DIR, exist_ok=True)

        # State for monitoring
        self._engine_state = {"window_id": "—", "t_remaining": 0, "bot_mode": "INIT"}
        self._last_subscribed_slug: Optional[str] = None

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
            
            if slug != self._last_subscribed_slug:
                # Window baru — subscribe ulang
                if self._poly_feed.is_connected:
                    await self._poly_feed.subscribe(slug)
                self._last_subscribed_slug = slug
                self._order_sent = False
                self._order_sent_up = False
                self._order_sent_down = False
                if hasattr(self._signal_processor, "reset_cvd"):
                    self._signal_processor.reset_cvd()
                logger.info(f"New window: {slug}")
            
            # Update state for dashboard
            self._engine_state.update({"window_id": slug, "t_remaining": t_rem})
            self._dashboard.state.window_id = slug
            self._dashboard.state.time_remaining = t_rem
            
            # Mode selection (PRD v2.3 dynamic timing)
            if t_rem > self._cfg.GOLDEN_WINDOW_START:
                mode = "INIT"
            elif t_rem >= self._cfg.GOLDEN_WINDOW_END:
                mode = "EXECUTE"
            else:
                mode = "SETTLE"

            # Dashboard ARMED visual if within 10s of window start
            if mode == "INIT" and t_rem <= self._cfg.GOLDEN_WINDOW_START + 10:
                self._dashboard.state.bot_mode = "ARMED"
            else:
                self._dashboard.state.bot_mode = mode

            self._engine_state["bot_mode"] = mode

            if t_rem > 295:
                self._order_sent = False
                self._order_sent_up = False
                self._order_sent_down = False

            # Update dashboard state from components
            self._sync_dashboard()

            # Lockdown Auto-Resume logic (PRD v2.3 compliant Section 06)
            if self._circuit_breaker.is_lockdown:
                # Try resume every 5 seconds or when a new window starts
                if int(t_rem) % 5 == 0 or t_rem > 298:
                    resume_res = await self._circuit_breaker.attempt_resume(
                        hl_feed_connected=self._hl_feed.is_connected,
                        poly_feed_connected=self._poly_feed.is_connected,
                        chainlink_fresh=self._chainlink_feed.is_connected,
                        wallet_balance=self._dashboard.state.balance,
                        unclaimed_since_sec=self._claim_manager.unclaimed_since,
                        signal_processor=self._signal_processor
                    )
                    if resume_res.success:
                        logger.info("═══ LOCKDOWN RESUMED ═══ All health checks passed.")
                    else:
                        # Log why resume was denied if it's not just a cooldown
                        if resume_res.reason != "COOLDOWN_NOT_ELAPSED":
                            logger.debug("Resume denied: %s | Failed checks: %s", resume_res.reason, resume_res.failed_checks)

            # Execution logic
            if mode == "EXECUTE" and not self._circuit_breaker.is_lockdown:
                if self._cfg.HEDGE_MODE_ENABLED:
                    await self._handle_hedge_execution(slug)
                elif not self._order_sent:
                    await self._handle_execution(slug)
                
            await asyncio.sleep(0.1)

            if self._dashboard.quit_requested:
                self._shutdown.set()

            await asyncio.sleep(0.5)

    async def _handle_execution(self, slug: str) -> None:
        """Evaluate gates and execute order if all pass."""
        from risk.gates import GateEvaluator
        from logs.audit_logger import TradeRecord, SkipRecord
        
        evaluator = GateEvaluator(self._cfg)
        t_rem = get_time_remaining()
        gate_res = evaluator.evaluate(
            signal=self._signal_processor.state,
            book=self._signal_processor.latest_book,
            odds=self._signal_processor.latest_odds,
            time_remaining=t_rem,
            order_sent=self._order_sent,
        )
        
        if gate_res.all_pass:
            self._order_sent = True
            logger.info("🎯 TARGET ACQUIRED: %s at odds %.3f", gate_res.side, gate_res.target_ask)
            
            order_res = await self._order_executor.execute(gate_res, slug)
            
            ss = self._signal_processor.state
            latest_odds = self._signal_processor.latest_odds
            
            if order_res.status in ("FILLED", "PARTIAL", "PAPER_FILL"):
                trade = TradeRecord(
                    session_id=self._session_id,
                    window_id=slug,
                    timestamp_trigger=datetime.now(timezone.utc).isoformat(),
                    timestamp_order_sent=datetime.now(timezone.utc).isoformat(),
                    timestamp_confirmed=datetime.now(timezone.utc).isoformat(),
                    side=order_res.side or gate_res.side or "",
                    strike_price=gate_res.target_ask,
                    hl_price_at_trigger=ss.hl_price,
                    gap_value=ss.gap,
                    gap_threshold_used=ss.gap_threshold,
                    atr_regime=ss.vol_regime,
                    cvd_60s=ss.cvd_60s,
                    cvd_threshold_used=ss.cvd_threshold,
                    cvd_threshold_pct=self._cfg.CVD_MIN_PCT if hasattr(self._cfg, "CVD_MIN_PCT") else 0.0,
                    velocity=ss.velocity_1_5s,
                    entry_odds=order_res.entry_odds or gate_res.target_ask,
                    odds_in_sweet_spot=(self._cfg.ODDS_SWEET_SPOT_LOW <= (order_res.entry_odds or gate_res.target_ask) <= self._cfg.ODDS_SWEET_SPOT_HIGH),
                    spread_pct=0.0,
                    expected_odds=gate_res.expected_odds,
                    mispricing_delta=0.0,
                    slippage_delta=order_res.slippage_delta,
                    slippage_threshold_used=self._cfg.MAX_SLIPPAGE_PCT if hasattr(self._cfg, "MAX_SLIPPAGE_PCT") else 0.0,
                    blockchain_latency_ms=0,
                    shares_bought=order_res.shares_bought or 0.0,
                    cost_usdc=order_res.cost_usd or 0.0,
                    result=order_res.status,
                    resolution_price=None,
                    payout_usdc=None,
                    pnl_usdc=None,
                    claim_method=None,
                    claim_timestamp=None,
                    mode="A",
                    bot_version=getattr(self._cfg, "BOT_VERSION", "2.3")
                )
                await self._audit_logger.log_trade(trade)
                
                from cli.dashboard import TradeHistoryEntry
                entry = TradeHistoryEntry(
                    number=len(self._dashboard.state.trade_history)+1,
                    time_str=datetime.now().strftime("%H:%M:%S"),
                    result="OPEN", side=order_res.side or "",
                    odds=order_res.entry_odds or 0, gap=self._signal_processor.state.gap,
                    cvd_pct=0, velocity=self._signal_processor.state.velocity_1_5s,
                    spread=0, slippage=order_res.slippage_delta, claim="WAIT"
                )
                self._dashboard.state.trade_history.append(entry)
                
                asyncio.create_task(self._claim_and_finalize(slug, order_res, entry))
            else:
                logger.warning("Order failed: %s - %s", order_res.status, order_res.error_msg)
        else:
            ss = self._signal_processor.state
            latest_odds = self._signal_processor.latest_odds
            
            skip = SkipRecord(
                session_id=self._session_id,
                window_id=slug,
                timestamp=datetime.now(timezone.utc).isoformat(),
                skip_reason=gate_res.fail_reason or "",
                skip_stage=f"Gate {gate_res.failed_gate}" if gate_res.failed_gate else "Unknown",
                gap_value=ss.gap,
                gap_threshold=ss.gap_threshold,
                gap_gate_pass=gate_res.gate_statuses.get(1, False),
                cvd_value=ss.cvd_60s,
                cvd_gate_pass=gate_res.gate_statuses.get(2, False),
                liquidity_gate_pass=gate_res.gate_statuses.get(3, False),
                current_ask=latest_odds.up_odds if gate_res.side == "UP" else (latest_odds.down_odds if latest_odds else 0.0),
                min_odds=self._cfg.ODDS_SWEET_SPOT_LOW,
                max_odds=self._cfg.ODDS_SWEET_SPOT_HIGH,
                odds_gate_pass=gate_res.gate_statuses.get(4, False),
                golden_window_gate_pass=gate_res.gate_statuses.get(5, False),
                velocity_gate_pass=gate_res.gate_statuses.get(6, False),
                slippage_gate_pass=gate_res.gate_statuses.get(7, False),
                t_remaining_sec=t_rem,
                would_have_won=None,
                chainlink_age_sec=0
            )
            await self._audit_logger.log_skip(skip)

    async def _handle_hedge_execution(self, slug: str) -> None:
        """Execute Hedge Strategy: Buy both sides if they are cheap enough."""
        from logs.audit_logger import TradeRecord
        from risk.gates import GateResult
        
        t_rem = get_time_remaining()
        in_window = self._cfg.GOLDEN_WINDOW_END <= t_rem <= self._cfg.GOLDEN_WINDOW_START
        if not in_window:
            return

        latest_odds = self._signal_processor.latest_odds
        if not latest_odds:
            return

        up_odds = latest_odds.up_odds
        down_odds = latest_odds.down_odds
        
        # Beli UP jika murah
        if up_odds <= self._cfg.HEDGE_MODE_ODDS_MAX and not self._order_sent_up:
            logger.info("🛡️ HEDGE UP: odds %.3f <= %.3f", up_odds, self._cfg.HEDGE_MODE_ODDS_MAX)
            ss = self._signal_processor.state
            gate_res = GateResult(
                all_pass=True, 
                failed_gate=None, 
                fail_reason=None, 
                gate_statuses={i: True for i in range(1, 8)},
                evaluated_at=time.time(),
                signal_snapshot=ss,
                target_ask=up_odds,
                expected_odds=up_odds,
                in_sweet_spot=True,
                side="UP"
            )
            order_res = await self._order_executor.execute(gate_res, slug)
            if order_res.status in ("FILLED", "PARTIAL", "PAPER_FILL"):
                self._order_sent_up = True
                await self._log_hedge_trade(slug, order_res, "HEDGE_UP")
        
        # Beli DOWN jika murah
        if down_odds <= self._cfg.HEDGE_MODE_ODDS_MAX and not self._order_sent_down:
            logger.info("🛡️ HEDGE DOWN: odds %.3f <= %.3f", down_odds, self._cfg.HEDGE_MODE_ODDS_MAX)
            ss = self._signal_processor.state
            gate_res = GateResult(
                all_pass=True, 
                failed_gate=None, 
                fail_reason=None, 
                gate_statuses={i: True for i in range(1, 8)},
                evaluated_at=time.time(),
                signal_snapshot=ss,
                target_ask=down_odds,
                expected_odds=down_odds,
                in_sweet_spot=True,
                side="DOWN"
            )
            order_res = await self._order_executor.execute(gate_res, slug)
            if order_res.status in ("FILLED", "PARTIAL", "PAPER_FILL"):
                self._order_sent_down = True
                await self._log_hedge_trade(slug, order_res, "HEDGE_DOWN")

    async def _log_hedge_trade(self, slug: str, order_res, mode: str) -> None:
        """Helper to log hedge trades and update dashboard."""
        from logs.audit_logger import TradeRecord
        from cli.dashboard import TradeHistoryEntry
        
        ss = self._signal_processor.state
        trade = TradeRecord(
            session_id=self._session_id, window_id=slug,
            timestamp_trigger=datetime.now(timezone.utc).isoformat(),
            timestamp_order_sent=datetime.now(timezone.utc).isoformat(),
            timestamp_confirmed=datetime.now(timezone.utc).isoformat(),
            side=order_res.side or "", strike_price=order_res.entry_odds or 0.0,
            hl_price_at_trigger=ss.hl_price, gap_value=ss.gap,
            gap_threshold_used=ss.gap_threshold, atr_regime=ss.vol_regime,
            cvd_60s=ss.cvd_60s, cvd_threshold_used=ss.cvd_threshold,
            cvd_threshold_pct=0.0, velocity=ss.velocity_1_5s,
            entry_odds=order_res.entry_odds or 0.0, odds_in_sweet_spot=True,
            spread_pct=0.0, expected_odds=order_res.entry_odds or 0.0,
            mispricing_delta=0.0, slippage_delta=order_res.slippage_delta,
            slippage_threshold_used=0.0, blockchain_latency_ms=0,
            shares_bought=order_res.shares_bought or 0.0,
            cost_usdc=order_res.cost_usd or 0.0, result=order_res.status,
            resolution_price=None, payout_usdc=None, pnl_usdc=None,
            claim_method=None, claim_timestamp=None, mode=mode,
            bot_version=getattr(self._cfg, "BOT_VERSION", "2.3")
        )
        await self._audit_logger.log_trade(trade)
        
        entry = TradeHistoryEntry(
            number=len(self._dashboard.state.trade_history)+1,
            time_str=datetime.now().strftime("%H:%M:%S"),
            result="OPEN", side=order_res.side or "",
            odds=order_res.entry_odds or 0, gap=ss.gap,
            cvd_pct=0, velocity=ss.velocity_1_5s,
            spread=0, slippage=order_res.slippage_delta, claim="WAIT"
        )
        self._dashboard.state.trade_history.append(entry)
        asyncio.create_task(self._claim_and_finalize(slug, order_res, entry))

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
        """Sync component states to dashboard (PRD v2.3 compliant fields)."""
        ds = self._dashboard.state
        ss = self._signal_processor.state
        
        # Panel B: Price & Gap
        ds.hl_price = ss.current_hl_price
        ds.strike_price = ss.strike_price
        ds.gap = ss.gap
        ds.gap_direction = ss.gap_direction
        ds.gap_threshold = ss.gap_threshold
        ds.velocity = ss.velocity_1_5s
        ds.atr = ss.atr
        ds.vol_regime = ss.vol_regime
        
        # Panel C: CVD
        ds.buy_volume = ss.buy_volume_60s
        ds.sell_volume = ss.sell_volume_60s
        ds.cvd_net = ss.cvd_60s
        ds.avg_vol_per_min = ss.avg_volume_per_min
        ds.cvd_threshold = ss.cvd_threshold
        ds.cvd_aligned = ss.cvd_aligned
        ds.cvd_direction = ss.cvd_direction
        
        # Panel D: Order Book (Odds)
        latest_odds = self._signal_processor.latest_odds
        if latest_odds:
            ds.up_ask = latest_odds.up_odds
            ds.up_bid = latest_odds.up_odds - 0.01
            ds.down_ask = latest_odds.down_odds
            ds.down_bid = latest_odds.down_odds - 0.01
            ds.spread_pct = abs(latest_odds.up_odds + latest_odds.down_odds - 1.0) * 100.0
            
        # Panel E: Safety Gates
        from risk.gates import GateEvaluator
        evaluator = GateEvaluator(self._cfg)
        gate_res = evaluator.evaluate(
            signal=ss,
            book=self._signal_processor.latest_book,
            odds=latest_odds,
            time_remaining=self._dashboard.state.time_remaining,
            order_sent=self._order_sent,
        )
        ds.gate_statuses = gate_res.gate_statuses

        # Hedge Mode Status
        ds.hedge_mode_enabled = self._cfg.HEDGE_MODE_ENABLED
        if latest_odds:
            ds.up_armed = latest_odds.up_odds <= self._cfg.HEDGE_MODE_ODDS_MAX
            ds.down_armed = latest_odds.down_odds <= self._cfg.HEDGE_MODE_ODDS_MAX
        else:
            ds.up_armed = False
            ds.down_armed = False
        ds.expected_odds = gate_res.expected_odds
        ds.mispricing = (latest_odds and ds.up_ask < gate_res.expected_odds) if latest_odds else False
        
        # Panel A: Header extras
        ds.wallet_type = self._claim_manager.wallet_type
        ds.balance = 1000.0 if self._cfg.PAPER_TRADING_MODE else 0.0
        ds.unclaimed = self._claim_manager.unclaimed_balance
        ds.eoa_warning = self._claim_manager.eoa_warning
        
        # Sync Health Metrics
        ds.chainlink_age_sec = self._chainlink_feed.last_event.age_seconds if self._chainlink_feed.last_event else 999.0
        ds.poly_sync_latency_sec = self._poly_feed.sync_latency
        
        ds.gate_values = {
            1: f"${ss.gap:+.1f} / ${ss.gap_threshold:.1f}",
            2: f"${ss.cvd_60s:+.0f} / {ss.cvd_threshold:.0f}",
            3: f"Ask: {ds.up_ask:.2f} / Edge: {'YES' if ds.mispricing else 'NO'}",
            4: f"[{self._cfg.ODDS_SWEET_SPOT_LOW:.2f}-{self._cfg.ODDS_SWEET_SPOT_HIGH:.2f}]" if latest_odds else "NO DATA",
            5: f"T-{self._dashboard.state.time_remaining}s",
            6: f"${ss.velocity_1_5s:.1f}/s" if self._cfg.VELOCITY_ENABLED else "DISABLED",
            7: "SENT" if self._order_sent else "CLEAR",
        }
            
        ds.is_lockdown = self._circuit_breaker.is_lockdown
        ds.lockdown_reason = self._circuit_breaker.lockdown_reason
        
        # Stats
        if (ds.wins + ds.losses) > 0:
            ds.win_rate = ds.wins / (ds.wins + ds.losses)

    async def stop(self) -> None:
        """Graceful shutdown of all components."""
        if self._stopping: return
        self._stopping = True
        
        logger.info("Stopping engine...")
        self._shutdown.set()
        
        await self._hl_feed.stop()
        await self._poly_feed.stop()
        await self._chainlink_feed.stop()
        self._safety_monitor.stop()
        self._dashboard.stop()
        await self._order_executor.stop()
        await self._claim_manager.stop()
        
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
                temp_file = ui_file + ".tmp"
                with open(temp_file, "w") as f:
                    json.dump(state_dict, f)
                os.replace(temp_file, ui_file)
            except Exception: pass
            await asyncio.sleep(0.5)

    async def _periodic_state_flush(self) -> None:
        while not self._shutdown.is_set():
            await asyncio.sleep(self._cfg.LOG_FLUSH_INTERVAL_SEC)
            if self._audit_logger: await self._audit_logger.flush_state(dict(self._engine_state))

    async def _periodic_snapshot_writer(self) -> None:
        while not self._shutdown.is_set():
            await asyncio.sleep(self._cfg.STATE_SNAPSHOT_INTERVAL_SEC)
            await self._audit_logger.flush_state(dict(self._engine_state))
