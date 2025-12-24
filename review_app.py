#!/usr/bin/env python3
"""
数据包回放应用程序 - Review App
用于回放 .upkg 文件中的数据包内容

功能：
- 选择 .upkg 文件
- 左侧显示图片
- 右侧显示 trace 内容
- 底部进度条选择帧
"""

import sys
import json
import numpy as np
import cv2
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFileDialog, QSlider, QTextEdit, QSplitter,
    QFrame
)
from PyQt6.QtGui import QImage, QPixmap, QFont
from PyQt6.QtCore import Qt, QTimer

from modules.data_package import DataPackage
from modules.logger import get_logger
from modules.config import get_save_root

logger = get_logger()


class ReviewApp(QMainWindow):
    """数据包回放应用程序主窗口"""

    def __init__(self):
        super().__init__()
        self.package = None  # 当前加载的数据包
        self.current_frame = 0  # 当前帧索引
        self.total_frames = 0  # 总帧数
        self.init_ui()

    def init_ui(self):
        """初始化UI"""
        self.setWindowTitle('Data Package Review - 超声导航数据包回放')
        self.setGeometry(100, 100, 1400, 800)

        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # ========== 文件信息显示（顶部）==========
        # 文件信息标签移到顶部单独一行
        self.file_info_label = QLabel("未选择文件")
        self.file_info_label.setStyleSheet("font-size: 12px; color: #666; padding: 5px;")
        self.file_info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(self.file_info_label)

        # ========== 主显示区域 ==========
        # 创建水平分割器
        main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左侧：图片显示区域
        left_panel = QWidget()
        left_panel.setMinimumWidth(450)
        left_panel.setMaximumWidth(800)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(5, 5, 5, 5)

        # 图片标题
        image_title = QLabel("图像帧")
        image_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        image_title.setStyleSheet("font-size: 16px; font-weight: bold; padding: 5px; color: #333;")
        left_layout.addWidget(image_title)

        # 图片显示标签 - 固定尺寸
        self.image_label = QLabel("请先选择 .upkg 文件")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setStyleSheet("border: 2px dashed #ccc; background-color: #f9f9f9; font-size: 14px;")
        self.image_label.setFixedSize(400, 300)  # 固定尺寸
        left_layout.addWidget(self.image_label, 0, Qt.AlignmentFlag.AlignCenter)

        # 帧信息显示
        self.frame_info_label = QLabel("")
        self.frame_info_label.setStyleSheet("font-size: 12px; color: #666; padding: 5px;")
        self.frame_info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_layout.addWidget(self.frame_info_label)

        main_splitter.addWidget(left_panel)

        # 右侧：Trace数据显示区域
        right_panel = QWidget()
        right_panel.setMinimumWidth(450)
        right_panel.setMaximumWidth(800)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(5, 5, 5, 5)

        # Trace标题
        trace_title = QLabel("Trace 数据")
        trace_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        trace_title.setStyleSheet("font-size: 16px; font-weight: bold; padding: 5px; color: #333;")
        right_layout.addWidget(trace_title)

        # Trace显示文本框 - 固定高度
        self.trace_text = QTextEdit()
        self.trace_text.setReadOnly(True)
        self.trace_text.setFont(QFont("Consolas", 10))
        self.trace_text.setFixedHeight(300)  # 固定高度
        self.trace_text.setStyleSheet("""
            QTextEdit {
                border: 1px solid #ccc;
                background-color: #f8f8f8;
                font-family: Consolas, Monaco, monospace;
            }
        """)
        right_layout.addWidget(self.trace_text)

        main_splitter.addWidget(right_panel)

        # 设置分割器比例
        main_splitter.setSizes([600, 600])
        main_layout.addWidget(main_splitter)

        # ========== 底部控制区域 ==========
        control_layout = QHBoxLayout()

        # 文件选择按钮（最左侧）
        self.btn_open = QPushButton("选择 .upkg 文件")
        self.btn_open.setFixedHeight(40)
        self.btn_open.setStyleSheet("""
            QPushButton {
                padding: 10px;
                font-size: 14px;
                background-color: #4a90e2;
                color: white;
                border: none;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #357abd;
            }
            QPushButton:pressed {
                background-color: #2a5f8f;
            }
        """)
        self.btn_open.clicked.connect(self.on_open_file)
        control_layout.addWidget(self.btn_open)

        # 添加分隔符
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        separator.setStyleSheet("color: #ccc;")
        control_layout.addWidget(separator)

        # 播放控制按钮
        self.btn_prev = QPushButton("◀◀")
        self.btn_prev.setFixedSize(50, 40)
        self.btn_prev.clicked.connect(self.on_prev_frame)

        self.btn_play = QPushButton("▶")
        self.btn_play.setFixedSize(50, 40)
        self.btn_play.clicked.connect(self.on_play_pause)

        self.btn_next = QPushButton("▶▶")
        self.btn_next.setFixedSize(50, 40)
        self.btn_next.clicked.connect(self.on_next_frame)

        control_layout.addWidget(self.btn_prev)
        control_layout.addWidget(self.btn_play)
        control_layout.addWidget(self.btn_next)

        # 帧计数器
        self.frame_counter = QLabel("0 / 0")
        self.frame_counter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.frame_counter.setFixedWidth(100)
        self.frame_counter.setStyleSheet("font-size: 14px; font-weight: bold;")
        control_layout.addWidget(self.frame_counter)

        # 进度条
        self.progress_slider = QSlider(Qt.Orientation.Horizontal)
        self.progress_slider.setMinimum(0)
        self.progress_slider.setMaximum(0)  # 初始为0
        self.progress_slider.setValue(0)
        self.progress_slider.valueChanged.connect(self.on_slider_changed)
        self.progress_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border: 1px solid #999;
                height: 8px;
                background: #ddd;
                margin: 2px 0;
            }
            QSlider::handle:horizontal {
                background: #4a90e2;
                border: 1px solid #4a90e2;
                width: 18px;
                margin: -2px 0;
                border-radius: 3px;
            }
            QSlider::handle:horizontal:hover {
                background: #357abd;
            }
        """)
        control_layout.addWidget(self.progress_slider)

        # 时间戳显示
        self.timestamp_label = QLabel("00:00.000")
        self.timestamp_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.timestamp_label.setFixedWidth(120)
        self.timestamp_label.setStyleSheet("font-size: 12px; color: #666;")
        control_layout.addWidget(self.timestamp_label)

        main_layout.addLayout(control_layout)

        # 初始化播放状态
        self.is_playing = False
        self.play_timer = QTimer()
        self.play_timer.timeout.connect(self.on_next_frame)

        # 禁用控制按钮（直到加载文件）
        self.set_controls_enabled(False)

    def set_controls_enabled(self, enabled: bool):
        """启用/禁用控制按钮"""
        self.btn_prev.setEnabled(enabled)
        self.btn_play.setEnabled(enabled)
        self.btn_next.setEnabled(enabled)
        self.progress_slider.setEnabled(enabled)

    def on_open_file(self):
        """选择并打开 .upkg 文件"""
        # 从配置文件获取默认目录
        default_dir = get_save_root()
        # 如果是相对路径，转换为绝对路径
        if not Path(default_dir).is_absolute():
            default_dir = str(Path(__file__).parent / default_dir)

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择数据包文件",
            default_dir,
            "Data Package Files (*.upkg);;All Files (*)"
        )

        if not file_path:
            return

        try:
            logger.info(f"正在加载数据包文件: {file_path}")

            # 加载数据包
            self.package = DataPackage.open(file_path)
            self.total_frames = self.package.get_total()

            if self.total_frames == 0:
                self.show_error("数据包中没有帧数据")
                return

            # 更新UI
            self.file_info_label.setText(f"文件: {Path(file_path).name} | 帧数: {self.total_frames}")
            self.progress_slider.setMaximum(self.total_frames - 1)
            self.set_controls_enabled(True)

            # 显示第一帧
            self.current_frame = 0
            self.display_current_frame()

            logger.info(f"成功加载数据包: {self.total_frames} 帧")

        except Exception as e:
            logger.error(f"加载数据包失败: {e}", exc_info=True)
            self.show_error(f"加载失败: {str(e)}")

    def display_current_frame(self):
        """显示当前帧"""
        if not self.package or self.current_frame >= self.total_frames:
            return

        try:
            # 获取帧数据
            timestamp, image, trace_data = self.package.get_frame(self.current_frame)

            # 显示图片
            self.display_image(image)

            # 显示trace数据
            self.display_trace(trace_data)

            # 更新帧信息
            self.frame_counter.setText(f"{self.current_frame + 1} / {self.total_frames}")
            self.progress_slider.blockSignals(True)
            self.progress_slider.setValue(self.current_frame)
            self.progress_slider.blockSignals(False)

            # 更新时间戳
            self.timestamp_label.setText(".3f")

        except Exception as e:
            logger.error(f"显示帧失败: {e}", exc_info=True)
            self.show_error(f"显示帧失败: {str(e)}")

    def display_image(self, image: np.ndarray):
        """显示图像"""
        try:
            # 根据图像类型转换
            if image.dtype != np.uint8:
                image = image.astype(np.uint8)

            # 处理不同格式的图像
            if len(image.shape) == 2:
                # NV12格式: (height * 3/2, width)
                # 需要转换为RGB显示
                if self.package and hasattr(self.package, 'width') and hasattr(self.package, 'height'):
                    total_height = self.package.height * 3 // 2
                    width = self.package.width
                    height = self.package.height

                    # 重塑为NV12格式
                    if image.shape[0] == total_height and image.shape[1] == width:
                        # 转换为YUV420格式用于OpenCV转换
                        yuv_image = image.reshape((int(height * 1.5), width))
                        # 转换为RGB
                        rgb_image = cv2.cvtColor(yuv_image, cv2.COLOR_YUV2RGB_NV12)
                    else:
                        # 如果形状不匹配，直接显示为灰度
                        rgb_image = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
                else:
                    # 没有尺寸信息，直接显示为灰度
                    rgb_image = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
            elif len(image.shape) == 3:
                if image.shape[2] == 3:
                    # RGB/BGR格式
                    rgb_image = image
                else:
                    # 其他3D格式，转为RGB
                    rgb_image = cv2.cvtColor(image[:, :, 0], cv2.COLOR_GRAY2RGB)
            else:
                # 其他格式，尝试直接转换为RGB
                try:
                    rgb_image = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
                except:
                    # 如果转换失败，使用原始数据的前3个通道或扩展单通道
                    if len(image.shape) == 3 and image.shape[2] >= 3:
                        rgb_image = image[:, :, :3]
                    else:
                        rgb_image = cv2.cvtColor(image.reshape(image.shape[0], -1)[:, :1], cv2.COLOR_GRAY2RGB)

            # 确保是RGB格式
            if len(rgb_image.shape) == 2:
                rgb_image = cv2.cvtColor(rgb_image, cv2.COLOR_GRAY2RGB)

            # 转换为QImage
            height, width, channel = rgb_image.shape
            bytes_per_line = channel * width
            q_image = QImage(rgb_image.data, width, height, bytes_per_line, QImage.Format.Format_RGB888)

            # 缩放到固定尺寸 (400x300)，保持宽高比
            pixmap = QPixmap.fromImage(q_image)
            scaled_pixmap = pixmap.scaled(
                400, 300,  # 固定尺寸
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )

            self.image_label.setPixmap(scaled_pixmap)

            # 更新帧信息
            self.frame_info_label.setText(f"图像尺寸: {width} x {height} | 类型: {rgb_image.dtype}")

        except Exception as e:
            logger.error(f"显示图像失败: {e}", exc_info=True)
            self.image_label.setText(f"图像显示失败:\n{str(e)}")
            self.frame_info_label.setText("")

    def display_trace(self, trace_data):
        """显示trace数据"""
        try:
            if trace_data is None:
                trace_data = {}

            # 格式化JSON显示
            formatted_json = json.dumps(trace_data, indent=2, ensure_ascii=False)

            # 添加一些统计信息
            stats = f"帧号: {self.current_frame}\n数据字段数: {len(trace_data)}\n\n"

            self.trace_text.setText(stats + formatted_json)

        except Exception as e:
            logger.error(f"显示trace数据失败: {e}", exc_info=True)
            self.trace_text.setText(f"Trace数据显示失败:\n{str(e)}")

    def on_prev_frame(self):
        """上一帧"""
        if self.current_frame > 0:
            self.current_frame -= 1
            self.display_current_frame()

    def on_next_frame(self):
        """下一帧"""
        if self.current_frame < self.total_frames - 1:
            self.current_frame += 1
            self.display_current_frame()

    def on_play_pause(self):
        """播放/暂停"""
        if self.is_playing:
            # 暂停
            self.play_timer.stop()
            self.btn_play.setText("▶")
            self.is_playing = False
        else:
            # 播放
            self.play_timer.start(100)  # 100ms per frame (10 FPS)
            self.btn_play.setText("⏸")
            self.is_playing = True

    def on_slider_changed(self, value):
        """进度条改变"""
        if self.current_frame != value:
            self.current_frame = value
            self.display_current_frame()

    def show_error(self, message: str):
        """显示错误消息"""
        self.image_label.setText(f"错误:\n{message}")
        self.trace_text.setText(f"错误:\n{message}")

    def closeEvent(self, event):
        """窗口关闭事件"""
        if self.play_timer.isActive():
            self.play_timer.stop()
        event.accept()


def main():
    """主函数"""
    app = QApplication(sys.argv)
    app.setStyle('Fusion')  # 使用Fusion样式，确保跨平台一致性

    # 创建并显示主窗口
    window = ReviewApp()
    window.show()

    # 运行应用程序
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
