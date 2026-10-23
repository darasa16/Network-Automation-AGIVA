"""
=============================================================================
PT AGIVA INDONESIA - NETWORK OPERATIONS AUTOMATION
Sentralisasi Logging Standar Python dengan RotatingFileHandler
=============================================================================
Spesifikasi:
1. Modul logging bawaan Python (INFO, WARNING, ERROR).
2. Rotasi file otomatis lewat RotatingFileHandler (5 MB per file, 5 backup).
3. Logging konsol & file tersinkronisasi.
4. Hook fail-safe pengiriman ringkasan error kritis ke Telegram.
=============================================================================
"""

import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime

LOG_DIR = os.path.join(os.path.dirname(__file__), 'logs')
LOG_FILE = os.path.join(LOG_DIR, 'agiva_noc.log')

# Pastikan folder logs tersedia
os.makedirs(LOG_DIR, exist_ok=True)

# Format log terstandar
LOG_FORMAT = '%(asctime)s [%(levelname)s] [%(name)s]: %(message)s'
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

_INITIALIZED = False
_LAST_CRITICAL_TG_TIME = 0  # Timestamp pengiriman error kritis terakhir untuk throttling (anti-spam)

def get_configured_logger(name="AgivaNOC", level=logging.INFO):
    """
    Mengembalikan instance logger dengan StreamHandler (konsol) dan
    RotatingFileHandler (rotasi file otomatis).
    """
    global _INITIALIZED
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Hindari duplikasi handler jika sudah diinisialisasi
    if not logger.handlers:
        formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

        # 1. Console / Stream Handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        # 2. Rotating File Handler (5 MB per file, max 5 file cadangan)
        try:
            file_handler = RotatingFileHandler(
                LOG_FILE,
                maxBytes=5 * 1024 * 1024,  # 5 MB
                backupCount=5,
                encoding='utf-8'
            )
            file_handler.setLevel(level)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except Exception as e:
            logger.warning(f"Tidak dapat membuat RotatingFileHandler pada {LOG_FILE}: {e}")

    return logger

def log_and_telegram_critical_error(logger_instance, error_message, module_name="System"):
    """
    Mencatat log ERROR kritis ke file rotasi dan opsional mengirimkan ringkasan ke Telegram grup NOC
    dengan batasan jeda (throttling) minimal 60 detik agar tidak membanjiri grup Telegram.
    """
    import time
    global _LAST_CRITICAL_TG_TIME

    logger_instance.error(f"[{module_name}] {error_message}")

    now_ts = time.time()
    # Throttling: kirim ringkasan ke Telegram maksimal 1 kali per 60 detik untuk error sejenis
    if now_ts - _LAST_CRITICAL_TG_TIME > 60:
        _LAST_CRITICAL_TG_TIME = now_ts
        try:
            from rule_engine import send_telegram_broadcast
            tg_text = (
                f"⚠️ <b>[NOC AGIVA - CRITICAL SYSTEM LOG]</b> ⚠️\n\n"
                f"📌 <b>Modul:</b> {module_name}\n"
                f"📌 <b>Level:</b> ERROR\n"
                f"📌 <b>Waktu:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} WIB\n"
                f"📌 <b>Pesan:</b> <code>{str(error_message)[:180]}</code>\n\n"
                f"<i>Log lengkap tersimpan di file rotasi agiva_noc.log.</i>"
            )
            send_telegram_broadcast(tg_text, parse_mode='HTML')
        except Exception:
            pass  # Jangan pernah membiarkan kegagalan kirim error Telegram mematikan proses utama
