import os, sys, re

# 1. Update templates/telegram.html
with open('templates/telegram.html', 'r', encoding='utf-8') as f:
    tg = f.read()

# Replace whitelist subtext
tg = re.sub(
    r'<span class="panel-sub">Daftar akun Telegram resmi yang memiliki keseluruhan akses command\s*bot</span>',
    '<span class="panel-sub">Official Telegram accounts authorized with full administrative and operational command access</span>',
    tg
)
tg = tg.replace('<!-- Dimuat dinamis via JavaScript dengan Paginasi -->', '<!-- Loaded dynamically via JavaScript with pagination -->')
tg = tg.replace('<!-- Dimuat otomatis via JavaScript dengan Paginasi 20 baris/halaman -->', '<!-- Loaded automatically via JavaScript with 20 rows/page pagination -->')
tg = tg.replace('/* Khusus Pagination Whitelist di Dual-Panel agar rapi satu baris & tidak pecah */', '/* Whitelist Pagination styling in Dual-Panel layout */')
tg = tg.replace('/* Standarisasi Font Inter (Sans-serif) untuk Kolom Tabel Riwayat Telegram */', '/* Standardize Inter (Sans-serif) font for Telegram history table columns */')
tg = tg.replace('/* Kolom Perintah tanpa kotak badge */', '/* Command column without badge box */')
tg = tg.replace('// Tombol Prev (‹ Prev)', '// Prev Button (‹ Prev)')
tg = tg.replace('// Penomoran Halaman dengan format cerdas (1 ... 9 [10] 11 ... 20)', '// Smart pagination formatting (1 ... 9 [10] 11 ... 20)')
tg = tg.replace('// Selalu tampilkan halaman 1', '// Always display page 1')
tg = tg.replace('// Selalu tampilkan halaman terakhir', '// Always display last page')
tg = tg.replace('// Tombol Next (Next ›)', '// Next Button (Next ›)')
tg = tg.replace('// Jalankan render tabel pertama kali saat DOM selesai dimuat', '// Initial table render once DOM is fully loaded')
tg = tg.replace('// Re-render jika hash berubah ke log atau whitelist di halaman berbeda', '// Re-render if hash changes to log or whitelist on different page')
tg = tg.replace('// Auto-refresh telegram logs setiap 5 detik', '// Auto-refresh telegram logs every 5 seconds')

with open('templates/telegram.html', 'w', encoding='utf-8') as f:
    f.write(tg)
print('Updated templates/telegram.html')

# 2. Update templates/backups.html
with open('templates/backups.html', 'r', encoding='utf-8') as f:
    bk = f.read()

bk = bk.replace('/* Label Sub-Site Perangkat (Diselaraskan dengan .neighbor-desc: 11px, var(--text-muted)) */', '/* Device Sub-Site Label (Aligned with .neighbor-desc: 11px, var(--text-muted)) */')
bk = bk.replace('/* Kecualikan badge kategori, status, dan tombol aksi */', '/* Exclude category badge, status, and action buttons */')
bk = bk.replace('/* Hilangkan titik bulat pada badge status */', '/* Remove dot circle on status badge */')
bk = bk.replace('/* Category Filter Buttons - Diselaraskan dengan Desain Filter Tab/Badge AGIVA */', '/* Category Filter Buttons - Aligned with AGIVA Filter Tab/Badge Design */')
bk = bk.replace('// Tombol Prev (‹ Prev)', '// Prev Button (‹ Prev)')
bk = bk.replace('// Penomoran Halaman dengan format cerdas (1 ... 9 [10] 11 ... 20)', '// Smart pagination formatting (1 ... 9 [10] 11 ... 20)')
bk = bk.replace('// Selalu tampilkan halaman 1', '// Always display page 1')
bk = bk.replace('// Selalu tampilkan halaman terakhir', '// Always display last page')
bk = bk.replace('// Tombol Next (Next ›)', '// Next Button (Next ›)')

with open('templates/backups.html', 'w', encoding='utf-8') as f:
    f.write(bk)
print('Updated templates/backups.html')

# 3. Update templates/alerts.html
with open('templates/alerts.html', 'r', encoding='utf-8') as f:
    al = f.read()

al = al.replace('/* Standardisasi 100% Font Inter untuk SELURUH elemen kedua tabel */', '/* Standardize 100% Inter Font for ALL elements across both tables */')
al = al.replace('<!-- 1. ACTIVE & SUSTAINED ALERTS TABLE (>= 10 MENIT)          -->', '<!-- 1. ACTIVE & SUSTAINED ALERTS TABLE (>= 10 MINUTES)        -->')
al = al.replace('<!-- 2. INCIDENT HISTORY & COOLDOWN LOG TABLE (RETENSI 30 HARI)-->', '<!-- 2. INCIDENT HISTORY & COOLDOWN LOG TABLE (30-DAY RETENTION)-->')
al = al.replace('<!-- Incidents Table Panel (Tanpa Kolom Message sesuai request) -->', '<!-- Incidents Table Panel (Without Message column as requested) -->')
al = al.replace('// Tombol Prev (‹ Prev)', '// Prev Button (‹ Prev)')
al = al.replace('// Penomoran Halaman dengan format cerdas (1 ... 9 [10] 11 ... 20)', '// Smart pagination formatting (1 ... 9 [10] 11 ... 20)')
al = al.replace('// Tombol Next (Next ›)', '// Next Button (Next ›)')

with open('templates/alerts.html', 'w', encoding='utf-8') as f:
    f.write(al)
print('Updated templates/alerts.html')

# 4. Update templates/device_detail.html
with open('templates/device_detail.html', 'r', encoding='utf-8') as f:
    dd = f.read()

dd = dd.replace('<!-- SEKSI ATAS: BARIS 1 (CPU & Memory + Throughput Uplink) -->', '<!-- TOP SECTION: ROW 1 (CPU & Memory + Uplink Throughput) -->')
dd = dd.replace('<!-- Kotak 1: Real-time CPU & Memory (Dual-Line) -->', '<!-- Box 1: Real-time CPU & Memory (Dual-Line) -->')
dd = dd.replace('<!-- Kotak 2: Throughput Uplink (Dual-Line: Ingress & Egress) -->', '<!-- Box 2: Uplink Throughput (Dual-Line: Ingress & Egress) -->')
dd = dd.replace('<!-- SEKSI BAWAH: BARIS 2 (Buffer Hardware & Integritas Transmisi Fisik) -->', '<!-- BOTTOM SECTION: ROW 2 (Hardware Buffer & Physical Transmission Integrity) -->')
dd = dd.replace('<!-- Kotak 3: Buffer Hardware Switch (Spike Bar Histogram persis Integritas Transmisi Fisik) -->', '<!-- Box 3: Hardware Buffer (Spike Bar Histogram matching Physical Transmission Integrity) -->')
dd = dd.replace('<!-- Kotak 4: Integritas Transmisi Fisik (Spike Bar Histogram) -->', '<!-- Box 4: Physical Transmission Integrity (Spike Bar Histogram) -->')
dd = dd.replace('<!-- SEKSI BAWAH: BARIS 3 (Diagnostik Transmisi ICMP & Kualitas Jaringan) -->', '<!-- BOTTOM SECTION: ROW 3 (ICMP Transmission Diagnostics & Network Quality) -->')
dd = dd.replace('<!-- Kotak 5: Latensi Jaringan (ICMP Ping RTT) -->', '<!-- Box 5: Network Latency (ICMP Ping RTT) -->')
dd = dd.replace('<!-- Kotak 6: Ping Drop / Packet Loss (%) -->', '<!-- Box 6: Packet Loss / Ping Drop (%) -->')

with open('templates/device_detail.html', 'w', encoding='utf-8') as f:
    f.write(dd)
print('Updated templates/device_detail.html')

# 5. Update backup_service.py
with open('backup_service.py', 'r', encoding='utf-8') as f:
    bs = f.read()

bs = bs.replace("raise Exception(f\"Vendor '{device.vendor}' belum didukung.\")", "raise Exception(f\"Vendor '{device.vendor}' is not supported yet.\")")
bs = bs.replace(
    'content = f"// BACKUP ERROR [{now.strftime(\'%Y-%m-%d %H:%M:%S WIB\')}]\\n// Perangkat: {dev_name} ({ip})\\n// Kategori: {category}\\n// Error: {error_msg}\\n"',
    'content = f"// BACKUP ERROR [{now.strftime(\'%Y-%m-%d %H:%M:%S WIB\')}]\\n// Device: {dev_name} ({ip})\\n// Category: {category}\\n// Error: {error_msg}\\n"'
)
old_hdr = """    header_info = (
        f"{'='*70}\\n"
        f"AGIVA NOC RAW SNAPSHOT [{category.upper()}]\\n"
        f"Waktu Eksekusi: {now.strftime('%Y-%m-%d %H:%M:%S WIB')}\\n"
        f"Perangkat     : {dev_name} ({ip})\\n"
        f"Site          : {device.site or '-'}\\n"
        f"Kategori      : {category}\\n"
        f"Pemicu        : {trigger_by}\\n"
        f"{'='*70}\\n\\n"
    )"""

new_hdr = """    header_info = (
        f"{'='*70}\\n"
        f"AGIVA NOC RAW SNAPSHOT [{category.upper()}]\\n"
        f"Execution Time : {now.strftime('%Y-%m-%d %H:%M:%S WIB')}\\n"
        f"Device         : {dev_name} ({ip})\\n"
        f"Site           : {device.site or '-'}\\n"
        f"Category       : {category}\\n"
        f"Triggered By   : {trigger_by}\\n"
        f"{'='*70}\\n\\n"
    )"""

bs = bs.replace(old_hdr, new_hdr)

with open('backup_service.py', 'w', encoding='utf-8') as f:
    f.write(bs)
print('Updated backup_service.py')

