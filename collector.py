import time
import os
import re
import logging
import yaml
from datetime import datetime
from dotenv import load_dotenv

from apscheduler.schedulers.background import BackgroundScheduler
from netmiko import ConnectHandler
import routeros_api

# Import database dan rule engine dari aplikasi
from database import db_session
from models import Device, DeviceStatusLog
from app import trigger_alert_with_antispam

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("DataCollector")

load_dotenv()

# ==========================================
# 1. load_inventory()
# ==========================================
def load_inventory():
    """
    Sesuai LLD: baca daftar perangkat dari devices.yaml (atau DB).
    Melakukan sinkronisasi awal dari devices.yaml ke database jika ada perangkat baru.
    """
    session = db_session()
    
    # 1. Sync dari devices.yaml
    yaml_path = os.path.join(os.path.dirname(__file__), 'devices.yaml')
    if os.path.exists(yaml_path):
        try:
            with open(yaml_path, 'r') as file:
                data = yaml.safe_load(file)
                if data and 'devices' in data:
                    for d_info in data['devices']:
                        # Cek apakah device sudah ada di DB berdasarkan IP
                        existing = session.query(Device).filter_by(ip_address=d_info.get('ip_address')).first()
                        if not existing:
                            logger.info(f"Syncing perangkat baru dari YAML: {d_info.get('name')} ({d_info.get('ip_address')})")
                            new_dev = Device(
                                name=d_info.get('name'),
                                ip_address=d_info.get('ip_address'),
                                vendor=d_info.get('vendor'),
                                site=d_info.get('site', 'Unknown'),
                                credential_ref=d_info.get('credential_ref', 'env_vault')
                            )
                            session.add(new_dev)
            session.commit()
        except Exception as e:
            logger.error(f"Gagal memproses devices.yaml: {e}")
            session.rollback()

    # 2. Ambil dari DB sebagai single source of truth
    devices = session.query(Device).all()
    session.close()
    return devices

# ==========================================
# 2. poll_device(device)
# ==========================================
def poll_device(device):
    """
    Sesuai LLD: cek reachability lalu ambil metrik (status interface, CPU, memory, uptime)
    via RouterOS-API (MikroTik) atau SSH via Netmiko (Cisco).
    """
    # Ambil referensi kredensial dari .env (simulasi credential_ref)
    username = os.getenv("ROUTER_USER", "admin")
    password = os.getenv("ROUTER_PASS", "agiva123")
    
    metrics = {
        "status": "DOWN",
        "cpu": 0.0,
        "mem": 0.0,
        "traffic": 0.0,
        "uptime": "Unknown"
    }
    
    try:
        if device.vendor.lower() == 'cisco':
            # KONEKSI NETMIKO (CISCO)
            cisco_device = {
                'device_type': 'cisco_ios',
                'host': device.ip_address,
                'username': username,
                'password': password,
                'timeout': 10
            }
            with ConnectHandler(**cisco_device) as net_connect:
                metrics["status"] = "UP"
                
                # Parsing Uptime
                ver_output = net_connect.send_command('show version')
                uptime_match = re.search(r'uptime is (.*?)\n', ver_output)
                if uptime_match:
                    metrics["uptime"] = uptime_match.group(1).strip()
                
                # Parsing CPU
                cpu_output = net_connect.send_command('show processes cpu')
                cpu_match = re.search(r'CPU utilization for five seconds: (\d+)%', cpu_output)
                if cpu_match:
                    metrics["cpu"] = float(cpu_match.group(1))
                    
                # Parsing Memory
                mem_output = net_connect.send_command('show memory statistics')
                # Logika parsing memori cisco berbeda tiap seri, ini contoh umum:
                mem_match = re.search(r'Processor Memory.*?Total:\s+(\d+)\s+Used:\s+(\d+)', mem_output)
                if mem_match:
                    total_mem = float(mem_match.group(1))
                    used_mem = float(mem_match.group(2))
                    metrics["mem"] = (used_mem / total_mem) * 100 if total_mem > 0 else 0.0
                    
                # Traffic (contoh parse sederhana untuk antarmuka utama)
                metrics["traffic"] = 0.0 # Butuh parsing lebih detail dari show interfaces

        elif device.vendor.lower() == 'mikrotik':
            # KONEKSI ROUTEROS-API (MIKROTIK)
            connection = routeros_api.RouterOsApiPool(
                device.ip_address,
                username=username,
                password=password,
                plaintext_login=True
            )
            api = connection.get_api()
            metrics["status"] = "UP"
            
            # Parsing Metrik (Resource)
            resource = api.get_resource('/system/resource').get()[0]
            metrics["cpu"] = float(resource.get('cpu-load', 0))
            metrics["uptime"] = resource.get('uptime', 'Unknown')
            
            total_mem = float(resource.get('total-memory', 1))
            free_mem = float(resource.get('free-memory', 1))
            metrics["mem"] = ((total_mem - free_mem) / total_mem) * 100
            
            # Traffic (Ambil dari ether1 sebagai contoh)
            monitor = api.get_resource('/interface').call('monitor-traffic', {'interface': 'ether1', 'once': ''})
            if monitor:
                rx_bps = float(monitor[0].get('rx-bits-per-second', 0))
                tx_bps = float(monitor[0].get('tx-bits-per-second', 0))
                # Konversi bps ke Mbps
                metrics["traffic"] = round((rx_bps + tx_bps) / 1000000, 2)
                
            connection.disconnect()
            
    except Exception as e:
        logger.error(f"Gagal koneksi ke {device.name} ({device.ip_address}): {e}")
        metrics["status"] = "DOWN"
        
    return metrics

# ==========================================
# 3. save_metrics(device_id, metrics)
# ==========================================
def save_metrics(device_id, metrics):
    """
    Sesuai LLD: simpan ke data store (update status di device dan catat histori).
    Juga memicu Rule Engine untuk mengecek threshold.
    """
    session = db_session()
    device = session.query(Device).filter(Device.device_id == device_id).first()
    if not device:
        session.close()
        return

    # Update perangkat
    device.status = metrics["status"]
    device.cpu_usage = metrics["cpu"]
    device.mem_usage = metrics["mem"]
    device.traffic_mbps = metrics["traffic"]
    device.uptime = metrics["uptime"]
    device.last_polled = datetime.now()

    # Log histori metrik
    log_entry = DeviceStatusLog(
        device_id=device.device_id,
        status=metrics["status"],
        cpu_usage=metrics["cpu"],
        mem_usage=metrics["mem"],
        traffic_mbps=metrics["traffic"],
        timestamp=datetime.now()
    )
    session.add(log_entry)
    
    # Eksekusi Rule Engine & Anti-spam
    if device.status == "DOWN":
        trigger_alert_with_antispam(session, device, "HOST_DOWN", "CRITICAL", f"Perangkat {device.name} tidak dapat dijangkau via SSH/API.")
    elif device.cpu_usage > 85.0:
        trigger_alert_with_antispam(session, device, "CPU_OVERLOAD", "WARNING", f"Penggunaan CPU mencapai {device.cpu_usage:.1f}%")
    elif device.mem_usage > 85.0:
        trigger_alert_with_antispam(session, device, "MEMORY_OVERLOAD", "WARNING", f"Penggunaan Memory mencapai {device.mem_usage:.1f}%")
        
    session.commit()
    session.close()

# ==========================================
# 4. run_polling_cycle()
# ==========================================
def run_polling_cycle():
    """
    Sesuai LLD: loop semua device, dipanggil scheduler.
    """
    logger.info("=== START POLLING CYCLE ===")
    devices = load_inventory()
    
    for device in devices:
        logger.info(f"Polling {device.name} ({device.vendor})...")
        metrics = poll_device(device)
        save_metrics(device.device_id, metrics)
        
    logger.info("=== END POLLING CYCLE ===")

def start_scheduler():
    scheduler = BackgroundScheduler()
    # LLD: dijadwalkan tiap 1-5 menit. Kita set 2 menit sebagai default
    scheduler.add_job(run_polling_cycle, 'interval', minutes=2)
    scheduler.start()
    
    logger.info("Scheduler berjalan. Menunggu jadwal polling...")
    try:
        while True:
            time.sleep(2)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logger.info("Data Collector dihentikan.")

if __name__ == "__main__":
    start_scheduler()
