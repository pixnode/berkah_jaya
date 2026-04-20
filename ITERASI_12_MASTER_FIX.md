# ITERASI 12 — MASTER FIX: CONFIG MISMATCH + POLYMARKET STARTUP + SAFE WALLET
### Zero-tolerance audit prompt untuk Polymarket BTC Sniper v2.3
`Triggered by: Akumulasi AttributeError dari inkonsistensi nama field antar file`

---

```
PERAN:
Kamu adalah Senior Python Developer yang melakukan audit menyeluruh terhadap
codebase Polymarket BTC Sniper v2.3. Tugasmu adalah menemukan DAN memperbaiki
SEMUA inkonsistensi nama field antara config.py, signal_processor.py,
engine.py, safety_monitor.py, dan polymarket_ws.py dalam SATU iterasi.
Tidak ada "TODO" atau "akan diperbaiki nanti".

════════════════════════════════════════════════════════════════
BAGIAN A — AUDIT DAN FIX config.py
════════════════════════════════════════════════════════════════

MASALAH YANG DITEMUKAN:
Beberapa nama field di BotConfig tidak konsisten dengan nama yang diakses
di file lain. Ini menyebabkan AttributeError saat runtime.

ATURAN WAJIB:
Nama field di BotConfig HARUS PERSIS SAMA dengan yang diakses di semua file.
Jika ada konflik, gunakan nama dari PRD v2.3 sebagai referensi final.

LANGKAH 1 — Jalankan perintah ini di terminal untuk temukan semua cfg.XXX:
  grep -rh "self\._cfg\." /root/berkah_jaya/btc_sniper/ \
    --include="*.py" | grep -o "_cfg\.[A-Z_]*" | sort -u

LANGKAH 2 — Bandingkan hasilnya dengan field yang ada di BotConfig.
  Setiap cfg.XXX yang diakses tapi TIDAK ADA di BotConfig = error.

FIELD YANG WAJIB ADA DI BotConfig (nama PERSIS seperti ini):

  # STRATEGY CORE
  BASE_SHARES: float = 1.0
  MAX_POSITION_USD: float = 10.0
  GAP_THRESHOLD_DEFAULT: float = 45.0      <- nama ini, bukan GAP_THRESHOLD_NORMAL
  GAP_THRESHOLD_LOW_VOL: float = 60.0      <- nama ini, bukan GAP_THRESHOLD_LOW
  GAP_THRESHOLD_HIGH_VOL: float = 35.0     <- nama ini, bukan GAP_THRESHOLD_HIGH
  ATR_LOW_THRESHOLD: float = 50.0
  ATR_HIGH_THRESHOLD: float = 150.0
  ATR_LOOKBACK_CANDLES: int = 12

  # ODDS
  ODDS_MIN: float = 0.58
  ODDS_MAX: float = 0.82
  ODDS_SWEET_SPOT_LOW: float = 0.62
  ODDS_SWEET_SPOT_HIGH: float = 0.76

  # CVD
  CVD_VOLUME_WINDOW_MINUTES: int = 30
  CVD_THRESHOLD_PCT: float = 25.0
  CVD_CALC_INTERVAL_MS: int = 500

  # VELOCITY
  VELOCITY_ENABLED: bool = True
  VELOCITY_MIN_DELTA: float = 15.0
  VELOCITY_WINDOW_SECONDS: float = 1.5

  # TIMING
  GOLDEN_WINDOW_START: int = 60
  GOLDEN_WINDOW_END: int = 42

  # SLIPPAGE
  SLIPPAGE_THRESHOLD_NORMAL: float = 1.0
  SLIPPAGE_THRESHOLD_ELEVATED: float = 1.5
  SLIPPAGE_THRESHOLD_HIGH: float = 2.0
  SPREAD_MAX_PCT: float = 3.0
  MISPRICING_MULTIPLIER: float = 0.15
  MISPRICING_MIN_EDGE: float = 0.02

  # QUEUE
  QUEUE_HL_MAXSIZE: int = 2000
  MIN_TRADE_SIZE_USD: float = 0.0

  # RISK
  CIRCUIT_BREAKER_MAX_LOSS: int = 3
  COOLDOWN_CIRCUIT_BREAKER_SEC: int = 900
  COOLDOWN_DATA_STALE_SEC: int = 300
  MAX_DAILY_LOSS_USD: float = 0.0
  MIN_TRADE_RESERVE: int = 5

  # DATA FRESHNESS
  CHAINLINK_MAX_AGE_SEC: int = 10
  CHAINLINK_MAX_AGE_ENTRY_SEC: int = 25
  CHAINLINK_VOLATILITY_SKIP_USD: float = 35.0
  CHAINLINK_POLL_INTERVAL_SEC: int = 3
  WS_HEARTBEAT_INTERVAL_SEC: int = 3
  WS_STALE_THRESHOLD_SEC: int = 5
  WS_RECONNECT_MAX_RETRY: int = 5
  WS_RECONNECT_BASE_DELAY_SEC: int = 1
  WS_RECONNECT_MAX_DELAY_SEC: int = 30
  SYNC_LATENCY_MAX_SEC: int = 10

  # BLOCKCHAIN & CLAIM
  POLYGON_GAS_TIP_MULTIPLIER: float = 1.0
  CLAIM_RETRY_MAX: int = 3
  CLAIM_RETRY_TIMEOUT_SEC: int = 30
  CLAIM_RETRY_INTERVAL_SEC: int = 60
  POLY_CHAIN_ID: int = 137

  # LOGGING
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
  STATE_SNAPSHOT_INTERVAL_SEC: int = 5    <- field ini wajib ada

  # SAFETY MONITOR
  SAFETY_MONITOR_STARTUP_GRACE_SEC: int = 60   <- field ini wajib ada

  # OPERATIONAL
  PAPER_TRADING_MODE: bool = True
  BOT_VERSION: str = "2.3"
  LOG_LEVEL: str = "INFO"
  CLI_REFRESH_RATE: int = 4
  CLI_ORDERBOOK_UPDATE_SEC: int = 2
  CLI_TRADE_LOG_ROWS: int = 10

  # CONNECTIONS
  HYPERLIQUID_WS_URL: str = "wss://api.hyperliquid.xyz/ws"
  POLY_WS_URL: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
  CLOB_HOST: str = "https://clob.polymarket.com"
  RELAYER_URL: str = "https://relayer.polymarket.com"
  GAMMA_API_URL: str = "https://gamma-api.polymarket.com"
  POLYGON_RPC_URL: str = ""
  CHAINLINK_CONTRACT_ADDRESS: str = "0xc907E116054Ad103354f2D350FD2514433D57F6F"

  # WALLET
  POLYMARKET_PRIVATE_KEY: str = ""
  POLYMARKET_PROXY_WALLET: str = ""
  POLY_WALLET_TYPE: str = "safe"           <- default "safe" untuk SAFE wallet
  POLY_API_KEY: str = ""
  POLY_API_SECRET: str = ""
  POLY_API_PASSPHRASE: str = ""

TUGAS config.py:
1. Tulis ulang BotConfig dataclass dengan SEMUA field di atas.
   Semua field punya default value — tidak ada "required positional argument".
   KECUALI field berikut yang wajib diisi (tidak boleh kosong saat live mode):
   - POLYMARKET_PRIVATE_KEY
   - POLYMARKET_PROXY_WALLET
   - POLYGON_RPC_URL

2. Tulis fungsi validate_config(cfg: BotConfig) -> None:
   - Jika PAPER_TRADING_MODE=False: raise ConfigurationError jika field wajib kosong
   - Jika PAPER_TRADING_MODE=True: hanya log WARNING jika field wajib kosong, tidak crash
   - Validasi: ODDS_MIN < ODDS_SWEET_SPOT_LOW < ODDS_SWEET_SPOT_HIGH < ODDS_MAX
   - Validasi: GOLDEN_WINDOW_END < GOLDEN_WINDOW_START
   - Validasi: BASE_SHARES * ODDS_MAX <= MAX_POSITION_USD

3. Tulis .env.example lengkap dengan semua field dan komentar singkat.

════════════════════════════════════════════════════════════════
BAGIAN B — FIX signal_processor.py
════════════════════════════════════════════════════════════════

MASALAH YANG DITEMUKAN:
1. cfg.GAP_THRESHOLD_HIGH tidak ada -> harus cfg.GAP_THRESHOLD_HIGH_VOL
2. event.size_usd tidak ada di TradeEvent -> harus dihitung manual
3. SignalState belum punya field buy_volume_60s, sell_volume_60s, latest_odds

TUGAS signal_processor.py:

1. Ganti SEMUA nama field cfg yang salah:
   cfg.GAP_THRESHOLD_HIGH    -> cfg.GAP_THRESHOLD_HIGH_VOL
   cfg.GAP_THRESHOLD_LOW     -> cfg.GAP_THRESHOLD_LOW_VOL
   cfg.GAP_THRESHOLD_NORMAL  -> cfg.GAP_THRESHOLD_DEFAULT

2. Fix filter MIN_TRADE_SIZE_USD:
   HAPUS:
     if event.size_usd < self._cfg.MIN_TRADE_SIZE_USD:
   GANTI DENGAN:
     size_usd = event.size * event.price
     if self._cfg.MIN_TRADE_SIZE_USD > 0 and size_usd < self._cfg.MIN_TRADE_SIZE_USD:
         return

3. Pastikan SignalState dataclass punya SEMUA field ini:
   current_hl_price: float = 0.0
   strike_price: float = 0.0
   gap: float = 0.0
   gap_direction: str = "NEUTRAL"
   gap_threshold: float = 45.0
   vol_regime: str = "NORM"
   atr: float = 0.0
   cvd_60s: float = 0.0
   cvd_threshold: float = 0.0
   cvd_threshold_pct: float = 0.0
   avg_volume_per_min: float = 0.0
   cvd_aligned: bool = False
   cvd_direction: str = "NEUTRAL"
   velocity_1_5s: float = 0.0
   velocity_pass: bool = False
   buy_volume_60s: float = 0.0
   sell_volume_60s: float = 0.0
   latest_odds: object = None

4. Update _handle_trade_event():
   - Saat net_delta > 0: tambahkan ke buy_volume_60s
   - Saat net_delta < 0: tambahkan ke sell_volume_60s (nilai absolut)
   - Reset buy_volume_60s dan sell_volume_60s ke 0 setiap window 60s di-refresh

5. Update cvd_direction setelah setiap CVD calculation:
   if cvd > 0: state.cvd_direction = "UP"
   elif cvd < 0: state.cvd_direction = "DOWN"
   else: state.cvd_direction = "NEUTRAL"

6. Tambahkan method update_odds():
   def update_odds(self, odds_event: object) -> None:
       self._state.latest_odds = odds_event

════════════════════════════════════════════════════════════════
BAGIAN C — FIX polymarket_ws.py: SUBSCRIBE SAAT STARTUP
════════════════════════════════════════════════════════════════

MASALAH YANG DITEMUKAN:
Polymarket WS connect tapi tidak subscribe ke market apapun saat startup.
SafetyMonitor trigger DATA_STALE karena last_message_at = 0 (belum ada message).
Ini false positive karena feed belum ada market untuk di-subscribe.

TUGAS polymarket_ws.py:

1. Tambahkan instance variable di __init__:
   self._current_slug: Optional[str] = None
   self._last_message_at: float = 0.0

2. Tambahkan property is_subscribed:
   @property
   def is_subscribed(self) -> bool:
       return self._current_slug is not None

3. Ubah last_message_at menjadi property:
   @property
   def last_message_at(self) -> float:
       if not self.is_subscribed:
           return time.time()  # belum subscribe = bukan stale
       return self._last_message_at

4. Di method subscribe(), simpan slug:
   async def subscribe(self, market_slug: str) -> None:
       self._current_slug = market_slug
       # ... kirim subscribe message

5. Di method unsubscribe() dan saat reconnect:
   self._current_slug = None

6. Di method start(), subscribe ke window aktif saat pertama connect:
   async def start(self, queue: asyncio.Queue) -> None:
       self._queue = queue
       await self._connect()
       now = int(time.time())
       window_start = now - (now % 300)
       initial_slug = f"btc-updown-5m-{window_start}"
       await self.subscribe(initial_slug)
       logger.info(f"Polymarket: auto-subscribed to initial window {initial_slug}")
       # lanjut ke receive loop

7. Di receive loop, update _last_message_at setiap message masuk:
   self._last_message_at = time.time()

════════════════════════════════════════════════════════════════
BAGIAN D — FIX safety_monitor.py: GUARD CEK POLYMARKET
════════════════════════════════════════════════════════════════

MASALAH YANG DITEMUKAN:
SafetyMonitor cek Polymarket DATA_STALE tanpa tahu apakah feed sudah subscribe.

TUGAS safety_monitor.py:

1. Gunakan SAFETY_MONITOR_STARTUP_GRACE_SEC dari config:
   async def run(self) -> None:
       grace = self._cfg.SAFETY_MONITOR_STARTUP_GRACE_SEC
       logger.info(f"SafetyMonitor starting up — entering {grace}s grace period...")
       await asyncio.sleep(grace)
       logger.info("SafetyMonitor active — checking every 0.5s.")
       while not self._shutdown:
           await self._check_all()
           await asyncio.sleep(0.5)

2. Di method _check_all(), tambahkan guard untuk Polymarket:
   HAPUS:
     poly_age = time.time() - self._poly_feed.last_message_at
     if poly_age > self._cfg.WS_STALE_THRESHOLD_SEC:
         await self._trigger_lockdown("DATA_STALE", ...)

   GANTI DENGAN:
     if self._poly_feed.is_subscribed:
         poly_age = time.time() - self._poly_feed.last_message_at
         if poly_age > self._cfg.WS_STALE_THRESHOLD_SEC:
             await self._trigger_lockdown(
                 "DATA_STALE",
                 f"Polymarket no update for {poly_age:.1f}s > {self._cfg.WS_STALE_THRESHOLD_SEC}s"
             )
     # Jika belum subscribe: skip, ini kondisi normal saat startup

════════════════════════════════════════════════════════════════
BAGIAN E — FIX claim_manager.py: SAFE WALLET SUPPORT
════════════════════════════════════════════════════════════════

KONTEKS:
User menggunakan SAFE wallet (Gnosis Safe) bukan EOA.
SAFE wallet MENDUKUNG auto-claim via Polymarket gasless relayer.
Config POLY_WALLET_TYPE=safe harus dikenali sebagai wallet yang support auto-claim.

TUGAS claim_manager.py:

Update method check_wallet_type():
   async def check_wallet_type(self) -> None:
       wallet_type = self._cfg.POLY_WALLET_TYPE.lower().strip()
       
       if wallet_type in ("proxy", "safe", "gnosis"):
           self._wallet_type = "PROXY"
           self._eoa_warning = False
           logger.info(f"{wallet_type.upper()} wallet detected — auto-claim enabled.")
       elif wallet_type == "eoa":
           self._wallet_type = "EOA"
           self._eoa_warning = True
           logger.warning("EOA wallet detected — auto-claim NOT supported.")
       else:
           self._wallet_type = "EOA"
           self._eoa_warning = True
           logger.warning(f"Unknown wallet type '{wallet_type}' — defaulting to EOA.")

Update .env.example untuk SAFE wallet:
   # POLY_WALLET_TYPE: tipe wallet Polymarket
   # Nilai valid: proxy | safe | gnosis | eoa
   # "safe" = Gnosis Safe wallet, mendukung auto-claim
   # "proxy" = Polymarket Proxy wallet, mendukung auto-claim
   # "eoa" = External Owned Account, TIDAK mendukung auto-claim
   POLY_WALLET_TYPE=safe

════════════════════════════════════════════════════════════════
BAGIAN F — VERIFIKASI AKHIR WAJIB
════════════════════════════════════════════════════════════════

Setelah menulis semua file, WAJIB tampilkan tabel verifikasi ini:

VERIFIKASI 1 — cfg.XXX vs BotConfig:
Untuk setiap cfg.XXX yang diakses di semua file,
konfirmasi ada di BotConfig dengan format:
  signal_processor.py: cfg.GAP_THRESHOLD_HIGH_VOL -> ADA di BotConfig: YA
  signal_processor.py: cfg.GAP_THRESHOLD_LOW_VOL  -> ADA di BotConfig: YA
  ... (semua field)

VERIFIKASI 2 — ss.XXX vs SignalState:
Untuk setiap akses self._signal_processor.state.XXX di engine.py,
konfirmasi ada di SignalState:
  engine.py: ss.current_hl_price  -> ADA di SignalState: YA
  engine.py: ss.buy_volume_60s    -> ADA di SignalState: YA
  engine.py: ss.latest_odds       -> ADA di SignalState: YA
  ... (semua field)

VERIFIKASI 3 — TradeEvent fields:
  TradeEvent punya: timestamp, price, size, side
  TradeEvent TIDAK punya: size_usd (harus dihitung: size * price)
  Konfirmasi tidak ada akses event.size_usd di codebase.

════════════════════════════════════════════════════════════════
FORMAT OUTPUT
════════════════════════════════════════════════════════════════

Tulis file dalam urutan ini:
1. config.py — LENGKAP
2. core/signal_processor.py — LENGKAP
3. feeds/polymarket_ws.py — LENGKAP
4. risk/safety_monitor.py — LENGKAP
5. core/claim_manager.py — LENGKAP

ATURAN PENULISAN:
- Tulis setiap file SECARA LENGKAP — tidak ada "# kode lainnya sama"
- Tidak ada "# TODO", "pass", atau placeholder
- Type hints di semua fungsi
- Docstring singkat di setiap class dan method publik
- Header: # === FILE: path/to/file.py ===
- Setelah semua file, tampilkan 3 tabel verifikasi
```
