
import csv
import collections

file_path = r'c:\Users\Razer\OneDrive\Desktop\BERKAH JAYA\btc_sniper\output\trade_log_2026-04-21.csv'

# Group by window_id
windows = collections.defaultdict(list)

try:
    with open(file_path, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            windows[row['window_id']].append({
                'side': row['side'],
                'cost': float(row['cost_usdc']),
                'odds': float(row['entry_odds'])
            })

    total_cost = 0
    guaranteed_payout = 0
    total_trades = 0

    print(f"{'Window ID':<30} | {'Status':<15} | {'Cost':<10} | {'Max Payout':<10} | {'Profit':<10}")
    print("-" * 85)

    for win_id, trades in windows.items():
        sides = [t['side'] for t in trades]
        cost = sum(t['cost'] for t in trades)
        total_cost += cost
        total_trades += len(trades)
        
        payout = 0
        status = ""
        
        if 'UP' in sides and 'DOWN' in sides:
            # HEDGE SUCCESS: One side definitely wins 1.0
            payout = 1.0
            guaranteed_payout += payout
            status = "HEDGED (Win)"
        else:
            # Only one side bought
            payout = 0 # We don't assume win if not hedged
            status = f"SINGLE ({sides[0]})"
            
        profit = payout - cost
        print(f"{win_id:<30} | {status:<15} | ${cost:<9.3f} | ${payout:<9.2f} | ${profit:<9.3f}")

    print("-" * 85)
    print(f"Total Trades: {total_trades}")
    print(f"Total Modal (Cost): ${total_cost:.3f}")
    print(f"Guaranteed Payout (Hedged Only): ${guaranteed_payout:.2f}")
    print(f"NETT PnL (Confirmed): ${guaranteed_payout - total_cost:.3f}")
    
except Exception as e:
    print(f"Error: {e}")
