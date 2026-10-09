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
    traffic_mbps = Column(Float, default=0.0)
    uptime = Column(String(100), default='Unknown')
    credential_ref = Column(String(100), default='env_vault')
    last_polled = Column(DateTime, default=datetime.now)

    # Relationships
    logs = relationship("DeviceStatusLog", back_populates="device", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="device", cascade="all, delete-orphan")
    backups = relationship("BackupHistory", back_populates="device", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.device_id,
            "name": self.name,
            "ip": self.ip_address,
            "vendor": self.vendor,
            "site": self.site,
            "status": self.status,
            "cpu": round(self.cpu_usage, 1),
            "mem": round(self.mem_usage, 1),
            "traffic": round(self.traffic_mbps, 1),
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
    traffic_mbps = Column(Float, default=0.0)

    device = relationship("Device", back_populates="logs")

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
            "triggered_at": self.triggered_at.strftime("%H:%M:%S WIB") if self.triggered_at else "-",
            "acknowledged": self.acknowledged,
            "acknowledged_by": self.acknowledged_by,
            "resolved_at": self.resolved_at.strftime("%Y-%m-%d %H:%M") if self.resolved_at else None
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
    status = Column(String(20), default='SENT')       # 'SENT', 'FAILED', 'PENDING'
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
            "sent_at": self.sent_at.strftime("%H:%M:%S WIB")
        }

# 4. BACKUP HISTORY MODEL
class BackupHistory(Base):
    """Tabel: backup_history (Log Hasil Backup Konfigurasi)"""
    __tablename__ = 'backup_history'

    backup_id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(Integer, ForeignKey('devices.device_id', ondelete='CASCADE'), nullable=False)
    timestamp = Column(DateTime, default=datetime.now, nullable=False)
    file_path = Column(Text, nullable=False)
    file_size = Column(String(50), default="45.2 KB")
    status = Column(String(20), nullable=False)  # 'SUCCESS' / 'FAILED'

    device = relationship("Device", back_populates="backups")
