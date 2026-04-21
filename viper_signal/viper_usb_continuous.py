#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Viper USB Continuous Mode Reader
仿照C语言实现，从USB设备获取数据，采用continuous模式
"""

import usb.core
import usb.util
import struct
import time
import threading
import sys
import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
from collections import deque
import queue

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
    """计算CRC16校验值"""
    crc = 0
    for byte in data:
        crc = CRC_TABLE[(crc ^ byte) & 0xff] ^ (crc >> 8)
    return crc & 0xFFFFFFFF


class ViperUSB:
    """Viper USB设备类"""
    
    def __init__(self, data_queue=None):
        self.dev = None
        self.keep_reading = True
        self.is_continuous = False
        self.data_queue = data_queue  # 用于向3D可视化传递数据
        
    def connect(self):
        """连接USB设备"""
        # 查找设备
        self.dev = usb.core.find(idVendor=VID, idProduct=PID)
        
        if self.dev is None:
            raise ValueError("无法找到USB设备 (VID:0x%04x PID:0x%04x)" % (VID, PID))
        
        # 设置配置
        try:
            self.dev.set_configuration()
        except usb.core.USBError as e:
            print("设置配置时出错:", e)
            return False
        
        # 声明接口
        try:
            usb.util.claim_interface(self.dev, 0)
        except usb.core.USBError as e:
            print("声明接口时出错:", e)
            return False
        
        print("USB设备连接成功")
        return True
    
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
            except Exception as e:
                # Interface might already be released
                pass
            
            try:
                # Try to reset device to ensure clean state (optional, may fail)
                try:
                    self.dev.reset()
                except:
                    pass  # Reset may not be necessary
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
        """发送命令到USB设备"""
        try:
            bytes_written = self.dev.write(OUT_EP, cmd_data, timeout=1000)
            return bytes_written
        except usb.core.USBError as e:
            print("发送命令时出错:", e)
            return -1
    
    def recv_data(self, length):
        """从USB设备接收数据"""
        try:
            data = self.dev.read(IN_EP, length, timeout=200)
            return bytes(data)
        except usb.core.USBError as e:
            # 超时是正常的，不需要打印错误
            if e.errno != 110:  # 110是超时错误
                print("接收数据时出错:", e)
            return b''
    
    def start_continuous(self):
        """启动continuous模式"""
        # 构建命令包: preamble(4) + size(4) + SEUCMD(20) + CRC(4) = 32字节
        cmd_pkg = bytearray(32)
        
        # 填充preamble
        struct.pack_into('<I', cmd_pkg, 0, VIPER_CMD_PREAMBLE)
        
        # size = 32 - 8 (不包括preamble和size本身)
        struct.pack_into('<I', cmd_pkg, 4, 24)
        
        # SEUCMD结构: seuid(-1), cmd, action, arg1(0), arg2(0)
        struct.pack_into('<I', cmd_pkg, 8, 0xFFFFFFFF)  # seuid = -1 (所有SEU)
        struct.pack_into('<I', cmd_pkg, 12, CMD_CONTINUOUS_PNO)
        struct.pack_into('<I', cmd_pkg, 16, CMD_ACTION_SET)
        struct.pack_into('<I', cmd_pkg, 20, 0)  # arg1
        struct.pack_into('<I', cmd_pkg, 24, 0)  # arg2
        
        # 计算CRC (不包括最后4字节的CRC)
        crc = calc_crc16(cmd_pkg[:28])
        struct.pack_into('<I', cmd_pkg, 28, crc)
        
        # 发送命令
        if self.send_cmd(cmd_pkg) < 0:
            return False
        
        # 等待响应
        time.sleep(0.2)  # CMD_DELAY = 200ms
        
        # 接收响应
        resp = self.recv_data(32)
        if len(resp) < 32:
            print("响应数据长度不足：", len(resp), "，响应数据：", resp)
            return False
        
        # 检查CRC
        crc = calc_crc16(resp[:28])
        resp_crc = struct.unpack_from('<I', resp, 28)[0]
        if crc != resp_crc:
            print("响应CRC校验失败")
            return False
        
        # 检查ACK
        action = struct.unpack_from('<I', resp, 16)[0]
        if action != CMD_ACTION_ACK:
            print("未收到ACK响应")
            return False
        
        print("Continuous模式启动成功")
        self.is_continuous = True
        return True
    
    def read_usb_data(self):
        """持续读取USB数据的线程函数"""
        resp_size = 4 * 11 + 32 * 16 + 4  # 最大响应大小
        
        while self.keep_reading:
            data = self.recv_data(resp_size)
            if len(data) >= 8:  # 至少要有preamble和size
                preamble = struct.unpack_from('<I', data, 0)[0]
                
                if preamble == VIPER_PNO_PREAMBLE:
                    # 这是PNO数据帧
                    self.process_pno_frame(data)
                elif preamble == VIPER_CMD_PREAMBLE:
                    # 这是命令响应帧（可以忽略，因为我们只关心PNO数据）
                    pass
            
            time.sleep(0.002)  # 2ms延迟
    
    def process_pno_frame(self, data):
        """处理PNO数据帧"""
        if len(data) < 24:  # 至少要有header + SEUPNO
            return
        
        # 读取size
        size = struct.unpack_from('<I', data, 4)[0]
        expected_size = size + 8  # size不包括preamble和size本身
        
        if len(data) < expected_size:
            # 数据不完整，需要继续读取
            return
        
        # 提取完整帧
        frame = data[:expected_size]
        
        # 检查CRC
        crc = calc_crc16(frame[:-4])
        frame_crc = struct.unpack_from('<I', frame, len(frame) - 4)[0]
        if crc != frame_crc:
            print("PNO帧CRC校验失败")
            return
        
        # 解析SEUPNO
        seuid = struct.unpack_from('<I', frame, 8)[0]
        frame_num = struct.unpack_from('<I', frame, 12)[0]
        sensor_count = struct.unpack_from('<I', frame, 20)[0]
        
        # 解析每个传感器的数据
        sensors_data = []
        offset = 24  # SEUPNO_HDR结束位置
        for i in range(sensor_count):
            if offset + 32 > len(frame):
                break
            
            # 解析SENFRAMEDATA
            sensor_info = struct.unpack_from('<I', frame, offset)[0]
            sensor_num = (sensor_info & 0x7F) + 1  # 传感器编号（1-based）
            
            # 解析位置和方向数据
            pos = struct.unpack_from('<fff', frame, offset + 4)
            ori = struct.unpack_from('<ffff', frame, offset + 16)
            
            sensors_data.append({
                'num': sensor_num,
                'pos': pos,
                'ori': ori
            })
            
            offset += 32  # SENFRAMEDATA大小是32字节
        
        # 将数据发送到队列（用于3D可视化）
        if self.data_queue is not None:
            try:
                self.data_queue.put_nowait({
                    'frame_num': frame_num,
                    'seuid': seuid,
                    'sensors': sensors_data
                })
            except queue.Full:
                pass  # 队列满时跳过
        
        # 打印帧信息（可选，如果不需要可以注释掉）
        # print(f"\n帧 #{frame_num}, SEU ID: {seuid}, 传感器数量: {sensor_count}")
        # for sensor in sensors_data:
        #     print(f"  传感器 {sensor['num']}: "
        #           f"位置({sensor['pos'][0]:.3f}, {sensor['pos'][1]:.3f}, {sensor['pos'][2]:.3f}) "
        #           f"方向({sensor['ori'][0]:.3f}, {sensor['ori'][1]:.3f}, {sensor['ori'][2]:.3f})")


class Viper3DVisualizer:
    """3D Visualization Class"""
    
    def __init__(self, data_queue):
        self.data_queue = data_queue
        self.fig = None
        self.ax = None
        self.info_ax = None  # Text info display axis
        self.sensor_points = {}  # Store current points for each sensor
        self.sensor_trails = {}  # Store trajectories for each sensor
        self.max_trail_length = 100  # Maximum trail length
        self.running = True
        self.coord_range = 100  # Fixed coordinate range
        self.update_interval = 0.1  # Update every 0.1 seconds (10 FPS)
        self.last_update_time = 0
        self.latest_data = None  # Store latest sensor data
        
    def init_plot(self):
        """Initialize 3D plot"""
        plt.ion()  # Enable interactive mode
        self.fig = plt.figure(figsize=(14, 10))
        
        # Create subplots: 3D plot on top, text info at bottom
        gs = self.fig.add_gridspec(2, 1, height_ratios=[3, 1], hspace=0.3)
        
        # 3D plot
        self.ax = self.fig.add_subplot(gs[0], projection='3d')
        
        # Text info area
        self.info_ax = self.fig.add_subplot(gs[1])
        self.info_ax.axis('off')
        self.info_text = None
        
        # Set axis labels
        self.ax.set_xlabel('X (mm)')
        self.ax.set_ylabel('Y (mm)')
        self.ax.set_zlabel('Z (mm)')
        self.ax.set_title('Viper Sensor Real-time Position Tracking')
        
        # Set fixed coordinate range
        self.ax.set_xlim([-self.coord_range, self.coord_range])
        self.ax.set_ylim([-self.coord_range, self.coord_range])
        self.ax.set_zlim([-self.coord_range, self.coord_range])
        
        # Add grid
        self.ax.grid(True)
        
        # Set view angle
        self.ax.view_init(elev=20, azim=45)
        
        plt.tight_layout()
    
    def euler_to_rotation_matrix(self, euler):
        """Convert Euler angles (azimuth, elevation, roll) to rotation matrix"""
        az, el, roll = euler[0], euler[1], euler[2]
        
        # Convert to radians
        az = np.radians(az)
        el = np.radians(el)
        roll = np.radians(roll)
        
        # Rotation matrices
        Rz = np.array([[np.cos(az), -np.sin(az), 0],
                       [np.sin(az), np.cos(az), 0],
                       [0, 0, 1]])
        
        Ry = np.array([[np.cos(el), 0, np.sin(el)],
                       [0, 1, 0],
                       [-np.sin(el), 0, np.cos(el)]])
        
        Rx = np.array([[1, 0, 0],
                       [0, np.cos(roll), -np.sin(roll)],
                       [0, np.sin(roll), np.cos(roll)]])
        
        # Combined rotation: R = Rz * Ry * Rx
        R = Rz @ Ry @ Rx
        return R
    
    def draw_rotated_box(self, pos, ori, size=5, color='blue', alpha=0.7):
        """Draw a rotated box at position with orientation"""
        # Box vertices (centered at origin, size x size x size*2)
        box_vertices = np.array([
            [-size, -size, -size],
            [size, -size, -size],
            [size, size, -size],
            [-size, size, -size],
            [-size, -size, size],
            [size, -size, size],
            [size, size, size],
            [-size, size, size]
        ])
        
        # Get rotation matrix from Euler angles
        R = self.euler_to_rotation_matrix(ori)
        
        # Rotate box vertices
        rotated_vertices = (R @ box_vertices.T).T
        
        # Translate to position
        rotated_vertices += pos
        
        # Define box faces (6 faces, each with 4 vertices)
        faces = [
            [0, 1, 2, 3],  # bottom
            [4, 5, 6, 7],  # top
            [0, 1, 5, 4],  # front
            [2, 3, 7, 6],  # back
            [0, 3, 7, 4],  # left
            [1, 2, 6, 5]   # right
        ]
        
        # Draw each face using Poly3DCollection
        face_collection = []
        for face in faces:
            face_vertices = rotated_vertices[face]
            face_collection.append(face_vertices)
        
        # Create Poly3DCollection for all faces
        poly3d = Poly3DCollection(face_collection, 
                                  facecolors=color, 
                                  edgecolors='black', 
                                  linewidths=0.5, 
                                  alpha=alpha)
        self.ax.add_collection3d(poly3d)
        
    def update_plot(self, sensors_data):
        """Update 3D plot"""
        if self.ax is None:
            return
        
        # Clear previous plot
        self.ax.clear()
        
        # Reset axes
        self.ax.set_xlabel('X (mm)')
        self.ax.set_ylabel('Y (mm)')
        self.ax.set_zlabel('Z (mm)')
        self.ax.set_title('Viper Sensor Real-time Position Tracking')
        self.ax.grid(True)
        
        # Set fixed coordinate range
        self.ax.set_xlim([-self.coord_range, self.coord_range])
        self.ax.set_ylim([-self.coord_range, self.coord_range])
        self.ax.set_zlim([-self.coord_range, self.coord_range])
        
        # Draw coordinate origin
        origin = np.array([0, 0, 0])
        self.ax.scatter(origin[0], origin[1], origin[2], 
                       c='red', s=50, marker='o', label='Origin')
        
        # Colors for sensors
        colors = plt.cm.tab20(np.linspace(0, 1, 16))
        
        for sensor in sensors_data:
            sensor_num = sensor['num']
            pos = np.array(sensor['pos'])
            ori = sensor['ori']
            
            # Initialize trajectory
            if sensor_num not in self.sensor_trails:
                self.sensor_trails[sensor_num] = deque(maxlen=self.max_trail_length)
            
            # Add current position to trajectory
            self.sensor_trails[sensor_num].append(pos)
            
            # Get color for this sensor
            color = colors[(sensor_num - 1) % len(colors)]
            
            # Draw trajectory
            if len(self.sensor_trails[sensor_num]) > 1:
                trail = np.array(self.sensor_trails[sensor_num])
                self.ax.plot(trail[:, 0], trail[:, 1], trail[:, 2], 
                           color=color, alpha=0.3, linewidth=1)
            
            # Draw line from origin to current position
            self.ax.plot3D([origin[0], pos[0]], 
                          [origin[1], pos[1]], 
                          [origin[2], pos[2]], 
                          color=color, linewidth=2, alpha=0.5)
            
            # Draw rotated box to show orientation
            box_size = 3
            # Convert color from RGBA to RGB tuple for Poly3DCollection
            color_rgb = tuple(color[:3]) if len(color) > 3 else color
            self.draw_rotated_box(pos, ori, size=box_size, 
                                 color=color_rgb, alpha=0.7)
            
            # Draw current position point
            self.ax.scatter(pos[0], pos[1], pos[2], 
                          c=[color], s=100, marker='o', 
                          edgecolors='black', linewidths=1)
            
            # Add text label
            self.ax.text(pos[0], pos[1], pos[2], f' S{sensor_num}', fontsize=8)
        
        # Add legend (only show first few sensors to avoid clutter)
        if len(sensors_data) <= 8:
            self.ax.legend(loc='upper left', fontsize=8)
        
        # Update text info display
        self.update_info_text(sensors_data)
        
        # Refresh plot
        plt.draw()
        plt.pause(0.01)
    
    def update_info_text(self, sensors_data):
        """Update text information display with real-time coordinates and rotation"""
        if self.info_ax is None:
            return
        
        # Clear previous text
        self.info_ax.clear()
        self.info_ax.axis('off')
        
        # Create info text with header
        info_lines = ["Real-time Sensor Data:", "=" * 100]
        info_lines.append(f"{'Sensor':<8} {'X (mm)':>10} {'Y (mm)':>10} {'Z (mm)':>10}  |  {'Azimuth(°)':>12} {'Elevation(°)':>13} {'Roll(°)':>10}")
        info_lines.append("-" * 100)
        
        for sensor in sensors_data:
            sensor_num = sensor['num']
            pos = sensor['pos']
            ori = sensor['ori']
            
            # Format each value
            info_line = (f"Sensor {sensor_num:<2} "
                        f"{pos[0]:>10.3f} {pos[1]:>10.3f} {pos[2]:>10.3f}  |  "
                        f"{ori[0]:>12.2f} {ori[1]:>13.2f} {ori[2]:>10.2f}")
            info_lines.append(info_line)
        
        # Display text
        info_text = "\n".join(info_lines)
        self.info_ax.text(0.02, 0.95, info_text, 
                         transform=self.info_ax.transAxes,
                         fontsize=9, 
                         family='monospace',
                         verticalalignment='top',
                         bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))
    
    def run(self):
        """Run visualization loop"""
        self.init_plot()
        self.last_update_time = time.time()
        
        try:
            while self.running:
                # Check if window is closed
                if self.fig is None or not plt.fignum_exists(self.fig.number):
                    print("\nWindow closed, exiting...")
                    self.running = False
                    break
                
                current_time = time.time()
                time_since_last_update = current_time - self.last_update_time
                
                # Try to get latest data from queue (non-blocking, consume all available)
                # This ensures we always use the most recent data
                try:
                    while True:
                        data = self.data_queue.get_nowait()
                        self.latest_data = data  # Keep only the latest data
                except queue.Empty:
                    pass
                
                # Update plot only if enough time has passed (10 FPS = 0.1s interval)
                if time_since_last_update >= self.update_interval:
                    if self.latest_data is not None:
                        self.update_plot(self.latest_data['sensors'])
                        self.last_update_time = current_time
                    else:
                        # If no data yet, just pause briefly
                        plt.pause(0.01)
                else:
                    # Wait until it's time for next update
                    remaining_time = self.update_interval - time_since_last_update
                    if remaining_time > 0.001:  # Only sleep if significant time remains
                        plt.pause(min(remaining_time, 0.01))
                    
        except KeyboardInterrupt:
            pass
        except Exception as e:
            print(f"Visualization update error: {e}")
        finally:
            self.cleanup()
    
    def cleanup(self):
        """Cleanup resources"""
        self.running = False
        if self.fig is not None:
            plt.close(self.fig)


def main():
    """主函数"""
    # 创建数据队列用于在USB读取线程和可视化线程之间传递数据
    data_queue = queue.Queue(maxsize=10)
    
    # 创建Viper USB对象
    viper = ViperUSB(data_queue=data_queue)
    
    # 创建3D可视化对象
    visualizer = Viper3DVisualizer(data_queue)
    
    try:
        # Connect USB device
        if not viper.connect():
            print("Failed to connect USB device")
            return 1
        
        # Start continuous mode
        if not viper.start_continuous():
            print("Failed to start continuous mode")
            viper.disconnect()
            return 1
        
        # 启动读取线程
        read_thread = threading.Thread(target=viper.read_usb_data, daemon=True)
        read_thread.start()
        
        print("\nStarting USB data reading and 3D visualization (Close window or press Ctrl+C to exit)...\n")
        
        # 启动3D可视化（在主线程中运行，因为matplotlib需要主线程）
        try:
            visualizer.run()
        except KeyboardInterrupt:
            print("\n\nStopping...")
        finally:
            # Ensure cleanup happens
            visualizer.running = False
            viper.keep_reading = False
            viper.is_continuous = False
            
            # Wait for read thread to finish
            if read_thread.is_alive():
                read_thread.join(timeout=2)
            
            # Disconnect device (this will stop continuous mode)
            viper.disconnect()
            print("Exited")
    
    except Exception as e:
        print(f"Error occurred: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Ensure cleanup in all cases
        if 'visualizer' in locals():
            visualizer.running = False
        if 'viper' in locals():
            viper.keep_reading = False
            viper.is_continuous = False
            viper.disconnect()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

