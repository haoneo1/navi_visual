import usb.core
import usb.util
import threading
import time
from dataclasses import dataclass
from typing import Optional, Tuple


# --------------------------
# 1. 配置与常量（根据设备实际情况修改）
# --------------------------
VIPER_VID = 0x0F44    # 设备厂商ID（需替换为你的设备ID）
VIPER_PID = 0xBF01    # 设备产品ID（需替换为你的设备ID）
VIPER_PNO_PREAMBLE = 0x504E4F56  # 传感器数据帧头（"PNOV" 小端序）
CRC16_POLY = 0x8005   # CRC16 校验多项式（与设备协议匹配）
MAX_DATA_LEN = 256    # 最大单次读取字节数（根据设备协议调整）
READ_INTERVAL = 0.002 # 数据读取间隔（2ms，匹配设备数据流频率）


# --------------------------
# 2. 数据结构（用 dataclass 简化，替代 C++ 结构体）
# --------------------------
@dataclass
class SensorData:
    """传感器单帧数据结构（位置+姿态）"""
    sensor_id: int          # 传感器编号
    frame_num: int          # 数据帧号
    position: Tuple[int, int, int]  # 位置 (x, y, z)
    orientation: Tuple[int, int, int]  # 姿态 (roll, pitch, yaw)


# --------------------------
# 3. USB 数据读取核心类
# --------------------------
class ViperUSBReader:
    def __init__(self):
        self.dev: Optional[usb.core.Device] = None  # USB 设备对象
        self.ep_in = None  # 输入端点（设备 → 主机）
        self.running = False  # 数据读取开关
        self.read_thread: Optional[threading.Thread] = None  # 读取线程
        self._init_crc_table()  # 初始化 CRC16 校验表

    def _init_crc_table(self) -> None:
        """初始化 CRC16 校验表（预计算提升效率）"""
        self.crc_table = [0] * 256
        for i in range(256):
            crc = i
            for _ in range(8):
                crc = (crc << 1) ^ CRC16_POLY if (crc & 0x8000) else (crc << 1)
                crc &= 0xFFFF  # 保持 16 位
        return

    def _calc_crc16(self, data: bytes) -> int:
        """计算字节数据的 CRC16 校验值"""
        crc = 0
        for byte in data:
            crc = self.crc_table[(crc ^ byte) & 0xFF] ^ (crc >> 8)
        return crc & 0xFFFF

    def connect(self) -> bool:
        """连接 USB 设备：成功返回 True，失败抛异常"""
        # 1. 查找设备
        self.dev = usb.core.find(idVendor=VIPER_VID, idProduct=VIPER_PID)
        if self.dev is None:
            raise RuntimeError(f"未找到设备（VID: {VIPER_VID:04X}, PID: {VIPER_PID:04X}）")

        # 2. 分离内核驱动（避免系统占用）
        try:
            if self.dev.is_kernel_driver_active(0):
                self.dev.detach_kernel_driver(0)
        except usb.core.USBError as e:
            raise RuntimeError(f"分离内核驱动失败：{e}")

        # 3. 配置设备并获取输入端点
        try:
            self.dev.set_configuration()  # 启用默认配置
            cfg = self.dev.get_active_configuration()
            intf = cfg[(0, 0)]  # 获取第一个接口（根据设备描述符调整）
            
            # 查找输入端点（地址为奇数）
            self.ep_in = usb.util.find_descriptor(
                intf,
                custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_IN
            )
            if self.ep_in is None:
                raise RuntimeError("未找到 USB 输入端点")
        except usb.core.USBError as e:
            raise RuntimeError(f"配置设备失败：{e}")

        print("✅ USB 设备连接成功")
        return True

    def _read_loop(self) -> None:
        """后台读取循环（线程内部执行）"""
        while self.running:
            try:
                # 1. 从 USB 读取数据
                raw_data = self.ep_in.read(MAX_DATA_LEN, timeout=100)  # 超时 100ms
                if not raw_data:
                    time.sleep(READ_INTERVAL)
                    continue

                # 2. 解析数据（按设备协议处理，此处需与硬件协议匹配）
                parsed_data = self._parse_raw_data(bytes(raw_data))
                if parsed_data:
                    self._on_data_received(parsed_data)  # 处理解析后的数据

            except usb.core.USBError as e:
                # 超时属于正常无数据情况，其他错误打印警告
                if e.errno != 110:  # 110 = 超时错误码
                    print(f"⚠️ USB 读取警告：{e}")
            except Exception as e:
                print(f"⚠️ 数据解析错误：{e}")
            finally:
                time.sleep(READ_INTERVAL)

    def _parse_raw_data(self, raw_data: bytes) -> Optional[SensorData]:
        """解析原始字节数据：返回 SensorData 对象，失败返回 None"""
        # 协议解析逻辑（需根据设备实际协议调整，以下为示例）
        min_len = 24  # 最小有效数据长度（帧头+帧号+传感器ID+位置+姿态+CRC）
        if len(raw_data) < min_len:
            return None

        # 1. 校验帧头
        preamble = int.from_bytes(raw_data[0:4], byteorder="little")
        if preamble != VIPER_PNO_PREAMBLE:
            return None

        # 2. 校验 CRC（假设最后 2 字节为 CRC）
        data_body = raw_data[:-2]
        crc_recv = int.from_bytes(raw_data[-2:], byteorder="little")
        crc_calc = self._calc_crc16(data_body)
        if crc_recv != crc_calc:
            print(f"⚠️ CRC 校验失败（计算: {crc_calc:04X}, 接收: {crc_recv:04X}）")
            return None

        # 3. 提取数据字段（字段偏移需与设备协议匹配）
        frame_num = int.from_bytes(raw_data[4:8], byteorder="little")
        sensor_id = (int.from_bytes(raw_data[8:12], byteorder="little") & 0xFF) + 1  # 传感器ID（低8位有效）
        position = (
            int.from_bytes(raw_data[12:16], byteorder="little"),
            int.from_bytes(raw_data[16:20], byteorder="little"),
            int.from_bytes(raw_data[20:24], byteorder="little")
        )
        orientation = (
            int.from_bytes(raw_data[24:28], byteorder="little") if len(raw_data) >= 28 else 0,
            int.from_bytes(raw_data[28:32], byteorder="little") if len(raw_data) >= 32 else 0,
            int.from_bytes(raw_data[32:36], byteorder="little") if len(raw_data) >= 36 else 0
        )

        return SensorData(sensor_id, frame_num, position, orientation)

    def _on_data_received(self, data: SensorData) -> None:
        """数据接收回调：可自定义处理逻辑（如打印、存储、转发）"""
        # 示例：格式化打印数据
        print(
            f"📊 帧号: {data.frame_num:6d} | "
            f"传感器 {data.sensor_id:2d} | "
            f"位置: ({data.position[0]:6d}, {data.position[1]:6d}, {data.position[2]:6d}) | "
            f"姿态: ({data.orientation[0]:6d}, {data.orientation[1]:6d}, {data.orientation[2]:6d})"
        )

    def start_reading(self) -> None:
        """启动连续数据读取（后台线程）"""
        if self.running:
            print("ℹ️ 数据读取已在运行")
            return
        self.running = True
        self.read_thread = threading.Thread(target=self._read_loop, daemon=True)  # 守护线程：主程序退出时自动结束
        self.read_thread.start()
        print("▶️ 开始连续读取 USB 数据（按 Ctrl+C 停止）")

    def stop_reading(self) -> None:
        """停止数据读取"""
        if not self.running:
            return
        self.running = False
        if self.read_thread and self.read_thread.is_alive():
            self.read_thread.join()
        print("\n⏹️ 停止数据读取")

    def disconnect(self) -> None:
        """断开 USB 设备连接"""
        self.stop_reading()
        if self.dev:
            usb.util.release_interface(self.dev, 0)
            usb.util.dispose_resources(self.dev)
            self.dev = None
        print("🔌 USB 设备已断开")


# --------------------------
# 4. 主程序入口
# --------------------------
if __name__ == "__main__":
    reader = ViperUSBReader()
    try:
        # 1. 连接设备
        reader.connect()
        # 2. 启动连续读取
        reader.start_reading()
        # 3. 阻塞主进程（按 Ctrl+C 退出）
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n👋 用户终止程序")
    except RuntimeError as e:
        print(f"\n❌ 程序异常：{e}")
    finally:
        # 4. 清理资源
        reader.disconnect()
