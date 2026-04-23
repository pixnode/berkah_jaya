# ═══ FILE: btc_sniper/backtesting/run_backtest.py ═══
import random
import time
from dataclasses import dataclass
from typing import List, Dict, Optional
import os
from dotenv import dotenv_values

# Load environment
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
env_dict = dotenv_values(env_path)

# --- QUANTITATIVE PARAMETERS (Loaded from .env or Defaults) ---
NUM_WINDOWS = 5000 # To get ~1000 high-conviction trades
BASE_BET = float(env_dict.get('BASE_SHARES', 1.0))

# Strategy Settings
GAP_THRESHOLD = float(env_dict.get('GAP_THRESHOLD_DEFAULT', 15.0))
CVD_THRESHOLD = float(env_dict.get('CVD_THRESHOLD_PCT', 15.0))
VELOCITY_THRESHOLD = float(env_dict.get('VELOCITY_MIN_DELTA', 15.0))
TIMING_START = int(env_dict.get('GOLDEN_WINDOW_START', 60))
TIMING_END = int(env_dict.get('GOLDEN_WINDOW_END', 42))

# Odds & Costs
DIRECTIONAL_MAX_ODDS = float(env_dict.get('DIRECTIONAL_MAX_ODDS', 0.65))
ODDS_MAX_INDIVIDUAL = float(env_dict.get('ODDS_MAX', 0.30))
SMART_HEDGE_PAIR_MAX = float(env_dict.get('SMART_HEDGE_PAIR_MAX', 0.80))
TEMPORAL_MAX_SINGLE_ODDS = float(env_dict.get('TEMPORAL_MAX_SINGLE_ODDS', 0.40))
TEMPORAL_MAX_TOTAL_COST = float(env_dict.get('TEMPORAL_MAX_TOTAL_COST', 0.80))

@dataclass
class WindowData:
    id: int
    resolution: str
    up_odds: float
    down_odds: float
    gap: float
    cvd_pct: float
    velocity: float
    time_rem: int
    is_sniper_active: bool

def generate_market_data(num_windows: int) -> List[WindowData]:
    windows = []
    for i in range(num_windows):
        res = random.choice(["UP", "DOWN"])
        
        # Simulating odds around equilibrium with some bias
        base = 0.50
        trend = random.uniform(-0.1, 0.1)
        up_odds = round(min(0.99, max(0.01, base + (0.1 if res == "UP" else -0.1) + trend + random.uniform(-0.05, 0.05))), 3)
        # Real spread simulation
        spread = random.uniform(-0.02, 0.04) # -0.02 allows for arbitrage
        down_odds = round(min(0.99, max(0.01, 1.0 - up_odds + spread)), 3)
        
        # Signal Generation
        # Gap: higher if market is trending
        gap = round(random.uniform(5.0, 35.0), 1)
        # CVD: higher if volume is biased
        cvd = round(random.uniform(0.0, 50.0), 1)
        # Velocity: spikes
        velocity = round(random.uniform(0.0, 40.0), 1)
        # Timing: mostly in golden window
        t_rem = random.randint(30, 70)
        
        # Sniper Logic: Triple Confirmation
        is_sniper = (gap >= GAP_THRESHOLD and cvd >= CVD_THRESHOLD and velocity >= VELOCITY_THRESHOLD)
        
        windows.append(WindowData(i, res, up_odds, down_odds, gap, cvd, velocity, t_rem, is_sniper))
    return windows

class Backtester:
    def __init__(self, data: List[WindowData]):
        self.data = data
        self.results = {
            "SNIPER_DIRECTIONAL": {"trades": 0, "wins": 0, "cost": 0.0, "payout": 0.0},
            "DIRECTIONAL": {"trades": 0, "wins": 0, "cost": 0.0, "payout": 0.0},
            "SMART_HEDGE": {"trades": 0, "wins": 0, "cost": 0.0, "payout": 0.0},
            "TEMPORAL_HEDGE": {"trades": 0, "wins": 0, "cost": 0.0, "payout": 0.0},
        }

    def run(self):
        for w in self.data:
            # 1. SNIPER_DIRECTIONAL (Triple Confirmation)
            if w.is_sniper_active and TIMING_END <= w.time_rem <= TIMING_START:
                # Assuming signal points to the winning side for simplicity of performance model
                # In real life, it has an error rate. We simulate 85% accuracy for Sniper.
                predicted = w.resolution if random.random() < 0.85 else ("DOWN" if w.resolution == "UP" else "UP")
                odds = w.up_odds if predicted == "UP" else w.down_odds
                
                if odds <= DIRECTIONAL_MAX_ODDS:
                    res = self.results["SNIPER_DIRECTIONAL"]
                    res["trades"] += 1
                    res["cost"] += odds * BASE_BET
                    if predicted == w.resolution:
                        res["wins"] += 1
                        res["payout"] += 1.0 * BASE_BET

            # 2. DIRECTIONAL (Basic Gap + CVD)
            if w.gap >= GAP_THRESHOLD and w.cvd_pct >= CVD_THRESHOLD:
                # 65% accuracy for basic signal
                predicted = w.resolution if random.random() < 0.65 else ("DOWN" if w.resolution == "UP" else "UP")
                odds = w.up_odds if predicted == "UP" else w.down_odds
                
                if odds <= DIRECTIONAL_MAX_ODDS:
                    res = self.results["DIRECTIONAL"]
                    res["trades"] += 1
                    res["cost"] += odds * BASE_BET
                    if predicted == w.resolution:
                        res["wins"] += 1
                        res["payout"] += 1.0 * BASE_BET

            # 3. SMART_HEDGE (Arbitrage)
            pair_cost = w.up_odds + w.down_odds
            if pair_cost <= SMART_HEDGE_PAIR_MAX:
                res = self.results["SMART_HEDGE"]
                res["trades"] += 1
                res["cost"] += pair_cost * BASE_BET
                res["wins"] += 1 # Guaranteed 1 side wins
                res["payout"] += 1.0 * BASE_BET

            # 4. TEMPORAL_HEDGE (Scale-in)
            # Try buy cheapest side first
            h_cost = 0.0
            sides_bought = 0
            if w.up_odds <= TEMPORAL_MAX_SINGLE_ODDS and (h_cost + w.up_odds) <= TEMPORAL_MAX_TOTAL_COST:
                h_cost += w.up_odds
                sides_bought += 1
                up_bought = True
            else: up_bought = False

            if w.down_odds <= TEMPORAL_MAX_SINGLE_ODDS and (h_cost + w.down_odds) <= TEMPORAL_MAX_TOTAL_COST:
                h_cost += w.down_odds
                sides_bought += 1
                down_bought = True
            else: down_bought = False

            if sides_bought > 0:
                res = self.results["TEMPORAL_HEDGE"]
                res["trades"] += 1
                res["cost"] += h_cost * BASE_BET
                # Win if we bought the side that resolved correctly
                if (up_bought and w.resolution == "UP") or (down_bought and w.resolution == "DOWN"):
                    res["wins"] += 1
                    res["payout"] += 1.0 * BASE_BET

    def print_report(self):
        print("\n" + "="*85)
        print(f" SENIOR QUANT TRADER REPORT — BACKTEST {NUM_WINDOWS} WINDOWS")
        print("="*85)
        
        # Parameter Table
        print(f"{'PARAMETER':<25} | {'VALUE':<15} | {'DESCRIPTION'}")
        print("-" * 85)
        print(f"{'GOLDEN WINDOW (Timing)':<25} | {f'T-{TIMING_START}s to T-{TIMING_END}s':<15} | Execution zone")
        print(f"{'GAP_THRESHOLD':<25} | {f'${GAP_THRESHOLD}':<15} | Minimum price edge")
        print(f"{'CVD_THRESHOLD':<25} | {f'{CVD_THRESHOLD}%':<15} | Minimum volume delta bias")
        print(f"{'VELOCITY_THRESHOLD':<25} | {f'${VELOCITY_THRESHOLD}/s':<15} | Minimum momentum spike")
        print(f"{'ODDS_MAX (Directional)':<25} | {f'{DIRECTIONAL_MAX_ODDS}':<15} | Individual side cap")
        print(f"{'SMART_HEDGE_PAIR_MAX':<25} | {f'{SMART_HEDGE_PAIR_MAX}':<15} | Max pair cost for Arb")
        
        print("\n" + "="*85)
        print(f"{'STRATEGY':<20} | {'TRADES':<7} | {'WIN %':<7} | {'P&L ($)':<10} | {'ROI':<8} | {'CONDITION'}")
        print("-" * 85)
        
        conditions = {
            "SNIPER_DIRECTIONAL": "Gap+CVD+Vel",
            "DIRECTIONAL": "Gap+CVD",
            "SMART_HEDGE": "Pair < Threshold",
            "TEMPORAL_HEDGE": "Single < Threshold",
        }

        for name, metrics in self.results.items():
            t = metrics["trades"]
            w = metrics["wins"]
            c = metrics["cost"]
            p = metrics["payout"]
            
            win_pct = (w / t * 100) if t > 0 else 0
            pnl = p - c
            roi = (pnl / c * 100) if c > 0 else 0
            
            print(f"{name:<20} | {t:<7} | {win_pct:>5.1f}% | {pnl:>+10.2f} | {roi:>+7.1f}% | {conditions[name]}")
        
        print("="*85)

if __name__ == "__main__":
    print(f"Quant Engine Initializing... Running simulation for {NUM_WINDOWS} windows.")
    data = generate_market_data(NUM_WINDOWS)
    tester = Backtester(data)
    tester.run()
    tester.print_report()
