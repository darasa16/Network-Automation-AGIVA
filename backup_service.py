"""
AGIVA NOC - Network Backup & Log Archiving Service
Mendukung pencadangan multi-vendor:
- Palo Alto PA-220 (System, Config, Traffic, Threat)
- Aruba 2930F (System, Config, Traffic, Threat)
- Huawei S5735 (System, Config, Traffic, Threat)

Format Penyimpanan:
/backups/{site}/{device_name}/{YYYY-MM-DD_HHmmss}_{category.lower()}.txt
Mendukung Initial Pull & Point-in-Time Audit Trail Logging (Opsi 2).
"""

import os
import re
import json
import time
import requests
import paramiko
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from netmiko import ConnectHandler

from logger_config import get_configured_logger
from database import db_session
from models import Device, BackupHistory

logger = get_configured_logger("BackupService")

BACKUP_BASE_DIR = os.path.join(os.getcwd(), "backups")
CHECKPOINT_FILE = os.path.join(BACKUP_BASE_DIR, ".checkpoint.json")

def get_now_wib():
    try:
        return datetime.now(ZoneInfo("Asia/Jakarta"))
    except Exception:
        return datetime.now()

def load_checkpoints() -> dict:
    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Gagal membaca checkpoint file: {e}")
    return {}

def save_checkpoint(device_name: str, category: str, checkpoint_val: str):
    checkpoints = load_checkpoints()
    key = f"{device_name}_{category}"
    checkpoints[key] = checkpoint_val
    try:
        os.makedirs(BACKUP_BASE_DIR, exist_ok=True)
        with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
            json.dump(checkpoints, f, indent=2)
    except Exception as e:
        logger.error(f"Gagal menyimpan checkpoint: {e}")

def get_device_credentials(device_name: str, ip_address: str):
    """Mengambil username dan password vault yang sesuai untuk tiap perangkat."""
    default_user = os.getenv("ROUTER_USER", "admin")
    default_pass = os.getenv("ROUTER_PASS", "AgivaP@ssw0rd")

    dev_lower = device_name.lower()
    if "corner" in dev_lower or "155" in ip_address:
        user = os.getenv("CORNER_USER", "Administrator")
        pwd = os.getenv("CORNER_PASS", "P@ssw0rd")
    elif "ho" in dev_lower or "10" in ip_address:
        user = os.getenv("HO_USER", default_user)
        pwd = os.getenv("HO_PASS", default_pass)
    elif "pa" in dev_lower or "11" in ip_address:
        user = os.getenv("PA_USER", "arifin")
        pwd = os.getenv("PA_PASS", "P@ssw0rd2025")
    else:
        user = default_user
        pwd = default_pass
    return user, pwd

def normalize_site_name(site: str) -> str:
    """Membersihkan nama site agar aman dipakai sebagai path direktori."""
    if not site:
        return "Default_Site"
    clean = re.sub(r'[^a-zA-Z0-9_\-]', '_', site.strip())
    return re.sub(r'_+', '_', clean).strip('_')

def format_file_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{round(size_bytes / 1024.0, 1)} KB"
    else:
        return f"{round(size_bytes / (1024.0 * 1024.0), 2)} MB"

# ==================== VENDOR BACKUP EXECUTORS ====================

def fetch_aruba_log_or_config(ip: str, user: str, pwd: str, category: str, *args, **kwargs) -> str:
    """Ekstraksi raw snapshot log/config Aruba 2930F via SSH Netmiko/Paramiko (Anti-Paging / no page)."""
    cat_lower = (category or "").lower()
    if cat_lower == "system":
        cmd = "show log"
    elif cat_lower == "config":
        cmd = "show running-config"
    elif cat_lower == "traffic":
        cmd = "show interfaces"
    elif cat_lower == "threat":
        cmd = "show port-security"
    else:
        cmd = "show running-config"
    
    # Kandidat user: prioritas user yang diset, lalu 'manager' (default Aruba/HP), lalu 'admin'
    user_candidates = []
    for u in [user, "manager", "admin"]:
        if u and u not in user_candidates:
            user_candidates.append(u)

    # Kandidat password: password dari env, password kosong, dan variasi umum
    pw_candidates = []
    for p in [pwd, "", "admin", "admin123", "P@ssw0rd"]:
        if p is not None and p not in pw_candidates:
            pw_candidates.append(p)
    
    last_err = None
    for cand_u in user_candidates:
        for cand_pw in pw_candidates:
            # 1. Coba via Netmiko dengan paging disabled ('no page') dan regex fleksibel r"#"
            try:
                device_params = {
                    'device_type': 'aruba_osswitch',
                    'host': ip,
                    'username': cand_u,
                    'password': cand_pw,
                    'timeout': 10,
                    'fast_cli': False
                }
                with ConnectHandler(**device_params) as net_connect:
                    # Nonaktifkan paging agar log panjang tidak berhenti di '-- MORE --'
                    try:
                        net_connect.send_command("no page", expect_string=r"#", read_timeout=5)
                    except Exception:
                        pass

                    output = net_connect.send_command(cmd, expect_string=r"#", read_timeout=45)
                    if output and len(output.strip()) > 10:
                        logger.info(f"Koneksi SSH Aruba (Netmiko) berhasil dengan user='{cand_u}'")
                        return output
            except Exception as e_nm:
                last_err = e_nm

            # 2. Fallback via Paramiko Shell murni (paling handal untuk output sangat panjang)
            try:
                client = paramiko.SSHClient()
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                client.connect(ip, port=22, username=cand_u, password=cand_pw, timeout=10)
                
                shell = client.invoke_shell()
                time.sleep(0.5)
                # Kirim Enter & no page untuk mematikan pagination
                shell.send("\nno page\n")
                time.sleep(0.6)
                if shell.recv_ready():
                    shell.recv(65535)

                shell.send(f"{cmd}\n")
                time.sleep(1.5)
                
                output = ""
                idle_count = 0
                while idle_count < 8:
                    if shell.recv_ready():
                        chunk = shell.recv(65535).decode('utf-8', errors='ignore')
                        output += chunk
                        idle_count = 0
                        time.sleep(0.3)
                    else:
                        idle_count += 1
                        time.sleep(0.4)

                client.close()
                if output and len(output.strip()) > 15:
                    logger.info(f"Koneksi SSH Aruba (Paramiko Shell) berhasil dengan user='{cand_u}'")
                    return output
            except Exception as e_pm:
                last_err = e_pm
                continue

    raise Exception(f"Aruba SSH connection failed: {last_err}")

def fetch_huawei_log_or_config(ip: str, user: str, pwd: str, category: str, *args, **kwargs) -> str:
    """Ekstraksi raw snapshot log/config Huawei CloudEngine S5735 via Paramiko/Netmiko."""
    cat_lower = (category or "").lower()
    if cat_lower == "system":
        cmd = "display logbuffer"
    elif cat_lower == "config":
        cmd = "display current-configuration"
    elif cat_lower == "traffic":
        cmd = "display interface counters"
    elif cat_lower == "threat":
        cmd = "display port-security"
    else:
        cmd = "display current-configuration"
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(ip, port=22, username=user, password=pwd, timeout=8)
        
        # Jalankan command dengan paging disabled agar tidak terpotong
        shell = client.invoke_shell()
        time.sleep(0.4)
        shell.send("screen-length 0 temporary\n")
        time.sleep(0.3)
        shell.send(f"{cmd}\n")
        time.sleep(1.2)
        
        output = ""
        while shell.recv_ready():
            chunk = shell.recv(65535).decode('utf-8', errors='ignore')
            output += chunk
            time.sleep(0.2)
        client.close()
        
        if output.strip():
            # Bersihkan banner login VTY, echo command, dan prompt terminal Huawei
            cmd_pattern = re.compile(rf'<[^>]+>\s*{re.escape(cmd)}', re.IGNORECASE)
            match = cmd_pattern.search(output)
            if match:
                output = output[match.end():]
            else:
                cmd_idx = output.find(cmd)
                if cmd_idx != -1:
                    nl_idx = output.find("\n", cmd_idx)
                    if nl_idx != -1:
                        output = output[nl_idx + 1:]

            lines = output.splitlines()
            while lines and not lines[0].strip():
                lines.pop(0)
            while lines and (re.match(r'^\s*<[^>]+>\s*$', lines[-1]) or re.match(r'^\s*\[[^\]]+\]\s*$', lines[-1]) or not lines[-1].strip()):
                lines.pop()

            clean_res = "\n".join(lines).strip()
            return clean_res if clean_res else output
        raise Exception("Empty output from Huawei switch")
    except Exception as e:
        raise Exception(f"Huawei SSH connection failed: {e}")

def fetch_palo_alto_log_or_config(ip: str, user: str, pwd: str, category: str, *args, **kwargs) -> str:
    """
    Ekstraksi raw snapshot log/config Palo Alto PA-220 via PAN-OS XML API / SSH.
    Mendukung kategori: System, Config, Traffic, Threat.
    """
    api_key = os.getenv("PA_API_KEY", "LUFRPT1mOVAwR1h3bzFrTFNnQjI4WkF3L0h5UVg5Z3c9VDZ2TVVXS2ZmODdwUVRkbDdvcGdJSW1WUkJWVnFCWWdUWWhZV3J4SnhoWFdLalNySkpoRmI0enhVWkdNZjBBdw==")
    cat_lower = category.lower()

    if cat_lower == "config":
        # Ambil running configuration lengkap
        try:
            r = requests.get(f"https://{ip}/api/?type=config&action=show&key={api_key}", verify=False, timeout=12)
            if r.status_code == 200 and r.text.strip():
                return r.text
        except Exception:
            pass

    # Kategori log: system, config, traffic, threat (500 log terbaru saat ini)
    try:
        url = f"https://{ip}/api/?type=log&log-type={cat_lower}&key={api_key}&nlogs=500"
        r = requests.get(url, verify=False, timeout=15)
        if r.status_code == 200 and r.text:
            # Jika PAN-OS mengembalikan asynchronous query job (<job>123</job>)
            job_match = re.search(r'<job>(\d+)</job>', r.text)
            if job_match:
                job_id = job_match.group(1)
                for _ in range(5):
                    time.sleep(1)
                    poll_url = f"https://{ip}/api/?type=log&action=get&job-id={job_id}&key={api_key}"
                    pr = requests.get(poll_url, verify=False, timeout=15)
                    if pr.status_code == 200 and pr.text:
                        if "<status>FIN</status>" in pr.text or "<logs" in pr.text:
                            return pr.text
                if pr and pr.text and ("<status>FIN</status>" in pr.text or "<logs" in pr.text):
                    return pr.text
            return r.text
    except Exception as e:
        logger.warning(f"PAN-OS XML API gagal, mencoba fallback SSH: {e}")

    # Fallback SSH jika API tidak merespons
    try:
        device_params = {
            'device_type': 'paloalto_panos',
            'host': ip,
            'username': user,
            'password': pwd,
            'timeout': 15
        }
        with ConnectHandler(**device_params) as net_connect:
            net_connect.send_command("set cli pager off")
            cmd = f"show log {cat_lower} direction equal backward"
            output = net_connect.send_command(cmd)
            return output
    except Exception as e:
        raise Exception(f"Palo Alto connection failed (API & SSH): {e}")

# ==================== MAIN BACKUP CONTROLLER ====================

def run_single_backup(device: Device, category: str, trigger_by: str = "Scheduler (02:00 WIB)", session=None) -> dict:
    """
    Mengeksekusi pencadangan 1 perangkat untuk 1 kategori spesifik (Raw Snapshot Murni).
    Setiap eksekusi mengambil output mentah CLI/API saat itu juga dan menghasilkan berkas mandiri.
    """
    now = get_now_wib()
    time_str = now.strftime("%Y-%m-%d_%H%M%S")

    site_clean = normalize_site_name(device.site or "HO")
    dev_name = device.name
    vendor_clean = device.vendor.lower() if device.vendor else ""
    ip = device.ip_address

    # Direktori tujuan: /backups/{site}/{device_name}/
    target_dir = os.path.join(BACKUP_BASE_DIR, site_clean, dev_name)
    os.makedirs(target_dir, exist_ok=True)

    # Nama file unik berbasis timestamp detik: {YYYY-MM-DD_HHmmss}_{category.lower()}.txt
    file_name = f"{time_str}_{category.lower()}.txt"
    abs_file_path = os.path.join(target_dir, file_name)
    rel_file_path = f"/backups/{site_clean}/{dev_name}/{file_name}".replace("\\", "/")

    user, pwd = get_device_credentials(dev_name, ip)
    status = "SUCCESS"
    error_msg = None
    content = ""

    try:
        logger.info(f"Memulai raw snapshot [{category}] untuk {dev_name} ({ip}) [Pemicu: {trigger_by}]...")
        
        if "palo" in vendor_clean or "pan" in vendor_clean or "11" in ip:
            content = fetch_palo_alto_log_or_config(ip, user, pwd, category)
        elif "aruba" in vendor_clean or "hp" in vendor_clean or "10" in ip:
            content = fetch_aruba_log_or_config(ip, user, pwd, category)
        elif "huawei" in vendor_clean or "155" in ip:
            content = fetch_huawei_log_or_config(ip, user, pwd, category)
        else:
            raise Exception(f"Vendor '{device.vendor}' is not supported yet.")

    except Exception as e:
        logger.error(f"Failed to fetch raw snapshot {dev_name} [{category}]: {e}")
        status = "FAILED"
        error_msg = str(e)
        content = f"// BACKUP ERROR [{now.strftime('%Y-%m-%d %H:%M:%S WIB')}]\n// Device: {dev_name} ({ip})\n// Category: {category}\n// Error: {error_msg}\n"

    # Penulisan berkas mandiri (Pure Raw Snapshot)
    header_info = (
        f"{'='*70}\n"
        f"AGIVA NOC RAW SNAPSHOT [{category.upper()}]\n"
        f"Execution Time: {now.strftime('%Y-%m-%d %H:%M:%S WIB')}\n"
        f"Device        : {dev_name} ({ip})\n"
        f"Site          : {device.site or '-'}\n"
        f"Category      : {category}\n"
        f"Triggered By  : {trigger_by}\n"
        f"{'='*70}\n\n"
    )
    write_data = header_info + content

    try:
        with open(abs_file_path, "w", encoding="utf-8") as f:
            f.write(write_data)
        file_size_bytes = os.path.getsize(abs_file_path)
        file_size_str = format_file_size(file_size_bytes)
    except Exception as e:
        logger.error(f"Gagal menulis berkas backup ke disk: {e}")
        file_size_str = "0 B"
        status = "FAILED"

    # Rentang data: Snapshot waktu eksekusi saat itu
    data_range = f"Snapshot: {now.strftime('%d/%m/%Y %H:%M:%S WIB')}"

    # Catat riwayat ke Database sebagai baris baru (Audit Trail Murni)
    close_session_at_end = False
    if session is None:
        session = db_session()
        close_session_at_end = True

    try:
        bh = BackupHistory(
            device_id=device.device_id,
            category=category,
            timestamp=now,
            file_path=rel_file_path,
            file_size=file_size_str,
            trigger_by=trigger_by,
            data_range=data_range,
            status=status
        )
        session.add(bh)
        session.commit()
        history_id = bh.backup_id
    except Exception as e:
        logger.error(f"Gagal mencatat backup ke database: {e}")
        session.rollback()
        history_id = None
    finally:
        if close_session_at_end:
            session.close()

    return {
        "id": history_id,
        "device": dev_name,
        "category": category,
        "file": file_name,
        "path": rel_file_path,
        "size": file_size_str,
        "trigger_by": trigger_by,
        "data_range": data_range,
        "status": status,
        "error": error_msg,
        "is_incremental": False
    }

def get_categories_for_device(vendor: str = "") -> list:
    """
    Mengembalikan 4 kategori arsip & audit lengkap untuk seluruh perangkat jaringan:
    - SYSTEM: Event Log / Logbuffer
    - CONFIG: Running / Current Configuration
    - TRAFFIC: Statistik throughput & counter transmisi port interface
    - THREAT: Log keamanan port, violation, loop & attack protection
    """
    return ["System", "Config", "Traffic", "Threat"]

def run_device_backup(device_name_query: str, category_filter: str = None, trigger_by: str = "Manual Trigger") -> dict:
    """
    Mengeksekusi pencadangan untuk sebuah perangkat spesifik.
    Mendukung filter kategori spesifik ('System', 'Config', 'Traffic', 'Threat') atau 'all'.
    """
    session = db_session()
    try:
        dev = session.query(Device).filter(Device.name.ilike(f"%{device_name_query.strip()}%")).first()
        if not dev:
            # Fallback cari berdasarkan IP
            dev = session.query(Device).filter(Device.ip_address == device_name_query.strip()).first()
        if not dev:
            return {
                "success": False,
                "error": f"Device '{device_name_query}' not found in inventory database."
            }

        avail_categories = get_categories_for_device(dev.vendor)
        if category_filter and category_filter.lower() not in ["all", "semua"]:
            cat_match = [c for c in avail_categories if c.lower() == category_filter.lower().strip()]
            categories = cat_match if cat_match else avail_categories
        else:
            categories = avail_categories

        results = []
        for cat in categories:
            res = run_single_backup(dev, cat, trigger_by=trigger_by, session=session)
            results.append(res)

        return {
            "success": True,
            "device": dev.name,
            "ip": dev.ip_address,
            "site": dev.site,
            "vendor": dev.vendor,
            "trigger_by": trigger_by,
            "results": results
        }
    finally:
        session.close()

def run_all_devices_backup() -> list:
    """
    Mengeksekusi pencadangan otomatis untuk SELURUH perangkat aktif.
    Dipanggil secara berkala oleh APScheduler setiap pukul 02:00 WIB.
    """
    logger.info("=== [APScheduler] Memulai Siklus Pencadangan Harian Otomatis (02:00 WIB) ===")
    session = db_session()
    total_results = []
    try:
        devices = session.query(Device).all()
        for dev in devices:
            categories = get_categories_for_device(dev.vendor)
            for cat in categories:
                try:
                    res = run_single_backup(dev, cat, trigger_by="Scheduler (02:00 WIB)", session=session)
                    total_results.append(res)
                except Exception as e:
                    logger.error(f"Siklus backup gagal untuk {dev.name} [{cat}]: {e}")
        logger.info(f"=== Siklus Pencadangan Harian Selesai. Total dieksekusi: {len(total_results)} berkas ===")
        return total_results
    finally:
        session.close()

def get_backup_content(backup_id: int) -> dict:
    """Mengambil isi teks berkas backup untuk ditampilkan pada modal viewer."""
    session = db_session()
    try:
        b = session.query(BackupHistory).filter(BackupHistory.backup_id == backup_id).first()
        if not b:
            return {"success": False, "error": "Backup data not found."}

        # Convert /backups/... relative path to absolute local filesystem path
        clean_path = b.file_path.strip("/\\")
        parts = clean_path.split("/")
        if parts and parts[0] == "backups":
            parts = parts[1:]
        
        abs_path = os.path.join(BACKUP_BASE_DIR, *parts)
        dev_name = b.device.name if b.device else "Unknown"
        site_clean = normalize_site_name(b.device.site if b.device else "")
        category = getattr(b, "category", "System")

        if not os.path.exists(abs_path):
            # Cek apakah ada berkas arsip yang sudah tersimpan di direktori perangkat
            dev_dir = os.path.join(BACKUP_BASE_DIR, site_clean, dev_name)
            if os.path.exists(dev_dir):
                files = [f for f in os.listdir(dev_dir) if f.endswith(".txt")]
                if files:
                    cat_lower = category.lower()
                    matched = [f for f in files if cat_lower in f.lower()]
                    target_file = matched[-1] if matched else files[-1]
                    fallback_abs = os.path.join(dev_dir, target_file)
                    with open(fallback_abs, "r", encoding="utf-8", errors="ignore") as f:
                        fallback_content = f.read()
                    return {
                        "success": True,
                        "backup_id": b.backup_id,
                        "device": dev_name,
                        "category": category,
                        "file_path": f"/backups/{site_clean}/{dev_name}/{target_file}".replace("\\", "/"),
                        "file_size": format_file_size(os.path.getsize(fallback_abs)),
                        "date": b.timestamp.strftime("%Y-%m-%d %H:%M:%S WIB"),
                        "content": f"// [Note: Archive file dated {b.timestamp.strftime('%Y-%m-%d')} not found on local disk]\n// [Displaying available archive file: {target_file}]\n\n" + fallback_content
                    }

            return {
                "success": False,
                "error": f"Physical file not yet stored on server disk ({abs_path}).",
                "file_path": b.file_path,
                "device": dev_name,
                "category": category
            }

        with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        return {
            "success": True,
            "backup_id": b.backup_id,
            "device": dev_name,
            "category": category,
            "file_path": b.file_path,
            "file_size": b.file_size,
            "date": b.timestamp.strftime("%Y-%m-%d %H:%M:%S WIB"),
            "content": content
        }
    finally:
        session.close()

def cleanup_old_backup_history(retention_days: int = None) -> dict:
    """
    Data Retention Policy (Housekeeping) untuk Riwayat Backup & Log Audit:
    - Menghapus riwayat backup & log audit (System, Config, Traffic, Threat) yang berumur > retention_days (default 30 hari).
    - Menghapus record di tabel public.backup_history dan berkas fisik .txt di disk server.
    - SAFETY NET (Disaster Recovery): Menjaga minimal 1 salinan backup 'Config' terakhir untuk masing-masing
      perangkat jaringan agar selalu tersedia konfigurasi cadangan untuk pemulihan darurat jika perangkat mati/rusak.
    """
    if retention_days is None:
        retention_days = int(os.getenv("BACKUP_RETENTION_DAYS", "30"))

    session = db_session()
    cutoff_date = datetime.now() - timedelta(days=retention_days)

    deleted_db_count = 0
    deleted_files_count = 0
    skipped_safety_net = 0

    try:
        # 1. Cari riwayat backup yang tanggalnya lebih lama dari cutoff_date
        old_backups = session.query(BackupHistory).filter(BackupHistory.timestamp < cutoff_date).all()
        if not old_backups:
            logger.info(f"[Housekeeping] Retensi data backup bersih. Tidak ada data backup/log audit yang berumur > {retention_days} hari.")
            return {"deleted_db": 0, "deleted_files": 0, "skipped_safety_net": 0}

        # 2. Identifikasi backup 'Config' terbaru untuk tiap perangkat (Safety Net Disaster Recovery)
        device_ids_with_old_config = {
            b.device_id for b in old_backups if (b.category or "").strip().lower() == "config"
        }
        latest_config_backup_ids = set()
        for dev_id in device_ids_with_old_config:
            latest_cfg = (
                session.query(BackupHistory.backup_id)
                .filter(
                    BackupHistory.device_id == dev_id,
                    BackupHistory.category.ilike("config")
                )
                .order_by(BackupHistory.timestamp.desc(), BackupHistory.backup_id.desc())
                .first()
            )
            if latest_cfg:
                latest_config_backup_ids.add(latest_cfg[0])

        # 3. Iterasi dan proses pembersihan data & berkas fisik
        for b in old_backups:
            cat_lower = (b.category or "").strip().lower()

            # Pengecekan Safety Net: Lindungi salinan konfigurasi terakhir per perangkat
            if cat_lower == "config" and b.backup_id in latest_config_backup_ids:
                dev_name = b.device.name if b.device else f"Device #{b.device_id}"
                logger.info(
                    f"[Housekeeping] Safety Net Aktif: Melewati penghapusan backup Config ID {b.backup_id} ({dev_name}) "
                    f"karena merupakan salinan konfigurasi terakhir untuk Disaster Recovery."
                )
                skipped_safety_net += 1
                continue

            # Hapus berkas fisik .txt di disk lokal server jika ada
            if b.file_path:
                clean_path = b.file_path.replace("\\", "/").strip("/")
                parts = clean_path.split("/")
                if parts and parts[0] == "backups":
                    parts = parts[1:]
                abs_path = os.path.join(BACKUP_BASE_DIR, *parts)

                if os.path.isfile(abs_path):
                    try:
                        os.remove(abs_path)
                        deleted_files_count += 1
                    except Exception as e_del:
                        logger.warning(f"[Housekeeping] Gagal menghapus berkas fisik {abs_path}: {e_del}")

            session.delete(b)
            deleted_db_count += 1

        session.commit()
        logger.info(
            f"[Housekeeping] Retensi Backup & Log Audit berhasil dieksekusi: "
            f"{deleted_db_count} record database & {deleted_files_count} berkas fisik dihapus (> {retention_days} hari). "
            f"{skipped_safety_net} konfigurasi dilindungi Safety Net."
        )
    except Exception as e:
        logger.error(f"[Housekeeping] Gagal menjalankan retensi backup & log audit: {e}")
        session.rollback()
    finally:
        session.close()

    return {
        "deleted_db": deleted_db_count,
        "deleted_files": deleted_files_count,
        "skipped_safety_net": skipped_safety_net
    }


