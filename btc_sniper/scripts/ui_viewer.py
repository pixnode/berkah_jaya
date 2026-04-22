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
from rich.panel import Panel
from rich.text import Text
from cli.dashboard import Dashboard, DashboardState, TradeHistoryEntry
from config import load_config

async def run_viewer():
    # Move up ONE level from scripts/ to btc_sniper/ — where .env actually lives
    project_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    env_path = os.path.join(project_dir, ".env")
    cfg = load_config(env_path if os.path.exists(env_path) else None)
    
    # dashboard_ui.json is written to OUTPUT_DIR (default: ./output) relative to cwd
    ui_file = os.path.join(project_dir, cfg.OUTPUT_DIR.lstrip("./"), "dashboard_ui.json")
    
    if not os.path.exists(ui_file):
        print(f"Error: UI State file not found at {ui_file}")
        print("Make sure the bot is running and writing to this location.")
        return

    dashboard = Dashboard(cfg)
    
    def update_dashboard_state(target_state, source_data):
        # Convert trade history
        history = []
        for h in source_data.get("trade_history", []):
            history.append(TradeHistoryEntry(**h))
        
        # Update fields on existing state object
        for k, v in source_data.items():
            if k == "trade_history":
                target_state.trade_history = history
            elif hasattr(target_state, k):
                setattr(target_state, k, v)

    print("Connecting to Bot UI Stream...")
    
    with Live(dashboard._build_layout(), refresh_per_second=1, screen=True) as live:
        while True:
            try:
                if os.path.exists(ui_file):
                    with open(ui_file, "r") as f:
                        data = json.load(f)
                    
                    file_age = time.time() - os.path.getmtime(ui_file)
                    update_dashboard_state(dashboard.state, data)
                    
                    layout = dashboard._build_layout()
                    live.update(layout)
                else:
                    live.update(Panel(Text(f"Mencari file: {ui_file}...", style="yellow")))
            except Exception as e:
                # Tampilkan error di layar jika terjadi masalah pembacaan
                live.update(Panel(Text(f"ERROR SINKRONISASI: {str(e)}", style="bold white on red")))
            
            await asyncio.sleep(0.5)

if __name__ == "__main__":
    try:
        asyncio.run(run_viewer())
    except KeyboardInterrupt:
        pass
