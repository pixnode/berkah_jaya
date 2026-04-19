# ═══ FILE: btc_sniper/core/engine.py ═══
"""BotEngine — main orchestrator. Startup, main loop, shutdown."""

from __future__ import annotations
import asyncio, json, logging, time
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
    def __init__(self, cfg: BotConfig) -> None:
        self._cfg = cfg
        self._tasks: Set[asyncio.Task] = set()
        self._shutdown = asyncio.Event()
        self._stopping = False
        self._session_id = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
        self._session_start = time.time()
        self._window_count = 0
        self._order_sent = False
        self._soft_start = False
        self._engine_state: dict = {}
        self._hl_feed = None; self._poly_feed = None; self._chainlink_feed = None
        self._signal_processor = None; self._gate_evaluator = None
        self._order_executor = None; self._claim_manager = None
        self._circuit_breaker = None; self._safety_monitor = None
        self._audit_logger = None; self._dashboard = None
        self._queue: Optional[asyncio.Queue] = None
        # session stats
        self._wins=0; self._losses=0; self._skips=0; self._locked_windows=0
        self._total_cost=0.0; self._total_payout=0.0
        self._entry_odds_list: list[float] = []; self._gap_list: list[float] = []
        self._latency_list: list[int] = []
        self._skip_reasons: dict[str,int] = {}
        self._lockdown_triggers: list[str] = []

    async def start(self) -> None:
        from feeds.hyperliquid_ws import HyperliquidFeed
        from feeds.polymarket_ws import PolymarketFeed
        from feeds.chainlink_feed import ChainlinkFeed
        from core.signal_processor import SignalProcessor
        from core.order_executor import OrderExecutor
        from core.claim_manager import ClaimManager
        from core.circuit_breaker import CircuitBreaker
        from risk.gates import GateEvaluator
        from risk.safety_monitor import SafetyMonitor
        from logs.audit_logger import AuditLogger, EventRecord
        from cli.dashboard import Dashboard

        self._audit_logger = AuditLogger(self._cfg)
        await self._audit_logger.log_event(EventRecord(time.time(),"STARTUP","","engine","","Bot starting",None,"{}"))

        self._queue = asyncio.Queue(maxsize=self._cfg.QUEUE_HL_MAXSIZE)
        self._hl_feed = HyperliquidFeed(self._cfg, self._audit_logger)
        self._poly_feed = PolymarketFeed(self._cfg, self._audit_logger)
        self._chainlink_feed = ChainlinkFeed(self._cfg, self._audit_logger)
        self._signal_processor = SignalProcessor(self._cfg)
        self._gate_evaluator = GateEvaluator(self._cfg)
        self._order_executor = OrderExecutor(self._cfg, self._audit_logger)
        self._claim_manager = ClaimManager(self._cfg, self._audit_logger)
        self._circuit_breaker = CircuitBreaker(self._cfg, self._audit_logger)
        self._safety_monitor = SafetyMonitor(self._cfg, self._audit_logger)
        self._dashboard = Dashboard(self._cfg)

        await self._claim_manager.check_wallet_type()
        self._claim_manager.set_chainlink_feed(self._chainlink_feed)
        await self._claim_manager._init_clob_client()
        
        if not self._cfg.PAPER_TRADING_MODE:
            import aiohttp
            logger.info("Performing live mode startup health checks...")
            try:
                async with aiohttp.ClientSession() as session:
                    # Test CLOB
                    async with session.get(f"{self._cfg.CLOB_HOST}/auth/api-key", timeout=5) as resp:
                        if resp.status not in (200, 401, 404, 405):  # As long as we can reach it
                            logger.warning("CLOB API check unexpected status: %d", resp.status)
                    # Test Relayer
                    async with session.get(f"{self._cfg.RELAYER_URL}/health", timeout=5) as resp:
                        if resp.status == 200:
                            logger.info("CLOB connected ✓  Relayer: OK")
                        else:
                            logger.warning("Relayer returned status: %d", resp.status)
            except Exception as e:
                raise RuntimeError(f"CLOB API connection failed — {e}")

        self._safety_monitor.set_components(
            self._hl_feed, self._poly_feed, self._chainlink_feed,
            self._circuit_breaker, self._signal_processor,
        )

        for coro in [
            self._hl_feed.start(self._queue),
            self._poly_feed.start(self._queue),
            self._chainlink_feed.start_polling(self._queue),
            self._signal_processor.run(self._queue),
            self._safety_monitor.run(),
            self._dashboard.run(),
            self._ui_exporter_loop(),
            self._periodic_state_flush(),
            self._periodic_snapshot_writer(),
        ]:
            t = asyncio.create_task(coro)
            self._tasks.add(t)
            t.add_done_callback(self._tasks.discard)

        await self._audit_logger.log_event(EventRecord(time.time(),"STARTUP","","engine","","All tasks launched",None,"{}"))
        logger.info("═══ BTC SNIPER v%s STARTED ═══", self._cfg.BOT_VERSION)
        await self.main_loop()

    async def main_loop(self) -> None:
        from logs.audit_logger import EventRecord, SkipRecord, TradeRecord
        from feeds import ChainlinkEvent
        last_window_slug = ""

        while not self._shutdown.is_set():
            if self._circuit_breaker and self._circuit_breaker.is_lockdown:
                self._update_dashboard_mode("LOCKDOWN")
                await asyncio.sleep(1); continue

            t_rem = get_time_remaining()
            slug = get_current_window_slug()

            # ── New window detection ──
            if slug != last_window_slug:
                last_window_slug = slug
                self._window_count += 1
                self._order_sent = False
                self._update_engine_state(slug, t_rem, "INIT")

                # Get strike price
                try:
                    cl_event = await self._chainlink_feed.get_strike_price()
                    if cl_event.age_seconds > self._cfg.CHAINLINK_MAX_AGE_SEC:
                        logger.warning("Strike price stale (%ds), waiting...", cl_event.age_seconds)
                        await asyncio.sleep(min(15, t_rem))
                        cl_event = await self._chainlink_feed.get_strike_price()
                        if cl_event.age_seconds > self._cfg.CHAINLINK_MAX_AGE_SEC:
                            self._record_skip("STRIKE_PRICE_STALE", slug, t_rem, "INIT")
                            continue
                    self._signal_processor.set_strike_price(cl_event.price)
                except Exception as exc:
                    logger.error("Failed to get strike price: %s", exc)
                    self._record_skip("STRIKE_PRICE_STALE", slug, t_rem, "INIT")
                    continue

                await self._poly_feed.subscribe(slug)
                self._signal_processor.reset_velocity()
                self._update_dashboard_mode("MONITORING")

                if self._soft_start:
                    logger.info("Soft start: MONITOR only for this window")
                    self._soft_start = False
                    self._update_dashboard_mode("MONITORING")
                    while get_current_window_slug() == slug and not self._shutdown.is_set():
                        self._update_dashboard_state(slug)
                        await asyncio.sleep(1)
                    continue

            t_rem = get_time_remaining()

            # ── Wait for golden window ──
            if t_rem > self._cfg.GOLDEN_WINDOW_START:
                self._update_dashboard_mode("MONITORING")
                self._update_dashboard_state(slug)
                await asyncio.sleep(0.5); continue

            # ── Golden window active ──
            if t_rem < self._cfg.GOLDEN_WINDOW_END:
                if not self._order_sent:
                    self._record_skip("WINDOW_EXPIRED", slug, t_rem, "ARMED")
                self._update_dashboard_mode("SKIP" if not self._order_sent else "WAIT")
                while get_current_window_slug() == slug and not self._shutdown.is_set():
                    self._update_dashboard_state(slug)
                    await asyncio.sleep(1)
                continue

            if self._order_sent:
                self._update_dashboard_state(slug)
                await asyncio.sleep(0.5); continue

            self._update_dashboard_mode("ARMED")
            signal = self._signal_processor.get_state_snapshot()
            book = self._signal_processor.latest_book
            odds = self._signal_processor.latest_odds

            gate_result = self._gate_evaluator.evaluate(signal, book, odds, t_rem, self._order_sent)
            self._update_gate_display(gate_result)

            if gate_result.all_pass:
                self._update_dashboard_mode("EXECUTING")
                order_result = await self._order_executor.execute(gate_result, slug)
                self._order_sent = True

                cost = order_result.cost_usd or 0.0
                self._total_cost += cost
                if order_result.entry_odds: self._entry_odds_list.append(order_result.entry_odds)
                if gate_result.signal_snapshot.gap: self._gap_list.append(abs(gate_result.signal_snapshot.gap))
                if order_result.latency_ms: self._latency_list.append(order_result.latency_ms)

                now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                trade = TradeRecord(
                    session_id=self._session_id, window_id=slug,
                    timestamp_trigger=now_str, timestamp_order_sent=now_str,
                    timestamp_confirmed=now_str, side=gate_result.side or "",
                    strike_price=signal.strike_price, hl_price_at_trigger=signal.current_hl_price,
                    gap_value=signal.gap, gap_threshold_used=signal.gap_threshold,
                    atr_regime=signal.vol_regime, cvd_60s=signal.cvd_60s,
                    cvd_threshold_used=signal.cvd_threshold, cvd_threshold_pct=signal.cvd_threshold_pct,
                    velocity=signal.velocity_1_5s, entry_odds=order_result.entry_odds or 0,
                    odds_in_sweet_spot=gate_result.in_sweet_spot, spread_pct=book.spread_pct if book else 0,
                    expected_odds=gate_result.expected_odds, mispricing_delta=gate_result.expected_odds-(order_result.entry_odds or 0),
                    slippage_delta=order_result.slippage_delta, slippage_threshold_used=order_result.slippage_threshold_used,
                    blockchain_latency_ms=order_result.latency_ms or 0, shares_bought=order_result.shares_bought or 0,
                    cost_usdc=cost, result="PENDING", resolution_price=None,
                    payout_usdc=None, pnl_usdc=None, claim_method=None, claim_timestamp=None,
                    bot_version=self._cfg.BOT_VERSION,
                )
                await self._audit_logger.log_trade(trade)
                self._update_dashboard_mode("WAIT")

                # Wait for resolution and claim
                claim_result = await self._claim_manager.claim(slug, order_result)

                # Determine result
                if claim_result.status in ("AUTO","PAPER"):
                    payout = claim_result.payout_usd
                    pnl = payout - cost
                    result = "WIN" if pnl >= 0 else "LOSS"
                    self._total_payout += payout
                    if result == "WIN":
                        self._wins += 1; await self._circuit_breaker.record_win()
                    else:
                        self._losses += 1; await self._circuit_breaker.record_loss(abs(pnl))
                elif claim_result.status == "LOSS":
                    result = "LOSS"; payout = 0.0; pnl = -cost
                    self._losses += 1; await self._circuit_breaker.record_loss(abs(pnl))
                else:
                    result = "PENDING"; payout = 0.0; pnl = 0.0

                res_price = self._signal_processor.latest_chainlink
                await self._audit_logger.update_trade_resolution(
                    slug, res_price.price if res_price else 0, payout, pnl,
                    claim_result.claim_method, datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                )

                # Update skip would_have_won and snapshot window_result
                resolution_dir = "UP" if (res_price and res_price.price >= signal.strike_price) else "DOWN"
                await self._audit_logger.update_skip_would_have_won(slug, resolution_dir)
                await self._audit_logger.update_snapshot_window_result(slug, resolution_dir)

                self._update_trade_history(gate_result, order_result, result, claim_result.claim_method)
                self._update_dashboard_pnl()

            else:
                # Gate failed — log once per evaluation
                pass  # Skip log written at window expiry

            self._update_dashboard_state(slug)
            await asyncio.sleep(1)

    def _record_skip(self, reason: str, slug: str, t_rem: int, stage: str) -> None:
        from logs.audit_logger import SkipRecord
        self._skips += 1
        cat = reason.split(":")[0] if ":" in reason else reason
        self._skip_reasons[cat] = self._skip_reasons.get(cat, 0) + 1
        asyncio.ensure_future(self._circuit_breaker.record_skip())

        signal = self._signal_processor.get_state_snapshot() if self._signal_processor else None
        skip = SkipRecord(
            session_id=self._session_id, window_id=slug,
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            skip_reason=reason, skip_stage=stage,
            gap_value=signal.gap if signal else None,
            gap_threshold=signal.gap_threshold if signal else None,
            gap_gate_pass=None, cvd_value=signal.cvd_60s if signal else None,
            cvd_gate_pass=None, liquidity_gate_pass=None,
            current_ask=None, min_odds=self._cfg.ODDS_MIN, max_odds=self._cfg.ODDS_MAX,
            odds_gate_pass=None, golden_window_gate_pass=None,
            velocity_gate_pass=None, slippage_gate_pass=None,
            t_remaining_sec=t_rem, would_have_won=None,
            chainlink_age_sec=self._signal_processor.latest_chainlink.age_seconds if self._signal_processor and self._signal_processor.latest_chainlink else None,
        )
        asyncio.ensure_future(self._audit_logger.log_skip(skip))

    def _update_engine_state(self, slug: str, t_rem: int, mode: str) -> None:
        self._engine_state = {"window_id": slug, "t_remaining": t_rem, "bot_mode": mode,
            "session_id": self._session_id, "order_sent": self._order_sent}
        if self._safety_monitor: self._safety_monitor.set_engine_state(self._engine_state)

    def _update_dashboard_mode(self, mode: str) -> None:
        if self._dashboard:
            self._dashboard.state.bot_mode = mode
            self._dashboard.state.is_lockdown = (mode == "LOCKDOWN")
            if self._circuit_breaker:
                self._dashboard.state.lockdown_reason = self._circuit_breaker.lockdown_reason

    def _update_dashboard_state(self, slug: str) -> None:
        if not self._dashboard: return
        s = self._dashboard.state
        s.window_id = slug; s.time_remaining = get_time_remaining()
        s.eoa_warning = self._claim_manager.eoa_warning if self._claim_manager else False
        s.unclaimed = self._claim_manager.unclaimed_balance if self._claim_manager else 0
        if self._signal_processor:
            sig = self._signal_processor.state
            s.hl_price = sig.current_hl_price; s.strike_price = sig.strike_price
            s.gap = sig.gap; s.gap_direction = sig.gap_direction
            s.gap_threshold = sig.gap_threshold; s.velocity = sig.velocity_1_5s
            s.atr = sig.atr; s.vol_regime = sig.vol_regime
            s.cvd_net = sig.cvd_60s; s.cvd_threshold = sig.cvd_threshold
            s.cvd_aligned = sig.cvd_aligned; s.avg_vol_per_min = sig.avg_volume_per_min
            book = self._signal_processor.latest_book
            if book:
                s.up_ask=book.up_ask; s.up_bid=book.up_bid
                s.down_ask=book.down_ask; s.down_bid=book.down_bid
                s.spread_pct=book.spread_pct

    def _update_gate_display(self, gr) -> None:
        if not self._dashboard: return
        s = self._dashboard.state
        s.gate_statuses = dict(gr.gate_statuses)
        sig = gr.signal_snapshot
        s.gate_values = {
            1: f"${abs(sig.gap):.1f} / ${sig.gap_threshold:.1f}",
            2: f"${sig.cvd_60s:,.0f} / ${sig.cvd_threshold:,.0f}",
            3: f"Spread {s.spread_pct:.1f}%",
            4: f"{gr.target_ask:.3f} [{self._cfg.ODDS_MIN}-{self._cfg.ODDS_MAX}]",
            5: f"T-{s.time_remaining}s [{self._cfg.GOLDEN_WINDOW_END}-{self._cfg.GOLDEN_WINDOW_START}]",
            6: f"${sig.velocity_1_5s:.1f} / ${self._cfg.VELOCITY_MIN_DELTA:.1f}" if self._cfg.VELOCITY_ENABLED else "DISABLED",
            7: "No" if not self._order_sent else "SENT",
        }
        s.expected_odds = gr.expected_odds
        s.mispricing = gr.gate_statuses.get(3, False)

    def _update_dashboard_pnl(self) -> None:
        if not self._dashboard: return
        s = self._dashboard.state
        s.total_pnl = self._total_payout - self._total_cost
        s.wins = self._wins; s.losses = self._losses; s.skips = self._skips
        s.win_rate = self._wins / max(self._wins + self._losses, 1)

    def _update_trade_history(self, gr, order_result, result, claim_method) -> None:
        if not self._dashboard: return
        from cli.dashboard import TradeHistoryEntry
        sig = gr.signal_snapshot
        entry = TradeHistoryEntry(
            number=self._wins+self._losses, time_str=time.strftime("%H:%M:%S"),
            result=result, side=gr.side or "", odds=order_result.entry_odds or 0,
            gap=abs(sig.gap), cvd_pct=abs(sig.cvd_60s)/max(sig.cvd_threshold,1)*100,
            velocity=sig.velocity_1_5s, spread=sig.gap_threshold,
            slippage=order_result.slippage_delta, claim=claim_method or "—",
        )
        self._dashboard.state.trade_history.append(entry)

    async def _ui_exporter_loop(self) -> None:
        """Saves a JSON snapshot of the dashboard state for external viewers."""
        import json
        import dataclasses
        
        ui_file = os.path.join(self._cfg.OUTPUT_DIR, "dashboard_ui.json")
        
        while not self._shutdown.is_set():
            try:
                # Helper to convert dataclass to dict, handling nested dataclasses
                def d_to_dict(obj):
                    if dataclasses.is_dataclass(obj):
                        result = {}
                        for f in dataclasses.fields(obj):
                            value = getattr(obj, f.name)
                            result[f.name] = d_to_dict(value)
                        return result
                    elif isinstance(obj, list):
                        return [d_to_dict(i) for i in obj]
                    elif isinstance(obj, dict):
                        return {k: d_to_dict(v) for k, v in obj.items()}
                    else:
                        return obj

                state_dict = d_to_dict(self._dashboard.state)
                with open(ui_file, "w") as f:
                    json.dump(state_dict, f)
            except Exception:
                pass
            await asyncio.sleep(1.0)

    async def _periodic_state_flush(self) -> None:
        while not self._shutdown.is_set():
            await asyncio.sleep(self._cfg.LOG_FLUSH_INTERVAL_SEC)
            if self._audit_logger:
                await self._audit_logger.flush_state(dict(self._engine_state))

    async def _periodic_snapshot_writer(self) -> None:
        from logs.audit_logger import SnapshotRecord
        while not self._shutdown.is_set():
            await asyncio.sleep(self._cfg.SNAPSHOT_INTERVAL_SEC)
            if not self._signal_processor: continue
            sig = self._signal_processor.state
            book = self._signal_processor.latest_book
            odds = self._signal_processor.latest_odds
            cl = self._signal_processor.latest_chainlink
            slug = get_current_window_slug()
            snap = SnapshotRecord(
                session_id=self._session_id, window_id=slug,
                timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                t_remaining_sec=get_time_remaining(), strike_price=sig.strike_price,
                hl_price=sig.current_hl_price, gap=sig.gap, gap_direction=sig.gap_direction,
                atr_60m=sig.atr, atr_regime=sig.vol_regime, cvd_60s=sig.cvd_60s,
                cvd_aligned=sig.cvd_aligned, avg_volume_per_min=sig.avg_volume_per_min,
                poly_up_odds=odds.up_odds if odds else 0, poly_down_odds=odds.down_odds if odds else 0,
                poly_up_ask_depth=book.up_ask if book else 0, poly_down_bid_depth=book.down_bid if book else 0,
                spread_pct=book.spread_pct if book else 0, dual_side_ok=bool(book and book.up_ask>0 and book.down_bid>0),
                chainlink_age_sec=cl.age_seconds if cl else 999,
                bot_mode=self._engine_state.get("bot_mode",""), all_gates_pass=False, window_result=None,
            )
            await self._audit_logger.log_snapshot(snap)

    async def stop(self) -> None:
        if self._stopping:
            return
        self._stopping = True
        from logs.audit_logger import EventRecord, SessionStats
        self._shutdown.set()
        logger.info("Stopping engine...")

        for task in list(self._tasks):
            task.cancel()
            try: await asyncio.wait_for(task, timeout=5)
            except (asyncio.CancelledError, asyncio.TimeoutError): pass

        if self._audit_logger:
            await self._audit_logger.flush_state(dict(self._engine_state))
            end_time = time.time()
            dur = int((end_time - self._session_start) / 60)
            avg_odds = sum(self._entry_odds_list)/len(self._entry_odds_list) if self._entry_odds_list else 0
            avg_gap = sum(self._gap_list)/len(self._gap_list) if self._gap_list else 0
            avg_lat = int(sum(self._latency_list)/len(self._latency_list)) if self._latency_list else 0
            stats = SessionStats(
                session_id=self._session_id,
                start_time=datetime.fromtimestamp(self._session_start,timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                end_time=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                duration_min=dur, bot_version=self._cfg.BOT_VERSION,
                bot_mode="paper" if self._cfg.PAPER_TRADING_MODE else "live",
                total_windows=self._window_count, windows_traded=self._wins+self._losses,
                windows_skipped=self._skips, windows_locked=self._locked_windows,
                wins=self._wins, losses=self._losses,
                win_rate=self._wins/max(self._wins+self._losses,1),
                total_cost_usdc=self._total_cost, total_payout_usdc=self._total_payout,
                net_pnl_usdc=self._total_payout-self._total_cost,
                avg_entry_odds=avg_odds, avg_gap_at_entry=avg_gap, avg_blockchain_latency_ms=avg_lat,
                skip_gap_insufficient=self._skip_reasons.get("GAP_INSUFFICIENT",0),
                skip_cvd_not_aligned=self._skip_reasons.get("CVD_MISALIGNED",0),
                skip_odds_too_low=self._skip_reasons.get("ODDS_TOO_LOW",0),
                skip_odds_too_high=self._skip_reasons.get("ODDS_TOO_HIGH",0),
                skip_no_liquidity=self._skip_reasons.get("NO_LIQUIDITY",0),
                skip_slippage=self._skip_reasons.get("SLIPPAGE_EXCEEDED",0),
                skip_other=sum(v for k,v in self._skip_reasons.items() if k not in ("GAP_INSUFFICIENT","CVD_MISALIGNED","ODDS_TOO_LOW","ODDS_TOO_HIGH","NO_LIQUIDITY","SLIPPAGE_EXCEEDED")),
                lockdown_triggers=",".join(self._lockdown_triggers),
                unclaimed_balance_usdc=self._claim_manager.unclaimed_balance if self._claim_manager else 0,
                auto_claimed_usdc=self._total_payout,
                manual_claim_required=0.0,
            )
            await self._audit_logger.write_session_summary(stats)
            await self._audit_logger.log_event(EventRecord(time.time(),"SHUTDOWN","","engine","","Bot stopped",None,"{}"))

        if self._order_executor: await self._order_executor.close()
        if self._claim_manager: await self._claim_manager.close()
        if self._hl_feed: await self._hl_feed.stop()
        if self._poly_feed: await self._poly_feed.stop()
        if self._chainlink_feed: await self._chainlink_feed.stop()
        if self._dashboard: self._dashboard.stop()
        logger.info("═══ SHUTDOWN COMPLETE ═══")
