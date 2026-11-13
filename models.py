from datetime import datetime
from sqlalchemy import Column, Integer, BigInteger, String, Text, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

# 1. MONITORING MODELS
class Device(Base):
    """Tabel: devices (Inventaris Perangkat Jaringan & Status Terkini)"""
    __tablename__ = 'devices'

    device_id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    ip_address = Column(String(45), nullable=False, unique=True)
    vendor = Column(String(50), nullable=False)  # 'MikroTik' / 'Cisco'
    site = Column(String(100), nullable=False)
    status = Column(String(20), default='UP')   # 'UP' / 'DOWN'
    cpu_usage = Column(Float, default=0.0)
    mem_usage = Column(Float, default=0.0)
    latency_ms = Column(Float, default=0.0)
    packet_loss = Column(Float, default=0.0)
    uptime = Column(String(100), default='Unknown')
    credential_ref = Column(String(100), default='env_vault')
    last_polled = Column(DateTime, default=datetime.now)

    # Relationships
    logs = relationship("DeviceStatusLog", back_populates="device", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="device", cascade="all, delete-orphan")
    incidents = relationship("IncidentLog", back_populates="device", cascade="all, delete-orphan")
    backups = relationship("BackupHistory", back_populates="device", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.device_id,
            "name": self.name,
            "ip": self.ip_address,
            "vendor": self.vendor,
            "site": self.site,
            "status": self.status,
            "cpu": round(self.cpu_usage or 0.0, 1),
            "mem": round(self.mem_usage or 0.0, 1),
            "latency": round(self.latency_ms or 0.0, 1),
            "packet_loss": round(self.packet_loss or 0.0, 1),
            "uptime": self.uptime,
            "last_polled": self.last_polled.strftime("%H:%M:%S") if self.last_polled else "-"
        }


class DeviceStatusLog(Base):
    """Tabel: device_status_logs (Histori Metrik Polling Berkala untuk Chart.js)"""
    __tablename__ = 'device_status_logs'

    log_id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    device_id = Column(Integer, ForeignKey('devices.device_id', ondelete='CASCADE'), nullable=False)
    timestamp = Column(DateTime, default=datetime.now, nullable=False)
    status = Column(String(20), nullable=False)  # 'UP' / 'DOWN'
    cpu_usage = Column(Float, default=0.0)
    mem_usage = Column(Float, default=0.0)
    latency_ms = Column(Float, default=0.0)
    packet_loss = Column(Float, default=0.0)
    traffic_mbps = Column(Float, default=0.0)
    ingress_mbps = Column(Float, default=0.0)
    egress_mbps = Column(Float, default=0.0)
    packet_buffers = Column(Float, default=0.0)
    message_buffers = Column(Float, default=0.0)
    tx_errors = Column(Integer, default=0)
    rx_errors = Column(Integer, default=0)
    tx_drops = Column(Integer, default=0)

    device = relationship("Device", back_populates="logs")

class WanStatusLog(Base):
    """Tabel: wan_status_logs (Histori Metrik WAN / ISP Biznet ethernet1/3 untuk Chart.js & Card)"""
    __tablename__ = 'wan_status_logs'

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.now, nullable=False)
    interface_name = Column(String(50), default='ethernet1/3', nullable=False)
    provider = Column(String(50), default='Biznet', nullable=False)
    status = Column(String(20), default='UP', nullable=False)  # 'UP' / 'DOWN'
    download_mbps = Column(Float, default=0.0)
    upload_mbps = Column(Float, default=0.0)
    total_mbps = Column(Float, default=0.0)
    latency_ms = Column(Float, default=0.0)          # Ping ke Internet (1.1.1.1)
    gateway_latency_ms = Column(Float, default=0.0)  # Ping ke Gateway Modem (192.168.18.1)
    packet_loss = Column(Float, default=0.0)
    rx_errors = Column(Integer, default=0)
    tx_errors = Column(Integer, default=0)

    def to_dict(self):
        return {
            "id": self.id,
            "timestamp": self.timestamp.strftime("%Y-%m-%d %H:%M:%S") if self.timestamp else "-",
            "time_str": self.timestamp.strftime("%H:%M:%S") if self.timestamp else "-",
            "interface": self.interface_name,
            "provider": self.provider,
            "status": self.status,
            "download": round(self.download_mbps or 0.0, 1),
            "upload": round(self.upload_mbps or 0.0, 1),
            "total": round(self.total_mbps or 0.0, 1),
            "latency": round(self.latency_ms or 0.0, 1),
            "gateway_latency": round(self.gateway_latency_ms or 0.0, 1),
            "packet_loss": round(self.packet_loss or 0.0, 1),
            "rx_errors": self.rx_errors or 0,
            "tx_errors": self.tx_errors or 0,
            "total_errors": (self.rx_errors or 0) + (self.tx_errors or 0)
        }


# 2. ALERT MODELS
class Alert(Base):
    """Tabel: alerts (Log Kejadian Anomali / Trigger Rule Engine)"""
    __tablename__ = 'alerts'

    alert_id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(Integer, ForeignKey('devices.device_id', ondelete='CASCADE'), nullable=False)
    type = Column(String(50), nullable=False)       # 'CPU_OVERLOAD', 'HOST_DOWN', 'INTERFACE_DOWN'
    severity = Column(String(20), default='WARNING') # 'CRITICAL' / 'WARNING'
    message = Column(Text, nullable=False)
    triggered_at = Column(DateTime, default=datetime.now, nullable=False)
    acknowledged = Column(Boolean, default=False)
    acknowledged_by = Column(String(100), nullable=True) # e.g. '@noc_engineer via Telegram' or 'Web Admin'
    resolved_at = Column(DateTime, nullable=True)

    device = relationship("Device", back_populates="alerts")
    telegram_logs = relationship("TelegramMessageLog", back_populates="alert")

    def to_dict(self):
        return {
            "id": self.alert_id,
            "device_id": self.device_id,
            "device_name": self.device.name if self.device else "Unknown Device",
            "ip": self.device.ip_address if self.device else "-",
            "type": self.type,
            "severity": self.severity,
            "message": self.message,
            "triggered_at": self.triggered_at.strftime("%Y-%m-%d %H:%M:%S") if self.triggered_at else "-",
            "acknowledged": self.acknowledged,
            "acknowledged_by": self.acknowledged_by,
            "resolved_at": self.resolved_at.strftime("%Y-%m-%d %H:%M:%S") if self.resolved_at else None
        }

class IncidentLog(Base):
    """Tabel: incident_logs (Riwayat Anomali, Cooldown <10m, dan Audit Insiden)"""
    __tablename__ = 'incident_logs'

    incident_id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(Integer, ForeignKey('devices.device_id', ondelete='CASCADE'), nullable=False)
    type = Column(String(50), nullable=False)        # 'CPU_OVERLOAD', 'MEMORY_OVERLOAD', 'HOST_DOWN'
    severity = Column(String(20), default='WARNING') # 'CRITICAL' / 'WARNING'
    peak_metric = Column(String(50), nullable=True)  # misal '92.4%' atau 'DOWN (Timeout)'
    started_at = Column(DateTime, default=datetime.now, nullable=False)
    resolved_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Integer, default=0)
    status = Column(String(30), default='ACTIVE_MONITORING') # 'ACTIVE_MONITORING', 'AUTO_COOLDOWN', 'ACTIVE_ALERT', 'RESOLVED_ALERT'

    device = relationship("Device", back_populates="incidents")

    def to_dict(self):
        duration_str = "-"
        if self.duration_seconds and self.duration_seconds > 0:
            m, s = divmod(self.duration_seconds, 60)
            h, m = divmod(m, 60)
            if h > 0:
                duration_str = f"{h}h {m}m {s}s"
            elif m > 0:
                duration_str = f"{m}m {s}s"
            else:
                duration_str = f"{s}s"

        return {
            "id": self.incident_id,
            "device_id": self.device_id,
            "device_name": self.device.name if self.device else "Unknown Device",
            "ip": self.device.ip_address if self.device else "-",
            "type": self.type,
            "severity": self.severity,
            "peak_metric": self.peak_metric or "-",
            "started_at": self.started_at.strftime("%Y-%m-%d %H:%M:%S") if self.started_at else "-",
            "resolved_at": self.resolved_at.strftime("%Y-%m-%d %H:%M:%S") if self.resolved_at else "-",
            "duration": duration_str,
            "duration_seconds": self.duration_seconds or 0,
            "status": self.status
        }

# 3. TELEGRAM BOT MODELS
class TelegramWhitelist(Base):
    """Tabel: telegram_whitelist (Daftar Pengguna / Tim NOC yang Diizinkan Mengakses Bot)"""
    __tablename__ = 'telegram_whitelist'

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(String(50), unique=True, nullable=False)
    telegram_username = Column(String(100), nullable=False)
    engineer_name = Column(String(150), nullable=False)
    role = Column(String(80), default='NOC Engineer') # 'Lead NOC', 'Senior Engineer', etc.
    is_active = Column(Boolean, default=True)
    registered_at = Column(DateTime, default=datetime.now)

    def to_dict(self):
        return {
            "id": self.id,
            "chat_id": self.chat_id,
            "username": self.telegram_username,
            "name": self.engineer_name,
            "role": self.role,
            "is_active": self.is_active,
            "registered_at": self.registered_at.strftime("%Y-%m-%d")
        }


class TelegramMessageLog(Base):
    """Tabel: telegram_message_logs (Riwayat Pengiriman Notifikasi & Command Bot Telegram)"""
    __tablename__ = 'telegram_message_logs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    alert_id = Column(Integer, ForeignKey('alerts.alert_id', ondelete='SET NULL'), nullable=True)
    chat_id = Column(String(50), nullable=False)
    message_type = Column(String(50), nullable=False) # 'ALERT_NOTIFICATION', 'COMMAND_REPLY', 'BACKUP_SUMMARY'
    content = Column(Text, nullable=False)
    status = Column(String(100), default='SENT')      # 'SENT', 'FAILED', 'PENDING'
    sent_at = Column(DateTime, default=datetime.now)

    alert = relationship("Alert", back_populates="telegram_logs")

    def to_dict(self):
        return {
            "id": self.id,
            "alert_id": self.alert_id,
            "chat_id": self.chat_id,
            "type": self.message_type,
            "content": self.content,
            "status": self.status,
            "sent_at": self.sent_at.strftime("%Y-%m-%d %H:%M:%S") if self.sent_at else "-"
        }

# 4. BACKUP HISTORY MODEL
class BackupHistory(Base):
    """Tabel: backup_history (Log Hasil Backup Konfigurasi)"""
    __tablename__ = 'backup_history'

    backup_id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(Integer, ForeignKey('devices.device_id', ondelete='CASCADE'), nullable=False)
    timestamp = Column(DateTime, default=datetime.now, nullable=False)
    category = Column(String(50), default="System", nullable=False)
    file_path = Column(Text, nullable=False)
    file_size = Column(String(50), default="0 B")
    trigger_by = Column(String(100), default="Scheduler (02:00 WIB)", nullable=False)
    data_range = Column(String(100), default="Snapshot", nullable=False)
    status = Column(String(20), nullable=False)  # 'SUCCESS' / 'FAILED'

    device = relationship("Device", back_populates="backups")


# 5. AP CLIENT TELEMETRY MODEL (Opsi 1 - Database Persistence)
class ApClientTelemetry(Base):
    """Tabel: ap_client_telemetry (Data Klien Nirkabel & Bandwidth Palo Alto per AP di PostgreSQL)"""
    __tablename__ = 'ap_client_telemetry'

    id = Column(Integer, primary_key=True, autoincrement=True)
    ap_name = Column(String(64), nullable=False, index=True)
    client_ip = Column(String(45), nullable=False, index=True)
    client_mac = Column(String(32), nullable=False, index=True)
    hostname = Column(String(128), default="Station")
    vendor = Column(String(64), default="Unknown")
    os_label = Column(String(128), default="Station Device")
    os_type = Column(String(32), default="generic")
    connected_port = Column(String(64), default="PoE Port")
    connected_switch = Column(String(64), default="Switch")
    rx_mbps = Column(Float, default=0.0)
    tx_mbps = Column(Float, default=0.0)
    total_mbps = Column(Float, default=0.0)
    throughput_rx = Column(String(32), default="0 Kbps")
    throughput_tx = Column(String(32), default="0 Kbps")
    cumulative_bytes = Column(BigInteger().with_variant(Integer, "sqlite"), default=0)
    cumulative_fmt = Column(String(32), default="< 1 MB")
    top_app = Column(String(64), default="Idle")
    sessions = Column(Integer, default=0)
    status = Column(String(32), default="Active")
    last_seen = Column(DateTime, default=datetime.now, nullable=False)

    def to_dict(self):
        return {
            "id": self.id,
            "ap_name": self.ap_name,
            "hostname": self.hostname,
            "ip": self.client_ip,
            "mac": self.client_mac,
            "vendor": self.vendor,
            "os": self.os_label,
            "os_type": self.os_type,
            "port": self.connected_port,
            "switch": self.connected_switch,
            "rx_mbps": self.rx_mbps or 0.0,
            "tx_mbps": self.tx_mbps or 0.0,
            "total_mbps": self.total_mbps or 0.0,
            "throughput_rx": self.throughput_rx or "0 Kbps",
            "throughput_tx": self.throughput_tx or "0 Kbps",
            "throughput_fmt": f"Rx: {self.throughput_rx or '0 Kbps'} • Tx: {self.throughput_tx or '0 Kbps'}",
            "cumulative_bytes": self.cumulative_bytes or 0,
            "cumulative_usage": self.cumulative_fmt or "< 1 MB",
            "top_app": self.top_app or "Idle",
            "sessions": self.sessions or 0,
            "status": self.status or "Active",
            "last_seen": self.last_seen.strftime("%Y-%m-%d %H:%M:%S") if self.last_seen else "-"
        }
