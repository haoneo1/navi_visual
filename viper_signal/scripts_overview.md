# Viper 相关脚本与源文件说明

本文档概述各文件**主要职责**、**入口**及**依赖关系**。协议细节见同目录 [`protocol_notes.md`](protocol_notes.md)。

---

## 一、Python（`viper_signal/` 目录内）

### 1. `viper_main.py`

| 项目 | 说明 |
|------|------|
| **角色** | 主入口：把 **USB 读线程** 与 **matplotlib 3D 界面** 串起来。 |
| **做法** | 创建 `queue.Queue(maxsize=10)`；`ViperUSBComm(data_queue=..., trace_dir="trace")`；`Viper3DVisualizer(data_queue)`；`connect()` → `start_continuous()` → 守护线程 `read_usb_data` → 主线程 `visualizer.run()`。 |
| **退出** | 关窗口或 Ctrl+C 后：`keep_reading=False`、join 读线程、`disconnect()`（内含停 continuous、关 trace 文件）。 |
| **依赖** | `viper_usb_comm`、`viper_ui_display`；需已安装 **PyUSB**、**matplotlib**、**numpy**。 |
| **运行** | 在 `viper_signal` 目录下：`python viper_main.py`（或配置好 `PYTHONPATH`）。 |

---

### 2. `viper_usb_comm.py`

| 项目 | 说明 |
|------|------|
| **角色** | **唯一与 USB 协议强绑定**的 Python 模块：设备发现、组 VPRC 命令包、CRC、启停 **Continuous PNO**、读 IN 端点、解析 **VPRP** PNO 帧。 |
| **核心类** | `ViperUSBComm`：属性含 `dev`、`is_continuous`、`data_queue`、`trace_file` 等。 |
| **主要方法** | `connect` / `disconnect`、`start_continuous` / `stop_continuous`、`send_cmd` / `recv_data`、`read_usb_data`（循环读）、`process_pno_frame`（按偏移解析 `seuid`、`frame_num`、`sensor_count`、每路 32 字节 `SENFRAMEDATA`）、`log_data`（JSONL 写入 `trace/`）。 |
| **常量** | VID/PID、IN/OUT 端点、`VIPER_CMD_PREAMBLE` / `VIPER_PNO_PREAMBLE`、`CMD_CONTINUOUS_PNO`、`CMD_ACTION_*`、`CRC_TABLE` / `calc_crc16`。 |
| **被谁使用** | `viper_main.py`；不自带 `if __name__ == "__main__"` 时仅作库（以当前文件为准）。 |

---

### 3. `viper_ui_display.py`

| 项目 | 说明 |
|------|------|
| **角色** | **仅负责可视化**：从队列取「已解析好的字典」`frame_data`（含 `sensors` 的 `num` / `pos` / `ori`）。 |
| **核心类** | `Viper3DVisualizer`：`init_plot` 建 3D 子图 + 底部文字区；`euler_to_rotation_matrix`、`draw_rotated_box`；主循环里非阻塞取队列、限频刷新（约 10 FPS）、画轨迹 `deque`。 |
| **依赖** | **numpy**、**matplotlib**（含 `mpl_toolkits.mplot3d`）。 |
| **特点** | 不访问 USB；便于单独改 UI 或换别的后端消费同一队列结构。 |

---

### 4. `viper_usb_continuous.py`

| 项目 | 说明 |
|------|------|
| **角色** | **单文件一体化**：在同一脚本内重复实现 USB 常量、CRC、`ViperUSB` 类、解析与 **matplotlib 3D**（与 `viper_main` + `viper_usb_comm` + `viper_ui_display` 功能重叠）。 |
| **适用场景** | 需要「一个文件拷走就能跑」的演示、或历史兼容；维护时易与 `viper_usb_comm.py` 产生分歧，改协议建议以 `viper_usb_comm.py` 为准。 |
| **运行** | `python viper_usb_continuous.py`（文件末尾含 `main` / `if __name__ == "__main__"`）。 |

---

## 二、C++（官方风格终端示例）

### 5. `main.cpp`

| 项目 | 说明 |
|------|------|
| **内容** | `main()` 中构造 `viper_ui ui`，调用 `ui.detect_input()`，进入交互式终端流程。 |
| **产物** | 由 `Makefile` 链接生成可执行文件 **`vpr_simp_term`**。 |

---

### 6. `viper_ui.h` / `viper_ui.cpp`

| 项目 | 说明 |
|------|------|
| **角色** | **人机交互与业务编排**：USB 连接后启动 `read_usb_data` 线程；主循环读单键命令（`C` continuous、`P` 单次 PNO、`W` WhoAmI、`H` 帮助、`^X` 退出等）。 |
| **数据** | 内含 CRC 表、`CalcCrc16`；使用 **`viper_queue`**（`cmd_queue` / `pno_queue`）在 USB 读线程与解析逻辑之间传递字节流。 |
| **依赖** | `viper_usb.h`、`viper_queue.h`、`ViperInterface.h`。 |

---

### 7. `viper_usb.h` / `viper_usb.cpp`

| 项目 | 说明 |
|------|------|
| **角色** | **libusb 薄封装**：`usb_connect` 枚举设备、匹配 VID/PID（`0x0f44` / `0xbf01`）、打开、claim 接口 0；`usb_send_cmd` / `usb_rec_resp` 与 **OUT 0x02 / IN 0x81** 通信；`usb_disconnect` 释放资源。 |
| **依赖** | `libusb.h`（本目录随附头文件，配合系统 `-lusb-1.0`）。 |

---

### 8. `viper_queue.h` / `viper_queue.cpp`

| 项目 | 说明 |
|------|------|
| **角色** | **线程安全字节队列**：`push` 写入 USB 读到的字节；`wait_and_pop` 先取 8 字节判断 preamble/size，再弹出完整一帧到调用方缓冲区；非法 preamble 时清空队列防粘包。 |
| **同步** | `std::mutex` + `std::condition_variable`；`init(uint32_t*)` 绑定外部「是否继续」标志。 |

---

### 9. `ViperInterface.h`

| 项目 | 说明 |
|------|------|
| **角色** | **Polhemus 官方协议头**：命令枚举 `eViperCmds`、动作 `eCmdActions`、传感器/源数量上限、USB VID/PID 宏、`SEUPNO` / `SENFRAMEDATA` 等结构体布局。 |
| **体积** | 行数多，**不重复抄结构体**；改协议或核对偏移时以此文件与厂商文档为准。 |

---

### 10. `libusb.h`

| 项目 | 说明 |
|------|------|
| **角色** | **libusb-1.0 C API 头文件**（随示例打包），供 `viper_usb.cpp` 编译使用；非项目业务逻辑。 |

---

### 11. `Makefile`

| 项目 | 说明 |
|------|------|
| **内容** | `g++ -std=c++11` 编译 `main.o`、`viper_queue.o`、`viper_ui.o`、`viper_usb.o`，链接 **`usb-1.0`**、**`pthread`**，输出 **`vpr_simp_term`**。 |
| **命令** | `make` / `make clean`。 |

---

## 三、运行产物与数据（非脚本）

| 路径/类型 | 说明 |
|-----------|------|
| `trace/viper_trace_*.json` | `viper_usb_comm` 在连接后写入的 **JSONL** 轨迹（头行 + 每帧传感器 pos/ori + 结束摘要）；由 `ViperUSBComm.start_logging` 等控制。 |
| `.git/` | 若该目录为嵌套 git 仓库，为版本控制元数据，与业务无关。 |

---

## 四、仓库根目录：`viper_main_simple.py`（与 `viper_signal/` 并列）

| 项目 | 说明 |
|------|------|
| **角色** | **极简独立示例**：单文件内用 **dataclass** 描述 `SensorData`；`ViperUSBReader` 负责连接 VID/PID、detach 内核驱动、选 IN 端点、CRC16 表、后台读线程。 |
| **与 `viper_signal` 差异** | 帧头常量 **`VIPER_PNO_PREAMBLE = 0x504E4F56`**（注释为 `"PNOV"`）与 `viper_usb_comm` 中的 **`0x50525056`（VPRP）** 不同；解析字段类型为 **整数元组** 的简化模型，**不宜与正式 `viper_usb_comm` 协议实现混用**，仅作学习/另一设备变种参考。 |
| **运行** | 在项目根：`python viper_main_simple.py`（需按文件内注释核对设备与协议）。 |

---

## 五、推荐阅读顺序

1. 想快速看 **Python 全流程**：`viper_main.py` → `viper_usb_comm.py` → `viper_ui_display.py`。  
2. 想对 **字节协议** 对表：`protocol_notes.md` + `ViperInterface.h`。  
3. 想对照 **官方 C 示例**：`main.cpp` → `viper_ui.cpp` → `viper_queue.cpp` → `viper_usb.cpp`。  
4. 单文件跑通旧逻辑：`viper_usb_continuous.py`。

---

*若某脚本入口或类名与仓库最新代码不一致，以源文件为准。*
