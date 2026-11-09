
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
    if db_url.startswith('postgresql://'):
        db_url = db_url.replace('postgresql://', 'postgresql+psycopg2://', 1)
    
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
    from models import Base, Device, DeviceStatusLog, WanStatusLog, Alert, IncidentLog, TelegramWhitelist, TelegramMessageLog, BackupHistory
    Base.metadata.create_all(bind=engine)
    
    # Auto-migration: pastikan kolom latency_ms dan packet_loss ada di PostgreSQL
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE devices ADD COLUMN IF NOT EXISTS latency_ms FLOAT DEFAULT 0.0;"))
            conn.execute(text("ALTER TABLE devices ADD COLUMN IF NOT EXISTS packet_loss FLOAT DEFAULT 0.0;"))
            conn.execute(text("ALTER TABLE device_status_logs ADD COLUMN IF NOT EXISTS latency_ms FLOAT DEFAULT 0.0;"))
            conn.execute(text("ALTER TABLE device_status_logs ADD COLUMN IF NOT EXISTS packet_loss FLOAT DEFAULT 0.0;"))
            conn.execute(text("ALTER TABLE backup_history ADD COLUMN IF NOT EXISTS category VARCHAR(50) DEFAULT 'System';"))
            conn.execute(text("ALTER TABLE backup_history ADD COLUMN IF NOT EXISTS trigger_by VARCHAR(100) DEFAULT 'Scheduler (02:00 WIB)';"))
            conn.execute(text("ALTER TABLE backup_history ADD COLUMN IF NOT EXISTS data_range VARCHAR(100) DEFAULT 'Snapshot';"))
            conn.execute(text("UPDATE backup_history SET data_range = TO_CHAR(COALESCE(timestamp, NOW()) - INTERVAL '1 day', 'DD/MM HH24:MI:SS') || ' — ' || TO_CHAR(COALESCE(timestamp, NOW()), 'DD/MM HH24:MI:SS') || ' WIB' WHERE data_range IS NULL OR data_range = '24 Jam Terakhir' OR data_range LIKE 'Snapshot%' OR data_range NOT LIKE '%:%';"))
            conn.commit()
    except Exception as e:
        print(f"[!] Migration check warning: {e}")

    # Check if database needs seeding
    session = db_session()
    try:
        # Seeding Telegram Whitelist
        whitelist_count = session.query(TelegramWhitelist).count()
        if whitelist_count == 0:
            print("[*] Seeding Telegram Whitelist (Admin/NOC Security Access)...")
            seed_whitelist_only(session)

        # Seeding WAN Biznet History if empty
        seed_wan_history_if_needed(session)

    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()

def seed_wan_history_if_needed(session):
    from models import WanStatusLog
    try:
        count = session.query(WanStatusLog).count()
        if count == 0:
            print("[*] Menginisialisasi histori data metrik WAN Biznet ethernet1/3 (24 jam terakhir)...")
            now = datetime.now()
            entries = []
            for i in range(720, -1, -1):
                ts = now - timedelta(minutes=i * 2)
                hour = ts.hour
                is_busy = 9 <= hour <= 17
                base_dl = 46.0 if is_busy else 22.0
                base_ul = 15.0 if is_busy else 8.0
                dl = round(max(5.0, min(92.0, base_dl + random.uniform(-14.0, 20.0))), 1)
                ul = round(max(2.0, min(38.0, base_ul + random.uniform(-5.0, 8.0))), 1)
                lat = round(random.uniform(7.5, 14.0), 1)
                gw_lat = round(random.uniform(0.7, 1.3), 1)
                loss = 0.0
                if is_busy and random.random() < 0.04:
                    lat = round(random.uniform(22.0, 38.0), 1)

                entry = WanStatusLog(
                    timestamp=ts,
                    interface_name='ethernet1/3',
                    provider='Biznet',
                    status='UP',
                    download_mbps=dl,
                    upload_mbps=ul,
                    total_mbps=round(dl + ul, 1),
                    latency_ms=lat,
                    gateway_latency_ms=gw_lat,
                    packet_loss=loss,
                    rx_errors=0,
                    tx_errors=0
                )
                entries.append(entry)

            session.bulk_save_objects(entries)
            session.commit()
            print(f"[*] Berhasil menambahkan {len(entries)} data histori awal WAN Biznet.")
    except Exception as e:
        session.rollback()
        print(f"[!] Gagal inisialisasi WAN history: {e}")


def seed_demo_data(session):
    import yaml
    from models import Device, DeviceStatusLog, Alert, TelegramWhitelist, TelegramMessageLog, BackupHistory

    # 1. Sync Network Devices from devices.yaml
    yaml_path = os.path.join(os.path.dirname(__file__), 'devices.yaml')
    dev_objects = []
    if os.path.exists(yaml_path):
        with open(yaml_path, 'r') as file:
            data = yaml.safe_load(file)
            if data and 'devices' in data:
                for d_info in data['devices']:
                    existing = session.query(Device).filter_by(ip_address=d_info.get('ip_address')).first()
                    if not existing:
                        new_dev = Device(
                            name=d_info.get('name'),
                            ip_address=d_info.get('ip_address'),
                            vendor=d_info.get('vendor'),
                            site=d_info.get('site', 'HO'),
                            credential_ref=d_info.get('credential_ref', 'env_vault'),
                            status='UP',
                            cpu_usage=12.0,
                            mem_usage=45.0,
                            latency_ms=2.5,
                            packet_loss=0.0,
                            uptime='30 hari, 12 jam'
                        )
                        session.add(new_dev)
                        dev_objects.append(new_dev)
                    else:
                        dev_objects.append(existing)
        session.commit()

    # 2. Seed Telegram Whitelist
    seed_whitelist_only(session)
    print("[*] Database synchronized successfully with production network devices.")

def seed_whitelist_only(session):
    import os
    from models import TelegramWhitelist
    
    target_channel_id = os.getenv("NOC_TELEGRAM_CHAT_ID", "-1004429503436")
    lead_chat_id = os.getenv("TELEGRAM_CHAT_ID", "5419251159")
    
    whitelist_data = [
        {"chat_id": target_channel_id, "username": "@Agiva_Network_Automation_Bot", "name": "Agiva Network Automation Channel", "role": "Broadcast Group"},
        {"chat_id": lead_chat_id, "username": "@darasamsara", "name": "Dara Samsara", "role": "Admin"},
        {"chat_id": "1849201941", "username": "@budi_noc", "name": "Budi Santoso", "role": "Lead NOC Engineer"},
        {"chat_id": "1849201942", "username": "@andi_net", "name": "Andi Pratama", "role": "Senior Network Engineer"},
        {"chat_id": "1849201943", "username": "@citra_sec", "name": "Citra Lestari", "role": "Cybersecurity Analyst"},
        {"chat_id": "1849201944", "username": "@reza_ops", "name": "Reza Kurniawan", "role": "Network Operations"},
        {"chat_id": "1849201945", "username": "@dewi_infra", "name": "Dewi Anggraini", "role": "Infrastructure Engineer"},
        {"chat_id": "1849201946", "username": "@fajar_sys", "name": "Fajar Hidayat", "role": "Systems Engineer"},
        {"chat_id": "1849201947", "username": "@maya_netops", "name": "Maya Putri", "role": "NOC Technician"},
        {"chat_id": "1849201948", "username": "@eko_cloud", "name": "Eko Prasetyo", "role": "Cloud Network Specialist"},
        {"chat_id": "1849201949", "username": "@rina_mon", "name": "Rina Marlina", "role": "Monitoring Specialist"},
        {"chat_id": "1849201950", "username": "@gilang_core", "name": "Gilang Ramadhan", "role": "Core IP Engineer"}
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
