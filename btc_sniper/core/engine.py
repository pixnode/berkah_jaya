# ═══ FILE: btc_sniper/core/engine.py ═══
"""BotEngine — main orchestrator. Startup, main loop, shutdown."""

from __future__ import annotations
import asyncio, json, logging, time, os
from datetime import datetime, timezone
from typing import Optional, Set, Dict
import aiohttp
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
        self._paper_balance = 1000.0  # Saldo awal simulasi (Available to trade)
        self._current_tokens: Dict[str, str] = {}
        self._fetch_session = None
        self._last_resume_check_t = 0
        self._last_heartbeat_t = 0

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
                        if resp.status in (200, 401):  # 401 is fine, means endpoint is alive
                            logger.info("CLOB API connected ✓")
                    try:
                        async with session.get(f"{self._cfg.RELAYER_URL}/health", timeout=5) as resp:
                            if resp.status == 200:
                                logger.info("Relayer API: OK")
                    except Exception as relayer_err:
                        logger.warning(f"Relayer API health check failed (DNS/Timeout): {relayer_err}. Continuing anyway...")
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
            self._periodic_balance_refresh(),
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
                self._current_tokens = {}
                
                # Fetch exact Token IDs for the new window
                asyncio.create_task(self._fetch_window_tokens(slug))
                
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

            # Periodic Heartbeat Log (Every 30 seconds)
            if int(t_rem) % 30 == 0 and int(t_rem) != self._last_heartbeat_t:
                self._last_heartbeat_t = int(t_rem)
                ss = self._signal_processor.state
                logger.info(
                    "💓 [HEARTBEAT] Window: %s | Mode: %s | Gap: $%.1f | CVD: %.1f%% | Odds: %.2f/%.2f",
                    slug, mode, ss.gap, ss.cvd_60s, ss.up_odds, ss.down_odds
                )

            # Lockdown Auto-Resume logic (PRD v2.3 compliant Section 06)
            if self._circuit_breaker.is_lockdown:
                # Try resume every 5 seconds or when a new window starts
                if (int(t_rem) % 5 == 0 and int(t_rem) != self._last_resume_check_t) or t_rem > 298:
                    self._last_resume_check_t = int(t_rem)
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
                if self._cfg.HEDGE_STRATEGY == 'SMART_HEDGE':
                    await self._handle_smart_hedge(slug)
                elif self._cfg.HEDGE_STRATEGY == 'TEMPORAL_HEDGE':
                    await self._handle_temporal_hedge(slug)
                elif self._cfg.HEDGE_STRATEGY == 'DIRECTIONAL' and not self._order_sent:
                    await self._handle_directional(slug)
                
            await asyncio.sleep(0.05)

            if self._dashboard.quit_requested:
                self._shutdown.set()



    async def _fetch_window_tokens(self, slug: str) -> None:
        """Fetch exact Token IDs for UP and DOWN outcomes from Gamma API with retries."""
        max_retries = 15
        for attempt in range(max_retries):
            try:
                if self._fetch_session is None or self._fetch_session.closed:
                    self._fetch_session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5))
                
                # Use specific User-Agent to bypass basic Cloudflare checks
                headers = {"User-Agent": "Mozilla/5.0 (Polymarket-BTCSniper/2.3)"}
                url = f"{self._cfg.GAMMA_API_URL}/markets?slug={slug}"
                
                async with self._fetch_session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data and isinstance(data, list) and len(data) > 0:
                            market_data = data[0]
                            tokens = market_data.get("tokens", [])
                            if tokens:
                                for t in tokens:
                                    outcome = t.get("outcome", "").upper()
                                    token_id = t.get("token_id")
                                    if outcome in ("YES", "UP"):
                                        self._current_tokens["UP"] = token_id
                                    elif outcome in ("NO", "DOWN"):
                                        self._current_tokens["DOWN"] = token_id
                            else:
                                # Fallback to clobTokenIds if tokens array is lagging
                                clob_token_ids_str = market_data.get("clobTokenIds", "[]")
                                outcomes_str = market_data.get("outcomes", "[]")
                                try:
                                    clob_token_ids = json.loads(clob_token_ids_str)
                                    outcomes = json.loads(outcomes_str)
                                    if len(clob_token_ids) == len(outcomes):
                                        for idx, outcome in enumerate(outcomes):
                                            outcome_upper = outcome.upper()
                                            if outcome_upper in ("YES", "UP"):
                                                self._current_tokens["UP"] = clob_token_ids[idx]
                                            elif outcome_upper in ("NO", "DOWN"):
                                                self._current_tokens["DOWN"] = clob_token_ids[idx]
                                except Exception as e:
                                    logger.warning("Failed to parse clobTokenIds fallback: %s", e)
                            
                            if self._current_tokens.get("UP") and self._current_tokens.get("DOWN"):
                                # Inject tokens into Polymarket WS feed immediately
                                if hasattr(self._poly_feed, "set_active_tokens"):
                                    self._poly_feed.set_active_tokens(self._current_tokens["UP"], self._current_tokens["DOWN"])
                                
                                # If WS is already connected, re-subscribe with the new tokens
                                if hasattr(self._poly_feed, "is_connected") and self._poly_feed.is_connected:
                                    asyncio.create_task(self._poly_feed.subscribe(slug))

                                logger.info("Fetched tokens for %s: UP=%s, DOWN=%s", 
                                            slug, self._current_tokens["UP"][:10], self._current_tokens["DOWN"][:10])
                                return
                    
                # If we get here, either status != 200 or data was empty/missing tokens
                if attempt < max_retries - 1:
                    logger.debug("Tokens for %s not ready yet (attempt %d). Retrying in 2s...", slug, attempt + 1)
                    await asyncio.sleep(2)
            except Exception as exc:
                logger.error("Failed to fetch window tokens for %s (attempt %d): %s", slug, attempt + 1, exc)
                if attempt < max_retries - 1:
                    await asyncio.sleep(2)
        
        logger.error("Giving up fetching tokens for %s after %d attempts.", slug, max_retries)

    async def _handle_directional(self, slug: str) -> None:
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
            
            target_token_id = self._current_tokens.get(gate_res.side)
            if not target_token_id:
                logger.error("Cannot execute %s: Missing token_id mapping!", gate_res.side)
                return
            
            order_res = await self._order_executor.execute(gate_res, target_token_id, slug)
            
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
                    cvd_threshold_pct=getattr(self._cfg, "CVD_THRESHOLD_PCT", 0.0),
                    velocity=ss.velocity_1_5s,
                    entry_odds=order_res.entry_odds or gate_res.target_ask,
                    odds_in_sweet_spot=gate_res.in_sweet_spot,
                    spread_pct=self._signal_processor.latest_book.spread_pct if self._signal_processor.latest_book else 0.0,
                    expected_odds=gate_res.expected_odds,
                    mispricing_delta=gate_res.expected_odds - gate_res.target_ask,
                    slippage_delta=order_res.slippage_delta,
                    slippage_threshold_used=getattr(self._cfg, "SLIPPAGE_THRESHOLD_NORMAL", 0.0),
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
                
                # Update paper balance immediately on entry
                if self._cfg.PAPER_TRADING_MODE:
                    self._paper_balance -= (order_res.cost_usd or 0)
                
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

    async def _handle_smart_hedge(self, slug: str) -> None:
        """Execute Smart Hedge Strategy: Buy both sides ONLY if pair cost < threshold."""
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
        pair_cost = up_odds + down_odds

        # CRITICAL FIX: PAIR COST CONTROL
        if pair_cost >= self._cfg.SMART_HEDGE_PAIR_MAX:
            from logs.audit_logger import SkipRecord
            reason = f"SMART_HEDGE_SKIP: pair cost ${pair_cost:.2f} >= max ${self._cfg.SMART_HEDGE_PAIR_MAX:.2f}"
            logger.info("🛡️ %s", reason)
            
            skip = SkipRecord(
                session_id=self._session_id,
                window_id=slug,
                timestamp=datetime.now(timezone.utc).isoformat(),
                skip_reason=reason,
                skip_stage="HEDGE_COST_CONTROL",
                gap_value=self._signal_processor.state.gap,
                gap_threshold=self._signal_processor.state.gap_threshold,
                gap_gate_pass=True,
                cvd_value=self._signal_processor.state.cvd_60s,
                cvd_gate_pass=True,
                liquidity_gate_pass=True,
                current_ask=pair_cost,
                min_odds=0.0,
                max_odds=self._cfg.SMART_HEDGE_PAIR_MAX,
                odds_gate_pass=False,
                golden_window_gate_pass=True,
                velocity_gate_pass=True,
                slippage_gate_pass=True,
                t_remaining_sec=t_rem,
                would_have_won=None,
                chainlink_age_sec=0
            )
            await self._audit_logger.log_skip(skip)
            return
        
        # Beli UP
        latest_book = self._signal_processor.latest_book
        if not latest_book:
            return

        if not self._order_sent_up:
            # BUG 1 FIXED: Indentasi diperbaiki, seluruh eksekusi masuk ke dalam if depth
            # KONDISI 1: Harga valid (Best Ask)
            # KONDISI 2: Depth cukup
            if up_odds <= self._cfg.ODDS_MAX and latest_book.up_ask_depth_usdc >= self._cfg.HEDGE_MIN_DEPTH_USDC:
                logger.info("🛡️ SMART HEDGE UP: odds %.3f (depth $%.2f)", up_odds, latest_book.up_ask_depth_usdc)
                ss = self._signal_processor.state
                gate_res = GateResult(
                    all_pass=True, failed_gate=None, fail_reason=None, gate_statuses={i: True for i in range(1, 8)},
                    evaluated_at=time.time(), signal_snapshot=ss, target_ask=up_odds, expected_odds=up_odds,
                    in_sweet_spot=True, side="UP"
                )
                target_token_id = self._current_tokens.get("UP")
                if target_token_id:
                    order_res = await self._order_executor.execute(gate_res, target_token_id, slug)
                    if order_res.status in ("FILLED", "PARTIAL", "PAPER_FILL"):
                        self._order_sent_up = True
                        await self._log_hedge_trade(slug, order_res, "HEDGE_UP")
                else:
                    logger.error("Cannot execute SMART HEDGE UP: Missing token_id!")
            elif up_odds > self._cfg.ODDS_MAX:
                logger.debug("🛡️ SMART HEDGE UP SKIP: Odds %.3f > %.3f", up_odds, self._cfg.ODDS_MAX)
            else:
                logger.debug("🛡️ SMART HEDGE UP SKIP: Depth $%.2f < $%.2f", latest_book.up_ask_depth_usdc, self._cfg.HEDGE_MIN_DEPTH_USDC)
        
        # Beli DOWN
        if not self._order_sent_down:
            # BUG 1 FIXED: Indentasi diperbaiki, seluruh eksekusi masuk ke dalam if depth
            # KONDISI 1: Harga valid (Best Ask)
            # KONDISI 2: Depth cukup
            if down_odds <= self._cfg.ODDS_MAX and latest_book.down_ask_depth_usdc >= self._cfg.HEDGE_MIN_DEPTH_USDC:
                logger.info("🛡️ SMART HEDGE DOWN: odds %.3f (depth $%.2f)", down_odds, latest_book.down_ask_depth_usdc)
                ss = self._signal_processor.state
                gate_res = GateResult(
                    all_pass=True, failed_gate=None, fail_reason=None, gate_statuses={i: True for i in range(1, 8)},
                    evaluated_at=time.time(), signal_snapshot=ss, target_ask=down_odds, expected_odds=down_odds,
                    in_sweet_spot=True, side="DOWN"
                )
                target_token_id = self._current_tokens.get("DOWN")
                if target_token_id:
                    order_res = await self._order_executor.execute(gate_res, target_token_id, slug)
                    if order_res.status in ("FILLED", "PARTIAL", "PAPER_FILL"):
                        self._order_sent_down = True
                        await self._log_hedge_trade(slug, order_res, "HEDGE_DOWN")
                else:
                    logger.error("Cannot execute HEDGE DOWN: Missing token_id!")
            elif down_odds > self._cfg.ODDS_MAX:
                logger.debug("🛡️ SMART HEDGE DOWN SKIP: Odds %.3f > %.3f", down_odds, self._cfg.ODDS_MAX)
            else:
                logger.debug("🛡️ SMART HEDGE DOWN SKIP: Depth $%.2f < $%.2f", latest_book.down_ask_depth_usdc, self._cfg.HEDGE_MIN_DEPTH_USDC)

    async def _handle_temporal_hedge(self, slug: str) -> None:
        """Execute Temporal Hedge Strategy: Buy cheapest side, track cost, buy other side later if total < max cost."""
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
        latest_book = self._signal_processor.latest_book
        if not latest_book:
            return
        
        # Track cumulative cost of hedge positions in this window
        if not hasattr(self, "_temporal_hedge_cost"):
            self._temporal_hedge_cost = 0.0

        # Reset cumulative cost if new window
        if not hasattr(self, "_current_slug") or self._current_slug != slug:
            self._temporal_hedge_cost = 0.0
            self._current_slug = slug

        # Try UP
        if not self._order_sent_up and up_odds <= self._cfg.TEMPORAL_MAX_SINGLE_ODDS:
            if latest_book.up_ask_depth_usdc < self._cfg.HEDGE_MIN_DEPTH_USDC:
                logger.debug("⏳ TEMPORAL UP SKIP: Depth $%.2f < $%.2f", latest_book.up_ask_depth_usdc, self._cfg.HEDGE_MIN_DEPTH_USDC)
            elif self._temporal_hedge_cost + up_odds <= self._cfg.TEMPORAL_MAX_TOTAL_COST:
                logger.info("⏳ TEMPORAL UP: odds %.3f (depth $%.2f). Total cost will be %.3f <= %.3f", 
                            up_odds, latest_book.up_ask_depth_usdc, self._temporal_hedge_cost + up_odds, self._cfg.TEMPORAL_MAX_TOTAL_COST)
                ss = self._signal_processor.state
                gate_res = GateResult(
                    all_pass=True, failed_gate=None, fail_reason=None, gate_statuses={i: True for i in range(1, 8)},
                    evaluated_at=time.time(), signal_snapshot=ss, target_ask=up_odds, expected_odds=up_odds,
                    in_sweet_spot=True, side="UP"
                )
                target_token_id = self._current_tokens.get("UP")
                if not target_token_id:
                    logger.error("Cannot execute TEMPORAL HEDGE UP: Missing token_id!")
                    return
                order_res = await self._order_executor.execute(gate_res, target_token_id, slug)
                if order_res.status in ("FILLED", "PARTIAL", "PAPER_FILL"):
                    self._order_sent_up = True
                    self._temporal_hedge_cost += (order_res.entry_odds or up_odds)
                    await self._log_hedge_trade(slug, order_res, "TEMPORAL_UP")
            else:
                logger.debug("⏳ TEMPORAL UP SKIP: Cost %.3f + %.3f > %.3f", self._temporal_hedge_cost, up_odds, self._cfg.TEMPORAL_MAX_TOTAL_COST)

        # Try DOWN
        if not self._order_sent_down and down_odds <= self._cfg.TEMPORAL_MAX_SINGLE_ODDS:
            if latest_book.down_ask_depth_usdc < self._cfg.HEDGE_MIN_DEPTH_USDC:
                logger.debug("⏳ TEMPORAL DOWN SKIP: Depth $%.2f < $%.2f", latest_book.down_ask_depth_usdc, self._cfg.HEDGE_MIN_DEPTH_USDC)
            elif self._temporal_hedge_cost + down_odds <= self._cfg.TEMPORAL_MAX_TOTAL_COST:
                logger.info("⏳ TEMPORAL DOWN: odds %.3f (depth $%.2f). Total cost will be %.3f <= %.3f", 
                            down_odds, latest_book.down_ask_depth_usdc, self._temporal_hedge_cost + down_odds, self._cfg.TEMPORAL_MAX_TOTAL_COST)
                ss = self._signal_processor.state
                gate_res = GateResult(
                    all_pass=True, failed_gate=None, fail_reason=None, gate_statuses={i: True for i in range(1, 8)},
                    evaluated_at=time.time(), signal_snapshot=ss, target_ask=down_odds, expected_odds=down_odds,
                    in_sweet_spot=True, side="DOWN"
                )
                target_token_id = self._current_tokens.get("DOWN")
                if not target_token_id:
                    logger.error("Cannot execute TEMPORAL HEDGE DOWN: Missing token_id!")
                    return
                order_res = await self._order_executor.execute(gate_res, target_token_id, slug)
                if order_res.status in ("FILLED", "PARTIAL", "PAPER_FILL"):
                    self._order_sent_down = True
                    self._temporal_hedge_cost += (order_res.entry_odds or down_odds)
                    await self._log_hedge_trade(slug, order_res, "TEMPORAL_DOWN")
            else:
                logger.debug("⏳ TEMPORAL DOWN SKIP: Cost %.3f + %.3f > %.3f", self._temporal_hedge_cost, down_odds, self._cfg.TEMPORAL_MAX_TOTAL_COST)

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
            hl_price_at_trigger=ss.current_hl_price, gap_value=ss.gap,
            gap_threshold_used=ss.gap_threshold, atr_regime=ss.vol_regime,
            cvd_60s=ss.cvd_60s, cvd_threshold_used=ss.cvd_threshold,
            cvd_threshold_pct=getattr(self._cfg, "CVD_THRESHOLD_PCT", 0.0),
            velocity=ss.velocity_1_5s,
            entry_odds=order_res.entry_odds or 0.0, odds_in_sweet_spot=True,
            spread_pct=self._signal_processor.latest_book.spread_pct if self._signal_processor.latest_book else 0.0,
            expected_odds=order_res.entry_odds or 0.0,
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
        
        # Update paper balance immediately on entry
        if self._cfg.PAPER_TRADING_MODE:
            self._paper_balance -= (order_res.cost_usd or 0)
            
        asyncio.create_task(self._claim_and_finalize(slug, order_res, entry))

    async def _claim_and_finalize(self, slug, order_res, history_entry):
        """Wait for resolution and claim."""
        claim_res = await self._claim_manager.claim(slug, order_res)
        history_entry.result = claim_res.status
        history_entry.claim = "DONE"
        
        # Determine status for CSV
        csv_result = "WIN" if claim_res.status in ("AUTO", "PAPER") else "LOSS"
        pnl = claim_res.payout_usd - (order_res.cost_usd or 0)
        
        # PERSIST TO CSV
        await self._audit_logger.update_trade_resolution(
            window_id=slug,
            result=csv_result,
            resolution_price=claim_res.resolution_price,
            payout_usdc=claim_res.payout_usd,
            pnl_usdc=pnl,
            claim_method=claim_res.claim_method,
            claim_timestamp=datetime.now(timezone.utc).isoformat()
        )
        
        # Synchronize other logs
        resolution_dir = "UP" if (csv_result == "WIN" and order_res.side in ("UP", "YES")) or (csv_result == "LOSS" and order_res.side in ("DOWN", "NO")) else "DOWN"
        await self._audit_logger.update_skip_would_have_won(slug, resolution_dir)
        await self._audit_logger.update_snapshot_window_result(slug, csv_result)

        # Update dashboard P&L & Balance
        if claim_res.status in ("AUTO", "PAPER"):
            self._dashboard.state.wins += 1
            self._dashboard.state.total_pnl += pnl
            if self._cfg.PAPER_TRADING_MODE:
                self._paper_balance += claim_res.payout_usd # Tambah hasil menang ke saldo (Claimed)
        elif claim_res.status == "LOSS":
            self._dashboard.state.losses += 1
            self._dashboard.state.total_pnl += pnl

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
        
        # Panel D: Order Book (Odds + Real Depth)
        latest_odds = self._signal_processor.latest_odds
        latest_book = self._signal_processor.latest_book
        if latest_odds:
            ds.up_ask = latest_odds.up_odds
            ds.down_ask = latest_odds.down_odds
            # Use real order book data for bids (not synthetic offset)
            if latest_book:
                ds.up_bid = latest_book.up_bid
                ds.down_bid = latest_book.down_bid
            else:
                ds.up_bid = 0.0
                ds.down_bid = 0.0
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
        ds.hedge_mode_enabled = self._cfg.HEDGE_STRATEGY != "DIRECTIONAL"
        if latest_odds:
            ds.up_armed = latest_odds.up_odds <= self._cfg.TEMPORAL_MAX_SINGLE_ODDS if self._cfg.HEDGE_STRATEGY == "TEMPORAL_HEDGE" else latest_odds.up_odds <= self._cfg.DIRECTIONAL_MAX_ODDS
            ds.down_armed = latest_odds.down_odds <= self._cfg.TEMPORAL_MAX_SINGLE_ODDS if self._cfg.HEDGE_STRATEGY == "TEMPORAL_HEDGE" else latest_odds.down_odds <= self._cfg.DIRECTIONAL_MAX_ODDS
        else:
            ds.up_armed = False
            ds.down_armed = False
        ds.expected_odds = gate_res.expected_odds
        ds.mispricing = (latest_odds and ds.up_ask < gate_res.expected_odds) if latest_odds else False
        
        # Panel A: Header extras
        ds.wallet_type = self._claim_manager.wallet_type
        ds.paper_mode = self._cfg.PAPER_TRADING_MODE  # Explicitly sync — never stale
        ds.balance = self._paper_balance if self._cfg.PAPER_TRADING_MODE else self._claim_manager.wallet_balance
        ds.unclaimed = self._claim_manager.unclaimed_balance
        ds.portfolio = ds.balance + ds.unclaimed
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

    async def _periodic_balance_refresh(self) -> None:
        """Periodically fetch USDC.e balance from Polygon RPC."""
        # Initial fetch on startup
        if not self._cfg.PAPER_TRADING_MODE:
            try:
                bal = await self._claim_manager.fetch_wallet_balance()
                logger.info("Initial balance: $%.2f USDC", bal)
            except Exception as exc:
                logger.warning("Initial balance fetch failed: %s", exc)

        while not self._shutdown.is_set():
            await asyncio.sleep(self._cfg.BALANCE_REFRESH_INTERVAL_SEC)
            if not self._cfg.PAPER_TRADING_MODE:
                try:
                    bal = await self._claim_manager.fetch_wallet_balance()
                    logger.debug("Balance refreshed: $%.2f USDC", bal)
                except Exception as exc:
                    logger.warning("Balance refresh failed: %s", exc)
