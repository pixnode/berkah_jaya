# 📘 Panduan Operasi: Polymarket BTC Sniper v2.3

Dokumen ini berisi instruksi cara menjalankan, memantau, dan mengelola bot di server VPS menggunakan **PM2** dan **UI Viewer**.

---

## 🚀 1. Cara Menjalankan Bot (Background)

Bot berjalan di background menggunakan PM2 agar tetap aktif 24/7 meskipun terminal ditutup.

**Langkah pertama (Update Kode):**
```bash
git pull
```

**Menjalankan Bot:**
```bash
pm2 start ecosystem.config.js
```

**Memastikan Bot Berjalan Saat Server Restart:**
```bash
pm2 save
pm2 startup
```

---

## 📊 2. Cara Memantau Dashboard (Visual)

Karena bot berjalan di background, Anda bisa menggunakan skrip **UI Viewer** untuk melihat grafik CVD, Gap Harga, dan status Safety Gates secara visual.

**Jalankan Viewer:**
```bash
python btc_sniper/scripts/ui_viewer.py
```
*   *Gunakan `Ctrl+C` untuk keluar dari viewer. Bot utama di background TIDAK akan mati.*

---

## 📜 3. Cara Membaca Log (Audit Teks)

Jika Anda ingin melihat detail teknis atau pesan error dari bot:

**Melihat Log Real-time:**
```bash
pm2 logs btc-sniper
```

**Melihat 50 baris terakhir:**
```bash
pm2 logs btc-sniper --lines 50
```

---

## 🛠️ 4. Perintah Manajemen PM2

| Perintah | Deskripsi |
| :--- | :--- |
| `pm2 list` | Melihat status bot (Online/Offline, RAM, CPU) |
| `pm2 restart btc-sniper` | Merestart bot (Wajib dilakukan setelah `git pull`) |
| `pm2 stop btc-sniper` | Menghentikan bot sementara |
| `pm2 delete btc-sniper` | Menghapus bot dari daftar PM2 |
| `pm2 monit` | Dashboard monitoring bawaan PM2 (CPU/RAM) |

---

## ⚠️ 5. Penjelasan Status Dashboard

*   **[INIT]**: Bot baru menyala, sedang menunggu data pertama masuk (Grace Period 30 detik).
*   **[ARMed]**: Bot sudah siap, data valid, sedang menunggu waktu eksekusi (T-48s).
*   **[EXECUTE]**: Jendela eksekusi terbuka. Bot akan menembak jika semua Safety Gates berwarna **GREEN (PASS)**.
*   **[LOCKDOWN]**: Keamanan aktif! Bot berhenti trading karena alasan tertentu (misal: koneksi lambat atau rugi beruntun). Akan terbuka otomatis dalam 30 detik jika kondisi normal.

---

## 📁 6. Lokasi File Penting

*   **Log Transaksi**: `output/trade_log.csv`
*   **Log Kejadian**: `output/event_log.csv`
*   **Snapshot State**: `output/dashboard_ui.json` (Digunakan oleh Viewer)
*   **PM2 Output**: `output/pm2-out.log`
