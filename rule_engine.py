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

load_dotenv(override=True)

logger = get_configured_logger("RuleEngine")


def send_telegram_broadcast(message_text, parse_mode='HTML'):
    """
    Mengirim pesan broadcast ke grup Telegram NOC dengan mekanisme:
    - Try/Except terisolasi
    - Retry terbatas (2x percobaan)
    - Timeout eksplisit (7 detik)
    - Fail-safe: kegagalan di-log tanpa menghentikan proses utama.
    """
    load_dotenv(override=True)
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


def trigger_alert_with_antispam(session, device, alert_type, severity, message, peak_metric_val=None):
    """
    Mekanisme Anomali & Aturan 10 Menit (State Machine Real-Time):
    1. Detik ke-0 (Anomali Baru):
       - Simpan ke IncidentLog (status: 'ACTIVE_MONITORING')
       - Kirim notifikasi Real-Time Early Warning ke Telegram
    2. Polling Berikutnya (< 10 Menit):
       - Tetap dalam pemantauan, update peak_metric jika ada kenaikan
       - Anti-spam menahan pengiriman ulang agar grup tidak bising
    3. Jika Bertahan >= 10 Menit:
       - Eskalasi: Masukkan ke tabel `alerts` (Active Alerts)
       - Update status IncidentLog -> 'ESCALATED_TO_ALERT'
       - Kirim notifikasi darurat 🚨 ke Telegram
    """
    target_chat_id = os.getenv('NOC_TELEGRAM_CHAT_ID', '-1004429503436')
    metric_display = str(peak_metric_val) if peak_metric_val else severity

    # 1. Cek apakah ada insiden aktif yang sedang dalam pemantauan untuk anomali ini
    active_incident = session.query(IncidentLog).filter(
        IncidentLog.device_id == device.device_id,
        IncidentLog.type == alert_type,
        IncidentLog.resolved_at == None,
        IncidentLog.status.in_(['ACTIVE_MONITORING', 'ESCALATED_TO_ALERT'])
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

        # Format pesan Real-Time Early Warning ke Telegram
        early_msg = (
            f"⚡ <b>[NOC AGIVA - DETEKSI ANOMALI REAL-TIME]</b> ⚡\n\n"
            f"📌 <b>Perangkat:</b> {device.name} ({device.ip_address})\n"
            f"📌 <b>Vendor / Site:</b> {device.vendor} ({device.site})\n"
            f"📌 <b>Tipe Anomali:</b> {alert_type}\n"
            f"📌 <b>Tingkat:</b> {severity}\n"
            f"📌 <b>Nilai Metrik:</b> {metric_display}\n"
            f"📌 <b>Waktu Deteksi:</b> {now.strftime('%Y-%m-%d %H:%M:%S')} WIB\n"
            f"📌 <b>Status:</b> Pemantauan Aktif (Jendela Evaluasi 10 Menit)\n\n"
            f"💡 <i>Jika pulih &lt; 10 menit, anomali dicatat ke Incident Log (Cooldown). "
            f"Jika bertahan ≥ 10 menit, sistem akan mengeskalasi ke Active Alerts.</i>"
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

        logger.info(f"[RuleEngine] Anomali terdeteksi: {device.name} - {alert_type} ({metric_display}). Jendela pemantauan 10 menit dimulai.")
        return True, new_incident, "Deteksi anomali baru, early warning real-time dikirim."

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
        active_incident.status = 'ESCALATED_TO_ALERT'

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

        # Format pesan Eskalasi Darurat ke Telegram
        dur_mins = int(elapsed_seconds // 60)
        escalate_msg = (
            f"🚨 <b>[NOC AGIVA - {severity} ALERT (≥ 10 MENIT)]</b> 🚨\n\n"
            f"📌 <b>Alert ID:</b> #{alert_id}\n"
            f"📌 <b>Perangkat:</b> {device.name} ({device.ip_address})\n"
            f"📌 <b>Vendor / Site:</b> {device.vendor} ({device.site})\n"
            f"📌 <b>Tipe Anomali:</b> {alert_type}\n"
            f"📌 <b>Detail Masalah:</b> {message}\n"
            f"📌 <b>Durasi Gangguan:</b> Telah berlangsung {dur_mins} menit (sejak {active_incident.started_at.strftime('%H:%M:%S')} WIB)\n"
            f"📌 <b>Status:</b> ESKALASI KE ACTIVE ALERT (Memerlukan Tindakan)\n\n"
            f"💡 <i>Ketik /ack {alert_id} di Telegram Bot untuk konfirmasi penanganan tiket operasional.</i>"
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
        IncidentLog.status.in_(['ACTIVE_MONITORING', 'ESCALATED_TO_ALERT'])
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
        dur_str = f"{h} jam {m} menit {s} detik"
    elif m > 0:
        dur_str = f"{m} menit {s} detik"
    else:
        dur_str = f"{s} detik"

    is_cooldown = active_incident and (active_incident.status == 'ACTIVE_MONITORING') and (dur_sec < 600)

    # =========================================================================
    # KASUS A: Pulih dalam < 10 Menit (AUTO-COOLDOWN)
    # =========================================================================
    if is_cooldown:
        active_incident.resolved_at = now
        active_incident.duration_seconds = dur_sec
        active_incident.status = 'AUTO_COOLDOWN'

        cooldown_msg = (
            f"⚡ <b>[NOC AGIVA - ANOMALI PULIH / COOLDOWN]</b> ⚡\n\n"
            f"📌 <b>Perangkat:</b> {device.name} ({device.ip_address})\n"
            f"📌 <b>Vendor / Site:</b> {device.vendor} ({device.site})\n"
            f"📌 <b>Tipe Kejadian:</b> {alert_type}\n"
            f"📌 <b>Metrik Puncak:</b> {active_incident.peak_metric or '-'}\n"
            f"📌 <b>Durasi Anomali:</b> {dur_str} (Pulih &lt; 10 Menit)\n"
            f"📌 <b>Waktu Pulih:</b> {now.strftime('%Y-%m-%d %H:%M:%S')} WIB\n"
            f"📌 <b>Status:</b> Auto-Cooldown (Dicatat ke Incident Log #{active_incident.incident_id})\n\n"
            f"💡 <i>Lonjakan sesaat telah mereda secara normal tanpa eskalasi tiket.</i>"
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

        logger.info(f"[RuleEngine] Insiden #{active_incident.incident_id} ({device.name} - {alert_type}) pulih dalam {dur_str} -> AUTO_COOLDOWN.")
        return True, active_incident

    # =========================================================================
    # KASUS B: Anomali Telah Dieskalasi ke Alert (>= 10 Menit) - OPSI 2 (MANUAL RESOLVE ONLY)
    # =========================================================================
    # Sesuai SOP Opsi 2: Sistem TIDAK MENUTUP alert secara otomatis meskipun metrik sudah kembali normal.
    # Alert TETAP TERBUKA di antrean Active & Sustained Alerts sampai petugas secara manual
    # mengetik /resolve <alert_id> di Telegram sebagai verifikasi penyelesaian tiket.
    alert_ref = f"#{active_alert.alert_id}" if active_alert else (f"#INC-{active_incident.incident_id}" if active_incident else "-")
    logger.info(
        f"[RuleEngine] Metrik {device.name} - {alert_type} telah normal kembali, "
        f"tetapi Alert {alert_ref} tetap OPEN di antrean Active Alerts menunggu /resolve manual petugas via Telegram."
    )
    return False, None


def evaluate_device_rules(session, device, metrics):

    if device.status == "DOWN":
        trigger_alert_with_antispam(
            session=session,
            device=device,
            alert_type="HOST_DOWN",
            severity="CRITICAL",
            message=f"Perangkat {device.name} ({device.ip_address}) tidak merespons polling ICMP/SSH/API.",
            peak_metric_val="DOWN (Unreachable)"
        )
    else:
        auto_resolve_alert(
            session=session,
            device=device,
            alert_type="HOST_DOWN",
            recovery_message=f"Koneksi ke {device.name} ({device.ip_address}) berhasil dipulihkan (STATUS: UP)."
        )

    cpu_val = float(device.cpu_usage or 0.0)
    if cpu_val > 90.0:
        severity = "CRITICAL" if cpu_val >= 95.0 else "WARNING"
        trigger_alert_with_antispam(
            session=session,
            device=device,
            alert_type="CPU_OVERLOAD",
            severity=severity,
            message=f"Penggunaan CPU melonjak mencapai {cpu_val:.1f}% (Ambang batas: 90%).",
            peak_metric_val=f"{cpu_val:.1f}%"
        )
    elif cpu_val <= 80.0:
        # Auto-resolve jika CPU sudah kembali di bawah 80%
        auto_resolve_alert(
            session=session,
            device=device,
            alert_type="CPU_OVERLOAD",
            recovery_message=f"Beban CPU {device.name} telah kembali normal ({cpu_val:.1f}%)."
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
            message=f"Penggunaan Memory melonjak mencapai {mem_val:.1f}% (Ambang batas: 90%).",
            peak_metric_val=f"{mem_val:.1f}%"
        )
    elif mem_val <= 80.0:
        # Auto-resolve jika Memory sudah kembali di bawah 80%
        auto_resolve_alert(
            session=session,
            device=device,
            alert_type="MEMORY_OVERLOAD",
            recovery_message=f"Penggunaan Memory {device.name} telah kembali normal ({mem_val:.1f}%)."
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
                message=f"Latency respons ICMP ke {device.name} melonjak mencapai {lat_val:.1f} ms (Batas normal: 5 ms).",
                peak_metric_val=f"{lat_val:.1f} ms"
            )
        elif lat_val <= 5.0:
            auto_resolve_alert(
                session=session,
                device=device,
                alert_type="HIGH_LATENCY",
                recovery_message=f"Latency {device.name} telah kembali normal ({lat_val:.1f} ms)."
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
                message=f"Terdeteksi ping drop / packet loss sebesar {loss_val:.1f}% ke {device.name} (Batas normal: 5%).",
                peak_metric_val=f"{loss_val:.1f}%"
            )
        elif loss_val <= 0.0:
            auto_resolve_alert(
                session=session,
                device=device,
                alert_type="PACKET_LOSS",
                recovery_message=f"Koneksi ke {device.name} stabil tanpa packet loss (0.0%)."
            )
