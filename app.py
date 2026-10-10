from dotenv import load_dotenv
load_dotenv(override=True)
import os
import random
import json
import urllib.request
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify, request
from database import db_session, init_db
from models import Device, DeviceStatusLog, Alert, TelegramWhitelist, TelegramMessageLog, BackupHistory

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'agiva-noc-secret-key-2026')

# Initialize DB tables and seed data
init_db()


def send_telegram_broadcast(message_text):
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
            'parse_mode': 'Markdown'
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return True, 'SENT'
    except Exception as e:
        return False, f'FAILED: {str(e)[:40]}'

@app.teardown_appcontext
def shutdown_session(exception=None):
    db_session.remove()

@app.context_processor
def inject_global_vars():
    session = db_session()
    active_alerts_count = session.query(Alert).filter(Alert.acknowledged == False).count()
    return dict(active_alerts_count=active_alerts_count)

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

    return render_template(
        'index.html',
        total_devices=total_devices,
        devices_online=devices_online,
        devices_offline=devices_offline,
        active_alerts_count=active_alerts_count,
        devices=device_list,
        alerts=alert_list
    )

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

    return render_template('device_detail.html', device=device.to_dict(), alerts=alerts_data)

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
    whitelist = session.query(TelegramWhitelist).order_by(TelegramWhitelist.id.asc()).all()
    msg_logs = session.query(TelegramMessageLog).order_by(TelegramMessageLog.id.desc()).limit(20).all()

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
        {"command": "/status", "params": "-", "desc": "Melihat ringkasan status kesehatan seluruh perangkat jaringan (UP/DOWN) & alert aktif."},
        {"command": "/devices", "params": "-", "desc": "Menampilkan tabel inventaris seluruh perangkat jaringan (Node, IP, Vendor, Site)."},
        {"command": "/device", "params": "<nama_device>", "desc": "Melihat metrik real-time CPU, RAM, & Uptime satu router/switch (Contoh: /device RTR-Core-01)."},
        {"command": "/alerts", "params": "-", "desc": "Menampilkan daftar gangguan dan anomali jaringan aktif yang memerlukan mitigasi."},
        {"command": "/ack", "params": "<alert_id>", "desc": "Melakukan konfirmasi (Acknowledge) penanganan alert anomali oleh teknisi bertugas."},
        {"command": "/resolve", "params": "<alert_id>", "desc": "Menandai bahwa gangguan jaringan telah dipulihkan (Resolved)."},
        {"command": "/backup", "params": "<nama_device>", "desc": "Memicu backup running-config manual seketika lewat SSH/API ke Git repo."},
        {"command": "/user", "params": "-", "desc": "Melihat profil teknisi, Chat ID Telegram, dan verifikasi status otorisasi Whitelist tim NOC."},
        {"command": "/approve", "params": "<username> [role]", "desc": "(Khusus Admin) Menyetujui akses teknisi baru dengan role pilihan (default: Network Engineer (Member))."},
        {"command": "/help", "params": "-", "desc": "Menampilkan panduan operasional perintah bot tim NOC."}
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
    
    # Pesan dengan emoji yang aman
    msg_content = (
        f"🚨 *[NOC AGIVA - {severity} ALERT]* 🚨\n\n"
        f"📌 *Alert ID:* #{new_alert.alert_id}\n"
        f"📌 *Perangkat:* {device.name} ({device.ip_address})\n"
        f"📌 *Tipe Error:* {alert_type}\n"
        f"📌 *Pesan:* {new_alert.message}\n"
        f"📌 *Waktu:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} WIB\n\n"
        f"💡 Ketik /ack {new_alert.alert_id} di bot untuk konfirmasi penanganan."
    )
    
    ok, delivery_status = send_telegram_broadcast(msg_content)

    # Log dispatch ke bot telegram
    log_entry = TelegramMessageLog(
        alert_id=new_alert.alert_id,
        chat_id=target_chat_id,
        message_type="ALERT_NOTIFICATION",
        content=msg_content,
        status="SENT" if ok else delivery_status,
        sent_at=datetime.now()
    )
    session.add(log_entry)
    session.commit()
    
    return True, new_alert, "Alert baru berhasil dikirim."

@app.route('/api/telegram/logs', methods=['GET'])
def api_telegram_logs():
    """Endpoint untuk mengecek riwayat log Telegram (Auto-refresh)"""
    session = db_session()
    msg_logs = session.query(TelegramMessageLog).order_by(TelegramMessageLog.id.desc()).limit(20).all()
    active_alerts_pushed = session.query(TelegramMessageLog).filter(TelegramMessageLog.message_type == 'ALERT_NOTIFICATION').count()
    
    # Format the logs so it's easier to consume on the frontend
    logs_data = []
    for l in msg_logs:
        logs_data.append({
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

# 5. REAL-TIME JSON APIS FOR DASHBOARD POLLING

@app.route('/api/status')
def api_status():
    """
    Endpoint JSON real-time untuk polling frontend Chart.js & tabel status.
    Melakukan variasi simulasi halus pada metrik aktif agar grafik hidup.
    """
    session = db_session()
    devices = session.query(Device).all()
    active_alerts = session.query(Alert).filter(Alert.acknowledged == False).all()

    # Murni membaca data DB (Collector sejati akan mengupdate ini dari luar)

    online_devs = [d for d in devices if d.status == 'UP']
    avg_cpu = round(sum(d.cpu_usage for d in online_devs) / len(online_devs), 1) if online_devs else 0
    avg_mem = round(sum(d.mem_usage for d in online_devs) / len(online_devs), 1) if online_devs else 0
    total_trf = round(sum(d.traffic_mbps for d in online_devs), 1)

    return jsonify({
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "summary": {
            "total_devices": len(devices),
            "devices_online": len(online_devs),
            "devices_offline": len(devices) - len(online_devs),
            "active_alerts": len(active_alerts)
        },
        "metrics": {
            "avg_cpu": avg_cpu,
            "avg_mem": avg_mem,
            "total_traffic": total_trf
        },
        "devices": [d.to_dict() for d in devices],
        "alerts": [a.to_dict() for a in active_alerts]
    })

@app.route('/api/device/<int:device_id>/metrics')
def api_device_metrics(device_id):
    """Data histori time-series 12 jam untuk Chart.js di halaman detail perangkat."""
    session = db_session()
    device = session.query(Device).filter(Device.device_id == device_id).first()
    if not device:
        return jsonify({"error": "Device not found"}), 404

    logs = session.query(DeviceStatusLog).filter(DeviceStatusLog.device_id == device_id).order_by(DeviceStatusLog.timestamp.asc()).all()

    labels = [l.timestamp.strftime("%H:%M") for l in logs]
    cpu_vals = [l.cpu_usage for l in logs]
    mem_vals = [l.mem_usage for l in logs]
    trf_vals = [l.traffic_mbps for l in logs]

    # Tambahkan titik terkini
    labels.append(datetime.now().strftime("%H:%M"))
    cpu_vals.append(device.cpu_usage)
    mem_vals.append(device.mem_usage)
    trf_vals.append(device.traffic_mbps)

    return jsonify({
        "device_id": device_id,
        "name": device.name,
        "labels": labels,
        "cpu": cpu_vals,
        "memory": mem_vals,
        "traffic": trf_vals
    })

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    print(f"[*] Starting PT Agiva Network Operations Dashboard on http://127.0.0.1:{port}")
    app.run(host='0.0.0.0', port=port, debug=True)

# PostgreSQL reload trigger
