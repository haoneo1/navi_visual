超声导航（演示版）

## 功能说明

### 主应用程序 (main.py)
实时超声导航系统，支持视频流处理和3D渲染。

### 数据包回放工具 (review_app.py)
用于回放 .upkg 格式的数据包文件。

#### 功能特性
- 选择 .upkg 文件进行回放
- 左侧显示图像帧
- 右侧显示 trace 数据（JSON格式）
- 底部进度条选择帧
- 支持逐帧播放和自动播放

#### 使用方法
```bash
# 方式1：使用启动脚本
./run_review.sh

# 方式2：使用 uv 直接运行
uv run python review_app.py

# 方式3：直接运行（需要安装依赖）
python3 review_app.py
```

#### 支持的图像格式
- NV12 (YUV420)
- RGB/BGR
- PNG/JPG (压缩格式)
- 其他numpy数组格式