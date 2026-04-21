# Viper（Polhemus）USB 协议笔记

本文档根据仓库内 `viper_signal/` 与 `viper_usb_comm.py` 的实现整理，便于对照 **官方头文件** `ViperInterface.h`（完整枚举与结构体定义以该文件为准）。

---

## 1. 设备与传输

| 项目 | 值 | 说明 |
|------|-----|------|
| USB VID | `0x0F44` | `POLHEMUS_USB_VID`（`ViperInterface.h`） |
| USB PID | `0xBF01` | `VIPER_USB_PID` |
| 控制/批量 OUT | `0x02` | 主机 → 设备，下发命令包 |
| 控制/批量 IN | `0x81` | 设备 → 主机，接收应答或 PNO 数据流 |

Python 使用 **PyUSB**（`usb.core`）；C++ 示例使用 **libusb-1.0**（`viper_usb.cpp`）。

---

## 2. 帧前缀（Preamble）

所有逻辑帧以 **小端 32 位** 前缀区分类型：

| 名称 | 十六进制 | ASCII 含义（大端读 uint32） |
|------|-----------|------------------------------|
| 命令帧 | `0x43525056` | `'VPRC'` |
| PNO 数据帧 | `0x50525056` | `'VPRP'` |

接收端先读前 8 字节：`preamble` + `size`，再按 `size` 收齐后续载荷与 CRC（见下文）。

---

## 3. 通用包布局

典型布局（与 `viper_queue.cpp` / `viper_usb_comm.py` 一致）：

```
[0:4)   uint32  preamble   VPRC 或 VPRP
[4:8)   uint32  size       后续载荷长度（不含这 8 字节本身；实现中常与「总长度 - 8」对应使用）
[8:8+N)         载荷       命令时为 SEUCMD 等；PNO 时为 SEUPNO + N×SENFRAMEDATA
[末尾4) uint32  crc        CRC16 算法填充为 32 位，参与校验的数据为「整帧去掉最后 4 字节 CRC」
```

**CRC**：实现使用 **CRC-16 查表**（`CRC_TABLE`），对 `frame[:-4]` 计算，与帧尾 4 字节比较（`viper_usb_comm.py` 中 `calc_crc16`）。

---

## 4. 命令帧（VPRC）与 SEUCMD 概要

命令包用于配置/查询/启停 **Continuous PNO** 等。Python 中 **32 字节** 启动连续模式示例如下（`start_continuous`）：

| 偏移 | 类型 | 含义 |
|------|------|------|
| 0 | u32 LE | `VIPER_CMD_PREAMBLE` (VPRC) |
| 4 | u32 LE | `24`（表示除前 8 字节外载荷为 24 字节；即 SEUCMD 20 + CRC 4 前的逻辑与代码注释一致） |
| 8 | u32 LE | `seuid`，常用 `0xFFFFFFFF`（-1，表示所有 SEU） |
| 12 | u32 LE | `cmd`，连续位姿为 **`19`** = `CMD_CONTINUOUS_PNO` |
| 16 | u32 LE | `action`，启动为 **`CMD_ACTION_SET` = 0`** |
| 20 | u32 LE | `arg1` |
| 24 | u32 LE | `arg2` |
| 28 | u32 LE | CRC（对前 28 字节做 CRC16，再 pack 为 u32） |

**停止 Continuous**：同一 `cmd = 19`，`action = CMD_ACTION_RESET`（值为 `2`），其余字段按 `stop_continuous` 构造，仍带 CRC；成功后设备 `action` 字段为 **`CMD_ACTION_ACK` = 3**（应答中偏移 16 处 u32）。

**动作枚举**（节选，见 `ViperInterface.h` `eCmdActions`）：

| 值 | 宏 | 含义 |
|----|-----|------|
| 0 | SET | 带载荷写状态 |
| 1 | GET | 查询 |
| 2 | RESET | 恢复默认 / 停止连续流等 |
| 3 | ACK | 应答成功 |

---

## 5. PNO 数据帧（VPRP）解析（Python 实现摘要）

当 `preamble == VIPER_PNO_PREAMBLE` 时，按 PNO 处理（`process_pno_frame`）：

1. `size = unpack('<I', data, 4)`，`expected_size = size + 8`。
2. 收满 `expected_size` 后，对 `frame[:-4]` 做 CRC，与 `frame` 最后 4 字节比较。
3. **SEUPNO 头**（小端）：
   - `seuid`：`frame[8:12]`
   - `frame_num`：`frame[12:16]`
   - `sensor_count`：`frame[20:24]`（实现中从偏移 20 读取）
4. 每个传感器 **`SENFRAMEDATA` 固定 32 字节**，从偏移 `24` 起循环：
   - `sensor_info`：u32 @ `offset`，`sensor_num = (sensor_info & 0x7F) + 1`（1 基编号）
   - **位置** `pos`：3×float @ `offset+4`（单位在 UI 中按 mm 显示）
   - **姿态** `ori`：4×float @ `offset+16`（实现中按四元数或欧拉相关浮点打包，具体语义以官方结构体为准）
   - `offset += 32`

解析结果进入 **`queue`** 供 3D 显示，并可选写入 **`trace/viper_trace_*.json`**（每行一条 JSON：`timestamp`、`frame_num`、`seuid`、`sensors[].num/pos/ori`）。

---

## 6. 与 C++ 示例的对应关系

| 组件 | 作用 |
|------|------|
| `ViperInterface.h` | 官方协议：命令号、结构体、传感器上限等 |
| `viper_usb.*` | libusb 打开设备、读写端点 |
| `viper_queue.*` | 字节流重组为「8 字节头 + size 载荷」完整帧 |
| `viper_ui.*` | 键盘菜单：启动/停止 continuous、单次 PNO、WhoAmI 等 |

Python 路线将「组包 + 读端点 + 解析 PNO」集中在 **`viper_usb_comm.py`**，不再使用 `viper_queue` 的 C++ 实现。

---

## 7. 工程内脚本分工（非协议，便于索引）

| 文件 | 用途 |
|------|------|
| `viper_main.py` | 组装 USB 线程 + 队列 + matplotlib 主线程可视化 |
| `viper_usb_comm.py` | USB、CRC、Continuous、PNO 解析、JSON trace |
| `viper_ui_display.py` | 仅从队列读数据绘图 |
| `viper_usb_continuous.py` | 单文件整合版，可独立运行 |
| `Makefile` + `main.cpp` 等 | 编译终端程序 `vpr_simp_term` |

---

## 8. 延伸阅读

- 完整命令列表与载荷结构：**`ViperInterface.h`**（`eViperCmds`、`SEUPNO`、`SENFRAMEDATA` 等）。
- 本仓库 Python 与官方字节序、偏移不一致时，**以设备厂商文档与 `ViperInterface.h` 为准**，再核对 `viper_usb_comm.py` 中的 `struct.unpack_from` 偏移。

---

*文档生成自项目内实现梳理，不替代 Polhemus 正式规格书。*
