# Polymarket BTC Sniper v2.3 — Full Build Implementation Plan

> **Scope:** PRD_v2.3.md + MASTER_PROMPT_v2.3_REVISED.md  
> **Target:** Build seluruh sistem dari Iterasi 0 hingga Iterasi 9 secara berurutan  
> **Working Directory:** `c:\Users\Razer\OneDrive\Desktop\BERKAH JAYA\btc_sniper\`

---

## Execution Summary

Build 10 iterasi secara berurutan. Setiap iterasi menghasilkan file-file production-ready — tanpa placeholder, tanpa `# TODO`, tanpa `pass` tanpa implementasi.

| Iterasi | Komponen | File yang Dibuat | Est. LOC |
|---|---|---|---|
| **0** | Project Bootstrap | `config.py`, `main.py`, `.env.example`, `requirements.txt`, semua `__init__.py`, scaffold | ~600 |
| **1** | Feed Layer | `feeds/hyperliquid_ws.py`, `feeds/polymarket_ws.py`, `feeds/chainlink_feed.py`, `feeds/__init__.py` | ~800 |
| **2** | Signal Processor | `core/signal_processor.py` | ~400 |
| **3** | Entry Gates | `risk/gates.py` | ~350 |
| **4** | Order Executor + Claim | `core/order_executor.py`, `core/claim_manager.py` | ~500 |
| **5** | Circuit Breaker + Safety | `core/circuit_breaker.py`, `risk/safety_monitor.py` | ~450 |
| **6** | Audit Logger | `logs/audit_logger.py` | ~600 |
| **7** | CLI Dashboard | `cli/dashboard.py` | ~500 |
| **8** | Main Engine + Integration | `core/engine.py` (full), `main.py` (full) | ~600 |
| **9** | Testing Suite | `tests/test_gates.py`, `test_signal_processor.py`, `test_circuit_breaker.py`, `test_audit_logger.py`, `test_order_executor.py` | ~800 |

**Total estimasi: ~5,600 LOC across ~25 files**

---

## Target Directory Structure

```
btc_sniper/
├── main.py
├── config.py
├── .env.example
├── requirements.txt
├── core/
│   ├── __init__.py
│   ├── engine.py
│   ├── signal_processor.py
│   ├── order_executor.py
│   ├── claim_manager.py
│   └── circuit_breaker.py
├── feeds/
│   ├── __init__.py
│   ├── hyperliquid_ws.py
│   ├── polymarket_ws.py
│   └── chainlink_feed.py
├── risk/
│   ├── __init__.py
│   ├── gates.py
│   └── safety_monitor.py
├── logs/
│   ├── __init__.py
│   └── audit_logger.py
├── cli/
│   ├── __init__.py
│   └── dashboard.py
├── output/
│   └── .gitkeep
└── tests/
    ├── __init__.py
    ├── conftest.py
    ├── test_gates.py
    ├── test_signal_processor.py
    ├── test_circuit_breaker.py
    ├── test_audit_logger.py
    └── test_order_executor.py
```

---

## Proposed Changes (Iterasi per Iterasi)

### Iterasi 0 — Project Bootstrap

#### [NEW] config.py
- `BotConfig` dataclass dengan **50+ env vars** lengkap dari Master Prompt
- `validate_config()` — validasi semua field wajib, tipe data, range values
- Startup banner dengan rich box, paper mode warning

#### [NEW] main.py  
- Entry point, argparse `--paper`, KeyboardInterrupt handler

#### [NEW] .env.example
- Semua variable dengan komentar penjelasan

#### [NEW] requirements.txt
- Pinned versions sesuai Master Prompt

#### [NEW] Semua `__init__.py` 
- Export symbols sesuai spesifikasi

#### [NEW] core/engine.py (scaffold)
- `get_current_window_slug()` dan `get_time_remaining()` utility functions

---

### Iterasi 1 — Feed Layer

#### [NEW] feeds/__init__.py
- 6 dataclasses: `TradeEvent`, `PriceEvent`, `OrderBookEvent`, `OddsEvent`, `ChainlinkEvent`, `DataStaleEvent`

#### [NEW] feeds/hyperliquid_ws.py
- `HyperliquidFeed` — WebSocket ke Hyperliquid, parse trades + l2Book, heartbeat, reconnect backoff

#### [NEW] feeds/polymarket_ws.py
- `PolymarketFeed` — WebSocket ke Polymarket CLOB, subscribe/unsubscribe per window, orderbook + odds events

#### [NEW] feeds/chainlink_feed.py
- `ChainlinkFeed` — Poll Chainlink BTC/USD via web3.py AsyncWeb3, age tracking, staleness detection

---

### Iterasi 2 — Signal Processor

#### [NEW] core/signal_processor.py
- `SignalProcessor` — CVD rolling 60s (deque), ATR candle aggregation (deque), velocity (deque), gap calculation
- `SignalState` dataclass
- Semua kalkulasi O(1) / O(window), pure Python tanpa numpy/pandas

---

### Iterasi 3 — Entry Gates

#### [NEW] risk/gates.py
- `GateEvaluator` — 7-gate AND logic (sesuai PRD v2.3 Section 04)
- Gate 4 = Odds Boundary (MIN/MAX), Gate 5 = Golden Window
- `GateResult` dataclass dengan `to_csv_row()`, short-circuit evaluation

---

### Iterasi 4 — Order Executor + Claim Manager

#### [NEW] core/order_executor.py
- `OrderExecutor` — paper trading guard, temporal slippage check (Check B), position size guard, EIP-712 signing
- `OrderResult` dataclass

#### [NEW] core/claim_manager.py
- `ClaimManager` — auto claim via gasless relayer, retry queue, wallet type detection
- `ClaimResult` dataclass

---

### Iterasi 5 — Circuit Breaker + Safety Monitor

#### [NEW] core/circuit_breaker.py
- `CircuitBreaker` — state machine NORMAL → LOCKDOWN → COOLDOWN → NORMAL
- 4-step LOCKDOWN Resume Protocol, asyncio.Lock untuk thread-safety

#### [NEW] risk/safety_monitor.py
- `SafetyMonitor` — 10 trigger monitoring loop (0.5s), DATA_STALE, CHAINLINK_UNSTABLE, SYNC_LATENCY, dsb
- `SafetyEvent` dataclass

---

### Iterasi 6 — Audit Logger

#### [NEW] logs/audit_logger.py
- `AuditLogger` — 4 CSV + 1 JSON + 1 event log
- trade_log.csv: 32 field persis PRD v2.3 Section 08.1
- skip_log.csv: 21 field + `would_have_won` post-hoc update
- market_snapshot.csv: 23 field + `window_result` post-hoc update
- session_summary.csv: 30 field
- event_log.csv: 8 field
- engine_state.json: atomic write via .tmp → rename
- Asyncio.Lock per file, file rotation, append-only

---

### Iterasi 7 — CLI Dashboard

#### [NEW] cli/dashboard.py
- `Dashboard` — 6-panel rich.Live terminal dashboard
- Panel A: Header, Panel B: Price/Gap, Panel C: CVD ASCII, Panel D: Order Book, Panel E: Safety Gates, Panel F: P&L + History
- Keyboard: Q=quit, P=pause, R=resume, L=locks overlay
- Selective refresh strategy (bukan full repaint setiap cycle)

---

### Iterasi 8 — Main Engine Integration

#### [MODIFY] core/engine.py
- `BotEngine` — full integration: startup sequence (10 steps), main_loop, window lifecycle, task supervisor
- Shutdown sequence: cancel tasks, flush state, write session summary

#### [MODIFY] main.py
- Full entry point dengan argparse, banner, exception handling

---

### Iterasi 9 — Testing Suite

#### [NEW] tests/conftest.py + 5 test files
- 40+ test functions covering: gates, signal processor, circuit breaker, audit logger, order executor
- pytest-asyncio, mock semua network calls
- Validasi kolom count CSV (32, 21, 23, 30 fields)

---

## Verification Plan

### Automated Tests
```bash
cd btc_sniper
pip install -r requirements.txt
python -m pytest tests/ -v --tb=short
```

### Manual Verification
1. `python config.py` — validate .env loading + banner display
2. `python main.py --paper` — paper mode startup, verify CLI dashboard renders
3. Inspect output CSV files for correct column counts
4. Verify engine_state.json atomic write behavior

---

> [!IMPORTANT]
> **Semua file akan ditulis secara lengkap tanpa placeholder, `# TODO`, atau `pass` tanpa implementasi.**
> Estimasi waktu eksekusi: signifikan karena ~5,600 LOC.
> Setiap iterasi akan dikerjakan berurutan — output iterasi N menjadi input iterasi N+1.

> [!WARNING]
> **PAPER_TRADING_MODE=True** akan menjadi default di semua konfigurasi.
> Tidak ada real money execution sampai semua 3 validasi pra-build (Section 09 PRD) selesai.
