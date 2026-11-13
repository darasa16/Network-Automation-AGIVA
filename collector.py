import socket
import struct
import random
from typing import Dict, Any, Optional, Tuple, List
import time
import os
import json
import re
import logging
import yaml
import subprocess
import platform
from datetime import datetime, timedelta
from dotenv import load_dotenv

from apscheduler.schedulers.background import BackgroundScheduler

# Import database dan rule engine mandiri (Komponen 4 LLD)
from database import db_session
from models import Device, DeviceStatusLog, IncidentLog, WanStatusLog
from rule_engine import evaluate_device_rules, trigger_alert_with_antispam
from logger_config import get_configured_logger

logger = get_configured_logger("DataCollector")

load_dotenv()

POLLING_INTERVAL_MINUTES = int(os.getenv("POLLING_INTERVAL_MINUTES", "2"))
_scheduler = None

def get_next_polling_time(reference_time=None):
    """
    Mengambil waktu polling berikutnya dari scheduler APScheduler aktif,
    atau mengestimasi berdasarkan POLLING_INTERVAL_MINUTES jika scheduler belum/tidak aktif.
    """
    global _scheduler
    if reference_time is None:
        reference_time = datetime.now()
        
    if _scheduler and _scheduler.running:
        try:
            job = _scheduler.get_job('polling_job')
            if job and job.next_run_time:
                nrt = job.next_run_time
                if hasattr(nrt, 'astimezone'):
                    return nrt.astimezone().strftime("%Y-%m-%d %H:%M:%S")
                return nrt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass

    next_dt = reference_time + timedelta(minutes=POLLING_INTERVAL_MINUTES)
    return next_dt.strftime("%Y-%m-%d %H:%M:%S")


def measure_ping_metrics(host, count=3, timeout_sec=1):
    """
    Uji reachability dan metrik performa transmisi via ICMP Ping (Windows & Linux).
    Return tuple: (is_up: bool, avg_latency_ms: float, packet_loss_pct: float)
    """
    try:
        is_win = platform.system().lower() == "windows"
        timeout_ms = int(timeout_sec * 1000)
        cmd = ["ping", "-n", str(count), "-w", str(timeout_ms), str(host)] if is_win else ["ping", "-c", str(count), "-W", str(timeout_sec), str(host)]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=(count * timeout_sec) + 3)
        out = (res.stdout or "")
        
        loss_pct = 100.0
        avg_latency = 0.0

        # Regex Loss
        loss_m = re.search(r'\((\d+)%\s+loss\)', out, re.IGNORECASE) or re.search(r'(\d+)%\s+packet loss', out, re.IGNORECASE)
        if loss_m:
            loss_pct = float(loss_m.group(1))

        # Regex Latency RTT
        lat_m = re.search(r'Average\s*=\s*(\d+)ms', out, re.IGNORECASE)
        if lat_m:
            avg_latency = float(lat_m.group(1))
        else:
            lat_lin = re.search(r'=\s*[\d\.]+/([\d\.]+)/', out)
            if lat_lin:
                avg_latency = float(lat_lin.group(1))
            elif '<1ms' in out.lower() and loss_pct < 100.0:
                avg_latency = 0.0

        is_up = loss_pct < 100.0
        return is_up, avg_latency, loss_pct
    except Exception:
        return False, 0.0, 100.0


def ping_device(host, timeout_sec=2):
    """
    Uji reachability cepat via ICMP Ping (Windows & Linux).
    Return True jika respons balasan diterima langsung dari host target dengan TTL valid.
    Return False jika RTO, Destination host unreachable, atau error routing/jaringan lainnya.
    """
    is_up, _, _ = measure_ping_metrics(host, count=1, timeout_sec=timeout_sec)
    return is_up


# =========================================================================
# MESIN PROTOKOL SNMP v2c (PURE PYTHON ASN.1 BER CLIENT) - ZERO DEPENDENCY
# =========================================================================
# ==================== ASN.1 & SNMP BER CONSTANTS ====================
TAG_BOOLEAN = 0x01
TAG_INTEGER = 0x02
TAG_BITSTRING = 0x03
TAG_OCTETSTRING = 0x04
TAG_NULL = 0x05
TAG_OID = 0x06
TAG_SEQUENCE = 0x30

PDU_GET = 0xA0
PDU_GETNEXT = 0xA1
PDU_RESPONSE = 0xA2
PDU_SET = 0xA3
PDU_GETBULK = 0xA5

TAG_IPADDRESS = 0x40
TAG_COUNTER32 = 0x41
TAG_GAUGE32 = 0x42
TAG_TIMETICKS = 0x43
TAG_OPAQUE = 0x44
TAG_COUNTER64 = 0x46

TAG_NO_SUCH_OBJECT = 0x80
TAG_NO_SUCH_INSTANCE = 0x81
TAG_END_OF_MIB_VIEW = 0x82

# ==================== STANDARD & VENDOR MIB OIDS ====================
# RFC 1213 / MIB-II
OID_SYS_DESCR = "1.3.6.1.2.1.1.1.0"
OID_SYS_UPTIME = "1.3.6.1.2.1.1.3.0"
OID_SYS_CONTACT = "1.3.6.1.2.1.1.4.0"
OID_SYS_NAME = "1.3.6.1.2.1.1.5.0"
OID_SYS_LOCATION = "1.3.6.1.2.1.1.6.0"

# RFC 2863 / IF-MIB (Universal Across Aruba, Huawei, Palo Alto)
OID_IF_DESCR = "1.3.6.1.2.1.2.2.1.2"
OID_IF_ADMIN_STATUS = "1.3.6.1.2.1.2.2.1.7"      # 1=UP, 2=DOWN, 3=TESTING
OID_IF_OPER_STATUS = "1.3.6.1.2.1.2.2.1.8"       # 1=UP, 2=DOWN
OID_IF_IN_ERRORS = "1.3.6.1.2.1.2.2.1.14"
OID_IF_OUT_ERRORS = "1.3.6.1.2.1.2.2.1.20"
OID_IF_IN_DISCARDS = "1.3.6.1.2.1.2.2.1.13"
OID_IF_OUT_DISCARDS = "1.3.6.1.2.1.2.2.1.19"

# 64-Bit High Capacity (HC) Counters (No 4GB 32-bit wrap limit)
OID_IF_NAME = "1.3.6.1.2.1.31.1.1.1.1"
OID_IF_HC_IN_OCTETS = "1.3.6.1.2.1.31.1.1.1.6"   # Rx Bytes (Ingress)
OID_IF_HC_OUT_OCTETS = "1.3.6.1.2.1.31.1.1.1.10" # Tx Bytes (Egress)
OID_IF_HIGH_SPEED = "1.3.6.1.2.1.31.1.1.1.15"    # Link Speed in Mbps

# --- VENDOR SPECIFIC CPU, MEMORY & BUFFER OIDS ---
# 1. Aruba 2930F (HP-Enterprise MIB)
OID_ARUBA_CPU_UTIL = "1.3.6.1.4.1.11.2.14.11.5.1.9.6.1.0"          # hpSwitchCpuStat (1 min avg)
OID_ARUBA_MEM_TOTAL = "1.3.6.1.4.1.11.2.14.11.5.1.1.2.2.1.1.5.1"   # Total Memory (Bytes) - hpGlobalMemTotalBytes
OID_ARUBA_MEM_FREE = "1.3.6.1.4.1.11.2.14.11.5.1.1.2.2.1.1.6.1"    # Free Memory (Bytes) - hpGlobalMemFreeBytes
OID_ARUBA_MEM_ALLOC = "1.3.6.1.4.1.11.2.14.11.5.1.1.2.2.1.1.7.1"   # Allocated Memory (Bytes) - hpGlobalMemAllocBytes
OID_ARUBA_PKT_BUF_TOTAL = "1.3.6.1.4.1.11.2.14.11.5.1.1.1.1.1.1.4.1" # Total Packet Buffers
OID_ARUBA_PKT_BUF_FREE = "1.3.6.1.4.1.11.2.14.11.5.1.1.1.1.1.1.3.1"  # Free Packet Buffers
OID_ARUBA_MSG_BUF_TOTAL = "1.3.6.1.4.1.11.2.14.11.5.1.1.1.2.1.1.4.1" # Total Message Buffers
OID_ARUBA_MSG_BUF_FREE = "1.3.6.1.4.1.11.2.14.11.5.1.1.1.2.1.1.3.1"  # Free Message Buffers
OID_ARUBA_POE_PORT_POWER = "1.3.6.1.4.1.11.2.14.11.1.9.1.1.1.1.1"    # Real Port PoE Power Draw

# 2. Huawei CloudEngine S5735 (Huawei VRP / YunShan MIB & Entity-MIB)
OID_HUAWEI_CPU_UTIL = "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.5.16842753"  # hwEntityCpuUsage
OID_HUAWEI_MEM_UTIL = "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.7.16842753"  # hwEntityMemUsage (%)
OID_HUAWEI_TEMP = "1.3.6.1.4.1.2011.5.25.31.1.1.1.1.11.16842753"     # hwEntityTemperature (°C)
OID_HUAWEI_SERIAL = "1.3.6.1.2.1.47.1.1.1.1.11.16842753"              # Board Serial Number (entPhysicalSerialNum)
OID_HUAWEI_CHASSIS_SERIAL = "1.3.6.1.2.1.47.1.1.1.1.11.16777216"      # Chassis Serial Number
OID_HUAWEI_MODEL = "1.3.6.1.2.1.47.1.1.1.1.13.16842753"               # Model Name (entPhysicalModelName)
OID_HUAWEI_HW_REV = "1.3.6.1.2.1.47.1.1.1.1.8.16842753"                # Hardware Revision (entPhysicalHardwareRev)
OID_HUAWEI_RAM_TOTAL = "1.3.6.1.4.1.2011.6.3.5.1.1.2.1.1.0"           # Total Memory Bytes (hwMemoryDevSize)
OID_HUAWEI_FAN1_STATUS = "1.3.6.1.4.1.2011.5.25.31.1.1.10.1.7.1.1"    # Fan 1 Status (1=Normal)
OID_HUAWEI_FAN2_STATUS = "1.3.6.1.4.1.2011.5.25.31.1.1.10.1.7.1.2"    # Fan 2 Status (1=Normal)
OID_BRIDGE_BASE_MAC = "1.3.6.1.2.1.17.1.1.0"                          # dot1dBaseBridgeAddress (Bridge MAC)
OID_ENT_PHYSICAL_SERIAL = "1.3.6.1.2.1.47.1.1.1.1.11"                  # entPhysicalSerialNum (Base Walk)
OID_DOT1Q_VLAN_STATIC_NAME = "1.3.6.1.2.1.17.7.1.4.3.1.1"              # dot1qVlanStaticName (Q-BRIDGE-MIB)

# 3. Palo Alto PA-220 (HOST-RESOURCES-MIB & PAN-COMMON-MIB)
OID_PA_CPU_DP0 = "1.3.6.1.2.1.25.3.3.1.2.1"          # hrProcessorLoad (Data Plane DP0)
OID_PA_CPU_MP = "1.3.6.1.2.1.25.3.3.1.2.2"           # hrProcessorLoad (Management Plane MP)
OID_PA_MEM_TOTAL = "1.3.6.1.2.1.25.2.3.1.5.1020"    # hrStorageSize (Slot-1 Management Memory)
OID_PA_MEM_USED = "1.3.6.1.2.1.25.2.3.1.6.1020"     # hrStorageUsed (Slot-1 Management Memory)
OID_PA_SW_VERSION = "1.3.6.1.4.1.25461.2.1.2.1.1.0" # panSysSwVersion
OID_PA_SERIAL = "1.3.6.1.4.1.25461.2.1.2.1.3.0"     # panSysSerialNumber
OID_PA_SESSION_UTIL = "1.3.6.1.4.1.25461.2.1.2.3.1.0" # panSessionUtilization (%)
OID_PA_SESSION_MAX = "1.3.6.1.4.1.25461.2.1.2.3.2.0"  # panSessionMax (Max sessions)
OID_PA_ACTIVE_SESSIONS = "1.3.6.1.4.1.25461.2.1.2.3.3.0" # panSysActiveSessions
OID_PA_ACTIVE_TCP = "1.3.6.1.4.1.25461.2.1.2.3.4.0" # panSessionActiveTcp
OID_PA_ACTIVE_UDP = "1.3.6.1.4.1.25461.2.1.2.3.5.0" # panSessionActiveUdp
OID_ARUBA_POE_CONSUMPTION = "1.3.6.1.2.1.105.1.3.1.1.4.1" # pethMainPseConsumptionPower

# Universal 64-bit HC Packet Counters
OID_IF_HC_IN_UCAST_PKTS = "1.3.6.1.2.1.31.1.1.1.7"   # Ingress Unicast Packets (64-bit HC)
OID_IF_HC_OUT_UCAST_PKTS = "1.3.6.1.2.1.31.1.1.1.11" # Egress Unicast Packets (64-bit HC)

# Persistent in-memory traffic counter cache to calculate Mbps delta: {device_id_or_ip: (ts, in_bytes, out_bytes)}
_SNMP_PREV_COUNTERS: Dict[str, Tuple[float, int, int]] = {}
_SNMP_WAN_PREV_COUNTERS: Dict[str, Tuple[float, int, int]] = {}


# ==================== LOW-LEVEL ASN.1 BER ENGINE ====================

def encode_length(length: int) -> bytes:
    if length < 0x80:
        return bytes([length])
    len_bytes = []
    while length > 0:
        len_bytes.insert(0, length & 0xFF)
        length >>= 8
    return bytes([0x80 | len(len_bytes)] + len_bytes)


def decode_length(data: bytes, offset: int) -> Tuple[int, int]:
    first = data[offset]
    offset += 1
    if first < 0x80:
        return first, offset
    num_octets = first & 0x7F
    length = 0
    for _ in range(num_octets):
        length = (length << 8) | data[offset]
        offset += 1
    return length, offset


def encode_integer(val: int, tag=TAG_INTEGER) -> bytes:
    if val == 0:
        content = b'\x00'
    else:
        content = bytearray()
        negative = val < 0
        if negative:
            val = (1 << (val.bit_length() + 8)) + val
        while val > 0 or (negative and len(content) == 0):
            content.insert(0, val & 0xFF)
            val >>= 8
        if not negative and (content[0] & 0x80):
            content.insert(0, 0x00)
    return bytes([tag]) + encode_length(len(content)) + bytes(content)


def decode_integer(data: bytes, offset: int, length: int) -> int:
    val = 0
    negative = bool(data[offset] & 0x80)
    for i in range(length):
        val = (val << 8) | data[offset + i]
    if negative:
        val -= (1 << (length * 8))
    return val


def decode_unsigned(data: bytes, offset: int, length: int) -> int:
    val = 0
    for i in range(length):
        val = (val << 8) | data[offset + i]
    return val


def encode_oid(oid_str: str) -> bytes:
    parts = [int(p) for p in oid_str.strip('.').split('.')]
    if len(parts) < 2:
        raise ValueError("OID must have at least 2 components")
    first = 40 * parts[0] + parts[1]
    encoded = bytearray([first])
    for num in parts[2:]:
        if num == 0:
            encoded.append(0)
            continue
        octets = []
        while num > 0:
            octets.insert(0, num & 0x7F)
            num >>= 7
        for i in range(len(octets) - 1):
            octets[i] |= 0x80
        encoded.extend(octets)
    return bytes([TAG_OID]) + encode_length(len(encoded)) + bytes(encoded)


def decode_oid(data: bytes, offset: int, length: int) -> str:
    end = offset + length
    first = data[offset]
    offset += 1
    parts = [first // 40, first % 40]
    while offset < end:
        val = 0
        while True:
            b = data[offset]
            offset += 1
            val = (val << 7) | (b & 0x7F)
            if not (b & 0x80):
                break
        parts.append(val)
    return '.' + '.'.join(str(p) for p in parts)


def encode_string(val: str, tag=TAG_OCTETSTRING) -> bytes:
    b = val.encode('utf-8', errors='ignore')
    return bytes([tag]) + encode_length(len(b)) + b


def build_pdu(oids: List[str], community: str = "public", request_id: int = None, pdu_type=PDU_GET) -> Tuple[bytes, int]:
    if request_id is None:
        request_id = random.randint(100000, 999999)
    
    varbinds = bytearray()
    for oid in oids:
        oid_bytes = encode_oid(oid)
        null_val = bytes([TAG_NULL, 0x00])
        vb = bytes([TAG_SEQUENCE]) + encode_length(len(oid_bytes) + len(null_val)) + oid_bytes + null_val
        varbinds.extend(vb)
    
    varbind_list = bytes([TAG_SEQUENCE]) + encode_length(len(varbinds)) + bytes(varbinds)
    pdu_body = encode_integer(request_id) + encode_integer(0) + encode_integer(0) + varbind_list
    pdu = bytes([pdu_type]) + encode_length(len(pdu_body)) + pdu_body
    
    version_bytes = encode_integer(1)  # 1 = SNMP v2c (RFC 1905)
    comm_bytes = encode_string(community)
    
    msg_body = version_bytes + comm_bytes + pdu
    return bytes([TAG_SEQUENCE]) + encode_length(len(msg_body)) + msg_body, request_id


def parse_snmp_response(packet: bytes) -> Dict[str, Any]:
    offset = 0
    if len(packet) < 4 or packet[offset] != TAG_SEQUENCE:
        raise ValueError("Invalid SNMP packet header")
    offset += 1
    msg_len, offset = decode_length(packet, offset)
    
    # Version
    offset += 1
    v_len, offset = decode_length(packet, offset)
    version = decode_integer(packet, offset, v_len)
    offset += v_len
    
    # Community
    offset += 1
    c_len, offset = decode_length(packet, offset)
    offset += c_len
    
    # PDU
    pdu_tag = packet[offset]
    offset += 1
    pdu_len, offset = decode_length(packet, offset)
    
    # Req ID, Error Status, Error Index
    offset += 1
    req_len, offset = decode_length(packet, offset)
    offset += req_len
    
    offset += 1
    err_len, offset = decode_length(packet, offset)
    error_status = decode_integer(packet, offset, err_len)
    offset += err_len
    
    offset += 1
    idx_len, offset = decode_length(packet, offset)
    offset += idx_len
    
    # Varbind List
    offset += 1
    vb_list_len, offset = decode_length(packet, offset)
    vb_list_end = offset + vb_list_len
    
    results = {}
    while offset < vb_list_end:
        offset += 1  # TAG_SEQUENCE
        vb_len, offset = decode_length(packet, offset)
        
        # OID
        offset += 1  # TAG_OID
        oid_len, offset = decode_length(packet, offset)
        oid_str = decode_oid(packet, offset, oid_len).lstrip('.')
        offset += oid_len
        
        # Value
        val_tag = packet[offset]
        offset += 1
        val_len, offset = decode_length(packet, offset)
        
        val = None
        if val_tag == TAG_INTEGER:
            val = decode_integer(packet, offset, val_len)
        elif val_tag in (TAG_COUNTER32, TAG_GAUGE32, TAG_TIMETICKS, TAG_COUNTER64):
            val = decode_unsigned(packet, offset, val_len)
        elif val_tag == TAG_OCTETSTRING:
            raw_bytes = packet[offset:offset+val_len]
            try:
                val = raw_bytes.decode('utf-8')
            except UnicodeDecodeError:
                val = raw_bytes.hex(':')
        elif val_tag == TAG_OID:
            val = decode_oid(packet, offset, val_len).lstrip('.')
        elif val_tag == TAG_IPADDRESS:
            val = '.'.join(str(b) for b in packet[offset:offset+val_len])
        elif val_tag in (TAG_NO_SUCH_OBJECT, TAG_NO_SUCH_INSTANCE, TAG_END_OF_MIB_VIEW):
            val = None
        else:
            val = packet[offset:offset+val_len]
            
        offset += val_len
        results[oid_str] = val
        
    return results


# ==================== HIGH-LEVEL SNMP API ====================

def snmp_get(host: str, oids: List[str], community: str = "public", port: int = 161, timeout: float = 2.5, retries: int = 1) -> Optional[Dict[str, Any]]:
    """
    Eksekusi SNMP v2c GET query ke host. Mengembalikan dict {oid: val} atau None.
    Default timeout 2.5s dan retries 1x untuk respon cepat tanpa blocking siklus polling.
    """
    pkt, _ = build_pdu(oids, community=community, pdu_type=PDU_GET)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    
    try:
        for _ in range(retries + 1):
            try:
                sock.sendto(pkt, (host, port))
                resp, _ = sock.recvfrom(65535)
                return parse_snmp_response(resp)
            except socket.timeout:
                continue
    except Exception as e:
        logger.debug(f"SNMP GET ke {host} gagal: {e}")
        return None
    finally:
        sock.close()
    return None


def snmp_getnext(host: str, oid: str, community: str = "public", port: int = 161, timeout: float = 2.5) -> Optional[Tuple[str, Any]]:
    pkt, _ = build_pdu([oid], community=community, pdu_type=PDU_GETNEXT)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto(pkt, (host, port))
        resp, _ = sock.recvfrom(65535)
        parsed = parse_snmp_response(resp)
        if parsed:
            for k, v in parsed.items():
                return k, v
    except Exception:
        return None
    finally:
        sock.close()
    return None


def snmp_walk(host: str, root_oid: str, community: str = "public", port: int = 161, timeout: float = 2.5, max_repetitions: int = 120) -> Dict[str, Any]:
    """
    Eksekusi SNMP v2c Walk mulai dari root_oid.
    """
    root_norm = root_oid.strip('.')
    curr_oid = root_norm
    results = {}
    
    for _ in range(max_repetitions):
        res = snmp_getnext(host, curr_oid, community=community, port=port, timeout=timeout)
        if not res:
            break
        next_oid, val = res
        next_norm = next_oid.strip('.')
        if not next_norm.startswith(root_norm) or val is None:
            break
        results[next_norm] = val
        curr_oid = next_norm
        
    return results


def format_timeticks(ticks: int) -> str:
    """Konversi TimeTicks (centiseconds) ke format readable: X days, HH:MM:SS"""
    if not ticks or ticks < 0:
        return "Unknown"
    seconds = ticks // 100
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if days > 0:
        return f"{days} days, {hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def get_device_community(device) -> str:
    """Mengambil SNMP community string yang tepat untuk tiap perangkat."""
    explicit_comm = getattr(device, 'snmp_community', None)
    if explicit_comm:
        return explicit_comm

    dev_name = getattr(device, 'name', '').lower()
    ip = getattr(device, 'ip_address', '')
    vendor = getattr(device, 'vendor', '').lower()
    
    # Aruba Access Points (HO AP-505)
    if any(x in ip for x in ["193", "183", "177"]) or "ap-505" in dev_name or ("aruba" in vendor and "ap" in dev_name):
        return os.getenv("ARUBA_AP_COMMUNITY", "HODevice")
    # Aruba Switch HO (SW-2930F-HO)
    elif "sw-2930f" in dev_name or ip == "192.168.1.10" or ("aruba" in vendor and ("sw" in dev_name or "switch" in dev_name)):
        return os.getenv("ARUBA_SNMP_COMMUNITY", "public")
    # Huawei Access Points (Corner AP-AE5776)
    elif any(x in ip for x in ["154", "173", "156"]) or "ap-ae5776" in dev_name or ("huawei" in vendor and "ap" in dev_name):
        return os.getenv("HUAWEI_AP_COMMUNITY", "CornerDevice")
    # Huawei Switch Corner (SW-S5735-CORNER)
    elif "sw-s5735" in dev_name or ip == "192.168.1.155" or "corner" in dev_name or ("huawei" in vendor and ("sw" in dev_name or "switch" in dev_name)):
        return os.getenv("HUAWEI_SNMP_COMMUNITY", "agiva_mon")
    # Palo Alto Firewall (HO Gateway)
    elif "pa" in dev_name or "11" in ip or "palo" in vendor:
        return os.getenv("PA_SNMP_COMMUNITY", "publik")
    elif "ho" in dev_name or "aruba" in vendor:
        return os.getenv("ARUBA_SNMP_COMMUNITY", "public")
    return os.getenv("SNMP_COMMUNITY_DEFAULT", "public")


# ==================== UNIFIED POLLING TELEMETRY COLLECTOR ====================

def poll_device_telemetry_snmp(device) -> Dict[str, Any]:
    """
    Ekstraksi telemetri komprehensif seragam via SNMP v2c untuk:
    - Aruba 2930F
    - Huawei S5735
    - Palo Alto PA-220
    
    Return dict metrics standar:
    {
        "status": "UP"|"DOWN",
        "cpu": float,
        "mem": float,
        "traffic": float,
        "ingress": float,
        "egress": float,
        "uptime": str,
        "packet_buffers": float,
        "message_buffers": float,
        "tx_errors": int,
        "rx_errors": int,
        "tx_drops": int
    }
    """
    ip = device.ip_address
    community = get_device_community(device)
    vendor = (device.vendor or "").lower()
    
    metrics = {
        "status": "DOWN",
        "cpu": 0.0,
        "mem": 0.0,
        "traffic": 0.0,
        "ingress": 0.0,
        "egress": 0.0,
        "latency": 0.0,
        "packet_loss": 0.0,
        "uptime": "Unknown",
        "packet_buffers": 0.0,
        "message_buffers": 0.0,
        "tx_errors": 0,
        "rx_errors": 0,
        "tx_drops": 0
    }
    
    # 1. Tentukan OID List untuk sekali query GET PDU (Multi-varbind)
    query_oids = [OID_SYS_UPTIME, OID_SYS_DESCR]
    
    if "huawei" in vendor or "155" in ip:
        query_oids.extend([OID_HUAWEI_CPU_UTIL, OID_HUAWEI_MEM_UTIL])
        # Port Uplink Huawei 10GE1/0/1 (Index 25 pada Huawei ifTable)
        uplink_idx = "25"
    elif "aruba" in vendor or "10" in ip:
        query_oids.extend([
            OID_ARUBA_CPU_UTIL, 
            OID_ARUBA_MEM_TOTAL, 
            OID_ARUBA_MEM_FREE,
            OID_ARUBA_MEM_ALLOC,
            OID_ARUBA_PKT_BUF_TOTAL,
            OID_ARUBA_PKT_BUF_FREE,
            OID_ARUBA_MSG_BUF_TOTAL,
            OID_ARUBA_MSG_BUF_FREE
        ])
        # Port Uplink Aruba Port 1 (Index 1)
        uplink_idx = "1"
    else:  # Palo Alto PA-220
        query_oids.extend([
            OID_PA_CPU_DP0,
            OID_PA_CPU_MP,
            OID_PA_MEM_TOTAL,
            OID_PA_MEM_USED,
            OID_PA_SESSION_UTIL,
            OID_PA_SESSION_MAX,
            OID_PA_ACTIVE_SESSIONS
        ])
        # Port LAN ethernet1/2 (Index 7 pada PA-220)
        uplink_idx = "7"

    # Tambahkan OID 64-bit HC counters dan health error/discard untuk port uplink
    query_oids.extend([
        f"{OID_IF_HC_IN_OCTETS}.{uplink_idx}",
        f"{OID_IF_HC_OUT_OCTETS}.{uplink_idx}",
        f"{OID_IF_IN_ERRORS}.{uplink_idx}",
        f"{OID_IF_OUT_ERRORS}.{uplink_idx}",
        f"{OID_IF_IN_DISCARDS}.{uplink_idx}",
        f"{OID_IF_OUT_DISCARDS}.{uplink_idx}"
    ])
    
    # Eksekusi SNMP GET ke perangkat (timeout 3.0 detik, 1 kali retry demi keandalan tanpa blocking)
    res = snmp_get(ip, query_oids, community=community, timeout=3.0, retries=1)
    
    if not res:
        logger.warning(f"SNMP polling timeout ke {device.name} ({ip}) [community: {community}]")
        return metrics
    
    metrics["status"] = "UP"
    
    # 2. Parse Uptime
    ticks = res.get(OID_SYS_UPTIME)
    if ticks is not None and isinstance(ticks, int):
        metrics["uptime"] = format_timeticks(ticks)
        
    # 3. Parse CPU & Memory per Vendor (100% Data Riil dari Sensor/Register SNMP, Tanpa Dummy)
    if "huawei" in vendor or "155" in ip:
        # Huawei CPU
        hw_cpu = res.get(OID_HUAWEI_CPU_UTIL)
        metrics["cpu"] = float(hw_cpu) if hw_cpu is not None else 0.0
            
        # Huawei Memory
        hw_mem = res.get(OID_HUAWEI_MEM_UTIL)
        metrics["mem"] = float(hw_mem) if hw_mem is not None else 0.0

        # Huawei Buffer Congestion (Opsi 2: Data Riil Egress & Ingress Queue Buffer Drops pada Uplink)
        hw_tx_drop = int(res.get(f"{OID_IF_OUT_DISCARDS}.{uplink_idx}") or 0)
        hw_rx_drop = int(res.get(f"{OID_IF_IN_DISCARDS}.{uplink_idx}") or 0)
        metrics["packet_buffers"] = float(hw_tx_drop)
        metrics["message_buffers"] = float(hw_rx_drop)
            
    elif "aruba" in vendor or "10" in ip:
        # Aruba CPU
        ar_cpu = res.get(OID_ARUBA_CPU_UTIL)
        metrics["cpu"] = float(ar_cpu) if ar_cpu is not None else 0.0
            
        # Aruba Memory Utilization:
        # MIB NETSWITCH-MIB: .5.1 = Total, .6.1 = Free, .7.1 = Allocated
        mem_tot = res.get(OID_ARUBA_MEM_TOTAL)
        mem_alloc = res.get(OID_ARUBA_MEM_ALLOC)
        mem_free = res.get(OID_ARUBA_MEM_FREE)
        if mem_tot and mem_tot > 0:
            if mem_alloc is not None and mem_alloc > 0:
                metrics["mem"] = round((float(mem_alloc) / float(mem_tot)) * 100.0, 1)
            elif mem_free is not None:
                used = mem_tot - mem_free
                metrics["mem"] = round((float(used) / float(mem_tot)) * 100.0, 1)
            else:
                metrics["mem"] = 0.0
        else:
            metrics["mem"] = 0.0
            
        # Aruba Packet Buffers & Message Buffers
        buf_tot = res.get(OID_ARUBA_PKT_BUF_TOTAL)
        buf_free = res.get(OID_ARUBA_PKT_BUF_FREE)
        if buf_tot and buf_free and buf_tot > 0:
            metrics["packet_buffers"] = round(((buf_tot - buf_free) / buf_tot) * 100.0, 1)
        else:
            metrics["packet_buffers"] = 0.0

        msg_tot = res.get(OID_ARUBA_MSG_BUF_TOTAL)
        msg_free = res.get(OID_ARUBA_MSG_BUF_FREE)
        if msg_tot and msg_free and msg_tot > 0:
            metrics["message_buffers"] = round(((msg_tot - msg_free) / msg_tot) * 100.0, 1)
        else:
            metrics["message_buffers"] = 0.0
            
    else:  # Palo Alto PA-220 NGFW
        # Palo Alto Data Plane CPU (Max of DP0 and MP)
        pa_dp_cpu = res.get(OID_PA_CPU_DP0)
        pa_mp_cpu = res.get(OID_PA_CPU_MP)
        if pa_dp_cpu is not None or pa_mp_cpu is not None:
            metrics["cpu"] = float(max(pa_dp_cpu or 0, pa_mp_cpu or 0))
        else:
            metrics["cpu"] = 0.0
            
        # Palo Alto Memory Utilization: (used / total) * 100
        pa_m_tot = res.get(OID_PA_MEM_TOTAL)
        pa_m_used = res.get(OID_PA_MEM_USED)
        if pa_m_tot and pa_m_used and pa_m_tot > 0:
            metrics["mem"] = round((float(pa_m_used) / float(pa_m_tot)) * 100.0, 1)
        else:
            metrics["mem"] = 0.0
            
        # Palo Alto Firewall Session Capacity & Active Sessions (Data Riil PAN-COMMON-MIB)
        pa_sess_util = res.get(OID_PA_SESSION_UTIL)
        pa_sess_act = res.get(OID_PA_ACTIVE_SESSIONS)
        pa_sess_max = res.get(OID_PA_SESSION_MAX)

        if pa_sess_util is not None:
            metrics["packet_buffers"] = float(pa_sess_util)
        elif pa_sess_act is not None and pa_sess_max and pa_sess_max > 0:
            metrics["packet_buffers"] = round((float(pa_sess_act) / float(pa_sess_max)) * 100.0, 2)
        else:
            metrics["packet_buffers"] = 0.0

        # Simpan Active Sessions count riil
        if pa_sess_act is not None:
            metrics["message_buffers"] = float(pa_sess_act)
        elif pa_dp_cpu is not None:
            metrics["message_buffers"] = float(pa_dp_cpu)
        else:
            metrics["message_buffers"] = 0.0

    # 4. Parse Error & Discard Counters (Fast single-packet extraction from uplink OID - 100% Pure Hardware SNMP)
    metrics["rx_errors"] = int(res.get(f"{OID_IF_IN_ERRORS}.{uplink_idx}") or 0)
    metrics["tx_errors"] = int(res.get(f"{OID_IF_OUT_ERRORS}.{uplink_idx}") or 0)
    metrics["tx_drops"] = int(res.get(f"{OID_IF_OUT_DISCARDS}.{uplink_idx}") or 0)
    
    # 5. Parse Real Dynamic Throughput Ingress & Egress (64-bit HC Octets Delta)
    rx_bytes = res.get(f"{OID_IF_HC_IN_OCTETS}.{uplink_idx}")
    tx_bytes = res.get(f"{OID_IF_HC_OUT_OCTETS}.{uplink_idx}")
    
    if rx_bytes is not None and tx_bytes is not None:
        curr_rx = int(rx_bytes)
        curr_tx = int(tx_bytes)
        now_ts = time.time()
        dev_key = f"{getattr(device, 'device_id', 'dev')}_{ip}"
        
        if dev_key in _SNMP_PREV_COUNTERS:
            prev_ts, prev_rx, prev_tx = _SNMP_PREV_COUNTERS[dev_key]
            dt = now_ts - prev_ts
            if dt > 0:
                delta_rx = curr_rx - prev_rx if curr_rx >= prev_rx else (2**64 - prev_rx) + curr_rx
                delta_tx = curr_tx - prev_tx if curr_tx >= prev_tx else (2**64 - prev_tx) + curr_tx
                
                # Konversi Bytes ke Megabits per second (Mbps): (Bytes * 8) / (dt * 1,000,000)
                ing_mbps = round((delta_rx * 8.0) / (dt * 1_000_000.0), 2)
                egr_mbps = round((delta_tx * 8.0) / (dt * 1_000_000.0), 2)
                
                # Batasi anomali spike di atas kapasitas link fisik (10 Gbps)
                metrics["ingress"] = min(ing_mbps, 10000.0)
                metrics["egress"] = min(egr_mbps, 10000.0)
                metrics["traffic"] = round(metrics["ingress"] + metrics["egress"], 2)
                
        _SNMP_PREV_COUNTERS[dev_key] = (now_ts, curr_rx, curr_tx)
        
    return metrics


# ==================== WAN STATUS SNMP POLLER (PALO ALTO BIZNET) ====================

def poll_wan_status_snmp(ip: str = "192.168.1.11", community: str = "publik", wan_idx: str = "8") -> Dict[str, Any]:
    """
    Ekstraksi statistik WAN ISP Biznet (ethernet1/3 pada Palo Alto PA-220, SNMP ifIndex 8) via SNMP v2c.
    """
    wan_data = {
        "provider": "Biznet Dedicated",
        "interface_name": "ethernet1/3",
        "download_mbps": 0.0,
        "upload_mbps": 0.0,
        "total_mbps": 0.0,
        "rx_errors": 0,
        "tx_errors": 0,
        "status": "DOWN"
    }
    
    query_oids = [
        f"{OID_IF_OPER_STATUS}.{wan_idx}",
        f"{OID_IF_HC_IN_OCTETS}.{wan_idx}",
        f"{OID_IF_HC_OUT_OCTETS}.{wan_idx}",
        f"{OID_IF_IN_ERRORS}.{wan_idx}",
        f"{OID_IF_OUT_ERRORS}.{wan_idx}"
    ]
    
    res = snmp_get(ip, query_oids, community=community, timeout=2.5, retries=1)
    if not res:
        return wan_data
        
    oper_status = res.get(f"{OID_IF_OPER_STATUS}.{wan_idx}")
    wan_data["status"] = "UP" if oper_status == 1 else "DOWN"
    wan_data["rx_errors"] = int(res.get(f"{OID_IF_IN_ERRORS}.{wan_idx}") or 0)
    wan_data["tx_errors"] = int(res.get(f"{OID_IF_OUT_ERRORS}.{wan_idx}") or 0)
    
    rx_bytes = res.get(f"{OID_IF_HC_IN_OCTETS}.{wan_idx}")
    tx_bytes = res.get(f"{OID_IF_HC_OUT_OCTETS}.{wan_idx}")
    
    if rx_bytes is not None and tx_bytes is not None:
        curr_rx = int(rx_bytes)
        curr_tx = int(tx_bytes)
        now_ts = time.time()
        
        if "wan_palo" in _SNMP_WAN_PREV_COUNTERS:
            prev_ts, prev_rx, prev_tx = _SNMP_WAN_PREV_COUNTERS["wan_palo"]
            dt = now_ts - prev_ts
            if dt > 0:
                delta_rx = curr_rx - prev_rx if curr_rx >= prev_rx else 0
                delta_tx = curr_tx - prev_tx if curr_tx >= prev_tx else 0
                
                # Ingress WAN = Download, Egress WAN = Upload
                wan_data["download_mbps"] = round((delta_rx * 8.0) / (dt * 1_000_000.0), 2)
                wan_data["upload_mbps"] = round((delta_tx * 8.0) / (dt * 1_000_000.0), 2)
                wan_data["total_mbps"] = round(wan_data["download_mbps"] + wan_data["upload_mbps"], 2)
                
        _SNMP_WAN_PREV_COUNTERS["wan_palo"] = (now_ts, curr_rx, curr_tx)
        
    return wan_data



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
    devices = session.query(Device).order_by(Device.device_id.asc()).all()
    session.close()
    return devices

# ==========================================
# 2. poll_device(device) & Retry Wrapper
# ==========================================
def _execute_device_poll(device):
    """
    Eksekusi satu kali pengambilan metrik telemetri ke perangkat MURNI via SNMP v2c (Multi-Vendor).
    Seragam untuk Aruba 2930F, Huawei S5735, dan Palo Alto PA-220 tanpa overhead SSH atau XML API.
    Pengukuran ketersediaan fisik (Host Reachability) dan transmisi Layer-3 diukur presisi via ICMP Ping.
    """
    metrics = {
        "status": "DOWN",
        "cpu": 0.0,
        "mem": 0.0,
        "traffic": 0.0,
        "ingress": 0.0,
        "egress": 0.0,
        "latency": 0.0,
        "packet_loss": 0.0,
        "uptime": "Unknown",
        "packet_buffers": 0.0,
        "message_buffers": 0.0,
        "tx_errors": 0,
        "rx_errors": 0,
        "tx_drops": 0
    }

    # ========================================================
    # 1. PURE SNMP v2c TELEMETRY (Aruba, Huawei, Palo Alto)
    # ========================================================
    snmp_success = False
    try:
        snmp_res = poll_device_telemetry_snmp(device)
        if snmp_res and snmp_res.get("status") == "UP":
            logger.info(f"[{device.name}] Berhasil polling telemetri via SNMP v2c ({device.ip_address})")
            metrics.update(snmp_res)
            snmp_success = True

            # Polling WAN khusus gateway Palo Alto via SNMP v2c
            vendor_clean = (device.vendor or "").lower()
            if any(k in vendor_clean for k in ['palo', 'pan']) or '11' in device.ip_address:
                try:
                    wan_metrics = poll_wan_status_snmp(device.ip_address, community=get_device_community(device))
                    _, inet_lat, inet_loss = measure_ping_metrics("1.1.1.1", count=2, timeout_sec=1)
                    _, gw_lat, _ = measure_ping_metrics("192.168.18.1", count=1, timeout_sec=1)
                    wan_metrics["latency_ms"] = inet_lat
                    wan_metrics["packet_loss"] = inet_loss
                    wan_metrics["gateway_latency_ms"] = gw_lat
                    metrics["wan_data"] = wan_metrics
                except Exception as e_w:
                    logger.warning(f"Gagal polling WAN SNMP Palo Alto: {e_w}")

                # Pre-fetch cache telemetri sesi wireless client dari Palo Alto (Opsi 1)
                try:
                    from telemetry_helper import fetch_palo_alto_client_telemetry
                    fetch_palo_alto_client_telemetry(device.ip_address)
                except Exception as e_pa_cli:
                    logger.debug(f"Palo Alto client telemetry pre-fetch skipped: {e_pa_cli}")
        else:
            logger.warning(f"[{device.name}] SNMP query tidak merespons (UDP 161 timeout)")
    except Exception as e_snmp:
        logger.error(f"[{device.name}] Exception pada SNMP polling: {e_snmp}")

    # ========================================================
    # 2. METRIK TRANSMISI LAYER-3 (ICMP PING REACHABILITY & LATENCY)
    # Standar Industri NOC: Host Reachability (UP/DOWN) ditentukan oleh ICMP Ping.
    # Jika ICMP merespons (loss < 100%), perangkat fisik terbukti UP di kantor.
    # ========================================================
    try:
        is_ping_up, lat_val, loss_val = measure_ping_metrics(device.ip_address, count=2, timeout_sec=2)
        metrics["latency"] = lat_val
        metrics["packet_loss"] = loss_val

        if is_ping_up:
            metrics["status"] = "UP"
            if not snmp_success:
                logger.info(f"[{device.name}] Perangkat merespons ICMP Ping (RTT: {lat_val:.1f}ms, Loss: {loss_val:.0f}%) -> Status: UP (SNMP timeout).")
                # Pertahankan metrik terakhir agar dashboard & threshold tidak drop palsu ke 0
                if getattr(device, 'cpu_usage', None) is not None and float(device.cpu_usage) > 0:
                    metrics["cpu"] = float(device.cpu_usage)
                if getattr(device, 'mem_usage', None) is not None and float(device.mem_usage) > 0:
                    metrics["mem"] = float(device.mem_usage)
                if getattr(device, 'uptime', None) and device.uptime not in ["Offline", "Unknown"]:
                    metrics["uptime"] = device.uptime

                # Pertahankan juga metrik traffic terakhir agar grafik dashboard tidak drop ke 0
                try:
                    s_hist = db_session()
                    last_l = s_hist.query(DeviceStatusLog).filter_by(device_id=device.device_id).order_by(DeviceStatusLog.log_id.desc()).first()
                    if last_l:
                        if not metrics.get("cpu") and last_l.cpu_usage:
                            metrics["cpu"] = float(last_l.cpu_usage)
                        if not metrics.get("mem") and last_l.mem_usage:
                            metrics["mem"] = float(last_l.mem_usage)
                        if last_l.traffic_mbps:
                            metrics["traffic"] = float(last_l.traffic_mbps)
                            metrics["ingress"] = float(last_l.ingress_mbps or 0.0)
                            metrics["egress"] = float(last_l.egress_mbps or 0.0)
                    s_hist.close()
                except Exception:
                    pass
        else:
            # Jika Ping 100% loss DAN SNMP gagal, maka perangkat benar-benar DOWN
            if not snmp_success:
                logger.warning(f"[{device.name}] Tidak merespons ICMP Ping (100% loss) & SNMP timeout -> Status: DOWN")
                metrics["status"] = "DOWN"
            else:
                # SNMP aktif tapi Ping ditolak (ICMP disabled/blocked oleh firewall) -> Tetap UP
                metrics["status"] = "UP"
    except Exception as e_ping:
        logger.warning(f"Gagal mengukur ICMP latency/loss untuk {device.name}: {e_ping}")
        if not snmp_success:
            metrics["status"] = "DOWN"

    return metrics


def poll_device(device):
    """
    Sesuai instruksi LLD & spesifikasi arsitektur:
    Setiap koneksi ke device dibungkus try/except dengan retry terbatas (3x)
    dan timeout eksplisit, sehingga satu device bermasalah tidak memblokir
    siklus polling device lain.
    """
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            metrics = _execute_device_poll(device)
            # Jika polling menghasilkan status DOWN dan belum percobaan terakhir, retry
            if metrics.get("status") == "DOWN" and attempt < max_retries:
                logger.warning(f"Percobaan {attempt}/{max_retries} ke {device.name} terdeteksi DOWN. Melakukan retry dalam 2 detik...")
                time.sleep(2)
                continue
            return metrics
        except Exception as e:
            logger.warning(f"Percobaan {attempt}/{max_retries} koneksi ke {device.name} ({device.ip_address}) gagal: {e}")
            if attempt < max_retries:
                time.sleep(2)
            else:
                logger.error(f"[DataCollector] Koneksi polling ke {device.name} ({device.ip_address}) gagal setelah {max_retries}x percobaan: {e}")
                return {
                    "status": "DOWN",
                    "cpu": 0.0,
                    "mem": 0.0,
                    "traffic": 0.0,
                    "ingress": 0.0,
                    "egress": 0.0,
                    "latency": 0.0,
                    "packet_loss": 100.0,
                    "uptime": "Offline",
                    "packet_buffers": 0.0,
                    "message_buffers": 0.0,
                    "tx_errors": 0,
                    "rx_errors": 0,
                    "tx_drops": 0
                }

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
    device.latency_ms = metrics.get("latency", 0.0)
    device.packet_loss = metrics.get("packet_loss", 0.0)
    device.uptime = metrics["uptime"]
    device.last_polled = datetime.now()

    # Log histori metrik
    log_entry = DeviceStatusLog(
        device_id=device.device_id,
        status=metrics["status"],
        cpu_usage=metrics["cpu"],
        mem_usage=metrics["mem"],
        latency_ms=metrics.get("latency", 0.0),
        packet_loss=metrics.get("packet_loss", 0.0),
        traffic_mbps=metrics["traffic"],
        ingress_mbps=metrics.get("ingress", 0.0),
        egress_mbps=metrics.get("egress", 0.0),
        packet_buffers=metrics.get("packet_buffers", 0.0),
        message_buffers=metrics.get("message_buffers", 0.0),
        tx_errors=metrics.get("tx_errors", 0),
        rx_errors=metrics.get("rx_errors", 0),
        tx_drops=metrics.get("tx_drops", 0),
        timestamp=datetime.now()
    )
    try:
        session.add(log_entry)

        # Log WAN Biznet jika tersedia
        if metrics.get("wan_data"):
            w = metrics["wan_data"]
            wan_entry = WanStatusLog(
                timestamp=datetime.now(),
                interface_name='ethernet1/3',
                provider='Biznet',
                status=w.get("status", "UP"),
                download_mbps=w.get("download_mbps", 0.0),
                upload_mbps=w.get("upload_mbps", 0.0),
                total_mbps=w.get("total_mbps", 0.0),
                latency_ms=w.get("latency_ms", 0.0),
                gateway_latency_ms=w.get("gateway_latency_ms", 0.0),
                packet_loss=w.get("packet_loss", 0.0),
                rx_errors=w.get("rx_errors", 0),
                tx_errors=w.get("tx_errors", 0)
            )
            session.add(wan_entry)

        # Eksekusi Rule Engine & Anti-spam (Komponen 4 LLD)
        import importlib
        import rule_engine
        importlib.reload(rule_engine)
        rule_engine.evaluate_device_rules(session, device, metrics)
        session.commit()
    except Exception as e:
        logger.error(f"Gagal commit metrik/alert untuk {device.name}: {e}")
        session.rollback()
    finally:
        session.close()

# ==========================================
# 4. run_polling_cycle()
# ==========================================
def run_polling_cycle():
    """
    Sesuai LLD: loop semua device, dipanggil scheduler.
    Tiap iterasi terisolasi try/except agar 1 device bermasalah tidak memblokir device lain.
    """
    awal_polling = datetime.now()
    awal_str = awal_polling.strftime("%Y-%m-%d %H:%M:%S")
    next_str = get_next_polling_time(awal_polling)

    logger.info("=== START POLLING CYCLE ===")
    logger.info(f"[*] Awal Polling : {awal_str}")
    logger.info(f"[*] Next Polling : {next_str} (Interval: {POLLING_INTERVAL_MINUTES} menit)")
    devices = load_inventory()
    
    for device in devices:
        try:
            logger.info(f"Polling {device.name} ({device.vendor})...")
            metrics = poll_device(device)
            save_metrics(device.device_id, metrics)
        except Exception as e:
            logger.error(f"Siklus polling gagal pada perangkat {device.name}: {e}")
        
    # Sinkronisasi berkala (2 menit) telemetri klien nirkabel AP ke tabel PostgreSQL ap_client_telemetry
    try:
        from telemetry_helper import sync_all_ap_telemetry_to_db
        sync_all_ap_telemetry_to_db()
    except Exception as e_ap:
        logger.debug(f"Sinkronisasi berkala AP client telemetry ke database dilewati: {e_ap}")

    duration = (datetime.now() - awal_polling).total_seconds()
    next_str_end = get_next_polling_time(awal_polling)
    logger.info(f"=== END POLLING CYCLE (Durasi: {duration:.2f}s) ===")
    logger.info(f"[*] Awal Polling : {awal_str}")
    logger.info(f"[*] Next Polling : {next_str_end}")

# ==========================================
# 5. Data Retention Policy (Housekeeping)
# ==========================================
def cleanup_old_device_logs(retention_days=None):
    """
    Data Retention Policy (Auto-Pruning / Housekeeping):
    Menghapus riwayat data metrik lama dari tabel public.device_status_logs
    yang berumur lebih dari `retention_days` hari (default 30 hari).
    """
    if retention_days is None:
        retention_days = int(os.getenv("LOG_RETENTION_DAYS", "30"))
        
    session = db_session()
    cutoff_date = datetime.now() - timedelta(days=retention_days)
    try:
        deleted_count = session.query(DeviceStatusLog).filter(DeviceStatusLog.timestamp < cutoff_date).delete()
        del_wan = session.query(WanStatusLog).filter(WanStatusLog.timestamp < cutoff_date).delete()
        session.commit()
        if (deleted_count + del_wan) > 0:
            logger.info(f"[Housekeeping] Berhasil menghapus {deleted_count} baris log device dan {del_wan} baris log WAN lama (> {retention_days} hari).")
        else:
            logger.info(f"[Housekeeping] Retensi data bersih. Tidak ada data device/WAN logs yang berumur lebih dari {retention_days} hari.")
    except Exception as e:
        logger.error(f"[Housekeeping] Gagal menjalankan data retention cleanup device_status_logs: {e}")
        session.rollback()
    finally:
        session.close()

def cleanup_old_incident_logs(retention_days=30):
    """
    Data Retention Policy (Auto-Pruning / Housekeeping):
    Menghapus riwayat insiden lama dari tabel public.incident_logs
    yang berumur lebih dari `retention_days` hari (30 hari).
    """
    session = db_session()
    cutoff_date = datetime.now() - timedelta(days=retention_days)
    try:
        deleted_count = session.query(IncidentLog).filter(IncidentLog.started_at < cutoff_date).delete()
        session.commit()
        if deleted_count > 0:
            logger.info(f"[Housekeeping] Berhasil menghapus {deleted_count} baris insiden lama (> {retention_days} hari) dari incident_logs.")
        else:
            logger.info(f"[Housekeeping] Retensi data bersih. Tidak ada data incident_logs yang berumur lebih dari {retention_days} hari.")
    except Exception as e:
        logger.error(f"[Housekeeping] Gagal menjalankan data retention cleanup incident_logs: {e}")
        session.rollback()
    finally:
        session.close()

def cleanup_old_backup_history_job(retention_days=None):
    """
    Data Retention Policy (Auto-Pruning / Housekeeping):
    Menghapus riwayat backup konfigurasi & log audit lama dari tabel public.backup_history
    dan berkas fisik .txt di disk lokal yang berumur lebih dari `retention_days` hari (default 30 hari).
    Dilengkapi Safety Net untuk mempertahankan minimal 1 backup Config terakhir per perangkat demi Disaster Recovery.
    """
    try:
        from backup_service import cleanup_old_backup_history
        cleanup_old_backup_history(retention_days=retention_days)
    except Exception as e:
        logger.error(f"[Housekeeping] Gagal menjalankan data retention cleanup backup_history: {e}")

def start_scheduler():
    global _scheduler
    _scheduler = BackgroundScheduler()
    # LLD: Polling dijadwalkan tiap 1-5 menit. Menggunakan POLLING_INTERVAL_MINUTES (default 2 menit)
    _scheduler.add_job(run_polling_cycle, 'interval', minutes=POLLING_INTERVAL_MINUTES, id='polling_job')
    
    # Data Retention Policy: Dijadwalkan otomatis setiap tengah malam (jam 00:00, 00:05, & 00:10 WIB)
    _scheduler.add_job(cleanup_old_device_logs, 'cron', hour=0, minute=0, id='cleanup_device_logs_job')
    _scheduler.add_job(cleanup_old_incident_logs, 'cron', hour=0, minute=5, id='cleanup_incident_logs_job')
    _scheduler.add_job(cleanup_old_backup_history_job, 'cron', hour=0, minute=10, id='cleanup_backup_history_job')
    
    # Pencadangan Konfigurasi & Log Harian Otomatis: Setiap Pukul 02:00 WIB (Incremental via Checkpoint)
    backup_hour = int(os.getenv('BACKUP_CRON_HOUR', 2))
    backup_minute = int(os.getenv('BACKUP_CRON_MINUTE', 0))
    try:
        from backup_service import run_all_devices_backup
        _scheduler.add_job(run_all_devices_backup, 'cron', hour=backup_hour, minute=backup_minute, id='daily_backup_job')
        logger.info(f"Job pencadangan harian terdaftar: setiap pukul {backup_hour:02d}:{backup_minute:02d} WIB.")
    except Exception as e_bkp:
        logger.warning(f"Gagal mendaftarkan job backup harian ke scheduler: {e_bkp}")
    
    _scheduler.start()
    
    # Jalankan pemeriksaan awal retensi data saat collector pertama kali start
    cleanup_old_device_logs()
    cleanup_old_incident_logs()
    cleanup_old_backup_history_job()
    
    # Langsung jalankan 1 siklus polling awal agar metrik riil terisi seketika tanpa harus menunggu interval
    run_polling_cycle()
    
    next_poll = get_next_polling_time()
    logger.info(f"Scheduler berjalan. Menunggu jadwal polling (tiap {POLLING_INTERVAL_MINUTES} mnt, Next Polling: {next_poll}) & housekeeping (tiap 00:00)...")
    try:
        while True:
            time.sleep(2)
    except (KeyboardInterrupt, SystemExit):
        _scheduler.shutdown()
        logger.info("Data Collector dihentikan.")

if __name__ == "__main__":
    import sys
    if "--once" in sys.argv or "--manual" in sys.argv:
        logger.info("=== MODE MANUAL: Menjalankan 1 siklus polling & metrik ===")
        run_polling_cycle()
        logger.info("=== Selesai 1 siklus manual. Keluar (tidak berjalan di latar belakang). ===")
    else:
        start_scheduler()

