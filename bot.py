import os
import sys
import html
import random
import hashlib
import logging
import json
import time
import threading
from datetime import datetime, timedelta
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
import re
from database import db_session
from models import TelegramWhitelist, TelegramMessageLog, Alert, IncidentLog, Device, BackupHistory

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

# ==================== DATA MODEL ====================
# Data inventaris, telemetri, dan alert diproses langsung secara riil dari database PostgreSQL
DEVICES = {}
ALERTS = {}

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
    session = None
    try:
        session = db_session()
        entry = session.query(TelegramWhitelist).filter(
            TelegramWhitelist.chat_id == str(user_id),
            TelegramWhitelist.is_active == True
        ).first()
        if entry:
            if user_id not in WHITELIST_USERS:
                WHITELIST_USERS.append(user_id)
            return True
        return False
    except Exception as e:
        if session:
            try:
                session.rollback()
            except Exception:
                pass
        logger.error(f"Error checking whitelist DB: {e}")
        return False
    finally:
        if session:
            session.close()
        db_session.remove()

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
    session = None
    try:
        session = db_session()
        # 30-Day Auto Retention: Hapus log berumur lebih dari 30 hari
        cutoff_date = datetime.now() - timedelta(days=30)
        try:
            session.query(TelegramMessageLog).filter(TelegramMessageLog.sent_at < cutoff_date).delete()
        except Exception:
            pass

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
    except Exception as e:
        if session:
            try:
                session.rollback()
            except Exception:
                pass
        logger.error(f"Error logging telegram message to DB: {e}")
    finally:
        if session:
            session.close()
        db_session.remove()


# ==================== VIEW BUILDERS (FORMAL CORPORATE TEMPLATES) ====================

def build_status_view() -> str:
    """Tampilan Ringkasan Status NOC Riil dari Database"""
    session = None
    try:
        session = db_session()
        devices = session.query(Device).order_by(Device.device_id.asc()).all()
        active_alerts = session.query(Alert).filter(Alert.resolved_at == None).all()

        total = len(devices)
        up_count = sum(1 for d in devices if (d.status or "").upper() == "UP")
        down_count = total - up_count
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
            down_devices = [d.name for d in devices if (d.status or "").upper() == "DOWN"]
            msg += f"Perangkat tidak terjangkau: <code>{', '.join(down_devices)}</code>\n\n"
        else:
            msg += "Seluruh perangkat beroperasi normal.\n\n"

        msg += (
            "Perintah yang tersedia:\n"
            "/start - Panduan operasional bot\n"
            "/devices - Daftar seluruh perangkat\n"
            "/device [nama_perangkat] - Rincian telemetri perangkat\n"
            "/alerts - Daftar gangguan aktif\n"
            "/ack [id_alert] - Konfirmasi penanganan alert\n"
            "/resolve [id_alert] - Selesaikan dan pulihkan gangguan\n"
            "/backup [nama_perangkat] [kategori] - Backup manual konfigurasi & log audit\n"
            "/user - Profil & status hak akses akun\n"
            "/approve @username [role] - (Khusus Admin) Menyetujui akses teknisi baru."
        )
        return msg
    except Exception as e:
        logger.error(f"Error in build_status_view: {e}")
        return "Gagal memuat status sistem jaringan dari database."
    finally:
        if session:
            session.close()
        db_session.remove()

def build_devices_view() -> str:
    """Tampilan Daftar Inventaris Perangkat Riil dari Database"""
    session = None
    try:
        session = db_session()
        devices = session.query(Device).order_by(Device.device_id.asc()).all()

        msg = (
            "<b>INVENTARIS PERANGKAT JARINGAN</b>\n\n"
            f"Total Perangkat Terdata : {len(devices)} Unit\n"
            "<pre>\n"
            "NAMA PERANGKAT     VENDOR      STATUS   LOKASI\n"
        )
        for dev in devices:
            d_name = (dev.name or "-")[:18]
            v_name = (dev.vendor or "-")[:11]
            status_txt = "UP" if (dev.status or "").upper() == "UP" else "DOWN"
            site_name = (dev.site or "-")[:12]
            msg += f"{d_name:<18} {v_name:<11} {status_txt:<8} {site_name}\n"
        msg += "</pre>\n\n"
        example_name = devices[0].name if devices else "SW-2930F-HO"
        msg += f"Ketik /device [nama_perangkat] untuk melihat telemetri lengkap. Contoh: /device {example_name}"
        return msg
    except Exception as e:
        logger.error(f"Error in build_devices_view: {e}")
        return "Gagal memuat daftar perangkat dari database."
    finally:
        if session:
            session.close()
        db_session.remove()

def build_device_detail_view(device_name: str) -> str:
    """Tampilan Detail Telemetri Satu Perangkat Riil dari Database"""
    session = None
    try:
        session = db_session()
        clean_name = device_name.strip()
        db_dev = session.query(Device).filter(Device.name.ilike(f"%{clean_name}%")).first()
        if not db_dev:
            db_dev = session.query(Device).filter(Device.ip_address == clean_name).first()

        if not db_dev:
            return (
                "<b>PERANGKAT TIDAK DITEMUKAN</b>\n\n"
                f"Perangkat <code>{html.escape(device_name)}</code> tidak terdaftar dalam inventaris.\n"
                "Gunakan perintah /devices untuk melihat daftar perangkat yang tersedia."
            )

        d_name = db_dev.name
        d_status = db_dev.status or "UP"
        d_ip = db_dev.ip_address or "-"
        d_vendor = db_dev.vendor or "-"
        d_site = db_dev.site or "-"
        d_uptime = db_dev.uptime or "-"
        cpu_val = int(db_dev.cpu_usage or 0)
        mem_val = int(db_dev.mem_usage or 0)
        lat_val = round(db_dev.latency_ms or 0.0, 1)
        loss_val = round(db_dev.packet_loss or 0.0, 1)

        status_badge = "UP" if d_status == "UP" else "DOWN"

        cpu_bar = make_progress_bar(cpu_val, 10)
        mem_bar = make_progress_bar(mem_val, 10)

        cpu_label = "Kritis" if cpu_val >= 85 else ("Tinggi" if cpu_val >= 70 else "Normal")
        mem_label = "Kritis" if mem_val >= 85 else ("Tinggi" if mem_val >= 70 else "Normal")

        # Ambil riwayat backup terakhir riil dari BackupHistory
        last_bkp = session.query(BackupHistory).filter(
            BackupHistory.device_id == db_dev.device_id,
            BackupHistory.status == 'SUCCESS'
        ).order_by(BackupHistory.timestamp.desc()).first()

        site_clean = str(d_site).replace(" ", "_")
        if last_bkp and last_bkp.timestamp:
            last_b = last_bkp.timestamp.strftime("%Y-%m-%d %H:%M WIB")
            b_path = os.path.dirname(last_bkp.file_path).replace("\\", "/") if last_bkp.file_path else f"/backups/{site_clean}/{d_name}"
        else:
            last_b = "Belum Ada Backup"
            b_path = f"/backups/{site_clean}/{d_name}"

        msg = (
            "<b>INFORMASI PERANGKAT</b>\n\n"
            f"Nama Device: {html.escape(d_name)}\n"
            f"Status Operasional: {status_badge}\n"
            f"Alamat IP: <code>{d_ip}</code>\n"
            f"Vendor: {d_vendor}\n"
            f"Lokasi: {d_site}\n"
            f"Latency: <code>{lat_val} ms</code> | Ping Drop: <code>{loss_val}%</code>\n"
            f"Waktu Aktif: <code>{d_uptime}</code>\n\n"
            "Penggunaan Sumber Daya:\n"
            f"<code>CPU [{cpu_bar}] {cpu_val:>2}% ({cpu_label})</code>\n"
            f"<code>MEM [{mem_bar}] {mem_val:>2}% ({mem_label})</code>\n\n"
            "Manajemen Konfigurasi:\n"
            f"• Backup Terakhir: <code>{last_b}</code>\n"
            f"• Jalur Direktori: <code>{b_path}</code>\n\n"
            f"Ketik /backup {html.escape(d_name)} untuk melakukan backup konfigurasi manual."
        )
        return msg
    except Exception as e:
        logger.error(f"Error in build_device_detail_view: {e}")
        return f"Gagal memuat telemetri perangkat {html.escape(device_name)} dari database."
    finally:
        if session:
            session.close()
        db_session.remove()

def build_alerts_view() -> str:
    """Tampilan Daftar Incident & Alert Aktif dari Database sesuai Format Resmi AGIVA"""
    session = None
    try:
        session = db_session()
        db_alerts = session.query(Alert).filter(Alert.resolved_at == None).order_by(Alert.triggered_at.desc()).all()
        open_alerts = [a for a in db_alerts if not a.acknowledged]
        ack_alerts = [a for a in db_alerts if a.acknowledged]

        today_start = datetime.combine(datetime.now().date(), datetime.min.time())
        resolved_count = session.query(IncidentLog).filter(
            IncidentLog.status == 'RESOLVED_ALERT',
            IncidentLog.resolved_at >= today_start
        ).count()

        time_wib = get_current_time_wib()

        # Format 1: Jika tidak ada gangguan aktif
        if not db_alerts:
            msg = (
                "<b>ACTIVE ALERTS</b>\n"
                f"As of {time_wib}\n\n"
                "<pre>\n"
                f"{'Unacknowledged':<17} {len(open_alerts)}\n"
                f"{'Acknowledged':<17} {len(ack_alerts)}\n"
                f"{'Resolved today':<17} {resolved_count}\n"
                "</pre>\n\n"
                "No active incidents."
            )
            return msg

        # Format 2: Jika ada gangguan aktif (Tabel Status)
        type_map = {
            "HOST_DOWN": "HOST DOWN",
            "CPU_OVERLOAD": "HIGH CPU",
            "MEMORY_OVERLOAD": "HIGH MEM",
            "HIGH_LATENCY": "HIGH LAT",
            "PACKET_LOSS": "PACKET LOSS"
        }

        now = datetime.now()
        table_lines = [
            f"{'ID':<4} {'SEV':<9} {'DEVICE':<14} {'TYPE':<11} {'AGE':<5} {'STATE'}"
        ]

        for a in db_alerts:
            id_str = f"#{a.alert_id}"
            sev_str = (a.severity or "WARNING").upper()[:8]
            dev_name = a.device.name if a.device else f"DEV-{a.device_id}"
            dev_str = dev_name[:14]
            t_raw = a.type or "INCIDENT"
            type_str = type_map.get(t_raw, t_raw.replace("_", " ").upper())[:11]

            if a.triggered_at:
                dur_sec = max(0, int((now - a.triggered_at).total_seconds()))
                if dur_sec < 3600:
                    age_str = f"{dur_sec // 60}m"
                elif dur_sec < 86400:
                    age_str = f"{dur_sec // 3600}h"
                else:
                    age_str = f"{dur_sec // 86400}d"
            else:
                age_str = "-"

            state_str = "ACK" if a.acknowledged else "UNACK"
            table_lines.append(f"{id_str:<4} {sev_str:<9} {dev_str:<14} {type_str:<11} {age_str:<5} {state_str}")

        msg = (
            "<b>ACTIVE ALERTS</b>\n"
            f"As of {time_wib}\n\n"
            "<pre>\n"
            f"{'Unacknowledged':<17} {len(open_alerts)}\n"
            f"{'Acknowledged':<17} {len(ack_alerts)}\n"
            f"{'Resolved today':<17} {resolved_count}\n\n"
            + "\n".join(table_lines) + "\n"
            "</pre>\n\n"
            "Acknowledge: /ack &lt;id&gt;"
        )
        return msg
    except Exception as e:
        logger.error(f"Error in build_alerts_view: {e}")
        return "Gagal memuat daftar alert dari database."
    finally:
        if session:
            session.close()
        db_session.remove()

def build_backup_report(device_name: str, operator_name: str) -> str:
    """Laporan Hasil Eksekusi Backup Konfigurasi Terakhir dari Database"""
    session = None
    try:
        session = db_session()
        clean_name = device_name.strip()
        db_dev = session.query(Device).filter(Device.name.ilike(f"%{clean_name}%")).first()
        if not db_dev:
            return f"Perangkat <code>{html.escape(device_name)}</code> tidak ditemukan dalam inventaris."

        last_bkp = session.query(BackupHistory).filter(
            BackupHistory.device_id == db_dev.device_id
        ).order_by(BackupHistory.timestamp.desc()).first()

        time_str = last_bkp.timestamp.strftime("%Y-%m-%d %H:%M:%S WIB") if last_bkp and last_bkp.timestamp else get_current_time_wib()
        f_path = last_bkp.file_path if last_bkp else f"/backups/{db_dev.site}/{db_dev.name}/"
        f_size = last_bkp.file_size if last_bkp else "-"
        st = "Sukses" if (last_bkp and last_bkp.status == 'SUCCESS') else ("Gagal" if last_bkp else "Belum Ada Riwayat")
        cat = last_bkp.category if last_bkp else "Config"

        return (
            "<b>LAPORAN HASIL BACKUP KONFIGURASI</b>\n\n"
            f"Perangkat: <code>{db_dev.name}</code> ({db_dev.ip_address})\n"
            f"Vendor: {db_dev.vendor}\n"
            f"Site: {db_dev.site}\n"
            f"Operator: @{html.escape(operator_name)}\n"
            f"Waktu Eksekusi: <code>{time_str}</code>\n\n"
            "Rincian Pengarsipan:\n"
            f"• Kategori: {cat}\n"
            f"• Lokasi Berkas:\n  <code>{f_path}</code>\n"
            f"• Ukuran Berkas: {f_size}\n"
            f"• Status Akhir: {st}"
        )
    except Exception as e:
        logger.error(f"Error in build_backup_report: {e}")
        return "Gagal memuat laporan backup dari database."
    finally:
        if session:
            session.close()
        db_session.remove()

def build_start_view() -> str:
    """Panduan & Dokumentasi Operasional NOC saat /start"""
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
        "Contoh: /device SW-2930F-HO\n\n"
        "• /alerts\n"
        "Menampilkan daftar gangguan dan anomali jaringan yang memerlukan mitigasi.\n\n"
        "• /ack [id_alert]\n"
        "Konfirmasi penanganan alert oleh engineer yang bertugas.\n"
        "Contoh: /ack 17\n\n"
        "• /resolve [id_alert]\n"
        "Selesaikan dan pulihkan gangguan secara manual.\n"
        "Contoh: /resolve 17\n\n"
        "• /backup [nama_perangkat] [kategori]\n"
        "Memicu penarikan konfigurasi & log audit multi-vendor (pilihan: all, system, config, traffic, threat).\n"
        "Contoh: /backup FW-PA220-1 (semua kategori) atau /backup SW-2930F-HO config\n\n"
        "• /user\n"
        "Melihat identitas teknisi, Chat ID Telegram, dan verifikasi otomatis akses Whitelist.\n\n"
        "• /approve [username] [role]\n"
        "Menyetujui akses teknisi baru dengan role pilihan (khusus admin)."
    )


# ==================== TELEGRAM COMMAND HANDLERS ====================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command /start: Menampilkan Panduan Operasional Bot"""
    ACTIVE_CHATS.add(update.effective_chat.id)
    text = build_start_view()
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)
    u_name = update.effective_user.username or update.effective_user.first_name if update.effective_user else "User"
    log_telegram_message(update.effective_chat.id, "COMMAND_REPLY", f"Response /start: Operational bot guide sent to @{u_name}")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command /status: Ringkasan Telemetri Kesehatan Jaringan"""
    ACTIVE_CHATS.add(update.effective_chat.id)
    text = build_status_view()
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)
    u_name = update.effective_user.username or update.effective_user.first_name if update.effective_user else "User"
    log_telegram_message(update.effective_chat.id, "COMMAND_REPLY", f"Response /status: Telemetry health summary sent to @{u_name}")

async def devices_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command /devices: Daftar Inventaris Seluruh Node"""
    ACTIVE_CHATS.add(update.effective_chat.id)
    text = build_devices_view()
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)
    u_name = update.effective_user.username or update.effective_user.first_name if update.effective_user else "User"
    log_telegram_message(update.effective_chat.id, "COMMAND_REPLY", f"Response /devices: Node inventory list sent to @{u_name}")

async def device_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command /device <nama>: Status Detail Satu Node"""
    ACTIVE_CHATS.add(update.effective_chat.id)
    if not context.args:
        text = build_devices_view()
        await update.message.reply_text(
            "Parameter Perangkat Diperlukan. Gunakan format: <code>/device &lt;nama_perangkat&gt;</code>\n"
            "Contoh: <code>/device SW-2930F-HO</code>\n\n"
            + text,
            parse_mode=ParseMode.HTML
        )
        return

    device_name = context.args[0].strip()
    text = build_device_detail_view(device_name)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)
    u_name = update.effective_user.username or update.effective_user.first_name if update.effective_user else "User"
    log_telegram_message(update.effective_chat.id, "COMMAND_REPLY", f"Response /device: Telemetry details for {device_name} sent to @{u_name}")

async def alerts_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command /alerts: Tampilan Daftar Insiden Jaringan"""
    ACTIVE_CHATS.add(update.effective_chat.id)
    text = build_alerts_view()
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)
    u_name = update.effective_user.username or update.effective_user.first_name if update.effective_user else "User"
    log_telegram_message(update.effective_chat.id, "COMMAND_REPLY", f"Response /alerts: Active alerts list sent to @{u_name}")

async def ack_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command /ack <alert_id>: Acknowledge Alert (Database Riil)"""
    user_id = update.effective_user.id
    if not is_whitelisted(user_id):
        logger.warning(f"Unauthorized /ack command by user {user_id}")
        await update.message.reply_text(
            render_access_denied_view(user_id, "/ack"),
            parse_mode=ParseMode.HTML
        )
        return

    # Parse ID dari argumen (/ack 10) atau text (/ack10 atau /ack_10)
    raw_id = ""
    if context.args:
        raw_id = context.args[0].strip()
    elif update.message and update.message.text:
        m = re.search(r'^/ack_?(\w+)', update.message.text.strip(), re.IGNORECASE)
        if m:
            raw_id = m.group(1).strip()

    if not raw_id:
        text = build_alerts_view()
        await update.message.reply_text(
            "<b>PARAMETER ALERT DIPERLUKAN</b>\n\n"
            "Gunakan format: <code>/ack &lt;id_alert&gt;</code> (contoh: <code>/ack 17</code>)\n\n"
            + text,
            parse_mode=ParseMode.HTML
        )
        return

    alert_id_clean = raw_id.lstrip('#').replace('ALT-', '').strip()
    handler_user = update.effective_user.username or update.effective_user.first_name

    session = None
    db_alert = None
    try:
        session = db_session()
        if alert_id_clean.isdigit():
            db_alert = session.query(Alert).filter(Alert.alert_id == int(alert_id_clean)).first()

        if db_alert:
            if db_alert.resolved_at:
                await update.message.reply_text(f"<b>PEMBERITAHUAN</b>\n\nAlert #{db_alert.alert_id} sudah dalam status Resolved sebelumnya.", parse_mode=ParseMode.HTML)
                return

            alert_id_val = db_alert.alert_id
            dev_name = db_alert.device.name if db_alert.device else f"Perangkat #{db_alert.device_id}"
            severity_val = db_alert.severity

            db_alert.acknowledged = True
            db_alert.acknowledged_by = f"@{handler_user}"
            session.commit()

            ack_report = (
                "<b>KONFIRMASI PENANGANAN ALERT</b>\n\n"
                f"Referensi Alert: <code>#{alert_id_val}</code>\n"
                f"Perangkat: <code>{dev_name}</code>\n"
                f"Tingkat Bahaya: {severity_val}\n"
                f"Petugas: @{html.escape(handler_user)}\n"
                f"Waktu Konfirmasi: <code>{get_current_time_wib()}</code>\n"
                "Status ACK: Acknowledged (Sedang Ditangani)\n\n"
                f"Ketik <code>/resolve {alert_id_val}</code> untuk menyelesaikan gangguan dan memindahkannya ke Incident Log."
            )
            ACTIVE_CHATS.add(update.effective_chat.id)
            await update.message.reply_text(ack_report, parse_mode=ParseMode.HTML)
            log_telegram_message(
                chat_id=str(update.effective_chat.id),
                message_type="COMMAND_REPLY",
                content=f"Alert #{alert_id_val} ({dev_name}) acknowledged by @{handler_user}.",
                status="SENT"
            )
            return

        await update.message.reply_text(
            f"<b>ALERT ID TIDAK DITEMUKAN</b>\n\nAlert <code>{html.escape(raw_id)}</code> tidak terdaftar dalam antrean aktif database.",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Error handling /ack command: {e}")
        await update.message.reply_text(f"Gagal memproses acknowledge: {e}")
    finally:
        if session:
            session.close()
        db_session.remove()

async def resolve_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command /resolve <alert_id>: Resolve Alert secara manual & pindahkan ke Incident Log"""
    user_id = update.effective_user.id
    if not is_whitelisted(user_id):
        logger.warning(f"Unauthorized /resolve command by user {user_id}")
        await update.message.reply_text(
            render_access_denied_view(user_id, "/resolve"),
            parse_mode=ParseMode.HTML
        )
        return

    # Parse ID dari argumen (/resolve 10) atau text (/resolve10 atau /resolve_10)
    raw_id = ""
    if context.args:
        raw_id = context.args[0].strip()
    elif update.message and update.message.text:
        m = re.search(r'^/resolve_?(\w+)', update.message.text.strip(), re.IGNORECASE)
        if m:
            raw_id = m.group(1).strip()

    if not raw_id:
        text = build_alerts_view()
        await update.message.reply_text(
            "<b>PARAMETER ALERT DIPERLUKAN</b>\n\n"
            "Gunakan format: <code>/resolve &lt;id_alert&gt;</code> (contoh: <code>/resolve 17</code>)\n\n"
            + text,
            parse_mode=ParseMode.HTML
        )
        return

    alert_id_clean = raw_id.lstrip('#').replace('ALT-', '').strip()
    handler_user = update.effective_user.username or update.effective_user.first_name

    session = None
    db_alert = None
    try:
        session = db_session()
        if alert_id_clean.isdigit():
            db_alert = session.query(Alert).filter(Alert.alert_id == int(alert_id_clean)).first()

        if db_alert:
            if db_alert.resolved_at:
                await update.message.reply_text(f"<b>PEMBERITAHUAN</b>\n\nAlert #{db_alert.alert_id} sudah terselesaikan sebelumnya (Status: Resolved).", parse_mode=ParseMode.HTML)
                return

            # VALIDASI KETAT PER SOP PT AGIVA: Wajib /ack terlebih dahulu sebelum /resolve
            if not db_alert.acknowledged:
                dev_name = db_alert.device.name if db_alert.device else f"Perangkat #{db_alert.device_id}"
                await update.message.reply_text(
                    f"<b>ALERT BELUM DI-ACKNOWLEDGE</b>\n\n"
                    f"Alert <code>#{db_alert.alert_id}</code> ({html.escape(dev_name)}) harus di-acknowledge terlebih dahulu sebelum dapat diselesaikan per SOP NOC PT AGIVA.\n\n"
                    f"Silakan ketik <code>/ack {db_alert.alert_id}</code> terlebih dahulu untuk mengonfirmasi penanganan.",
                    parse_mode=ParseMode.HTML
                )
                return

            alert_id_val = db_alert.alert_id
            dev_name = db_alert.device.name if db_alert.device else f"Perangkat #{db_alert.device_id}"
            severity_val = db_alert.severity

            now = datetime.now()
            db_alert.resolved_at = now
            db_alert.acknowledged = True

            # Pindahkan / sinkronkan ke Incident Log dengan status RESOLVED_ALERT
            active_inc = session.query(IncidentLog).filter(
                IncidentLog.device_id == db_alert.device_id,
                IncidentLog.type == db_alert.type,
                IncidentLog.resolved_at == None
            ).first()

            if active_inc:
                dur_sec = max(1, int((now - active_inc.started_at).total_seconds()))
                active_inc.resolved_at = now
                active_inc.duration_seconds = dur_sec
                active_inc.status = 'RESOLVED_ALERT'
                inc_id = active_inc.incident_id
            else:
                dur_sec = max(1, int((now - db_alert.triggered_at).total_seconds())) if db_alert.triggered_at else 600
                new_inc = IncidentLog(
                    device_id=db_alert.device_id,
                    type=db_alert.type,
                    severity=severity_val,
                    peak_metric="-",
                    started_at=db_alert.triggered_at or now,
                    resolved_at=now,
                    duration_seconds=dur_sec,
                    status='RESOLVED_ALERT'
                )
                session.add(new_inc)
                session.flush()
                inc_id = new_inc.incident_id

            session.commit()

            ACTIVE_CHATS.add(update.effective_chat.id)
            resolve_report = (
                "<b>KONFIRMASI PENYELESAIAN ALERT</b>\n\n"
                f"Referensi Alert: <code>#{alert_id_val}</code>\n"
                f"Perangkat: <code>{dev_name}</code>\n"
                f"Tingkat Bahaya: {severity_val}\n"
                f"Diselesaikan oleh: @{html.escape(handler_user)}\n"
                f"Waktu Selesai: <code>{get_current_time_wib()}</code>\n"
                f"Status Insiden: Resolved (Tercatat di Incident Log #INC-{inc_id})\n\n"
                "Perangkat telah pulih. Alert berhasil ditutup dan dipindahkan dari tabel Active Alerts ke tabel Incident Log & Cooldown History."
            )
            await update.message.reply_text(resolve_report, parse_mode=ParseMode.HTML)
            log_telegram_message(
                chat_id=str(update.effective_chat.id),
                message_type="COMMAND_REPLY",
                content=f"Alert #{alert_id_val} ({dev_name}) resolved by @{handler_user} and moved to Incident Log.",
                status="SENT"
            )
            return

        await update.message.reply_text(
            f"<b>ALERT ID TIDAK DITEMUKAN</b>\n\nAlert <code>{html.escape(raw_id)}</code> tidak terdaftar dalam antrean aktif database.",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"Error handling /resolve command: {e}")
        await update.message.reply_text(f"Gagal memproses penyelesaian alert: {e}")
    finally:
        if session:
            session.close()
        db_session.remove()

async def backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command /backup <nama>: Trigger Backup & Log Archive Manual Riil"""
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
            "Gunakan format: <code>/backup &lt;nama_perangkat&gt; [kategori]</code>\n\n"
            "Pilihan Kategori: <code>all</code>, <code>system</code>, <code>config</code>, <code>traffic</code>, <code>threat</code>\n\n"
            "Contoh:\n"
            "• <code>/backup FW-PA220-1</code> (Tarik semua kategori)\n"
            "• <code>/backup FW-PA220-1 traffic</code> (Hanya Traffic)\n"
            "• <code>/backup SW-2930F-HO config</code> (Hanya Running Config)\n\n"
            + text,
            parse_mode=ParseMode.HTML
        )
        return

    device_name = context.args[0].strip()
    category_param = context.args[1].strip().lower() if len(context.args) > 1 else None
    operator_user = update.effective_user.username or update.effective_user.first_name

    cat_desc = f"kategori {category_param.upper()}" if category_param and category_param != "all" else "semua kategori"

    # Deteksi protokol komunikasi perangkat riil dari database (SSH vs API)
    method = "SSH"
    session_check = None
    try:
        session_check = db_session()
        db_dev = session_check.query(Device).filter(Device.name.ilike(f"%{device_name}%")).first()
        if not db_dev:
            db_dev = session_check.query(Device).filter(Device.ip_address == device_name).first()
        if db_dev and db_dev.vendor:
            v_low = db_dev.vendor.lower()
            if "palo" in v_low or "pan" in v_low:
                method = "API"
            elif "aruba" in v_low or "huawei" in v_low or "cisco" in v_low:
                method = "SSH"
    except Exception:
        pass
    finally:
        if session_check:
            session_check.close()
        db_session.remove()

    progress_msg = await update.message.reply_text(
        "<b>MEMPROSES PENCADANGAN</b>\n\n"
        f"Menghubungi <code>{html.escape(device_name)}</code> via {method}.\n"
        f"Mengekstrak berkas {cat_desc}.",
        parse_mode=ParseMode.HTML
    )

    try:
        from backup_service import run_device_backup
        backup_result = run_device_backup(
            device_name,
            category_filter=category_param,
            trigger_by=f"Telegram (@{operator_user})"
        )
    except Exception as e_bkp:
        logger.error(f"Error executing backup_service: {e_bkp}")
        backup_result = {"success": False, "error": str(e_bkp)}

    if not backup_result.get("success"):
        await progress_msg.edit_text(
            f"<b>GAGAL MENGEKSEKUSI PENCADANGAN</b>\n\n"
            f"Perangkat: <code>{html.escape(device_name)}</code>\n"
            f"Keterangan: {html.escape(backup_result.get('error', 'Terjadi kesalahan internal.'))}",
            parse_mode=ParseMode.HTML
        )
        return

    dev_name_res = backup_result.get("device", device_name)
    ip_res = backup_result.get("ip", "-")
    site_res = backup_result.get("site", "HO")
    vendor_res = backup_result.get("vendor", "-")
    items = backup_result.get("results", [])

    total = len(items)
    succeeded = sum(1 for it in items if it.get("status") == "SUCCESS")
    has_failed = succeeded < total

    header = "<b>BACKUP COMPLETED WITH ERRORS</b>" if has_failed else "<b>BACKUP COMPLETED</b>"
    time_wib = get_current_time_wib()

    lines_meta = [
        f"{'Device':<10} {dev_name_res}",
        f"{'IP':<10} {ip_res}",
        f"{'Vendor':<10} {vendor_res}",
        f"{'Site':<10} {site_res}",
        f"{'Operator':<10} @{operator_user}",
        f"{'Executed':<10} {time_wib}",
    ]

    lines_art = [
        f"{'Artifact':<10} {'Status':<8} Size"
    ]
    files = []
    errors = []

    for it in items:
        cat = it.get("category", "CONFIG").upper()
        is_ok = (it.get("status") == "SUCCESS")
        st_label = "OK" if is_ok else "FAILED"
        sz = it.get("size", "0 B") if is_ok else "-"
        lines_art.append(f"{cat:<10} {st_label:<8} {sz}")
        fname = it.get("file")
        if is_ok and fname and fname != "-":
            files.append(fname)
        if not is_ok:
            err_msg = it.get("error") or "Unknown error"
            errors.append(f"{cat}: {err_msg}")

    res_str = f"{succeeded} of {total} succeeded"
    site_clean_dir = str(site_res).replace(" ", "_")
    loc_str = f"/backups/{site_clean_dir}/{dev_name_res}/"

    files_block = "\n".join(files) if files else "None"
    errors_block = "\n".join(errors) if errors else "None"

    body_content = (
        "\n".join(lines_meta) + "\n\n"
        + "\n".join(lines_art) + "\n\n"
        + f"{'Result':<10} {res_str}\n"
        + f"{'Location':<10} {loc_str}\n\n"
        + "Files\n" + files_block + "\n\n"
        + "Errors\n" + errors_block
    )

    report_text = f"{header}\n\n<pre>\n{body_content}\n</pre>"

    await progress_msg.edit_text(report_text, parse_mode=ParseMode.HTML)
    log_telegram_message(
        chat_id=str(update.effective_chat.id),
        message_type="COMMAND_REPLY",
        content=f"Backup & Log Archive for {device_name} executed by @{operator_user}.",
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
                "• Diizinkan: /status, /devices, /device, /alerts, /user, /start, /ack, /backup\n"
                "• Ditolak: -\n\n"
                f"Terdaftar sejak: <code>{entry.registered_at.strftime('%Y-%m-%d')}</code>"
            )
            log_telegram_message(update.effective_chat.id, "COMMAND_REPLY", f"Response /user: Engineer profile check for @{raw_username or full_name} (ID: {user_id})")
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
            "• Diizinkan: /status, /devices, /device, /alerts, /user, /start\n"
            "• Ditolak: /ack, /backup\n\n"
            "Untuk mendaftarkan akun ke Whitelist, hubungi admin untuk di-approve via username Telegram Anda."
        )
        await update.message.reply_text(reply_msg, parse_mode=ParseMode.HTML)

    except Exception as e:
        try:
            session.rollback()
        except Exception:
            pass
        logger.error(f"Error handling /user command: {e}")
        await update.message.reply_text(f"Gagal memuat profil: {e}")
    finally:
        session.close()
        db_session.remove()


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

    # Ambil parameter target (@username) dan custom role
    target = None
    custom_role = None

    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        replied_user = update.message.reply_to_message.from_user
        if not replied_user.username:
            await update.message.reply_text(
                "Registrasi ditolak. Wajib menggunakan username dan role.\n\n"
                "Gunakan format: /approve @username [role].",
                parse_mode=ParseMode.HTML
            )
            return
        target = f"@{replied_user.username}"
        if context.args:
            custom_role = " ".join(context.args).strip()
    elif context.args:
        target = context.args[0].strip()
        if len(context.args) > 1:
            custom_role = " ".join(context.args[1:]).strip()

    if not target or not target.startswith("@") or target.lstrip("@").strip().isdigit():
        await update.message.reply_text(
            "Registrasi ditolak. Wajib menggunakan username dan role.\n\n"
            "Gunakan format: /approve @username [role].",
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

        # Jika belum ada di database, buat record baru dengan placeholder pending
        new_entry = TelegramWhitelist(
            chat_id=f"Pending_{clean_target[:35]}",
            telegram_username=username_tag,
            engineer_name=eng_name,
            role=eng_role,
            is_active=True
        )
        session.add(new_entry)
        session.commit()

        msg = f"Akun {html.escape(username_tag)} berhasil di-approve sebagai {html.escape(eng_role)}."
        await update.message.reply_text(msg)
        log_telegram_message(update.effective_chat.id, "COMMAND_REPLY", f"Response /approve: Account {username_tag} approved as {eng_role} by Admin")

    except Exception as e:
        try:
            session.rollback()
        except Exception:
            pass
        logger.error(f"Error handling /approve: {e}")
        await update.message.reply_text(f"Gagal melakukan approval: {e}")
    finally:
        session.close()
        db_session.remove()


# ==================== MAIN APPLICATION INITIALIZATION ====================

async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Menangkap semua exception agar bot tetap berjalan tanpa crash"""
    logger.error(f"Global Error Handler caught: {context.error}")

import atexit

def mark_bot_offline():
    """Menulis status OFFLINE ke heartbeat file agar dashboard segera mendeteksi bot mati"""
    try:
        hb_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs', 'bot_heartbeat.json')
        if os.path.exists(hb_path):
            with open(hb_path, 'w') as f:
                json.dump({'timestamp': 0, 'status': 'OFFLINE', 'pid': None}, f)
    except Exception:
        pass

atexit.register(mark_bot_offline)

def start_local_heartbeat():
    """Menulis heartbeat file lokal agar dashboard lokal dapat memantau status bot saat dijalankan di lokal"""
    def _worker():
        hb_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
        os.makedirs(hb_dir, exist_ok=True)
        hb_path = os.path.join(hb_dir, 'bot_heartbeat.json')
        while True:
            try:
                with open(hb_path, 'w') as f:
                    json.dump({'timestamp': time.time(), 'status': 'ONLINE', 'pid': os.getpid()}, f)
            except Exception:
                pass
            time.sleep(5)
    t = threading.Thread(target=_worker, daemon=True)
    t.start()

def main():
    if not BOT_TOKEN:
        print("[Critical] TELEGRAM_BOT_TOKEN belum diset di file .env!")
        return

    start_local_heartbeat()

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
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("devices", devices_command))
    app.add_handler(CommandHandler("device", device_command))
    app.add_handler(CommandHandler("alerts", alerts_command))
    app.add_handler(CommandHandler("ack", ack_command))
    app.add_handler(MessageHandler(filters.Regex(r'^/ack_?\d+'), ack_command))
    app.add_handler(CommandHandler("resolve", resolve_command))
    app.add_handler(MessageHandler(filters.Regex(r'^/resolve_?\d+'), resolve_command))
    app.add_handler(CommandHandler("backup", backup_command))
    app.add_handler(CommandHandler("user", user_command))
    app.add_handler(CommandHandler("approve", approve_command))

    # Automated Background Data Collector Scheduler dinonaktifkan (Manual Resolve Only)
    # if app.job_queue:
    #     app.job_queue.run_repeating(auto_collector_job, interval=25, first=10)
    #     logger.info("Background Automated Data Collector Scheduler initialized (interval: 25s)")

    # Global Error Handler
    app.add_error_handler(global_error_handler)

    try:
        app.run_polling()
    except (KeyboardInterrupt, SystemExit):
        print("\n[*] Bot engine dihentikan oleh pengguna.")
    finally:
        mark_bot_offline()
        print("[*] Status bot dicatat sebagai OFFLINE.")

if __name__ == "__main__":
    main()
