# ═══ FILE: btc_sniper/scripts/ui_viewer.py ═══
"""
Remote UI Viewer for BTC Sniper.
Reads output/dashboard_ui.json and renders the Dashboard locally.
"""

import os
import sys
import json
import time
import asyncio
from dataclasses import dataclass, field
from typing import List, Dict

# Add parent dir to sys.path to import modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Force UTF-8 for Windows consoles to avoid cp1252 UnicodeEncodeError
if sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from rich.live import Live
from cli.dashboard import Dashboard, DashboardState, TradeHistoryEntry
from config import load_config

async def run_viewer():
    cfg = load_config()
    ui_file = os.path.join(cfg.OUTPUT_DIR, "dashboard_ui.json")
    
    if not os.path.exists(ui_file):
        print(f"Error: UI State file not found at {ui_file}")
        print("Make sure the bot is running via PM2.")
        return

    # Use existing Dashboard class but override run to be read-only
    dashboard = Dashboard(cfg)
    
    def dict_to_state(data: dict) -> DashboardState:
        # Convert trade history
        history = []
        for h in data.get("trade_history", []):
            history.append(TradeHistoryEntry(**h))
        
        # Create state
        state = DashboardState()
        for k, v in data.items():
            if k == "trade_history":
                state.trade_history = history
            elif hasattr(state, k):
                setattr(state, k, v)
        return state

    print("Connecting to Bot UI Stream...")
    
    with Live(dashboard._build_layout(), refresh_per_second=4, screen=True) as live:
        while True:
            try:
                if os.path.exists(ui_file):
                    with open(ui_file, "r") as f:
                        data = json.load(f)
                    
                    new_state = dict_to_state(data)
                    # Update current dashboard state
                    dashboard._state = new_state
                    live.update(dashboard._build_layout())
            except Exception:
                pass
            await asyncio.sleep(0.25)

if __name__ == "__main__":
    try:
        asyncio.run(run_viewer())
    except KeyboardInterrupt:
        pass
