
import time
import os
import json
from datetime import datetime

# Path files
EVENT_LOG = r'c:\Users\Razer\OneDrive\Desktop\BERKAH JAYA\btc_sniper\output\event_log_2026-04-21.csv'
TRADE_LOG = r'c:\Users\Razer\OneDrive\Desktop\BERKAH JAYA\btc_sniper\output\trade_log.csv'
REPORT_FILE = r'c:\Users\Razer\OneDrive\Desktop\BERKAH JAYA\btc_sniper\output\monitor_report_1h.json'

print("🚀 MONITORING STARTED (Duration: 60 minutes)")

start_time = time.time()
duration = 3600 # 1 hour
report = {
    "start_time": datetime.now().isoformat(),
    "windows_monitored": [],
    "hedge_opportunities": 0,
    "trades_executed": 0,
    "errors": []
}

last_processed_line = 0

while time.time() - start_time < duration:
    try:
        if os.path.exists(EVENT_LOG):
            with open(EVENT_LOG, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                if len(lines) > last_processed_line:
                    new_lines = lines[last_processed_line:]
                    for line in new_lines:
                        if "HEDGE UP" in line or "HEDGE DOWN" in line:
                            report["hedge_opportunities"] += 1
                        if "TARGET ACQUIRED" in line:
                            report["trades_executed"] += 1
                        if "ERROR" in line or "CRITICAL" in line or "Uncaught exception" in line:
                            report["errors"].append(line.strip())
                    last_processed_line = len(lines)
        
        # Save intermediate report
        with open(REPORT_FILE, 'w') as f:
            json.dump(report, f, indent=4)
            
    except Exception as e:
        print(f"Monitor error: {e}")
    
    time.sleep(10) # Poll every 10s

print("✅ MONITORING COMPLETE")
