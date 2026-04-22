# Navi Visual

超声导航可视化应用（当前版本为非 AI 版）。

## 当前功能

- 主界面为左右双栏：
  - 左侧：3D OpenGL 位置显示
  - 右侧：视频画面显示
- 视频输入支持两种模式：
  - 实时流（HTTP NV12）
  - dummy（本地图片序列）
- 支持录制会话：
  - `video.upkg`（NV12 原始帧包）
  - `viper_poses.jsonl`（USB 位姿流）
  - `meta.json`（会话元信息）

## 已移除内容

- 已删除 AI 推理链路（`modules/ai_analyzer.py`、`modules/network.py` 及接线代码）。
- 当前 `video_thread.py` 不再做模型分析，只负责取流、分发、录制、容错重启。

## 运行环境

- Python `>=3.11`
- 推荐使用 [uv](https://docs.astral.sh/uv/) 管理环境

安装依赖：

```bash
uv sync
```

## 启动主程序

```bash
uv run python main.py
```

## 配置文件

主配置：`config.toml`

### 1) 实时流模式

```toml
[dummy]
use_dummy = false
```

并配置：

```toml
[video]
video_url = "http://localhost:8080/raw"
frame_width = 1920
frame_height = 1088
fps = 30
```

### 2) dummy 模式

```toml
[dummy]
use_dummy = true
dummy_root = "./data/capture/20250816_100250"
dummy_frames = "./data/dummy_frames.txt"
dummy_path = "./data/dummy_path.txt"
```

说明：

- `dummy_frames` 为逐行图片路径列表。
- 支持相对路径，程序会做路径兼容解析。

## 录制输出目录

点击主界面 `Record` 后，会在以下目录创建会话文件夹：

```text
./data/Data_save/capture_YYYYMMDD_HHMMSS/
```

每次会话包含：

- `video.upkg`
- `viper_poses.jsonl`
- `meta.json`

## 目录与模块说明（核心）

- `main.py`：应用入口
- `modules/ui.py`：主窗口与流程调度
- `modules/video_thread.py`：视频采集线程（实时流/dummy）
- `modules/gl_widget.py`：3D OpenGL 控件
- `modules/data_package.py`：uPKG 读写
- `modules/config.py`：配置加载与保存
- `modules/dummy_path_visualizer.py`：dummy 路径 3D 演示脚本（独立工具）
- `viper_signal/`：Viper USB 通信与独立可视化脚本

## 常见说明

- 修改 `config.toml` 后建议重启程序（部分参数在模块加载时读取）。
- 若实时流无画面，优先检查 `video_url` 是否可访问。
- 若 dummy 无画面，检查 `dummy_frames` 中路径是否真实存在。  