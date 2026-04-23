import random
from dataclasses import dataclass
from typing import List, Dict, Optional

import os
import sys
from dotenv import dotenv_values

env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
env_dict = dotenv_values(env_path)

# Constants for simulation
NUM_WINDOWS = 1000
STARTING_BALANCE = 100.0
BASE_BET = 1.0

# Strategy configs (loaded from .env)
DIRECTIONAL_MAX_ODDS = float(env_dict.get('DIRECTIONAL_MAX_ODDS', 0.65))
SMART_HEDGE_PAIR_MAX = float(env_dict.get('SMART_HEDGE_PAIR_MAX', 0.95))
TEMPORAL_MAX_SINGLE_ODDS = float(env_dict.get('TEMPORAL_MAX_SINGLE_ODDS', 0.50))
TEMPORAL_MAX_TOTAL_COST = float(env_dict.get('TEMPORAL_MAX_TOTAL_COST', 0.95))

@dataclass
class WindowData:
    id: int
    resolution: str  # "UP" or "DOWN"
    # Odds simulated at different timestamps (T-240, T-180, T-120, T-60)
    up_odds_history: List[float]
    down_odds_history: List[float]
    signal_direction: str  # "UP" or "DOWN"
    signal_strength: float # 0.0 to 1.0

def generate_market_data(num_windows: int) -> List[WindowData]:
    windows = []
    for i in range(num_windows):
        resolution = random.choice(["UP", "DOWN"])
        
        # Simulate realistic odds paths
        # If UP wins, UP odds should generally trend towards 0.99
        # If DOWN wins, DOWN odds should generally trend towards 0.99
        up_odds_history = []
        down_odds_history = []
        
        # Initial odds
        base_up = random.uniform(0.40, 0.60)
        
        for step in range(4): # 4 snapshots per window
            noise = random.uniform(-0.05, 0.05)
            if resolution == "UP":
                current_up = min(0.99, max(0.01, base_up + (step * 0.1) + noise))
            else:
                current_up = min(0.99, max(0.01, base_up - (step * 0.1) + noise))
                
            # Simulate spread (pair cost usually 1.00 - 1.04)
            spread = random.uniform(0.0, 0.04)
            current_down = min(0.99, max(0.01, 1.0 - current_up + spread))
            
            up_odds_history.append(round(current_up, 3))
            down_odds_history.append(round(current_down, 3))

        # Generate a signal that is ~60% accurate
        signal_direction = resolution if random.random() < 0.60 else ("DOWN" if resolution == "UP" else "UP")
        signal_strength = random.uniform(0.5, 1.0)
        
        windows.append(WindowData(
            id=i, resolution=resolution, 
            up_odds_history=up_odds_history, down_odds_history=down_odds_history,
            signal_direction=signal_direction, signal_strength=signal_strength
        ))
    return windows

class Backtester:
    def __init__(self, data: List[WindowData]):
        self.data = data
        self.results = {
            "DIRECTIONAL": {"trades": 0, "wins": 0, "cost": 0.0, "revenue": 0.0},
            "SMART_HEDGE": {"trades": 0, "wins": 0, "cost": 0.0, "revenue": 0.0},
            "TEMPORAL_HEDGE": {"trades": 0, "wins": 0, "cost": 0.0, "revenue": 0.0},
        }

    def run_directional(self):
        """Buys the signal direction if odds <= DIRECTIONAL_MAX_ODDS"""
        res = self.results["DIRECTIONAL"]
        for w in self.data:
            trade_made = False
            for up, down in zip(w.up_odds_history, w.down_odds_history):
                # The bot only buys if the odds are cheap (<=0.40). 
                # This means we only trade when our signal says "UP" but the market prices it at <= 0.40
                if w.signal_direction == "UP" and up <= DIRECTIONAL_MAX_ODDS:
                    res["trades"] += 1
                    res["cost"] += up * BASE_BET
                    if w.resolution == "UP":
                        res["wins"] += 1
                        res["revenue"] += 1.0 * BASE_BET
                    trade_made = True
                    break
                elif w.signal_direction == "DOWN" and down <= DIRECTIONAL_MAX_ODDS:
                    res["trades"] += 1
                    res["cost"] += down * BASE_BET
                    if w.resolution == "DOWN":
                        res["wins"] += 1
                        res["revenue"] += 1.0 * BASE_BET
                    trade_made = True
                    break
            if trade_made: continue

    def run_smart_hedge(self):
        """Buys both sides instantly ONLY if pair_cost <= SMART_HEDGE_PAIR_MAX"""
        res = self.results["SMART_HEDGE"]
        for w in self.data:
            for up, down in zip(w.up_odds_history, w.down_odds_history):
                pair_cost = up + down
                if pair_cost <= SMART_HEDGE_PAIR_MAX:
                    res["trades"] += 1
                    res["cost"] += pair_cost * BASE_BET
                    res["wins"] += 1  # Always wins 1 side
                    res["revenue"] += 1.0 * BASE_BET
                    break

    def run_temporal_hedge(self):
        """Buys cheapest side first, then buys the other if total cost <= TEMPORAL_MAX_TOTAL_COST"""
        res = self.results["TEMPORAL_HEDGE"]
        for w in self.data:
            cost = 0.0
            has_up = False
            has_down = False
            
            for up, down in zip(w.up_odds_history, w.down_odds_history):
                # Try UP
                if not has_up and up <= TEMPORAL_MAX_SINGLE_ODDS:
                    if cost + up <= TEMPORAL_MAX_TOTAL_COST:
                        cost += up
                        has_up = True
                
                # Try DOWN
                if not has_down and down <= TEMPORAL_MAX_SINGLE_ODDS:
                    if cost + down <= TEMPORAL_MAX_TOTAL_COST:
                        cost += down
                        has_down = True
                        
                if has_up and has_down:
                    break
                    
            if has_up or has_down:
                res["trades"] += 1
                res["cost"] += cost * BASE_BET
                
                if (has_up and w.resolution == "UP") or (has_down and w.resolution == "DOWN"):
                    res["wins"] += 1
                    res["revenue"] += 1.0 * BASE_BET

    def print_results(self):
        print("="*65)
        print(f" BACKTEST RESULTS — {NUM_WINDOWS} Simulated Windows")
        print("="*65)
        print(f"{'Strategy':<18} | {'Trades':<6} | {'Win%':<6} | {'P&L ($)':<8} | {'Avg ROI':<8}")
        print("-" * 65)
        
        for name, metrics in self.results.items():
            trades = metrics["trades"]
            wins = metrics["wins"]
            cost = metrics["cost"]
            rev = metrics["revenue"]
            
            win_pct = (wins / trades * 100) if trades > 0 else 0
            pnl = rev - cost
            roi = (pnl / cost * 100) if cost > 0 else 0
            
            print(f"{name:<18} | {trades:<6} | {win_pct:>5.1f}% | {pnl:>+8.2f} | {roi:>+7.1f}%")
        print("="*65)


if __name__ == "__main__":
    print(f"Generating {NUM_WINDOWS} windows of historical data...")
    data = generate_market_data(NUM_WINDOWS)
    
    tester = Backtester(data)
    tester.run_directional()
    tester.run_smart_hedge()
    tester.run_temporal_hedge()
    
    tester.print_results()
