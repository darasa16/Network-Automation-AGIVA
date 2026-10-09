
import os
from datetime import datetime, timedelta
import random
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from dotenv import load_dotenv

load_dotenv()

import socket
import subprocess
import time
from urllib.parse import urlparse

DATABASE_URL = os.getenv(
    'DATABASE_URL',
    'postgresql://postgres:password@localhost:5432/agiva_noc_db'
)

def is_db_alive(db_url=DATABASE_URL, timeout=0.5):
    """Cek cepat apakah port PostgreSQL (5432) sedang aktif."""
    try:
        parsed = urlparse(db_url)
        host = parsed.hostname or '127.0.0.1'
        if host == 'localhost':
            host = '127.0.0.1'
        port = parsed.port or 5432
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False

def ensure_postgres_running():
    """Otomatis menyalakan server PostgreSQL portable jika sedang mati."""
    if is_db_alive(DATABASE_URL):
        return

    # Lokasi instalasi PostgreSQL portable
    pg_ctl_candidates = [
        r"C:\Users\LENOVO FLEX 7\pgsql\bin\pg_ctl.exe",
        r"C:\Program Files\PostgreSQL\16\bin\pg_ctl.exe",
        r"C:\pgsql\bin\pg_ctl.exe"
    ]
    pg_data_candidates = [
        r"C:\Users\LENOVO FLEX 7\pgsql\data",
        r"C:\Program Files\PostgreSQL\16\data",
        r"C:\pgsql\data"
    ]
    
    pg_ctl = next((p for p in pg_ctl_candidates if os.path.exists(p)), None)
    pg_data = next((d for d in pg_data_candidates if os.path.exists(d)), None)
    pg_log = r"C:\Users\LENOVO FLEX 7\pgsql\server.log"

    if pg_ctl and pg_data:
        print("[*] Server PostgreSQL sedang offline. Menyalakan server otomatis...")
        flags = subprocess.DETACHED_PROCESS if os.name == 'nt' else 0
        try:
            subprocess.Popen(
                [pg_ctl, "start", "-D", pg_data, "-l", pg_log, "-w"],
                creationflags=flags
            )
            # Tunggu server aktif
            for _ in range(12):
                time.sleep(0.5)
                if is_db_alive(DATABASE_URL):
                    print("[*] Server PostgreSQL berhasil dinyalakan dan siap melayani koneksi!")
                    return
        except Exception as err:
            print(f"[!] Gagal auto-start PostgreSQL: {err}")

def get_engine():
    """Menginisialisasi engine PostgreSQL murni sesuai spesifikasi LLD."""
    db_url = os.getenv('DATABASE_URL', DATABASE_URL)
    
    # Pastikan server PostgreSQL sudah aktif sebelum mencoba koneksi
    if db_url.startswith('postgresql'):
        ensure_postgres_running()

    engine = create_engine(
        db_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10
    )

    # Coba koneksi dengan toleransi saat server baru booting
    max_retries = 8
    for attempt in range(max_retries):
        try:
            with engine.connect() as conn:
                print("[*] Terhubung ke Database PostgreSQL (agiva_noc_db) dengan sukses.")
                return engine
        except Exception as e:
            err_str = str(e).lower()
            if ("starting up" in err_str or "connection timeout" in err_str) and attempt < max_retries - 1:
                time.sleep(1.0)
                continue
            if attempt == max_retries - 1:
                print(f"\n[FATAL ERROR] Gagal menghubungkan ke database PostgreSQL di {db_url}: {e}")
                raise e
            time.sleep(0.5)
    return engine

engine = get_engine()
db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))

def init_db():
    """Create all tables and seed realistic sample data if empty in PostgreSQL."""
    from models import Base, Device, DeviceStatusLog, Alert, TelegramWhitelist, TelegramMessageLog, BackupHistory
    Base.metadata.create_all(bind=engine)
    
    # Check if database needs seeding
    session = db_session()
    try:
        # Tetap izinkan seeding untuk akun Telegram Whitelist agar bot tetap punya admin
        whitelist_count = session.query(TelegramWhitelist).count()
        if whitelist_count == 0:
            print("[*] Seeding Telegram Whitelist (Admin/NOC Security Access)...")
            seed_whitelist_only(session)
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()

def seed_demo_data(session):
    from models import Device, DeviceStatusLog, Alert, TelegramWhitelist, TelegramMessageLog, BackupHistory

    # 1. Seed Network Devices (MikroTik RouterOS & Cisco IOS)
    devices_data = [
        {"name": "Router-Core-01", "ip": "192.168.1.1", "vendor": "MikroTik", "site": "Data Center HQ", "status": "UP", "cpu": 34.5, "mem": 48.2, "trf": 145.2, "uptime": "42 days, 14 hours"},
        {"name": "Switch-Dist-01", "ip": "192.168.1.2", "vendor": "Cisco", "site": "Data Center HQ", "status": "UP", "cpu": 22.0, "mem": 39.1, "trf": 88.4, "uptime": "89 days, 06 hours"},
        {"name": "Router-Edge-01", "ip": "192.168.1.3", "vendor": "MikroTik", "site": "Gateway IDC", "status": "UP", "cpu": 58.7, "mem": 64.3, "trf": 210.8, "uptime": "15 days, 02 hours"},
        {"name": "Router-Branch-Sby", "ip": "10.10.20.1", "vendor": "MikroTik", "site": "Surabaya Branch", "status": "UP", "cpu": 18.2, "mem": 31.0, "trf": 45.6, "uptime": "4 days, 11 hours"},
        {"name": "Switch-Access-Bdg", "ip": "10.20.30.2", "vendor": "Cisco", "site": "Bandung Site", "status": "DOWN", "cpu": 0.0, "mem": 0.0, "trf": 0.0, "uptime": "Offline"},
        {"name": "Router-Backup-01", "ip": "192.168.1.254", "vendor": "Cisco", "site": "Data Center HQ", "status": "UP", "cpu": 12.4, "mem": 28.5, "trf": 12.1, "uptime": "120 days, 18 hours"},
        {"name": "Firewall-Ext-01", "ip": "192.168.100.1", "vendor": "Cisco", "site": "DMZ Gateway", "status": "DOWN", "cpu": 0.0, "mem": 0.0, "trf": 0.0, "uptime": "Offline"},
        {"name": "Router-Distribution-02", "ip": "10.10.10.1", "vendor": "MikroTik", "site": "Medan Branch", "status": "UP", "cpu": 41.2, "mem": 52.8, "trf": 64.0, "uptime": "28 days, 09 hours"}
    ]

    dev_objects = []
    for d in devices_data:
        dev = Device(
            name=d["name"],
            ip_address=d["ip"],
            vendor=d["vendor"],
            site=d["site"],
            status=d["status"],
            cpu_usage=d["cpu"],
            mem_usage=d["mem"],
            traffic_mbps=d["trf"],
            uptime=d["uptime"]
        )
        session.add(dev)
        dev_objects.append(dev)
    
    session.flush()

    # 2. Seed 12-hour historical logs for charts
    now = datetime.now()
    for dev in dev_objects:
        if dev.status == 'UP':
            for i in range(12, 0, -1):
                t = now - timedelta(hours=i)
                log = DeviceStatusLog(
                    device_id=dev.device_id,
                    timestamp=t,
                    status='UP',
                    cpu_usage=round(max(5.0, min(95.0, dev.cpu_usage + random.uniform(-15.0, 15.0))), 1),
                    mem_usage=round(max(10.0, min(90.0, dev.mem_usage + random.uniform(-6.0, 6.0))), 1),
                    traffic_mbps=round(max(10.0, min(350.0, dev.traffic_mbps + random.uniform(-30.0, 30.0))), 1)
                )
                session.add(log)

    # 3. Seed Alerts (Matching LLD Rule Engine triggers)
    alerts_data = [
        {
            "device_id": dev_objects[2].device_id, # Router-Edge-01
            "type": "CPU_THRESHOLD_EXCEEDED",
            "severity": "WARNING",
            "message": "High CPU utilization detected (> 85%) on Core CPU 0.",
            "time_offset": 12,
            "ack": False,
            "ack_by": None
        },
        {
            "device_id": dev_objects[4].device_id, # Switch-Access-Bdg
            "type": "HOST_UNREACHABLE",
            "severity": "CRITICAL",
            "message": "Device unreachable after 2 consecutive polling attempts (ICMP/SSH Timeout).",
            "time_offset": 25,
            "ack": False,
            "ack_by": None
        },
        {
            "device_id": dev_objects[6].device_id, # Firewall-Ext-01
            "type": "INTERFACE_DOWN",
            "severity": "CRITICAL",
            "message": "Interface GigabitEthernet0/1 changed state to administratively down.",
            "time_offset": 55,
            "ack": True,
            "ack_by": "@agiva_noc_lead via Telegram"
        }
    ]

    alert_objects = []
    for a in alerts_data:
        alt = Alert(
            device_id=a["device_id"],
            type=a["type"],
            severity=a["severity"],
            message=a["message"],
            triggered_at=now - timedelta(minutes=a["time_offset"]),
            acknowledged=a["ack"],
            acknowledged_by=a["ack_by"]
        )
        session.add(alt)
        alert_objects.append(alt)
    
    session.flush()

    # 4. Seed Telegram Whitelist (NOC Engineers & Groups)
    whitelist_data = [
        {"chat_id": "-1004429503436", "username": "@Agiva_Network_Automation_Bot", "name": "Agiva Network Automation Channel", "role": "Broadcast Group"},
        {"chat_id": "5419251159", "username": "@darasamsara", "name": "Dara Samsara", "role": "Admin"}
    ]
    for w in whitelist_data:
        entry = TelegramWhitelist(
            chat_id=w["chat_id"],
            telegram_username=w["username"],
            engineer_name=w["name"],
            role=w["role"],
            is_active=True
        )
        session.add(entry)

    # 5. Seed Telegram Message Logs
    target_channel_id = os.getenv("NOC_TELEGRAM_CHAT_ID", "-1004429503436")
    lead_chat_id = os.getenv("TELEGRAM_CHAT_ID", "5419251159")
    telegram_logs = [
        {
            "alert_id": alert_objects[0].alert_id,
            "chat_id": target_channel_id,
            "type": "ALERT_NOTIFICATION",
            "content": f"[WARNING] #{alert_objects[0].alert_id}: High CPU utilization on Router-Edge-01 (192.168.1.3). Type /ack {alert_objects[0].alert_id} to confirm.",
            "status": "SENT",
            "offset": 12
        },
        {
            "alert_id": alert_objects[1].alert_id,
            "chat_id": target_channel_id,
            "type": "ALERT_NOTIFICATION",
            "content": f"[CRITICAL] #{alert_objects[1].alert_id}: Host Switch-Access-Bdg (10.20.30.2) UNREACHABLE. Type /ack {alert_objects[1].alert_id} to confirm.",
            "status": "SENT",
            "offset": 25
        },
        {
            "alert_id": None,
            "chat_id": lead_chat_id,
            "type": "COMMAND_REPLY",
            "content": "Status Ringkasan: Total 8 Devices (6 Online, 2 Offline). Active Alerts: 2 pending.",
            "status": "SENT",
            "offset": 5
        },
        {
            "alert_id": alert_objects[2].alert_id,
            "chat_id": lead_chat_id,
            "type": "COMMAND_REPLY",
            "content": f"Alert #{alert_objects[2].alert_id} berhasil di-acknowledge oleh @darasamsara (Lead Engineer).",
            "status": "SENT",
            "offset": 45
        }
    ]
    for tl in telegram_logs:
        log_entry = TelegramMessageLog(
            alert_id=tl["alert_id"],
            chat_id=tl["chat_id"],
            message_type=tl["type"],
            content=tl["content"],
            status=tl["status"],
            sent_at=now - timedelta(minutes=tl["offset"])
        )
        session.add(log_entry)

    # 6. Seed Backup History
    backups_data = [
        {"device_id": dev_objects[0].device_id, "path": "/backups/HQ/Router-Core-01/2026-09-28_config.txt", "size": "45.2 KB", "status": "SUCCESS"},
        {"device_id": dev_objects[1].device_id, "path": "/backups/HQ/Switch-Dist-01/2026-09-28_config.txt", "size": "128.6 KB", "status": "SUCCESS"},
        {"device_id": dev_objects[2].device_id, "path": "/backups/Gateway/Router-Edge-01/2026-09-28_config.txt", "size": "56.8 KB", "status": "SUCCESS"},
        {"device_id": dev_objects[4].device_id, "path": "-", "size": "0 KB", "status": "FAILED"}
    ]
    for b in backups_data:
        bh = BackupHistory(
            device_id=b["device_id"],
            file_path=b["path"],
            file_size=b["size"],
            status=b["status"],
            timestamp=now - timedelta(hours=8)
        )
        session.add(bh)

    session.commit()
    print("[*] Database seeded successfully with realistic NOC data.")

def seed_whitelist_only(session):
    import os
    from models import TelegramWhitelist
    
    target_channel_id = os.getenv("NOC_TELEGRAM_CHAT_ID", "-1004429503436")
    lead_chat_id = os.getenv("TELEGRAM_CHAT_ID", "5419251159")
    
    whitelist_data = [
        {"chat_id": target_channel_id, "username": "@Agiva_Network_Automation_Bot", "name": "Agiva Network Automation Channel", "role": "Broadcast Group"},
        {"chat_id": lead_chat_id, "username": "@darasamsara", "name": "Dara Samsara", "role": "Admin"}
    ]
    for w in whitelist_data:
        entry = TelegramWhitelist(
            chat_id=w["chat_id"],
            telegram_username=w["username"],
            engineer_name=w["name"],
            role=w["role"],
            is_active=True
        )
        session.add(entry)
    
    session.commit()
    print("[*] Whitelist seeded successfully.")
