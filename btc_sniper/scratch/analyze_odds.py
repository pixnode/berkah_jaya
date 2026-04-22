
import csv
import re

file_path = r'c:\Users\Razer\OneDrive\Desktop\BERKAH JAYA\btc_sniper\output\event_log_2026-04-21.csv'
count_01_05 = 0
total_odds_events = 0
odds_list = []

try:
    with open(file_path, mode='r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            details = row.get('details', '')
            # Mencari pola ask=0.XXX
            match = re.search(r'ask=([0-9.]+)', details)
            if match:
                odds = float(match.group(1))
                total_odds_events += 1
                odds_list.append(odds)
                if 0.01 <= odds <= 0.50:
                    count_01_05 += 1

    print(f"Total kejadian Odds terdeteksi: {total_odds_events}")
    print(f"Jumlah Odds di rentang 0.01 - 0.50: {count_01_05}")
    if total_odds_events > 0:
        print(f"Persentase: {(count_01_05/total_odds_events)*100:.2f}%")
        
    # Distribusi detail
    print("\nDistribusi Odds (Top 5):")
    from collections import Counter
    dist = Counter([round(o, 2) for o in odds_list if 0.01 <= o <= 0.50])
    for val, count in dist.most_common(5):
        print(f"Odds {val:.2f}: {count} kali")

except Exception as e:
    print(f"Error: {e}")
