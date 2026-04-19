# Polymarket BTC Sniper — PRD v2.3
**Architectural Review Edition · Senior Quant Trader + Senior Backend Engineer**
`Platform: Polymarket / Hyperliquid · April 2026 · Status: Pre-Validation`

---

## Overall Confidence: 68–72% (Pre-Validation)
> Target setelah 3 validasi + paper trading: **80–85%**

| Dimensi | Score | Target |
|---|---|---|
| Strategy Logic | 7.5/10 | 9/10 |
| Risk Management | 8.0/10 | 9/10 |
| Technical Architecture | 7.0/10 | 8.5/10 |
| Execution Realism | 6.5/10 | 8.0/10 |
| Edge Sustainability | 6.0/10 | 7.5/10 |
| Auto Claim Reliability | 8.5/10 | 9.0/10 |
| CLI Observability | 8.0/10 | 9.0/10 |

---

## Changelog v2.1 → v2.3

| Area | Perubahan |
|---|---|
| **NEW** | `MIN_ODDS` / `MAX_ODDS` / Sweet Spot masuk Strategy Core |
| **NEW** | 4-file CSV output spec lengkap dengan semua field |
| **NEW** | `.env` master control — semua parameter vital terkontrol |
| **NEW** | Skip Log & Market Snapshot Log untuk kalibrasi masa depan |
| **NEW** | Session Summary CSV per run |
| **UPDATE** | Gap threshold dynamic (ATR-based) |
| **UPDATE** | CVD threshold berbasis % avg volume |
| **UPDATE** | Adaptive slippage threshold |
| **UPDATE** | LOCKDOWN Resume Protocol |
| **UPDATE** | asyncio.Queue architecture wajib |

---

## 01 · Executive Summary

Bot ini adalah **latency arbitrage system** — bukan prediction system. Bot mengeksploitasi **informasi asimetri temporal**: Hyperliquid bergerak dulu, Polymarket menyesuaikan belakangan. Bot membeli shares yang underpriced di gap repricing itu, dalam odds range yang memberikan risk/reward optimal, lalu auto-claim winnings setelah resolusi.

```
PRINSIP    : Reactionary — bereaksi, tidak memprediksi
SIGNAL     : CVD + Gap dari Strike Price
ODDS RANGE : MIN_ODDS – MAX_ODDS (sweet spot control)
TIMING     : Golden Window T-60s → T-42s
SIZING     : Flat 1× BASE_SHARES
INTERFACE  : CLI Terminal (Python rich)
CONFIG     : 100% dikontrol via .env
```

> **Asumsi kritis yang belum tervalidasi:** Lag repricing Polymarket masih cukup besar untuk dieksploitasi. Harus diukur secara empiris — lihat Section 09.

---

## 02 · Cara Kerja Market

Setiap 5 menit, Polymarket buka satu market baru:

> *"Apakah harga BTC saat window TUTUP ≥ harga saat window BUKA?"*

| Aksi | Kondisi Menang | Kondisi Kalah |
|---|---|---|
| Beli **UP** shares | Harga penutupan ≥ Strike Price | Harga penutupan < Strike Price |
| Beli **DOWN** shares | Harga penutupan < Strike Price | Harga penutupan ≥ Strike Price |

**Payout:** Menang = $1.00/share · Kalah = $0.00/share

### Expected Value Formula

```
EV = (P_win × profit_per_share) − (P_loss × cost_per_share)

Contoh entry di $0.72:
EV = (P_win × $0.28) − (P_loss × $0.72)
EV positif hanya jika P_win > 72%

Target win rate minimum per entry odds:
  Entry $0.60 → harus benar > 60% dari trade
  Entry $0.70 → harus benar > 70% dari trade
  Entry $0.82 → harus benar > 82% dari trade  ← mulai tidak efisien
```

### Resolution Source

**Chainlink BTC/USD Data Stream** — snapshot tepat di detik akhir window. Bukan Hyperliquid, bukan Binance.

> ⚠️ **Risk:** Chainlink update setiap ~10–30 detik atau saat deviasi 0.5%. Ada kemungkinan snapshot resolusi adalah harga 8–15 detik sebelum window tutup.
>
> ✅ **Fix:** Monitor `CHAINLINK_LAST_UPDATE_AGE` real-time. Jika age > 25 detik saat T-60s → SKIP window.

---

## 03 · Strategy Logic

### Pilar 1 — Gap Detection (Hyperliquid)

```
GAP = Harga Hyperliquid (real-time) − Strike Price (Chainlink)

Gap > +GAP_THRESHOLD  →  kandidat UP
Gap < -GAP_THRESHOLD  →  kandidat DOWN
│Gap│ < GAP_THRESHOLD →  SKIP
```

**Gap Threshold Dynamic (ATR-based):**

| ATR Regime | ATR 60m | Gap Threshold | Catatan |
|---|---|---|---|
| Low Vol | < $50 | $60 | Banyak false signal di low vol |
| Normal | $50–$150 | $45 (default) | Kondisi optimal bot |
| High Vol | > $150 | $35 | Threshold turun tapi CVD req naik |

> ⚠️ **Risk:** $45 belum divalidasi secara empiris. Bisa terlalu mudah atau terlalu ketat tergantung kondisi April 2026.
>
> ✅ **Fix:** Validasi 1 di Section 09 — backtest win rate per Gap size bucket.

---

### Pilar 2 — CVD Confirmation (Hyperliquid Trade Feed)

```
CVD (rolling 60s) = Σ(buy_volume) − Σ(sell_volume) dalam 60 detik terakhir

CVD strongly positive + Gap UP   → HIGH CONVICTION UP
CVD strongly negative + Gap DOWN → HIGH CONVICTION DOWN
CVD mixed / flat                 → SKIP
```

**CVD Threshold — Berbasis Persentase Volume (bukan absolut):**

```
avg_volume_per_min = rolling average volume Hyperliquid BTC (30 menit terakhir)
CVD_threshold = avg_volume_per_min × CVD_THRESHOLD_PCT

Default CVD_THRESHOLD_PCT = 0.25 (25% dari avg volume per menit)

Contoh:
  avg volume = $4.2M/menit
  CVD threshold = $4.2M × 0.25 = $1.05M net delta
```

> ⚠️ **Risk:** Angka absolut tidak bermakna jika tidak dibandingkan dengan average volume hari itu.
>
> ✅ **Fix:** CVD_THRESHOLD_PCT dikontrol via .env, bisa diupdate tanpa restart.

---

### Pilar 3 — MIN/MAX ODDS & Sweet Spot *(NEW)*

Ini adalah **filter eksekusi terakhir** sebelum order dikirim. Mendefinisikan range harga shares yang memberikan risk/reward optimal.

```
MIN_ODDS  = 0.58   (default)  →  di bawah ini: suspicious, kemungkinan data error
MAX_ODDS  = 0.82   (default)  →  di atas ini: terlalu mahal, edge sudah habis
SWEET_SPOT = 0.62 – 0.76     →  risk/reward optimal
```

**Kenapa MIN_ODDS diperlukan:**

```
Shares harga $0.52 saat Gap > $45 adalah RED FLAG.
Market seharusnya price UP shares di 75–85% probability.
Jika masih $0.52 → kemungkinan:
  1. Liquidity sangat rendah, spread sangat wide
  2. Data feed error di sisi bot atau Polymarket
  3. Strike price yang bot gunakan berbeda dengan yang Polymarket gunakan
  4. Window belum liquid (baru buka, belum ada market maker)

Entry di odds terlalu murah = entry tanpa informasi yang valid.
```

**Kenapa MAX_ODDS diperlukan:**

```
Shares harga $0.90 → profit hanya $0.10/share
Risk/Reward = $0.90 : $0.10 = 9:1 (sangat buruk)
Market sudah consensus — tidak ada lag repricing tersisa.
Edge sudah fully priced in.
Masuk di $0.90 = betting pada sisa $0.10 dengan risiko $0.90.
```

**Tabel Risk/Reward per Entry Odds:**

| Entry Odds | Profit/Share | Risk/Share | R/R Ratio | Verdict |
|---|---|---|---|---|
| 0.52 | $0.48 | $0.52 | 0.92:1 | ❌ SUSPICIOUS — skip |
| 0.58 | $0.42 | $0.58 | 0.72:1 | ⚠️ MIN boundary |
| 0.62 | $0.38 | $0.62 | 0.61:1 | ✅ Sweet spot entry |
| 0.70 | $0.30 | $0.70 | 0.43:1 | ✅ Sweet spot core |
| 0.76 | $0.24 | $0.76 | 0.32:1 | ✅ Sweet spot exit |
| 0.82 | $0.18 | $0.82 | 0.22:1 | ⚠️ MAX boundary |
| 0.90 | $0.10 | $0.90 | 0.11:1 | ❌ TOO EXPENSIVE — skip |

> 📋 **Note:** Sweet spot 0.62–0.76 adalah range di mana Gap $45+ dengan win rate ~75–85% memberikan EV positif yang signifikan. Di luar range ini, EV positif tapi tipis atau tidak ada.
>
> ✅ **MIN_ODDS dan MAX_ODDS dikontrol penuh via .env** — bisa disesuaikan tanpa menyentuh kode.

---

### Pilar 4 — Dual Side Liquidity (Polymarket CLOB)

| Cek | Kondisi Required | Jika Gagal |
|---|---|---|
| UP ask tersedia | Ada seller di sisi UP | SKIP |
| DOWN bid tersedia | Ada buyer di sisi DOWN | SKIP — market 1 arah |
| Spread sisi target | ≤ SPREAD_MAX_PCT dari mid | SKIP |
| Mispricing terdeteksi | ask < Expected_odds − MISPRICING_MIN_EDGE | SKIP |

**Formula Mispricing:**

```
Expected_odds = 0.50 + (Gap / ATR_5min × MISPRICING_MULTIPLIER)
Mispricing    = True jika current_ask < Expected_odds − MISPRICING_MIN_EDGE

Default:
  MISPRICING_MULTIPLIER = 0.15
  MISPRICING_MIN_EDGE   = 0.02

Contoh: Gap=$100, ATR=$200
  Expected = 0.50 + (0.50 × 0.15) = 0.575
  Mispricing = True jika ask < 0.555
```

---

## 04 · Entry Conditions

**AND logic — semua 7 gate harus PASS. Satu FAIL = SKIP.**

| # | Gate | Parameter | Tujuan | Bisa Skip? |
|---|---|---|---|---|
| 1 | Gap > threshold | Dynamic ATR-based | Core edge | TIDAK |
| 2 | CVD Aligned | % dari avg volume | Filter fake momentum | TIDAK |
| 3 | Dual Side Liquidity | Spread ≤ SPREAD_MAX_PCT | Edge masih ada | TIDAK |
| 4 | **MIN_ODDS ≤ ask ≤ MAX_ODDS** | **Dikontrol .env** | **Sweet spot — risk/reward valid** | **TIDAK** |
| 5 | Golden Window | T-60s hingga T-42s | Buffer blockchain latency | TIDAK |
| 6 | Velocity Filter | > VELOCITY_MIN dalam 1.5 detik | Filter noise | Dikaji |
| 7 | Adaptive Slippage Guard | ≤ SLIPPAGE_THRESHOLD_PCT | Proteksi eksekusi | TIDAK |

**Gate 4 adalah tambahan baru di v2.3** — sebelumnya tidak ada filter odds eksplisit.

**Adaptive Slippage Threshold:**

| ATR Regime | Slippage Threshold |
|---|---|
| Low Vol (ATR < $100) | 1.0% |
| Normal (ATR $100–200) | 1.5% |
| High Vol (ATR > $200) | 2.0% (+ Gap req naik ke $70+) |

---

## 05 · Execution Workflow

> **Wajib sebelum build:** Implementasi `asyncio.Queue` sebagai buffer antara WebSocket dan signal processor.
> ```
> WebSocket Stream → asyncio.Queue(maxsize=100) → Signal Processor → Entry Evaluator → Order Executor
> ```

### Step 01 — INIT
- Query Chainlink BTC/USD → simpan sebagai `STRIKE_PRICE`
- Validasi: `strike_price_age` < 10 detik — jika tidak, SKIP window
- Buka Polymarket CLOB WebSocket untuk window slug
- Reset state: CVD accumulator, Gap tracker, `order_sent=False`, velocity buffer
- Cek wallet type: Proxy/Gnosis Safe → AUTO CLAIM OK · EOA → WARNING permanen

> ⚠️ **Risk:** Chainlink tidak selalu update tepat di detik ke-0 window.
> ✅ **Fix:** Tolak Strike Price jika `strike_price_age > STRIKE_PRICE_MAX_AGE_SEC` (.env).

### Step 02 — MONITOR (T-300s → T-61s)
- Hyperliquid WebSocket → asyncio.Queue: stream harga + trade feed
- Hitung Gap, ATR, CVD rolling 60s setiap detik
- Polymarket CLOB: odds + order book depth setiap 2 detik
- **Market Snapshot Log:** catat ke `market_snapshot.csv` setiap 5 detik (lihat Section 08)
- CLI: update semua panel live
- Heartbeat check: tidak ada update > 5 detik → DATA_STALE → LOCKDOWN

### Step 03 — ARMED (T-60s)
- Mode ARMED — evaluasi entry setiap detik
- CLI: status KUNING — ARMED
- Velocity check aktif
- Jika tidak ada trigger valid sampai T-43s → SKIP, catat ke `skip_log.csv`

### Step 04 — VELOCITY TRIGGER
- Delta harga HL dalam 1.5 detik > `VELOCITY_MIN` → lanjut EVALUATE
- Jika tidak → kembali ke ARMED loop

### Step 05 — EVALUATE (7 Gates)
1. `│Gap│ > GAP_THRESHOLD` (dynamic ATR-based)
2. CVD aligned dengan arah Gap (> CVD threshold)
3. Dual side liquidity OK, spread ≤ `SPREAD_MAX_PCT`
4. **`MIN_ODDS ≤ current_ask ≤ MAX_ODDS`**
5. Masih dalam T-60s hingga T-42s
6. Velocity > `VELOCITY_MIN`
7. `order_sent == False`

Semua PASS → PRE-ORDER · Satu FAIL → catat gate yang gagal ke `skip_log.csv`, kembali ARMED

### Step 06 — PRE-ORDER (Adaptive Slippage Guard)
- Snapshot odds di T_signal
- Bandingkan dengan odds live di T_order
- Delta > `SLIPPAGE_THRESHOLD_PCT` (adaptive) → CANCEL, catat ke skip_log
- OK → EXECUTE

> ⚠️ **Risk:** Blockchain Polygon: konfirmasi 2–8 detik. Di T-52s dengan latency 8 detik → confirmed T-44s. Margin tipis.
> ✅ **Fix:** Pre-sign transaction di T-65s, broadcast di T-58s. Ukur latency empiris dulu (Validasi 3).

### Step 07 — EXECUTE
- Beli UP atau DOWN shares sesuai arah Gap
- Size: `BASE_SHARES` (flat)
- Set `order_sent = True`
- Tulis ke `trade_log.csv` (semua 18 field — lihat Section 08)
- CLI: status HIJAU — ORDER SENT

### Step 08 — WAIT
- Tidak ada aksi setelah order terkirim
- Monitor: filled / partial / rejected
- Chainlink snapshot otomatis di detik terakhir
- CLI: countdown ke resolusi

### Step 09 — AUTO CLAIM
- Cek wallet untuk winning shares setelah resolusi on-chain
- Kirim redeem via Polymarket gasless relayer
- Jika relayer tidak respond dalam `CLAIM_TIMEOUT_SEC` → tambahkan ke retry queue
- Max retry: `CLAIM_MAX_RETRY` kali
- Jika semua retry gagal: log sebagai `PENDING_MANUAL`, alert di CLI
- EOA wallet: log `MANUAL_CLAIM_REQUIRED`, tidak ada auto-claim
- Update `UNCLAIMED_BALANCE` di engine_state

### Step 10 — SETTLE & LOG
- Hitung P&L: `payout − cost`
- Update session stats: W/L/Skip, cumulative P&L, win rate
- Update circuit breaker counter
- Jika `circuit_breaker_count >= CIRCUIT_BREAKER_LIMIT` → LOCKDOWN
- Tulis ke `trade_log.csv`, `session_summary.csv`
- CLI: update Session P&L + Trade History
- Cycle selesai → Step 01

---

## 06 · Safety Gates & Risk Management

### SKIP vs LOCKDOWN

| Dimensi | SKIP | LOCKDOWN |
|---|---|---|
| Scope | Satu window | Seluruh sesi |
| Trigger | Kondisi pasar tidak ideal | Data rusak / circuit breaker |
| Recovery | Otomatis window berikutnya | Manual restart + checklist |
| Order | Tidak ada | Semua freeze |
| CLI | KUNING | MERAH |
| Session stats | Dilanjutkan, skip+1 | Di-freeze |

### Trigger Table

| Trigger | Mode | Kondisi |
|---|---|---|
| `DATA_STALE` | LOCKDOWN | WebSocket tidak update > `DATA_STALE_SEC` |
| `CHAINLINK_UNSTABLE` | SKIP | Volatilitas 3 tick > `CHAINLINK_UNSTABLE_THRESHOLD` |
| `SYNC_LATENCY` | LOCKDOWN | Delta timestamp HL vs Poly > `SYNC_LATENCY_MAX_SEC` |
| `CIRCUIT_BREAKER` | LOCKDOWN | Loss berturut ≥ `CIRCUIT_BREAKER_LIMIT` |
| `SLIPPAGE_EXCEEDED` | CANCEL (SKIP) | Odds delta > `SLIPPAGE_THRESHOLD_PCT` |
| `STRIKE_PRICE_STALE` | SKIP | Chainlink age > `STRIKE_PRICE_MAX_AGE_SEC` |
| `ODDS_OUT_OF_RANGE` | SKIP | ask < MIN_ODDS atau ask > MAX_ODDS |
| `WINDOW_EXPIRED` | SKIP | Sudah T-42s tanpa valid entry |
| `ALL_GATES_FAIL` | SKIP | Tidak ada 7-gate PASS di golden window |
| `EOA_WALLET` | WARN | Auto claim tidak support |

> 📋 **Trigger baru v2.3:** `ODDS_OUT_OF_RANGE` — ketika ask di luar MIN_ODDS/MAX_ODDS. Dicatat di skip_log dengan alasan spesifik.

### LOCKDOWN Resume Protocol

```
LANGKAH 1 — Cooldown Minimum
  Circuit breaker    : cooldown LOCKDOWN_COOLDOWN_MIN menit (default: 15)
  Data stale / sync  : cooldown 5 menit setelah koneksi restore

LANGKAH 2 — Pre-Resume Checklist (manual)
  [ ] Hyperliquid WebSocket: terhubung dan menerima data
  [ ] Polymarket CLOB WebSocket: terhubung
  [ ] Chainlink feed: update dalam 15 detik terakhir
  [ ] Wallet balance: cukup untuk minimum BASE_SHARES × MIN_TRADE_RESERVE
  [ ] UNCLAIMED_BALANCE: tidak ada pending > 30 menit

LANGKAH 3 — State Reset
  circuit_breaker_count : 0
  order_sent            : False
  CVD accumulator       : 0 (fresh start)
  Session P&L           : TIDAK di-reset (append only)
  Trade log             : TIDAK di-reset (append only)

LANGKAH 4 — Soft Start
  Window pertama setelah resume : MONITOR only (tidak ARMED)
  Window kedua                  : operasi normal
```

---

## 07 · .ENV Master Control

> **Prinsip:** Tidak ada angka hardcoded di kode. Semua parameter yang bisa berubah — threshold, timing, sizing, keys, mode — dikontrol dari `.env`. Bot bisa dikalibrasi ulang tanpa menyentuh source code.

```dotenv
# ══════════════════════════════════════════════════════
# POLYMARKET BTC SNIPER v2.3 — MASTER CONFIGURATION
# ══════════════════════════════════════════════════════

# ── MODE ──────────────────────────────────────────────
BOT_MODE=paper                    # paper | live
BOT_VERSION=2.3
LOG_LEVEL=INFO                    # DEBUG | INFO | WARNING | ERROR

# ── WALLET & KEYS ─────────────────────────────────────
POLY_PRIVATE_KEY=0x...            # Private key Polymarket wallet
POLY_WALLET_ADDRESS=0x...         # Wallet address
POLY_WALLET_TYPE=proxy            # proxy | gnosis | eoa
HYPERLIQUID_API_KEY=              # Kosong jika public endpoint

# ── STRATEGY CORE ─────────────────────────────────────
GAP_THRESHOLD_NORMAL=45           # USD — Gap minimum kondisi normal
GAP_THRESHOLD_LOW_VOL=60          # USD — Gap minimum saat ATR < 50
GAP_THRESHOLD_HIGH_VOL=35         # USD — Gap minimum saat ATR > 150
ATR_LOW_VOL_THRESHOLD=50          # USD — Batas ATR low vol regime
ATR_HIGH_VOL_THRESHOLD=150        # USD — Batas ATR high vol regime
ATR_LOOKBACK_CANDLES=12           # Jumlah 5-menit candle untuk ATR (= 60 menit)

# ── CVD PARAMETERS ────────────────────────────────────
CVD_ROLLING_WINDOW_SEC=60         # Detik window rolling CVD
CVD_THRESHOLD_PCT=0.25            # % dari avg volume per menit
CVD_AVG_VOLUME_LOOKBACK_MIN=30    # Menit untuk hitung avg volume baseline

# ── ODDS CONTROL (MIN/MAX/SWEET SPOT) ─────────────────
MIN_ODDS=0.58                     # Batas bawah — di bawah ini suspicious
MAX_ODDS=0.82                     # Batas atas — di atas ini terlalu mahal
SWEET_SPOT_LOW=0.62               # Sweet spot bawah (untuk reporting)
SWEET_SPOT_HIGH=0.76              # Sweet spot atas (untuk reporting)

# ── EXECUTION TIMING ──────────────────────────────────
GOLDEN_WINDOW_START_SEC=60        # Detik sebelum tutup: mulai ARMED
GOLDEN_WINDOW_END_SEC=42          # Detik sebelum tutup: batas akhir entry
VELOCITY_MIN=15                   # USD — minimum delta dalam 1.5 detik
VELOCITY_WINDOW_SEC=1.5           # Detik window velocity check

# ── SLIPPAGE CONTROL ──────────────────────────────────
SLIPPAGE_THRESHOLD_NORMAL=0.01    # 1.0% — ATR normal
SLIPPAGE_THRESHOLD_ELEVATED=0.015 # 1.5% — ATR elevated
SLIPPAGE_THRESHOLD_HIGH_VOL=0.02  # 2.0% — ATR high vol

# ── LIQUIDITY FILTERS ─────────────────────────────────
SPREAD_MAX_PCT=0.03               # 3% — spread maksimal sisi target
MISPRICING_MULTIPLIER=0.15        # Koefisien formula expected odds
MISPRICING_MIN_EDGE=0.02          # Margin minimum mispricing

# ── POSITION SIZING ───────────────────────────────────
BASE_SHARES=1.0                   # Unit shares per trade (flat sizing)
MIN_TRADE_RESERVE=5               # Minimum trade reserve untuk resume check

# ── SAFETY GATES ──────────────────────────────────────
DATA_STALE_SEC=5                  # Detik tanpa update → DATA_STALE
SYNC_LATENCY_MAX_SEC=10           # Detik delta HL vs Poly → SYNC_LATENCY
CHAINLINK_UNSTABLE_THRESHOLD=35   # USD — volatilitas 3 tick Chainlink
STRIKE_PRICE_MAX_AGE_SEC=10       # Detik maks umur Chainlink saat INIT
CHAINLINK_MAX_AGE_ENTRY_SEC=25    # Detik maks umur Chainlink saat entry

# ── CIRCUIT BREAKER ───────────────────────────────────
CIRCUIT_BREAKER_LIMIT=3           # Jumlah loss berturut → LOCKDOWN
LOCKDOWN_COOLDOWN_MIN=15          # Menit cooldown setelah LOCKDOWN

# ── AUTO CLAIM ────────────────────────────────────────
AUTO_CLAIM_ENABLED=true           # true | false
CLAIM_TIMEOUT_SEC=30              # Detik timeout gasless relayer
CLAIM_MAX_RETRY=3                 # Jumlah maksimal retry claim
CLAIM_RETRY_INTERVAL_SEC=60       # Detik antara retry

# ── OUTPUT FILES ──────────────────────────────────────
OUTPUT_DIR=./output               # Direktori output semua file
TRADE_LOG_FILE=trade_log.csv
SKIP_LOG_FILE=skip_log.csv
MARKET_SNAPSHOT_FILE=market_snapshot.csv
SESSION_SUMMARY_FILE=session_summary.csv
ENGINE_STATE_FILE=engine_state.json
SNAPSHOT_INTERVAL_SEC=5           # Interval tulis market snapshot

# ── CLI DISPLAY ───────────────────────────────────────
CLI_REFRESH_PER_SEC=4             # Rich Live refresh rate
CLI_PRICE_UPDATE_SEC=1            # Panel harga update interval
CLI_ORDERBOOK_UPDATE_SEC=2        # Panel order book update interval
CLI_TRADE_LOG_ROWS=10             # Jumlah baris trade history di CLI

# ── WEBSOCKET ─────────────────────────────────────────
HL_WS_URL=wss://api.hyperliquid.xyz/ws
POLY_WS_URL=wss://clob.polymarket.com
WS_HEARTBEAT_INTERVAL_SEC=3       # Interval heartbeat check
WS_RECONNECT_MAX_RETRY=5          # Max reconnect attempt sebelum LOCKDOWN
WS_RECONNECT_DELAY_SEC=2          # Delay antara reconnect attempt

# ── ASYNC QUEUE ───────────────────────────────────────
ASYNC_QUEUE_MAXSIZE=100           # Max items di asyncio.Queue
ASYNC_QUEUE_WARN_THRESHOLD=80     # Items di queue → log WARNING (backpressure)
```

> ✅ **Semua angka threshold, timing, dan sizing di PRD ini mengacu ke variable .env di atas.**
> Tidak ada angka yang hardcoded di source code.

---

## 08 · CSV Output Specification

> **4 file CSV dengan tujuan berbeda.** Semua append-only kecuali session_summary yang di-overwrite setiap run.

---

### 08.1 · trade_log.csv — Full Audit Per Trade

**Tujuan:** Audit trail lengkap setiap trade yang di-execute. Dataset utama untuk kalibrasi parameter.

**Trigger tulis:** Setiap kali Step 10 selesai (trade WIN/LOSS/CANCEL).

| # | Field | Tipe | Contoh | Keterangan |
|---|---|---|---|---|
| 1 | `session_id` | string | `2026-04-19-143000` | ID session: tanggal + waktu mulai |
| 2 | `window_id` | string | `btc-updown-5m-1776444000` | Slug Polymarket window |
| 3 | `timestamp_trigger` | datetime | `2026-04-19 14:35:08.412` | Detik tepat semua 7 gate PASS |
| 4 | `timestamp_order_sent` | datetime | `2026-04-19 14:35:08.891` | Detik order dikirim ke CLOB |
| 5 | `timestamp_confirmed` | datetime | `2026-04-19 14:35:11.203` | Detik konfirmasi on-chain |
| 6 | `side` | UP/DOWN | `UP` | Sisi yang dibeli |
| 7 | `strike_price` | float | `84000.00` | Harga opening window (Chainlink) |
| 8 | `hl_price_at_trigger` | float | `84215.50` | Harga Hyperliquid saat trigger |
| 9 | `gap_value` | float | `215.50` | Gap = HL − Strike saat trigger |
| 10 | `gap_threshold_used` | float | `45.00` | Threshold Gap yang aktif (dynamic) |
| 11 | `atr_regime` | string | `NORMAL` | LOW_VOL / NORMAL / HIGH_VOL |
| 12 | `cvd_60s` | float | `620000.00` | Net CVD rolling 60s saat trigger |
| 13 | `cvd_threshold_used` | float | `1050000.00` | Threshold CVD yang aktif |
| 14 | `cvd_threshold_pct` | float | `0.25` | % avg volume yang digunakan |
| 15 | `velocity` | float | `18.50` | Delta harga HL dalam 1.5 detik |
| 16 | `entry_odds` | float | `0.710` | Harga ask shares yang dibeli |
| 17 | `odds_in_sweet_spot` | bool | `True` | Apakah dalam SWEET_SPOT range |
| 18 | `spread_pct` | float | `0.012` | Spread bid-ask sisi target |
| 19 | `expected_odds` | float | `0.691` | Expected odds dari formula mispricing |
| 20 | `mispricing_delta` | float | `0.019` | expected_odds − entry_odds |
| 21 | `slippage_delta` | float | `0.003` | Perubahan odds T_signal ke T_order |
| 22 | `slippage_threshold_used` | float | `0.015` | Threshold slippage yang aktif |
| 23 | `blockchain_latency_ms` | int | `2791` | Ms dari send ke confirmed |
| 24 | `shares_bought` | float | `1.0` | Jumlah shares dieksekusi |
| 25 | `cost_usdc` | float | `0.710` | USDC dikeluarkan |
| 26 | `result` | string | `WIN` | WIN / LOSS / CANCEL |
| 27 | `resolution_price` | float | `84310.25` | Harga Chainlink saat resolusi |
| 28 | `payout_usdc` | float | `1.000` | USDC diterima (0 jika LOSS) |
| 29 | `pnl_usdc` | float | `0.290` | payout − cost |
| 30 | `claim_method` | string | `AUTO` | AUTO / MANUAL / PENDING / N-A |
| 31 | `claim_timestamp` | datetime | `2026-04-19 14:36:02.100` | Waktu claim berhasil |
| 32 | `bot_version` | string | `2.3` | Versi bot saat trade |

---

### 08.2 · skip_log.csv — Log Setiap Window yang Di-SKIP

**Tujuan:** Analisis efisiensi gate — gate mana yang paling sering memblok trade, apakah SKIP opportunity yang bagus atau buruk.

**Trigger tulis:** Setiap kali window di-SKIP (semua alasan).

| # | Field | Tipe | Contoh | Keterangan |
|---|---|---|---|---|
| 1 | `session_id` | string | `2026-04-19-143000` | ID session |
| 2 | `window_id` | string | `btc-updown-5m-1776444000` | Slug window |
| 3 | `timestamp` | datetime | `2026-04-19 14:35:52.100` | Waktu skip dicatat |
| 4 | `skip_reason` | string | `ODDS_OUT_OF_RANGE` | Kode trigger (lihat Section 06) |
| 5 | `skip_stage` | string | `EVALUATE` | Stage bot saat skip: INIT/MONITOR/ARMED/EVALUATE/PRE_ORDER |
| 6 | `gap_value` | float | `215.50` | Gap saat skip (null jika belum dihitung) |
| 7 | `gap_threshold` | float | `45.00` | Threshold yang berlaku |
| 8 | `gap_gate_pass` | bool | `True` | Apakah Gate 1 PASS |
| 9 | `cvd_value` | float | `620000.00` | CVD saat skip |
| 10 | `cvd_gate_pass` | bool | `True` | Apakah Gate 2 PASS |
| 11 | `liquidity_gate_pass` | bool | `True` | Apakah Gate 3 PASS |
| 12 | `current_ask` | float | `0.855` | Harga ask saat skip |
| 13 | `min_odds` | float | `0.58` | MIN_ODDS yang berlaku |
| 14 | `max_odds` | float | `0.82` | MAX_ODDS yang berlaku |
| 15 | `odds_gate_pass` | bool | `False` | Apakah Gate 4 PASS |
| 16 | `golden_window_gate_pass` | bool | `True` | Apakah Gate 5 PASS |
| 17 | `velocity_gate_pass` | bool | `True` | Apakah Gate 6 PASS |
| 18 | `slippage_gate_pass` | bool | `True` | Apakah Gate 7 PASS (null jika belum sampai PRE_ORDER) |
| 19 | `t_remaining_sec` | int | `48` | Detik tersisa di window saat skip |
| 20 | `would_have_won` | bool | `True` | *Post-hoc*: apakah arah Gap akhirnya benar? |
| 21 | `chainlink_age_sec` | int | `8` | Umur data Chainlink saat skip |

> 📋 **Field `would_have_won`** adalah field post-hoc — diisi setelah window resolve. Ini yang memungkinkan analisis: "seberapa banyak trade bagus yang di-skip karena odds terlalu tinggi (MAX_ODDS)?"

---

### 08.3 · market_snapshot.csv — Kondisi Market Setiap 5 Detik

**Tujuan:** Dataset untuk backtest dan kalibrasi. Rekam kondisi lengkap sepanjang window — bukan hanya saat trigger.

**Trigger tulis:** Setiap `SNAPSHOT_INTERVAL_SEC` (default: 5 detik) per window aktif.

| # | Field | Tipe | Contoh | Keterangan |
|---|---|---|---|---|
| 1 | `session_id` | string | `2026-04-19-143000` | ID session |
| 2 | `window_id` | string | `btc-updown-5m-1776444000` | Slug window |
| 3 | `timestamp` | datetime | `2026-04-19 14:30:05.000` | Waktu snapshot |
| 4 | `t_remaining_sec` | int | `295` | Detik tersisa di window |
| 5 | `strike_price` | float | `84000.00` | Strike price window |
| 6 | `hl_price` | float | `84055.25` | Harga Hyperliquid saat snapshot |
| 7 | `gap` | float | `55.25` | Gap = HL − Strike |
| 8 | `gap_direction` | string | `UP` | UP / DOWN / NEUTRAL |
| 9 | `atr_60m` | float | `92.50` | ATR 60 menit |
| 10 | `atr_regime` | string | `NORMAL` | LOW_VOL / NORMAL / HIGH_VOL |
| 11 | `cvd_60s` | float | `180000.00` | CVD rolling 60s |
| 12 | `cvd_aligned` | bool | `True` | Apakah CVD aligned dengan Gap |
| 13 | `avg_volume_per_min` | float | `4200000.00` | Avg volume baseline |
| 14 | `poly_up_odds` | float | `0.565` | Odds UP saat snapshot |
| 15 | `poly_down_odds` | float | `0.435` | Odds DOWN saat snapshot |
| 16 | `poly_up_ask_depth` | float | `850.00` | USDC depth ask sisi UP |
| 17 | `poly_down_bid_depth` | float | `620.00` | USDC depth bid sisi DOWN |
| 18 | `spread_pct` | float | `0.018` | Spread sisi target |
| 19 | `dual_side_ok` | bool | `True` | Apakah dual side liquidity OK |
| 20 | `chainlink_age_sec` | int | `6` | Umur data Chainlink |
| 21 | `bot_mode` | string | `MONITORING` | MONITORING / ARMED / ORDER_SENT |
| 22 | `all_gates_pass` | bool | `False` | Apakah semua 7 gate PASS saat snapshot ini |
| 23 | `window_result` | string | `UP` | *Post-hoc*: hasil resolusi window (UP/DOWN) |

> 📋 **Field `window_result`** diisi setelah window resolve. Kombinasi dengan `gap`, `cvd_60s`, `poly_up_odds` di berbagai `t_remaining_sec` adalah dataset backtest yang berharga.

---

### 08.4 · session_summary.csv — Ringkasan Per Session Run

**Tujuan:** Overview cepat performa setiap session. Satu baris per session. Di-append setiap kali bot berhenti (graceful quit atau LOCKDOWN).

**Trigger tulis:** Saat bot shutdown (Step 10 terakhir atau LOCKDOWN).

| # | Field | Tipe | Contoh | Keterangan |
|---|---|---|---|---|
| 1 | `session_id` | string | `2026-04-19-143000` | ID session |
| 2 | `start_time` | datetime | `2026-04-19 14:30:00` | Waktu mulai session |
| 3 | `end_time` | datetime | `2026-04-19 17:15:00` | Waktu selesai session |
| 4 | `duration_min` | int | `165` | Durasi session dalam menit |
| 5 | `bot_version` | string | `2.3` | Versi bot |
| 6 | `bot_mode` | string | `live` | paper / live |
| 7 | `total_windows` | int | `33` | Jumlah window yang terjadi |
| 8 | `windows_traded` | int | `8` | Jumlah window dengan trade |
| 9 | `windows_skipped` | int | `22` | Jumlah window di-SKIP |
| 10 | `windows_locked` | int | `3` | Jumlah window karena LOCKDOWN |
| 11 | `wins` | int | `6` | Jumlah trade WIN |
| 12 | `losses` | int | `2` | Jumlah trade LOSS |
| 13 | `win_rate` | float | `0.750` | wins / (wins + losses) |
| 14 | `total_cost_usdc` | float | `5.680` | Total USDC dikeluarkan |
| 15 | `total_payout_usdc` | float | `7.420` | Total USDC diterima |
| 16 | `net_pnl_usdc` | float | `1.740` | total_payout − total_cost |
| 17 | `avg_entry_odds` | float | `0.710` | Rata-rata entry odds |
| 18 | `avg_gap_at_entry` | float | `198.30` | Rata-rata Gap saat entry |
| 19 | `avg_blockchain_latency_ms` | int | `2840` | Rata-rata latency konfirmasi |
| 20 | `skip_gap_insufficient` | int | `8` | Skip karena Gap kurang |
| 21 | `skip_cvd_not_aligned` | int | `4` | Skip karena CVD tidak aligned |
| 22 | `skip_odds_too_low` | int | `1` | Skip karena ask < MIN_ODDS |
| 23 | `skip_odds_too_high` | int | `5` | Skip karena ask > MAX_ODDS |
| 24 | `skip_no_liquidity` | int | `2` | Skip karena dual side fail |
| 25 | `skip_slippage` | int | `1` | Skip karena slippage exceeded |
| 26 | `skip_other` | int | `1` | Skip alasan lain |
| 27 | `lockdown_triggers` | string | `CIRCUIT_BREAKER` | Kode trigger LOCKDOWN (comma-separated) |
| 28 | `unclaimed_balance_usdc` | float | `0.00` | USDC pending claim saat session end |
| 29 | `auto_claimed_usdc` | float | `7.420` | Total USDC berhasil auto-claim |
| 30 | `manual_claim_required` | float | `0.00` | USDC perlu manual claim |

---

## 09 · Validasi Pra-Build

> **3 validasi ini HARUS selesai sebelum menulis kode trading.** Estimasi waktu: 3–5 hari.

### Validasi 1 — Win Rate di Gap > $45

**Target:** Win rate ≥ 72% untuk break even di entry odds $0.72 rata-rata.

```
CARA EKSEKUSI:
1. Download historical Hyperliquid BTC price data (30 hari terakhir)
2. Download historical Polymarket BTC 5-min resolution data
3. Simulasikan: untuk setiap window, apakah Gap > $45 di T-60s?
4. Hitung win rate per Gap bucket: $45–60, $60–90, $90–120, $120+
5. Output: tabel win rate vs Gap threshold yang empiris

HASIL MINIMUM:
  Gap $45–60  : win rate ≥ 68%
  Gap $60–90  : win rate ≥ 74%
  Gap $90+    : win rate ≥ 80%

KEPUTUSAN:
  Semua bucket lolos → lanjut build
  Bucket $45–60 gagal → naikkan GAP_THRESHOLD_NORMAL ke 60
  Semua bucket di bawah minimum → edge tidak ada, jangan build
```

### Validasi 2 — Lag Repricing Polymarket

**Target:** Median lag ≥ 20 detik setelah price movement > $45.

```
CARA EKSEKUSI:
1. Monitor live: setiap kali Gap > $45 terbentuk, catat timestamp
2. Monitor Polymarket CLOB setiap 3 detik: kapan odds UP melebihi 0.80?
3. Selisih waktu = lag repricing. Lakukan 50+ observasi
4. Hitung: median, p25, p75 lag

HASIL MINIMUM:
  Median lag ≥ 20 detik
  p25 lag ≥ 8 detik (25% kasus tercepat masih ada 8 detik window)

KEPUTUSAN:
  Lolos → lanjut, golden window T-60s cukup
  Median 10–20 detik → pertimbangkan perlebar ke T-70s
  Median < 10 detik → edge hampir tidak ada, evaluasi ulang strategi
```

### Validasi 3 — Blockchain Latency Polygon

**Target:** Median latency ≤ 4 detik.

```
CARA EKSEKUSI:
1. Kirim 20 test transactions ke Polygon (dummy contract)
2. Variasikan: normal hours, peak hours, weekend
3. Ukur: median, p50, p75, p95 latency
4. Ulangi dengan gas price normal vs +20% tip

HASIL MINIMUM:
  Median ≤ 4 detik
  p95 ≤ 8 detik

KEPUTUSAN:
  Lolos → T-60s golden window cukup
  Median 4–6 detik → implementasi pre-sign strategy
  Median > 6 detik → perlebar golden window ke T-70s di .env
```

### Decision Gate

| Validasi | Minimum | Status |
|---|---|---|
| Win Rate (Gap > $45) | ≥ 72% | ☐ BELUM |
| Lag Repricing Polymarket | Median ≥ 20 detik | ☐ BELUM |
| Polygon Latency | Median ≤ 4 detik | ☐ BELUM |

---

## 10 · Confidence Tracker

| Dimensi | Sekarang | Target | Naik Setelah |
|---|---|---|---|
| Strategy Logic | 7.5 | 9.0 | Validasi 1 + MIN/MAX ODDS kalibrasi |
| Risk Management | 8.0 | 9.0 | Adaptive threshold diimplementasi |
| Technical Architecture | 7.0 | 8.5 | asyncio queue + resume protocol |
| Execution Realism | 6.5 | 8.0 | Validasi 3 (blockchain latency) |
| Edge Sustainability | 6.0 | 7.5 | Validasi 2 (lag repricing terukur) |
| Auto Claim | 8.5 | 9.0 | Wallet type divalidasi |
| CLI Observability | 8.0 | 9.0 | Refresh strategy diimplementasi |

**Overall: 68–72% → Target: 80–85%**

### Roadmap Confidence

| # | Langkah | Impact |
|---|---|---|
| 1 | Validasi Win Rate | +5–8% Strategy Logic |
| 2 | Ukur Lag Repricing | +5–7% Edge Sustainability |
| 3 | Test Polygon Latency | +5–8% Execution Realism |
| 4 | Implementasi asyncio Queue | +4–5% Architecture |
| 5 | Kalibrasi CVD + MIN/MAX ODDS dari data live | +3–5% Strategy Logic |
| 6 | Paper Trading 50 window | +3–5% semua dimensi |

---

## 11 · Technical Infrastructure

```
HYPERLIQUID WebSocket
     │
asyncio.Queue (maxsize=ASYNC_QUEUE_MAXSIZE)
     │
┌────┴────────────────────┐
│                         │
Price Processor      Trade Feed Processor
(Gap, Velocity, ATR) (CVD rolling 60s)
│                         │
└────────────┬────────────┘
             │
      Signal Evaluator
      (7-gate AND logic)
      Gate 4: MIN_ODDS ≤ ask ≤ MAX_ODDS  ← NEW
             │
    ┌────────┴────────┐
  SKIP/LOCK      Order Executor
  skip_log.csv   (Polymarket CLOB API)
                      │
               Auto Claim Retry Queue
                      │
         ┌────────────┼────────────┐
    trade_log    skip_log     market_snapshot
    .csv         .csv         .csv
                      │
               session_summary.csv
                      │
               engine_state.json (in-memory + flush 5s)
                      │
               CLI Terminal (rich.Live)
```

| Komponen | Source | Fungsi |
|---|---|---|
| Harga + CVD | Hyperliquid WebSocket | Gap + CVD accumulation |
| Odds + Order Book | Polymarket CLOB WebSocket | Mispricing + dual side |
| Order Execution | Polymarket CLOB API | Kirim order |
| Auto Claim | Polymarket Gasless Relayer | Redeem → USDC |
| Resolution | Chainlink BTC/USD | Otomatis oleh smart contract |
| CLI | Python rich | Dashboard 6-panel real-time |
| Async Buffer | asyncio.Queue | Decoupling I/O dari logic |
| Config | .env | Semua parameter vital |
| Audit | 4 × CSV | Trade, Skip, Snapshot, Summary |

---

## Version History

| Version | Perubahan Utama |
|---|---|
| v1.1 | Model prediktif, threshold 30 detik |
| v1.2 | Tambah CVD dan OBI |
| v1.3 | Reactionary Sniper: Velocity, $45 Buffer, T-48s, Conviction 2× |
| v2.0 | CVD + Dual Side Liquidity. Drop OI, flat sizing, T-60s |
| v2.1 | Auto Claim, SKIP vs LOCKDOWN, CLI Terminal 6-panel |
| v2.2 | Risk/Fix per section, asyncio Queue, Resume Protocol, 3 Validasi Pra-Build, Confidence Tracker |
| **v2.3** | **MIN/MAX ODDS + Sweet Spot di Strategy Core. 4-file CSV spec lengkap. .env Master Control 50+ variable. Gate 4 ODDS_OUT_OF_RANGE. would_have_won di skip_log. 32-field trade_log. session_summary.csv.** |

---

*Polymarket BTC Sniper PRD v2.3 · April 2026*
*Dokumen ini adalah referensi arsitektur utama. Setiap deviasi di kode harus direkonsiliasi terhadap spesifikasi ini.*
*Current Confidence: 68–72% · Target Pre-Live: 80–85% · Next Step: Selesaikan 3 Validasi Pra-Build*
