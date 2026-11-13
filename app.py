from dotenv import load_dotenv
load_dotenv(override=True)
import os
import json
import re
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta
from sqlalchemy import or_, and_
from flask import Flask, render_template, jsonify, request, redirect, url_for, session as flask_session
from database import db_session, init_db
from models import Device, DeviceStatusLog, WanStatusLog, Alert, IncidentLog, TelegramWhitelist, TelegramMessageLog, BackupHistory
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
    active_alerts_count = session.query(Alert).filter(Alert.resolved_at == None).count()
    devices = session.query(Device).order_by(Device.device_id.asc()).all()
    nav_devices = [d.to_dict() for d in devices]
    session.close()
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

def get_wan_metrics_summary(session=None):
    """Mengambil metrik ringkasan WAN Biznet (ethernet1/3) terkini & evaluasi kualitas."""
    close_session = False
    if session is None:
        session = db_session()
        close_session = True

    try:
        latest = session.query(WanStatusLog).order_by(WanStatusLog.timestamp.desc()).first()
    except Exception as e:
        session.rollback()
        logger.warning(f"Error querying WanStatusLog: {e}")
        latest = None

    capacity = float(os.getenv("BIZNET_CAPACITY_MBPS", "100.0"))

    # Single Source of Truth: app.py murni membaca data riil dari database (dicatat oleh collector.py).
    # Tidak membuat/memalsukan log baru saat collector.py tidak aktif.
    if latest:
        dl = round(latest.download_mbps or 0.0, 1)
        ul = round(latest.upload_mbps or 0.0, 1)
        tot = round(latest.total_mbps or (dl + ul), 1)
        lat = round(latest.latency_ms or 0.0, 1)
        gw_lat = round(latest.gateway_latency_ms or 0.0, 1)
        loss = round(latest.packet_loss or 0.0, 1)
        rx_err = int(latest.rx_errors or 0)
        tx_err = int(latest.tx_errors or 0)
        tot_err = rx_err + tx_err
        st = latest.status or "UP"
        if latest.timestamp:
            ts = latest.timestamp
            if isinstance(ts, str):
                try:
                    ts = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                except Exception:
                    ts = datetime.now()
            # Seragamkan dengan time bucket interval grafik (kelipatan 120 detik / 2 menit)
            bucket_seconds = 120
            cycle_key = int(ts.timestamp()) // bucket_seconds
            floored_dt = datetime.fromtimestamp(cycle_key * bucket_seconds)
            date_str = floored_dt.strftime("%d/%m/%Y")
            time_str = floored_dt.strftime("%H:%M:%S")
            updated = f"{date_str} {time_str}"
        else:
            updated = "-"
    else:
        dl, ul, tot, lat, gw_lat, loss, rx_err, tx_err, tot_err, st, updated = 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0, 0, "UP", "-"

    # Metode Agregat Gabungan: Menghitung persentase pemakaian total trafik (Download + Upload) terhadap kapasitas paket
    utilization_pct = round(min(100.0, (tot / capacity) * 100.0), 1)

    # Diagnostik Pintar Otomatis (Cukup Hijau: Koneksi Normal, Merah: Koneksi Abnormal)
    if st == "DOWN" or loss > 2.0 or lat > 45.0 or tot_err > 0 or utilization_pct >= 90.0:
        quality_status = "ABNORMAL"
        quality_label = "Abnormal Connection"
        quality_color = "red"
    else:
        quality_status = "NORMAL"
        quality_label = "Normal Connection"
        quality_color = "green"

    if close_session:
        session.close()

    return {
        "provider": "Biznet",
        "interface": "ethernet1/3",
        "device_name": "FW-PA220-1",
        "status": st,
        "speed": "1 Gbps Full-Duplex",
        "ip_address": "192.168.18.226",
        "gateway_ip": "192.168.18.1",
        "download_mbps": dl,
        "upload_mbps": ul,
        "total_mbps": tot,
        "capacity_mbps": capacity,
        "utilization_pct": utilization_pct,
        "latency_ms": lat,
        "gateway_latency_ms": gw_lat,
        "packet_loss": loss,
        "rx_errors": rx_err,
        "tx_errors": tx_err,
        "total_errors": tot_err,
        "quality_status": quality_status,
        "quality_label": quality_label,
        "quality_color": quality_color,
        "last_updated": updated
    }

def get_wan_chart_history(range_mode='live', session=None):
    """Mengambil data time-series histori WAN Biznet untuk Chart.js (Live, 1h, 12h, 24h)."""
    close_session = False
    if session is None:
        session = db_session()
        close_session = True

    now = datetime.now()
    if range_mode == '1h':
        cutoff = now - timedelta(hours=1)
        bucket_seconds = 120
    elif range_mode == '12h':
        cutoff = now - timedelta(hours=12)
        bucket_seconds = 120
    elif range_mode == '24h':
        cutoff = now - timedelta(hours=24)
        bucket_seconds = 120
    else:  # 'live'
        cutoff = now - timedelta(minutes=36)
        bucket_seconds = 120

    try:
        logs = session.query(WanStatusLog).filter(
            WanStatusLog.timestamp >= cutoff
        ).order_by(WanStatusLog.timestamp.asc()).all()

        limit_fallback = 720 if range_mode == '24h' else (360 if range_mode == '12h' else (60 if range_mode == '1h' else 36))
        if len(logs) < 18:
            logs = session.query(WanStatusLog).order_by(
                WanStatusLog.timestamp.desc()
            ).limit(limit_fallback).all()
            logs.reverse()
    except Exception as e:
        session.rollback()
        logger.warning(f"Error querying WanStatusLog history: {e}")
        logs = []

    if not logs:
        if close_session:
            session.close()
        return {
            "range": range_mode,
            "labels": [now.strftime('%H:%M:%S')],
            "download": [0.0],
            "upload": [0.0],
            "latency": [0.0],
            "packet_loss": [0.0]
        }

    buckets = defaultdict(list)
    for l in logs:
        cycle_key = int(l.timestamp.timestamp()) // bucket_seconds
        buckets[cycle_key].append(l)

    labels = []
    dl_vals = []
    ul_vals = []
    lat_vals = []
    loss_vals = []

    for key in sorted(buckets.keys()):
        cycle_logs = buckets[key]
        dt = datetime.fromtimestamp(key * bucket_seconds)
        if range_mode in ['24h', '12h', '1h']:
            lbl = dt.strftime('%d/%m %H:%M') if dt.date() != now.date() else dt.strftime('%H:%M')
        else:
            lbl = dt.strftime('%d/%m %H:%M') if dt.date() != now.date() else dt.strftime('%H:%M:%S')

        labels.append(lbl)
        avg_dl = round(sum(x.download_mbps or 0.0 for x in cycle_logs) / len(cycle_logs), 1)
        avg_ul = round(sum(x.upload_mbps or 0.0 for x in cycle_logs) / len(cycle_logs), 1)
        avg_lat = round(sum(x.latency_ms or 0.0 for x in cycle_logs) / len(cycle_logs), 1)
        avg_loss = round(sum(x.packet_loss or 0.0 for x in cycle_logs) / len(cycle_logs), 1)

        dl_vals.append(avg_dl)
        ul_vals.append(avg_ul)
        lat_vals.append(avg_lat)
        loss_vals.append(avg_loss)

    if range_mode == 'live' and len(labels) > 18:
        labels = labels[-18:]
        dl_vals = dl_vals[-18:]
        ul_vals = ul_vals[-18:]
        lat_vals = lat_vals[-18:]
        loss_vals = loss_vals[-18:]

    if close_session:
        session.close()

    return {
        "range": range_mode,
        "labels": labels,
        "download": dl_vals,
        "upload": ul_vals,
        "latency": lat_vals,
        "packet_loss": loss_vals
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
            return jsonify({'error': 'Unauthorized', 'message': 'Login session expired'}), 401
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
            error = 'Invalid username or password. Please verify your credentials.'

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
    alerts = session.query(Alert).filter(Alert.resolved_at == None).order_by(Alert.triggered_at.desc()).limit(10).all()

    total_devices = len(devices)
    devices_online = sum(1 for d in devices if d.status == 'UP')
    devices_offline = sum(1 for d in devices if d.status == 'DOWN')
    active_alerts_count = session.query(Alert).filter(Alert.resolved_at == None).count()

    device_list = [d.to_dict() for d in devices]
    alert_list = [a.to_dict() for a in alerts]
    initial_chart_history = get_aggregated_chart_history(session=session)
    wan_summary = get_wan_metrics_summary(session=session)
    initial_wan_history = get_wan_chart_history('live', session=session)
    session.close()

    return render_template(
        'index.html',
        total_devices=total_devices,
        devices_online=devices_online,
        devices_offline=devices_offline,
        active_alerts_count=active_alerts_count,
        devices=device_list,
        alerts=alert_list,
        initial_chart_history=initial_chart_history,
        wan=wan_summary,
        initial_wan_history=initial_wan_history
    )

from telemetry_helper import get_device_full_telemetry, get_ap_client_telemetry

@app.route('/device/<int:device_id>')
@app.route('/device_detail.html')
def device_detail(device_id=1):
    session = db_session()
    device = session.query(Device).filter(Device.device_id == device_id).first()
    if not device:
        device = session.query(Device).first()
    if not device:
        return "Device not found", 404

    device_alerts = session.query(Alert).filter(Alert.device_id == device.device_id, Alert.resolved_at == None).all()
    alerts_data = [a.to_dict() for a in device_alerts]

    telemetry = get_device_full_telemetry(device)
    ports = telemetry.get("ports", [])
    res = telemetry.get("resources", {})
    if res.get("memory_pct") is not None and "aruba" in device.vendor.lower():
        device.mem_usage = round(float(res.get("memory_pct")), 1)

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

    session.close()

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
    cutoff_30d = datetime.now() - timedelta(days=30)
    
    # 1. Tabel Atas (Active & Sustained Alerts): Hanya menampilkan alert yang BELUM di-resolve
    # Alert yang sudah Resolved otomatis pindah dan diarsipkan di tabel bawah (Incident Log & Cooldown History)
    alerts = session.query(Alert).filter(
        Alert.resolved_at == None
    ).order_by(Alert.triggered_at.desc()).all()
    alerts_data = [a.to_dict() for a in alerts]
    
    # 2. Tabel Bawah (Incident Log & Cooldown History): 30 hari terakhir sesuai retensi
    incidents = session.query(IncidentLog).filter(
        IncidentLog.started_at >= cutoff_30d
    ).order_by(IncidentLog.started_at.desc()).all()
    incidents_data = [inc.to_dict() for inc in incidents]
    
    total_alerts = len(alerts)
    pending_alerts = sum(1 for a in alerts if not a.acknowledged)
    acked_alerts = sum(1 for a in alerts if a.acknowledged)
    resolved_alerts = 0

    total_incidents = len(incidents)
    monitoring_incidents = sum(1 for inc in incidents if inc.status == 'ACTIVE_MONITORING')
    cooldown_incidents = sum(1 for inc in incidents if inc.status == 'AUTO_COOLDOWN')
    resolved_incidents = sum(1 for inc in incidents if inc.status == 'RESOLVED_ALERT')
    
    # Badge notifikasi hanya menghitung alert yang masih aktif memerlukan penanganan
    active_alerts_count = pending_alerts + acked_alerts

    session.close()
    return render_template(
        'alerts.html', 
        alerts=alerts_data,
        incidents=incidents_data,
        total_alerts=total_alerts,
        pending_alerts=pending_alerts,
        acked_alerts=acked_alerts,
        resolved_alerts=resolved_alerts,
        total_incidents=total_incidents,
        monitoring_incidents=monitoring_incidents,
        cooldown_incidents=cooldown_incidents,
        resolved_incidents=resolved_incidents,
        active_alerts_count=active_alerts_count
    )

@app.route('/api/ack/<int:alert_id>', methods=['POST'])
def api_ack_alert(alert_id):
    """
    SOP PT AGIVA: Acknowledge tiket via Web dinonaktifkan secara ketat.
    Tiket Active Alerts HANYA boleh di-acknowledge melalui Telegram Bot (/ack <id>)
    oleh Administrator / Duty Engineer yang terdaftar di Whitelist.
    """
    return jsonify({
        "success": False,
        "message": "Web acknowledge is strictly disabled PT AGIVA SOP. Please use Telegram command: /ack <alert_id> by authorized Duty Engineer."
    }), 403

@app.route('/api/resolve/<int:alert_id>', methods=['POST'])
def api_resolve_alert(alert_id):
    """
    SOP PT AGIVA: Resolusi tiket via Web dinonaktifkan secara ketat.
    Tiket Active Alerts HANYA boleh diselesaikan melalui Telegram Bot (/resolve <id>)
    oleh Administrator / Duty Engineer yang terdaftar di Whitelist.
    """
    return jsonify({
        "success": False,
        "message": "Resolusi tiket via Web dinonaktifkan. tiket hanya dapat diselesaikan melalui Telegram Bot (/resolve <id>) oleh admin terverifikasi."
    }), 403

# 3. TELEGRAM BOT INTEGRATION ROUTES

# Cache untuk status Telegram Bot agar tidak membebani I/O setiap request
_telegram_bot_status_cache = {
    "timestamp": 0,
    "is_online": False
}

def is_telegram_bot_online():
    """
    Memeriksa apakah proses Bot Telegram (bot.py) benar-benar sedang berjalan aktif:
    1. Cek file logs/bot_heartbeat.json yang ditulis secara berkala (tiap 5 detik) oleh bot.py.
       Bot dianggap ONLINE jika status == 'ONLINE' dan timestamp masih segar (<= 15 detik yang lalu).
    2. Jika proses bot.py dimatikan atau crash, heartbeat tidak akan diperbarui sehingga
       otomatis terdeteksi sebagai OFFLINE.
    3. Menggunakan cache pendek (4 detik) agar respon cepat dan hemat resource.
    """
    global _telegram_bot_status_cache
    now = time.time()
    if now - _telegram_bot_status_cache["timestamp"] < 4:
        return _telegram_bot_status_cache["is_online"]

    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token or token.startswith('123456'):
        _telegram_bot_status_cache = {"timestamp": now, "is_online": False}
        return False

    is_online = False
    heartbeat_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs', 'bot_heartbeat.json')

    if os.path.exists(heartbeat_file):
        try:
            with open(heartbeat_file, 'r') as f:
                hb = json.load(f)
                hb_status = hb.get('status', '').upper()
                hb_timestamp = hb.get('timestamp', 0)
                # Syarat Online: Status 'ONLINE' dan heartbeat terkirim dalam 15 detik terakhir
                if hb_status == 'ONLINE' and (now - hb_timestamp <= 15):
                    is_online = True
        except Exception:
            is_online = False

    _telegram_bot_status_cache = {
        "timestamp": now,
        "is_online": is_online
    }
    return is_online

def get_active_alerts_pushed_count(session, cutoff_date):
    """
    Menghitung total alert yang di-push ke Telegram (>= 10 menit) bertipe ALERT_NOTIFICATION.
    Semua anomali (HOST_DOWN, CPU, MEMORY, LATENCY, PACKET_LOSS) diperlakukan seragam:
    hanya dikirim ke Telegram jika anomali bertahan >= 10 menit (anti-spam & anti-flapping).
    """
    return session.query(TelegramMessageLog).filter(
        TelegramMessageLog.message_type == 'ALERT_NOTIFICATION',
        TelegramMessageLog.sent_at >= cutoff_date
    ).count()

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

    # Cek status koneksi Bot API Telegram (aktif baik di VPS maupun lokal)
    bot_is_online = is_telegram_bot_online()

    bot_info = {
        "bot_name": os.getenv('TELEGRAM_BOT_NAME', 'Agiva Network Automation Bot'),
        "username": os.getenv('TELEGRAM_BOT_USERNAME', '@Agiva_Network_Automation_Bot'),
        "status": "Online" if bot_is_online else "Offline",
        "is_online": bot_is_online,
        "chat_group": os.getenv('TELEGRAM_GROUP_NAME', 'Agiva Network Automation Channel'),
        "chat_id": os.getenv('NOC_TELEGRAM_CHAT_ID', '-1004429503436'),
        "active_alerts_pushed": get_active_alerts_pushed_count(session, cutoff_date)
    }

    commands = [
        {"command": "/start", "params": "-", "desc": "Start bot interaction and show operational command guide."},
        {"command": "/status", "params": "-", "desc": "View health summary of all network devices and active alerts."},
        {"command": "/devices", "params": "-", "desc": "Display inventory table of all registered network devices."},
        {"command": "/device", "params": "<device_name>", "desc": "View real-time CPU, RAM, & Uptime telemetry for a specific device."},
        {"command": "/alerts", "params": "-", "desc": "Display list of active network anomalies requiring mitigation."},
        {"command": "/ack", "params": "<alert_id>", "desc": "Acknowledge anomaly alert handling by duty engineer."},
        {"command": "/resolve", "params": "<alert_id>", "desc": "Mark network incident as resolved and move to log."},
        {"command": "/backup", "params": "<device_name> [category]", "desc": "Trigger manual backup for config & audit logs (options: all, system, config, traffic, threat)."},
        {"command": "/user", "params": "-", "desc": "View engineer profile, Telegram Chat ID, and Whitelist authorization status."},
        {"command": "/approve", "params": "<username> [role]", "desc": "(Admin only) Approve new engineer access with specified role."}
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
    active_alerts_pushed = get_active_alerts_pushed_count(session, cutoff_date)
    
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
        "active_alerts_pushed": active_alerts_pushed,
        "bot_is_online": is_telegram_bot_online()
    })

@app.route('/api/telegram/test-alert', methods=['POST'])
def api_test_telegram_alert():
    """
    Diagnostic Test: Memastikan Telegram Bot API aktif.
    """
    session = db_session()
    tg_chat_id = os.getenv('NOC_TELEGRAM_CHAT_ID', '-1004429503436')
    
    bot_online = is_telegram_bot_online()
    if bot_online:
        bot_clause = "Telegram Bot token communication channel is operational, and interactive bot engine (bot.py) is actively running."
    else:
        bot_clause = "Telegram Bot token communication channel is operational, but interactive bot engine (bot.py) is currently offline."

    msg_content = (
        "*TEST CONNECTIVITY*\n\n"
        "This is a diagnostic Ping test message from the Dashboard.\n"
        f"{bot_clause}\n"
        f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} WIB"
    )
    
    ok, delivery_status = send_telegram_broadcast(msg_content, parse_mode='Markdown')
    
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
        return jsonify({"success": True, "message": "Test connectivity message sent successfully!"})
    else:
        return jsonify({"success": False, "message": f"Failed: {delivery_status}"}), 500

# 4. BACKUP ROUTE

@app.route('/backups')
@app.route('/backups.html')
@app.route('/backup.html')
@app.route('/backupfile.html')
def backups_page():
    """Route: /backups - Riwayat backup konfigurasi & log audit multi-vendor"""
    session = db_session()
    backups = session.query(BackupHistory).order_by(BackupHistory.timestamp.desc()).all()
    backups_data = []
    success_count = 0
    failed_count = 0
    for b in backups:
        cat = getattr(b, 'category', None)
        if not cat:
            fp_lower = (b.file_path or "").lower()
            if "_system" in fp_lower or "logbuffer" in fp_lower:
                cat = "System"
            elif "_traffic" in fp_lower:
                cat = "Traffic"
            elif "_threat" in fp_lower:
                cat = "Threat"
            else:
                cat = "Config"

        if b.status == 'SUCCESS':
            success_count += 1
        else:
            failed_count += 1

        time_str = b.timestamp.strftime("%H:%M:%S WIB") if b.timestamp else "-"
        date_str = b.timestamp.strftime("%d/%m/%Y") if b.timestamp else "-"
        full_date_str = b.timestamp.strftime("%Y-%m-%d %H:%M:%S WIB") if b.timestamp else "-"
        timestamp_str = b.timestamp.strftime("%d/%m/%Y %H:%M:%S WIB") if b.timestamp else "-"

        backups_data.append({
            "id": b.backup_id,
            "device": b.device.name if b.device else "Unknown",
            "site": b.device.site if b.device else "-",
            "category": cat,
            "time": time_str,
            "date": date_str,
            "full_date": full_date_str,
            "timestamp": timestamp_str,
            "file": b.file_path,
            "size": b.file_size,
            "trigger_by": getattr(b, 'trigger_by', 'Scheduler (02:00 WIB)') or 'Scheduler (02:00 WIB)',
            "status": b.status
        })

    category_counts = {
        "all": len(backups_data),
        "system": 0,
        "config": 0,
        "traffic": 0,
        "threat": 0
    }
    for b in backups_data:
        cat_key = (b.get('category') or 'CONFIG').lower()
        if cat_key in category_counts:
            category_counts[cat_key] += 1
        else:
            category_counts['config'] += 1

    session.close()
    return render_template(
        'backups.html',
        backups=backups_data,
        success_count=success_count,
        failed_count=failed_count,
        total_backups=len(backups_data),
        category_counts=category_counts
    )

@app.route('/api/backup/content/<int:backup_id>')
def api_backup_content(backup_id):
    """Mengembalikan isi teks berkas backup untuk preview modal di backups.html"""
    from backup_service import get_backup_content
    res = get_backup_content(backup_id)
    return jsonify(res)

@app.route('/api/backup/download/<int:backup_id>')
def api_backup_download(backup_id):
    """Mengunduh berkas fisik backup (.txt) langsung ke laptop pengguna"""
    from flask import send_file
    from backup_service import BACKUP_BASE_DIR
    session = db_session()
    try:
        b = session.query(BackupHistory).filter(BackupHistory.backup_id == backup_id).first()
        if not b:
            return jsonify({"error": "Backup data not found"}), 404
        
        clean_path = b.file_path.strip("/\\")
        parts = clean_path.split("/")
        if parts and parts[0] == "backups":
            parts = parts[1:]
        
        abs_path = os.path.join(BACKUP_BASE_DIR, *parts)
        if not os.path.exists(abs_path):
            return jsonify({"error": "Physical file not yet stored on server disk"}), 404
            
        filename = os.path.basename(abs_path)
        return send_file(abs_path, as_attachment=True, download_name=filename)
    finally:
        session.close()

@app.route('/api/backup/trigger/<string:device_name>', methods=['POST'])
def api_trigger_backup(device_name):
    """Memicu penarikan backup & log langsung ke perangkat via SSH/API dari web modal"""
    from backup_service import run_device_backup
    category = request.args.get('category') or (request.json.get('category') if request.is_json else None)
    res = run_device_backup(device_name, category_filter=category, trigger_by="Web Dashboard")
    return jsonify(res)

# 5. REAL-TIME JSON APIS FOR DASHBOARD POLLING & OMNI-SEARCH

@app.route('/api/search')
def api_search():
    """
    Pattern 3: Omni-Search / Command Palette API (Comprehensive, Ultra-Fast & Resilient)
    Mencari secara serentak ke 6 domain data tanpa pembatasan limit di awal.
    """
    q = request.args.get('q', '').strip()
    if not q or len(q) < 1:
        return jsonify({
            "query": "",
            "total_results": 0,
            "categories": {
                "devices": [],
                "alerts": [],
                "incidents": [],
                "backups": [],
                "telegram": [],
                "navigation": []
            }
        })

    session = db_session()
    try:
        ql = q.lower()
        clean_q = re.sub(r'[\#]', '', ql).strip()
        num_matches = re.findall(r'\d+', ql)
        numeric_id = int(num_matches[0]) if num_matches else None
        clean_nospace = re.sub(r'[\s\-_]+', '', ql)
        cutoff_30d = datetime.now() - timedelta(days=30)

        # Pre-cache all devices in memory (Hanya 3-10 perangkat, mencegah N+1 queries ribuan kali)
        all_devs = session.query(Device).order_by(Device.device_id.asc()).all()
        dev_map = {d.device_id: d for d in all_devs}

        # 1. DEVICES: Match name, IP, vendor, site, status (UP/DOWN/Online/Offline), atau ports
        matched_devices = []
        for d in all_devs:
            d_name = (d.name or "").lower()
            d_ip = (d.ip_address or "").lower()
            d_vendor = (d.vendor or "").lower()
            d_site = (d.site or "").lower()
            d_status = (d.status or "").lower()

            is_status_match = False
            if ql in ["up", "online", "status:up", "status up"] and d_status == 'up':
                is_status_match = True
            elif ql in ["down", "offline", "status:down", "status down"] and d_status == 'down':
                is_status_match = True
            elif ql == d_status:
                is_status_match = True

            is_port_match = False
            if d_vendor == 'palo alto' and any(k in ql for k in ['biznet', 'wan', 'gateway', 'lan gateway', 'ethernet1/3', 'pa-220']):
                is_port_match = True
            elif d_vendor == 'aruba' and any(k in ql for k in ['sfp', 'poe', '2930f']):
                is_port_match = True
            elif d_vendor == 'huawei' and any(k in ql for k in ['vlanif', 'stack', 's5735', '10ge']):
                is_port_match = True

            if (ql in d_name or 
                ql in d_ip or 
                ql in d_vendor or 
                ql in d_site or
                is_status_match or
                is_port_match):
                matched_devices.append({
                    "id": d.device_id,
                    "name": d.name or "Unknown Device",
                    "ip": d.ip_address or "-",
                    "vendor": d.vendor or "Generic",
                    "site": d.site or "-",
                    "status": d.status or "UP",
                    "url": f"/device/{d.device_id}#deviceHeaderCard"
                })
                if len(matched_devices) >= 10:
                    break

        # 2. ACTIVE ALERTS (Antrean berjalan yang butuh mitigasi)
        active_alerts = session.query(Alert).filter(
            Alert.resolved_at == None
        ).order_by(Alert.triggered_at.desc()).all()
        matched_alerts = []
        for a in active_alerts:
            dev = dev_map.get(a.device_id)
            dev_name = (dev.name or "").lower() if dev else ""
            dev_ip = (dev.ip_address or "").lower() if dev else ""
            dev_vendor = (dev.vendor or "").lower() if dev else ""
            a_type = (a.type or "").lower()
            a_msg = (a.message or "").lower()
            a_sev = (a.severity or "").lower()
            ack_by = (a.acknowledged_by or "").lower()

            is_id_match = (numeric_id is not None and a.alert_id == numeric_id) or (clean_q and clean_q in f"alert-{a.alert_id}") or (clean_q and clean_q == str(a.alert_id))

            is_ack_match = False
            if ql in ["pending", "pending ack", "unack", "unacknowledged"] and not a.acknowledged:
                is_ack_match = True
            elif ql in ["ack", "acked", "acknowledged"] and a.acknowledged:
                is_ack_match = True
            elif ack_by and ql in ack_by:
                is_ack_match = True

            if (is_id_match or
                ql in a_type or 
                ql in a_msg or 
                ql in a_sev or 
                ql in dev_name or
                ql in dev_ip or
                ql in dev_vendor or
                is_ack_match):
                matched_alerts.append({
                    "id": a.alert_id,
                    "type": a.type or "ANOMALY",
                    "severity": a.severity or "WARNING",
                    "message": (a.message or "")[:75] + ("..." if len(a.message or "") > 75 else ""),
                    "device_name": dev.name if dev else "Unknown Device",
                    "ip": dev.ip_address if dev else "-",
                    "triggered_at": a.triggered_at.strftime("%d/%m %H:%M") if a.triggered_at else "-",
                    "acknowledged": bool(a.acknowledged),
                    "url": f"/alerts#alert-row-{a.alert_id}"
                })
                if len(matched_alerts) >= 10:
                    break

        # 3. INCIDENT LOG & COOLDOWN HISTORY (Ultra fast using dev_map, zero extra SQL calls!)
        all_incidents = session.query(IncidentLog).filter(
            IncidentLog.started_at >= cutoff_30d
        ).order_by(IncidentLog.started_at.desc()).all()

        matched_incidents = []
        for inc in all_incidents:
            dev = dev_map.get(inc.device_id)
            dev_name = (dev.name or "").lower() if dev else ""
            dev_ip = (dev.ip_address or "").lower() if dev else ""
            dev_vendor = (dev.vendor or "").lower() if dev else ""
            inc_code = f"inc-{inc.incident_id}".lower()
            status_raw = (inc.status or "").lower()
            status_clean = status_raw.replace('_', ' ')
            peak_metric_val = (inc.peak_metric or "").lower()
            
            if inc.status == 'AUTO_COOLDOWN':
                status_label = "Cooldown"
            elif inc.status == 'RESOLVED_ALERT':
                status_label = "Resolved"
            elif inc.status == 'ACTIVE_MONITORING':
                status_label = "Monitoring"
            elif inc.status in ['ACTIVE_ALERT', 'ESCALATED_TO_ALERT']:
                status_label = "Active Alert"
            else:
                status_label = inc.status or "Incident"

            is_inc_id_match = (numeric_id is not None and inc.incident_id == numeric_id) or (clean_q and clean_q in inc_code) or (clean_q and clean_q == str(inc.incident_id))

            is_status_match = False
            if inc.status == 'RESOLVED_ALERT' and any(k in ql for k in ["resolved", "resolved alert", "resolve", "selesai"]):
                is_status_match = True
            elif inc.status == 'AUTO_COOLDOWN' and any(k in ql for k in ["cooldown", "auto cooldown", "cooling"]):
                is_status_match = True
            elif inc.status == 'ACTIVE_MONITORING' and any(k in ql for k in ["monitoring", "active monitoring"]):
                is_status_match = True
            elif ql in ["incident", "incidents", "insiden"]:
                is_status_match = True
            elif ql in ["alert", "alerts", "peringatan"] and inc.status in ['ACTIVE_ALERT', 'ESCALATED_TO_ALERT', 'RESOLVED_ALERT']:
                is_status_match = True

            has_nospace_match = len(clean_nospace) >= 2 and (clean_nospace in re.sub(r'[\s\-_]+', '', status_raw))

            if (is_inc_id_match or 
                ql in dev_name or 
                ql in dev_ip or 
                ql in dev_vendor or
                ql in (inc.type or "").lower() or 
                ql in (inc.severity or "").lower() or 
                ql in status_raw or 
                ql in status_clean or
                ql in status_label.lower() or
                has_nospace_match or
                ql in peak_metric_val or
                is_status_match):
                
                dur_str = "-"
                if inc.duration_seconds and inc.duration_seconds > 0:
                    m, s = divmod(inc.duration_seconds, 60)
                    h, m = divmod(m, 60)
                    if h > 0:
                        dur_str = f"{h}h {m}m"
                    elif m > 0:
                        dur_str = f"{m}m {s}s"
                    else:
                        dur_str = f"{s}s"

                matched_incidents.append({
                    "id": inc.incident_id,
                    "code": f"#INC-{inc.incident_id}",
                    "device_name": dev.name if dev else "Unknown Device",
                    "ip": dev.ip_address if dev else "-",
                    "type": inc.type or "INCIDENT",
                    "severity": inc.severity or "WARNING",
                    "peak_metric": inc.peak_metric or "-",
                    "status": inc.status or "MONITORING",
                    "status_label": status_label,
                    "started_at": inc.started_at.strftime("%d/%m %H:%M") if inc.started_at else "-",
                    "duration": dur_str,
                    "url": f"/alerts#inc-row-{inc.incident_id}"
                })
                if len(matched_incidents) >= 10:
                    break

        # 4. CONFIGURATION BACKUPS (Ultra fast using dev_map, safe os.path.basename)
        all_backups = session.query(BackupHistory).order_by(BackupHistory.timestamp.desc(), BackupHistory.backup_id.desc()).all()
        matched_backups = []
        for b in all_backups:
            dev = dev_map.get(b.device_id)
            dev_name = (dev.name or "").lower() if dev else ""
            dev_ip = (dev.ip_address or "").lower() if dev else ""
            dev_vendor = (dev.vendor or "").lower() if dev else ""
            dev_site = (dev.site or "").lower() if dev else ""
            
            raw_fp = b.file_path or ""
            file_name = os.path.basename(raw_fp) if raw_fp else f"backup-{b.backup_id}.cfg"

            cat = (getattr(b, 'category', None) or "").lower()
            if not cat:
                fp_lower = raw_fp.lower()
                if "_system" in fp_lower or "logbuffer" in fp_lower:
                    cat = "system"
                elif "_traffic" in fp_lower:
                    cat = "traffic"
                elif "_threat" in fp_lower:
                    cat = "threat"
                else:
                    cat = "config"

            trigger_str = (b.trigger_by or "").lower()
            status_str = (b.status or "").lower()

            is_backup_id_match = (numeric_id is not None and b.backup_id == numeric_id) or (clean_q and clean_q in f"backup-{b.backup_id}")

            if (is_backup_id_match or
                ql in file_name.lower() or 
                ql in dev_name or 
                ql in dev_ip or
                ql in dev_vendor or
                ql in dev_site or
                ql in cat or
                ql in trigger_str or
                ql in status_str):
                matched_backups.append({
                    "id": b.backup_id,
                    "file_name": file_name,
                    "device_name": dev.name if dev else "Unknown Device",
                    "site": dev.site if dev and dev.site else "-",
                    "date": b.timestamp.strftime("%d/%m %H:%M") if b.timestamp else "-",
                    "size": b.file_size or "0 B",
                    "status": b.status or "SUCCESS",
                    "category": cat.upper(),
                    "url": f"/backups#backup-row-{b.backup_id}"
                })
                if len(matched_backups) >= 10:
                    break

        # 5. TELEGRAM BOT INTEGRATION
        matched_telegram = []

        all_tg_users = session.query(TelegramWhitelist).order_by(TelegramWhitelist.id.asc()).all()
        for u in all_tg_users:
            u_name = (u.engineer_name or "").lower()
            # Whitelist search: strictly Technician Name only, include all matched data
            if ql in u_name:
                matched_telegram.append({
                    "id": u.id,
                    "is_whitelist": True,
                    "title": f"{u.engineer_name} ({u.telegram_username})",
                    "desc": f"Technician: {u.engineer_name} • Role: {u.role} • Chat ID: {u.chat_id}",
                    "status": "ACTIVE" if u.is_active else "INACTIVE",
                    "url": f"/telegram#whitelist-row-{u.id}"
                })

        tg_commands = [
            {"cmd": "/start", "desc": "Start bot interaction & operational guide"},
            {"cmd": "/status", "desc": "Health summary of all network devices"},
            {"cmd": "/devices", "desc": "Inventory table of all network devices"},
            {"cmd": "/device", "desc": "Real-time CPU, RAM, & Uptime for a device"},
            {"cmd": "/alerts", "desc": "List of active network anomalies & alerts"},
            {"cmd": "/ack", "desc": "Acknowledge alert handling by engineer"},
            {"cmd": "/resolve", "desc": "Mark network incident as resolved"},
            {"cmd": "/backup", "desc": "Trigger manual running-config backup"},
            {"cmd": "/user", "desc": "Engineer profile & Whitelist verification"},
            {"cmd": "/approve", "desc": "Approve new engineer access role"}
        ]
        count_cmd = 0
        for c in tg_commands:
            clean_cmd = c["cmd"].replace('/', '')
            if (ql in c["cmd"].lower() or 
                ql in clean_cmd.lower() or
                ql in c["desc"].lower() or 
                (ql.startswith('/') and ql in c["cmd"].lower())):
                matched_telegram.append({
                    "id": c["cmd"],
                    "title": f"Bot Command: {c['cmd']}",
                    "desc": c["desc"],
                    "status": "COMMAND",
                    "url": f"/telegram#cmd-row-{clean_cmd}"
                })
                count_cmd += 1
                if count_cmd >= 3:
                    break

        msg_logs = session.query(TelegramMessageLog).filter(
            TelegramMessageLog.sent_at >= cutoff_30d
        ).order_by(TelegramMessageLog.sent_at.desc(), TelegramMessageLog.id.desc()).all()
        count_msg = 0
        for m in msg_logs:
            m_content = (m.content or "").lower()
            m_type = (m.message_type or "").lower()
            m_status = (m.status or "").lower()
            m_chat = str(m.chat_id or "")

            if (ql in m_content or 
                ql in m_type or 
                ql in m_status or
                ql in m_chat):
                clean_content = re.sub(r'<[^>]+>', '', m.content or '').strip()
                clean_content = ' '.join(clean_content.split())
                snippet = clean_content[:65] + ("..." if len(clean_content) > 65 else "")
                time_str = m.sent_at.strftime("%d/%m %H:%M") if m.sent_at else "-"
                matched_telegram.append({
                    "id": m.id,
                    "title": f"Log: {snippet}",
                    "desc": f"{m.message_type or 'DISPATCH'} • Chat ID: {m.chat_id} • {time_str}",
                    "status": m.status or "SENT",
                    "url": f"/telegram#msglog-row-{m.id}"
                })
                count_msg += 1
                if count_msg >= 3:
                    break

        # 6. QUICK NAVIGATION MENUS
        navigation_items = [
            {
                "title": "Monitoring Dashboard",
                "desc": "Real-time metrics and full device inventory",
                "category": "Navigation Menu",
                "keywords": ["dashboard", "monitoring", "home", "graph", "metrics", "switch", "traffic", "cpu", "perangkat", "ringkasan", "alat", "grafik"],
                "url": "/"
            },
            {
                "title": "Alert & Incident Center",
                "desc": "Active alarms, incident log history, and device cooldown",
                "category": "Navigation Menu",
                "keywords": ["alert", "alerts", "incident", "alarm", "anomaly", "ack", "notif", "warning", "cooldown", "resolved", "peringatan", "gangguan", "anomali", "insiden"],
                "url": "/alerts"
            },
            {
                "title": "Configuration Backups",
                "desc": "Manage device running-config backups and audit archives",
                "category": "Navigation Menu",
                "keywords": ["backup", "backups", "config", "configuration", "file", "download", "diff", "cadangan", "konfigurasi", "unduh"],
                "url": "/backups"
            },
            {
                "title": "Telegram Bot Integration",
                "desc": "Bot control center, technician whitelist, and dispatch audit logs",
                "category": "Navigation Menu",
                "keywords": ["telegram", "bot", "whitelist", "chat", "command", "engineer", "noc", "teknisi", "perintah"],
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
    except Exception as e:
        logger.error(f"[api_search] Error processing search query '{q}': {e}", exc_info=True)
        return jsonify({
            "query": q,
            "total_results": 0,
            "categories": {
                "devices": [],
                "alerts": [],
                "incidents": [],
                "backups": [],
                "telegram": [],
                "navigation": []
            }
        })
    finally:
        session.close()

@app.route('/api/status')
def api_status():
    """
    Endpoint JSON real-time untuk polling frontend Chart.js & tabel status.
    Mendukung parameter ?range=live|1h|12h|24h untuk histori rentang waktu.
    """
    session = db_session()
    range_mode = request.args.get('range', 'live')
    devices = session.query(Device).order_by(Device.device_id.asc()).all()
    active_alerts = session.query(Alert).filter(Alert.resolved_at == None).order_by(Alert.triggered_at.desc()).all()

    online_devs = [d for d in devices if d.status == 'UP']
    avg_cpu = round(sum(d.cpu_usage for d in online_devs) / len(online_devs), 1) if online_devs else 0
    avg_mem = round(sum(d.mem_usage for d in online_devs) / len(online_devs), 1) if online_devs else 0
    devices_data = [d.to_dict() for d in devices]
    alerts_data = [a.to_dict() for a in active_alerts]
    history_data = get_aggregated_chart_history(range_mode, session=session)
    wan_data = get_wan_metrics_summary(session=session)
    wan_history = get_wan_chart_history(range_mode, session=session)
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
        "wan": wan_data,
        "wan_history": wan_history,
        "history": history_data,
        "devices": devices_data,
        "alerts": alerts_data
    }
    return jsonify(payload)

@app.route('/api/wan/logs')
def api_wan_logs():
    """Mengambil riwayat log status WAN Biznet (ethernet1/3) dalam 24 jam terakhir (interval 2 menit)."""
    session = db_session()
    try:
        now = datetime.now()
        cutoff = now - timedelta(hours=24)
        logs = session.query(WanStatusLog).filter(
            WanStatusLog.timestamp >= cutoff
        ).order_by(WanStatusLog.timestamp.desc()).all()

        if not logs:
            logs = session.query(WanStatusLog).order_by(
                WanStatusLog.timestamp.desc()
            ).limit(720).all()

        # Data riil dari database: baris paling atas di See Log adalah data polling terbaru yang sama persis dengan KPI Card.
        historical_logs = logs

        result = []
        for row in historical_logs:
            result.append({
                "id": row.id,
                "timestamp": row.timestamp.strftime("%Y-%m-%d %H:%M:%S") if row.timestamp else "-",
                "time_short": row.timestamp.strftime("%H:%M:%S") if row.timestamp else "-",
                "interface": row.interface_name or "ethernet1/3",
                "provider": row.provider or "Biznet",
                "status": row.status or "UP",
                "download_mbps": round(row.download_mbps or 0.0, 2),
                "upload_mbps": round(row.upload_mbps or 0.0, 2),
                "total_mbps": round(row.total_mbps or 0.0, 2),
                "latency_ms": round(row.latency_ms or 0.0, 1),
                "gateway_latency_ms": round(row.gateway_latency_ms or 0.0, 1),
                "packet_loss": round(row.packet_loss or 0.0, 1),
                "rx_errors": row.rx_errors or 0,
                "tx_errors": row.tx_errors or 0,
                "total_errors": (row.rx_errors or 0) + (row.tx_errors or 0)
            })

        return jsonify({
            "status": "success",
            "count": len(result),
            "logs": result
        })
    except Exception as e:
        session.rollback()
        logger.error(f"Error fetching WAN logs: {e}")
        return jsonify({"status": "error", "message": str(e), "logs": []}), 500
    finally:
        session.close()

@app.route('/api/wan/speedtest', methods=['GET', 'POST'])
def api_wan_speedtest():
    """
    Eksekusi speedtest on-demand real-time untuk jalur WAN Biznet (ethernet1/3).
    Melakukan pengukuran langsung:
    1. Ping ICMP ke 1.1.1.1 (Internet) & 192.168.18.1 (Gateway ISP Biznet).
    2. Delta throughput langsung dari Palo Alto interface ethernet1/3 (atau live sample).
    3. Menyimpan hasil instan ke WanStatusLog di database PostgreSQL.
    4. Mengembalikan ringkasan WAN terkini ke frontend.
    """
    import platform
    import subprocess
    import re
    import time

    def _ping(host, count=2, timeout_sec=1):
        try:
            is_win = platform.system().lower() == "windows"
            timeout_ms = int(timeout_sec * 1000)
            cmd = ["ping", "-n", str(count), "-w", str(timeout_ms), str(host)] if is_win else ["ping", "-c", str(count), "-W", str(timeout_sec), str(host)]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=(count * timeout_sec) + 3)
            out = res.stdout or ""
            loss_pct = 100.0
            avg_lat = 0.0

            m_loss = re.search(r'\((\d+)%\s+loss\)', out) or re.search(r'(\d+)%\s+packet loss', out)
            if m_loss:
                loss_pct = float(m_loss.group(1))

            m_avg = re.search(r'Average\s*=\s*(\d+)ms', out, re.IGNORECASE) or re.search(r'rtt min/avg/max.*?=\s*[\d\.]+/([\d\.]+)/', out)
            if m_avg:
                avg_lat = float(m_avg.group(1))
            elif loss_pct < 100.0:
                times = re.findall(r'time[=<](\d+)ms', out, re.IGNORECASE)
                if times:
                    avg_lat = float(sum(int(t) for t in times) / len(times))

            return (loss_pct < 100.0), round(avg_lat, 1), round(loss_pct, 1)
        except Exception:
            return False, 0.0, 100.0

    # 1. Jalankan live ping
    inet_up, inet_lat, inet_loss = _ping("1.1.1.1", count=2, timeout_sec=1)
    gw_up, gw_lat, _ = _ping("192.168.18.1", count=1, timeout_sec=1)

    # Validasi konektivitas: Jika tidak ada internet dan gateway tidak tembus
    if not inet_up and not gw_up:
        return jsonify({
            "status": "error",
            "message": "Cannot connect to Biznet internet link or Gateway (192.168.18.1). Please verify physical network connectivity."
        }), 503

    # 2. Eksekusi pengujian kapasitas maksimal jalur Biznet ala Ookla Speedtest
    import subprocess
    import json
    import shutil

    dl_mbps = 0.0
    ul_mbps = 0.0
    lat_ms = inet_lat if inet_lat > 0 else 0.0
    loss_pct = inet_loss
    ookla_success = False

    # A. Coba jalankan Ookla Speedtest CLI resmi (jika terinstall di sistem)
    ookla_bin_candidates = [
        os.path.expanduser(r"~\AppData\Local\Microsoft\WinGet\Links\speedtest.exe"),
        r"C:\Program Files\Speedtest\speedtest.exe",
        shutil.which("speedtest")
    ]
    for b in ookla_bin_candidates:
        if b and os.path.exists(b):
            try:
                cmd = [b, "-f", "json", "--accept-license", "--accept-gdpr"]
                p = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
                if p.returncode == 0 and p.stdout:
                    lines = [ln.strip() for ln in p.stdout.strip().splitlines() if ln.strip().startswith('{') and ln.strip().endswith('}')]
                    if lines:
                        d = json.loads(lines[-1])
                        if "download" in d and "upload" in d:
                            dl_mbps = round((d["download"].get("bandwidth", 0) * 8.0) / 1_000_000.0, 1)
                            ul_mbps = round((d["upload"].get("bandwidth", 0) * 8.0) / 1_000_000.0, 1)
                            lat_ms = round(d.get("ping", {}).get("latency", inet_lat), 1)
                            loss_pct = round(d.get("packetLoss", inet_loss), 1)
                            ookla_success = True
                            break
            except Exception as e_ookla:
                logger.warning(f"Ookla CLI runner attempt failed: {e_ookla}")

    # B. Coba python speedtest-cli library (jika Ookla CLI gagal)
    if not ookla_success:
        try:
            cmd_py = ["python", "-m", "speedtest", "--secure", "--json"]
            p_py = subprocess.run(cmd_py, capture_output=True, text=True, timeout=45)
            if p_py.returncode == 0 and p_py.stdout:
                d_py = json.loads(p_py.stdout.strip())
                dl_mbps = round(d_py.get("download", 0.0) / 1_000_000.0, 1)
                ul_mbps = round(d_py.get("upload", 0.0) / 1_000_000.0, 1)
                if "ping" in d_py:
                    lat_ms = round(d_py["ping"], 1)
                ookla_success = True
        except Exception as e_py:
            logger.warning(f"Python speedtest runner attempt failed: {e_py}")

    # C. Jika pengujian benchmark gagal dieksekusi secara riil, kembalikan error (TIDAK ADA DATA DUMMY / SIMULASI)
    if not ookla_success or dl_mbps == 0.0:
        return jsonify({
            "status": "error",
            "message": "Speedtest execution failed. Please verify internet connectivity and Ookla CLI installation."
        }), 500

    total_mbps = round(dl_mbps + ul_mbps, 1)
    link_status = "UP" if inet_up or gw_up else "DOWN"

    speedtest_result = {
        "provider": "Biznet Networks",
        "interface": "ethernet1/3",
        "device_name": "FW-PA220-1",
        "status": link_status,
        "download_mbps": dl_mbps,
        "upload_mbps": ul_mbps,
        "total_mbps": total_mbps,
        "capacity_mbps": 100.0,
        "latency_ms": lat_ms,
        "gateway_latency_ms": gw_lat if gw_lat > 0 else 0.0,
        "packet_loss": loss_pct,
        "quality_label": "Normal Connection" if loss_pct <= 2.0 and lat_ms <= 45.0 else "Abnormal Connection",
        "quality_color": "green" if loss_pct <= 2.0 and lat_ms <= 45.0 else "red",
        "last_updated": datetime.now().strftime('%H:%M:%S')
    }

    # Penting: Speedtest on-demand ini KHUSUS untuk tampilan modal pengujian kapasitas maksimal,
    # dan TIDAK disimpan ke WanStatusLog agar tidak menimpa data utilisasi pemakaian aktif di kartu dashboard.
    return jsonify({
        "status": "success",
        "message": f"Speedtest Completed Successfully! Download: {dl_mbps} Mbps, Upload: {ul_mbps} Mbps, Ping: {lat_ms} ms",
        "speedtest": speedtest_result,
        "wan": speedtest_result
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
    if res.get("memory_pct") is not None and "aruba" in device.vendor.lower():
        device.mem_usage = round(float(res.get("memory_pct")), 1)
    res = telemetry.get("resources", {})
    pb_raw = res.get("packet_buffers_pct")
    mb_raw = res.get("message_buffers_pct")
    pb_base = float(pb_raw) if pb_raw is not None else 0.0
    mb_base = float(mb_raw) if mb_raw is not None else 0.0
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
            mem_val = round(b.mem_usage or 0.0, 1)
            # Selaraskan jika ada titik histori lama Aruba yang sempat merekam nilai inversi (~60-65%):
            if "aruba" in device.vendor.lower() and mem_val > 50.0 and res.get("memory_pct", 0) < 50.0:
                mem_val = round(100.0 - mem_val, 1)
            mem_vals.append(mem_val)
            lat_vals.append(round(b.latency_ms or 0.0, 1))
            loss_vals.append(round(b.packet_loss or 0.0, 1))
            trf_vals.append(round(b.traffic_mbps or 0.0, 2))
            trf_in_vals.append(round(b.ingress_mbps or 0.0, 2))
            trf_out_vals.append(round(b.egress_mbps or 0.0, 2))
            pb_vals.append(round(b.packet_buffers or 0.0, 1))
            mb_vals.append(round(b.message_buffers or 0.0, 1))
            # Ambil data error & drop: selaraskan dengan akumulasi riil seluruh port perangkat
            cur_td = int(b.tx_drops or 0)
            cur_re = int(b.rx_errors or 0)
            cur_te = int(b.tx_errors or 0)
            if cur_td == 0 and cur_re == 0 and cur_te == 0 and (td_val > 0 or re_val > 0 or te_val > 0):
                cur_td = td_val
                cur_re = re_val
                cur_te = te_val
            td_vals.append(cur_td)
            re_vals.append(cur_re)
            te_vals.append(cur_te)

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
        "current_packet_buffers": pb_vals[-1] if pb_vals else pb_base,
        "current_tx_drops": td_vals[-1] if td_vals else td_val,
        "current_message_buffers": mb_vals[-1] if mb_vals else mb_base,
        "current_rx_errors": re_vals[-1] if re_vals else re_val,
        "current_tx_errors": te_vals[-1] if te_vals else te_val,
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

@app.route('/api/ap/<path:ap_name>/clients')
def api_ap_clients(ap_name):
    """Mengambil telemetri wireless client (bandwidth, RSSI, SSID, IP/MAC) untuk AP tertentu via SNMP & FDB correlation."""
    try:
        force = request.args.get('force', '').lower() in ['1', 'true', 'yes']
        data = get_ap_client_telemetry(ap_name, force=force)
        return jsonify({"success": True, "data": data})
    except Exception as e:
        logger.error(f"Gagal mengambil data klien AP {ap_name}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    print(f"[*] Starting PT Agiva Network Operations Dashboard on http://127.0.0.1:{port}")
    app.run(host='0.0.0.0', port=port, debug=True, threaded=True)

# PostgreSQL reload trigger - full dynamic Palo Alto specs (All 10 hardware parameters + ports)
