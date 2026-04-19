# MASTER PROMPT — Polymarket BTC Sniper v2.3
### Optimized for Claude Opus 4.6 | Build Prompt Engineering
`Revised after audit: April 2026 | PRD Reference: v2.3`

---

## ITERASI 0 — PROJECT BOOTSTRAP
> Jalankan prompt ini PERTAMA KALI sebelum iterasi lainnya.

```
PERAN:
Kamu adalah Senior Python Engineer dengan spesialisasi di:
- Asyncio & high-performance WebSocket systems
- Quantitative trading bot architecture
- Blockchain transaction handling (Polygon/EVM)
- CLI terminal dashboard (Python rich library)

Kamu menulis kode production-grade: clean, modular, fully typed (mypy-compatible),
dengan error handling eksplisit di setiap layer. Kamu tidak pernah menulis placeholder
seperti "# TODO" atau "pass" tanpa implementasi nyata.

TUGAS:
Buat struktur direktori lengkap dan file bootstrap untuk Polymarket BTC Sniper v2.3.
Jangan tulis logic trading dulu — hanya scaffold, config loader, dan ENV validator.

KONTEKS:
Bot ini adalah latency arbitrage system:
- Signal source   : Hyperliquid WebSocket (harga BTC + trade feed untuk CVD)
- Execution venue : Polymarket CLOB API (beli UP/DOWN shares)
- Resolution      : Chainlink BTC/USD on-chain (otomatis via smart contract)
- Runtime         : Python 3.11+, asyncio, berjalan di VPS via tmux
- Config          : Semua parameter dikontrol via .env (python-dotenv)
- Version         : 2.3 (gunakan string ini di banner, log, dan engine_state)

TUGAS DETAIL:

1. Buat struktur direktori ini PERSIS:
   btc_sniper/
   ├── main.py
   ├── config.py
   ├── .env.example
   ├── requirements.txt
   ├── core/
   │   ├── __init__.py          # export: BotEngine, SignalProcessor, OrderExecutor, ClaimManager, CircuitBreaker
   │   ├── engine.py
   │   ├── signal_processor.py
   │   ├── order_executor.py
   │   ├── claim_manager.py
   │   └── circuit_breaker.py
   ├── feeds/
   │   ├── __init__.py          # export: HyperliquidFeed, PolymarketFeed, ChainlinkFeed, semua event dataclasses
   │   ├── hyperliquid_ws.py
   │   ├── polymarket_ws.py
   │   └── chainlink_feed.py
   ├── risk/
   │   ├── __init__.py          # export: GateEvaluator, GateResult, SafetyMonitor, SafetyEvent
   │   ├── gates.py
   │   └── safety_monitor.py
   ├── logs/
   │   ├── __init__.py          # export: AuditLogger, TradeRecord, SkipRecord, SnapshotRecord, EventRecord
   │   └── audit_logger.py
   ├── cli/
   │   ├── __init__.py          # export: Dashboard
   │   └── dashboard.py
   └── output/
       └── .gitkeep             # semua CSV dan JSON disimpan di sini saat runtime

2. Tulis dua utility functions di core/engine.py:

   def get_current_window_slug() -> str:
       """Hitung slug Polymarket untuk window 5-menit yang sedang aktif.
       Format: btc-updown-5m-{unix_timestamp_detik_awal_window}
       Contoh: window 14:35:00–14:40:00 → 'btc-updown-5m-1776444900'
       """
       now = int(time.time())
       window_start = now - (now % 300)
       return f"btc-updown-5m-{window_start}"

   def get_time_remaining() -> int:
       """Hitung detik tersisa hingga window tutup (0–300)."""
       now = int(time.time())
       window_start = now - (now % 300)
       return (window_start + 300) - now

3. Tulis config.py dengan:
   - Dataclass BotConfig yang memuat SEMUA env vars berikut (lengkap):

   # WALLET & AUTH
   POLYMARKET_PRIVATE_KEY: str          # wajib — crash jika kosong
   POLYMARKET_PROXY_WALLET: str         # wajib
   POLYMARKET_API_KEY: str              # wajib
   HYPERLIQUID_WS_URL: str              # default: wss://api.hyperliquid.xyz/ws
   POLYGON_RPC_URL: str                 # wajib

   # STRATEGY CORE
   BASE_SHARES: float                   # default: 1.0  ← BUKAN 100
   MAX_POSITION_USD: float              # default: 10.0 — hard cap cost per trade
   GAP_THRESHOLD_DEFAULT: float         # default: 45.0
   GAP_THRESHOLD_LOW_VOL: float         # default: 60.0
   GAP_THRESHOLD_HIGH_VOL: float        # default: 35.0
   ATR_LOW_THRESHOLD: float             # default: 50.0
   ATR_HIGH_THRESHOLD: float            # default: 150.0
   ATR_LOOKBACK_CANDLES: int            # default: 12

   # ODDS BOUNDARY (Gate 4)
   ODDS_MIN: float                      # default: 0.58
   ODDS_MAX: float                      # default: 0.82
   ODDS_SWEET_SPOT_LOW: float           # default: 0.62
   ODDS_SWEET_SPOT_HIGH: float          # default: 0.76

   # CVD
   CVD_VOLUME_WINDOW_MINUTES: int       # default: 30
   CVD_THRESHOLD_PCT: float             # default: 25.0

   # VELOCITY FILTER
   VELOCITY_ENABLED: bool               # default: True
   VELOCITY_MIN_DELTA: float            # default: 15.0
   VELOCITY_WINDOW_SECONDS: float       # default: 1.5

   # TIMING
   GOLDEN_WINDOW_START: int             # default: 60
   GOLDEN_WINDOW_END: int               # default: 42

   # SLIPPAGE
   SLIPPAGE_THRESHOLD_NORMAL: float     # default: 1.0
   SLIPPAGE_THRESHOLD_ELEVATED: float   # default: 1.5
   SLIPPAGE_THRESHOLD_HIGH: float       # default: 2.0
   SPREAD_MAX_PCT: float                # default: 3.0
   MISPRICING_MULTIPLIER: float         # default: 0.15
   MISPRICING_MIN_EDGE: float           # default: 0.02

   # RISK & CIRCUIT BREAKER
   CIRCUIT_BREAKER_MAX_LOSS: int        # default: 3
   COOLDOWN_CIRCUIT_BREAKER_SEC: int    # default: 900
   COOLDOWN_DATA_STALE_SEC: int         # default: 300
   MAX_DAILY_LOSS_USD: float            # default: 0.0 (0 = disabled)
   MIN_TRADE_RESERVE: int               # default: 5

   # DATA FRESHNESS
   CHAINLINK_MAX_AGE_SEC: int           # default: 10
   CHAINLINK_MAX_AGE_ENTRY_SEC: int     # default: 25
   CHAINLINK_VOLATILITY_SKIP_USD: float # default: 35.0
   WS_HEARTBEAT_INTERVAL_SEC: int       # default: 3
   WS_STALE_THRESHOLD_SEC: int          # default: 5
   WS_RECONNECT_MAX_RETRY: int          # default: 5
   SYNC_LATENCY_MAX_SEC: int            # default: 10

   # BLOCKCHAIN
   POLYGON_GAS_TIP_MULTIPLIER: float    # default: 1.0
   CLAIM_RETRY_MAX: int                 # default: 3
   CLAIM_RETRY_TIMEOUT_SEC: int         # default: 30
   CLAIM_RETRY_INTERVAL_SEC: int        # default: 60

   # LOGGING & AUDIT
   OUTPUT_DIR: str                      # default: ./output
   TRADE_LOG_FILE: str                  # default: trade_log.csv
   SKIP_LOG_FILE: str                   # default: skip_log.csv
   MARKET_SNAPSHOT_FILE: str            # default: market_snapshot.csv
   SESSION_SUMMARY_FILE: str            # default: session_summary.csv
   EVENT_LOG_FILE: str                  # default: event_log.csv
   STATE_FILE: str                      # default: engine_state.json
   LOG_FLUSH_INTERVAL_SEC: int          # default: 5
   LOG_ROTATION_DAYS: int               # default: 30
   SNAPSHOT_INTERVAL_SEC: int           # default: 5

   # OPERATIONAL
   PAPER_TRADING_MODE: bool             # default: True (WAJIB True saat pertama deploy)
   BOT_VERSION: str                     # default: "2.3"
   CLI_REFRESH_RATE: int                # default: 4
   CLI_ORDERBOOK_UPDATE_SEC: int        # default: 2
   CLI_TRADE_LOG_ROWS: int              # default: 10

4. Tulis validator di config.py:
   - Fungsi validate_config(cfg: BotConfig) -> None
   - Raise ConfigurationError dengan pesan spesifik jika field wajib kosong
   - Validasi tipe data numerik (semua float/int harus > 0 kecuali yang boleh 0)
   - Validasi ODDS_MIN < ODDS_SWEET_SPOT_LOW < ODDS_SWEET_SPOT_HIGH < ODDS_MAX
   - Validasi GOLDEN_WINDOW_END < GOLDEN_WINDOW_START
   - Validasi BASE_SHARES * ODDS_MAX <= MAX_POSITION_USD (position size check)
   - Print startup banner saat config valid: tampilkan semua nilai aktif
   - Jika PAPER_TRADING_MODE=True: cetak prominent WARNING BOX di banner

5. Tulis .env.example dengan semua vars dan komentar penjelasan singkat.

6. Tulis requirements.txt dengan versi yang di-pin:
   websockets>=12.0
   aiohttp>=3.9.0
   python-dotenv>=1.0.0
   rich>=13.7.0
   web3>=6.15.0
   py-clob-client==0.34.5
   aioconsole>=0.6.0
   pydantic>=2.0.0
   pytest>=8.0.0
   pytest-asyncio>=0.23.0

FORMAT OUTPUT:
- Tulis setiap file secara lengkap, tidak ada yang disingkat
- Gunakan Python type hints di semua fungsi
- Tambahkan docstring singkat di setiap class dan fungsi publik
- Pisahkan setiap file dengan header komentar: # ═══ FILE: path/to/file.py ═══
```

---

## ITERASI 1 — FEED LAYER (WebSocket + Chainlink)

```
PERAN:
Kamu adalah Senior Python Engineer spesialis asyncio dan WebSocket systems.
Lanjutkan dari scaffold yang sudah dibuat di Iterasi 0.
Kamu memiliki akses ke BotConfig yang sudah divalidasi.

TUGAS:
Implementasikan tiga feed modules secara lengkap dan production-ready.

KONTEKS TEKNIS:
- Semua feed berjalan sebagai asyncio Task terpisah
- Data dikirim via asyncio.Queue ke signal processor (maxsize=100)
- Jika queue penuh → log WARNING "QUEUE_FULL" ke event_log, jangan block
- Heartbeat check setiap cfg.WS_HEARTBEAT_INTERVAL_SEC detik
- Jika tidak ada message dalam cfg.WS_STALE_THRESHOLD_SEC → emit DataStaleEvent
- Reconnect otomatis dengan exponential backoff: 1s, 2s, 4s, 8s, max 30s
- Max reconnect attempts: cfg.WS_RECONNECT_MAX_RETRY — jika habis → LOCKDOWN
- Setiap reconnect attempt → log ke event_log.csv

TUGAS DETAIL — Tulis tiga file ini secara lengkap:

━━━ FILE 1: feeds/hyperliquid_ws.py ━━━
Class: HyperliquidFeed
- Connect ke cfg.HYPERLIQUID_WS_URL
- Subscribe dua channel: "trades" dan "l2Book" untuk symbol "BTC"
- Parse trade message → emit TradeEvent(timestamp, price, size, side: "buy"|"sell")
- Hitung harga BTC terbaru → emit PriceEvent(timestamp, price)
- Heartbeat: kirim ping setiap cfg.WS_HEARTBEAT_INTERVAL_SEC, expect pong dalam 3 detik
- Jika pong tidak datang → log WS_HEARTBEAT_TIMEOUT, reconnect
- Method: async def start(self, queue: asyncio.Queue) -> None
- Method: async def stop(self) -> None
- Property: is_connected: bool
- Property: last_message_at: float (unix timestamp)

ERROR HANDLING WAJIB:
- websockets.ConnectionClosed → log, reconnect dengan backoff
- asyncio.TimeoutError (heartbeat) → log WS_HEARTBEAT_TIMEOUT, reconnect
- Setiap reconnect attempt → log EVENT ke event_log: {type: WS_RECONNECT, source: hyperliquid, attempt: n}

━━━ FILE 2: feeds/polymarket_ws.py ━━━
Class: PolymarketFeed
- Connect ke Polymarket CLOB WebSocket
- Subscribe ke market slug yang diberikan (dinamis per window)
- Parse order book update → emit OrderBookEvent(timestamp, up_ask, up_bid, down_ask, down_bid, spread_pct)
- Parse odds update → emit OddsEvent(timestamp, up_odds, down_odds)
- Method: async def subscribe(self, market_slug: str) -> None
- Method: async def unsubscribe(self) -> None
- Method: async def start(self, queue: asyncio.Queue) -> None
- Method: async def stop(self) -> None
- Hitung spread_pct = (ask - bid) / mid * 100 dan masukkan ke OrderBookEvent

ERROR HANDLING WAJIB:
- Sama dengan HyperliquidFeed — backoff, max retry, LOCKDOWN jika habis

━━━ FILE 3: feeds/chainlink_feed.py ━━━
Class: ChainlinkFeed
- Connect ke cfg.POLYGON_RPC_URL via web3.py (AsyncWeb3)
- Poll Chainlink BTC/USD feed setiap 3 detik
- Contract address: CHAINLINK_BTC_USD_POLYGON = "0xc907E116054Ad103354f2D350FD2514433D57F6F"
- ABI: hanya fungsi latestRoundData() → (roundId, answer, startedAt, updatedAt, answeredInRound)
- Parse response: price = answer / 1e8 (Chainlink BTC 8 desimal)
- Emit ChainlinkEvent(timestamp, price, updated_at, age_seconds, is_stale)
- age_seconds = current_unix_time - updated_at
- Jika age_seconds > cfg.CHAINLINK_MAX_AGE_SEC → set is_stale = True di event
- Method: async def get_strike_price(self) -> ChainlinkEvent
- Method: async def start_polling(self, queue: asyncio.Queue) -> None

ERROR HANDLING WAJIB — RPC Failures:
- asyncio.TimeoutError → log CHAINLINK_RPC_TIMEOUT, emit DataStaleEvent(source="chainlink")
- web3.exceptions.ContractLogicError → log CHAINLINK_CONTRACT_ERROR, emit DataStaleEvent
- aiohttp.ClientError (network) → log CHAINLINK_RPC_DOWN
- Setelah 3 consecutive RPC failures → trigger LOCKDOWN via circuit_breaker
- Retry dengan backoff: 1s, 2s, 4s sebelum emit DataStaleEvent

━━━ DATACLASSES (feeds/__init__.py) ━━━
Definisikan semua event dataclasses:
@dataclass
class TradeEvent: timestamp: float, price: float, size: float, side: Literal["buy","sell"]
class PriceEvent: timestamp: float, price: float
class OrderBookEvent: timestamp: float, up_ask: float, up_bid: float, down_ask: float, down_bid: float, spread_pct: float
class OddsEvent: timestamp: float, up_odds: float, down_odds: float
class ChainlinkEvent: timestamp: float, price: float, updated_at: float, age_seconds: int, is_stale: bool
class DataStaleEvent: timestamp: float, source: Literal["hyperliquid","polymarket","chainlink"]

FORMAT OUTPUT:
- Tulis semua file secara lengkap, tidak ada bagian yang disingkat
- Semua exception harus ditangkap secara spesifik, bukan bare except
- Setiap reconnect dan error → tulis ke event_log via logger yang di-inject ke constructor
- Gunakan logging standard Python, bukan print
```

---

## ITERASI 2 — SIGNAL PROCESSOR (CVD + ATR + GAP)

```
PERAN:
Kamu adalah Senior Quant Developer spesialis signal processing untuk HFT systems.
Kamu memahami CVD (Cumulative Volume Delta), ATR, dan rolling window calculations
dengan kompleksitas O(1) menggunakan deque — bukan recalculate dari scratch tiap tick.

TUGAS:
Implementasikan core/signal_processor.py secara lengkap.

KONTEKS:
- Signal processor membaca dari asyncio.Queue (output dari feed layer)
- Semua kalkulasi harus O(1) atau O(window) — tidak boleh O(n²)
- ATR dihitung dari candle 5-menit Hyperliquid (bukan tick-by-tick)
- CVD adalah rolling 60 detik net delta: Σ(buy_volume) - Σ(sell_volume)
- Setiap update state → simpan ke EngineState in-memory (flush ke JSON setiap cfg.LOG_FLUSH_INTERVAL_SEC)

TUGAS DETAIL:

━━━ CLASS: SignalProcessor ━━━

Method: async def run(self, queue: asyncio.Queue) -> None
- Loop utama yang consume events dari queue
- Dispatch berdasarkan event type ke handler masing-masing

Method: _handle_trade_event(event: TradeEvent) -> None
- Update CVD rolling window menggunakan collections.deque
- Setiap entry deque: tuple(timestamp_float, net_delta_float)
  net_delta = +size jika side=="buy", -size jika side=="sell"
- Hapus semua entry dengan timestamp < (time.time() - cfg.CVD_VOLUME_WINDOW_MINUTES*60)
  sebelum setiap kalkulasi
- Hitung cvd_current = sum(entry[1] for entry in cvd_deque)
- Hitung avg_volume_per_minute dari rolling cfg.CVD_VOLUME_WINDOW_MINUTES menit
- cvd_threshold = avg_volume_per_minute * (cfg.CVD_THRESHOLD_PCT / 100)
- Set cvd_aligned = True jika:
  Gap UP  dan cvd_current > +cvd_threshold
  Gap DOWN dan cvd_current < -cvd_threshold

Method: _handle_price_event(event: PriceEvent) -> None
- Update current_hl_price
- Hitung velocity menggunakan deque of (timestamp, price):
  Hapus entry > cfg.VELOCITY_WINDOW_SECONDS, ambil oldest entry yang tersisa
  velocity = current_price - oldest_price_in_window
- Hitung gap = current_hl_price - strike_price
- Determine vol_regime:
  LOW  jika ATR < cfg.ATR_LOW_THRESHOLD
  HIGH jika ATR > cfg.ATR_HIGH_THRESHOLD
  NORM sebaliknya
- Set gap_threshold berdasarkan regime:
  LOW  → cfg.GAP_THRESHOLD_LOW_VOL
  NORM → cfg.GAP_THRESHOLD_DEFAULT
  HIGH → cfg.GAP_THRESHOLD_HIGH_VOL

Method: _update_atr(candle: Candle) -> None
- Simpan collections.deque of Candle dengan maxlen = cfg.ATR_LOOKBACK_CANDLES
- True Range = max(high-low, abs(high-prev_close), abs(low-prev_close))
- ATR = mean(True Range) dari semua candle dalam deque
- Aggregate tick data → candle baru setiap 5 menit (deteksi berdasarkan timestamp)

Method: def reset_cvd(self) -> None
- Kosongkan cvd_deque
- Reset cvd_current = 0.0
- Dipanggil saat LOCKDOWN Resume (Step 3 Resume Protocol)

━━━ DATACLASS: SignalState ━━━
@dataclass
class SignalState:
    timestamp: float
    current_hl_price: float
    strike_price: float
    gap: float
    gap_direction: Literal["UP", "DOWN", "NEUTRAL"]
    gap_threshold: float
    vol_regime: Literal["LOW", "NORM", "HIGH"]
    atr: float
    cvd_60s: float
    cvd_threshold: float
    cvd_threshold_pct: float
    avg_volume_per_min: float
    cvd_aligned: bool
    velocity_1_5s: float
    velocity_pass: bool

FORMAT OUTPUT:
- Gunakan collections.deque untuk semua rolling windows — bukan list dengan slicing
- Tidak ada numpy atau pandas — pure Python untuk minimisasi dependency dan latency
- Setiap kalkulasi harus ada doctest minimal sebagai dokumentasi
- Tulis file secara lengkap tanpa disingkat
```

---

## ITERASI 3 — ENTRY GATES (7 Gate AND Logic)

```
PERAN:
Kamu adalah Senior Quant Trader yang memahami bahwa false positive jauh lebih
berbahaya dari false negative. Kamu menulis gate logic yang defensif, eksplisit,
dan menghasilkan audit trail lengkap untuk setiap evaluasi.

TUGAS:
Implementasikan risk/gates.py — 7-gate AND logic entry evaluation secara lengkap.

KONTEKS:
Semua 7 gate harus PASS. Jika satu FAIL → catat gate yang gagal → kembali ke ARMED.
Gate evaluation terjadi setiap detik selama golden window aktif.

URUTAN GATE (sesuai PRD v2.3 Section 04 — jangan ubah urutan ini):
Gate 1: Gap Threshold
Gate 2: CVD Alignment
Gate 3: Dual Side Liquidity
Gate 4: Odds Boundary (MIN/MAX)  ← Gate 4, bukan Gate 5
Gate 5: Golden Window Timing
Gate 6: Velocity Filter
Gate 7: No Duplicate Order

TUGAS DETAIL — Tulis class GateEvaluator:

━━━ METHOD: evaluate(signal, book, odds, time_remaining, order_sent) -> GateResult ━━━

GATE 1 — Gap Threshold (Dynamic ATR-based)
  PASS jika: abs(signal.gap) > signal.gap_threshold
  FAIL reason: f"GAP_INSUFFICIENT: {signal.gap:.1f} < threshold {signal.gap_threshold:.1f}"

GATE 2 — CVD Alignment
  PASS jika: signal.cvd_aligned == True
  FAIL reason: f"CVD_MISALIGNED: cvd={signal.cvd_60s:.0f}, threshold={signal.cvd_threshold:.0f}"

GATE 3 — Dual Side Liquidity + Mispricing
  Cek: up_ask tersedia (not None), down_bid tersedia, spread_pct <= cfg.SPREAD_MAX_PCT
  Hitung Expected_odds = 0.50 + (abs(signal.gap) / max(signal.atr, 1) * cfg.MISPRICING_MULTIPLIER)
  Clamp Expected_odds ke range [0.50, 0.95]
  PASS jika: current_ask < Expected_odds - cfg.MISPRICING_MIN_EDGE
  FAIL reason: "NO_LIQUIDITY" | f"SPREAD_TOO_WIDE: {book.spread_pct:.1f}%" | 
               f"NO_MISPRICING: ask={current_ask:.3f} >= expected={Expected_odds:.3f}-{cfg.MISPRICING_MIN_EDGE}"

GATE 4 — Odds Boundary (MIN/MAX)  ← POSISI BARU di v2.3
  target_ask = odds.up_odds jika gap direction UP, else odds.down_odds
  PASS jika: cfg.ODDS_MIN <= target_ask <= cfg.ODDS_MAX
  FAIL reason: f"ODDS_OUT_OF_RANGE: {target_ask:.3f} not in [{cfg.ODDS_MIN},{cfg.ODDS_MAX}]"
  Tambahkan field: in_sweet_spot = cfg.ODDS_SWEET_SPOT_LOW <= target_ask <= cfg.ODDS_SWEET_SPOT_HIGH

GATE 5 — Golden Window Timing
  PASS jika: cfg.GOLDEN_WINDOW_END <= time_remaining <= cfg.GOLDEN_WINDOW_START
  FAIL reason: f"OUTSIDE_GOLDEN_WINDOW: T-{time_remaining}s"

GATE 6 — Velocity Filter (jika cfg.VELOCITY_ENABLED)
  PASS jika: signal.velocity_pass == True ATAU cfg.VELOCITY_ENABLED == False
  FAIL reason: f"VELOCITY_LOW: {signal.velocity_1_5s:.1f} < {cfg.VELOCITY_MIN_DELTA}"

GATE 7 — No Duplicate Order
  PASS jika: order_sent == False
  FAIL reason: "ORDER_ALREADY_SENT_THIS_WINDOW"

━━━ DATACLASS: GateResult ━━━
@dataclass
class GateResult:
    all_pass: bool
    failed_gate: Optional[int]          # None jika semua pass
    fail_reason: Optional[str]
    gate_statuses: dict[int, bool]      # {1: True, 2: True, 3: False, ...} — selalu 7 keys
    evaluated_at: float                 # unix timestamp
    signal_snapshot: SignalState        # snapshot state saat evaluasi
    target_ask: float
    expected_odds: float
    in_sweet_spot: bool
    side: Optional[Literal["UP", "DOWN"]]  # None jika gagal

    def to_csv_row(self) -> dict:
        """Serialize ke dict untuk skip_log.csv dan event_log.csv."""
        ...  # implementasikan

FORMAT OUTPUT:
- Short-circuit: evaluasi berhenti di gate pertama yang FAIL
- Jika VELOCITY_ENABLED=False, Gate 6 selalu PASS (catat sebagai DISABLED bukan PASS)
- GateResult.gate_statuses selalu punya tepat 7 keys
- Tulis file secara lengkap
```

---

## ITERASI 4 — ORDER EXECUTOR + CLAIM MANAGER

```
PERAN:
Kamu adalah Senior Backend Engineer spesialis blockchain transaction handling
di Polygon/EVM. Kamu memahami bahwa setiap order adalah blockchain transaction
dengan latency 2-8 detik dan tidak ada "undo".

TUGAS:
Implementasikan core/order_executor.py dan core/claim_manager.py secara lengkap.

KONTEKS:
- Polymarket CLOB API menggunakan signed EIP-712 orders
- Setiap order harus di-sign dengan POLYMARKET_PRIVATE_KEY sebelum dikirim
- Gas tip dikontrol via cfg.POLYGON_GAS_TIP_MULTIPLIER
- Order timeout: jika tidak confirmed dalam (cfg.GOLDEN_WINDOW_END - 2) detik → cancel
- Auto claim via Polymarket Gasless Relayer dengan retry queue

PENTING — DUA SLIPPAGE CHECK YANG BERBEDA:
Check A (Gate 3, di Iterasi 3): Mispricing — apakah ask SEKARANG underpriced vs expected_odds?
Check B (OrderExecutor, di sini): Temporal slippage — apakah ask BERUBAH antara T_signal dan T_order?
Keduanya harus ada dan keduanya wajib PASS.

TUGAS DETAIL:

━━━ FILE 1: core/order_executor.py ━━━
Class: OrderExecutor

Method: async def execute(self, gate_result: GateResult, window_id: str) -> OrderResult

  LANGKAH 0 — Paper Trading Guard:
    Jika cfg.PAPER_TRADING_MODE == True:
      - Simulasikan order fill: entry_odds = gate_result.target_ask
      - cost_usd = cfg.BASE_SHARES * entry_odds
      - Tidak ada actual API call ke Polymarket CLOB
      - Return OrderResult(status="FILLED", ...semua field diisi dengan simulated values...)
      - Semua log entry harus punya prefix "[PAPER]" di field notes
      - CLI: badge [PAPER MODE] sudah ditampilkan di header (bukan tugas method ini)

  LANGKAH 1 — Snapshot T_signal odds (sudah ada di gate_result)

  LANGKAH 2 — Re-fetch live odds dari Polymarket (Check B — temporal slippage)
    live_odds = await self._fetch_live_odds(gate_result.side, window_id)
    slippage_delta = abs(live_odds - gate_result.target_ask) / gate_result.target_ask * 100

  LANGKAH 3 — Tentukan slippage threshold berdasarkan vol_regime:
    NORM/LOW → cfg.SLIPPAGE_THRESHOLD_NORMAL
    ELEVATED → cfg.SLIPPAGE_THRESHOLD_ELEVATED
    HIGH     → cfg.SLIPPAGE_THRESHOLD_HIGH
    Jika slippage_delta > threshold → return OrderResult(status="SLIPPAGE_EXCEEDED")

  LANGKAH 4 — Position size guard:
    cost_estimate = cfg.BASE_SHARES * live_odds
    Jika cost_estimate > cfg.MAX_POSITION_USD → return OrderResult(status="POSITION_TOO_LARGE")

  LANGKAH 5 — Build dan sign order (EIP-712)
  LANGKAH 6 — Submit ke Polymarket CLOB API
    Timeout eksplisit: 8 detik untuk submit, 15 detik untuk confirmation
  LANGKAH 7 — Monitor confirmation
    Jika timeout → return OrderResult(status="TIMEOUT")
    TIMEOUT bukan LOSS — TIDAK increment circuit_breaker
    Log ke event_log: {type: "ORDER_TIMEOUT", note: "TIMEOUT_NOT_LOSS"}
  LANGKAH 8 — Return OrderResult lengkap

ERROR HANDLING WAJIB:
- asyncio.TimeoutError saat submit → OrderResult(status="TIMEOUT")
- aiohttp.ClientError → OrderResult(status="ERROR", error_msg=str(e))
- Setiap error → log ke event_log dengan state_snapshot penuh

@dataclass
class OrderResult:
    status: Literal["FILLED","PARTIAL","REJECTED","SLIPPAGE_EXCEEDED","TIMEOUT","ERROR","POSITION_TOO_LARGE","PAPER_FILL"]
    window_id: str
    side: Optional[str]
    entry_odds: Optional[float]
    shares_bought: Optional[float]
    cost_usd: Optional[float]
    slippage_delta: float
    slippage_threshold_used: float
    tx_hash: Optional[str]
    confirmed_at: Optional[float]
    latency_ms: Optional[int]
    error_msg: Optional[str]
    is_paper: bool                      # True jika PAPER_TRADING_MODE

━━━ FILE 2: core/claim_manager.py ━━━
Class: ClaimManager

Method: async def claim(self, window_id: str, order_result: OrderResult) -> ClaimResult
  1. Tunggu resolusi on-chain (poll setiap 5 detik, max 15 menit)
  2. Cek wallet untuk winning shares via Polymarket API
  3. Jika winning shares ada → kirim redeem request via Gasless Relayer
  4. Jika relayer tidak respond dalam cfg.CLAIM_RETRY_TIMEOUT_SEC → masuk retry queue
  5. Retry queue: max cfg.CLAIM_RETRY_MAX attempts
     Backoff: cfg.CLAIM_RETRY_INTERVAL_SEC, 2×, 4× (capped di 120s)
  6. Jika semua retry gagal → log PENDING_MANUAL ke event_log, emit alert ke CLI
  7. Jika PAPER_TRADING_MODE → simulasikan claim, tidak ada actual API call

Method: async def _check_wallet_type(self) -> Literal["PROXY","EOA","GNOSIS"]
  - Check pada INIT apakah wallet adalah Proxy/Gnosis (support auto-claim) atau EOA
  - Jika EOA → set self.eoa_warning = True
  - EOA_WARNING ditampilkan sebagai WARNING permanen di CLI header (bukan LOCKDOWN)

@dataclass
class ClaimResult:
    status: Literal["AUTO","PENDING_RETRY","PENDING_MANUAL","LOSS","NOT_APPLICABLE","PAPER"]
    window_id: str
    payout_usd: float
    claim_method: Literal["AUTO","MANUAL","PENDING","N-A","PAPER"]
    claimed_at: Optional[float]
    retry_count: int
    is_paper: bool

FORMAT OUTPUT:
- Semua network calls harus punya timeout eksplisit
- Jangan gunakan bare except — tangkap aiohttp.ClientError, asyncio.TimeoutError secara spesifik
- Setiap state change → emit ke event_log
- Tulis semua file secara lengkap
```

---

## ITERASI 5 — CIRCUIT BREAKER + SAFETY MONITOR

```
PERAN:
Kamu adalah Senior Risk Analyst yang memahami bahwa preservasi modal lebih
penting dari profit. Kamu menulis risk systems yang fail-safe: jika ada
keraguan, system berhenti — bukan melanjutkan.

TUGAS:
Implementasikan core/circuit_breaker.py dan risk/safety_monitor.py secara lengkap.

KONTEKS:
SKIP     = satu window dilewati, otomatis lanjut ke window berikutnya
LOCKDOWN = seluruh sesi berhenti, butuh manual restart operator

TUGAS DETAIL:

━━━ FILE 1: core/circuit_breaker.py ━━━
Class: CircuitBreaker

State machine: NORMAL → LOCKDOWN → COOLDOWN → NORMAL

Method: def record_loss(self) -> BotMode
  - Increment consecutive_loss_count (gunakan asyncio.Lock)
  - Jika consecutive_loss_count >= cfg.CIRCUIT_BREAKER_MAX_LOSS → trigger LOCKDOWN
  - Jika MAX_DAILY_LOSS_USD > 0 dan daily_loss >= MAX_DAILY_LOSS_USD → trigger LOCKDOWN

Method: def record_win(self) -> None
  - Reset consecutive_loss_count ke 0 (gunakan asyncio.Lock)

Method: def record_skip(self) -> None
  - Tidak affect consecutive_loss_count (SKIP bukan LOSS)

Method: async def trigger_lockdown(self, reason: str) -> None
  - Set mode = LOCKDOWN (asyncio.Lock)
  - Log LOCKDOWN event ke event_log dengan reason dan full state snapshot
  - Emit alert ke CLI (merah, blink jika rich support)
  - Mulai cooldown timer:
    reason == "CIRCUIT_BREAKER" atau "DAILY_LOSS_LIMIT" → cfg.COOLDOWN_CIRCUIT_BREAKER_SEC
    reason == "DATA_STALE" atau "SYNC_LATENCY" → cfg.COOLDOWN_DATA_STALE_SEC

Method: async def attempt_resume(self) -> ResumeResult
  Implementasikan 4 langkah LOCKDOWN Resume Protocol secara eksplisit:

  STEP 1 — Cooldown Check:
    elapsed = time.time() - lockdown_triggered_at
    required = cfg.COOLDOWN_CIRCUIT_BREAKER_SEC atau cfg.COOLDOWN_DATA_STALE_SEC
    Jika elapsed < required → return ResumeResult(success=False, reason="COOLDOWN_NOT_ELAPSED",
                                                   remaining_sec=int(required-elapsed))

  STEP 2 — Pre-resume Checklist:
    checks = {
      "hl_feed_connected": hl_feed.is_connected,
      "poly_feed_connected": poly_feed.is_connected,
      "chainlink_fresh": chainlink.last_event is not None and chainlink.last_event.age_seconds < 15,
      "balance_sufficient": wallet_balance >= cfg.BASE_SHARES * cfg.MAX_POSITION_USD * cfg.MIN_TRADE_RESERVE,
      "no_overdue_claims": claim_manager.unclaimed_since < 30 * 60
    }
    failed = [k for k, v in checks.items() if not v]
    Jika failed → return ResumeResult(success=False, failed_checks=failed)

  STEP 3 — State Reset:
    self.consecutive_loss_count = 0
    engine_state.order_sent = False
    signal_processor.reset_cvd()
    # Session P&L dan trade log TIDAK di-reset — append only

  STEP 4 — Soft Start:
    engine_state.soft_start = True
    # Window pertama setelah resume: MONITOR only (skip ARMED evaluation)
    # Window kedua: clear soft_start, operasi normal
    return ResumeResult(success=True)

━━━ FILE 2: risk/safety_monitor.py ━━━
Class: SafetyMonitor

Jalankan monitoring loop setiap 0.5 detik sebagai asyncio Task terpisah.
Untuk setiap trigger, evaluasi kondisinya, emit SafetyEvent, panggil circuit_breaker:

Trigger → Action:
DATA_STALE        : source tidak update > cfg.WS_STALE_THRESHOLD_SEC → LOCKDOWN
CHAINLINK_UNSTABLE: abs(tick[0] - tick[2]) > cfg.CHAINLINK_VOLATILITY_SKIP_USD → SKIP
SYNC_LATENCY      : abs(hl_last_ts - poly_last_ts) > cfg.SYNC_LATENCY_MAX_SEC → LOCKDOWN
CIRCUIT_BREAKER   : consecutive_loss >= cfg.CIRCUIT_BREAKER_MAX_LOSS → LOCKDOWN
DAILY_LOSS_LIMIT  : daily_loss >= cfg.MAX_DAILY_LOSS_USD (jika MAX_DAILY_LOSS_USD > 0) → LOCKDOWN
SLIPPAGE_EXCEEDED : odds_delta > adaptive_threshold → CANCEL (SKIP)
STRIKE_PRICE_STALE: chainlink.age > cfg.CHAINLINK_MAX_AGE_SEC saat INIT → SKIP window
WINDOW_EXPIRED    : time_remaining < cfg.GOLDEN_WINDOW_END dan belum ada order → SKIP
ODDS_OUT_OF_RANGE : ask di luar [cfg.ODDS_MIN, cfg.ODDS_MAX] → SKIP (Gate 4 sudah handle ini,
                    SafetyMonitor juga monitor sebagai backup)
HIGH_VOL_SKIP     : CHAINLINK_UNSTABLE=True TAPI Gap > 2×threshold → log sebagai HIGH_VOL_SKIP,
                    tetap SKIP (jangan override safety gate), log terpisah untuk analisis post-hoc

Method: async def run(self, state: SharedBotState) -> None

@dataclass
class SafetyEvent:
    timestamp: float
    trigger: str
    mode: Literal["SKIP","LOCKDOWN","CANCEL"]
    window_id: str
    details: str
    state_snapshot: dict

FORMAT OUTPUT:
- CircuitBreaker harus thread-safe: gunakan asyncio.Lock untuk semua state mutation
- Setiap LOCKDOWN dan SKIP → wajib tulis ke event_log.csv dengan semua field
- Tulis file secara lengkap
```

---

## ITERASI 6 — AUDIT LOGGER (4 CSV + JSON State)

```
PERAN:
Kamu adalah Senior Backend Engineer spesialis data pipeline dan audit systems.
Kamu memahami bahwa audit log adalah sumber kebenaran — tidak boleh ada data loss,
korupsi, atau race condition saat menulis.

TUGAS:
Implementasikan audit logging system yang menulis ke EMPAT CSV dan satu JSON state.

KONTEKS:
- trade_log.csv        : setiap filled order — 32 field sesuai PRD v2.3 Section 08.1
- skip_log.csv         : setiap window yang di-SKIP — 21 field sesuai PRD v2.3 Section 08.2
- market_snapshot.csv  : kondisi market setiap SNAPSHOT_INTERVAL_SEC — 23 field
- session_summary.csv  : ringkasan per session run — 30 field
- event_log.csv        : semua events sistem (LOCKDOWN, WS_RECONNECT, dsb)
- engine_state.json    : in-memory state, flush ke disk setiap cfg.LOG_FLUSH_INTERVAL_SEC

Append-only untuk semua CSV — tidak pernah overwrite.
File rotation: buat file baru setiap cfg.LOG_ROTATION_DAYS hari.
SATU asyncio.Lock per file — tidak boleh concurrent write ke file yang sama.

TUGAS DETAIL — Tulis logs/audit_logger.py:

━━━ TRADE LOG (trade_log.csv) — 32 FIELD PERSIS ━━━
Gunakan PERSIS kolom berikut (dari PRD v2.3 Section 08.1):
session_id, window_id, timestamp_trigger, timestamp_order_sent, timestamp_confirmed,
side, strike_price, hl_price_at_trigger, gap_value, gap_threshold_used, atr_regime,
cvd_60s, cvd_threshold_used, cvd_threshold_pct, velocity, entry_odds,
odds_in_sweet_spot, spread_pct, expected_odds, mispricing_delta, slippage_delta,
slippage_threshold_used, blockchain_latency_ms, shares_bought, cost_usdc, result,
resolution_price, payout_usdc, pnl_usdc, claim_method, claim_timestamp, bot_version

Field yang belum tersedia saat write pertama boleh diisi None/empty TAPI kolom tetap harus ada.
Field yang diupdate post-hoc: resolution_price, payout_usdc, pnl_usdc, claim_method, claim_timestamp
Implementasikan: async def update_trade_resolution(window_id, resolution_price, payout, claim_result)

━━━ SKIP LOG (skip_log.csv) — 21 FIELD ━━━
Gunakan PERSIS kolom berikut (dari PRD v2.3 Section 08.2):
session_id, window_id, timestamp, skip_reason, skip_stage,
gap_value, gap_threshold, gap_gate_pass,
cvd_value, cvd_gate_pass,
liquidity_gate_pass,
current_ask, min_odds, max_odds, odds_gate_pass,
golden_window_gate_pass, velocity_gate_pass, slippage_gate_pass,
t_remaining_sec, would_have_won, chainlink_age_sec

Field would_have_won: diisi None saat skip terjadi.
Implementasikan: async def update_skip_would_have_won(window_id: str, resolution_direction: str) -> None
  Logic: untuk setiap row di skip_log dengan window_id ini,
  update would_have_won = True jika gap_direction_saat_skip == resolution_direction

━━━ MARKET SNAPSHOT (market_snapshot.csv) — 23 FIELD ━━━
Dipanggil setiap cfg.SNAPSHOT_INTERVAL_SEC detik oleh SignalProcessor.
Gunakan PERSIS kolom berikut (dari PRD v2.3 Section 08.3):
session_id, window_id, timestamp, t_remaining_sec, strike_price,
hl_price, gap, gap_direction, atr_60m, atr_regime,
cvd_60s, cvd_aligned, avg_volume_per_min,
poly_up_odds, poly_down_odds, poly_up_ask_depth, poly_down_bid_depth, spread_pct,
dual_side_ok, chainlink_age_sec, bot_mode, all_gates_pass, window_result

Field window_result: diisi None saat snapshot.
Implementasikan: async def update_snapshot_window_result(window_id: str, result: str) -> None

━━━ SESSION SUMMARY (session_summary.csv) — 30 FIELD ━━━
Di-append saat bot shutdown (graceful atau LOCKDOWN). Satu baris per session.
Gunakan PERSIS kolom berikut (dari PRD v2.3 Section 08.4):
session_id, start_time, end_time, duration_min, bot_version, bot_mode,
total_windows, windows_traded, windows_skipped, windows_locked,
wins, losses, win_rate, total_cost_usdc, total_payout_usdc, net_pnl_usdc,
avg_entry_odds, avg_gap_at_entry, avg_blockchain_latency_ms,
skip_gap_insufficient, skip_cvd_not_aligned, skip_odds_too_low, skip_odds_too_high,
skip_no_liquidity, skip_slippage, skip_other,
lockdown_triggers, unclaimed_balance_usdc, auto_claimed_usdc, manual_claim_required

Implementasikan: async def write_session_summary(session_stats: SessionStats) -> None

━━━ EVENT LOG (event_log.csv) — 8 FIELD ━━━
timestamp, event_type, window_id, trigger, mode, details, gate_failed, state_snapshot_json

event_type values (exhaustive):
TRADE_FILL, SKIP, LOCKDOWN, RESUME, DATA_STALE, SLIPPAGE_EXCEEDED,
ODDS_OUT_OF_RANGE, CIRCUIT_BREAKER, WS_RECONNECT, CLAIM_SUCCESS,
CLAIM_RETRY, CLAIM_PENDING_MANUAL, WS_HEARTBEAT_TIMEOUT,
CHAINLINK_STALE, HIGH_VOL_SKIP, QUEUE_FULL, STARTUP, SHUTDOWN,
ORDER_TIMEOUT, DAILY_LOSS_LIMIT, POSITION_TOO_LARGE

━━━ ENGINE STATE (engine_state.json) ━━━
- Simpan sebagai Python dict in-memory — akses O(1)
- Flush ke disk setiap cfg.LOG_FLUSH_INTERVAL_SEC detik
- Atomic write: tulis ke {STATE_FILE}.tmp dulu, lalu os.rename() → tidak ada partial write
- Sertakan semua field dari PRD v2.3 engine_state.json spec

Method: async def log_trade(self, trade: TradeRecord) -> None
Method: async def log_skip(self, skip: SkipRecord) -> None
Method: async def log_snapshot(self, snapshot: SnapshotRecord) -> None
Method: async def log_event(self, event: EventRecord) -> None
Method: async def flush_state(self, state: EngineState) -> None
Method: async def write_session_summary(self, stats: SessionStats) -> None
Method: async def update_trade_resolution(self, window_id: str, ...) -> None
Method: async def update_skip_would_have_won(self, window_id: str, direction: str) -> None
Method: async def update_snapshot_window_result(self, window_id: str, result: str) -> None
Method: def _get_log_path(self, base_path: str) -> Path

FORMAT OUTPUT:
- Gunakan asyncio.Lock yang BERBEDA untuk setiap file CSV
- Atomic write untuk JSON state (write to .tmp → os.rename)
- Datetime format: ISO 8601 dengan timezone UTC
- Tulis file secara lengkap dengan error handling
```

---

## ITERASI 7 — CLI DASHBOARD (Python rich)

```
PERAN:
Kamu adalah Senior Frontend Engineer (terminal UI) spesialis Python rich library.
Kamu membuat dashboard yang informatif, tidak flickering, dan berjalan mulus
di VPS dengan resource terbatas.

TUGAS:
Implementasikan cli/dashboard.py — 6-panel real-time terminal dashboard.

KONTEKS:
- Gunakan rich.Live dengan refresh_per_second=cfg.CLI_REFRESH_RATE (default 4)
- Panel B (harga) dan C (CVD): update setiap event dari queue
- Panel D (order book): update setiap cfg.CLI_ORDERBOOK_UPDATE_SEC detik
- Panel F (trade log): update hanya saat ada trade baru (event-driven)
- Panel F rows: cfg.CLI_TRADE_LOG_ROWS (default 10)
- Keyboard controls: Q=quit graceful, P=pause (no orders), R=resume, L=show locks
- Jika cfg.PAPER_TRADING_MODE=True → tampilkan badge [PAPER MODE] permanen di Panel A
- Jika wallet type EOA → tampilkan badge [EOA - MANUAL CLAIM] permanen di Panel A

LAYOUT 6-PANEL (implementasikan PERSIS seperti wireframe PRD v2.3 Section 07):

Panel A — Header Bar (update 1 detik):
  "BTC SNIPER v2.3  [MODE]  Window: {window_id}   T-{remaining}s  {timestamp}"
  "Wallet: {wallet_type}  │  Balance: ${balance}  │  Unclaimed: ${unclaimed}"
  Warna mode: HIJAU=NORMAL, KUNING=ARMED/SKIP, MERAH=LOCKDOWN

Panel B — Live Price & Gap:
  HL Price, Strike, GAP dengan arah [UP]/[DOWN]
  Velocity (1.5s), ATR (60m) dengan regime label
  Warna GAP: HIJAU jika > threshold, MERAH jika tidak

Panel C — CVD Chart ASCII:
  Bar chart horizontal untuk BUY volume, SELL volume, NET CVD
  Tampilkan: avg_vol_per_min, cvd_threshold, cvd_percentage dari threshold
  Label ALIGNED ↑/↓ atau MIXED

Panel D — Order Book Depth:
  Visual bar UP ask/bid dan DOWN ask/bid
  Spread %, mispricing status dengan expected_odds vs current_ask

Panel E — Safety Gates:
  7 gate dengan status [PASS]/[FAIL]/[N-A] dan nilai aktual
  Gate numbering sesuai PRD v2.3: Gate 4 = Odds Boundary
  Chainlink age, Polymarket sync latency
  Warna: HIJAU=PASS, MERAH=FAIL, DIM=N-A

Panel F — Session P&L + Trade History:
  Running stats: P&L, W/L/Skip counts, win rate
  Tabel trade history (cfg.CLI_TRADE_LOG_ROWS trade terakhir)
  Kolom: #, TIME, RES, SIDE, ODDS, GAP, CVD%, VEL, SPR, SLIP, CLAIM

KEYBOARD HANDLING:
  - Gunakan aioconsole — non-blocking
  - Q → trigger graceful shutdown
  - P → set PAUSED flag (safety monitor tetap jalan, tidak ada order)
  - R → clear PAUSED flag
  - L → tampilkan modal overlay: semua active locks dan circuit breaker state

RENDERING STRATEGY (mencegah flicker dan CPU spike):
  - Jangan refresh semua panel sekaligus setiap cycle
  - Panel B, C, E: update setiap tick (dari asyncio event)
  - Panel D: update setiap cfg.CLI_ORDERBOOK_UPDATE_SEC detik (timer)
  - Panel F: update hanya saat ada trade baru (event-driven, bukan polling)
  - Gunakan rich.Live dengan transient=False

FORMAT OUTPUT:
- Tidak ada print() langsung — semua output via rich.Console
- Dashboard tidak boleh crash jika data belum tersedia — handle None dengan "— WAITING DATA —"
- Tulis file secara lengkap
```

---

## ITERASI 8 — MAIN ENGINE + INTEGRATION

```
PERAN:
Kamu adalah Systems Architect yang mengintegrasikan semua komponen menjadi
satu cohesive system. Kamu memastikan startup sequence benar, shutdown bersih,
dan tidak ada race condition antar komponen.

TUGAS:
Implementasikan core/engine.py dan main.py — titik integrasi seluruh sistem.

KONTEKS:
Bot harus survive: WebSocket drops, Chainlink delays, Polygon congestion,
queue overflow, dan unexpected exceptions tanpa crash.

TUGAS DETAIL:

━━━ FILE 1: core/engine.py ━━━
Class: BotEngine

STARTUP SEQUENCE (async def start()):
  1. Load dan validate BotConfig
  2. Init AuditLogger, log STARTUP event ke event_log
  3. Check wallet type (PROXY/GNOSIS vs EOA) → set warning flag jika EOA
  4. Connect ChainlinkFeed, validate koneksi (raise jika gagal)
  5. Connect HyperliquidFeed
  6. Connect PolymarketFeed
  7. Init SignalProcessor, GateEvaluator, OrderExecutor, ClaimManager
  8. Init CircuitBreaker, SafetyMonitor
  9. Mulai asyncio tasks (simpan semua di self._tasks: set[asyncio.Task]):
     - asyncio.create_task(hl_feed.start(queue))
     - asyncio.create_task(poly_feed.start(queue))
     - asyncio.create_task(chainlink.start_polling(queue))
     - asyncio.create_task(signal_processor.run(queue))
     - asyncio.create_task(safety_monitor.run(state))
     - asyncio.create_task(dashboard.run())
     - asyncio.create_task(_periodic_state_flush())
     - asyncio.create_task(_periodic_snapshot_writer())
  10. Log STARTUP_COMPLETE ke event_log
  11. Masuk ke main_loop()

TASK SUPERVISOR (implementasikan):
  Jika feed task crash (exception) → attempt restart max 3×
  Jika 3× restart gagal → trigger_lockdown("FEED_TASK_CRASHED")
  Gunakan asyncio.gather(return_exceptions=True) untuk monitor tasks

MAIN LOOP (async def main_loop()):
  Setiap window baru (setiap 5 menit, deteksi via get_time_remaining() < threshold):

  WINDOW INIT:
  1. Ambil strike_price via chainlink.get_strike_price()
     Validasi: jika strike_price.age > cfg.CHAINLINK_MAX_AGE_SEC → log STRIKE_PRICE_STALE,
     tunggu update baru (max 15 detik) atau SKIP window
  2. Hitung window_slug = get_current_window_slug()
  3. await poly_feed.subscribe(window_slug)
  4. Reset window state: cvd (via signal_processor.reset_cvd()),
     order_sent=False, velocity_buffer clear
  5. Inisialisasi session_id jika belum ada
  6. Jika engine_state.soft_start == True → MONITOR only, skip ARMED evaluation

  WAIT FOR GOLDEN WINDOW:
  7. Tunggu time_remaining <= cfg.GOLDEN_WINDOW_START

  GOLDEN WINDOW LOOP (T-60s hingga T-42s):
  8. Setiap detik:
     a. Evaluasi GateEvaluator.evaluate()
     b. Jika all_pass:
        - Execute order: order_result = await order_executor.execute(gate_result, window_slug)
        - Set order_sent = True
        - Log ke trade_log.csv (semua 32 field yang tersedia saat ini)
        - Tunggu resolusi: claim_result = await claim_manager.claim(window_slug, order_result)
        - Keluar dari golden window loop
     c. Jika fail:
        - Log ke skip_log.csv dengan GateResult.to_csv_row()
        - Lanjut loop
  9. Jika T < GOLDEN_WINDOW_END tanpa order → WINDOW_EXPIRED → SKIP

  WINDOW SETTLE (Step 10):
  10. Dapatkan resolution_direction dari chainlink/polymarket
  11. Update trade_log: resolution_price, payout, pnl, claim_method
  12. Update skip_log: update_skip_would_have_won(window_slug, resolution_direction)
  13. Update market_snapshot: update_snapshot_window_result(window_slug, resolution_direction)
  14. Update session stats: wins, losses, skips, cumulative P&L
  15. CircuitBreaker: record_win() atau record_loss() atau record_skip()
  16. Jika circuit_breaker → LOCKDOWN: hentikan main_loop
  17. Write session_summary jika akhir hari (deteksi pergantian hari)
  18. Lanjut ke window berikutnya

SHUTDOWN SEQUENCE (async def stop()):
  - Set shutdown flag
  - Cancel semua tasks dalam self._tasks dengan timeout 5 detik
  - Flush state ke JSON
  - Flush semua pending log ke CSV (trade, skip, snapshot, event)
  - Write session_summary.csv (satu baris untuk session ini)
  - Log SHUTDOWN event ke event_log
  - Close semua WebSocket connections
  - Log "All connections closed, shutdown complete"

━━━ FILE 2: main.py ━━━
- Entry point: python main.py
- Parse argument: --paper (override PAPER_TRADING_MODE=True)
- Tampilkan startup banner dengan semua config values (dari validate_config)
- Jika PAPER_TRADING_MODE=True → cetak prominent warning box
- Handle KeyboardInterrupt → graceful shutdown via engine.stop()
- Handle uncaught exception → log ke event_log → graceful shutdown
- asyncio.run(engine.start())

FORMAT OUTPUT:
- Gunakan asyncio.gather() dengan return_exceptions=True untuk task monitoring
- Implementasikan task supervisor: crash → restart 3× → LOCKDOWN
- Semua asyncio.create_task() disimpan dalam set untuk proper cancellation
- Tulis semua file secara lengkap tanpa disingkat
```

---

## ITERASI 9 — TESTING & VALIDATION

```
PERAN:
Kamu adalah Senior QA Engineer spesialis asyncio testing dan trading system validation.
Kamu menulis tests yang benar-benar menguji behavior kritis, bukan hanya happy path.

TUGAS:
Tulis test suite lengkap untuk komponen paling kritis.

TUGAS DETAIL — Buat direktori tests/ dengan file berikut:

━━━ tests/test_gates.py ━━━
Test setiap gate secara isolated (sesuai urutan PRD v2.3 — Gate 4 = Odds Boundary):
- test_gate1_pass_normal_regime()
- test_gate1_fail_gap_too_small()
- test_gate1_low_vol_regime_higher_threshold()
- test_gate2_fail_cvd_misaligned()
- test_gate3_fail_spread_too_wide()
- test_gate3_fail_no_mispricing()
- test_gate4_fail_odds_too_high()           ← Gate 4 = Odds Boundary
- test_gate4_fail_odds_too_low()
- test_gate4_sweet_spot_detection()
- test_gate5_fail_outside_golden_window()  ← Gate 5 = Timing
- test_gate6_fail_velocity_too_low()       ← Gate 6 = Velocity
- test_gate6_pass_when_disabled()
- test_gate7_fail_duplicate_order()        ← Gate 7 = No Duplicate
- test_all_gates_pass_returns_correct_side()
- test_short_circuit_stops_at_first_fail()
- test_gate_result_to_csv_row_has_correct_keys()

━━━ tests/test_signal_processor.py ━━━
- test_cvd_rolling_window_drops_old_entries()
- test_cvd_threshold_scales_with_volume()
- test_atr_regime_detection_low()
- test_atr_regime_detection_high()
- test_velocity_calculation_correct_delta()
- test_gap_threshold_changes_with_regime()
- test_reset_cvd_clears_accumulator()

━━━ tests/test_circuit_breaker.py ━━━
- test_three_consecutive_losses_trigger_lockdown()
- test_win_resets_consecutive_counter()
- test_skip_does_not_affect_counter()
- test_lockdown_blocks_new_orders()
- test_resume_checklist_fails_if_feed_down()
- test_daily_loss_limit_triggers_lockdown()
- test_timeout_does_not_increment_counter()    ← OrderResult TIMEOUT bukan LOSS
- test_paper_fill_does_not_affect_counter()

━━━ tests/test_audit_logger.py ━━━
- test_trade_log_creates_header_on_new_file()
- test_trade_log_has_32_columns()              ← validasi jumlah field
- test_trade_log_appends_correctly()
- test_skip_log_has_21_columns()
- test_skip_log_would_have_won_update()
- test_market_snapshot_has_23_columns()
- test_snapshot_window_result_update()
- test_session_summary_has_30_columns()
- test_event_log_all_event_types_serializable()
- test_state_flush_atomic_write()
- test_log_rotation_creates_new_file()
- test_concurrent_writes_no_corruption()  (asyncio.gather 10 concurrent writes)

━━━ tests/test_order_executor.py ━━━
- test_paper_mode_returns_paper_fill_no_api_call()
- test_slippage_exceeded_cancels_order()
- test_position_too_large_cancels_order()
- test_timeout_returns_timeout_not_loss()
- test_temporal_slippage_different_from_gate3_mispricing()

SETUP:
- Gunakan pytest-asyncio untuk semua async tests
- Mock semua network calls (WebSocket, Polymarket API, Polygon RPC)
- Gunakan fixtures untuk BotConfig dengan nilai test-safe
- Setiap test harus independent — tidak ada shared state

FORMAT OUTPUT:
- Tulis semua test secara lengkap dengan assert messages yang deskriptif
- Coverage target: semua gate logic, circuit breaker, audit logger, order executor
```

---

## TIPS PENGGUNAAN PROMPT INI

```
URUTAN EKSEKUSI:
Iterasi 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9
Setiap iterasi bergantung pada output iterasi sebelumnya.

CARA TERBAIK MENGGUNAKAN OPUS 4.6:
1. Kirim satu iterasi per conversation turn
2. Setelah Opus menulis kode, review dan konfirmasi sebelum lanjut
3. Jika ada perubahan, sebutkan PERSIS di bagian mana sebelum kirim iterasi berikutnya
4. Sertakan kode yang sudah dihasilkan sebagai konteks di iterasi berikutnya
5. Sertakan .env.example sebagai konteks di setiap iterasi agar Opus tahu config yang aktif

CHECKPOINTS WAJIB SEBELUM ITERASI 8 (INTEGRATION):
□ config.py validate_config() sudah ditest manual dengan .env.example
□ BASE_SHARES=1.0 dan MAX_POSITION_USD=10.0 sudah dikonfirmasi di .env
□ Semua feed bisa connect dan emit events (test dengan paper mode)
□ Gate evaluator menghasilkan GateResult dengan 7 gate_statuses yang benar
□ Gate 4 = Odds Boundary, Gate 5 = Golden Window (sesuai PRD v2.3)
□ CSV validation:
   □ trade_log.csv: tulis 1 dummy trade, validasi 32 kolom benar di spreadsheet
   □ skip_log.csv: tulis 1 dummy skip, validasi 21 kolom dengan gate status benar
   □ market_snapshot.csv: jalankan MONITOR 1 window, pastikan snapshot setiap 5 detik
   □ session_summary.csv: shutdown bot, validasi 1 baris summary terbentuk
   □ engine_state.json: kill -9 saat flush, validasi tidak ada partial write
□ Circuit breaker state machine: 3 loss → LOCKDOWN, resume protocol 4 langkah benar
□ PAPER_TRADING_MODE=True di semua test awal

JIKA OPUS MEMBERIKAN PLACEHOLDER ATAU "# TODO":
Kirim prompt tambahan ini:
"File [nama file] di bagian [nama method] masih placeholder.
Tulis implementasi lengkap untuk bagian tersebut.
Jangan gunakan 'pass', '# TODO', atau '...' — tulis kode yang benar-benar berjalan."

CATATAN VERSI:
Semua output harus menggunakan versi "2.3" — bukan "2.2".
BOT_VERSION = "2.3" di config, banner, log, dan engine_state.
```

---

*Revised Master Prompt v2.3 — Post-Audit April 2026*
*Skor sebelum audit: 78/100 · Skor target setelah perbaikan: 90+/100*
