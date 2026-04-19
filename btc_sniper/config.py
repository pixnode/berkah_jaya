# ═══ FILE: btc_sniper/config.py ═══
"""
Polymarket BTC Sniper v2.3 — Configuration Loader & Validator.
Loads all parameters from .env, validates constraints, prints startup banner.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


class ConfigurationError(Exception):
    """Raised when .env configuration is invalid or incomplete."""


def _env_str(key: str, default: Optional[str] = None) -> str:
    """Read a string from environment, return default if not set."""
    val = os.getenv(key, default)
    if val is None:
        return ""
    return val.strip()


def _env_float(key: str, default: float) -> float:
    """Read a float from environment."""
    raw = os.getenv(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw.strip())
    except ValueError:
        raise ConfigurationError(f"{key}={raw!r} is not a valid float")


def _env_int(key: str, default: int) -> int:
    """Read an int from environment."""
    raw = os.getenv(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw.strip())
    except ValueError:
        raise ConfigurationError(f"{key}={raw!r} is not a valid integer")


def _env_bool(key: str, default: bool) -> bool:
    """Read a bool from environment (True/False/1/0/yes/no)."""
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
    POLYMARKET_PRIVATE_KEY: str
    POLYMARKET_PROXY_WALLET: str
    POLY_CHAIN_ID: int

    # ── POLYMARKET API CREDENTIALS ────────────────────
    POLY_API_KEY: str
    POLY_API_SECRET: str
    POLY_API_PASSPHRASE: str

    # ── POLYMARKET ENDPOINTS ──────────────────────────
    CLOB_HOST: str
    RELAYER_URL: str
    GAMMA_API_URL: str

    # ── POLYGON RPC ───────────────────────────────────
    POLYGON_RPC_URL: str

    # ── HYPERLIQUID WEBSOCKET ─────────────────────────
    HYPERLIQUID_WS_URL: str
    HYPERLIQUID_API_KEY: str

    # ── POLYMARKET CLOB WEBSOCKET ─────────────────────
    POLY_WS_URL: str

    # ── CHAINLINK ─────────────────────────────────────
    CHAINLINK_CONTRACT_ADDRESS: str
    CHAINLINK_POLL_INTERVAL_SEC: int

    # ── STRATEGY CORE ─────────────────────────────────
    BASE_SHARES: float
    MAX_POSITION_USD: float
    GAP_THRESHOLD_DEFAULT: float
    GAP_THRESHOLD_LOW_VOL: float
    GAP_THRESHOLD_HIGH_VOL: float
    ATR_LOW_THRESHOLD: float
    ATR_HIGH_THRESHOLD: float
    ATR_LOOKBACK_CANDLES: int

    # ── ODDS BOUNDARY (Gate 4) ────────────────────────
    ODDS_MIN: float
    ODDS_MAX: float
    ODDS_SWEET_SPOT_LOW: float
    ODDS_SWEET_SPOT_HIGH: float

    # ── CVD ────────────────────────────────────────────
    CVD_VOLUME_WINDOW_MINUTES: int
    CVD_THRESHOLD_PCT: float

    # ── VELOCITY FILTER ───────────────────────────────
    VELOCITY_ENABLED: bool
    VELOCITY_MIN_DELTA: float
    VELOCITY_WINDOW_SECONDS: float

    # ── TIMING ────────────────────────────────────────
    GOLDEN_WINDOW_START: int
    GOLDEN_WINDOW_END: int

    # ── SLIPPAGE ──────────────────────────────────────
    SLIPPAGE_THRESHOLD_NORMAL: float
    SLIPPAGE_THRESHOLD_ELEVATED: float
    SLIPPAGE_THRESHOLD_HIGH: float
    SPREAD_MAX_PCT: float
    MISPRICING_MULTIPLIER: float
    MISPRICING_MIN_EDGE: float

    # ── RISK & CIRCUIT BREAKER ────────────────────────
    CIRCUIT_BREAKER_MAX_LOSS: int
    COOLDOWN_CIRCUIT_BREAKER_SEC: int
    COOLDOWN_DATA_STALE_SEC: int
    MAX_DAILY_LOSS_USD: float
    MIN_TRADE_RESERVE: int

    # ── DATA FRESHNESS ────────────────────────────────
    CHAINLINK_MAX_AGE_SEC: int
    CHAINLINK_MAX_AGE_ENTRY_SEC: int
    CHAINLINK_VOLATILITY_SKIP_USD: float
    WS_HEARTBEAT_INTERVAL_SEC: int
    WS_STALE_THRESHOLD_SEC: int
    WS_RECONNECT_MAX_RETRY: int
    WS_RECONNECT_BASE_DELAY_SEC: int
    WS_RECONNECT_MAX_DELAY_SEC: int
    SYNC_LATENCY_MAX_SEC: int

    # ── BLOCKCHAIN ────────────────────────────────────
    POLYGON_GAS_TIP_MULTIPLIER: float
    CLAIM_RETRY_MAX: int
    CLAIM_RETRY_TIMEOUT_SEC: int
    CLAIM_RETRY_INTERVAL_SEC: int

    # ── LOGGING & AUDIT ───────────────────────────────
    OUTPUT_DIR: str
    TRADE_LOG_FILE: str
    SKIP_LOG_FILE: str
    MARKET_SNAPSHOT_FILE: str
    SESSION_SUMMARY_FILE: str
    EVENT_LOG_FILE: str
    STATE_FILE: str
    LOG_FLUSH_INTERVAL_SEC: int
    LOG_ROTATION_DAYS: int
    SNAPSHOT_INTERVAL_SEC: int

    # ── OPERATIONAL ───────────────────────────────────
    PAPER_TRADING_MODE: bool
    BOT_VERSION: str
    CLI_REFRESH_RATE: int
    CLI_ORDERBOOK_UPDATE_SEC: int
    CLI_TRADE_LOG_ROWS: int


def load_config(env_path: Optional[str] = None) -> BotConfig:
    """Load BotConfig from .env file. Raises ConfigurationError on failure."""
    if env_path:
        load_dotenv(env_path)
    else:
        load_dotenv()

    cfg = BotConfig(
        # WALLET & AUTH
        POLYMARKET_PRIVATE_KEY=_env_str("POLYMARKET_PRIVATE_KEY", ""),
        POLYMARKET_PROXY_WALLET=_env_str("POLYMARKET_PROXY_WALLET", ""),
        POLY_CHAIN_ID=_env_int("POLY_CHAIN_ID", 137),
        # POLYMARKET API CREDENTIALS
        POLY_API_KEY=_env_str("POLY_API_KEY", ""),
        POLY_API_SECRET=_env_str("POLY_API_SECRET", ""),
        POLY_API_PASSPHRASE=_env_str("POLY_API_PASSPHRASE", ""),
        # POLYMARKET ENDPOINTS
        CLOB_HOST=_env_str("CLOB_HOST", "https://clob.polymarket.com"),
        RELAYER_URL=_env_str("RELAYER_URL", "https://relayer.polymarket.com"),
        GAMMA_API_URL=_env_str("GAMMA_API_URL", "https://gamma-api.polymarket.com"),
        # POLYGON RPC
        POLYGON_RPC_URL=_env_str("POLYGON_RPC_URL", ""),
        # HYPERLIQUID WEBSOCKET
        HYPERLIQUID_WS_URL=_env_str("HYPERLIQUID_WS_URL", "wss://api.hyperliquid.xyz/ws"),
        HYPERLIQUID_API_KEY=_env_str("HYPERLIQUID_API_KEY", ""),
        # POLYMARKET CLOB WEBSOCKET
        POLY_WS_URL=_env_str("POLY_WS_URL", "wss://ws-subscriptions-clob.polymarket.com/ws/market"),
        # CHAINLINK
        CHAINLINK_CONTRACT_ADDRESS=_env_str("CHAINLINK_CONTRACT_ADDRESS", "0xc907E116054Ad103354f2D350FD2514433D57F6F"),
        CHAINLINK_POLL_INTERVAL_SEC=_env_int("CHAINLINK_POLL_INTERVAL_SEC", 3),
        # STRATEGY CORE
        BASE_SHARES=_env_float("BASE_SHARES", 1.0),
        MAX_POSITION_USD=_env_float("MAX_POSITION_USD", 10.0),
        GAP_THRESHOLD_DEFAULT=_env_float("GAP_THRESHOLD_DEFAULT", 45.0),
        GAP_THRESHOLD_LOW_VOL=_env_float("GAP_THRESHOLD_LOW_VOL", 60.0),
        GAP_THRESHOLD_HIGH_VOL=_env_float("GAP_THRESHOLD_HIGH_VOL", 35.0),
        ATR_LOW_THRESHOLD=_env_float("ATR_LOW_THRESHOLD", 50.0),
        ATR_HIGH_THRESHOLD=_env_float("ATR_HIGH_THRESHOLD", 150.0),
        ATR_LOOKBACK_CANDLES=_env_int("ATR_LOOKBACK_CANDLES", 12),
        # ODDS BOUNDARY
        ODDS_MIN=_env_float("ODDS_MIN", 0.58),
        ODDS_MAX=_env_float("ODDS_MAX", 0.82),
        ODDS_SWEET_SPOT_LOW=_env_float("ODDS_SWEET_SPOT_LOW", 0.62),
        ODDS_SWEET_SPOT_HIGH=_env_float("ODDS_SWEET_SPOT_HIGH", 0.76),
        # CVD
        CVD_VOLUME_WINDOW_MINUTES=_env_int("CVD_VOLUME_WINDOW_MINUTES", 30),
        CVD_THRESHOLD_PCT=_env_float("CVD_THRESHOLD_PCT", 25.0),
        # VELOCITY
        VELOCITY_ENABLED=_env_bool("VELOCITY_ENABLED", True),
        VELOCITY_MIN_DELTA=_env_float("VELOCITY_MIN_DELTA", 15.0),
        VELOCITY_WINDOW_SECONDS=_env_float("VELOCITY_WINDOW_SECONDS", 1.5),
        # TIMING
        GOLDEN_WINDOW_START=_env_int("GOLDEN_WINDOW_START", 60),
        GOLDEN_WINDOW_END=_env_int("GOLDEN_WINDOW_END", 42),
        # SLIPPAGE
        SLIPPAGE_THRESHOLD_NORMAL=_env_float("SLIPPAGE_THRESHOLD_NORMAL", 1.0),
        SLIPPAGE_THRESHOLD_ELEVATED=_env_float("SLIPPAGE_THRESHOLD_ELEVATED", 1.5),
        SLIPPAGE_THRESHOLD_HIGH=_env_float("SLIPPAGE_THRESHOLD_HIGH", 2.0),
        SPREAD_MAX_PCT=_env_float("SPREAD_MAX_PCT", 3.0),
        MISPRICING_MULTIPLIER=_env_float("MISPRICING_MULTIPLIER", 0.15),
        MISPRICING_MIN_EDGE=_env_float("MISPRICING_MIN_EDGE", 0.02),
        # RISK
        CIRCUIT_BREAKER_MAX_LOSS=_env_int("CIRCUIT_BREAKER_MAX_LOSS", 3),
        COOLDOWN_CIRCUIT_BREAKER_SEC=_env_int("COOLDOWN_CIRCUIT_BREAKER_SEC", 900),
        COOLDOWN_DATA_STALE_SEC=_env_int("COOLDOWN_DATA_STALE_SEC", 300),
        MAX_DAILY_LOSS_USD=_env_float("MAX_DAILY_LOSS_USD", 0.0),
        MIN_TRADE_RESERVE=_env_int("MIN_TRADE_RESERVE", 5),
        # DATA FRESHNESS
        CHAINLINK_MAX_AGE_SEC=_env_int("CHAINLINK_MAX_AGE_SEC", 10),
        CHAINLINK_MAX_AGE_ENTRY_SEC=_env_int("CHAINLINK_MAX_AGE_ENTRY_SEC", 25),
        CHAINLINK_VOLATILITY_SKIP_USD=_env_float("CHAINLINK_VOLATILITY_SKIP_USD", 35.0),
        WS_HEARTBEAT_INTERVAL_SEC=_env_int("WS_HEARTBEAT_INTERVAL_SEC", 3),
        WS_STALE_THRESHOLD_SEC=_env_int("WS_STALE_THRESHOLD_SEC", 5),
        WS_RECONNECT_MAX_RETRY=_env_int("WS_RECONNECT_MAX_RETRY", 5),
        WS_RECONNECT_BASE_DELAY_SEC=_env_int("WS_RECONNECT_BASE_DELAY_SEC", 1),
        WS_RECONNECT_MAX_DELAY_SEC=_env_int("WS_RECONNECT_MAX_DELAY_SEC", 30),
        SYNC_LATENCY_MAX_SEC=_env_int("SYNC_LATENCY_MAX_SEC", 10),
        # BLOCKCHAIN
        POLYGON_GAS_TIP_MULTIPLIER=_env_float("POLYGON_GAS_TIP_MULTIPLIER", 1.0),
        CLAIM_RETRY_MAX=_env_int("CLAIM_RETRY_MAX", 3),
        CLAIM_RETRY_TIMEOUT_SEC=_env_int("CLAIM_RETRY_TIMEOUT_SEC", 30),
        CLAIM_RETRY_INTERVAL_SEC=_env_int("CLAIM_RETRY_INTERVAL_SEC", 60),
        # LOGGING
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
        # OPERATIONAL
        PAPER_TRADING_MODE=_env_bool("PAPER_TRADING_MODE", True),
        BOT_VERSION=_env_str("BOT_VERSION", "2.3"),
        CLI_REFRESH_RATE=_env_int("CLI_REFRESH_RATE", 4),
        CLI_ORDERBOOK_UPDATE_SEC=_env_int("CLI_ORDERBOOK_UPDATE_SEC", 2),
        CLI_TRADE_LOG_ROWS=_env_int("CLI_TRADE_LOG_ROWS", 10),
    )

    validate_config(cfg)
    return cfg


def validate_config(cfg: BotConfig) -> None:
    """Validate all config constraints. Raises ConfigurationError on failure."""

    # ── Required fields (crash if empty) ──────────────
    if not cfg.POLYMARKET_PRIVATE_KEY:
        raise ConfigurationError("POLYMARKET_PRIVATE_KEY is required — cannot be empty")
    if not cfg.POLYMARKET_PROXY_WALLET:
        raise ConfigurationError("POLYMARKET_PROXY_WALLET is required — cannot be empty")
    if not cfg.POLYGON_RPC_URL:
        raise ConfigurationError("POLYGON_RPC_URL is required — cannot be empty")
    if not cfg.HYPERLIQUID_WS_URL:
        raise ConfigurationError("HYPERLIQUID_WS_URL is required — cannot be empty")

    if not cfg.PAPER_TRADING_MODE:
        if not cfg.POLY_API_KEY:
            raise ConfigurationError("POLY_API_KEY wajib di live mode")
        if not cfg.POLY_API_SECRET:
            raise ConfigurationError("POLY_API_SECRET wajib di live mode")
        if not cfg.POLY_API_PASSPHRASE:
            raise ConfigurationError("POLY_API_PASSPHRASE wajib di live mode")

    # ── Numeric positivity checks ─────────────────────
    positive_floats = [
        ("BASE_SHARES", cfg.BASE_SHARES),
        ("MAX_POSITION_USD", cfg.MAX_POSITION_USD),
        ("GAP_THRESHOLD_DEFAULT", cfg.GAP_THRESHOLD_DEFAULT),
        ("GAP_THRESHOLD_LOW_VOL", cfg.GAP_THRESHOLD_LOW_VOL),
        ("GAP_THRESHOLD_HIGH_VOL", cfg.GAP_THRESHOLD_HIGH_VOL),
        ("ATR_LOW_THRESHOLD", cfg.ATR_LOW_THRESHOLD),
        ("ATR_HIGH_THRESHOLD", cfg.ATR_HIGH_THRESHOLD),
        ("ODDS_MIN", cfg.ODDS_MIN),
        ("ODDS_MAX", cfg.ODDS_MAX),
        ("ODDS_SWEET_SPOT_LOW", cfg.ODDS_SWEET_SPOT_LOW),
        ("ODDS_SWEET_SPOT_HIGH", cfg.ODDS_SWEET_SPOT_HIGH),
        ("CVD_THRESHOLD_PCT", cfg.CVD_THRESHOLD_PCT),
        ("VELOCITY_MIN_DELTA", cfg.VELOCITY_MIN_DELTA),
        ("VELOCITY_WINDOW_SECONDS", cfg.VELOCITY_WINDOW_SECONDS),
        ("SLIPPAGE_THRESHOLD_NORMAL", cfg.SLIPPAGE_THRESHOLD_NORMAL),
        ("SLIPPAGE_THRESHOLD_ELEVATED", cfg.SLIPPAGE_THRESHOLD_ELEVATED),
        ("SLIPPAGE_THRESHOLD_HIGH", cfg.SLIPPAGE_THRESHOLD_HIGH),
        ("SPREAD_MAX_PCT", cfg.SPREAD_MAX_PCT),
        ("MISPRICING_MULTIPLIER", cfg.MISPRICING_MULTIPLIER),
        ("MISPRICING_MIN_EDGE", cfg.MISPRICING_MIN_EDGE),
        ("CHAINLINK_VOLATILITY_SKIP_USD", cfg.CHAINLINK_VOLATILITY_SKIP_USD),
        ("POLYGON_GAS_TIP_MULTIPLIER", cfg.POLYGON_GAS_TIP_MULTIPLIER),
    ]
    for name, val in positive_floats:
        if val <= 0:
            raise ConfigurationError(f"{name}={val} must be > 0")

    positive_ints = [
        ("ATR_LOOKBACK_CANDLES", cfg.ATR_LOOKBACK_CANDLES),
        ("CVD_VOLUME_WINDOW_MINUTES", cfg.CVD_VOLUME_WINDOW_MINUTES),
        ("GOLDEN_WINDOW_START", cfg.GOLDEN_WINDOW_START),
        ("GOLDEN_WINDOW_END", cfg.GOLDEN_WINDOW_END),
        ("CIRCUIT_BREAKER_MAX_LOSS", cfg.CIRCUIT_BREAKER_MAX_LOSS),
        ("COOLDOWN_CIRCUIT_BREAKER_SEC", cfg.COOLDOWN_CIRCUIT_BREAKER_SEC),
        ("COOLDOWN_DATA_STALE_SEC", cfg.COOLDOWN_DATA_STALE_SEC),
        ("MIN_TRADE_RESERVE", cfg.MIN_TRADE_RESERVE),
        ("CHAINLINK_MAX_AGE_SEC", cfg.CHAINLINK_MAX_AGE_SEC),
        ("CHAINLINK_MAX_AGE_ENTRY_SEC", cfg.CHAINLINK_MAX_AGE_ENTRY_SEC),
        ("CHAINLINK_POLL_INTERVAL_SEC", cfg.CHAINLINK_POLL_INTERVAL_SEC),
        ("WS_HEARTBEAT_INTERVAL_SEC", cfg.WS_HEARTBEAT_INTERVAL_SEC),
        ("WS_STALE_THRESHOLD_SEC", cfg.WS_STALE_THRESHOLD_SEC),
        ("WS_RECONNECT_MAX_RETRY", cfg.WS_RECONNECT_MAX_RETRY),
        ("WS_RECONNECT_BASE_DELAY_SEC", cfg.WS_RECONNECT_BASE_DELAY_SEC),
        ("WS_RECONNECT_MAX_DELAY_SEC", cfg.WS_RECONNECT_MAX_DELAY_SEC),
        ("SYNC_LATENCY_MAX_SEC", cfg.SYNC_LATENCY_MAX_SEC),
        ("CLAIM_RETRY_MAX", cfg.CLAIM_RETRY_MAX),
        ("CLAIM_RETRY_TIMEOUT_SEC", cfg.CLAIM_RETRY_TIMEOUT_SEC),
        ("CLAIM_RETRY_INTERVAL_SEC", cfg.CLAIM_RETRY_INTERVAL_SEC),
        ("LOG_FLUSH_INTERVAL_SEC", cfg.LOG_FLUSH_INTERVAL_SEC),
        ("LOG_ROTATION_DAYS", cfg.LOG_ROTATION_DAYS),
        ("SNAPSHOT_INTERVAL_SEC", cfg.SNAPSHOT_INTERVAL_SEC),
        ("CLI_REFRESH_RATE", cfg.CLI_REFRESH_RATE),
        ("CLI_ORDERBOOK_UPDATE_SEC", cfg.CLI_ORDERBOOK_UPDATE_SEC),
        ("CLI_TRADE_LOG_ROWS", cfg.CLI_TRADE_LOG_ROWS),
    ]
    for name, val in positive_ints:
        if val <= 0:
            raise ConfigurationError(f"{name}={val} must be > 0")

    # MAX_DAILY_LOSS_USD is allowed to be 0 (disabled)
    if cfg.MAX_DAILY_LOSS_USD < 0:
        raise ConfigurationError(f"MAX_DAILY_LOSS_USD={cfg.MAX_DAILY_LOSS_USD} must be >= 0")

    # ── Relational constraints ────────────────────────
    if not (cfg.ODDS_MIN < cfg.ODDS_SWEET_SPOT_LOW < cfg.ODDS_SWEET_SPOT_HIGH < cfg.ODDS_MAX):
        raise ConfigurationError(
            f"Odds ordering violated: ODDS_MIN({cfg.ODDS_MIN}) < "
            f"SWEET_LOW({cfg.ODDS_SWEET_SPOT_LOW}) < "
            f"SWEET_HIGH({cfg.ODDS_SWEET_SPOT_HIGH}) < "
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
        "║                                                  ║",
        "║  Semua order adalah SIMULASI.                    ║",
        "║  Tidak ada USDC yang keluar dari wallet.         ║",
        "║  Tidak ada transaksi ke Polygon blockchain.      ║",
        "║                                                  ║",
        "║  Yang tetap terhubung (read-only):               ║",
        "║  v Chainlink RPC (baca harga resolusi)           ║",
        "║  v Hyperliquid WebSocket (live price + CVD)      ║",
        "║  v Polymarket CLOB WebSocket (live odds)         ║",
        "║                                                  ║",
        "║  Untuk live trading: set PAPER_TRADING_MODE=false║",
        "║  dan pastikan wallet funded dengan USDC.         ║",
        "╚══════════════════════════════════════════════════╝",
    ]
    for line in lines:
        try:
            print(line)
        except UnicodeEncodeError:
            # Fallback for Windows consoles that don't support UTF-8 box drawing characters
            print(line.replace("╔", "+").replace("═", "-").replace("╗", "+").replace("║", "|").replace("╚", "+").replace("╝", "+"))


def _print_startup_banner(cfg: BotConfig) -> None:
    """Print a rich startup banner with all active config values."""
    try:
        from rich.console import Console
        from rich.table import Table
    except ImportError:
        # Fallback if rich not installed yet
        print(f"=== BTC SNIPER v{cfg.BOT_VERSION} ===")
        print_paper_mode_warning(cfg)
        return

    console = Console()

    # Paper mode warning box
    print_paper_mode_warning(cfg)

    # Config table
    table = Table(title=f"BTC SNIPER v{cfg.BOT_VERSION} — Active Configuration", show_lines=False)
    table.add_column("Parameter", style="cyan", min_width=30)
    table.add_column("Value", style="white", min_width=20)

    sections = {
        "── Strategy ──": [
            ("Base Shares", f"{cfg.BASE_SHARES}"),
            ("Max Position USD", f"${cfg.MAX_POSITION_USD:.2f}"),
            ("Gap Threshold (Normal)", f"${cfg.GAP_THRESHOLD_DEFAULT:.1f}"),
            ("Gap Threshold (Low Vol)", f"${cfg.GAP_THRESHOLD_LOW_VOL:.1f}"),
            ("Gap Threshold (High Vol)", f"${cfg.GAP_THRESHOLD_HIGH_VOL:.1f}"),
        ],
        "── Odds ──": [
            ("Odds Min", f"{cfg.ODDS_MIN}"),
            ("Odds Max", f"{cfg.ODDS_MAX}"),
            ("Sweet Spot", f"{cfg.ODDS_SWEET_SPOT_LOW} – {cfg.ODDS_SWEET_SPOT_HIGH}"),
        ],
        "── CVD ──": [
            ("CVD Threshold %", f"{cfg.CVD_THRESHOLD_PCT}%"),
            ("CVD Volume Window", f"{cfg.CVD_VOLUME_WINDOW_MINUTES} min"),
        ],
        "── Timing ──": [
            ("Golden Window", f"T-{cfg.GOLDEN_WINDOW_START}s → T-{cfg.GOLDEN_WINDOW_END}s"),
            ("Velocity", f"{'ON' if cfg.VELOCITY_ENABLED else 'OFF'} (min ${cfg.VELOCITY_MIN_DELTA:.1f} / {cfg.VELOCITY_WINDOW_SECONDS}s)"),
        ],
        "── Risk ──": [
            ("Circuit Breaker", f"{cfg.CIRCUIT_BREAKER_MAX_LOSS} consecutive losses"),
            ("CB Cooldown", f"{cfg.COOLDOWN_CIRCUIT_BREAKER_SEC}s"),
            ("Daily Loss Limit", f"{'$' + str(cfg.MAX_DAILY_LOSS_USD) if cfg.MAX_DAILY_LOSS_USD > 0 else 'DISABLED'}"),
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
