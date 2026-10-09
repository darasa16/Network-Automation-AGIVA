import os
import sys
import html
import random
import hashlib
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from database import db_session
from models import TelegramWhitelist, TelegramMessageLog

# Set terminal encoding to UTF-8
sys.stdout.reconfigure(encoding='utf-8')

# Setup Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("AgivaNOCBot")

load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

primary_chat_id = os.getenv("TELEGRAM_CHAT_ID", "5419251159")
whitelist_raw = os.getenv("WHITELIST_CHAT_IDS", primary_chat_id)
WHITELIST_USERS = [int(cid.strip()) for cid in whitelist_raw.split(",") if cid.strip().isdigit()]

ACTIVE_CHATS = set()
if primary_chat_id and primary_chat_id.strip().isdigit():
    ACTIVE_CHATS.add(int(primary_chat_id.strip()))

# Timezone Helper
def get_current_time_wib() -> str:
    try:
        return datetime.now(ZoneInfo("Asia/Jakarta")).strftime("%Y-%m-%d %H:%M:%S WIB")
    except Exception:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S WIB")

def get_current_date() -> str:
    try:
        return datetime.now(ZoneInfo("Asia/Jakarta")).strftime("%Y-%m-%d")
    except Exception:
        return datetime.now().strftime("%Y-%m-%d")

# ==================== DATA MODEL (LLD SPECIFICATION) ====================
# Simulasi Data Inventaris & Telemetri Perangkat Sesuai Dokumen LLD PT Agiva Indonesia
DEVICES = {
    "RTR-Core-01": {
        "ip": "192.168.1.1",
        "vendor": "Cisco IOS-XE (ISR 4451)",
        "site": "HQ - Cyber 2 Tower (Jakarta)",
        "status": "UP",
        "cpu": 34,
        "mem": 60,
        "uptime": "42 hari, 14 jam",
        "last_backup": "2026-09-29 02:00 WIB",
        "backup_path": "/backups/HQ/RTR-Core-01"
    },
    "SW-Dist-Lt2": {
        "ip": "192.168.1.10",
        "vendor": "MikroTik RouterOS v7 (CRS326)",
        "site": "HQ - Cyber 2 Tower (Jakarta)",
        "status": "UP",
        "cpu": 18,
        "mem": 40,
        "uptime": "15 hari, 06 jam",
        "last_backup": "2026-09-29 02:05 WIB",
        "backup_path": "/backups/HQ/SW-Dist-Lt2"
    },
    "FW-Perimeter": {
        "ip": "10.10.0.1",
        "vendor": "Huawei USG6000V Next-Gen FW",
        "site": "DC - DCI Cibitung (Tier IV)",
        "status": "UP",
        "cpu": 88,
        "mem": 74,
        "uptime": "90 hari, 22 jam",
        "last_backup": "2026-09-29 02:10 WIB",
        "backup_path": "/backups/DC/FW-Perimeter"
    },
    "RTR-Branch-BDG": {
        "ip": "172.16.5.1",
        "vendor": "Cisco IOS (Catalyst 8300)",
        "site": "Branch - Bandung Data Center",
        "status": "DOWN",
        "cpu": 0,
        "mem": 0,
        "uptime": "0 hari (Offline / Link Down)",
        "last_backup": "2026-09-28 02:00 WIB",
        "backup_path": "/backups/Branch-BDG/RTR-Branch-BDG"
    },
}

ALERTS = {
    "101": {
        "id": "ALT-101",
        "device": "RTR-Branch-BDG",
        "severity": "Critical",
        "issue": "Device Unreachable (ICMP Timeout / Loss 100%)",
        "site": "Branch - Bandung Data Center",
        "status": "Open",
        "triggered_at": "2026-09-29 14:15:00 WIB",
        "acknowledged_by": None,
        "acknowledged_at": None
    },
    "102": {
        "id": "ALT-102",
        "device": "FW-Perimeter",
        "severity": "Warning",
        "issue": "Penggunaan CPU Melebihi Batas (88% > 80%)",
        "site": "DC - DCI Cibitung (Tier IV)",
        "status": "Open",
        "triggered_at": "2026-09-29 15:02:10 WIB",
        "acknowledged_by": None,
        "acknowledged_at": None
    }
}

# ==================== FORMATTING & HELPERS ====================

def make_progress_bar(percent: int, length: int = 10) -> str:
    """Membuat visual progress bar telemetri persentase"""
    percent = max(0, min(100, int(percent)))
    filled = int(round((percent / 100) * length))
    return "█" * filled + "░" * (length - filled)

def is_whitelisted(user_id: int) -> bool:
    """Mengecek otorisasi pengguna dalam Whitelist NOC (memory + database)"""
    if user_id in WHITELIST_USERS:
        return True
    try:
        session = db_session()
        entry = session.query(TelegramWhitelist).filter(
            TelegramWhitelist.chat_id == str(user_id),
            TelegramWhitelist.is_active == True
        ).first()
        session.close()
        if entry:
            if user_id not in WHITELIST_USERS:
                WHITELIST_USERS.append(user_id)
            return True
        return False
    except Exception as e:
        logger.error(f"Error checking whitelist DB: {e}")
        return False

def render_access_denied_view(user_id: int, action_name: str) -> str:
    """Pesan keamanan standar enterprise saat akses tidak sah terjadi"""
    return (
        "<b>Akses Ditolak</b>\n\n"
        "Kejadian: Percobaan akses tanpa izin\n"
        f"Perintah: <code>{html.escape(action_name)}</code>\n"
        f"ID Pengguna: <code>{user_id}</code>\n"
        f"Waktu: <code>{get_current_time_wib()}</code>\n\n"
        "Akun Anda tidak terdaftar dalam daftar whitelist.\n"
        "Silahkan hubungi Admin untuk perizinan."
    )

def log_telegram_message(chat_id: str, message_type: str, content: str, status: str = 'SENT', alert_id: int = None):
    """Mencatat setiap pesan / dispatch bot Telegram ke basis data (tabel telegram_message_logs)"""
    try:
        session = db_session()
        log_entry = TelegramMessageLog(
            alert_id=alert_id,
            chat_id=str(chat_id),
            message_type=message_type,
            content=content[:500],
            status=status,
            sent_at=datetime.now()
        )
        session.add(log_entry)
        session.commit()
        session.close()
    except Exception as e:
        logger.error(f"Error logging telegram message to DB: {e}")


# ==================== VIEW BUILDERS (FORMAL CORPORATE TEMPLATES) ====================

def build_status_view() -> str:
    """Tampilan Ringkasan Status NOC"""
    total = len(DEVICES)
    up_count = sum(1 for d in DEVICES.values() if d.get("status", "").upper() == "UP")
    down_count = total - up_count
    active_alerts = [a for a in ALERTS.values() if a.get("status", "").upper() == "OPEN"]
    alert_count = len(active_alerts)
    uptime_ratio = (up_count / total) * 100 if total > 0 else 0

    overall_health = "Normal" if down_count == 0 and alert_count == 0 else ("Peringatan" if down_count > 0 else "Waspada")

    msg = (
        "<b>NETWORK AUTOMATION PT AGIVA INDONESIA</b>\n\n"
        f"Waktu Sistem: <code>{get_current_time_wib()}</code>\n"
        f"Kondisi Jaringan: {overall_health}\n"
        f"Tingkat Ketersediaan: <code>{uptime_ratio:.1f}% Online</code>\n\n"
        "<pre>\n"
        f"Total Perangkat   : {total} Unit\n"
        f"Perangkat Normal  : {up_count} Unit\n"
        f"Perangkat Gangguan: {down_count} Unit\n"
        f"Alert Terbuka     : {alert_count} Kasus\n"
        "</pre>\n"
    )

    if down_count > 0:
        down_devices = [k for k, v in DEVICES.items() if v["status"] == "DOWN"]
        msg += f"Perangkat tidak terjangkau: <code>{', '.join(down_devices)}</code>\n\n"
    else:
        msg += "Seluruh perangkat beroperasi normal.\n\n"

    msg += (
        "Perintah yang tersedia:\n"
        "/devices - Daftar seluruh perangkat\n"
        "/device [nama_perangkat] - Rincian telemetri perangkat\n"
        "/alerts - Daftar gangguan aktif\n"
        "/ack [id_alert] - Konfirmasi penanganan alert\n"
        "/backup [nama_perangkat] - Backup konfigurasi manual\n"
        "/user - Profil & status hak akses akun\n"
        "/help - Panduan operasional lengkap\n"
        "/approve [nama_admin] [role_admin] - (Khusus Admin) Menyetujui akses teknisi baru dengan role pilihan."
    )
    return msg

def build_devices_view() -> str:
    """Tampilan Daftar Inventaris Perangkat"""
    msg = (
        "<b>INVENTARIS PERANGKAT JARINGAN</b>\n\n"
        f"Total Perangkat Terdata : {len(DEVICES)} Unit\n"
        "<pre>\n"
        "NAMA PERANGKAT  VENDOR    STATUS   LOKASI\n"
    )
    for name, dev in DEVICES.items():
        v_short = dev["vendor"].split()[0]
        status_txt = "UP" if dev["status"] == "UP" else "DOWN"
        site_short = dev["site"].split()[0]
        msg += f"{name:<15} {v_short:<9} {status_txt:<8} {site_short}\n"
    msg += "</pre>\n\n"
    msg += "Ketik /device [nama_perangkat] untuk melihat telemetri lengkap. Contoh: /device RTR-Core-01"
    return msg

def build_device_detail_view(device_name: str) -> str:
    """Tampilan Detail Telemetri Satu Perangkat"""
    dev = DEVICES.get(device_name)
    if not dev:
        return (
            "<b>PERANGKAT TIDAK DITEMUKAN</b>\n\n"
            f"Perangkat <code>{html.escape(device_name)}</code> tidak terdaftar dalam inventaris.\n"
            "Gunakan perintah /devices untuk melihat daftar perangkat yang tersedia."
        )

    status_badge = "UP" if dev["status"] == "UP" else "DOWN"
    cpu_val = dev["cpu"]
    mem_val = dev["mem"]

    cpu_bar = make_progress_bar(cpu_val, 10)
    mem_bar = make_progress_bar(mem_val, 10)

    cpu_label = "Kritis" if cpu_val >= 85 else ("Tinggi" if cpu_val >= 70 else "Normal")
    mem_label = "Kritis" if mem_val >= 85 else ("Tinggi" if mem_val >= 70 else "Normal")

    msg = (
        "<b>INFORMASI PERANGKAT\n\n"
        f"Nama Device: {html.escape(device_name)}\n"
        f"Status Operasional: {status_badge}\n"
        f"Alamat IP: <code>{dev['ip']}</code>\n"
        f"Vendor: {dev['vendor']}\n"
        f"Lokasi: {dev['site']}\n"
        f"Waktu Aktif: <code>{dev['uptime']}</code>\n\n"
        "Penggunaan Sumber Daya:\n"
        f"<code>CPU [{cpu_bar}] {cpu_val:>2}% ({cpu_label})</code>\n"
        f"<code>MEM [{mem_bar}] {mem_val:>2}% ({mem_label})</code>\n\n"
        "Manajemen Konfigurasi:\n"
        f"• Backup Terakhir: <code>{dev['last_backup']}</code>\n"
        f"• Jalur Direktori: <code>{dev['backup_path']}</code>\n\n"
        f"Ketik /backup {html.escape(device_name)} untuk melakukan backup konfigurasi manual."
    )
    return msg

def build_alerts_view() -> str:
    """Tampilan Daftar Incident & Alert Aktif"""
    open_alerts = [a for a in ALERTS.values() if a.get("status", "").upper() == "OPEN"]
    ack_alerts = [a for a in ALERTS.values() if a.get("status", "").upper() == "ACKNOWLEDGED"]
    resolved_alerts = [a for a in ALERTS.values() if a.get("status", "").upper() == "RESOLVED"]

    msg = (
        "<b>DAFTAR ALERT JARINGAN</b>\n\n"
        f"Status Antrean: {len(open_alerts)} Terbuka | {len(ack_alerts)} Sedang Ditangani | {len(resolved_alerts)} Selesai\n"
        f"Waktu Data: <code>{get_current_time_wib()}</code>\n\n"
    )

    active_items = {k: v for k, v in ALERTS.items() if v.get("status", "").upper() != "RESOLVED"}

    if not active_items:
        msg += "Tidak ada gangguan aktif saat ini. Seluruh alert berstatus Resolved.\n"
    else:
        for alert_id, alert in active_items.items():
            status_tag = "Open" if alert.get("status", "").upper() == "OPEN" else "In Progress"

            msg += (
                f"<b>[{alert['id']}] {alert['severity']} — {alert['device']}</b>\n"
                f"• Masalah: {alert['issue']}\n"
                f"• Lokasi: {alert['site']}\n"
                f"• Waktu: <code>{alert['triggered_at']}</code>\n"
                f"• Status: {status_tag}\n"
            )
            if alert.get("status", "").upper() == "ACKNOWLEDGED":
                msg += f"• PIC: @{alert.get('acknowledged_by', 'NOC')} (<code>{alert.get('acknowledged_at', '')}</code>)\n"
            msg += "\n"

        msg += (
            "Perintah tindak lanjut:\n"
            "• /ack [id] - Konfirmasi penanganan alert\n"
            "• /resolve [id] - Selesaikan dan pulihkan gangguan"
        )

    return msg

def build_backup_report(device_name: str, operator_name: str) -> str:
    """Laporan Hasil Eksekusi Backup Konfigurasi"""
    dev = DEVICES[device_name]
    today_str = get_current_date()
    backup_file = f"{dev['backup_path']}/{today_str}_config.txt"
    job_id = f"BKP-{datetime.now().strftime('%Y%m%d')}-{random.randint(1000, 9999)}"
    commit_hash = hashlib.sha1(f"{device_name}{datetime.now()}".encode()).hexdigest()[:7]
    dummy_checksum = hashlib.sha256(f"{backup_file}".encode()).hexdigest()[:16]

    return (
        "<b>LAPORAN HASIL BACKUP KONFIGURASI</b>\n\n"
        f"ID Pekerjaan: <code>{job_id}</code>\n"
        f"Perangkat: <code>{device_name}</code> ({dev['ip']})\n"
        f"Vendor: {dev['vendor']}\n"
        f"Operator: @{html.escape(operator_name)}\n"
        f"Waktu Eksekusi: <code>{get_current_time_wib()}</code>\n\n"
        "Rincian Pengarsipan:\n"
        "• Metode Ekstraksi: Netmiko SSH Automated Collector\n"
        f"• Lokasi Berkas:\n  <code>{backup_file}</code>\n"
        "• Ukuran Berkas: 48.6 KB\n"
        f"• Checksum SHA-256: <code>{dummy_checksum}...</code>\n"
        f"• Version Control: Commit Git dibuat (hash: <code>{commit_hash}</code>)\n"
        "• Status Akhir: Sukses (Waktu eksekusi: 2.18 detik)"
    )

def build_help_view() -> str:
    """Bantuan & Dokumentasi Operasional NOC"""
    return (
        "<b>PANDUAN OPERASIONAL BOT NETWORK AUTOMATION</b>\n"
        "Sistem automasi pemantauan jaringan, pelaporan gangguan, dan backup konfigurasi terpusat.\n\n"
        "Daftar Perintah:\n\n"
        "• /status\n"
        "Menampilkan ringkasan kondisi jaringan, perangkat UP/DOWN, dan alert aktif.\n\n"
        "• /devices\n"
        "Menampilkan tabel inventaris seluruh perangkat yang dipantau.\n\n"
        "• /device [nama_perangkat]\n"
        "Menampilkan rincian telemetri satu perangkat (CPU, Memori, Uptime, Status Backup).\n"
        "Contoh: /device RTR-Core-01\n\n"
        "• /alerts\n"
        "Menampilkan daftar gangguan dan anomali jaringan yang memerlukan mitigasi.\n\n"
        "• /ack [id_alert]\n"
        "Konfirmasi penanganan alert oleh engineer yang bertugas.\n"
        "Contoh: /ack 101\n\n"
        "• /resolve [id_alert]\n"
        "Selesaikan dan pulihkan gangguan secara manual.\n"
        "Contoh: /resolve 101\n\n"
        "• /backup [nama_perangkat]\n"
        "Memicu penarikan konfigurasi manual dan commit otomatis ke repositori Git.\n"
        "Contoh: /backup RTR-Core-01\n\n"
        "• /user\n"
        "Melihat identitas teknisi, Chat ID Telegram, dan verifikasi otomatis akses Whitelist.\n\n"
        "• /approve [username] [role]\n"
        "Menyetujui akses teknisi baru dengan role pilihan (khusus admin)."
    )


# ==================== TELEGRAM COMMAND HANDLERS ====================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command /start: Menampilkan Dashboard Utama"""
    ACTIVE_CHATS.add(update.effective_chat.id)
    text = build_status_view()
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)
    u_name = update.effective_user.username or update.effective_user.first_name if update.effective_user else "User"
    log_telegram_message(update.effective_chat.id, "COMMAND_REPLY", f"Respon /start: Dashboard utama dibuka oleh @{u_name}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command /help: Menampilkan Panduan Operasional"""
    ACTIVE_CHATS.add(update.effective_chat.id)
    text = build_help_view()
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)
    u_name = update.effective_user.username or update.effective_user.first_name if update.effective_user else "User"
    log_telegram_message(update.effective_chat.id, "COMMAND_REPLY", f"Respon /help: Panduan bot dikirim ke @{u_name}")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command /status: Ringkasan Telemetri Kesehatan Jaringan"""
    ACTIVE_CHATS.add(update.effective_chat.id)
    text = build_status_view()
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)
    u_name = update.effective_user.username or update.effective_user.first_name if update.effective_user else "User"
    log_telegram_message(update.effective_chat.id, "COMMAND_REPLY", f"Respon /status: Ringkasan telemetri dikirim ke @{u_name}")

async def devices_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command /devices: Daftar Inventaris Seluruh Node"""
    ACTIVE_CHATS.add(update.effective_chat.id)
    text = build_devices_view()
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)
    u_name = update.effective_user.username or update.effective_user.first_name if update.effective_user else "User"
    log_telegram_message(update.effective_chat.id, "COMMAND_REPLY", f"Respon /devices: Inventaris node dikirim ke @{u_name}")

async def device_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command /device <nama>: Status Detail Satu Node"""
    ACTIVE_CHATS.add(update.effective_chat.id)
    if not context.args:
        text = build_devices_view()
        await update.message.reply_text(
            "Parameter Perangkat Diperlukan. Gunakan format: <code>/device &lt;nama_perangkat&gt;</code>\n"
            "Contoh: <code>/device RTR-Core-01</code>\n\n"
            + text,
            parse_mode=ParseMode.HTML
        )
        return

    device_name = context.args[0].strip()
    text = build_device_detail_view(device_name)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)
    u_name = update.effective_user.username or update.effective_user.first_name if update.effective_user else "User"
    log_telegram_message(update.effective_chat.id, "COMMAND_REPLY", f"Respon /device: Detail telemetri {device_name} dikirim ke @{u_name}")

async def alerts_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command /alerts: Tampilan Daftar Insiden Jaringan"""
    ACTIVE_CHATS.add(update.effective_chat.id)
    text = build_alerts_view()
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)
    u_name = update.effective_user.username or update.effective_user.first_name if update.effective_user else "User"
    log_telegram_message(update.effective_chat.id, "COMMAND_REPLY", f"Respon /alerts: Daftar gangguan dikirim ke @{u_name}")

async def ack_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command /ack <alert_id>: Acknowledge Alert"""
    user_id = update.effective_user.id
    if not is_whitelisted(user_id):
        logger.warning(f"Unauthorized /ack command by user {user_id}")
        await update.message.reply_text(
            render_access_denied_view(user_id, "/ack"),
            parse_mode=ParseMode.HTML
        )
        return

    if not context.args:
        text = build_alerts_view()
        await update.message.reply_text(
            "<b>PARAMETER ALERT DIPERLUKAN</b>\n\n"
            "Gunakan format: <code>/ack &lt;id_alert&gt;</code> (contoh: <code>/ack 101</code>)\n\n"
            + text,
            parse_mode=ParseMode.HTML
        )
        return

    alert_id = context.args[0].strip()
    alert = ALERTS.get(alert_id)
    if not alert:
        await update.message.reply_text(
            f"<b>ALERT ID TIDAK DITEMUKAN</b>\n\nAlert <code>{html.escape(alert_id)}</code> tidak terdaftar dalam antrean.",
            parse_mode=ParseMode.HTML
        )
        return

    handler_user = update.effective_user.username or update.effective_user.first_name
    alert["status"] = "Acknowledged"
    alert["acknowledged_by"] = handler_user
    alert["acknowledged_at"] = get_current_time_wib()
    ACTIVE_CHATS.add(update.effective_chat.id)

    ack_report = (
        "<b>KONFIRMASI PENANGANAN ALERT</b>\n\n"
        f"Referensi Alert: <code>{alert['id']}</code>\n"
        f"Perangkat: <code>{alert['device']}</code>\n"
        f"Tingkat Bahaya: {alert['severity']}\n"
        f"Petugas: @{html.escape(handler_user)}\n"
        f"Waktu Konfirmasi: <code>{alert['acknowledged_at']}</code>\n"
        "Status Alur: In Progress\n\n"
        "Ketik /resolve [alert_id] untuk menutup alert jika gangguan telah diperbaiki."
    )
    await update.message.reply_text(ack_report, parse_mode=ParseMode.HTML)
    log_telegram_message(
        chat_id=str(update.effective_chat.id),
        message_type="COMMAND_REPLY",
        content=f"Alert #{alert['id']} ({alert['device']}) berhasil di-acknowledge oleh @{handler_user}.",
        status="SENT"
    )

async def resolve_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command /resolve <alert_id>: Resolve Alert secara manual"""
    user_id = update.effective_user.id
    if not is_whitelisted(user_id):
        logger.warning(f"Unauthorized /resolve command by user {user_id}")
        await update.message.reply_text(
            render_access_denied_view(user_id, "/resolve"),
            parse_mode=ParseMode.HTML
        )
        return

    if not context.args:
        text = build_alerts_view()
        await update.message.reply_text(
            "<b>PARAMETER ALERT DIPERLUKAN</b>\n\n"
            "Gunakan format: <code>/resolve &lt;id_alert&gt;</code> (contoh: <code>/resolve 101</code>)\n\n"
            + text,
            parse_mode=ParseMode.HTML
        )
        return

    alert_id = context.args[0].strip()
    alert = ALERTS.get(alert_id)
    if not alert:
        await update.message.reply_text(
            f"<b>ALERT ID TIDAK DITEMUKAN</b>\n\nAlert <code>{html.escape(alert_id)}</code> tidak terdaftar dalam antrean.",
            parse_mode=ParseMode.HTML
        )
        return

    if alert.get("status", "").upper() == "RESOLVED":
        await update.message.reply_text("Alert ini sudah dalam status Resolved.")
        return

    handler_user = update.effective_user.username or update.effective_user.first_name
    dev_name = alert["device"]
    
    if dev_name in DEVICES:
        if DEVICES[dev_name]["status"] == "DOWN":
            DEVICES[dev_name]["status"] = "UP"
            DEVICES[dev_name]["uptime"] = "1 menit (Baru Pulih)"
        elif alert_id == "102":
            DEVICES[dev_name]["cpu"] = 24

    alert["status"] = "Resolved"
    alert["resolved_at"] = get_current_time_wib()
    ACTIVE_CHATS.add(update.effective_chat.id)

    resolve_report = (
        "<b>KONFIRMASI PENYELESAIAN ALERT</b>\n\n"
        f"Referensi Alert: <code>{alert['id']}</code>\n"
        f"Perangkat: <code>{alert['device']}</code>\n"
        f"Tingkat Bahaya: {alert['severity']}\n"
        f"Diselesaikan oleh: @{html.escape(handler_user)}\n"
        f"Waktu Selesai: <code>{alert['resolved_at']}</code>\n"
        "Status Alur: Resolved\n\n"
        "Perangkat telah dipulihkan dan alert ditutup."
    )
    await update.message.reply_text(resolve_report, parse_mode=ParseMode.HTML)
    
    log_telegram_message(
        chat_id=str(update.effective_chat.id),
        message_type="COMMAND_REPLY",
        content=f"Alert #{alert['id']} ({alert['device']}) berhasil di-resolve oleh @{handler_user}.",
        status="SENT"
    )

async def backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command /backup <nama>: Trigger Backup Manual"""
    user_id = update.effective_user.id
    if not is_whitelisted(user_id):
        logger.warning(f"Unauthorized /backup command by user {user_id}")
        await update.message.reply_text(
            render_access_denied_view(user_id, "/backup"),
            parse_mode=ParseMode.HTML
        )
        return

    if not context.args:
        text = build_devices_view()
        await update.message.reply_text(
            "<b>PARAMETER PERANGKAT DIPERLUKAN</b>\n\n"
            "Gunakan format: <code>/backup &lt;nama_perangkat&gt;</code> (contoh: <code>/backup RTR-Core-01</code>)\n\n"
            + text,
            parse_mode=ParseMode.HTML
        )
        return

    device_name = context.args[0].strip()
    if device_name not in DEVICES:
        await update.message.reply_text(
            f"<b>PERANGKAT TIDAK DITEMUKAN</b>\n\nPerangkat <code>{html.escape(device_name)}</code> tidak valid.",
            parse_mode=ParseMode.HTML
        )
        return

    operator_user = update.effective_user.username or update.effective_user.first_name
    progress_msg = await update.message.reply_text(
        f"Menghubungi {html.escape(device_name)} ({DEVICES[device_name]['ip']}) via SSH.\n"
        "Mengekstrak running-config dan menghitung checksum berkas",
        parse_mode=ParseMode.HTML
    )

    report_text = build_backup_report(device_name, operator_user)
    await progress_msg.edit_text(report_text, parse_mode=ParseMode.HTML)
    log_telegram_message(
        chat_id=str(update.effective_chat.id),
        message_type="COMMAND_REPLY",
        content=f"Backup konfigurasi manual {device_name} berhasil dieksekusi oleh @{operator_user}.",
        status="SENT"
    )


async def user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command /user: Menampilkan info profil teknisi, Chat ID Telegram, dan verifikasi status whitelist NOC"""
    ACTIVE_CHATS.add(update.effective_chat.id)
    user = update.effective_user
    if not user:
        return

    user_id = user.id
    raw_username = user.username or ''
    display_username = f"@{raw_username}" if raw_username else "(tidak ada username)"
    full_name = user.full_name or user.first_name or "Engineer"

    session = db_session()
    try:
        # 1. Cek apakah user sudah terdaftar dengan chat_id angka ini
        entry = session.query(TelegramWhitelist).filter(TelegramWhitelist.chat_id == str(user_id)).first()

        # 2. Jika belum ditemukan dengan chat_id, cek apakah sudah di-approve oleh Admin via @username
        if not entry and raw_username:
            entry = session.query(TelegramWhitelist).filter(
                (TelegramWhitelist.telegram_username.ilike(f"@{raw_username}")) |
                (TelegramWhitelist.telegram_username.ilike(raw_username))
            ).first()
            if entry:
                # Kaitkan Chat ID asli Telegram pengguna
                entry.chat_id = str(user_id)
                if full_name:
                    entry.engineer_name = full_name
                session.commit()
                if entry.is_active and user_id not in WHITELIST_USERS:
                    WHITELIST_USERS.append(user_id)

        # 3. Jika sudah terdaftar
        if entry:
            if entry.is_active and user_id not in WHITELIST_USERS:
                WHITELIST_USERS.append(user_id)

            status_str = "Active" if entry.is_active else "Inactive"
            reply_msg = (
                "<b>PROFIL TEKNISI AGIVA NETWORK OPERATIONS</b>\n\n"
                f"Nama: <code>{html.escape(entry.engineer_name)}</code>\n"
                f"Chat ID: <code>{user_id}</code>\n"
                f"Username: {html.escape(entry.telegram_username)}\n"
                f"Role: <code>{html.escape(entry.role)}</code>\n"
                f"Status: {status_str}\n\n"
                "Hak Akses:\n"
                "• Diizinkan: /status, /devices, /device, /alerts, /user, /help, /ack, /backup\n"
                "• Ditolak: -\n\n"
                f"Terdaftar sejak: <code>{entry.registered_at.strftime('%Y-%m-%d')}</code>"
            )
            log_telegram_message(update.effective_chat.id, "COMMAND_REPLY", f"Respon /user: Pengecekan profil teknisi @{raw_username or full_name} (ID: {user_id})")
            await update.message.reply_text(reply_msg, parse_mode=ParseMode.HTML)
            return

        # 4. Jika belum terdaftar
        reply_msg = (
            "<b>INFORMASI PENGGUNA TELEGRAM</b>\n\n"
            f"Nama: <code>{html.escape(full_name)}</code>\n"
            f"Chat ID: <code>{user_id}</code>\n"
            f"Username: {html.escape(display_username)}\n"
            "Role: <i>Guest</i>\n"
            "Status: Inactive\n\n"
            "Hak Akses:\n"
            "• Diizinkan: /status, /devices, /device, /alerts, /user, /help\n"
            "• Ditolak: /ack, /backup\n\n"
            "Untuk mendaftarkan akun ke Whitelist, hubungi admin untuk di-approve via username Telegram Anda."
        )
        await update.message.reply_text(reply_msg, parse_mode=ParseMode.HTML)

    except Exception as e:
        logger.error(f"Error handling /user command: {e}")
        await update.message.reply_text(f"Gagal memuat profil: {e}")
    finally:
        session.close()


async def approve_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command /approve @username [role]: Menyetujui akses teknisi oleh Lead Engineer Dara Samsara"""
    user = update.effective_user
    if not user:
        return

    # Otorisasi: HANYA Dara Samsara (Lead Engineer) yang berhak approve
    lead_admin_id = 5419251159
    try:
        env_admin = os.getenv("TELEGRAM_CHAT_ID", "5419251159").strip()
        if env_admin.isdigit():
            lead_admin_id = int(env_admin)
    except Exception:
        pass

    if user.id != lead_admin_id:
        logger.warning(f"Unauthorized /approve attempt by user {user.id} ({user.username})")
        await update.message.reply_text(
            "Akses ditolak. Hanya Admin yang memiliki wewenang untuk menyetujui akses.",
            parse_mode=ParseMode.HTML
        )
        return

    # Ambil parameter target (@username) dan custom role (opsional)
    target = None
    custom_role = None
    if context.args:
        target = context.args[0].strip()
        if len(context.args) > 1:
            custom_role = " ".join(context.args[1:]).strip()
    elif update.message.reply_to_message and update.message.reply_to_message.from_user:
        replied_user = update.message.reply_to_message.from_user
        target = f"@{replied_user.username}" if replied_user.username else replied_user.first_name
        if context.args:
            custom_role = " ".join(context.args).strip()

    if not target:
        await update.message.reply_text(
            "<b>PARAMETER USERNAME DIPERLUKAN</b>\n\n"
            "Gunakan format: <code>/approve @username [role]</code>\n\n"
            "Contoh:\n"
            "• <code>/approve @bintang Network Intern</code>",
            parse_mode=ParseMode.HTML
        )
        return

    # Normalisasi format username
    clean_target = target.lstrip("@").strip()
    username_tag = f"@{clean_target}"
    eng_name = clean_target.replace("_", " ").title()
    eng_role = custom_role if custom_role else "Member"

    session = db_session()
    try:
        # Cari di database berdasarkan username
        entry = session.query(TelegramWhitelist).filter(
            (TelegramWhitelist.telegram_username.ilike(username_tag)) |
            (TelegramWhitelist.telegram_username.ilike(clean_target)) |
            (TelegramWhitelist.engineer_name.ilike(clean_target))
        ).first()

        if entry:
            entry.is_active = True
            entry.role = eng_role
            if not entry.telegram_username.startswith("@"):
                entry.telegram_username = username_tag
            session.commit()
            if entry.chat_id.isdigit():
                cid_int = int(entry.chat_id)
                if cid_int not in WHITELIST_USERS:
                    WHITELIST_USERS.append(cid_int)

            msg = f"Akun {html.escape(entry.telegram_username)} berhasil di-approve sebagai {html.escape(entry.role)}."
            await update.message.reply_text(msg)
            return

        # Jika username belum ada di database, buat record baru
        new_entry = TelegramWhitelist(
            chat_id="-",
            telegram_username=username_tag,
            engineer_name=eng_name,
            role=eng_role,
            is_active=True
        )
        session.add(new_entry)
        session.commit()

        msg = f"Akun {html.escape(username_tag)} berhasil di-approve sebagai {html.escape(eng_role)}."
        await update.message.reply_text(msg)
        log_telegram_message(update.effective_chat.id, "COMMAND_REPLY", f"Respon /approve: Akun {username_tag} di-approve sebagai {eng_role} oleh Lead Admin")

    except Exception as e:
        logger.error(f"Error handling /approve: {e}")
        await update.message.reply_text(f"Gagal melakukan approval: {e}")
    finally:
        session.close()


async def fallback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Catch-all handler: tampilkan ringkasan status untuk pesan teks apa pun yang bukan command"""
    ACTIVE_CHATS.add(update.effective_chat.id)
    text = build_status_view()
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)
    u_name = update.effective_user.username or update.effective_user.first_name if update.effective_user else "User"
    log_telegram_message(update.effective_chat.id, "FALLBACK_REPLY", f"Pesan bebas dari @{u_name} → ringkasan status dikirim")


# ==================== MAIN APPLICATION INITIALIZATION ====================

async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Menangkap semua exception agar bot tetap berjalan tanpa crash"""
    logger.error(f"Global Error Handler caught: {context.error}")

def main():
    if not BOT_TOKEN:
        print("[Critical] TELEGRAM_BOT_TOKEN belum diset di file .env!")
        return

    print("===============================================================")
    print("   PT AGIVA INDONESIA — AUTOMATED NOC TELEGRAM ENGINE          ")
    print("===============================================================")
    print(f"[*] Started at      : {get_current_time_wib()}")
    print(f"[*] Whitelist Users : {WHITELIST_USERS if WHITELIST_USERS else 'Unrestricted (Open Lab)'}")
    print("[*] Engine Status   : Ready for Telemetry & Alert Dispatch")
    print("[*] Polling loop running... (Tekan Ctrl+C untuk menghentikan)")
    print("===============================================================\n")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Command Handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("devices", devices_command))
    app.add_handler(CommandHandler("device", device_command))
    app.add_handler(CommandHandler("alerts", alerts_command))
    app.add_handler(CommandHandler("ack", ack_command))
    app.add_handler(CommandHandler("resolve", resolve_command))
    app.add_handler(CommandHandler("backup", backup_command))
    app.add_handler(CommandHandler("user", user_command))
    app.add_handler(CommandHandler("approve", approve_command))

    # Fallback: pesan teks bebas (bukan command) → tampilkan ringkasan status
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback_handler))

    # Automated Background Data Collector Scheduler dinonaktifkan (Manual Resolve Only)
    # if app.job_queue:
    #     app.job_queue.run_repeating(auto_collector_job, interval=25, first=10)
    #     logger.info("Background Automated Data Collector Scheduler initialized (interval: 25s)")

    # Global Error Handler
    app.add_error_handler(global_error_handler)

    app.run_polling()

if __name__ == "__main__":
    main()
