# ITERASI 10 — PAPER MODE HARDENING + RELAYER API + CONNECTION CONFIG
### Tambahan untuk Master Prompt v2.3 | Polymarket BTC Sniper
`Prerequisite: Iterasi 0–9 sudah selesai | April 2026`

---

## ITERASI 10A — PAPER MODE HARDENING

```
PERAN:
Kamu adalah Senior Backend Engineer yang memastikan paper trading mode
berjalan aman dan realistis tanpa menyentuh blockchain atau real capital.

TUGAS:
Audit dan perkuat implementasi PAPER_TRADING_MODE di seluruh codebase.
Pastikan tidak ada satu pun network call yang bisa mengeluarkan USDC
saat PAPER_TRADING_MODE=True.

KONTEKS — APA YANG DIBUTUHKAN DI PAPER MODE:
Paper mode TIDAK butuh:
  - USDC di wallet (tidak ada transaksi keluar)
  - Signing transaksi real ke Polygon
  - Polymarket CLOB order submission
  - Gasless relayer untuk claim

Paper mode TETAP butuh:
  - POLYGON_RPC_URL → untuk baca Chainlink price feed (read-only, gratis)
  - POLYMARKET_PRIVATE_KEY → hanya untuk derive wallet address (bukan signing)
  - Hyperliquid WebSocket → live price feed (tidak perlu auth)
  - Polymarket CLOB WebSocket → live odds feed (tidak perlu auth)

TUGAS DETAIL:

━━━ 1. Tambahkan PAPER MODE GUARD di config.py ━━━

Tambahkan fungsi ini ke config.py:

def print_paper_mode_warning(cfg: BotConfig) -> None:
    """Cetak warning box prominent jika PAPER_TRADING_MODE=True."""
    if not cfg.PAPER_TRADING_MODE:
        return
    lines = [
        "╔══════════════════════════════════════════════════╗",
        "║           ⚠  PAPER TRADING MODE AKTIF  ⚠        ║",
        "║                                                  ║",
        "║  Semua order adalah SIMULASI.                    ║",
        "║  Tidak ada USDC yang keluar dari wallet.         ║",
        "║  Tidak ada transaksi ke Polygon blockchain.      ║",
        "║                                                  ║",
        "║  Yang tetap terhubung (read-only):               ║",
        "║  ✓ Chainlink RPC (baca harga resolusi)           ║",
        "║  ✓ Hyperliquid WebSocket (live price + CVD)      ║",
        "║  ✓ Polymarket CLOB WebSocket (live odds)         ║",
        "║                                                  ║",
        "║  Untuk live trading: set PAPER_TRADING_MODE=false║",
        "║  dan pastikan wallet funded dengan USDC.         ║",
        "╚══════════════════════════════════════════════════╝",
    ]
    for line in lines:
        print(line)

━━━ 2. Tambahkan Guard di order_executor.py ━━━

Di awal method execute():

    if self.cfg.PAPER_TRADING_MODE:
        # Simulasikan fill dengan live odds saat ini
        simulated_odds = gate_result.target_ask
        simulated_cost = self.cfg.BASE_SHARES * simulated_odds
        logger.info(f"[PAPER] Simulated {gate_result.side} fill: "
                    f"odds={simulated_odds:.3f}, cost=${simulated_cost:.4f}")
        return OrderResult(
            status="PAPER_FILL",
            window_id=window_id,
            side=gate_result.side,
            entry_odds=simulated_odds,
            shares_bought=self.cfg.BASE_SHARES,
            cost_usd=simulated_cost,
            slippage_delta=0.0,
            slippage_threshold_used=0.0,
            tx_hash=None,
            confirmed_at=time.time(),
            latency_ms=0,
            error_msg=None,
            is_paper=True,
        )
    # ... lanjut ke live execution

━━━ 3. Tambahkan Guard di claim_manager.py ━━━

Di method claim():

    if self.cfg.PAPER_TRADING_MODE:
        # Simulasikan resolusi — tentukan menang/kalah dari Chainlink
        resolution_price = await self.chainlink.get_strike_price()
        won = (
            (order_result.side == "UP" and resolution_price.price >= self.state.strike_price)
            or
            (order_result.side == "DOWN" and resolution_price.price < self.state.strike_price)
        )
        payout = self.cfg.BASE_SHARES if won else 0.0
        pnl    = payout - order_result.cost_usd
        logger.info(f"[PAPER] Claim simulated: {'WIN' if won else 'LOSS'} "
                    f"payout=${payout:.4f} pnl=${pnl:.4f}")
        return ClaimResult(
            status="PAPER",
            window_id=window_id,
            payout_usd=payout,
            claim_method="PAPER",
            claimed_at=time.time(),
            retry_count=0,
            is_paper=True,
        )
    # ... lanjut ke live claim

━━━ 4. Tambahkan ENV vars untuk Paper Mode ke .env.example ━━━

# ── PAPER TRADING ─────────────────────────────────────────────
PAPER_TRADING_MODE=true
# WAJIB true saat pertama deploy. Ubah ke false hanya setelah:
# 1. Semua 3 validasi pra-build lolos
# 2. Wallet funded dengan USDC
# 3. Relayer API credentials sudah dikonfigurasi (lihat bagian RELAYER)
# 4. Paper trading sudah menghasilkan data yang konsisten (50+ windows)

FORMAT OUTPUT:
- Tulis semua perubahan secara lengkap
- Tambahkan unit test: test_paper_mode_no_network_calls()
  yang memverifikasi tidak ada aiohttp/web3 call saat PAPER_TRADING_MODE=True
  (gunakan mock dan assert mock.call_count == 0)
```

---

## ITERASI 10B — RELAYER API + AUTO CLAIM SETUP

```
PERAN:
Kamu adalah Senior Backend Engineer spesialis Polymarket CLOB integration.
Kamu memahami bahwa auto-claim membutuhkan API credentials terpisah dari
private key wallet, dan credentials ini harus di-derive secara eksplisit.

TUGAS:
Implementasikan setup Polymarket API credentials dan Gasless Relayer
untuk auto-claim winning shares.

KONTEKS — CARA KERJA POLYMARKET AUTO CLAIM:
Polymarket menggunakan dua mekanisme berbeda:
  1. Order submission  : signed EIP-712 order via py-clob-client
  2. Auto claim/redeem : Gasless Relayer — Polymarket menanggung gas fee

Untuk keduanya, dibutuhkan API credentials yang di-derive dari wallet signature.
Ini BUKAN POLYMARKET_PRIVATE_KEY langsung, tapi derived API key.

Flow credentials:
  Private Key → sign message → derive API Key + Secret + Passphrase
  → gunakan untuk authenticate ke CLOB API dan Relayer

ENDPOINTS:
  CLOB_HOST     = https://clob.polymarket.com
  RELAYER_URL   = https://relayer.polymarket.com
  GAMMA_API     = https://gamma-api.polymarket.com  (untuk market lookup)

TUGAS DETAIL:

━━━ 1. Tambahkan ke config.py — Relayer & CLOB Config ━━━

Tambahkan ke BotConfig dataclass:

  # POLYMARKET CLOB & RELAYER
  CLOB_HOST: str                       # default: https://clob.polymarket.com
  RELAYER_URL: str                     # default: https://relayer.polymarket.com
  GAMMA_API_URL: str                   # default: https://gamma-api.polymarket.com
  POLY_API_KEY: str                    # di-derive dari wallet — wajib di live mode
  POLY_API_SECRET: str                 # di-derive dari wallet — wajib di live mode
  POLY_API_PASSPHRASE: str             # di-derive dari wallet — wajib di live mode
  POLY_CHAIN_ID: int                   # default: 137 (Polygon mainnet)

Tambahkan ke validate_config():
  Jika PAPER_TRADING_MODE=False:
    Jika POLY_API_KEY kosong → raise ConfigurationError("POLY_API_KEY wajib di live mode")
    Jika POLY_API_SECRET kosong → raise ConfigurationError("POLY_API_SECRET wajib di live mode")
    Jika POLY_API_PASSPHRASE kosong → raise ConfigurationError("POLY_API_PASSPHRASE wajib di live mode")
  Jika PAPER_TRADING_MODE=True:
    Log INFO: "Paper mode: POLY_API_KEY tidak diperlukan"

━━━ 2. Buat scripts/setup_credentials.py — One-time Setup Script ━━━

Tulis script TERPISAH (bukan bagian dari bot runtime) untuk generate
Polymarket API credentials dari private key:

#!/usr/bin/env python3
"""
One-time script untuk generate Polymarket API credentials.
Jalankan SEKALI sebelum live trading:
  python scripts/setup_credentials.py

Output: tampilkan POLY_API_KEY, POLY_API_SECRET, POLY_API_PASSPHRASE
yang harus disalin ke .env
"""

import asyncio
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds

async def setup_credentials(private_key: str, chain_id: int = 137) -> None:
    """
    Generate API credentials dari private key wallet.
    
    Langkah:
    1. Init ClobClient dengan private key
    2. Derive API credentials (sign challenge message)
    3. Set API credentials ke CLOB
    4. Print hasil ke terminal untuk disalin ke .env
    """
    client = ClobClient(
        host="https://clob.polymarket.com",
        key=private_key,
        chain_id=chain_id,
    )
    
    # Derive credentials
    creds: ApiCreds = client.create_or_derive_api_creds()
    
    print("\n" + "="*60)
    print("POLYMARKET API CREDENTIALS — SALIN KE .env")
    print("="*60)
    print(f"POLY_API_KEY={creds.api_key}")
    print(f"POLY_API_SECRET={creds.api_secret}")
    print(f"POLY_API_PASSPHRASE={creds.api_passphrase}")
    print("="*60)
    print("PENTING: Simpan credentials ini dengan aman.")
    print("Jangan commit .env ke git.")
    print("="*60 + "\n")

if __name__ == "__main__":
    import os
    from dotenv import load_dotenv
    load_dotenv()
    
    pk = os.getenv("POLYMARKET_PRIVATE_KEY")
    if not pk:
        print("ERROR: POLYMARKET_PRIVATE_KEY tidak ditemukan di .env")
        exit(1)
    
    print("Generating Polymarket API credentials...")
    asyncio.run(setup_credentials(pk))

━━━ 3. Refactor core/claim_manager.py untuk Gasless Relayer ━━━

Tambahkan method _init_clob_client() di ClaimManager.__init__():

    self._clob_client: Optional[ClobClient] = None

    async def _init_clob_client(self) -> None:
        """Initialize CLOB client dengan API credentials."""
        if self.cfg.PAPER_TRADING_MODE:
            logger.info("Paper mode: CLOB client tidak diinisialisasi")
            return
        self._clob_client = ClobClient(
            host=self.cfg.CLOB_HOST,
            key=self.cfg.POLYMARKET_PRIVATE_KEY,
            chain_id=self.cfg.POLY_CHAIN_ID,
            creds=ApiCreds(
                api_key=self.cfg.POLY_API_KEY,
                api_secret=self.cfg.POLY_API_SECRET,
                api_passphrase=self.cfg.POLY_API_PASSPHRASE,
            ),
        )
        logger.info("CLOB client initialized successfully")

Refactor method claim() untuk live mode:

    async def _redeem_winning_shares(self, window_id: str) -> ClaimResult:
        """
        Redeem winning shares via Polymarket Gasless Relayer.
        Tidak membutuhkan MATIC untuk gas — Polymarket menanggung biaya.
        """
        if self._clob_client is None:
            raise RuntimeError("CLOB client belum diinisialisasi")
        
        # Step 1: Cek apakah ada winning positions
        positions = await asyncio.wait_for(
            asyncio.to_thread(self._clob_client.get_positions),
            timeout=self.cfg.CLAIM_RETRY_TIMEOUT_SEC,
        )
        
        winning = [p for p in positions if p.market_id == window_id and p.size > 0]
        if not winning:
            return ClaimResult(
                status="NOT_APPLICABLE",
                window_id=window_id,
                payout_usd=0.0,
                claim_method="N-A",
                claimed_at=None,
                retry_count=0,
                is_paper=False,
            )
        
        # Step 2: Redeem via gasless relayer
        # py-clob-client handles the relayer call internally
        redeem_result = await asyncio.wait_for(
            asyncio.to_thread(
                self._clob_client.redeem_positions,
                [p.position_id for p in winning]
            ),
            timeout=self.cfg.CLAIM_RETRY_TIMEOUT_SEC,
        )
        
        payout = sum(p.payout for p in winning)
        logger.info(f"[CLAIM] Auto-claimed ${payout:.4f} for window {window_id}")
        
        return ClaimResult(
            status="AUTO",
            window_id=window_id,
            payout_usd=payout,
            claim_method="AUTO",
            claimed_at=time.time(),
            retry_count=0,
            is_paper=False,
        )

━━━ 4. Tambahkan Relayer Health Check di startup ━━━

Di core/engine.py, STARTUP SEQUENCE setelah step 4, tambahkan:

  4b. Jika PAPER_TRADING_MODE=False:
       - Test koneksi ke CLOB_HOST: GET /auth/api-key
       - Jika gagal → raise RuntimeError("CLOB API connection failed — cek POLY_API_KEY")
       - Test relayer: GET {RELAYER_URL}/health
       - Jika gagal → log WARNING (bukan raise — relayer bisa down sementara)
       - Log: "CLOB connected ✓  Relayer: {status}"

FORMAT OUTPUT:
- Tulis setup_credentials.py secara lengkap dan executable
- Tulis semua perubahan config.py, claim_manager.py, engine.py
- Tambahkan unit test: test_claim_paper_mode_no_relayer_call()
- Tulis semua file secara lengkap
```

---

## ITERASI 10C — CONNECTION CONFIG TERPUSAT VIA .ENV

```
PERAN:
Kamu adalah Senior Systems Architect yang memastikan semua koneksi
(API, RPC, WebSocket) terkontrol penuh dari .env tanpa hardcoded values.

TUGAS:
Audit seluruh codebase dan pastikan tidak ada URL, endpoint, atau
connection string yang hardcoded. Semua harus dari BotConfig.
Tambahkan connection health check yang bisa dijalankan standalone.

TUGAS DETAIL:

━━━ 1. .env.example LENGKAP — Semua Connection Config ━━━

Tulis ulang .env.example dengan SEMUA connection vars, dikelompokkan:

# ══════════════════════════════════════════════════════════════
# POLYMARKET BTC SNIPER v2.3 — MASTER CONFIGURATION
# ══════════════════════════════════════════════════════════════
# PETUNJUK PENGISIAN:
# 1. Copy file ini: cp .env.example .env
# 2. Jalankan: python scripts/setup_credentials.py  (untuk POLY_API_KEY)
# 3. Set PAPER_TRADING_MODE=true untuk mulai
# 4. Validasi semua koneksi: python scripts/check_connections.py

# ── MODE ──────────────────────────────────────────────────────
BOT_MODE=paper
PAPER_TRADING_MODE=true
BOT_VERSION=2.3
LOG_LEVEL=INFO

# ── WALLET ────────────────────────────────────────────────────
POLYMARKET_PRIVATE_KEY=0x_ISI_PRIVATE_KEY_DISINI
POLYMARKET_PROXY_WALLET=0x_ISI_PROXY_WALLET_DISINI
POLY_CHAIN_ID=137

# ── POLYMARKET API CREDENTIALS ────────────────────────────────
# Generate dengan: python scripts/setup_credentials.py
# Wajib diisi jika PAPER_TRADING_MODE=false
POLY_API_KEY=
POLY_API_SECRET=
POLY_API_PASSPHRASE=

# ── POLYMARKET ENDPOINTS ──────────────────────────────────────
CLOB_HOST=https://clob.polymarket.com
RELAYER_URL=https://relayer.polymarket.com
GAMMA_API_URL=https://gamma-api.polymarket.com

# ── POLYGON RPC ───────────────────────────────────────────────
# Gratis: https://polygon-rpc.com
# Alchemy (recommended): https://polygon-mainnet.g.alchemy.com/v2/YOUR_KEY
# Infura: https://polygon-mainnet.infura.io/v3/YOUR_KEY
POLYGON_RPC_URL=https://polygon-rpc.com
POLYGON_GAS_TIP_MULTIPLIER=1.0

# ── HYPERLIQUID WEBSOCKET ─────────────────────────────────────
HYPERLIQUID_WS_URL=wss://api.hyperliquid.xyz/ws
HYPERLIQUID_API_KEY=
# Kosong untuk public endpoint (tidak perlu API key untuk price feed)

# ── POLYMARKET CLOB WEBSOCKET ─────────────────────────────────
POLY_WS_URL=wss://ws-subscriptions-clob.polymarket.com/ws/market
# Note: URL ini berbeda dengan CLOB_HOST — endpoint WebSocket khusus

# ── WEBSOCKET RELIABILITY ─────────────────────────────────────
WS_HEARTBEAT_INTERVAL_SEC=3
WS_STALE_THRESHOLD_SEC=5
WS_RECONNECT_MAX_RETRY=5
WS_RECONNECT_BASE_DELAY_SEC=1
WS_RECONNECT_MAX_DELAY_SEC=30

# ── CHAINLINK ─────────────────────────────────────────────────
CHAINLINK_CONTRACT_ADDRESS=0xc907E116054Ad103354f2D350FD2514433D57F6F
CHAINLINK_POLL_INTERVAL_SEC=3
CHAINLINK_MAX_AGE_SEC=10
CHAINLINK_MAX_AGE_ENTRY_SEC=25
CHAINLINK_VOLATILITY_SKIP_USD=35.0

# ── STRATEGY CORE ─────────────────────────────────────────────
BASE_SHARES=1.0
MAX_POSITION_USD=10.0
GAP_THRESHOLD_DEFAULT=45.0
GAP_THRESHOLD_LOW_VOL=60.0
GAP_THRESHOLD_HIGH_VOL=35.0
ATR_LOW_THRESHOLD=50.0
ATR_HIGH_THRESHOLD=150.0
ATR_LOOKBACK_CANDLES=12

# ── ODDS BOUNDARY ─────────────────────────────────────────────
ODDS_MIN=0.58
ODDS_MAX=0.82
ODDS_SWEET_SPOT_LOW=0.62
ODDS_SWEET_SPOT_HIGH=0.76

# ── CVD ───────────────────────────────────────────────────────
CVD_VOLUME_WINDOW_MINUTES=30
CVD_THRESHOLD_PCT=25.0

# ── VELOCITY ──────────────────────────────────────────────────
VELOCITY_ENABLED=true
VELOCITY_MIN_DELTA=15.0
VELOCITY_WINDOW_SECONDS=1.5

# ── TIMING ────────────────────────────────────────────────────
GOLDEN_WINDOW_START=60
GOLDEN_WINDOW_END=42

# ── SLIPPAGE ──────────────────────────────────────────────────
SLIPPAGE_THRESHOLD_NORMAL=1.0
SLIPPAGE_THRESHOLD_ELEVATED=1.5
SLIPPAGE_THRESHOLD_HIGH=2.0
SPREAD_MAX_PCT=3.0
MISPRICING_MULTIPLIER=0.15
MISPRICING_MIN_EDGE=0.02

# ── RISK & CIRCUIT BREAKER ────────────────────────────────────
CIRCUIT_BREAKER_MAX_LOSS=3
COOLDOWN_CIRCUIT_BREAKER_SEC=900
COOLDOWN_DATA_STALE_SEC=300
MAX_DAILY_LOSS_USD=0.0
MIN_TRADE_RESERVE=5

# ── CLAIM / RELAYER ───────────────────────────────────────────
CLAIM_RETRY_MAX=3
CLAIM_RETRY_TIMEOUT_SEC=30
CLAIM_RETRY_INTERVAL_SEC=60

# ── SYNC LATENCY ──────────────────────────────────────────────
SYNC_LATENCY_MAX_SEC=10

# ── OUTPUT & LOGGING ──────────────────────────────────────────
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

# ── CLI ────────────────────────────────────────────────────────
CLI_REFRESH_RATE=4
CLI_ORDERBOOK_UPDATE_SEC=2
CLI_TRADE_LOG_ROWS=10

━━━ 2. Tambahkan ke config.py — Semua Connection Vars ━━━

Pastikan semua var di atas ada di BotConfig dataclass:
- POLY_WS_URL: str                  # default: wss://ws-subscriptions-clob.polymarket.com/ws/market
- CHAINLINK_CONTRACT_ADDRESS: str   # default: 0xc907E116054Ad103354f2D350FD2514433D57F6F
- CHAINLINK_POLL_INTERVAL_SEC: int  # default: 3
- WS_RECONNECT_BASE_DELAY_SEC: int  # default: 1
- WS_RECONNECT_MAX_DELAY_SEC: int   # default: 30
- HYPERLIQUID_API_KEY: str          # default: "" (kosong = public)

Refactor feeds/ untuk menggunakan vars ini (tidak ada hardcoded URL):
- hyperliquid_ws.py   : gunakan cfg.HYPERLIQUID_WS_URL
- polymarket_ws.py    : gunakan cfg.POLY_WS_URL
- chainlink_feed.py   : gunakan cfg.POLYGON_RPC_URL, cfg.CHAINLINK_CONTRACT_ADDRESS
- Exponential backoff  : cfg.WS_RECONNECT_BASE_DELAY_SEC, cfg.WS_RECONNECT_MAX_DELAY_SEC

━━━ 3. Buat scripts/check_connections.py — Standalone Health Check ━━━

Tulis script yang bisa dijalankan SEBELUM start bot untuk validasi semua koneksi:

#!/usr/bin/env python3
"""
Connection health check untuk Polymarket BTC Sniper.
Jalankan sebelum start bot:
  python scripts/check_connections.py

Checks semua koneksi dan print status.
Exit code 0 = semua OK, 1 = ada yang gagal.
"""

async def check_all_connections(cfg: BotConfig) -> dict[str, bool]:
    results = {}
    
    # 1. Polygon RPC + Chainlink
    print("Checking Polygon RPC + Chainlink...", end=" ", flush=True)
    try:
        w3 = AsyncWeb3(AsyncHTTPProvider(cfg.POLYGON_RPC_URL))
        connected = await asyncio.wait_for(w3.is_connected(), timeout=10)
        block = await asyncio.wait_for(w3.eth.block_number, timeout=10)
        # Test Chainlink read
        contract = w3.eth.contract(
            address=cfg.CHAINLINK_CONTRACT_ADDRESS,
            abi=CHAINLINK_ABI
        )
        data = await asyncio.wait_for(
            contract.functions.latestRoundData().call(), timeout=10
        )
        price = data[1] / 1e8
        age = int(time.time()) - data[3]
        print(f"✓  BTC=${price:,.0f}  age={age}s  block={block}")
        results["polygon_rpc"] = True
    except Exception as e:
        print(f"✗  FAILED: {e}")
        results["polygon_rpc"] = False

    # 2. Hyperliquid WebSocket
    print("Checking Hyperliquid WebSocket...", end=" ", flush=True)
    try:
        async with websockets.connect(cfg.HYPERLIQUID_WS_URL, open_timeout=10) as ws:
            sub_msg = '{"method":"subscribe","subscription":{"type":"trades","coin":"BTC"}}'
            await asyncio.wait_for(ws.send(sub_msg), timeout=5)
            msg = await asyncio.wait_for(ws.recv(), timeout=10)
            print(f"✓  Connected, received {len(msg)} bytes")
            results["hyperliquid_ws"] = True
    except Exception as e:
        print(f"✗  FAILED: {e}")
        results["hyperliquid_ws"] = False

    # 3. Polymarket CLOB WebSocket
    print("Checking Polymarket CLOB WebSocket...", end=" ", flush=True)
    try:
        async with websockets.connect(cfg.POLY_WS_URL, open_timeout=10) as ws:
            ping = await asyncio.wait_for(ws.ping(), timeout=5)
            print(f"✓  Connected")
            results["polymarket_ws"] = True
    except Exception as e:
        print(f"✗  FAILED: {e}")
        results["polymarket_ws"] = False

    # 4. Polymarket CLOB REST API
    print("Checking Polymarket CLOB API...", end=" ", flush=True)
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{cfg.CLOB_HOST}/health",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                status = resp.status
                print(f"✓  HTTP {status}")
                results["clob_api"] = status == 200
    except Exception as e:
        print(f"✗  FAILED: {e}")
        results["clob_api"] = False

    # 5. Relayer (hanya jika live mode)
    if not cfg.PAPER_TRADING_MODE:
        print("Checking Polymarket Relayer...", end=" ", flush=True)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{cfg.RELAYER_URL}/health",
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    print(f"✓  HTTP {resp.status}")
                    results["relayer"] = resp.status == 200
        except Exception as e:
            print(f"✗  FAILED: {e}")
            results["relayer"] = False

        # 6. CLOB API credentials (hanya live mode)
        print("Checking CLOB API credentials...", end=" ", flush=True)
        try:
            client = ClobClient(
                host=cfg.CLOB_HOST,
                key=cfg.POLYMARKET_PRIVATE_KEY,
                chain_id=cfg.POLY_CHAIN_ID,
                creds=ApiCreds(
                    api_key=cfg.POLY_API_KEY,
                    api_secret=cfg.POLY_API_SECRET,
                    api_passphrase=cfg.POLY_API_PASSPHRASE,
                ),
            )
            api_key = client.get_api_keys()
            print(f"✓  Authenticated")
            results["clob_credentials"] = True
        except Exception as e:
            print(f"✗  FAILED: {e}")
            results["clob_credentials"] = False
    else:
        print("Relayer & credentials check: SKIPPED (paper mode)")

    return results

if __name__ == "__main__":
    from config import load_config
    cfg = load_config()

    print("\n" + "═"*55)
    print("  POLYMARKET BTC SNIPER v2.3 — CONNECTION CHECK")
    mode = "[PAPER MODE]" if cfg.PAPER_TRADING_MODE else "[LIVE MODE]"
    print(f"  {mode}")
    print("═"*55 + "\n")

    results = asyncio.run(check_all_connections(cfg))

    print("\n" + "═"*55)
    all_ok = all(results.values())
    for name, ok in results.items():
        icon = "✓" if ok else "✗"
        print(f"  {icon}  {name}")
    print("═"*55)

    if all_ok:
        print("  STATUS: ALL CONNECTIONS OK — siap start bot\n")
        exit(0)
    else:
        failed = [k for k, v in results.items() if not v]
        print(f"  STATUS: FAILED — {', '.join(failed)}")
        print("  Perbaiki koneksi di .env sebelum start bot\n")
        exit(1)

FORMAT OUTPUT:
- Tulis check_connections.py secara lengkap dan executable
- Tulis .env.example secara lengkap dengan semua vars dan komentar
- Refactor feed files untuk tidak ada hardcoded URL
- Tulis semua file secara lengkap
```

---

## CARA PENGGUNAAN — URUTAN SETUP VPS

```
URUTAN SETUP PERTAMA KALI DI VPS:

STEP 1 — Clone dan setup environment:
  git clone <repo>
  cd btc_sniper
  pip install -r requirements.txt
  cp .env.example .env
  nano .env  # isi POLYMARKET_PRIVATE_KEY dan POLYGON_RPC_URL

STEP 2 — Generate Polymarket API credentials:
  python scripts/setup_credentials.py
  # Copy output ke .env:
  # POLY_API_KEY=...
  # POLY_API_SECRET=...
  # POLY_API_PASSPHRASE=...

STEP 3 — Validasi semua koneksi:
  python scripts/check_connections.py
  # Semua harus ✓ sebelum lanjut

STEP 4 — Start di paper mode (default):
  tmux new-session -s sniper
  python main.py
  # Pastikan PAPER_TRADING_MODE=true di .env

STEP 5 — Setelah 50+ windows paper trading konsisten:
  # Edit .env:
  PAPER_TRADING_MODE=false
  # Pastikan wallet funded dengan USDC
  python scripts/check_connections.py  # re-validate di live mode
  python main.py --live  # atau tanpa --paper flag

CHECKLIST WAJIB SEBELUM LIVE:
□ check_connections.py semua ✓ termasuk relayer dan credentials
□ POLY_API_KEY, POLY_API_SECRET, POLY_API_PASSPHRASE sudah diisi
□ Wallet adalah PROXY type (bukan EOA) untuk auto-claim
□ Wallet funded dengan USDC (minimal BASE_SHARES × MAX_POSITION_USD × 20)
□ Paper trading sudah 50+ windows dengan win rate > 70%
□ Semua 3 validasi pra-build dari PRD v2.3 Section 09 sudah lolos
```

---

*Iterasi 10A–10C | Tambahan untuk Master Prompt v2.3*
*Prerequisites: Iterasi 0–9 selesai*
