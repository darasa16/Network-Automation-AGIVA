from dotenv import load_dotenv
load_dotenv(override=True)
import os
import random
import json
import re
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify, request, redirect
from database import db_session, init_db
from models import Device, DeviceStatusLog, Alert, TelegramWhitelist, TelegramMessageLog, BackupHistory

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'agiva-noc-secret-key-2026')

# Initialize DB tables and seed data
init_db()


def send_telegram_broadcast(message_text, parse_mode='HTML'):
    load_dotenv(override=True)
    """Mengirim pesan broadcast langsung ke grup Telegram NOC resmi."""
    tg_token = os.getenv('TELEGRAM_BOT_TOKEN')
    tg_chat_id = os.getenv('NOC_TELEGRAM_CHAT_ID', '-1004429503436')
    if not tg_token or tg_token.startswith('123456'):
        return False, 'Token Telegram belum diset di .env'

    try:
        url = f'https://api.telegram.org/bot{tg_token}/sendMessage'
        payload = {
            'chat_id': tg_chat_id,
            'text': message_text,
            'parse_mode': parse_mode
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return True, 'SENT'
    except Exception as e:
        return False, f'FAILED: {str(e)[:90]}'

@app.teardown_appcontext
def shutdown_session(exception=None):
    db_session.remove()

@app.context_processor
def inject_global_vars():
    session = db_session()
    active_alerts_count = session.query(Alert).filter(Alert.acknowledged == False).count()
    devices = session.query(Device).all()
    nav_devices = [d.to_dict() for d in devices]
    return dict(
        active_alerts_count=active_alerts_count,
        nav_devices=nav_devices
    )

def get_aggregated_chart_history(range_mode='live', session=None):
    """
    Mengambil data histori metrik agregat riil dari database (DeviceStatusLog).
    Mendukung rentang waktu:
    - 'live': 10-12 siklus terakhir (~20-24 menit) dengan jeda 2 menit (%H:%M:%S)
    - '1h': Seluruh data 1 jam kebelakang (%H:%M)
    - '12h': Seluruh data 12 jam kebelakang (%H:%M)
    - '24h': Seluruh data 24 jam kebelakang (%d/%m %H:%M atau %H:%M)
    """
    close_session = False
    if session is None:
        session = db_session()
        close_session = True

    now = datetime.now()

    if range_mode == '1h':
        cutoff = now - timedelta(hours=1)
        bucket_seconds = 120   # 2 menit data mentah (~30 titik)
    elif range_mode == '12h':
        cutoff = now - timedelta(hours=12)
        bucket_seconds = 120   # 2 menit data mentah (~360 titik)
    elif range_mode == '24h':
        cutoff = now - timedelta(hours=24)
        bucket_seconds = 120   # 2 menit data mentah (~720 titik)
    else:  # 'live'
        cutoff = now - timedelta(minutes=24)
        bucket_seconds = 120   # 2 menit (max 12 titik)

    logs = session.query(DeviceStatusLog).filter(
        DeviceStatusLog.timestamp >= cutoff
    ).order_by(DeviceStatusLog.timestamp.asc()).all()

    limit_fallback = 720 if range_mode == '24h' else (360 if range_mode == '12h' else (60 if range_mode == '1h' else 36))
    if len(logs) < 6:
        # Fallback to latest rows if database has fewer historical rows in cutoff
        logs = session.query(DeviceStatusLog).order_by(
            DeviceStatusLog.timestamp.desc()
        ).limit(limit_fallback).all()
        logs.reverse()

    if not logs:
        if close_session:
            session.close()
        return {
            "range": range_mode,
            "labels": [now.strftime('%H:%M:%S')],
            "cpu": [0.0],
            "mem": [0.0],
            "ingress": [0.0],
            "egress": [0.0]
        }

    # Group into exact 2-minute cycle keys (tanpa perataan waktu multi-siklus)
    buckets = defaultdict(list)
    for l in logs:
        cycle_key = int(l.timestamp.timestamp()) // bucket_seconds
        buckets[cycle_key].append(l)

    labels = []
    cpu_vals = []
    mem_vals = []
    ing_vals = []
    eg_vals = []

    for key in sorted(buckets.keys()):
        cycle_logs = buckets[key]
        dt = datetime.fromtimestamp(key * bucket_seconds)
        if range_mode == '24h':
            lbl = dt.strftime('%d/%m %H:%M') if dt.date() != now.date() else dt.strftime('%H:%M')
        elif range_mode in ['1h', '12h']:
            lbl = dt.strftime('%H:%M')
        else: # 'live'
            lbl = dt.strftime('%H:%M:%S')

        labels.append(lbl)
        up_logs = [x for x in cycle_logs if x.status == 'UP']
        avg_cpu = round(sum(x.cpu_usage for x in up_logs) / len(up_logs), 1) if up_logs else 0.0
        avg_mem = round(sum(x.mem_usage for x in up_logs) / len(up_logs), 1) if up_logs else 0.0

        # Nilai throughput murni siklus 2-menit tersebut (total perangkat)
        tot_ing = round(sum(x.ingress_mbps or 0.0 for x in cycle_logs), 1)
        tot_eg = round(sum(x.egress_mbps or 0.0 for x in cycle_logs), 1)

        cpu_vals.append(avg_cpu)
        mem_vals.append(avg_mem)
        ing_vals.append(tot_ing)
        eg_vals.append(tot_eg)

    if range_mode == 'live' and len(labels) > 12:
        labels = labels[-12:]
        cpu_vals = cpu_vals[-12:]
        mem_vals = mem_vals[-12:]
        ing_vals = ing_vals[-12:]
        eg_vals = eg_vals[-12:]

    if close_session:
        session.close()
    return {
        "range": range_mode,
        "labels": labels,
        "cpu": cpu_vals,
        "mem": mem_vals,
        "ingress": ing_vals,
        "egress": eg_vals
    }

# 1. MONITORING ROUTES
@app.route('/')
@app.route('/index.html')
def dashboard():
    """
    Route: / - Monitoring Dashboard Utama
    Menampilkan ringkasan status perangkat jaringan (UP/DOWN),
    KPI Cards, grafik Chart.js, tabel perangkat, dan panel alert aktif.
    """
    session = db_session()
    devices = session.query(Device).all()
    alerts = session.query(Alert).order_by(Alert.triggered_at.desc()).limit(10).all()

    total_devices = len(devices)
    devices_online = sum(1 for d in devices if d.status == 'UP')
    devices_offline = sum(1 for d in devices if d.status == 'DOWN')
    active_alerts_count = session.query(Alert).filter(Alert.acknowledged == False).count()

    device_list = [d.to_dict() for d in devices]
    alert_list = [a.to_dict() for a in alerts]
    initial_chart_history = get_aggregated_chart_history()

    return render_template(
        'index.html',
        total_devices=total_devices,
        devices_online=devices_online,
        devices_offline=devices_offline,
        active_alerts_count=active_alerts_count,
        devices=device_list,
        alerts=alert_list,
        initial_chart_history=initial_chart_history
    )

from telemetry_helper import get_device_full_telemetry

@app.route('/device/<int:device_id>')
@app.route('/device_detail.html')
def device_detail(device_id=1):
    session = db_session()
    device = session.query(Device).filter(Device.device_id == device_id).first()
    if not device:
        device = session.query(Device).first()
    if not device:
        return "Device not found", 404

    device_alerts = session.query(Alert).filter(Alert.device_id == device.device_id).all()
    alerts_data = [a.to_dict() for a in device_alerts]

    telemetry = get_device_full_telemetry(device)

    return render_template(
        'device_detail.html',
        device=device.to_dict(),
        alerts=alerts_data,
        specs=telemetry.get("hardware", {}),
        vlans=telemetry.get("vlans", []),
        ports=telemetry.get("ports", []),
        summary=telemetry.get("summary", {}),
        resources=telemetry.get("resources", {})
    )

@app.route('/device/index.html')
def redirect_device_index():
    return redirect('/')

@app.route('/device/alerts.html')
def redirect_device_alerts():
    return redirect('/alerts')

@app.route('/device/telegram.html')
def redirect_device_telegram():
    return redirect('/telegram')

@app.route('/device/backups.html')
def redirect_device_backups():
    return redirect('/backups')

# 2. ALERTS ROUTES

@app.route('/alerts')
@app.route('/alerts.html')
def alerts_page():
    session = db_session()
    alerts = session.query(Alert).order_by(Alert.triggered_at.desc()).all()
    alerts_data = [a.to_dict() for a in alerts]
    
    total_alerts = len(alerts)
    pending_alerts = sum(1 for a in alerts if not a.acknowledged)
    acked_alerts = total_alerts - pending_alerts
    
    return render_template(
        'alerts.html', 
        alerts=alerts_data,
        total_alerts=total_alerts,
        pending_alerts=pending_alerts,
        acked_alerts=acked_alerts,
        active_alerts_count=pending_alerts
    )

@app.route('/api/ack/<int:alert_id>', methods=['POST'])
def api_ack_alert(alert_id):
    session = db_session()
    alert = session.query(Alert).filter(Alert.alert_id == alert_id).first()
    if not alert:
        return jsonify({"success": False, "message": "Alert ID tidak ditemukan"}), 404

    alert.acknowledged = True
    alert.acknowledged_by = "Web NOC Admin"

    target_chat_id = os.getenv('NOC_TELEGRAM_CHAT_ID', '-1004429503436')
    ack_content = f"✅ *[NOC AGIVA - ALERT ACKNOWLEDGED]*\n\nAlert #{alert.alert_id} ({alert.type}) pada `{alert.device.name if alert.device else 'Device'}` telah di-acknowledge oleh Web NOC Admin."
    send_telegram_broadcast(ack_content)

    # Catat ke log bot Telegram bahwa alert telah di-ACK
    tg_log = TelegramMessageLog(
        alert_id=alert.alert_id,
        chat_id=target_chat_id,
        message_type="COMMAND_REPLY",
        content=ack_content,
        status="SENT",
        sent_at=datetime.now()
    )
    session.add(tg_log)
    session.commit()

    return jsonify({
        "success": True,
        "alert_id": alert_id,
        "message": f"Alert #{alert_id} berhasil di-acknowledge dan dicatat ke basis data."
    })

# 3. TELEGRAM BOT INTEGRATION ROUTES

@app.route('/telegram')
@app.route('/telegram.html')
def telegram_page():
    """
    Route: /telegram - Panel Integrasi Bot Telegram
    Menampilkan status bot, daftar command NOC, whitelist engineer, dan log pesan terkirim.
    """
    session = db_session()
    # 30-Day Auto Retention: Hapus log berumur lebih dari 30 hari
    cutoff_date = datetime.now() - timedelta(days=30)
    try:
        session.query(TelegramMessageLog).filter(TelegramMessageLog.sent_at < cutoff_date).delete()
        session.commit()
    except Exception:
        session.rollback()

    whitelist = session.query(TelegramWhitelist).order_by(TelegramWhitelist.id.asc()).all()
    msg_logs = session.query(TelegramMessageLog).filter(
        TelegramMessageLog.sent_at >= cutoff_date
    ).order_by(TelegramMessageLog.sent_at.desc(), TelegramMessageLog.id.desc()).all()

    # Cek apakah proses bot.py sedang berjalan di sistem lokal
    bot_is_online = False
    try:
        import subprocess
        result = subprocess.run(
            ['powershell', '-Command',
             "Get-CimInstance Win32_Process -Filter \"name='python.exe'\" | Select-Object -ExpandProperty CommandLine"],
            capture_output=True, text=True, timeout=5
        )
        bot_is_online = 'bot.py' in result.stdout
    except Exception:
        bot_is_online = False

    bot_info = {
        "bot_name": os.getenv('TELEGRAM_BOT_NAME', 'Agiva Network Automation Bot'),
        "username": os.getenv('TELEGRAM_BOT_USERNAME', '@Agiva_Network_Automation_Bot'),
        "status": "ONLINE" if bot_is_online else "OFFLINE",
        "is_online": bot_is_online,
        "chat_group": os.getenv('TELEGRAM_GROUP_NAME', 'Agiva Network Automation Channel'),
        "chat_id": os.getenv('NOC_TELEGRAM_CHAT_ID', '-1004429503436'),
        "active_alerts_pushed": session.query(TelegramMessageLog).filter(TelegramMessageLog.message_type == 'ALERT_NOTIFICATION').count()
    }

    commands = [
        {"command": "/start", "params": "-", "desc": "Memulai interaksi bot dan menampilkan panduan operasional perintah."},
        {"command": "/status", "params": "-", "desc": "Melihat ringkasan status kesehatan seluruh perangkat jaringan dan alert aktif."},
        {"command": "/devices", "params": "-", "desc": "Menampilkan tabel inventaris seluruh perangkat jaringan."},
        {"command": "/device", "params": "<nama_device>", "desc": "Melihat metrik real-time CPU, RAM, & Uptime suatu device tertentu."},
        {"command": "/alerts", "params": "-", "desc": "Menampilkan daftar gangguan dan anomali jaringan aktif yang memerlukan mitigasi."},
        {"command": "/ack", "params": "<alert_id>", "desc": "Melakukan konfirmasi penanganan alert anomali oleh teknisi bertugas."},
        {"command": "/resolve", "params": "<alert_id>", "desc": "Menandai bahwa gangguan jaringan telah selesai ditangani."},
        {"command": "/backup", "params": "<nama_device>", "desc": "Memicu backup running-config manual device tertentu."},
        {"command": "/user", "params": "-", "desc": "Melihat profil teknisi, Chat ID Telegram, dan verifikasi status otorisasi Whitelist."},
        {"command": "/approve", "params": "<username> [role]", "desc": "(Khusus Admin) Menyetujui akses teknisi baru dengan role pilihan."}
    ]

    return render_template(
        'telegram.html',
        bot=bot_info,
        commands=commands,
        whitelist=[w.to_dict() for w in whitelist],
        logs=[l.to_dict() for l in msg_logs]
    )

def trigger_alert_with_antispam(session, device, alert_type, severity, message):
    """
    Rule Engine: Anti-spam Cooldown Logic
    Sesuai LLD: alert yang sama tidak dikirim ulang selama belum resolved,
    dengan cooldown per jenis alert per device.
    """
    # Cek apakah ada alert yang sama dan belum resolved
    existing_alert = session.query(Alert).filter(
        Alert.device_id == device.device_id,
        Alert.type == alert_type,
        Alert.resolved_at == None
    ).first()

    if existing_alert:
        # KONDISI 1: Spam terdeteksi. Jangan kirim pesan.
        return False, existing_alert, "Spam tertahan oleh Anti-spam Cooldown."

    # KONDISI 2: Alert baru, belum ada yang aktif.
    new_alert = Alert(
        device_id=device.device_id,
        type=alert_type,
        severity=severity,
        message=message,
        triggered_at=datetime.now(),
        acknowledged=False
    )
    session.add(new_alert)
    session.flush()

    target_chat_id = os.getenv('NOC_TELEGRAM_CHAT_ID', '-1004429503436')
    
    # Pesan dengan format HTML yang aman untuk karakter underscore dll
    msg_content = (
        f"🚨 <b>[NOC AGIVA - {severity} ALERT]</b> 🚨\n\n"
        f"📌 <b>Alert ID:</b> #{new_alert.alert_id}\n"
        f"📌 <b>Perangkat:</b> {device.name} ({device.ip_address})\n"
        f"📌 <b>Tipe Error:</b> {alert_type}\n"
        f"📌 <b>Pesan:</b> {new_alert.message}\n"
        f"📌 <b>Waktu:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} WIB\n\n"
        f"💡 Ketik /ack {new_alert.alert_id} di bot untuk konfirmasi penanganan."
    )
    
    ok, delivery_status = send_telegram_broadcast(msg_content, parse_mode='HTML')

    # Log dispatch ke bot telegram
    status_str = "SENT" if ok else str(delivery_status)[:90]
    log_entry = TelegramMessageLog(
        alert_id=new_alert.alert_id,
        chat_id=target_chat_id,
        message_type="ALERT_NOTIFICATION",
        content=msg_content,
        status=status_str,
        sent_at=datetime.now()
    )
    session.add(log_entry)
    session.commit()
    
    return True, new_alert, "Alert baru berhasil dikirim."

@app.route('/api/telegram/logs', methods=['GET'])
def api_telegram_logs():
    """Endpoint untuk mengecek riwayat log Telegram (Auto-refresh & 30-day retention)"""
    session = db_session()
    cutoff_date = datetime.now() - timedelta(days=30)
    try:
        session.query(TelegramMessageLog).filter(TelegramMessageLog.sent_at < cutoff_date).delete()
        session.commit()
    except Exception:
        session.rollback()

    msg_logs = session.query(TelegramMessageLog).filter(
        TelegramMessageLog.sent_at >= cutoff_date
    ).order_by(TelegramMessageLog.sent_at.desc(), TelegramMessageLog.id.desc()).all()
    active_alerts_pushed = session.query(TelegramMessageLog).filter(
        TelegramMessageLog.message_type == 'ALERT_NOTIFICATION',
        TelegramMessageLog.sent_at >= cutoff_date
    ).count()
    
    # Format the logs so it's easier to consume on the frontend
    logs_data = []
    for l in msg_logs:
        logs_data.append({
            "id": l.id,
            "sent_at": l.sent_at.strftime("%Y-%m-%d %H:%M:%S") if l.sent_at else "",
            "type": l.message_type,
            "chat_id": l.chat_id,
            "content": l.content,
            "status": l.status
        })
    session.close()
    
    return jsonify({
        "logs": logs_data,
        "active_alerts_pushed": active_alerts_pushed
    })

@app.route('/api/telegram/test-alert', methods=['POST'])
def api_test_telegram_alert():
    """
    Diagnostic Test: Memastikan Telegram Bot API aktif.
    """
    session = db_session()
    tg_chat_id = os.getenv('NOC_TELEGRAM_CHAT_ID', '-1004429503436')
    
    msg_content = (
        "*TEST CONNECTIVITY*\n\n"
        "Ini adalah pesan diagnostik uji coba Ping dari Dashboard.\n"
        "Jalur komunikasi Telegram Bot berfungsi dengan sangat baik.\n"
        f"Waktu: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} WIB"
    )
    
    ok, delivery_status = send_telegram_broadcast(msg_content)
    
    # Catat ke dispatch log agar terlihat di Dashboard
    log_entry = TelegramMessageLog(
        alert_id=None,
        chat_id=tg_chat_id,
        message_type="DIAGNOSTIC_TEST",
        content=msg_content,
        status="SENT" if ok else delivery_status,
        sent_at=datetime.now()
    )
    session.add(log_entry)
    session.commit()
    session.close()

    if ok:
        return jsonify({"success": True, "message": "Pesan Test Connectivity berhasil dikirim!"})
    else:
        return jsonify({"success": False, "message": f"Gagal: {delivery_status}"}), 500

# 4. BACKUP ROUTE

@app.route('/backups')
@app.route('/backups.html')
@app.route('/backup.html')
@app.route('/backupfile.html')
def backups_page():
    """Route: /backups - Riwayat backup konfigurasi harian"""
    session = db_session()
    backups = session.query(BackupHistory).order_by(BackupHistory.timestamp.desc()).all()
    backups_data = []
    for b in backups:
        backups_data.append({
            "id": b.backup_id,
            "device": b.device.name if b.device else "Unknown",
            "site": b.device.site if b.device else "-",
            "date": b.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "file": b.file_path,
            "size": b.file_size,
            "status": b.status
        })
    return render_template('backups.html', backups=backups_data)

# 5. REAL-TIME JSON APIS FOR DASHBOARD POLLING & OMNI-SEARCH

@app.route('/api/search')
def api_search():
    """
    Pattern 3: Omni-Search / Command Palette API
    Mencari secara serentak ke:
    1. Perangkat Jaringan (Devices)
    2. Alerts & Anomali (Alerts)
    3. File Backup Konfigurasi (Backup History)
    4. Navigasi Cepat (Pages & Menus)
    """
    q = request.args.get('q', '').strip()
    if not q or len(q) < 1:
        return jsonify({
            "query": "",
            "total_results": 0,
            "categories": {
                "devices": [],
                "alerts": [],
                "backups": [],
                "telegram": [],
                "navigation": []
            }
        })

    session = db_session()
    ql = q.lower()
    
    # 1. Devices matching name, IP, vendor, site, or status
    all_devs = session.query(Device).all()
    matched_devices = []
    for d in all_devs:
        if (ql in d.name.lower() or 
            ql in d.ip_address.lower() or 
            ql in d.vendor.lower() or 
            ql in d.site.lower() or
            ql == d.status.lower()):
            matched_devices.append({
                "id": d.device_id,
                "name": d.name,
                "ip": d.ip_address,
                "vendor": d.vendor,
                "site": d.site,
                "status": d.status,
                "url": f"/device/{d.device_id}#deviceHeaderCard"
            })

    # 2. Alerts matching type, message, severity, or device name
    all_alerts = session.query(Alert).order_by(Alert.alert_id.desc()).limit(50).all()
    matched_alerts = []
    for a in all_alerts:
        dev_name = a.device.name.lower() if a.device else ""
        if (ql in a.type.lower() or 
            ql in a.message.lower() or 
            ql in a.severity.lower() or 
            ql in dev_name):
            matched_alerts.append({
                "id": a.alert_id,
                "type": a.type,
                "severity": a.severity,
                "message": a.message[:75] + ("..." if len(a.message) > 75 else ""),
                "device_name": a.device.name if a.device else "Unknown Device",
                "triggered_at": a.triggered_at.strftime("%d/%m %H:%M") if a.triggered_at else "-",
                "acknowledged": a.acknowledged,
                "url": f"/alerts#alert-row-{a.alert_id}"
            })
            if len(matched_alerts) >= 5:
                break

    # 3. Backups matching file_path, status, device name, or site
    all_backups = session.query(BackupHistory).order_by(BackupHistory.backup_id.desc()).limit(50).all()
    matched_backups = []
    for b in all_backups:
        dev_name = b.device.name.lower() if b.device else ""
        dev_site = b.device.site.lower() if b.device and b.device.site else ""
        file_name = os.path.basename(b.file_path)
        if (ql in file_name.lower() or 
            ql in dev_name or 
            ql in dev_site or
            ql in b.status.lower()):
            matched_backups.append({
                "id": b.backup_id,
                "file_name": file_name,
                "device_name": b.device.name if b.device else "Unknown Device",
                "site": b.device.site if b.device and b.device.site else "-",
                "date": b.timestamp.strftime("%d/%m %H:%M") if b.timestamp else "-",
                "size": b.file_size,
                "status": b.status,
                "url": f"/backups#backup-row-{b.backup_id}"
            })
            if len(matched_backups) >= 5:
                break

    # 4. Telegram Whitelist & Bot Commands matching engineer, username, role, or command
    all_tg_users = session.query(TelegramWhitelist).all()
    matched_telegram = []
    for u in all_tg_users:
        if (ql in u.engineer_name.lower() or 
            ql in u.telegram_username.lower() or 
            ql in u.role.lower() or
            ql in str(u.chat_id)):
            matched_telegram.append({
                "id": u.id,
                "title": f"{u.engineer_name} ({u.telegram_username})",
                "desc": f"Role: {u.role} • Chat ID: {u.chat_id}",
                "status": "ACTIVE" if u.is_active else "INACTIVE",
                "url": f"/telegram#whitelist-row-{u.id}"
            })
            if len(matched_telegram) >= 4:
                break

    tg_commands = [
        {"cmd": "/start", "desc": "Memulai interaksi bot & panduan operasional"},
        {"cmd": "/status", "desc": "Ringkasan status kesehatan seluruh perangkat"},
        {"cmd": "/devices", "desc": "Tabel inventaris seluruh perangkat jaringan"},
        {"cmd": "/device", "desc": "Metrik real-time CPU, RAM, & Uptime suatu device"},
        {"cmd": "/alerts", "desc": "Daftar gangguan & anomali jaringan aktif"},
        {"cmd": "/ack", "desc": "Konfirmasi penanganan alert oleh teknisi"},
        {"cmd": "/resolve", "desc": "Tandai gangguan jaringan telah selesai"},
        {"cmd": "/backup", "desc": "Memicu backup running-config manual"},
        {"cmd": "/user", "desc": "Profil teknisi & verifikasi Whitelist"},
        {"cmd": "/approve", "desc": "Menyetujui akses teknisi baru"}
    ]
    for c in tg_commands:
        if len(matched_telegram) >= 6:
            break
        if (ql in c["cmd"].lower() or 
            ql in c["desc"].lower() or 
            (ql.startswith('/') and ql in c["cmd"].lower())):
            clean_cmd = c["cmd"].replace('/', '')
            matched_telegram.append({
                "id": c["cmd"],
                "title": f"Perintah Bot: {c['cmd']}",
                "desc": c["desc"],
                "status": "COMMAND",
                "url": f"/telegram#cmd-row-{clean_cmd}"
            })

    # c. Message Dispatch Logs (Riwayat Pengiriman Pesan & Notifikasi Telegram)
    msg_logs = session.query(TelegramMessageLog).order_by(TelegramMessageLog.sent_at.desc(), TelegramMessageLog.id.desc()).limit(100).all()
    for m in msg_logs:
        if len(matched_telegram) >= 8:
            break
        if (ql in m.content.lower() or 
            ql in m.message_type.lower() or 
            ql in str(m.chat_id)):
            clean_content = re.sub(r'<[^>]+>', '', m.content).strip()
            clean_content = ' '.join(clean_content.split())
            snippet = clean_content[:65] + ("..." if len(clean_content) > 65 else "")
            time_str = m.sent_at.strftime("%d/%m %H:%M") if m.sent_at else "-"
            matched_telegram.append({
                "id": m.id,
                "title": f"Log: {snippet}",
                "desc": f"{m.message_type} • Chat ID: {m.chat_id} • {time_str}",
                "status": m.status or "SENT",
                "url": f"/telegram#msglog-row-{m.id}"
            })

    # 5. Quick Navigation Menus
    navigation_items = [
        {
            "title": "Dashboard Monitoring",
            "desc": "Grafik metrik real-time dan inventaris seluruh perangkat",
            "category": "Menu Navigasi",
            "keywords": ["dashboard", "monitoring", "home", "beranda", "grafik", "metrik", "switch", "traffic", "cpu"],
            "url": "/"
        },
        {
            "title": "Pusat Alert & Insiden",
            "desc": "Daftar alarm gangguan dan konfirmasi penanganan",
            "category": "Menu Navigasi",
            "keywords": ["alert", "alerts", "insiden", "incident", "alarm", "anomali", "ack", "notif", "peringatan"],
            "url": "/alerts"
        },
        {
            "title": "Backup Konfigurasi",
            "desc": "Manajemen riwayat file backup running-config perangkat",
            "category": "Menu Navigasi",
            "keywords": ["backup", "backups", "cadangan", "config", "konfigurasi", "file", "download", "diff"],
            "url": "/backups"
        },
        {
            "title": "Integrasi Bot Telegram",
            "desc": "Panel kontrol bot, whitelist teknisi, dan audit log dispatch",
            "category": "Menu Navigasi",
            "keywords": ["telegram", "bot", "whitelist", "chat", "command", "perintah", "teknisi", "noc"],
            "url": "/telegram"
        }
    ]
    matched_nav = []
    for nav in navigation_items:
        if (ql in nav["title"].lower() or 
            ql in nav["desc"].lower() or 
            any(ql in k for k in nav["keywords"])):
            matched_nav.append(nav)

    total_count = len(matched_devices) + len(matched_alerts) + len(matched_backups) + len(matched_telegram) + len(matched_nav)

    return jsonify({
        "query": q,
        "total_results": total_count,
        "categories": {
            "devices": matched_devices,
            "alerts": matched_alerts,
            "backups": matched_backups,
            "telegram": matched_telegram,
            "navigation": matched_nav
        }
    })

@app.route('/api/status')
def api_status():
    """
    Endpoint JSON real-time untuk polling frontend Chart.js & tabel status.
    Mendukung parameter ?range=live|1h|12h|24h untuk histori rentang waktu.
    """
    session = db_session()
    range_mode = request.args.get('range', 'live')
    devices = session.query(Device).all()
    active_alerts = session.query(Alert).filter(Alert.acknowledged == False).all()

    online_devs = [d for d in devices if d.status == 'UP']
    avg_cpu = round(sum(d.cpu_usage for d in online_devs) / len(online_devs), 1) if online_devs else 0
    avg_mem = round(sum(d.mem_usage for d in online_devs) / len(online_devs), 1) if online_devs else 0
    total_trf = round(sum(d.traffic_mbps for d in online_devs), 1)
    ingress_trf = round(sum((getattr(d, 'ingress_mbps', None) if getattr(d, 'ingress_mbps', None) is not None and getattr(d, 'ingress_mbps', None) > 0 else (d.traffic_mbps * 0.65)) for d in online_devs), 1)
    egress_trf = round(sum((getattr(d, 'egress_mbps', None) if getattr(d, 'egress_mbps', None) is not None and getattr(d, 'egress_mbps', None) > 0 else (d.traffic_mbps * 0.35)) for d in online_devs), 1)

    devices_data = [d.to_dict() for d in devices]
    alerts_data = [a.to_dict() for a in active_alerts]
    history_data = get_aggregated_chart_history(range_mode, session=session)
    session.close()

    return jsonify({
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "range": range_mode,
        "summary": {
            "total_devices": len(devices),
            "devices_online": len(online_devs),
            "devices_offline": len(devices) - len(online_devs),
            "active_alerts": len(active_alerts)
        },
        "metrics": {
            "avg_cpu": avg_cpu,
            "avg_mem": avg_mem,
            "total_traffic": total_trf,
            "ingress_traffic": ingress_trf,
            "egress_traffic": egress_trf
        },
        "history": history_data,
        "devices": devices_data,
        "alerts": alerts_data
    })

@app.route('/api/device/<int:device_id>/metrics')
def api_device_metrics(device_id):
    """Data histori time-series (live, 1h, 12h, 24h) untuk Chart.js di halaman detail perangkat."""
    session = db_session()
    device = session.query(Device).filter(Device.device_id == device_id).first()
    if not device:
        session.close()
        return jsonify({"error": "Device not found"}), 404

    range_mode = request.args.get('range', 'live')
    now = datetime.now()

    if range_mode == '1h':
        cutoff = now - timedelta(hours=1)
        bucket_seconds = 120   # 2 menit data mentah (~30 titik)
    elif range_mode == '12h':
        cutoff = now - timedelta(hours=12)
        bucket_seconds = 120   # 2 menit data mentah (~360 titik)
    elif range_mode == '24h':
        cutoff = now - timedelta(hours=24)
        bucket_seconds = 120   # 2 menit data mentah (~720 titik)
    else:  # 'live'
        cutoff = now - timedelta(minutes=24)
        bucket_seconds = 120   # 2 menit (max 12 titik)

    logs = session.query(DeviceStatusLog).filter(
        DeviceStatusLog.device_id == device_id,
        DeviceStatusLog.timestamp >= cutoff
    ).order_by(DeviceStatusLog.timestamp.asc()).all()

    limit_fallback = 720 if range_mode == '24h' else (360 if range_mode == '12h' else (60 if range_mode == '1h' else 12))
    if len(logs) < 6:
        # Fallback to latest available logs for this device
        logs = session.query(DeviceStatusLog).filter(
            DeviceStatusLog.device_id == device_id
        ).order_by(DeviceStatusLog.timestamp.desc()).limit(limit_fallback).all()
        logs.reverse()

    if not logs:
        labels = [now.strftime("%H:%M:%S")]
        cpu_vals = [round(device.cpu_usage or 0.0, 1)]
        mem_vals = [round(device.mem_usage or 0.0, 1)]
        trf_vals = [round(device.traffic_mbps or 0.0, 2)]
        trf_in_vals = [round(device.ingress_mbps or 0.0, 2)]
        trf_out_vals = [round(device.egress_mbps or 0.0, 2)]
    else:
        # Group into exact 2-minute cycle keys (data mentah asli tanpa perataan)
        buckets = defaultdict(list)
        for l in logs:
            cycle_key = int(l.timestamp.timestamp()) // bucket_seconds
            buckets[cycle_key].append(l)

        labels = []
        cpu_vals = []
        mem_vals = []
        trf_vals = []
        trf_in_vals = []
        trf_out_vals = []
        for key in sorted(buckets.keys()):
            b_logs = buckets[key]
            dt = datetime.fromtimestamp(key * bucket_seconds)
            if range_mode == '24h':
                lbl = dt.strftime('%d/%m %H:%M') if dt.date() != now.date() else dt.strftime('%H:%M')
            elif range_mode in ['1h', '12h']:
                lbl = dt.strftime('%H:%M')
            else:  # live
                lbl = dt.strftime('%H:%M:%S')
            labels.append(lbl)
            # Ambil data mentah riil siklus tersebut
            b = b_logs[-1]
            cpu_vals.append(round(b.cpu_usage or 0.0, 1))
            mem_vals.append(round(b.mem_usage or 0.0, 1))
            trf_vals.append(round(b.traffic_mbps or 0.0, 2))
            trf_in_vals.append(round(b.ingress_mbps or 0.0, 2))
            trf_out_vals.append(round(b.egress_mbps or 0.0, 2))

        if range_mode == 'live' and len(labels) > 12:
            labels = labels[-12:]
            cpu_vals = cpu_vals[-12:]
            mem_vals = mem_vals[-12:]
            trf_vals = trf_vals[-12:]
            trf_in_vals = trf_in_vals[-12:]
            trf_out_vals = trf_out_vals[-12:]

    telemetry = get_device_full_telemetry(device)
    res = telemetry.get("resources", {})
    pb_base = float(res.get("packet_buffers_pct", 31.0))
    mb_base = float(res.get("message_buffers_pct", 22.0))
    td_val = int(res.get("tx_drops", 0))
    re_val = int(res.get("rx_errors", 0))
    te_val = int(res.get("tx_errors", 0))

    packet_buffers_vals = [pb_base for _ in labels]
    tx_drops_vals = [td_val for _ in labels]
    message_buffers_vals = [mb_base for _ in labels]
    rx_errors_vals = [re_val for _ in labels]
    tx_errors_vals = [te_val for _ in labels]

    result = {
        "device_id": device_id,
        "name": device.name,
        "status": device.status,
        "uptime": device.uptime,
        "range": range_mode,
        "current_cpu": device.cpu_usage,
        "current_memory": device.mem_usage,
        "current_traffic": round(device.traffic_mbps or 0.0, 2),
        "current_traffic_in": round(device.ingress_mbps or 0.0, 2),
        "current_traffic_out": round(device.egress_mbps or 0.0, 2),
        "current_packet_buffers": pb_base,
        "current_tx_drops": td_val,
        "current_message_buffers": mb_base,
        "current_rx_errors": re_val,
        "current_tx_errors": te_val,
        "labels": labels,
        "cpu": cpu_vals,
        "memory": mem_vals,
        "traffic": trf_vals,
        "traffic_in": trf_in_vals,
        "traffic_out": trf_out_vals,
        "packet_buffers": packet_buffers_vals,
        "tx_drops": tx_drops_vals,
        "message_buffers": message_buffers_vals,
        "rx_errors": rx_errors_vals,
        "tx_errors": tx_errors_vals,
        "resources": res,
        "specs": telemetry.get("hardware", {}),
        "vlans": telemetry.get("vlans", []),
        "ports": telemetry.get("ports", []),
    }
    session.close()
    return jsonify(result)

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    print(f"[*] Starting PT Agiva Network Operations Dashboard on http://127.0.0.1:{port}")
    app.run(host='0.0.0.0', port=port, debug=True)

# PostgreSQL reload trigger
