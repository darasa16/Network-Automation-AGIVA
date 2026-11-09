with open('static/js/dashboard.js', 'r', encoding='utf-8') as f:
    dj = f.read()

replacements_dj = [
    ('// Pulihkan data tabel dan KPI dari cache jika belum terisi', '// Restore table data and KPIs from cache if not yet populated'),
    ('// Bersihkan service worker agar browser tetap normal menampilkan layar koneksi terputus saat app.py mati', '// Clear service worker so browser displays standard disconnected screen when app.py terminates'),
    ('// Validasi apakah data awal memiliki titik valid', '// Validate whether initial data contains valid datapoints'),
    ('// Ambil data chart terakhir dari localStorage atau fallback', '// Retrieve latest chart data from localStorage or fallback'),
    ('// Hitung skala dinamis SEBELUM new Chart dibuat agar tidak terjadi glitch "sempet lewat / mentok di atas" saat refresh', '// Calculate dynamic scale BEFORE creating new Chart to prevent visual glitches during refresh'),
    ('// Terapkan data awal langsung dengan skala dinamis identik dengan device_detail.js', '// Apply initial data immediately with dynamic scale identical to device_detail.js'),
    ('// Segera render dari cache agar transisi instan dan tidak blank jika offline', '// Immediately render from cache for instant transitions without blanks when offline'),
    ('// Jika mode live: sembunyikan navigator, render seluruh data live', '// If live mode: hide navigator, render all live data'),
    ('// Sinkronisasi dengan slider traffic', '// Synchronize with traffic slider'),
    ('// Sinkronisasi dengan slider CPU', '// Synchronize with CPU slider'),
    ('// 1. CPU & Memory Chart (Standar Baku 100%, Dinamis jika tembus > 100%)', '// 1. CPU & Memory Chart (Default 100%, Dynamic if > 100%)'),
    ('// 2. Network Interface Traffic Chart (Standar Baku 100 Mbps, Dinamis jika tembus > 100 Mbps)', '// 2. Network Interface Traffic Chart (Default 100 Mbps, Dynamic if > 100 Mbps)'),
    ('// Server backend offline / down: terapkan data & grafik terakhir yang tersimpan', '// Backend server offline/down: apply latest saved data & charts'),
    ('// Ambil data dan grafik terakhir dari cache lokal', '// Retrieve latest data and charts from local cache'),
    ('// Kunci urutan permanen berdasarkan device_id (1, 2, 3) agar tidak pernah loncat', '// Permanent sort order by device_id (1, 2, 3) to prevent row jumping'),
    ('SOP PT AGIVA: Acknowledge (ACK) Alert via Web dinonaktifkan secara ketat.', 'SOP PT AGIVA: Alert Acknowledge (ACK) via Web is strictly disabled.'),
    ('Acknowledge HANYA boleh dilakukan oleh petugas melalui Telegram Bot: /ack <alert_id>', 'Acknowledge must ONLY be performed by authorized engineers via Telegram Bot: /ack <alert_id>'),
    ('// Status UP atau DOWN dihilangkan pada search bar dropdown', '// UP or DOWN status omitted in search bar dropdown'),
]

for old, new in replacements_dj:
    dj = dj.replace(old, new)

with open('static/js/dashboard.js', 'w', encoding='utf-8') as f:
    f.write(dj)
print('Updated static/js/dashboard.js')

with open('static/js/device_detail.js', 'r', encoding='utf-8') as f:
    ddj = f.read()

replacements_ddj = [
    ('// 6 Main Chart & Visual instances (Model 1: 3 baris x 2 panel)', '// 6 Main Chart & Visual instances (Model 1: 3 rows x 2 panels)'),
    ('// Pulihkan dari cache jika ada agar instan dan tidak kosong saat app.py mati', '// Restore from cache if available for instant display when app.py terminates'),
    ('// Sinkronisasi Tabel Port dengan Siklus Log 2 Menit Terbaru', '// Synchronize Port Table with Latest 2-Minute Log Cycle'),
    ('// Pastikan fallback array terisi bila kosong', '// Ensure fallback array is populated if empty'),
    ('// Jika mode live: sembunyikan semua 6 navigator slider, render seluruh data live', '// If live mode: hide all 6 navigator sliders, render all live data'),
    ('// Mode histori: 1h, 12h, 24h -> Inisialisasi 6 Timeline Navigators jika belum dibuat', '// Historical mode: 1h, 12h, 24h -> Initialize 6 Timeline Navigators if not yet created'),
    ('// Pertahankan batas pecahan jendela aktif jika pengguna sedang menyeret slider', '// Preserve active window boundaries if user is dragging slider'),
]

for old, new in replacements_ddj:
    ddj = ddj.replace(old, new)

with open('static/js/device_detail.js', 'w', encoding='utf-8') as f:
    f.write(ddj)
print('Updated static/js/device_detail.js')

