#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Viper USB Communication Module
负责USB设备通讯和数据记录
"""

import logging
import usb.core
import usb.util
import struct
import time
import threading
import queue
import os
import json
from datetime import datetime

_log = logging.getLogger("navi_visual.viper_usb")

# USB设备参数
VID = 0x0f44
PID = 0xbf01
IN_EP = 0x81
OUT_EP = 0x02

# 命令和常量
VIPER_CMD_PREAMBLE = 0x43525056  # 'VPRC'
VIPER_PNO_PREAMBLE = 0x50525056  # 'VPRP'
CMD_CONTINUOUS_PNO = 19
CMD_ACTION_SET = 0
CMD_ACTION_GET = 1
CMD_ACTION_RESET = 2
CMD_ACTION_ACK = 3
CRC_SIZE = 4

# CRC表
CRC_TABLE = [
    0x0000, 0xC0C1, 0xC181, 0x0140, 0xC301, 0x03C0, 0x0280, 0xC241,
    0xC601, 0x06C0, 0x0780, 0xC741, 0x0500, 0xC5C1, 0xC481, 0x0440,
    0xCC01, 0x0CC0, 0x0D80, 0xCD41, 0x0F00, 0xCFC1, 0xCE81, 0x0E40,
    0x0A00, 0xCAC1, 0xCB81, 0x0B40, 0xC901, 0x09C0, 0x0880, 0xC841,
    0xD801, 0x18C0, 0x1980, 0xD941, 0x1B00, 0xDBC1, 0xDA81, 0x1A40,
    0x1E00, 0xDEC1, 0xDF81, 0x1F40, 0xDD01, 0x1DC0, 0x1C80, 0xDC41,
    0x1400, 0xD4C1, 0xD581, 0x1540, 0xD701, 0x17C0, 0x1680, 0xD641,
    0xD201, 0x12C0, 0x1380, 0xD341, 0x1100, 0xD1C1, 0xD081, 0x1040,
    0xF001, 0x30C0, 0x3180, 0xF141, 0x3300, 0xF3C1, 0xF281, 0x3240,
    0x3600, 0xF6C1, 0xF781, 0x3740, 0xF501, 0x35C0, 0x3480, 0xF441,
    0x3C00, 0xFCC1, 0xFD81, 0x3D40, 0xFF01, 0x3FC0, 0x3E80, 0xFE41,
    0xFA01, 0x3AC0, 0x3B80, 0xFB41, 0x3900, 0xF9C1, 0xF881, 0x3840,
    0x2800, 0xE8C1, 0xE981, 0x2940, 0xEB01, 0x2BC0, 0x2A80, 0xEA41,
    0xEE01, 0x2EC0, 0x2F80, 0xEF41, 0x2D00, 0xEDC1, 0xEC81, 0x2C40,
    0xE401, 0x24C0, 0x2580, 0xE541, 0x2700, 0xE7C1, 0xE681, 0x2640,
    0x2200, 0xE2C1, 0xE381, 0x2340, 0xE101, 0x21C0, 0x2080, 0xE041,
    0xA001, 0x60C0, 0x6180, 0xA141, 0x6300, 0xA3C1, 0xA281, 0x6240,
    0x6600, 0xA6C1, 0xA781, 0x6740, 0xA501, 0x65C0, 0x6480, 0xA441,
    0x6C00, 0xACC1, 0xAD81, 0x6D40, 0xAF01, 0x6FC0, 0x6E80, 0xAE41,
    0xAA01, 0x6AC0, 0x6B80, 0xAB41, 0x6900, 0xA9C1, 0xA881, 0x6840,
    0x7800, 0xB8C1, 0xB981, 0x7940, 0xBB01, 0x7BC0, 0x7A80, 0xBA41,
    0xBE01, 0x7EC0, 0x7F80, 0xBF41, 0x7D00, 0xBDC1, 0xBC81, 0x7C40,
    0xB401, 0x74C0, 0x7580, 0xB541, 0x7700, 0xB7C1, 0xB681, 0x7640,
    0x7200, 0xB2C1, 0xB381, 0x7340, 0xB101, 0x71C0, 0x7080, 0xB041,
    0x5000, 0x90C1, 0x9181, 0x5140, 0x9301, 0x53C0, 0x5280, 0x9241,
    0x9601, 0x56C0, 0x5780, 0x9741, 0x5500, 0x95C1, 0x9481, 0x5440,
    0x9C01, 0x5CC0, 0x5D80, 0x9D41, 0x5F00, 0x9FC1, 0x9E81, 0x5E40,
    0x5A00, 0x9AC1, 0x9B81, 0x5B40, 0x9901, 0x59C0, 0x5880, 0x9841,
    0x8801, 0x48C0, 0x4980, 0x8941, 0x4B00, 0x8BC1, 0x8A81, 0x4A40,
    0x4E00, 0x8EC1, 0x8F81, 0x4F40, 0x8D01, 0x4DC0, 0x4C80, 0x8C41,
    0x4400, 0x84C1, 0x8581, 0x4540, 0x8701, 0x47C0, 0x4680, 0x8641,
    0x8201, 0x42C0, 0x4380, 0x8341, 0x4100, 0x81C1, 0x8081, 0x4040
]


def calc_crc16(data):
    """Calculate CRC16 checksum"""
    crc = 0
    for byte in data:
        crc = CRC_TABLE[(crc ^ byte) & 0xff] ^ (crc >> 8)
    return crc & 0xFFFFFFFF


# SFINFO 位域：与 ViperInterface.h 中 _SFINFO 一致（单 uint32，小端）
# bfSnum:7, bfSvirt:1, bfPosUnits:2, bfOriUnits:2, ...
_POS_UNIT_NAMES = ("inch", "foot", "cm", "meter")
_ORI_UNIT_NAMES = ("euler_degree", "euler_radian", "quaternion", "unknown")


def parse_sfinfo(sensor_info):
    """
    从 SENFRAMEDATA 前 4 字节 (SFINFO) 解析 pos/ori 单位等。
    """
    pos_e = (sensor_info >> 8) & 0x3
    ori_e = (sensor_info >> 10) & 0x3
    return {
        "pos_units": pos_e,
        "pos_units_name": _POS_UNIT_NAMES[pos_e] if pos_e < len(_POS_UNIT_NAMES) else "unknown",
        "ori_units": ori_e,
        "ori_units_name": _ORI_UNIT_NAMES[ori_e] if ori_e < len(_ORI_UNIT_NAMES) else "unknown",
        "virtual": bool((sensor_info >> 7) & 1),
        "raw": int(sensor_info) & 0xFFFFFFFF,
    }


class ViperUSBComm:
    """Viper USB Communication Class with Data Logging"""
    
    def __init__(self, data_queue=None, trace_dir="trace"):
        self.dev = None
        self.keep_reading = True
        self.is_continuous = False
        self.data_queue = data_queue  # Queue for passing data to display
        self.trace_dir = trace_dir
        self.trace_file = None
        self.trace_start_time = None
        self.frame_count = 0
        # USB 流式组包：单次 read 常为半帧，需在缓冲区内按 preamble+size 切帧
        self._rx_buf = bytearray()
        # 与 viper_ui_display 中 latest_data 一致：解析线程上始终保留「最后一帧」，
        # 供 Qt 主线程直接读取，避免 bounded queue 满时 put_nowait 丢弃「新帧」导致探头不跟手。
        self._latest_frame = None
        self._latest_frame_lock = threading.Lock()

        # Create trace directory if it doesn't exist
        if not os.path.exists(self.trace_dir):
            os.makedirs(self.trace_dir)
            print(f"Created trace directory: {self.trace_dir}")
        
    def connect(self):
        """Connect to USB device"""
        # Find device
        self.dev = usb.core.find(idVendor=VID, idProduct=PID)
        
        if self.dev is None:
            raise ValueError(f"Unable to find USB device (VID:0x{VID:04x} PID:0x{PID:04x})")
        
        # Set configuration
        try:
            self.dev.set_configuration()
        except usb.core.USBError as e:
            print(f"Error setting configuration: {e}")
            return False
        
        # Claim interface
        try:
            usb.util.claim_interface(self.dev, 0)
        except usb.core.USBError as e:
            print(f"Error claiming interface: {e}")
            return False
        
        print("USB device connected successfully")
        
        # Start data logging immediately when USB communication starts
        self.start_logging()
        
        return True
    
    def start_logging(self):
        """Start data logging to trace file"""
        if self.trace_file is not None:
            return  # Already logging
        
        # Create trace file with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        trace_filename = os.path.join(self.trace_dir, f"viper_trace_{timestamp}.json")
        
        self.trace_file = open(trace_filename, 'w')
        self.trace_start_time = time.time()
        self.frame_count = 0
        
        # Write header
        header = {
            "start_time": datetime.now().isoformat(),
            "timestamp": timestamp,
            "device": {
                "vid": f"0x{VID:04x}",
                "pid": f"0x{PID:04x}"
            }
        }
        self.trace_file.write(json.dumps(header) + "\n")
        self.trace_file.flush()
        
        print(f"Started data logging to: {trace_filename}")
    
    def stop_logging(self):
        """Stop data logging"""
        if self.trace_file is not None:
            # Write summary
            summary = {
                "end_time": datetime.now().isoformat(),
                "duration_seconds": time.time() - self.trace_start_time,
                "total_frames": self.frame_count
            }
            self.trace_file.write(json.dumps(summary) + "\n")
            self.trace_file.close()
            self.trace_file = None
            print("Data logging stopped")
    
    def log_data(self, frame_data):
        """Log frame data to trace file"""
        if self.trace_file is None:
            return
        
        try:
            log_entry = {
                "timestamp": time.time() - self.trace_start_time,
                "frame_num": frame_data.get('frame_num', 0),
                "seuid": frame_data.get('seuid', 0),
                "sensors": []
            }
            
            for sensor in frame_data.get('sensors', []):
                sensor_entry = {
                    "num": sensor['num'],
                    "pos": list(sensor['pos']),
                    "ori": list(sensor['ori']),
                }
                if "sfinfo" in sensor:
                    sensor_entry["sfinfo"] = sensor["sfinfo"]
                log_entry["sensors"].append(sensor_entry)
            
            self.trace_file.write(json.dumps(log_entry) + "\n")
            self.trace_file.flush()  # Ensure data is written immediately
            self.frame_count += 1
            
        except Exception as e:
            print(f"Error logging data: {e}")
    
    def stop_continuous(self):
        """Stop continuous mode"""
        if not self.is_continuous or self.dev is None:
            return True
        
        try:
            # Build command package: preamble(4) + size(4) + SEUCMD(20) + CRC(4) = 32 bytes
            cmd_pkg = bytearray(32)
            
            # Fill preamble
            struct.pack_into('<I', cmd_pkg, 0, VIPER_CMD_PREAMBLE)
            
            # size = 32 - 8 (excluding preamble and size itself)
            struct.pack_into('<I', cmd_pkg, 4, 24)
            
            # SEUCMD structure: seuid(-1), cmd, action(RESET), arg1(0), arg2(0)
            struct.pack_into('<I', cmd_pkg, 8, 0xFFFFFFFF)  # seuid = -1 (all SEUs)
            struct.pack_into('<I', cmd_pkg, 12, CMD_CONTINUOUS_PNO)
            struct.pack_into('<I', cmd_pkg, 16, CMD_ACTION_RESET)  # RESET action
            struct.pack_into('<I', cmd_pkg, 20, 0)  # arg1
            struct.pack_into('<I', cmd_pkg, 24, 0)  # arg2
            
            # Calculate CRC (excluding last 4 bytes of CRC)
            crc = calc_crc16(cmd_pkg[:28])
            struct.pack_into('<I', cmd_pkg, 28, crc)
            
            # Send command
            if self.send_cmd(cmd_pkg) < 0:
                return False
            
            # Wait for response
            time.sleep(0.2)  # CMD_DELAY = 200ms
            
            # Receive response (try multiple times if needed)
            resp = self.recv_data(32)
            attempts = 0
            while len(resp) < 32 and attempts < 5:
                time.sleep(0.1)
                resp = self.recv_data(32)
                attempts += 1
            
            if len(resp) >= 32:
                # Check CRC
                crc = calc_crc16(resp[:28])
                resp_crc = struct.unpack_from('<I', resp, 28)[0]
                if crc == resp_crc:
                    # Check ACK
                    action = struct.unpack_from('<I', resp, 16)[0]
                    if action == CMD_ACTION_ACK:
                        self.is_continuous = False
                        return True
            
            # Even if response check fails, mark as stopped
            self.is_continuous = False
            return True
            
        except Exception as e:
            print(f"Error stopping continuous mode: {e}")
            self.is_continuous = False
            return False
    
    def disconnect(self):
        """Disconnect USB device"""
        # Stop logging
        self.stop_logging()
        
        # First stop continuous mode if active
        if self.is_continuous:
            try:
                print("Stopping continuous mode...")
                self.stop_continuous()
                time.sleep(0.1)  # Give device time to process
            except Exception as e:
                print(f"Warning: Error stopping continuous mode: {e}")
        
        self.keep_reading = False
        
        if self.dev is not None:
            try:
                # Release interface
                usb.util.release_interface(self.dev, 0)
            except:
                pass
            
            try:
                # Try to reset device to ensure clean state
                try:
                    self.dev.reset()
                except:
                    pass
            except:
                pass
            
            try:
                # Dispose resources
                usb.util.dispose_resources(self.dev)
            except:
                pass
            
            self.dev = None
            print("USB device disconnected successfully")
    
    def send_cmd(self, cmd_data):
        """Send command to USB device"""
        try:
            bytes_written = self.dev.write(OUT_EP, cmd_data, timeout=1000)
            return bytes_written
        except usb.core.USBError as e:
            print(f"Error sending command: {e}")
            return -1
    
    def recv_data(self, length):
        """Receive data from USB device"""
        try:
            data = self.dev.read(IN_EP, length, timeout=200)
            return bytes(data)
        except usb.core.USBError as e:
            # Timeout is normal, don't print error
            if e.errno != 110:  # 110 is timeout error
                print(f"Error receiving data: {e}")
            return b''
    
    def start_continuous(self):
        """Start continuous mode"""
        # Build command package: preamble(4) + size(4) + SEUCMD(20) + CRC(4) = 32 bytes
        cmd_pkg = bytearray(32)
        
        # Fill preamble
        struct.pack_into('<I', cmd_pkg, 0, VIPER_CMD_PREAMBLE)
        
        # size = 32 - 8 (excluding preamble and size itself)
        struct.pack_into('<I', cmd_pkg, 4, 24)
        
        # SEUCMD structure: seuid(-1), cmd, action, arg1(0), arg2(0)
        struct.pack_into('<I', cmd_pkg, 8, 0xFFFFFFFF)  # seuid = -1 (all SEUs)
        struct.pack_into('<I', cmd_pkg, 12, CMD_CONTINUOUS_PNO)
        struct.pack_into('<I', cmd_pkg, 16, CMD_ACTION_SET)
        struct.pack_into('<I', cmd_pkg, 20, 0)  # arg1
        struct.pack_into('<I', cmd_pkg, 24, 0)  # arg2
        
        # Calculate CRC (excluding last 4 bytes of CRC)
        crc = calc_crc16(cmd_pkg[:28])
        struct.pack_into('<I', cmd_pkg, 28, crc)
        
        # Send command
        if self.send_cmd(cmd_pkg) < 0:
            _log.warning("start_continuous: 发送 SET continuous 命令失败 (send_cmd < 0)")
            return False
        
        # Wait for response
        time.sleep(0.2)  # CMD_DELAY = 200ms

        # 设备可能分片或略慢返回，累积读取直到 32 字节或超时
        resp = b""
        deadline = time.time() + 1.5
        while len(resp) < 32 and time.time() < deadline:
            chunk = self.recv_data(64)
            if chunk:
                resp += chunk
            else:
                time.sleep(0.02)
        if len(resp) < 32:
            _log.warning(
                "start_continuous: 应答不足 32 字节 (得到 %s 字节)，请检查线材/独占占用/上电。原始: %s",
                len(resp),
                resp.hex() if resp else "(空)",
            )
            return False
        resp = resp[:32]
        
        # Check CRC
        crc = calc_crc16(resp[:28])
        resp_crc = struct.unpack_from('<I', resp, 28)[0]
        if crc != resp_crc:
            _log.warning(
                "start_continuous: 应答 CRC 未通过, 计算=0x%x 帧内=0x%x, raw=%s",
                crc,
                resp_crc,
                resp.hex(),
            )
            return False
        
        # Check ACK
        action = struct.unpack_from('<I', resp, 16)[0]
        if action != CMD_ACTION_ACK:
            _log.warning(
                "start_continuous: 非 ACK (action=0x%x, 期望 ACK=0x%x), raw=%s",
                action,
                CMD_ACTION_ACK,
                resp.hex(),
            )
            return False
        
        _log.info("Viper continuous 模式已启动 (PNO 流)")
        self.is_continuous = True
        return True
    
    def read_usb_data(self):
        """Thread function: 累积字节流并按帧解析，避免单次 recv 只有半帧导致永不入队。"""
        resp_size = 4 * 11 + 32 * 16 + 4  # Maximum response size
        max_frame_body = 8192  # size 字段上限，防止异常值撑爆内存

        while self.keep_reading:
            chunk = self.recv_data(resp_size)
            if chunk:
                self._rx_buf.extend(chunk)

            while len(self._rx_buf) >= 8:
                preamble = struct.unpack_from("<I", self._rx_buf, 0)[0]
                if preamble not in (VIPER_PNO_PREAMBLE, VIPER_CMD_PREAMBLE):
                    del self._rx_buf[0]
                    continue
                size = struct.unpack_from("<I", self._rx_buf, 4)[0]
                if size < 0 or size > max_frame_body:
                    del self._rx_buf[0]
                    continue
                expected = size + 8
                if len(self._rx_buf) < expected:
                    break
                packet = bytes(self._rx_buf[:expected])
                del self._rx_buf[:expected]
                if preamble == VIPER_PNO_PREAMBLE:
                    self.process_pno_frame(packet)
                # VPRC 应答帧：已消费丢弃即可

            time.sleep(0.002)
    
    def process_pno_frame(self, data):
        """Process PNO data frame"""
        if len(data) < 24:  # At least header + SEUPNO
            return
        
        # Read size
        size = struct.unpack_from('<I', data, 4)[0]
        expected_size = size + 8  # size doesn't include preamble and size itself
        
        if len(data) < expected_size:
            # Data incomplete, need to continue reading
            return
        
        # Extract complete frame
        frame = data[:expected_size]
        
        # Check CRC
        crc = calc_crc16(frame[:-4])
        frame_crc = struct.unpack_from('<I', frame, len(frame) - 4)[0]
        if crc != frame_crc:
            print("PNO frame CRC check failed")
            return
        
        # Parse SEUPNO
        seuid = struct.unpack_from('<I', frame, 8)[0]
        frame_num = struct.unpack_from('<I', frame, 12)[0]
        sensor_count = struct.unpack_from('<I', frame, 20)[0]
        
        # Parse each sensor's data
        sensors_data = []
        offset = 24  # SEUPNO_HDR end position
        for i in range(sensor_count):
            if offset + 32 > len(frame):
                break
            
            # Parse SENFRAMEDATA
            sensor_info = struct.unpack_from('<I', frame, offset)[0]
            sensor_num = (sensor_info & 0x7F) + 1  # Sensor number (1-based)
            sfinfo = parse_sfinfo(sensor_info)
            
            # Parse position and orientation data
            pos = struct.unpack_from('<fff', frame, offset + 4)
            ori = struct.unpack_from('<ffff', frame, offset + 16)
            
            sensors_data.append({
                'num': sensor_num,
                'pos': pos,
                'ori': ori,
                'sfinfo': sfinfo,
            })
            
            offset += 32  # SENFRAMEDATA size is 32 bytes
        
        # Create frame data structure
        frame_data = {
            'frame_num': frame_num,
            'seuid': seuid,
            'sensors': sensors_data
        }
        
        # Log data immediately
        self.log_data(frame_data)

        with self._latest_frame_lock:
            self._latest_frame = frame_data

        # Send data to queue（录制端 drain）；满时丢弃最旧的一条再塞，避免丢掉「当前这一帧」
        if self.data_queue is not None:
            while True:
                try:
                    self.data_queue.put_nowait(frame_data)
                    break
                except queue.Full:
                    try:
                        self.data_queue.get_nowait()
                    except queue.Empty:
                        pass

