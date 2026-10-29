from dotenv import load_dotenv
load_dotenv(override=True)
import os
import random
import json
import re
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify, request, redirect, url_for, session as flask_session
from database import db_session, init_db
from models import Device, DeviceStatusLog, Alert, IncidentLog, TelegramWhitelist, TelegramMessageLog, BackupHistory
from logger_config import get_configured_logger

logger = get_configured_logger("FlaskApp")

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'agiva-noc-secret-key-2026')

# Initialize DB tables and seed data
init_db()


# Import Rule Engine & Alerting System (Komponen 4 LLD)
from rule_engine import send_telegram_broadcast, trigger_alert_with_antispam

@app.teardown_appcontext
def shutdown_session(exception=None):
    db_session.remove()

@app.context_processor
def inject_global_vars():
    session = db_session()
    active_alerts_count = session.query(Alert).filter(Alert.acknowledged == False).count()
    devices = session.query(Device).order_by(Device.device_id.asc()).all()
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
        cutoff = now - timedelta(minutes=36)
        bucket_seconds = 120   # 2 menit (max 18 titik)

    logs = session.query(DeviceStatusLog).filter(
        DeviceStatusLog.timestamp >= cutoff
    ).order_by(DeviceStatusLog.timestamp.asc()).all()

    limit_fallback = 720 if range_mode == '24h' else (360 if range_mode == '12h' else (60 if range_mode == '1h' else 72))
    if len(logs) < 18:
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
            lbl = dt.strftime('%d/%m %H:%M') if dt.date() != now.date() else dt.strftime('%H:%M')
        else: # 'live'
            lbl = dt.strftime('%d/%m %H:%M') if dt.date() != now.date() else dt.strftime('%H:%M:%S')

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

    if range_mode == 'live' and len(labels) > 18:
        labels = labels[-18:]
        cpu_vals = cpu_vals[-18:]
        mem_vals = mem_vals[-18:]
        ing_vals = ing_vals[-18:]
        eg_vals = eg_vals[-18:]

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

# ==============================================================
# AUTHENTICATION & SESSION MANAGEMENT (Super Admin)
# ==============================================================
@app.before_request
def check_authentication():
    # Izinkan static assets tanpa otentikasi agar tampilan login ter-render sempurna
    if request.path.startswith('/static'):
        return None
    # Izinkan endpoint login dan logout
    if request.path in ['/login', '/logout']:
        return None
    # Verifikasi status login session
    if not flask_session.get('logged_in'):
        # Jika request API/AJAX, kembalikan response 401 JSON
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Unauthorized', 'message': 'Sesi login telah berakhir'}), 401
        # Redirect ke halaman login dengan parameter next
        return redirect(url_for('login', next=request.full_path if request.query_string else request.path))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if flask_session.get('logged_in'):
        return redirect(url_for('dashboard'))

    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        super_user = os.getenv('SUPER_ADMIN_USERNAME', 'admin')
        super_pass = os.getenv('SUPER_ADMIN_PASSWORD', 'agiva_admin123')

        if username == super_user and password == super_pass:
            flask_session['logged_in'] = True
            flask_session['username'] = username
            flask_session['role'] = 'Administrator'
            next_url = request.args.get('next')
            if next_url and next_url.startswith('/') and not next_url.startswith('//'):
                return redirect(next_url)
            return redirect(url_for('dashboard'))
        else:
            error = 'Username atau password tidak sesuai. Silakan periksa kembali.'

    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    flask_session.clear()
    return redirect(url_for('login'))

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
    devices = session.query(Device).order_by(Device.device_id.asc()).all()
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
    ports = telemetry.get("ports", [])

    # Sinkronisasi 100% Opsi B: Port 1 (Uplink) identik dengan titik log database terbaru
    latest_log = session.query(DeviceStatusLog).filter(
        DeviceStatusLog.device_id == device.device_id
    ).order_by(DeviceStatusLog.timestamp.desc()).first()

    if latest_log and ports:
        for p in ports:
            pid = str(p.get("port_id")).lower()
            pname = str(p.get("port_name", "")).lower()
            if pid == "1" or "10ge1/0/1" in pid or "eth1/2" in pid or "ethernet1/2" in pname or "uplink" in pname:
                if latest_log.ingress_mbps is not None:
                    p["rx_mbps"] = round(float(latest_log.ingress_mbps), 2)
                if latest_log.egress_mbps is not None:
                    p["tx_mbps"] = round(float(latest_log.egress_mbps), 2)

    return render_template(
        'device_detail.html',
        device=device.to_dict(),
        alerts=alerts_data,
        specs=telemetry.get("hardware", {}),
        vlans=telemetry.get("vlans", []),
        ports=ports,
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
    # 1. Ambil data alert AKTIF saja (yang belum di-resolve)
    alerts = session.query(Alert).filter(Alert.resolved_at == None).order_by(Alert.triggered_at.desc()).all()
    alerts_data = [a.to_dict() for a in alerts]
    
    # 2. Ambil Incident Log (30 hari terakhir sesuai retensi)
    cutoff_30d = datetime.now() - timedelta(days=30)
    incidents = session.query(IncidentLog).filter(
        IncidentLog.started_at >= cutoff_30d
    ).order_by(IncidentLog.started_at.desc()).all()
    incidents_data = [inc.to_dict() for inc in incidents]
    
    total_alerts = len(alerts)
    pending_alerts = sum(1 for a in alerts if not a.acknowledged)
    acked_alerts = sum(1 for a in alerts if a.acknowledged)

    total_incidents = len(incidents)
    cooldown_incidents = sum(1 for inc in incidents if inc.status == 'AUTO_COOLDOWN')
    resolved_incidents = sum(1 for inc in incidents if inc.status == 'RESOLVED_ALERT')
    
    session.close()
    return render_template(
        'alerts.html', 
        alerts=alerts_data,
        incidents=incidents_data,
        total_alerts=total_alerts,
        pending_alerts=pending_alerts,
        acked_alerts=acked_alerts,
        total_incidents=total_incidents,
        cooldown_incidents=cooldown_incidents,
        resolved_incidents=resolved_incidents,
        active_alerts_count=total_alerts
    )

@app.route('/api/ack/<int:alert_id>', methods=['POST'])
def api_ack_alert(alert_id):
    session = db_session()
    alert = session.query(Alert).filter(Alert.alert_id == alert_id).first()
    if not alert:
        session.close()
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
    session.close()

    return jsonify({
        "success": True,
        "alert_id": alert_id,
        "message": f"Alert #{alert_id} berhasil di-acknowledge dan dicatat ke basis data."
    })

@app.route('/api/resolve/<int:alert_id>', methods=['POST'])
def api_resolve_alert(alert_id):
    session = db_session()
    alert = session.query(Alert).filter(Alert.alert_id == alert_id).first()
    if not alert:
        session.close()
        return jsonify({"success": False, "message": "Alert ID tidak ditemukan"}), 404

    now = datetime.now()
    alert.resolved_at = now
    alert.acknowledged = True

    # Pindahkan ke tabel IncidentLog dengan status RESOLVED_ALERT
    active_inc = session.query(IncidentLog).filter(
        IncidentLog.device_id == alert.device_id,
        IncidentLog.type == alert.type,
        IncidentLog.resolved_at == None
    ).first()

    dev_name = alert.device.name if alert.device else "Device"

    if active_inc:
        dur_sec = max(1, int((now - active_inc.started_at).total_seconds()))
        active_inc.resolved_at = now
        active_inc.duration_seconds = dur_sec
        active_inc.status = 'RESOLVED_ALERT'
        inc_id = active_inc.incident_id
    else:
        dur_sec = max(1, int((now - alert.triggered_at).total_seconds())) if alert.triggered_at else 600
        new_inc = IncidentLog(
            device_id=alert.device_id,
            type=alert.type,
            severity=alert.severity,
            peak_metric="-",
            started_at=alert.triggered_at or now,
            resolved_at=now,
            duration_seconds=dur_sec,
            status='RESOLVED_ALERT'
        )
        session.add(new_inc)
        session.flush()
        inc_id = new_inc.incident_id

    target_chat_id = os.getenv('NOC_TELEGRAM_CHAT_ID', '-1004429503436')
    res_content = f"✅ *[NOC AGIVA - ALERT RESOLVED]*\n\nAlert #{alert.alert_id} ({alert.type}) pada `{dev_name}` telah diselesaikan (Resolved) via Web NOC Admin dan dipindahkan ke Incident Log."
    send_telegram_broadcast(res_content)

    tg_log = TelegramMessageLog(
        alert_id=alert.alert_id,
        chat_id=target_chat_id,
        message_type="COMMAND_REPLY",
        content=res_content,
        status="SENT",
        sent_at=now
    )
    session.add(tg_log)
    session.commit()
    session.close()

    return jsonify({
        "success": True,
        "alert_id": alert_id,
        "incident_id": inc_id,
        "message": f"Alert #{alert_id} berhasil di-resolve dan dipindahkan ke Incident Log."
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
    all_devs = session.query(Device).order_by(Device.device_id.asc()).all()
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

    # 2. Alerts Aktif (hanya yang belum di-resolve agar sinkron dengan tabel Active Alerts)
    active_alerts = session.query(Alert).filter(Alert.resolved_at == None).order_by(Alert.triggered_at.desc()).all()
    matched_alerts = []
    clean_q = ql.replace('#', '').strip()
    for a in active_alerts:
        dev_name = a.device.name.lower() if a.device else ""
        dev_ip = a.device.ip_address.lower() if a.device else ""
        alert_code = f"alert-{a.alert_id}".lower()
        if (clean_q in alert_code or 
            clean_q == str(a.alert_id) or
            ql in a.type.lower() or 
            ql in a.message.lower() or 
            ql in a.severity.lower() or 
            ql in dev_name or
            ql in dev_ip):
            matched_alerts.append({
                "id": a.alert_id,
                "type": a.type,
                "severity": a.severity,
                "message": a.message[:75] + ("..." if len(a.message) > 75 else ""),
                "device_name": a.device.name if a.device else "Unknown Device",
                "ip": a.device.ip_address if a.device else "-",
                "triggered_at": a.triggered_at.strftime("%d/%m %H:%M") if a.triggered_at else "-",
                "acknowledged": a.acknowledged,
                "url": f"/alerts#alert-row-{a.alert_id}"
            })
            if len(matched_alerts) >= 5:
                break

    # 3. Incident Log & Cooldown History (30 hari terakhir sesuai retensi)
    cutoff_30d = datetime.now() - timedelta(days=30)
    all_incidents = session.query(IncidentLog).filter(
        IncidentLog.started_at >= cutoff_30d
    ).order_by(IncidentLog.started_at.desc()).limit(150).all()

    matched_incidents = []
    for inc in all_incidents:
        dev_name = inc.device.name.lower() if inc.device else ""
        dev_ip = inc.device.ip_address.lower() if inc.device else ""
        inc_code = f"inc-{inc.incident_id}".lower()
        status_raw = (inc.status or "").lower()
        peak_metric_val = (inc.peak_metric or "").lower()
        
        # Label representatif
        if inc.status == 'AUTO_COOLDOWN':
            status_label = "Cooldown"
        elif inc.status == 'RESOLVED_ALERT':
            status_label = "Resolved"
        elif inc.status == 'ACTIVE_MONITORING':
            status_label = "Pemantauan"
        elif inc.status in ['ACTIVE_ALERT', 'ESCALATED_TO_ALERT']:
            status_label = "Alert Aktif"
        else:
            status_label = inc.status or "Insiden"

        if (clean_q in inc_code or 
            clean_q == str(inc.incident_id) or
            ql in dev_name or 
            ql in dev_ip or 
            ql in inc.type.lower() or 
            ql in (inc.severity or "").lower() or 
            ql in status_raw or 
            ql in status_label.lower() or
            ql in peak_metric_val or
            (ql == "cooldown" and inc.status == 'AUTO_COOLDOWN') or
            (ql == "resolved" and inc.status == 'RESOLVED_ALERT') or
            (ql in ["alert aktif", "active_alert", "alert"] and inc.status in ['ACTIVE_ALERT', 'ESCALATED_TO_ALERT']) or
            (ql in ["insiden", "incident"])):
            
            dur_str = "-"
            if inc.duration_seconds and inc.duration_seconds > 0:
                m, s = divmod(inc.duration_seconds, 60)
                h, m = divmod(m, 60)
                if h > 0:
                    dur_str = f"{h}j {m}m"
                elif m > 0:
                    dur_str = f"{m}m {s}d"
                else:
                    dur_str = f"{s} dtk"

            matched_incidents.append({
                "id": inc.incident_id,
                "code": f"#INC-{inc.incident_id}",
                "device_name": inc.device.name if inc.device else "Unknown Device",
                "ip": inc.device.ip_address if inc.device else "-",
                "type": inc.type,
                "severity": inc.severity,
                "peak_metric": inc.peak_metric or "-",
                "status": inc.status,
                "status_label": status_label,
                "started_at": inc.started_at.strftime("%d/%m %H:%M") if inc.started_at else "-",
                "duration": dur_str,
                "url": f"/alerts#inc-row-{inc.incident_id}"
            })
            if len(matched_incidents) >= 6:
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
            "desc": "Daftar alarm aktif, riwayat incident log, dan cooldown perangkat",
            "category": "Menu Navigasi",
            "keywords": ["alert", "alerts", "insiden", "incident", "alarm", "anomali", "ack", "notif", "peringatan", "cooldown", "resolved"],
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

    total_count = (len(matched_devices) + 
                   len(matched_alerts) + 
                   len(matched_incidents) + 
                   len(matched_backups) + 
                   len(matched_telegram) + 
                   len(matched_nav))

    session.close()

    return jsonify({
        "query": q,
        "total_results": total_count,
        "categories": {
            "devices": matched_devices,
            "alerts": matched_alerts,
            "incidents": matched_incidents,
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
    devices = session.query(Device).order_by(Device.device_id.asc()).all()
    active_alerts = session.query(Alert).filter(Alert.acknowledged == False).all()

    online_devs = [d for d in devices if d.status == 'UP']
    avg_cpu = round(sum(d.cpu_usage for d in online_devs) / len(online_devs), 1) if online_devs else 0
    avg_mem = round(sum(d.mem_usage for d in online_devs) / len(online_devs), 1) if online_devs else 0
    devices_data = [d.to_dict() for d in devices]
    alerts_data = [a.to_dict() for a in active_alerts]
    history_data = get_aggregated_chart_history(range_mode, session=session)
    session.close()

    total_trf = round(history_data["ingress"][-1] + history_data["egress"][-1], 1) if history_data.get("ingress") and history_data.get("egress") else 0.0
    ingress_trf = round(history_data["ingress"][-1], 1) if history_data.get("ingress") else 0.0
    egress_trf = round(history_data["egress"][-1], 1) if history_data.get("egress") else 0.0

    payload = {
        "timestamp": datetime.now().strftime("%H:%M:%S"),
        "date_str": datetime.now().strftime("%d/%m/%Y"),
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
    }
    return jsonify(payload)

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
        cutoff = now - timedelta(minutes=36)
        bucket_seconds = 120   # 2 menit (max 18 titik)

    logs = session.query(DeviceStatusLog).filter(
        DeviceStatusLog.device_id == device_id,
        DeviceStatusLog.timestamp >= cutoff
    ).order_by(DeviceStatusLog.timestamp.asc()).all()

    limit_fallback = 720 if range_mode == '24h' else (360 if range_mode == '12h' else (60 if range_mode == '1h' else 24))
    if len(logs) < 18:
        # Fallback to latest available logs for this device
        logs = session.query(DeviceStatusLog).filter(
            DeviceStatusLog.device_id == device_id
        ).order_by(DeviceStatusLog.timestamp.desc()).limit(limit_fallback).all()
        logs.reverse()

    telemetry = get_device_full_telemetry(device)
    ports = telemetry.get("ports", [])
    res = telemetry.get("resources", {})
    pb_base = float(res.get("packet_buffers_pct", 35.1))
    mb_base = float(res.get("message_buffers_pct", 4.0))
    td_val = int(res.get("tx_drops", 0))
    re_val = int(res.get("rx_errors", 0))
    te_val = int(res.get("tx_errors", 0))

    if not logs:
        labels = [now.strftime("%H:%M:%S")]
        cpu_vals = [round(device.cpu_usage or 0.0, 1)]
        mem_vals = [round(device.mem_usage or 0.0, 1)]
        lat_vals = [round(device.latency_ms or 0.0, 1)]
        loss_vals = [round(device.packet_loss or 0.0, 1)]
        trf_vals = [0.0]
        trf_in_vals = [0.0]
        trf_out_vals = [0.0]
        pb_vals = [pb_base]
        mb_vals = [mb_base]
        td_vals = [td_val]
        re_vals = [re_val]
        te_vals = [te_val]
    else:
        # Group into exact 2-minute cycle keys (data mentah asli tanpa perataan)
        buckets = defaultdict(list)
        for l in logs:
            cycle_key = int(l.timestamp.timestamp()) // bucket_seconds
            buckets[cycle_key].append(l)

        labels = []
        cpu_vals = []
        mem_vals = []
        lat_vals = []
        loss_vals = []
        trf_vals = []
        trf_in_vals = []
        trf_out_vals = []
        pb_vals = []
        mb_vals = []
        td_vals = []
        re_vals = []
        te_vals = []
        for key in sorted(buckets.keys()):
            b_logs = buckets[key]
            dt = datetime.fromtimestamp(key * bucket_seconds)
            if range_mode == '24h':
                lbl = dt.strftime('%d/%m %H:%M') if dt.date() != now.date() else dt.strftime('%H:%M')
            elif range_mode in ['1h', '12h']:
                lbl = dt.strftime('%d/%m %H:%M') if dt.date() != now.date() else dt.strftime('%H:%M')
            else:  # live
                lbl = dt.strftime('%d/%m %H:%M') if dt.date() != now.date() else dt.strftime('%H:%M:%S')
            labels.append(lbl)
            # Ambil data mentah riil siklus tersebut
            b = b_logs[-1]
            cpu_vals.append(round(b.cpu_usage or 0.0, 1))
            mem_vals.append(round(b.mem_usage or 0.0, 1))
            lat_vals.append(round(b.latency_ms or 0.0, 1))
            loss_vals.append(round(b.packet_loss or 0.0, 1))
            trf_vals.append(round(b.traffic_mbps or 0.0, 2))
            trf_in_vals.append(round(b.ingress_mbps or 0.0, 2))
            trf_out_vals.append(round(b.egress_mbps or 0.0, 2))
            pb_vals.append(round(b.packet_buffers or 0.0, 1))
            mb_vals.append(round(b.message_buffers or 0.0, 1))
            td_vals.append(int(b.tx_drops or 0))
            re_vals.append(int(b.rx_errors or 0))
            te_vals.append(int(b.tx_errors or 0))

        if range_mode == 'live' and len(labels) > 18:
            labels = labels[-18:]
            cpu_vals = cpu_vals[-18:]
            mem_vals = mem_vals[-18:]
            lat_vals = lat_vals[-18:]
            loss_vals = loss_vals[-18:]
            trf_vals = trf_vals[-18:]
            trf_in_vals = trf_in_vals[-18:]
            trf_out_vals = trf_out_vals[-18:]
            pb_vals = pb_vals[-18:]
            mb_vals = mb_vals[-18:]
            td_vals = td_vals[-18:]
            re_vals = re_vals[-18:]
            te_vals = te_vals[-18:]

    result = {
        "device_id": device_id,
        "name": device.name,
        "status": device.status,
        "uptime": device.uptime,
        "range": range_mode,
        "current_cpu": device.cpu_usage,
        "current_memory": device.mem_usage,
        "current_latency": round(device.latency_ms or 0.0, 1),
        "current_packet_loss": round(device.packet_loss or 0.0, 1),
        "current_traffic": round((trf_in_vals[-1] + trf_out_vals[-1]), 2) if trf_in_vals and trf_out_vals else 0.0,
        "current_traffic_in": trf_in_vals[-1] if trf_in_vals else 0.0,
        "current_traffic_out": trf_out_vals[-1] if trf_out_vals else 0.0,
        "current_packet_buffers": pb_base,
        "current_tx_drops": td_val,
        "current_message_buffers": mb_base,
        "current_rx_errors": re_val,
        "current_tx_errors": te_val,
        "labels": labels,
        "cpu": cpu_vals,
        "memory": mem_vals,
        "latency": lat_vals,
        "packet_loss": loss_vals,
        "traffic": trf_vals,
        "traffic_in": trf_in_vals,
        "traffic_out": trf_out_vals,
        "packet_buffers": pb_vals,
        "tx_drops": td_vals,
        "message_buffers": mb_vals,
        "rx_errors": re_vals,
        "tx_errors": te_vals,
        "resources": res,
        "specs": telemetry.get("hardware", {}),
        "vlans": telemetry.get("vlans", []),
        "ports": ports,
        "summary": telemetry.get("summary", {}),
    }
    # Sinkronisasi 100% Opsi B: Port Uplink identik dengan titik grafik traffic terbaru (Aruba Port 1, Huawei 10GE1/0/1, Palo Alto ethernet1/2)
    if trf_in_vals and trf_out_vals and ports:
        latest_ingress = trf_in_vals[-1]
        latest_egress = trf_out_vals[-1]
        for p in ports:
            pid = str(p.get("port_id")).lower()
            pname = str(p.get("port_name", "")).lower()
            if pid == "1" or "10ge1/0/1" in pid or "eth1/2" in pid or "ethernet1/2" in pname or "uplink" in pname:
                p["rx_mbps"] = latest_ingress
                p["tx_mbps"] = latest_egress

    session.close()
    return jsonify(result)

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    print(f"[*] Starting PT Agiva Network Operations Dashboard on http://127.0.0.1:{port}")
    app.run(host='0.0.0.0', port=port, debug=True, threaded=True)

# PostgreSQL reload trigger - full dynamic Palo Alto specs (All 10 hardware parameters + ports)
