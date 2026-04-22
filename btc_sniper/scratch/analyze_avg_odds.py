
import csv

file_path = r'c:\Users\Razer\OneDrive\Desktop\BERKAH JAYA\btc_sniper\output\trade_log_2026-04-21.csv'

try:
    odds_up = []
    odds_down = []
    all_odds = []

    with open(file_path, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            odds = float(row['entry_odds'])
            side = row['side']
            all_odds.append(odds)
            if side == 'UP':
                odds_up.append(odds)
            elif side == 'DOWN':
                odds_down.append(odds)

    if all_odds:
        avg_all = sum(all_odds) / len(all_odds)
        avg_up = sum(odds_up) / len(odds_up) if odds_up else 0
        avg_down = sum(odds_down) / len(odds_down) if odds_down else 0
        
        print(f"--- RATA-RATA ODDS (AVERAGE ODDS) ---")
        print(f"Rata-rata Gabungan : {avg_all:.3f}")
        print(f"Rata-rata Sisi UP  : {avg_up:.3f}")
        print(f"Rata-rata Sisi DOWN: {avg_down:.3f}")
        print(f"Odds Terendah      : {min(all_odds):.3f}")
        print(f"Odds Tertinggi     : {max(all_odds):.3f}")
    else:
        print("Tidak ada data odds.")
        
except Exception as e:
    print(f"Error: {e}")
