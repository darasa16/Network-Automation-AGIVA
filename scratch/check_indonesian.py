import os, sys, re

# Set stdout encoding
sys.stdout.reconfigure(encoding='utf-8')

# Search for Indonesian words in templates, static/js, and app.py
indonesian_keywords = [
    'daftar', 'akun', 'resmi', 'memiliki', 'keseluruhan', 'akses', 'dimuat', 'baris',
    'halaman', 'cari', 'tambah', 'ubah', 'simpan', 'riwayat', 'berhasil', 'gagal',
    'tidak', 'tombol', 'tutup', 'pengguna', 'kata', 'sandi', 'masukkan', 'silahkan',
    'silakan', 'peringatan', 'perangkat', 'catatan', 'keterangan', 'batal', 'hapus',
    'apakah', 'yakin', 'ingin', 'menghapus', 'kembali', 'pesan', 'waktu', 'judul',
    'terakhir', 'semua', 'pilih', 'tindakan', 'rincian', 'unduh', 'salin', 'sebelumnya',
    'selanjutnya', 'menampilkan', 'kosong', 'masuk', 'keluar', 'ingat', 'saya',
    'sedang', 'proses', 'kesalahan', 'terjadi', 'sukses', 'koneksi', 'terputus',
    'terhubung', 'laporan', 'harian', 'mingguan', 'bulanan', 'jaringan', 'pemantauan',
    'antara', 'oleh', 'karena', 'jika', 'untuk', 'dengan', 'pada', 'adalah', 'diselaraskan',
    'kecualikan', 'standarisasi', 'standar'
]

pattern = re.compile(r'\b(' + '|'.join(indonesian_keywords) + r')\b', re.IGNORECASE)

files_to_check = []
for root, dirs, files in os.walk('templates'):
    for f in files:
        if f.endswith(('.html', '.js')):
            files_to_check.append(os.path.join(root, f))

for root, dirs, files in os.walk('static/js'):
    for f in files:
        if f.endswith('.js'):
            files_to_check.append(os.path.join(root, f))

for path in files_to_check:
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        for idx, line in enumerate(f, 1):
            matches = pattern.findall(line)
            # Filter out English words that might match (like 'an', 'in', etc. though our list doesn't have them)
            if matches:
                print(f"{path}:{idx}: [{', '.join(set(matches))}] -> {line.strip()[:140]}")

