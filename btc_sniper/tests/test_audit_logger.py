# ═══ tests/test_audit_logger.py ═══
"""Tests for AuditLogger — CSV field counts, append, atomic write."""
import asyncio, csv, json, os, pytest, shutil
from pathlib import Path
from logs.audit_logger import (
    AuditLogger, TradeRecord, SkipRecord, SnapshotRecord, SessionStats, EventRecord,
    TRADE_LOG_FIELDS, SKIP_LOG_FIELDS, SNAPSHOT_FIELDS, SESSION_SUMMARY_FIELDS, EVENT_LOG_FIELDS,
)

@pytest.fixture
def logger_instance(cfg, tmp_path):
    import os; os.environ["OUTPUT_DIR"] = str(tmp_path)
    from config import load_config
    c = load_config()
    return AuditLogger(c), tmp_path

def _dummy_trade() -> TradeRecord:
    return TradeRecord(
        "s1","w1","2026-04-19 14:35:08","2026-04-19 14:35:08","2026-04-19 14:35:11",
        "UP",84000.0,84200.0,200.0,45.0,"NORM",1500000,1050000,25.0,20.0,0.70,
        True,1.5,0.69,0.01,0.003,1.5,2800,1.0,0.70,"WIN",84300.0,1.0,0.30,"AUTO",
        "2026-04-19 14:36:00","2.3",
    )

def _dummy_skip() -> SkipRecord:
    return SkipRecord("s1","w1","2026-04-19 14:35:52","GAP_INSUFFICIENT","EVALUATE",
        30.0,45.0,False,500000,False,True,0.70,0.58,0.82,True,True,True,None,48,None,8)

def _dummy_snapshot() -> SnapshotRecord:
    return SnapshotRecord("s1","w1","2026-04-19 14:30:05",295,84000.0,84055.0,55.0,"UP",
        92.5,"NORM",180000,True,4200000,0.565,0.435,850.0,620.0,1.8,True,6,"MONITORING",False,None)

@pytest.mark.asyncio
async def test_trade_log_creates_header_on_new_file(logger_instance):
    al, tmp = logger_instance
    await al.log_trade(_dummy_trade())
    files = list(tmp.glob("trade_log*.csv"))
    assert len(files) >= 1
    with open(files[0]) as f:
        reader = csv.reader(f)
        header = next(reader)
        assert len(header) == 32, f"Trade log should have 32 columns, got {len(header)}"

@pytest.mark.asyncio
async def test_trade_log_has_32_columns(logger_instance):
    assert len(TRADE_LOG_FIELDS) == 32

@pytest.mark.asyncio
async def test_trade_log_appends_correctly(logger_instance):
    al, tmp = logger_instance
    await al.log_trade(_dummy_trade())
    await al.log_trade(_dummy_trade())
    files = list(tmp.glob("trade_log*.csv"))
    with open(files[0]) as f:
        rows = list(csv.reader(f))
        assert len(rows) == 3, "Header + 2 data rows"

@pytest.mark.asyncio
async def test_skip_log_has_21_columns(logger_instance):
    assert len(SKIP_LOG_FIELDS) == 21
    al, tmp = logger_instance
    await al.log_skip(_dummy_skip())
    files = list(tmp.glob("skip_log*.csv"))
    with open(files[0]) as f:
        header = next(csv.reader(f))
        assert len(header) == 21

@pytest.mark.asyncio
async def test_skip_log_would_have_won_update(logger_instance):
    al, tmp = logger_instance
    await al.log_skip(_dummy_skip())
    await al.update_skip_would_have_won("w1", "DOWN")
    files = list(tmp.glob("skip_log*.csv"))
    with open(files[0]) as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["window_id"] == "w1":
                # gap_value=30 (positive) = UP direction, resolution=DOWN → would_have_won=False
                assert row["would_have_won"] == "False"

@pytest.mark.asyncio
async def test_market_snapshot_has_23_columns(logger_instance):
    assert len(SNAPSHOT_FIELDS) == 23
    al, tmp = logger_instance
    await al.log_snapshot(_dummy_snapshot())
    files = list(tmp.glob("market_snapshot*.csv"))
    with open(files[0]) as f:
        header = next(csv.reader(f))
        assert len(header) == 23

@pytest.mark.asyncio
async def test_snapshot_window_result_update(logger_instance):
    al, tmp = logger_instance
    await al.log_snapshot(_dummy_snapshot())
    await al.update_snapshot_window_result("w1", "UP")
    files = list(tmp.glob("market_snapshot*.csv"))
    with open(files[0]) as f:
        reader = csv.DictReader(f)
        for row in reader:
            assert row["window_result"] == "UP"

@pytest.mark.asyncio
async def test_session_summary_has_30_columns(logger_instance):
    assert len(SESSION_SUMMARY_FIELDS) == 30

@pytest.mark.asyncio
async def test_event_log_all_event_types_serializable(logger_instance):
    al, tmp = logger_instance
    types = ["TRADE_FILL","SKIP","LOCKDOWN","RESUME","DATA_STALE","WS_RECONNECT","CLAIM_SUCCESS","SHUTDOWN"]
    for t in types:
        await al.log_event(EventRecord(1000.0, t, "w1", "test", "", "details", None, "{}"))
    files = list(tmp.glob("event_log*.csv"))
    with open(files[0]) as f:
        rows = list(csv.reader(f))
        assert len(rows) == len(types) + 1  # header + rows

@pytest.mark.asyncio
async def test_state_flush_atomic_write(logger_instance):
    al, tmp = logger_instance
    state = {"mode": "NORMAL", "window_id": "test", "order_sent": False}
    await al.flush_state(state)
    state_file = tmp / "engine_state.json"
    assert state_file.exists()
    with open(state_file) as f:
        data = json.load(f)
        assert data["mode"] == "NORMAL"
    # Verify no .tmp file left behind
    assert not (tmp / "engine_state.json.tmp").exists()

@pytest.mark.asyncio
async def test_concurrent_writes_no_corruption(logger_instance):
    al, tmp = logger_instance
    tasks = [al.log_trade(_dummy_trade()) for _ in range(10)]
    await asyncio.gather(*tasks)
    files = list(tmp.glob("trade_log*.csv"))
    with open(files[0]) as f:
        rows = list(csv.reader(f))
        assert len(rows) == 11, "Header + 10 concurrent writes"
