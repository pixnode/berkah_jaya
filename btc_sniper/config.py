# === FILE: btc_sniper/config.py ===
"""
Polymarket BTC Sniper v2.3 — Configuration Loader & Validator.
Loads all parameters from .env, validates constraints, prints startup banner.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

logger = logging.getLogger("btc_sniper.config")


class ConfigurationError(Exception):
    """Raised when .env configuration is invalid or incomplete."""


def _env_str(key: str, default: Optional[str] = None) -> str:
    val = os.getenv(key, default)
    if val is None:
        return ""
    return val.strip()


def _env_float(key: str, default: float) -> float:
    raw = os.getenv(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw.strip())
    except ValueError:
        raise ConfigurationError(f"{key}={raw!r} is not a valid float")


def _env_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw.strip())
    except ValueError:
        raise ConfigurationError(f"{key}={raw!r} is not a valid integer")


def _env_bool(key: str, default: bool) -> bool:
    raw = os.getenv(key)
    if raw is None or raw.strip() == "":
        return default
    val = raw.strip().lower()
    if val in ("true", "1", "yes"):
        return True
    if val in ("false", "0", "no"):
        return False
    raise ConfigurationError(f"{key}={raw!r} is not a valid boolean")


@dataclass(frozen=True)
class BotConfig:
    """Immutable configuration for Polymarket BTC Sniper v2.3."""

    # ── WALLET & AUTH ─────────────────────────────────
    POLYMARKET_PRIVATE_KEY: str = ""
    POLYMARKET_PROXY_WALLET: str = ""
    POLY_WALLET_TYPE: str = "safe"
    POLY_CHAIN_ID: int = 137
    POLY_API_KEY: str = ""
    POLY_API_SECRET: str = ""
    POLY_API_PASSPHRASE: str = ""
    CLOB_API_VERSION: str = "v1"

    # ── CONNECTIONS ───────────────────────────────────
    CLOB_HOST: str = "https://clob.polymarket.com"
    RELAYER_URL: str = "https://relayer.polymarket.com"
    GAMMA_API_URL: str = "https://gamma-api.polymarket.com"
    POLYGON_RPC_URL: str = ""
    HYPERLIQUID_WS_URL: str = "wss://api.hyperliquid.xyz/ws"
    HYPERLIQUID_API_KEY: str = ""
    POLY_WS_URL: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    CHAINLINK_CONTRACT_ADDRESS: str = "0xc907E116054Ad103354f2D350FD2514433D57F6F"

    # ── STRATEGY CORE ─────────────────────────────────
    BASE_SHARES: float = 1.0
    MAX_POSITION_USD: float = 10.0
    GAP_THRESHOLD_DEFAULT: float = 15.0
    GAP_THRESHOLD_LOW_VOL: float = 60.0
    GAP_THRESHOLD_HIGH_VOL: float = 35.0
    ATR_LOW_THRESHOLD: float = 50.0
    ATR_HIGH_THRESHOLD: float = 150.0
    ATR_LOOKBACK_CANDLES: int = 4

    # ── ODDS BOUNDARY ─────────────────────────────────
    ODDS_MIN: float = 0.01
    ODDS_MAX: float = 0.30
    ODDS_SWEET_SPOT_LOW: float = 0.01
    ODDS_SWEET_SPOT_HIGH: float = 0.30

    # ── CVD ────────────────────────────────────────────
    CVD_VOLUME_WINDOW_MINUTES: int = 30
    CVD_THRESHOLD_PCT: float = 25.0
    CVD_CALC_INTERVAL_MS: int = 500

    # ── GATE TOGGLES ──────────────────────────────────
    GATE3_ENABLED: bool = True

    # ── STRATEGY MODES ────────────────────────────────
    HEDGE_STRATEGY: str = "DIRECTIONAL"
    DIRECTIONAL_MAX_ODDS: float = 0.40
    SMART_HEDGE_PAIR_MAX: float = 0.80
    TEMPORAL_MAX_SINGLE_ODDS: float = 0.40
    TEMPORAL_MAX_TOTAL_COST: float = 0.80
    HEDGE_MIN_DEPTH_USDC: float = 50.0

    # ── HEDGE MODE (Legacy/General) ───────────────────
    HEDGE_MODE_ENABLED: bool = False
    HEDGE_MODE_ODDS_MAX: float = 0.50
    HEDGE_PAIR_MAX_COST: float = 0.35

    # ── TIMING & VELOCITY ─────────────────────────────
    GOLDEN_WINDOW_START: int = 60
    GOLDEN_WINDOW_END: int = 42
    VELOCITY_ENABLED: bool = True
    VELOCITY_MIN_DELTA: float = 15.0
    VELOCITY_WINDOW_SECONDS: float = 1.5

    # ── SLIPPAGE ──────────────────────────────────────
    SLIPPAGE_THRESHOLD_NORMAL: float = 5.0
    SLIPPAGE_THRESHOLD_ELEVATED: float = 7.0
    SLIPPAGE_THRESHOLD_HIGH: float = 10.0
    SLIPPAGE_THRESHOLD_ABS_LOW_ODDS: float = 0.05
    SLIPPAGE_CHECK_ENABLED: bool = True
    SPREAD_MAX_PCT: float = 3.0
    MISPRICING_MULTIPLIER: float = 0.15
    MISPRICING_MIN_EDGE: float = 0.02

    # ── RISK & CIRCUIT BREAKER ────────────────────────
    CIRCUIT_BREAKER_MAX_LOSS: int = 3
    COOLDOWN_CIRCUIT_BREAKER_SEC: int = 900
    COOLDOWN_DATA_STALE_SEC: int = 300
    MAX_DAILY_LOSS_USD: float = 0.0
    MIN_TRADE_RESERVE: int = 5

    # ── DATA FRESHNESS ────────────────────────────────
    CHAINLINK_MAX_AGE_SEC: int = 10
    CHAINLINK_MAX_AGE_ENTRY_SEC: int = 25
    CHAINLINK_VOLATILITY_SKIP_USD: float = 35.0
    CHAINLINK_POLL_INTERVAL_SEC: int = 3
    WS_HEARTBEAT_INTERVAL_SEC: int = 3
    WS_STALE_THRESHOLD_SEC: int = 5
    POLY_STALE_THRESHOLD_SEC: int = 120
    WS_RECONNECT_MAX_RETRY: int = 5
    WS_RECONNECT_BASE_DELAY_SEC: int = 1
    WS_RECONNECT_MAX_DELAY_SEC: int = 30
    SYNC_LATENCY_MAX_SEC: int = 10
    QUEUE_HL_MAXSIZE: int = 2000
    MIN_TRADE_SIZE_USD: float = 0.0
    SAFETY_MONITOR_STARTUP_GRACE_SEC: int = 60

    # ── BLOCKCHAIN & CLAIM ────────────────────────────
    POLYGON_GAS_TIP_MULTIPLIER: float = 1.0
    USDC_ADDRESS: str = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
    BALANCE_REFRESH_INTERVAL_SEC: int = 30
    CLAIM_RETRY_MAX: int = 3
    CLAIM_RETRY_TIMEOUT_SEC: int = 30
    CLAIM_RETRY_INTERVAL_SEC: int = 60

    # ── LOGGING & AUDIT ───────────────────────────────
    OUTPUT_DIR: str = "./output"
    TRADE_LOG_FILE: str = "trade_log.csv"
    SKIP_LOG_FILE: str = "skip_log.csv"
    MARKET_SNAPSHOT_FILE: str = "market_snapshot.csv"
    SESSION_SUMMARY_FILE: str = "session_summary.csv"
    EVENT_LOG_FILE: str = "event_log.csv"
    STATE_FILE: str = "engine_state.json"
    LOG_FLUSH_INTERVAL_SEC: int = 5
    LOG_ROTATION_DAYS: int = 30
    SNAPSHOT_INTERVAL_SEC: int = 5
    STATE_SNAPSHOT_INTERVAL_SEC: int = 5

    # ── OPERATIONAL ───────────────────────────────────
    PAPER_TRADING_MODE: bool = True
    BOT_VERSION: str = "2.3"
    LOG_LEVEL: str = "INFO"
    CLI_REFRESH_RATE: int = 4
    CLI_ORDERBOOK_UPDATE_SEC: int = 2
    CLI_TRADE_LOG_ROWS: int = 10


def load_config(env_path: Optional[str] = None) -> BotConfig:
    """Load BotConfig from .env file. Raises ConfigurationError on failure."""
    if env_path:
        load_dotenv(env_path, override=True)
    else:
        load_dotenv(override=True)

    cfg = BotConfig(
        POLYMARKET_PRIVATE_KEY=_env_str("POLYMARKET_PRIVATE_KEY", ""),
        POLYMARKET_PROXY_WALLET=_env_str("POLYMARKET_PROXY_WALLET", ""),
        POLY_WALLET_TYPE=_env_str("POLY_WALLET_TYPE", "safe"),
        POLY_CHAIN_ID=_env_int("POLY_CHAIN_ID", 137),
        POLY_API_KEY=_env_str("POLY_API_KEY", ""),
        POLY_API_SECRET=_env_str("POLY_API_SECRET", ""),
        POLY_API_PASSPHRASE=_env_str("POLY_API_PASSPHRASE", ""),
        CLOB_API_VERSION=_env_str("CLOB_API_VERSION", "v1").lower(),
        CLOB_HOST=_env_str("CLOB_HOST", "https://clob.polymarket.com"),
        RELAYER_URL=_env_str("RELAYER_URL", "https://relayer.polymarket.com"),
        GAMMA_API_URL=_env_str("GAMMA_API_URL", "https://gamma-api.polymarket.com"),
        POLYGON_RPC_URL=_env_str("POLYGON_RPC_URL", ""),
        HYPERLIQUID_WS_URL=_env_str("HYPERLIQUID_WS_URL", "wss://api.hyperliquid.xyz/ws"),
        HYPERLIQUID_API_KEY=_env_str("HYPERLIQUID_API_KEY", ""),
        POLY_WS_URL=_env_str("POLY_WS_URL", "wss://ws-subscriptions-clob.polymarket.com/ws/market"),
        CHAINLINK_CONTRACT_ADDRESS=_env_str("CHAINLINK_CONTRACT_ADDRESS", "0xc907E116054Ad103354f2D350FD2514433D57F6F"),
        BASE_SHARES=_env_float("BASE_SHARES", 1.0),
        MAX_POSITION_USD=_env_float("MAX_POSITION_USD", 10.0),
        GAP_THRESHOLD_DEFAULT=_env_float("GAP_THRESHOLD_DEFAULT", 10.0),
        GAP_THRESHOLD_LOW_VOL=_env_float("GAP_THRESHOLD_LOW_VOL", 10.0),
        GAP_THRESHOLD_HIGH_VOL=_env_float("GAP_THRESHOLD_HIGH_VOL", 10.0),
        ATR_LOW_THRESHOLD=_env_float("ATR_LOW_THRESHOLD", 50.0),
        ATR_HIGH_THRESHOLD=_env_float("ATR_HIGH_THRESHOLD", 150.0),
        ATR_LOOKBACK_CANDLES=_env_int("ATR_LOOKBACK_CANDLES", 12),
        ODDS_MIN=_env_float("ODDS_MIN", 0.58),
        ODDS_MAX=_env_float("ODDS_MAX", 0.30),
        ODDS_SWEET_SPOT_LOW=_env_float("ODDS_SWEET_SPOT_LOW", 0.62),
        ODDS_SWEET_SPOT_HIGH=_env_float("ODDS_SWEET_SPOT_HIGH", 0.76),
        CVD_VOLUME_WINDOW_MINUTES=_env_int("CVD_VOLUME_WINDOW_MINUTES", 30),
        CVD_THRESHOLD_PCT=_env_float("CVD_THRESHOLD_PCT", 25.0),
        CVD_CALC_INTERVAL_MS=_env_int("CVD_CALC_INTERVAL_MS", 500),
        GATE3_ENABLED=_env_bool("GATE3_ENABLED", True),
        HEDGE_STRATEGY=_env_str("HEDGE_STRATEGY", "DIRECTIONAL"),
        DIRECTIONAL_MAX_ODDS=_env_float("DIRECTIONAL_MAX_ODDS", 0.40),
        SMART_HEDGE_PAIR_MAX=_env_float("SMART_HEDGE_PAIR_MAX", 0.80),
        TEMPORAL_MAX_SINGLE_ODDS=_env_float("TEMPORAL_MAX_SINGLE_ODDS", 0.40),
        TEMPORAL_MAX_TOTAL_COST=_env_float("TEMPORAL_MAX_TOTAL_COST", 0.80),
        HEDGE_MIN_DEPTH_USDC=_env_float("HEDGE_MIN_DEPTH_USDC", 50.0),
        HEDGE_MODE_ENABLED=_env_bool("HEDGE_MODE_ENABLED", False),
        HEDGE_MODE_ODDS_MAX=_env_float("HEDGE_MODE_ODDS_MAX", 0.50),
        HEDGE_PAIR_MAX_COST=_env_float("HEDGE_PAIR_MAX_COST", 0.35),
        VELOCITY_ENABLED=_env_bool("VELOCITY_ENABLED", True),
        VELOCITY_MIN_DELTA=_env_float("VELOCITY_MIN_DELTA", 15.0),
        VELOCITY_WINDOW_SECONDS=_env_float("VELOCITY_WINDOW_SECONDS", 1.5),
        GOLDEN_WINDOW_START=_env_int("GOLDEN_WINDOW_START", 60),
        GOLDEN_WINDOW_END=_env_int("GOLDEN_WINDOW_END", 42),
        SLIPPAGE_THRESHOLD_NORMAL=_env_float("SLIPPAGE_THRESHOLD_NORMAL", 5.0),
        SLIPPAGE_THRESHOLD_ELEVATED=_env_float("SLIPPAGE_THRESHOLD_ELEVATED", 7.0),
        SLIPPAGE_THRESHOLD_HIGH=_env_float("SLIPPAGE_THRESHOLD_HIGH", 10.0),
        SLIPPAGE_THRESHOLD_ABS_LOW_ODDS=_env_float("SLIPPAGE_THRESHOLD_ABS_LOW_ODDS", 0.05),
        SLIPPAGE_CHECK_ENABLED=_env_bool("SLIPPAGE_CHECK_ENABLED", True),
        SPREAD_MAX_PCT=_env_float("SPREAD_MAX_PCT", 3.0),
        MISPRICING_MULTIPLIER=_env_float("MISPRICING_MULTIPLIER", 0.15),
        MISPRICING_MIN_EDGE=_env_float("MISPRICING_MIN_EDGE", 0.02),
        CIRCUIT_BREAKER_MAX_LOSS=_env_int("CIRCUIT_BREAKER_MAX_LOSS", 3),
        COOLDOWN_CIRCUIT_BREAKER_SEC=_env_int("COOLDOWN_CIRCUIT_BREAKER_SEC", 900),
        COOLDOWN_DATA_STALE_SEC=_env_int("COOLDOWN_DATA_STALE_SEC", 300),
        MAX_DAILY_LOSS_USD=_env_float("MAX_DAILY_LOSS_USD", 0.0),
        MIN_TRADE_RESERVE=_env_int("MIN_TRADE_RESERVE", 5),
        CHAINLINK_MAX_AGE_SEC=_env_int("CHAINLINK_MAX_AGE_SEC", 10),
        CHAINLINK_MAX_AGE_ENTRY_SEC=_env_int("CHAINLINK_MAX_AGE_ENTRY_SEC", 25),
        CHAINLINK_VOLATILITY_SKIP_USD=_env_float("CHAINLINK_VOLATILITY_SKIP_USD", 35.0),
        CHAINLINK_POLL_INTERVAL_SEC=_env_int("CHAINLINK_POLL_INTERVAL_SEC", 3),
        WS_HEARTBEAT_INTERVAL_SEC=_env_int("WS_HEARTBEAT_INTERVAL_SEC", 3),
        WS_STALE_THRESHOLD_SEC=_env_int("WS_STALE_THRESHOLD_SEC", 5),
        POLY_STALE_THRESHOLD_SEC=_env_int("POLY_STALE_THRESHOLD_SEC", 120),
        WS_RECONNECT_MAX_RETRY=_env_int("WS_RECONNECT_MAX_RETRY", 5),
        WS_RECONNECT_BASE_DELAY_SEC=_env_int("WS_RECONNECT_BASE_DELAY_SEC", 1),
        WS_RECONNECT_MAX_DELAY_SEC=_env_int("WS_RECONNECT_MAX_DELAY_SEC", 30),
        SYNC_LATENCY_MAX_SEC=_env_int("SYNC_LATENCY_MAX_SEC", 10),
        QUEUE_HL_MAXSIZE=_env_int("QUEUE_HL_MAXSIZE", 2000),
        MIN_TRADE_SIZE_USD=_env_float("MIN_TRADE_SIZE_USD", 0.0),
        SAFETY_MONITOR_STARTUP_GRACE_SEC=_env_int("SAFETY_MONITOR_STARTUP_GRACE_SEC", 60),
        POLYGON_GAS_TIP_MULTIPLIER=_env_float("POLYGON_GAS_TIP_MULTIPLIER", 1.0),
        CLAIM_RETRY_MAX=_env_int("CLAIM_RETRY_MAX", 3),
        CLAIM_RETRY_TIMEOUT_SEC=_env_int("CLAIM_RETRY_TIMEOUT_SEC", 30),
        CLAIM_RETRY_INTERVAL_SEC=_env_int("CLAIM_RETRY_INTERVAL_SEC", 60),
        OUTPUT_DIR=_env_str("OUTPUT_DIR", "./output"),
        TRADE_LOG_FILE=_env_str("TRADE_LOG_FILE", "trade_log.csv"),
        SKIP_LOG_FILE=_env_str("SKIP_LOG_FILE", "skip_log.csv"),
        MARKET_SNAPSHOT_FILE=_env_str("MARKET_SNAPSHOT_FILE", "market_snapshot.csv"),
        SESSION_SUMMARY_FILE=_env_str("SESSION_SUMMARY_FILE", "session_summary.csv"),
        EVENT_LOG_FILE=_env_str("EVENT_LOG_FILE", "event_log.csv"),
        STATE_FILE=_env_str("STATE_FILE", "engine_state.json"),
        LOG_FLUSH_INTERVAL_SEC=_env_int("LOG_FLUSH_INTERVAL_SEC", 5),
        LOG_ROTATION_DAYS=_env_int("LOG_ROTATION_DAYS", 30),
        SNAPSHOT_INTERVAL_SEC=_env_int("SNAPSHOT_INTERVAL_SEC", 5),
        STATE_SNAPSHOT_INTERVAL_SEC=_env_int("STATE_SNAPSHOT_INTERVAL_SEC", 5),
        PAPER_TRADING_MODE=_env_bool("PAPER_TRADING_MODE", True),
        BOT_VERSION=_env_str("BOT_VERSION", "2.3"),
        LOG_LEVEL=_env_str("LOG_LEVEL", "INFO"),
        CLI_REFRESH_RATE=_env_int("CLI_REFRESH_RATE", 4),
        CLI_ORDERBOOK_UPDATE_SEC=_env_int("CLI_ORDERBOOK_UPDATE_SEC", 2),
        CLI_TRADE_LOG_ROWS=_env_int("CLI_TRADE_LOG_ROWS", 10),
    )

    validate_config(cfg)
    return cfg


def validate_config(cfg: BotConfig) -> None:
    """Validate all config constraints. Raises ConfigurationError on failure in live mode."""
    is_paper = cfg.PAPER_TRADING_MODE

    # ── Required fields ───────────────────────────────
    required_live = [
        ("POLYMARKET_PRIVATE_KEY", cfg.POLYMARKET_PRIVATE_KEY),
        ("POLYMARKET_PROXY_WALLET", cfg.POLYMARKET_PROXY_WALLET),
        ("POLYGON_RPC_URL", cfg.POLYGON_RPC_URL),
    ]
    for name, val in required_live:
        if not val:
            if is_paper:
                logger.warning("WARNING: %s is empty — required for live mode", name)
            else:
                raise ConfigurationError(f"{name} is required — cannot be empty")

    if not is_paper:
        for name, val in [("POLY_API_KEY", cfg.POLY_API_KEY), ("POLY_API_SECRET", cfg.POLY_API_SECRET), ("POLY_API_PASSPHRASE", cfg.POLY_API_PASSPHRASE)]:
            if not val:
                raise ConfigurationError(f"{name} is required — cannot be empty")

    # ── Relational constraints ────────────────────────
    if not (cfg.ODDS_MIN <= cfg.ODDS_SWEET_SPOT_LOW <= cfg.ODDS_SWEET_SPOT_HIGH <= cfg.ODDS_MAX):
        raise ConfigurationError(
            f"Odds ordering violated: ODDS_MIN({cfg.ODDS_MIN}) <= "
            f"SWEET_LOW({cfg.ODDS_SWEET_SPOT_LOW}) <= "
            f"SWEET_HIGH({cfg.ODDS_SWEET_SPOT_HIGH}) <= "
            f"ODDS_MAX({cfg.ODDS_MAX}) required"
        )

    if not (cfg.GOLDEN_WINDOW_END < cfg.GOLDEN_WINDOW_START):
        raise ConfigurationError(
            f"GOLDEN_WINDOW_END({cfg.GOLDEN_WINDOW_END}) must be < "
            f"GOLDEN_WINDOW_START({cfg.GOLDEN_WINDOW_START})"
        )

    max_cost = cfg.BASE_SHARES * cfg.ODDS_MAX
    if max_cost > cfg.MAX_POSITION_USD:
        raise ConfigurationError(
            f"Position size check failed: BASE_SHARES({cfg.BASE_SHARES}) × "
            f"ODDS_MAX({cfg.ODDS_MAX}) = ${max_cost:.2f} > "
            f"MAX_POSITION_USD(${cfg.MAX_POSITION_USD:.2f})"
        )

    if cfg.ATR_LOW_THRESHOLD >= cfg.ATR_HIGH_THRESHOLD:
        raise ConfigurationError(
            f"ATR_LOW_THRESHOLD({cfg.ATR_LOW_THRESHOLD}) must be < "
            f"ATR_HIGH_THRESHOLD({cfg.ATR_HIGH_THRESHOLD})"
        )

    # ── Ensure output directory exists ────────────────
    output_path = Path(cfg.OUTPUT_DIR)
    output_path.mkdir(parents=True, exist_ok=True)

    # ── Print startup banner ──────────────────────────
    _print_startup_banner(cfg)


def print_paper_mode_warning(cfg: BotConfig) -> None:
    """Cetak warning box prominent jika PAPER_TRADING_MODE=True."""
    if not cfg.PAPER_TRADING_MODE:
        return
    lines = [
        "╔══════════════════════════════════════════════════╗",
        "║           !  PAPER TRADING MODE AKTIF  !         ║",
        "║  Semua order adalah SIMULASI.                    ║",
        "║  Untuk live trading: set PAPER_TRADING_MODE=false║",
        "╚══════════════════════════════════════════════════╝",
    ]
    for line in lines:
        try:
            print(line)
        except UnicodeEncodeError:
            print(line.replace("╔", "+").replace("═", "-").replace("╗", "+").replace("║", "|").replace("╚", "+").replace("╝", "+"))


def _print_startup_banner(cfg: BotConfig) -> None:
    """Print a rich startup banner with all active config values."""
    try:
        from rich.console import Console
        from rich.table import Table
    except ImportError:
        print(f"=== BTC SNIPER v{cfg.BOT_VERSION} ===")
        print_paper_mode_warning(cfg)
        return

    console = Console()
    print_paper_mode_warning(cfg)

    table = Table(title=f"BTC SNIPER v{cfg.BOT_VERSION} Configuration")
    table.add_column("Parameter", style="cyan", min_width=30)
    table.add_column("Value", style="white", min_width=20)

    sections = {
        "── Strategy ──": [
            ("Base Shares", f"{cfg.BASE_SHARES}"),
            ("Max Position USD", f"${cfg.MAX_POSITION_USD:.2f}"),
            ("Gap Threshold (Default)", f"${cfg.GAP_THRESHOLD_DEFAULT:.1f}"),
            ("Gap Threshold (Low Vol)", f"${cfg.GAP_THRESHOLD_LOW_VOL:.1f}"),
            ("Gap Threshold (High Vol)", f"${cfg.GAP_THRESHOLD_HIGH_VOL:.1f}"),
        ],
        "── Odds ──": [
            ("Odds Range", f"{cfg.ODDS_MIN} – {cfg.ODDS_MAX}"),
            ("Sweet Spot", f"{cfg.ODDS_SWEET_SPOT_LOW} – {cfg.ODDS_SWEET_SPOT_HIGH}"),
        ],
        "── Timing ──": [
            ("Golden Window", f"T-{cfg.GOLDEN_WINDOW_START}s → T-{cfg.GOLDEN_WINDOW_END}s"),
            ("Velocity", f"{'ON' if cfg.VELOCITY_ENABLED else 'OFF'} (min ${cfg.VELOCITY_MIN_DELTA:.1f} / {cfg.VELOCITY_WINDOW_SECONDS}s)"),
        ],
        "── Risk ──": [
            ("Circuit Breaker", f"{cfg.CIRCUIT_BREAKER_MAX_LOSS} consecutive losses"),
            ("Wallet Type", cfg.POLY_WALLET_TYPE.upper()),
        ],
        "── Mode ──": [
            ("Trading Mode", "PAPER" if cfg.PAPER_TRADING_MODE else "LIVE"),
            ("Bot Version", cfg.BOT_VERSION),
        ],
    }

    for section_name, params in sections.items():
        table.add_row(f"[bold magenta]{section_name}", "")
        for pname, pval in params:
            table.add_row(f"  {pname}", pval)

    console.print(table)
    console.print()
