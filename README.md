# 📘 Polymarket BTC Sniper v2.3 — Panduan Lengkap

## Daftar Isi
1. [Persyaratan Sistem](#1--persyaratan-sistem)
2. [Instalasi](#2--instalasi)
3. [Konfigurasi .env (Detail)](#3--konfigurasi-env-detail)
4. [Menjalankan Bot](#4--menjalankan-bot)
5. [Memahami Output & Log](#5--memahami-output--log)
6. [Troubleshooting](#6--troubleshooting)

---

## 1 · Persyaratan Sistem

| Komponen | Minimum | Rekomendasi |
|---|---|---|
| **OS** | Windows 10+ / Ubuntu 20.04+ | Ubuntu 22.04 (VPS) |
| **Python** | 3.11+ | 3.12 |
| **RAM** | 512MB | 1GB+ |
| **Internet** | Stabil, latency rendah | VPS di US East (dekat server Polymarket) |
| **Terminal** | PowerShell / bash | tmux (untuk VPS) |

### Akun & Wallet yang Dibutuhkan

> [!IMPORTANT]
> Anda **WAJIB** memiliki semua item berikut sebelum melanjutkan:

| Item | Cara Mendapatkan | Catatan |
|---|---|---|
| **Polymarket Account** | Daftar di [polymarket.com](https://polymarket.com) | Harus verified |
| **Polymarket Proxy Wallet** | Otomatis dibuat saat deposit pertama | Ini BUKAN wallet MetaMask Anda |
| **Polymarket API Key** | Settings → API → Generate Key | Simpan baik-baik, hanya muncul sekali |
| **Private Key** | Export dari wallet yang terhubung ke Polymarket | ⚠️ JANGAN share ke siapapun |
| **Polygon RPC URL** | Daftar di [Alchemy](https://alchemy.com) atau [Infura](https://infura.io) | Pilih network: **Polygon Mainnet** |
| **USDC di Polygon** | Bridge dari Ethereum atau beli langsung | Minimum $10 untuk testing |

---

## 2 · Instalasi

### Step 1 — Clone / Masuk ke Direktori Project

```powershell
# Windows (PowerShell)
cd "C:\Users\Razer\OneDrive\Desktop\BERKAH JAYA\btc_sniper"

# Linux/Mac
cd /path/to/btc_sniper
```

### Step 2 — Buat Virtual Environment

```powershell
# Buat virtual environment
python -m venv venv

# Aktifkan (Windows PowerShell)
.\venv\Scripts\Activate.ps1

# Aktifkan (Linux/Mac)
source venv/bin/activate
```

> [!TIP]
> Jika di Windows muncul error "execution policy", jalankan:
> ```powershell
> Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
> ```

### Step 3 — Install Dependencies

```powershell
pip install -r requirements.txt
```

Verifikasi instalasi:
```powershell
python -c "import websockets, aiohttp, rich, web3; print('✅ Semua dependency terinstall')"
```

### Step 4 — Buat File .env

```powershell
# Windows
copy .env.example .env

# Linux/Mac
cp .env.example .env
```

> [!CAUTION]
> File `.env` berisi **private key** Anda. JANGAN pernah:
> - Upload ke GitHub / repository publik
> - Share ke siapapun
> - Screenshot dan kirim via chat
>
> Tambahkan `.env` ke `.gitignore` jika menggunakan Git.

---

## 3 · Konfigurasi .env (Detail)

Buka file `.env` dengan text editor favorit Anda. Berikut penjelasan **setiap parameter** yang perlu diisi:

---

### 🔐 WALLET & AUTH — WAJIB DIISI

```dotenv
POLYMARKET_PRIVATE_KEY=0xabc123...your_private_key_here
```
**Apa ini:** Private key dari wallet Ethereum yang terhubung ke akun Polymarket Anda.
**Cara dapat:**
1. Jika menggunakan MetaMask → Settings → Security → Export Private Key
2. Jika menggunakan wallet lain → cari opsi "Export Private Key"

**Format:** Harus diawali `0x` diikuti 64 karakter hex.
**Contoh:** `0x4c0883a69102937d6231471b5dbb6204fe512961708279f9d34f28a1e24c7391`

> [!CAUTION]
> Ini adalah kunci akses PENUH ke wallet Anda. Siapapun yang memiliki key ini bisa menguras seluruh isi wallet.

---

```dotenv
POLYMARKET_PROXY_WALLET=0xdef456...your_proxy_wallet_here
```
**Apa ini:** Alamat proxy wallet yang dibuat Polymarket untuk Anda.
**Cara dapat:**
1. Login ke [polymarket.com](https://polymarket.com)
2. Klik profile icon → Settings → Wallet
3. Salin alamat "Proxy Wallet" atau "Trading Wallet"

**Kenapa bukan wallet biasa?** Polymarket menggunakan proxy wallet untuk gasless trading di Polygon. Bot harus tahu alamat ini untuk mengirim order.

**Format:** `0x` + 40 karakter hex
**Contoh:** `0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18`

---

```dotenv
POLYMARKET_API_KEY=your-api-key-here
```
**Apa ini:** API key untuk mengakses Polymarket CLOB (Central Limit Order Book).
**Cara dapat:**
1. Login ke [polymarket.com](https://polymarket.com)
2. Settings → API Keys → Create New Key
3. Salin key yang muncul (hanya ditampilkan SEKALI)

**Format:** String alfanumerik, biasanya UUID format
**Contoh:** `a1b2c3d4-e5f6-7890-abcd-ef1234567890`

---

```dotenv
POLYGON_RPC_URL=https://polygon-mainnet.g.alchemy.com/v2/YOUR_API_KEY
```
**Apa ini:** URL endpoint untuk membaca data blockchain Polygon (termasuk harga Chainlink).
**Cara dapat (Alchemy — gratis):**
1. Daftar di [alchemy.com](https://www.alchemy.com/)
2. Create App → Network: **Polygon Mainnet**
3. Klik "View Key" → salin HTTPS URL

**Cara dapat (Infura — alternatif):**
1. Daftar di [infura.io](https://infura.io)
2. Create Project → Network: Polygon
3. Salin endpoint URL

**Contoh Alchemy:** `https://polygon-mainnet.g.alchemy.com/v2/abc123xyz789`
**Contoh Infura:** `https://polygon-mainnet.infura.io/v3/abc123xyz789`

> [!TIP]
> Alchemy free tier memberikan 300M compute units/bulan — lebih dari cukup untuk bot ini.

---

```dotenv
HYPERLIQUID_WS_URL=wss://api.hyperliquid.xyz/ws
```
**Apa ini:** WebSocket endpoint Hyperliquid untuk streaming harga BTC real-time.
**Perlu diubah?** **TIDAK** — gunakan default. Ini adalah public endpoint, tidak perlu API key.

---

### ⚙️ STRATEGY CORE — Bisa Pakai Default

```dotenv
BASE_SHARES=1.0
```
**Apa ini:** Jumlah shares yang dibeli per trade (flat sizing).
**Default:** `1.0` (= beli 1 share per window)
**Berapa biayanya?** Tergantung odds. Jika odds = $0.70, maka 1 share = $0.70
**Kapan ubah?** Setelah validasi dan paper trading berhasil, bisa naikkan ke 2.0, 5.0, dst.

> [!WARNING]
> **JANGAN** set ke angka besar (100+) saat pertama kali. Mulai dengan 1.0.

---

```dotenv
MAX_POSITION_USD=10.0
```
**Apa ini:** Hard cap biaya maksimal per trade dalam USD.
**Default:** `$10.0`
**Fungsi:** Safety net — jika `BASE_SHARES × odds > MAX_POSITION_USD`, order dibatalkan.
**Contoh:** Jika BASE_SHARES=5 dan odds=$0.80, cost=$4.00 → PASS (< $10)

---

```dotenv
GAP_THRESHOLD_DEFAULT=45.0
GAP_THRESHOLD_LOW_VOL=60.0
GAP_THRESHOLD_HIGH_VOL=35.0
```
**Apa ini:** Minimum gap (selisih harga Hyperliquid vs Strike Price) untuk trigger entry.
**Default:** `$45` (kondisi normal), `$60` (volatilitas rendah), `$35` (volatilitas tinggi)
**Analogi:** Seperti filter sensitivitas. Semakin tinggi = semakin selektif = lebih sedikit trade tapi lebih akurat.

| Kondisi | Threshold | Artinya |
|---|---|---|
| Low Vol (ATR < $50) | $60 | Banyak false signal, perlu gap lebih besar |
| Normal (ATR $50-150) | $45 | Kondisi optimal |
| High Vol (ATR > $150) | $35 | Gap besar lebih sering, threshold diturunkan |

---

```dotenv
ATR_LOW_THRESHOLD=50.0
ATR_HIGH_THRESHOLD=150.0
ATR_LOOKBACK_CANDLES=12
```
**Apa ini:** Batas ATR (Average True Range) untuk menentukan regime volatilitas.
**Default:** Low < $50, High > $150, dihitung dari 12 candle 5-menit (= 60 menit)
**Perlu diubah?** Tidak untuk awal. Kalibrasi setelah mengumpulkan data.

---

### 🎯 ODDS BOUNDARY (Gate 4)

```dotenv
ODDS_MIN=0.58
ODDS_MAX=0.82
ODDS_SWEET_SPOT_LOW=0.62
ODDS_SWEET_SPOT_HIGH=0.76
```

| Parameter | Nilai | Artinya |
|---|---|---|
| `ODDS_MIN` | 0.58 | Di bawah $0.58 = **suspicious** → SKIP. Harga terlalu murah saat gap besar = kemungkinan data error |
| `ODDS_MAX` | 0.82 | Di atas $0.82 = **terlalu mahal** → SKIP. Profit hanya $0.18/share, R/R sangat buruk |
| `SWEET_SPOT_LOW` | 0.62 | Batas bawah zona optimal |
| `SWEET_SPOT_HIGH` | 0.76 | Batas atas zona optimal |

**Visual risk/reward:**
```
$0.52 ──── SKIP (suspicious)
$0.58 ──── MIN boundary ⚠️
$0.62 ──── Sweet spot start ✅
$0.70 ──── Sweet spot core ✅✅
$0.76 ──── Sweet spot end ✅
$0.82 ──── MAX boundary ⚠️
$0.90 ──── SKIP (terlalu mahal)
```

---

### 📊 CVD PARAMETERS

```dotenv
CVD_VOLUME_WINDOW_MINUTES=30
CVD_THRESHOLD_PCT=25.0
```
**CVD_VOLUME_WINDOW_MINUTES:** Window waktu untuk menghitung average volume (30 menit terakhir).
**CVD_THRESHOLD_PCT:** CVD harus ≥ 25% dari average volume per menit agar dianggap "aligned".

**Contoh:** Jika avg volume = $4.2M/menit, maka CVD threshold = $4.2M × 25% = **$1.05M net delta**.

---

### ⏱️ TIMING & VELOCITY

```dotenv
GOLDEN_WINDOW_START=60
GOLDEN_WINDOW_END=42
VELOCITY_ENABLED=True
VELOCITY_MIN_DELTA=15.0
VELOCITY_WINDOW_SECONDS=1.5
```

**Golden Window:** Bot hanya memasukkan order antara **T-60 detik** sampai **T-42 detik** sebelum window tutup.
- Sebelum T-60s = terlalu dini, harga masih bergerak
- Setelah T-42s = terlalu mepet, risiko blockchain latency

**Velocity:** Harga Hyperliquid harus bergerak minimal **$15 dalam 1.5 detik** terakhir.
- Ini filter untuk memastikan ada momentum nyata, bukan noise.
- Set `VELOCITY_ENABLED=False` untuk menonaktifkan filter ini.

---

### 🛡️ SLIPPAGE & LIQUIDITY

```dotenv
SLIPPAGE_THRESHOLD_NORMAL=1.0
SLIPPAGE_THRESHOLD_ELEVATED=1.5
SLIPPAGE_THRESHOLD_HIGH=2.0
SPREAD_MAX_PCT=3.0
MISPRICING_MULTIPLIER=0.15
MISPRICING_MIN_EDGE=0.02
```

**Slippage:** Jika harga berubah lebih dari threshold antara saat evaluasi dan saat kirim order → CANCEL.
**Spread:** Jika bid-ask spread > 3% → SKIP (market tidak likuid).
**Mispricing:** Formula internal untuk mendeteksi apakah shares masih underpriced.

---

### 🚨 RISK & CIRCUIT BREAKER

```dotenv
CIRCUIT_BREAKER_MAX_LOSS=3
COOLDOWN_CIRCUIT_BREAKER_SEC=900
COOLDOWN_DATA_STALE_SEC=300
MAX_DAILY_LOSS_USD=0.0
MIN_TRADE_RESERVE=5
```

| Parameter | Default | Penjelasan |
|---|---|---|
| `CIRCUIT_BREAKER_MAX_LOSS` | 3 | Setelah 3 loss berturut-turut → **LOCKDOWN** (bot berhenti) |
| `COOLDOWN_CIRCUIT_BREAKER_SEC` | 900 | Cooldown 15 menit setelah LOCKDOWN |
| `COOLDOWN_DATA_STALE_SEC` | 300 | Cooldown 5 menit setelah data stale |
| `MAX_DAILY_LOSS_USD` | 0.0 | Daily loss limit. **0 = disabled**. Set ke misal `5.0` untuk cap daily loss $5 |
| `MIN_TRADE_RESERVE` | 5 | Wallet harus punya saldo untuk minimal 5 trade untuk bisa resume |

---

### 🔗 DATA FRESHNESS & WEBSOCKET

```dotenv
CHAINLINK_MAX_AGE_SEC=10
CHAINLINK_MAX_AGE_ENTRY_SEC=25
CHAINLINK_VOLATILITY_SKIP_USD=35.0
WS_HEARTBEAT_INTERVAL_SEC=3
WS_STALE_THRESHOLD_SEC=5
WS_RECONNECT_MAX_RETRY=5
SYNC_LATENCY_MAX_SEC=10
```

**Pakai default** untuk semua parameter ini. Hanya ubah jika Anda memahami implikasinya.

---

### ⛓️ BLOCKCHAIN

```dotenv
POLYGON_GAS_TIP_MULTIPLIER=1.0
CLAIM_RETRY_MAX=3
CLAIM_RETRY_TIMEOUT_SEC=30
CLAIM_RETRY_INTERVAL_SEC=60
```

**POLYGON_GAS_TIP_MULTIPLIER:** `1.0` = gas normal. Set `1.2` untuk 20% tip lebih (konfirmasi lebih cepat tapi lebih mahal).
**Claim:** Setelah menang, bot auto-claim winnings. Retry 3x jika gagal, interval 60 detik.

---

### 📁 OUTPUT & LOGGING

```dotenv
OUTPUT_DIR=./output
TRADE_LOG_FILE=trade_log.csv
SKIP_LOG_FILE=skip_log.csv
MARKET_SNAPSHOT_FILE=market_snapshot.csv
SESSION_SUMMARY_FILE=session_summary.csv
EVENT_LOG_FILE=event_log.csv
STATE_FILE=engine_state.json
LOG_FLUSH_INTERVAL_SEC=5
LOG_ROTATION_DAYS=30
SNAPSHOT_INTERVAL_SEC=5
```

**Pakai default.** Semua log disimpan di folder `./output/`. File CSV di-rotate per hari.

---

### 🖥️ CLI & MODE

```dotenv
PAPER_TRADING_MODE=True
BOT_VERSION=2.3
CLI_REFRESH_RATE=4
CLI_ORDERBOOK_UPDATE_SEC=2
CLI_TRADE_LOG_ROWS=10
```

> [!IMPORTANT]
> **`PAPER_TRADING_MODE=True` — WAJIB True saat pertama kali!**
>
> Paper mode = bot berjalan normal tapi TIDAK mengirim order nyata. Semua trade disimulasikan.
> Gunakan ini untuk validasi bahwa bot bekerja dengan benar sebelum trading dengan uang sungguhan.
>
> Setelah yakin bot stabil → ubah ke `PAPER_TRADING_MODE=False` untuk live trading.

---

### 📋 Contoh .env Minimal (Siap Pakai)

```dotenv
# === WAJIB DIISI ===
POLYMARKET_PRIVATE_KEY=0x_GANTI_DENGAN_PRIVATE_KEY_ANDA
POLYMARKET_PROXY_WALLET=0x_GANTI_DENGAN_PROXY_WALLET_ANDA
POLYMARKET_API_KEY=GANTI_DENGAN_API_KEY_ANDA
POLYGON_RPC_URL=https://polygon-mainnet.g.alchemy.com/v2/GANTI_DENGAN_KEY_ANDA

# === PAKAI DEFAULT UNTUK SISANYA ===
PAPER_TRADING_MODE=True
BASE_SHARES=1.0
MAX_POSITION_USD=10.0
BOT_VERSION=2.3
```

Semua parameter lain akan menggunakan nilai default yang sudah optimal.

---

## 4 · Menjalankan Bot

### Paper Trading (Pertama Kali — WAJIB)

```powershell
# Pastikan virtual environment aktif
.\venv\Scripts\Activate.ps1    # Windows
source venv/bin/activate        # Linux

# Jalankan dengan --paper flag (override .env)
python main.py --paper
```

Anda akan melihat:
1. **Warning box kuning** — "PAPER TRADING MODE ACTIVE"
2. **Tabel konfigurasi** — semua parameter yang aktif
3. **Dashboard 6-panel** — live market data

### Live Trading (Setelah Validasi)

```powershell
# Ubah di .env:
# PAPER_TRADING_MODE=False

# Jalankan tanpa --paper flag
python main.py
```

### Menjalankan di VPS (Rekomendasi)

```bash
# Install tmux
sudo apt install tmux

# Buat session baru
tmux new -s sniper

# Jalankan bot
cd /path/to/btc_sniper
source venv/bin/activate
python main.py --paper

# Detach dari tmux (bot tetap jalan)
# Tekan: Ctrl+B, lalu D

# Re-attach untuk monitor
tmux attach -t sniper
```

### Keyboard Controls (Saat Bot Berjalan)

| Tombol | Fungsi |
|---|---|
| **Q** | Quit — shutdown graceful (simpan semua log) |
| **P** | Pause — bot tetap monitor tapi tidak kirim order |
| **R** | Resume — lanjutkan dari pause |
| **L** | Locks — tampilkan status circuit breaker |

### Custom .env Path

```powershell
# Jika .env ada di lokasi berbeda
python main.py --env "C:\path\to\my\.env"
```

---

## 5 · Memahami Output & Log

Setelah bot berjalan, folder `./output/` akan berisi:

| File | Isi | Kapan Ditulis |
|---|---|---|
| `trade_log_2026-04-19.csv` | Semua trade (32 kolom) | Setiap trade dieksekusi |
| `skip_log_2026-04-19.csv` | Semua window yang di-skip (21 kolom) | Setiap window dilewati |
| `market_snapshot_2026-04-19.csv` | Kondisi market tiap 5 detik (23 kolom) | Kontinu selama bot jalan |
| `session_summary_2026-04-19.csv` | Ringkasan per sesi (30 kolom) | Saat bot shutdown |
| `event_log_2026-04-19.csv` | Event sistem (reconnect, lockdown, dll) | Setiap event terjadi |
| `engine_state.json` | State real-time (in-memory snapshot) | Setiap 5 detik |

### Cara Baca trade_log.csv

Buka di Excel / Google Sheets. Kolom penting:
- `result`: WIN / LOSS / PENDING
- `entry_odds`: Harga beli shares
- `pnl_usdc`: Profit/loss per trade
- `gap_value`: Gap saat entry
- `claim_method`: AUTO / MANUAL / PENDING

---

## 6 · Troubleshooting

### ❌ "ConfigurationError: POLYMARKET_PRIVATE_KEY is required"
→ File `.env` belum diisi atau tidak ditemukan. Pastikan `.env` ada di folder `btc_sniper/`.

### ❌ "ModuleNotFoundError: No module named 'websockets'"
→ Virtual environment belum aktif atau dependencies belum diinstall.
```powershell
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### ❌ Dashboard kosong "— WAITING DATA —"
→ Normal saat baru startup. Tunggu 5-10 detik untuk data masuk.
→ Jika tetap kosong > 30 detik: cek koneksi internet dan POLYGON_RPC_URL.

### ❌ "LOCKDOWN TRIGGERED — DATA_STALE"
→ WebSocket terputus. Cek koneksi internet. Bot akan otomatis cooldown 5 menit lalu coba resume.

### ❌ "LOCKDOWN TRIGGERED — CIRCUIT_BREAKER"
→ 3 loss berturut-turut. Bot istirahat 15 menit. Ini behavior normal — melindungi modal.

### ❌ Trade selalu di-SKIP
→ Kondisi market mungkin tidak ideal (gap terlalu kecil, CVD tidak aligned).
→ Cek `skip_log.csv` untuk melihat gate mana yang paling sering gagal.
→ Jika `skip_odds_too_high` tinggi → market sudah efisien, edge kecil.

---

> [!NOTE]
> **Urutan yang disarankan:**
> 1. Install → Isi .env → Paper trading 24 jam
> 2. Review trade_log dan skip_log
> 3. Kalibrasi parameter jika perlu
> 4. Paper trading 24 jam lagi
> 5. Baru pertimbangkan live trading dengan BASE_SHARES=1.0
