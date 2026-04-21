# ═══ FILE: btc_sniper/cli/dashboard.py ═══
"""
CLI Dashboard — 6-panel real-time terminal dashboard using Python rich.
Panel A: Header, B: Price/Gap, C: CVD, D: Order Book, E: Gates, F: P&L/History.
Handles keyboard inputs (Q, P, R, L) via aioconsole.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from dataclasses import dataclass, field
from typing import Optional

try:
    import aioconsole
except ImportError:
    aioconsole = None

from rich.columns import Columns
from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from config import BotConfig

logger = logging.getLogger("btc_sniper.cli.dashboard")


@dataclass
class TradeHistoryEntry:
    """Single row for trade history display."""
    number: int
    time_str: str
    result: str
    side: str
    odds: float
    gap: float
    cvd_pct: float
    velocity: float
    spread: float
    slippage: float
    claim: str


@dataclass
class DashboardState:
    """Shared state that the dashboard reads from."""
    # Header
    bot_mode: str = "INIT"
    window_id: str = "—"
    time_remaining: int = 0
    wallet_type: str = "PROXY"
    balance: float = 0.0
    unclaimed: float = 0.0
    paper_mode: bool = True
    eoa_warning: bool = False
    bot_version: str = "2.3"

    # Price & Gap
    hl_price: float = 0.0
    strike_price: float = 0.0
    gap: float = 0.0
    gap_direction: str = "NEUTRAL"
    gap_threshold: float = 45.0
    velocity: float = 0.0
    atr: float = 0.0
    vol_regime: str = "NORM"

    # CVD
    buy_volume: float = 0.0
    sell_volume: float = 0.0
    cvd_net: float = 0.0
    avg_vol_per_min: float = 0.0
    cvd_threshold: float = 0.0
    cvd_aligned: bool = False
    cvd_direction: str = "MIXED"

    # Order Book
    up_ask: float = 0.0
    up_bid: float = 0.0
    down_ask: float = 0.0
    down_bid: float = 0.0
    spread_pct: float = 0.0
    expected_odds: float = 0.0
    mispricing: bool = False

    # Gates
    gate_statuses: dict[int, bool] = field(default_factory=lambda: {i: False for i in range(1, 8)})
    gate_values: dict[int, str] = field(default_factory=lambda: {i: "—" for i in range(1, 8)})
    chainlink_age_sec: float = 0.0
    poly_sync_latency_sec: float = 0.0

    # Session P&L
    total_pnl: float = 0.0
    wins: int = 0
    losses: int = 0
    skips: int = 0
    win_rate: float = 0.0
    trade_history: list[TradeHistoryEntry] = field(default_factory=list)

    # Status
    is_lockdown: bool = False
    lockdown_reason: str = ""
    paused: bool = False
    hedge_mode_enabled: bool = False
    up_armed: bool = False
    down_armed: bool = False


class Dashboard:
    """6-panel rich.Live terminal dashboard."""

    def __init__(self, cfg: BotConfig) -> None:
        self._cfg = cfg
        self._console = Console()
        self._state = DashboardState(
            paper_mode=cfg.PAPER_TRADING_MODE,
            bot_version=cfg.BOT_VERSION,
        )
        self._running: bool = False
        self._live: Optional[Live] = None
        
        # Throttling controls
        self._last_orderbook_update = 0.0
        self._cached_orderbook_panel: Optional[Panel] = None
        self._last_trade_count = 0
        self._cached_history_panel: Optional[Panel] = None
        
        self._show_locks: bool = False
        self._quit_requested: bool = False

    @property
    def state(self) -> DashboardState:
        """Mutable dashboard state — updated by engine."""
        return self._state

    @property
    def quit_requested(self) -> bool:
        return self._quit_requested

    async def run(self) -> None:
        """Start the dashboard rendering loop and keyboard listener."""
        self._running = True
        refresh_rate = self._cfg.CLI_REFRESH_RATE

        kb_task = None
        if aioconsole is not None:
            kb_task = asyncio.create_task(self._keyboard_listener())

        try:
            with Live(
                self._build_layout(),
                console=self._console,
                refresh_per_second=refresh_rate,
                transient=False,
                screen=True,
            ) as live:
                self._live = live
                while self._running:
                    live.update(self._build_layout())
                    await asyncio.sleep(1.0 / refresh_rate)
        except asyncio.CancelledError:
            pass
        finally:
            self._running = False
            if kb_task:
                kb_task.cancel()

    def stop(self) -> None:
        """Stop the dashboard."""
        self._running = False

    async def _keyboard_listener(self) -> None:
        """Non-blocking keyboard input loop via aioconsole."""
        while self._running:
            try:
                cmd = await aioconsole.ainput()
                cmd = cmd.strip().upper()
                if cmd == "Q":
                    self._quit_requested = True
                    self.stop()
                elif cmd == "P":
                    self._state.paused = True
                elif cmd == "R":
                    self._state.paused = False
                elif cmd == "L":
                    self._show_locks = not self._show_locks
            except (asyncio.CancelledError, EOFError):
                break
            except Exception:
                await asyncio.sleep(1)

    # ═══════════════════════════════════════════════════
    # LAYOUT BUILDER
    # ═══════════════════════════════════════════════════

    def _build_layout(self) -> Layout:
        """Build the complete 6-panel layout + controls footer."""
        layout = Layout()

        layout.split_column(
            Layout(name="header", size=5),
            Layout(name="body", ratio=1),
            Layout(name="footer", size=14),
            Layout(name="controls", size=3),
        )

        layout["body"].split_row(
            Layout(name="left", ratio=1),
            Layout(name="right", ratio=1),
        )

        layout["left"].split_column(
            Layout(name="price", ratio=1),
            Layout(name="cvd", ratio=1),
        )

        layout["right"].split_column(
            Layout(name="orderbook", ratio=1),
            Layout(name="gates", ratio=1),
        )

        # Assign panels
        layout["header"].update(self._panel_a_header())
        layout["price"].update(self._panel_b_price())
        layout["cvd"].update(self._panel_c_cvd())
        layout["orderbook"].update(self._panel_d_orderbook())
        layout["gates"].update(self._panel_e_gates())
        layout["footer"].update(self._panel_f_pnl())
        
        # Lock overlay logic
        if self._show_locks:
            layout["gates"].update(self._panel_locks_overlay())

        # Controls
        controls_text = Text("[Q] Quit graceful  [P] Pause (no orders)  [R] Resume  [L] Show locks", justify="center", style="dim white")
        layout["controls"].update(Panel(controls_text, border_style="dim"))

        return layout

    # ═══════════════════════════════════════════════════
    # PANEL A — Header Bar
    # ═══════════════════════════════════════════════════

    def _panel_a_header(self) -> Panel:
        s = self._state
        mode_color = "green"
        if s.is_lockdown:
            mode_color = "red"
        elif s.bot_mode in ("ARMED", "SKIP"):
            mode_color = "yellow"

        line1 = Text()
        line1.append(f"BTC SNIPER v{s.bot_version}  ", style="bold white")

        if s.paper_mode:
            line1.append(" [PAPER MODE] ", style="bold black on yellow")
            line1.append("  ")
        if s.eoa_warning:
            line1.append(" [EOA - MANUAL CLAIM] ", style="bold black on red")
            line1.append("  ")
        if s.paused:
            line1.append(" [PAUSED] ", style="bold black on cyan")
            line1.append("  ")
        if s.hedge_mode_enabled:
            line1.append(" [HEDGE MODE] ", style="bold white on magenta")
            line1.append("  ")

        line1.append(f"[{s.bot_mode}]", style=f"bold {mode_color}")
        line1.append(f"  Window: {s.window_id}   ", style="cyan")
        line1.append(f"T-{s.time_remaining}s  ", style="bold white")
        line1.append(time.strftime("%H:%M:%S"), style="dim")

        line2 = Text()
        line2.append(f"Wallet: {s.wallet_type}", style="cyan")
        line2.append(f"  │  Balance: ${s.balance:.2f}", style="green")
        line2.append(f"  │  Unclaimed: ${s.unclaimed:.2f}", style="yellow" if s.unclaimed > 0 else "dim")

        # Sync indicators
        cl_color = "green" if s.chainlink_age_sec < self._cfg.CHAINLINK_MAX_AGE_SEC else "red"
        py_color = "green" if s.poly_sync_latency_sec < self._cfg.POLY_STALE_THRESHOLD_SEC else "red"
        line2.append(f"  │  CL: {s.chainlink_age_sec:.1f}s", style=cl_color)
        line2.append(f"  │  PY: {s.poly_sync_latency_sec:.1f}s", style=py_color)

        if s.is_lockdown:
            line2.append(f"  │  LOCKDOWN: {s.lockdown_reason}", style="bold red")

        return Panel(Group(line1, line2), title="[bold]POLYMARKET BTC SNIPER", border_style=mode_color, height=5)

    # ═══════════════════════════════════════════════════
    # PANEL B — Live Price & Gap
    # ═══════════════════════════════════════════════════

    def _panel_b_price(self) -> Panel:
        s = self._state
        if s.hl_price <= 0:
            return Panel("— WAITING DATA —", title="[bold cyan]Live Price & Gap", border_style="dim")

        # Color based on direction: UP=green, DOWN=red
        gap_color = "green" if s.gap_direction == "UP" else "red" if s.gap_direction == "DOWN" else "white"
        dir_symbol = "▲" if s.gap_direction == "UP" else "▼" if s.gap_direction == "DOWN" else "—"

        table = Table(show_header=False, show_edge=False, pad_edge=False, expand=True)
        table.add_column("Label", style="dim", ratio=1)
        table.add_column("Value", ratio=2)

        table.add_row("HL Price", f"[bold white]${s.hl_price:,.2f}")
        table.add_row("Strike", f"[white]${s.strike_price:,.2f}")
        table.add_row("GAP", f"[bold {gap_color}]{dir_symbol} ${abs(s.gap):,.2f}  [bold]{s.gap_direction}[/]")
        table.add_row("Threshold", f"[dim]${s.gap_threshold:,.2f} ({s.vol_regime})")
        table.add_row("Velocity", f"[white]${s.velocity:,.2f} / {self._cfg.VELOCITY_MIN_DELTA}")
        table.add_row("ATR (60m)", f"[white]${s.atr:,.2f}  [{s.vol_regime}]")

        if s.hedge_mode_enabled:
            up_status = "[bold green]ARMED" if s.up_armed else "[dim]WAITING"
            down_status = "[bold green]ARMED" if s.down_armed else "[dim]WAITING"
            table.add_row("HEDGE UP", f"{up_status} [dim](ask <= {self._cfg.HEDGE_MODE_ODDS_MAX})")
            table.add_row("HEDGE DOWN", f"{down_status} [dim](ask <= {self._cfg.HEDGE_MODE_ODDS_MAX})")

        return Panel(table, title="[bold cyan]Live Price & Gap", border_style="cyan")

    # ═══════════════════════════════════════════════════
    # PANEL C — CVD Chart
    # ═══════════════════════════════════════════════════

    def _panel_c_cvd(self) -> Panel:
        s = self._state
        if s.avg_vol_per_min <= 0:
            return Panel("— WAITING DATA —", title="[bold green]CVD Analysis", border_style="dim")

        cvd_pct = abs(s.cvd_net) / max(s.cvd_threshold, 1) * 100
        bar_width = 25
        buy_bar_len = min(int(s.buy_volume / max(s.avg_vol_per_min, 1) * bar_width), bar_width)
        sell_bar_len = min(int(s.sell_volume / max(s.avg_vol_per_min, 1) * bar_width), bar_width)
        net_bar_len = min(int(cvd_pct / 100 * bar_width), bar_width)

        aligned_label = "[bold green]ALIGNED ↑" if s.cvd_aligned and s.cvd_net > 0 else (
            "[bold green]ALIGNED ↓" if s.cvd_aligned and s.cvd_net < 0 else "[bold red]MIXED"
        )

        lines = Text()
        lines.append(f"  BUY  ", style="green")
        lines.append("█" * buy_bar_len + "░" * (bar_width - buy_bar_len), style="green")
        lines.append(f"  ${s.buy_volume:,.0f}\n")
        lines.append(f"  SELL ", style="red")
        lines.append("█" * sell_bar_len + "░" * (bar_width - sell_bar_len), style="red")
        lines.append(f"  ${s.sell_volume:,.0f}\n")
        lines.append(f"  NET  ", style="cyan")
        lines.append("█" * net_bar_len + "░" * (bar_width - net_bar_len), style="cyan" if s.cvd_net >= 0 else "red")
        lines.append(f"  ${s.cvd_net:,.0f} ({cvd_pct:.0f}%)\n\n")
        lines.append(f"  Avg Vol/min: ${s.avg_vol_per_min:,.0f}  │  Threshold: ${s.cvd_threshold:,.0f}  │  ")
        lines.append(aligned_label)

        return Panel(lines, title="[bold green]CVD Analysis (rolling 60s)", border_style="green")

    # ═══════════════════════════════════════════════════
    # PANEL D — Order Book Depth
    # ═══════════════════════════════════════════════════

    def _panel_d_orderbook(self) -> Panel:
        s = self._state
        now = time.time()
        
        # Throttled update
        if self._cached_orderbook_panel and (now - self._last_orderbook_update < self._cfg.CLI_ORDERBOOK_UPDATE_SEC):
            return self._cached_orderbook_panel

        if s.up_ask <= 0:
            return Panel("— WAITING DATA —", title="[bold yellow]Order Book Depth", border_style="dim")

        table = Table(show_header=False, show_edge=False, expand=True, pad_edge=False)
        table.add_column("Side", width=4)
        table.add_column("Type", width=4)
        table.add_column("Bar", ratio=1)
        table.add_column("Price", justify="right", width=8)

        bar_w = 15
        up_ask_b = "█" * int(s.up_ask * bar_w) + "░" * (bar_w - int(s.up_ask * bar_w))
        up_bid_b = "█" * int(s.up_bid * bar_w) + "░" * (bar_w - int(s.up_bid * bar_w))
        dn_ask_b = "█" * int(s.down_ask * bar_w) + "░" * (bar_w - int(s.down_ask * bar_w))
        dn_bid_b = "█" * int(s.down_bid * bar_w) + "░" * (bar_w - int(s.down_bid * bar_w))

        table.add_row("[green]UP", "ask", f"[green]{up_ask_b}", f"${s.up_ask:.2f}")
        table.add_row("[green]UP", "bid", f"[dim green]{up_bid_b}", f"${s.up_bid:.2f}")
        table.add_row("[red]DN", "ask", f"[red]{dn_ask_b}", f"${s.down_ask:.2f}")
        table.add_row("[red]DN", "bid", f"[dim red]{dn_bid_b}", f"${s.down_bid:.2f}")

        info = Text()
        spread_color = "green" if s.spread_pct <= self._cfg.SPREAD_MAX_PCT else "red"
        info.append(f"\n  Spread   : ", style="dim")
        info.append(f"{s.spread_pct:.2f}%  ", style=spread_color)
        info.append("OK\n" if s.spread_pct <= self._cfg.SPREAD_MAX_PCT else "TOO WIDE\n", style=spread_color)
        
        info.append("  Mispricing: ", style="dim")
        if s.mispricing:
            info.append(f"YES (${s.up_ask:.2f} < expected ${s.expected_odds:.2f})", style="green")
        else:
            info.append(f"NO EDGE (${s.up_ask:.2f} >= expected ${s.expected_odds:.2f})", style="dim")

        content = Group(table, info)
        panel = Panel(content, title="[bold yellow]Order Book Depth", border_style="yellow")
        
        self._cached_orderbook_panel = panel
        self._last_orderbook_update = now
        return panel

    # ═══════════════════════════════════════════════════
    # PANEL E — Safety Gates
    # ═══════════════════════════════════════════════════

    def _panel_e_gates(self) -> Panel:
        s = self._state
        gate_names = {
            1: "Gap Threshold",
            2: "CVD Alignment",
            3: "Dual Side Liq",
            4: "Odds Boundary",
            5: "Golden Window",
            6: "Velocity",
            7: "No Dup Order",
        }

        table = Table(show_header=False, show_edge=False, expand=True, pad_edge=False)
        table.add_column("Gate", ratio=2)
        table.add_column("Status", width=6, justify="center")
        table.add_column("Value", ratio=2)

        for i in range(1, 8):
            # JSON keys are always strings, handle both int and str
            status = s.gate_statuses.get(i) or s.gate_statuses.get(str(i), False)
            val = s.gate_values.get(i) or s.gate_values.get(str(i), "—")

            if status:
                st = "[bold green]PASS"
                reason = ""
            elif val == "DISABLED":
                st = "[dim]N-A"
                reason = ""
            else:
                st = "[bold red]FAIL"
                reason = f" [dim]({val})"
            
            table.add_row(f"[{i}] {gate_names.get(i, '?')}", st, reason)

        cl_color = "green" if s.chainlink_age_sec < self._cfg.CHAINLINK_MAX_AGE_SEC else "red"
        cl_status = "OK" if s.chainlink_age_sec < self._cfg.CHAINLINK_MAX_AGE_SEC else "STALE"
        
        py_color = "green" if s.poly_sync_latency_sec < self._cfg.POLY_STALE_THRESHOLD_SEC else "red"
        py_status = "OK" if s.poly_sync_latency_sec < self._cfg.POLY_STALE_THRESHOLD_SEC else "STALE"

        info = Text("\n  Chainlink age: ", style="dim")
        info.append(f"{s.chainlink_age_sec:.1f}s ", style=cl_color)
        info.append(cl_status, style=f"bold {cl_color}")
        info.append("  │  Poly sync: ", style="dim")
        info.append(f"{s.poly_sync_latency_sec:.1f}s ", style=py_color)
        info.append(py_status, style=f"bold {py_color}")
        
        return Panel(Group(table, info), title="[bold magenta]Safety Gates", border_style="magenta")

    # ═══════════════════════════════════════════════════
    # PANEL F — Session P&L + Trade History
    # ═══════════════════════════════════════════════════

    def _panel_f_pnl(self) -> Panel:
        s = self._state
        
        # Throttled update: only rebuild table if trades changed
        current_trade_count = len(s.trade_history)
        if self._cached_history_panel and self._last_trade_count == current_trade_count:
            # We still need to update the header line for P&L changes, but we could just redraw.
            # Since trade list is short, rendering isn't too heavy, but we'll optimize it later if needed.
            pass

        pnl_color = "green" if s.total_pnl >= 0 else "red"
        stats = Text()
        stats.append(f"  SESSION P&L: ", style="bold white")
        stats.append(f"${s.total_pnl:+.2f}  ", style=f"bold {pnl_color}")
        stats.append(f"WIN:{s.wins}  LOSS:{s.losses}  SKIP:{s.skips}  ", style="white")
        wr_str = f"{s.win_rate * 100:.1f}%" if (s.wins + s.losses) > 0 else "—"
        stats.append(f"WIN RATE:{wr_str}\n", style="cyan bold")

        table = Table(show_header=True, show_edge=False, expand=True, padding=(0, 1))
        for col in ["#", "TIME", "RES", "SIDE", "ODDS", "GAP", "CVD%", "VEL", "SPR", "SLIP", "CLAIM"]:
            table.add_column(col, justify="center" if col != "TIME" else "left", style="dim white")

        max_rows = self._cfg.CLI_TRADE_LOG_ROWS
        history = s.trade_history[-max_rows:]
        for entry in history:
            res_style = "green" if entry.result == "WIN" else "red" if entry.result == "LOSS" else "yellow"
            table.add_row(
                f"{entry.number:02d}", entry.time_str, f"[{res_style}]{entry.result}",
                entry.side, f"{entry.odds:.2f}", f"${entry.gap:+.0f}",
                f"{entry.cvd_pct:.0f}%", f"${entry.velocity:+.0f}",
                f"{entry.spread:.1f}%", f"{entry.slippage:.1f}%", entry.claim
            )

        if not history:
            table.add_row(*["—"] * 11)

        panel = Panel(Group(stats, table), border_style="white")
        self._cached_history_panel = panel
        self._last_trade_count = current_trade_count
        return panel

    def _panel_locks_overlay(self) -> Panel:
        """Modal overlay displaying active locks."""
        s = self._state
        lines = Text("🔒 ACTIVE LOCKS & ALERTS\n\n", style="bold red", justify="center")
        if s.is_lockdown:
            lines.append(f"LOCKDOWN ACTIVE: {s.lockdown_reason}\n", style="bold red")
        else:
            lines.append("No active lockdowns.\n", style="green")
            
        if s.paused:
            lines.append("BOT IS PAUSED (No execution)\n", style="yellow")
            
        return Panel(lines, title="[bold red]System Status", border_style="red")
