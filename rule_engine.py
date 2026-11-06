"""
=============================================================================
PT AGIVA INDONESIA - NETWORK OPERATIONS AUTOMATION
Komponen 4: Rule Engine, 10-Minute Incident State Machine & Resilient Alerting
=============================================================================
Tanggung Jawab:
1. Evaluasi metrik telemetri perangkat terhadap batas ambang (Threshold).
2. Mekanisme 10-Minute State Machine:
   - Detik 0: Notifikasi Early Warning Real-Time ke Telegram.
   - < 10 Menit & Pulih: Masuk ke tabel incident_logs sebagai 'AUTO_COOLDOWN' 
     dan kirim notifikasi cooldown ke Telegram (tabel Alert Aktif tetap bersih).
   - >= 10 Menit & Belum Pulih: Eskalasi masuk ke tabel alerts (Active Alerts) 
     dan kirim notifikasi darurat ke Telegram.
   - Alert Aktif Pulih: Di-resolve dan dicatat ke incident_logs sebagai 'RESOLVED_ALERT'.
3. Resilient Telegram Dispatch: Retry 2x dengan timeout eksplisit dan fail-safe.
4. Logging terpusat dengan RotatingFileHandler.
=============================================================================
"""

import os
import json
import time
import urllib.request
from datetime import datetime
from dotenv import load_dotenv

from models import Alert, IncidentLog, TelegramMessageLog
from logger_config import get_configured_logger

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = os.path.join(BASE_DIR, '.env')
load_dotenv(ENV_PATH, override=True)

logger = get_configured_logger("RuleEngine")


def send_telegram_broadcast(message_text, parse_mode='HTML'):
    """
    Mengirim pesan broadcast ke grup Telegram NOC dengan mekanisme:
    - Try/Except terisolasi
    - Retry terbatas (2x percobaan)
    - Timeout eksplisit (7 detik)
    - Fail-safe: kegagalan di-log tanpa menghentikan proses utama.
    """
    load_dotenv(ENV_PATH, override=True)
    tg_token = os.getenv('TELEGRAM_BOT_TOKEN')
    tg_chat_id = os.getenv('NOC_TELEGRAM_CHAT_ID', '-1004429503436')

    if not tg_token or tg_token.startswith('123456'):
        logger.warning("Token Telegram belum diset di .env atau masih default.")
        return False, 'Token Telegram belum diset di .env'

    url = f'https://api.telegram.org/bot{tg_token}/sendMessage'
    payload = {
        'chat_id': tg_chat_id,
        'text': message_text,
        'parse_mode': parse_mode
    }

    max_retries = 2
    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode('utf-8'),
                headers={'Content-Type': 'application/json'}
            )
            with urllib.request.urlopen(req, timeout=7) as resp:
                if resp.status == 200:
                    return True, 'SENT'
        except Exception as e:
            logger.warning(f"Percobaan {attempt}/{max_retries} kirim pesan Telegram gagal: {e}")
            if attempt < max_retries:
                time.sleep(1.0)
            else:
                logger.error(f"Gagal mengirim pesan Telegram setelah {max_retries}x percobaan: {e}")
                return False, f'FAILED: {str(e)[:90]}'

    return False, 'FAILED: Max retries exceeded'


def is_early_warning_telegram_enabled(alert_type):
    """
    Menentukan apakah pesan Telegram Detik ke-0 (Early Warning) perlu dikirim ke grup:
    1. Khusus alert_type == 'HOST_DOWN': dikirim langsung di detik nol jika TELEGRAM_IMMEDIATE_HOST_DOWN == True.
    2. Sistem yang lain (CPU, RAM, Latency, Loss): default senyap di detik nol (hanya kirim jika TELEGRAM_ENABLE_EARLY_WARNING == True).
    """
    load_dotenv(ENV_PATH, override=True)
    if alert_type == 'HOST_DOWN':
        immediate_host_down = os.getenv('TELEGRAM_IMMEDIATE_HOST_DOWN', 'true').strip().lower() in ('true', '1', 'yes')
        return immediate_host_down

    enable_early = os.getenv('TELEGRAM_ENABLE_EARLY_WARNING', 'false').strip().lower() in ('true', '1', 'yes')
    return enable_early


def trigger_alert_with_antispam(session, device, alert_type, severity, message, peak_metric_val=None):
    """
    Mekanisme Anomali & Aturan 10 Menit (State Machine Real-Time):
    1. Detik ke-0 (Anomali Baru):
       - Simpan ke IncidentLog (status: 'ACTIVE_MONITORING')
       - Evaluasi Senyap / Kirim Early Warning (hanya jika diaktifkan atau HOST_DOWN)
    2. Polling Berikutnya (< 10 Menit):
       - Tetap dalam pemantauan, update peak_metric jika ada kenaikan
       - Anti-spam menahan pengiriman ulang agar grup tidak bising
    3. Jika Bertahan >= 10 Menit:
       - Eskalasi: Masukkan ke tabel `alerts` (Active Alerts)
       - Update status IncidentLog -> 'ACTIVE_ALERT'
       - Kirim notifikasi darurat 🚨 ke Telegram
    """
    target_chat_id = os.getenv('NOC_TELEGRAM_CHAT_ID', '-1004429503436')
    metric_display = str(peak_metric_val) if peak_metric_val else severity

    # 1. Cek apakah ada insiden aktif yang sedang dalam pemantauan untuk anomali ini
    active_incident = session.query(IncidentLog).filter(
        IncidentLog.device_id == device.device_id,
        IncidentLog.type == alert_type,
        IncidentLog.resolved_at == None,
        IncidentLog.status.in_(['ACTIVE_MONITORING', 'ACTIVE_ALERT', 'ESCALATED_TO_ALERT'])
    ).first()

    now = datetime.now()

    # =========================================================================
    # KASUS 1: Anomali Baru Pertama Kali Terdeteksi (Detik ke-0)
    # =========================================================================
    if not active_incident:
        new_incident = IncidentLog(
            device_id=device.device_id,
            type=alert_type,
            severity=severity,
            peak_metric=metric_display,
            started_at=now,
            resolved_at=None,
            duration_seconds=0,
            status='ACTIVE_MONITORING'
        )
        session.add(new_incident)
        session.flush()

        should_send = is_early_warning_telegram_enabled(alert_type)

        if should_send:
            # Format real-time early warning message to Telegram
            early_msg = (
                f"⚡ <b>[AGIVA NOC - REAL-TIME ANOMALY DETECTED]</b> ⚡\n\n"
                f"📌 <b>Device:</b> {device.name} ({device.ip_address})\n"
                f"📌 <b>Vendor / Site:</b> {device.vendor} ({device.site})\n"
                f"📌 <b>Anomaly Type:</b> {alert_type}\n"
                f"📌 <b>Severity:</b> {severity}\n"
                f"📌 <b>Metric Value:</b> {metric_display}\n"
                f"📌 <b>Detection Time:</b> {now.strftime('%Y-%m-%d %H:%M:%S')} WIB\n"
                f"📌 <b>Status:</b> Active Monitoring (10-Minute Evaluation Window)\n\n"
                f"💡 <i>If recovered in &lt; 10 mins, anomaly is logged to Incident Log (Cooldown). "
                f"If persistent for ≥ 10 mins, system escalates to Active Alerts.</i>"
            )

            ok, delivery_status = send_telegram_broadcast(early_msg, parse_mode='HTML')
            status_str = "SENT" if ok else str(delivery_status)[:90]

            log_entry = TelegramMessageLog(
                alert_id=None,
                chat_id=target_chat_id,
                message_type="EARLY_WARNING",
                content=early_msg,
                status=status_str,
                sent_at=now
            )
            session.add(log_entry)
            session.commit()

            logger.info(f"[RuleEngine] Anomali terdeteksi: {device.name} - {alert_type} ({metric_display}). Early warning dikirim ke Telegram.")
            return True, new_incident, "Deteksi anomali baru, early warning real-time dikirim."
        else:
            session.commit()
            logger.info(f"[RuleEngine] Anomali terdeteksi: {device.name} - {alert_type} ({metric_display}). Jendela pemantauan 10 menit dimulai secara senyap (Telegram muted).")
            return True, new_incident, "Deteksi anomali baru, evaluasi senyap 10 menit aktif (Telegram silent)."

    # =========================================================================
    # KASUS 2: Anomali Masih Berlangsung (Evaluasi Durasi 10 Menit)
    # =========================================================================
    elapsed_seconds = (now - active_incident.started_at).total_seconds()
    active_incident.duration_seconds = int(elapsed_seconds)

    # Perbarui peak_metric jika ada
    if peak_metric_val and active_incident.peak_metric != metric_display:
        active_incident.peak_metric = metric_display

    # Cek apakah durasi sudah mencapai atau melewati 10 menit (600 detik)
    if elapsed_seconds >= 600 and active_incident.status == 'ACTIVE_MONITORING':
        # ESKALASI KE ACTIVE ALERTS!
        active_incident.status = 'ACTIVE_ALERT'

        # Buat entri di tabel alerts
        existing_alert = session.query(Alert).filter(
            Alert.device_id == device.device_id,
            Alert.type == alert_type,
            Alert.resolved_at == None
        ).first()

        if not existing_alert:
            new_alert = Alert(
                device_id=device.device_id,
                type=alert_type,
                severity=severity,
                message=message,
                triggered_at=active_incident.started_at,
                acknowledged=False
            )
            session.add(new_alert)
            session.flush()
            alert_id = new_alert.alert_id
        else:
            alert_id = existing_alert.alert_id

        # Format emergency escalation message to Telegram
        dur_mins = int(elapsed_seconds // 60)
        escalate_msg = (
            f"🚨 <b>[AGIVA NOC - {severity} ALERT (≥ 10 MINS)]</b> 🚨\n\n"
            f"📌 <b>Alert ID:</b> #{alert_id}\n"
            f"📌 <b>Device:</b> {device.name} ({device.ip_address})\n"
            f"📌 <b>Vendor / Site:</b> {device.vendor} ({device.site})\n"
            f"📌 <b>Anomaly Type:</b> {alert_type}\n"
            f"📌 <b>Issue Detail:</b> {message}\n"
            f"📌 <b>Incident Duration:</b> Active for {dur_mins} mins (since {active_incident.started_at.strftime('%H:%M:%S')} WIB)\n"
            f"📌 <b>Status:</b> Active Alert (Action Required)\n\n"
            f"💡 <i>Type /ack {alert_id} in Telegram Bot to acknowledge operational ticket handling.</i>"
        )

        ok, delivery_status = send_telegram_broadcast(escalate_msg, parse_mode='HTML')
        status_str = "SENT" if ok else str(delivery_status)[:90]

        log_entry = TelegramMessageLog(
            alert_id=alert_id,
            chat_id=target_chat_id,
            message_type="ALERT_NOTIFICATION",
            content=escalate_msg,
            status=status_str,
            sent_at=now
        )
        session.add(log_entry)
        session.commit()

        logger.warning(f"[RuleEngine] ESKALASI ALERT #{alert_id}: {device.name} - {alert_type} telah berlangsung {dur_mins} menit.")
        return True, active_incident, "Anomali bertahan ≥ 10 menit, dieskalasi ke Alert Aktif."

    # Spam tertahan selama periode cooldown atau jika sudah dieskalasi
    session.commit()
    return False, active_incident, "Dalam pemantauan aktif / cooldown."


def auto_resolve_alert(session, device, alert_type, recovery_message=None):
    """
    Otomatis menyelesaikan status anomali:
    1. Jika anomali pulih dalam < 10 Menit:
       - Status IncidentLog -> 'AUTO_COOLDOWN'
       - Kirim notifikasi Telegram: '⚡ ANOMALI PULIH / COOLDOWN'
       - Tabel alerts tetap bersih.
    2. Jika anomali sebelumnya sudah dieskalasi (>= 10 Menit):
       - Selesaikan alert di tabel `alerts` (resolved_at diisi)
       - Status IncidentLog -> 'RESOLVED_ALERT'
       - Kirim notifikasi Telegram: '✅ RECOVERY NOTIFICATION'
    """
    target_chat_id = os.getenv('NOC_TELEGRAM_CHAT_ID', '-1004429503436')
    now = datetime.now()

    # 1. Cari incident log aktif
    active_incident = session.query(IncidentLog).filter(
        IncidentLog.device_id == device.device_id,
        IncidentLog.type == alert_type,
        IncidentLog.resolved_at == None,
        IncidentLog.status.in_(['ACTIVE_MONITORING', 'ACTIVE_ALERT', 'ESCALATED_TO_ALERT'])
    ).first()

    # 2. Cari juga alert aktif jika ada
    active_alert = session.query(Alert).filter(
        Alert.device_id == device.device_id,
        Alert.type == alert_type,
        Alert.resolved_at == None
    ).first()

    if not active_incident and not active_alert:
        return False, None

    # Hitung durasi anomali
    started_time = active_incident.started_at if active_incident else (active_alert.triggered_at if active_alert else now)
    dur_sec = max(1, int((now - started_time).total_seconds()))
    m, s = divmod(dur_sec, 60)
    h, m = divmod(m, 60)
    if h > 0:
        dur_str = f"{h}h {m}m {s}s"
    elif m > 0:
        dur_str = f"{m}m {s}s"
    else:
        dur_str = f"{s}s"

    is_cooldown = active_incident and (active_incident.status == 'ACTIVE_MONITORING') and (dur_sec < 600)

    # =========================================================================
    # KASUS A: Pulih dalam < 10 Menit (AUTO-COOLDOWN)
    # =========================================================================
    if is_cooldown:
        active_incident.resolved_at = now
        active_incident.duration_seconds = dur_sec
        active_incident.status = 'AUTO_COOLDOWN'

        # Khusus HOST_DOWN: Tetap kirim notifikasi cooldown ke Telegram agar NOC tahu perangkat sudah UP kembali!
        # Sistem lain (CPU, RAM, Latency, Loss): Senyap (Telegram silent jika pulih < 10 menit).
        should_send = is_early_warning_telegram_enabled(alert_type)

        if should_send:
            cooldown_msg = (
                f"⚡ <b>[AGIVA NOC - ANOMALY RECOVERED / COOLDOWN]</b> ⚡\n\n"
                f"📌 <b>Device:</b> {device.name} ({device.ip_address})\n"
                f"📌 <b>Vendor / Site:</b> {device.vendor} ({device.site})\n"
                f"📌 <b>Event Type:</b> {alert_type}\n"
                f"📌 <b>Peak Metric:</b> {active_incident.peak_metric or '-'}\n"
                f"📌 <b>Anomaly Duration:</b> {dur_str} (Recovered &lt; 10 Mins)\n"
                f"📌 <b>Recovery Time:</b> {now.strftime('%Y-%m-%d %H:%M:%S')} WIB\n"
                f"📌 <b>Status:</b> Auto-Cooldown (Recorded to Incident Log #{active_incident.incident_id})\n\n"
                f"💡 <i>Transient spike subsided normally without ticket escalation.</i>"
            )

            ok, delivery_status = send_telegram_broadcast(cooldown_msg, parse_mode='HTML')
            status_str = "SENT" if ok else str(delivery_status)[:90]

            log_entry = TelegramMessageLog(
                alert_id=None,
                chat_id=target_chat_id,
                message_type="COOLDOWN_NOTIFICATION",
                content=cooldown_msg,
                status=status_str,
                sent_at=now
            )
            session.add(log_entry)
            session.commit()

            logger.info(f"[RuleEngine] Insiden #{active_incident.incident_id} ({device.name} - {alert_type}) pulih dalam {dur_str} -> AUTO_COOLDOWN dikirim ke Telegram.")
        else:
            session.commit()
            logger.info(f"[RuleEngine] Insiden #{active_incident.incident_id} ({device.name} - {alert_type}) pulih dalam {dur_str} -> AUTO_COOLDOWN dicatat senyap (Telegram silent).")

        return True, active_incident

    # =========================================================================
    # KASUS B: Anomali yang Telah Bertahan di Atas 10 Menit (≥ 10 Menit)
    # =========================================================================
    # Gangguan berlangsung di atas 10 menit (sudah dieskalasi ke Active Alerts).
    # Ketika gangguan pulih, kirimkan notifikasi pemulihan resmi ke Telegram.
    if dur_sec >= 600 or (active_incident and active_incident.status in ('ACTIVE_ALERT', 'ESCALATED_TO_ALERT')) or active_alert:
        if active_incident:
            active_incident.resolved_at = now
            active_incident.duration_seconds = dur_sec
            active_incident.status = 'RESOLVED_ALERT'

        alert_ref = "-"
        if active_alert:
            active_alert.resolved_at = now
            active_alert.acknowledged = True
            alert_ref = f"#{active_alert.alert_id}"

        session.commit()

        recovery_msg = (
            f"✅ <b>[AGIVA NOC - INCIDENT RESOLVED (≥ 10 MINS)]</b> ✅\n\n"
            f"📌 <b>Alert ID:</b> {alert_ref}\n"
            f"📌 <b>Device:</b> {device.name} ({device.ip_address})\n"
            f"📌 <b>Vendor / Site:</b> {device.vendor} ({device.site})\n"
            f"📌 <b>Incident Type:</b> {alert_type}\n"
            f"📌 <b>Total Incident Duration:</b> {dur_str}\n"
            f"📌 <b>Recovery Time:</b> {now.strftime('%Y-%m-%d %H:%M:%S')} WIB\n"
            f"📌 <b>Status:</b> Resolved (Operational)\n\n"
            f"💡 <i>{recovery_message or 'Network metrics returned to normal thresholds.'}</i>"
        )

        ok, delivery_status = send_telegram_broadcast(recovery_msg, parse_mode='HTML')
        status_str = "SENT" if ok else str(delivery_status)[:90]

        log_entry = TelegramMessageLog(
            alert_id=active_alert.alert_id if active_alert else None,
            chat_id=target_chat_id,
            message_type="RECOVERY_NOTIFICATION",
            content=recovery_msg,
            status=status_str,
            sent_at=now
        )
        session.add(log_entry)
        session.commit()

        logger.info(f"[RuleEngine] Alert {alert_ref} ({device.name} - {alert_type}) pulih setelah {dur_str} (≥ 10 Menit) -> Notifikasi pemulihan dikirim ke Telegram.")
        return True, active_alert or active_incident


def evaluate_device_rules(session, device, metrics):

    if device.status == "DOWN":
        trigger_alert_with_antispam(
            session=session,
            device=device,
            alert_type="HOST_DOWN",
            severity="CRITICAL",
            message=f"Device {device.name} ({device.ip_address}) is not responding to ICMP/SSH/API polling.",
            peak_metric_val="DOWN (Unreachable)"
        )
    else:
        auto_resolve_alert(
            session=session,
            device=device,
            alert_type="HOST_DOWN",
            recovery_message=f"Connection to {device.name} ({device.ip_address}) restored successfully (STATUS: UP)."
        )

    cpu_val = float(device.cpu_usage or 0.0)
    if cpu_val > 90.0:
        severity = "CRITICAL" if cpu_val >= 95.0 else "WARNING"
        trigger_alert_with_antispam(
            session=session,
            device=device,
            alert_type="CPU_OVERLOAD",
            severity=severity,
            message=f"CPU utilization spiked to {cpu_val:.1f}% (Threshold: 90%).",
            peak_metric_val=f"{cpu_val:.1f}%"
        )
    elif cpu_val <= 80.0:
        # Auto-resolve jika CPU sudah kembali di bawah 80%
        auto_resolve_alert(
            session=session,
            device=device,
            alert_type="CPU_OVERLOAD",
            recovery_message=f"CPU load on {device.name} normalized ({cpu_val:.1f}%)."
        )

    # 3. Evaluasi Penggunaan Memori (RAM)
    mem_val = float(device.mem_usage or 0.0)
    if mem_val > 90.0:
        severity = "CRITICAL" if mem_val >= 95.0 else "WARNING"
        trigger_alert_with_antispam(
            session=session,
            device=device,
            alert_type="MEMORY_OVERLOAD",
            severity=severity,
            message=f"Memory utilization spiked to {mem_val:.1f}% (Threshold: 90%).",
            peak_metric_val=f"{mem_val:.1f}%"
        )
    elif mem_val <= 80.0:
        # Auto-resolve jika Memory sudah kembali di bawah 80%
        auto_resolve_alert(
            session=session,
            device=device,
            alert_type="MEMORY_OVERLOAD",
            recovery_message=f"Memory utilization on {device.name} normalized ({mem_val:.1f}%)."
        )

    # 4. Evaluasi Latency ICMP (ms)
    lat_val = float(device.latency_ms or 0.0)
    if device.status == "UP":
        if lat_val > 5.0:
            severity = "CRITICAL" if lat_val >= 50.0 else "WARNING"
            trigger_alert_with_antispam(
                session=session,
                device=device,
                alert_type="HIGH_LATENCY",
                severity=severity,
                message=f"ICMP response latency to {device.name} spiked to {lat_val:.1f} ms (Normal limit: 5 ms).",
                peak_metric_val=f"{lat_val:.1f} ms"
            )
        elif lat_val <= 5.0:
            auto_resolve_alert(
                session=session,
                device=device,
                alert_type="HIGH_LATENCY",
                recovery_message=f"Latency to {device.name} normalized ({lat_val:.1f} ms)."
            )

    # 5. Evaluasi Ping Drop / Packet Loss (%)
    loss_val = float(device.packet_loss or 0.0)
    if device.status == "UP":
        # Jika loss > 5% dan < 100% (100% adalah kondisi HOST_DOWN)
        if 5.0 < loss_val < 100.0:
            severity = "CRITICAL" if loss_val >= 25.0 else "WARNING"
            trigger_alert_with_antispam(
                session=session,
                device=device,
                alert_type="PACKET_LOSS",
                severity=severity,
                message=f"Detected packet loss of {loss_val:.1f}% to {device.name} (Normal limit: 5%).",
                peak_metric_val=f"{loss_val:.1f}%"
            )
        elif loss_val <= 0.0:
            auto_resolve_alert(
                session=session,
                device=device,
                alert_type="PACKET_LOSS",
                recovery_message=f"Connection to {device.name} stable without packet loss (0.0%)."
            )
