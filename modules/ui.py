import subprocess

from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout,
                           QHBoxLayout, QLabel, QPushButton, QFileDialog)
from PyQt6.QtGui import QImage, QPixmap, QPainter, QPen
from PyQt6.QtCore import Qt, QPoint, QRect, QTimer
from pathlib import Path
from .video_thread import VideoStreamThread, VideoFileThread
from .gl_widget import GLWidget
from .logger import get_logger
from .config import get_crop_region, save_crop_region, get_show_result, get_overlay_position, save_overlay_position, get_save_root, get_frame_width, get_frame_height, get_fps
from .data_package import DataPackage
import requests
import time
import threading
from datetime import datetime

logger = get_logger()


class DrawableVideoLabel(QLabel):
    """可绘制矩形的视频标签"""
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.drawing = False
        self.start_point = QPoint()
        self.end_point = QPoint()
        self.rect = None
        self.original_pixmap = None
    
    def setPixmap(self, pixmap):
        """保存原始pixmap并显示"""
        if isinstance(pixmap, QPixmap):
            self.original_pixmap = pixmap
            super().setPixmap(pixmap)
    
    def start_drawing(self):
        """开始绘制模式"""
        self.drawing = True
        self.rect = None
        self.update()
    
    def stop_drawing(self):
        """停止绘制模式"""
        self.drawing = False
    
    def get_rect(self):
        """获取绘制的矩形（相对于视频标签的坐标）"""
        return self.rect
    
    def mousePressEvent(self, event):
        if self.drawing and event.button() == Qt.MouseButton.LeftButton:
            self.start_point = event.pos()
            self.end_point = event.pos()
            self.rect = None
    
    def mouseMoveEvent(self, event):
        if self.drawing and event.buttons() & Qt.MouseButton.LeftButton:
            self.end_point = event.pos()
            self.update()
    
    def mouseReleaseEvent(self, event):
        if self.drawing and event.button() == Qt.MouseButton.LeftButton:
            self.end_point = event.pos()
            # 规范化矩形（确保左上角和右下角正确）
            self.rect = QRect(self.start_point, self.end_point).normalized()
            self.update()
    
    def paintEvent(self, event):
        """绘制视频和矩形"""
        super().paintEvent(event)
        
        if self.drawing and self.rect:
            painter = QPainter(self)
            painter.setPen(QPen(Qt.GlobalColor.red, 2))
            painter.drawRect(self.rect)

class TitleBar(QWidget):
    """标题栏 - 用于拖动窗口"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(30)
        self.setStyleSheet("background-color: #2a2a2a; color: white; font-size: 14px; font-weight: bold; padding: 1px;")
        self.dragging = False
        self.drag_offset = QPoint()
        # allow custom title text
        self._title_text = "ROT"
    
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = True
            overlay = self.parent()
            if overlay:
                self.drag_offset = self.pos() + event.pos()
    
    def mouseMoveEvent(self, event):
        if self.dragging:
            overlay = self.parent()
            if overlay and overlay.parent():
                new_global_pos = event.globalPosition().toPoint() - self.drag_offset
                parent_container = overlay.parent()
                new_local_pos = new_global_pos - parent_container.mapToGlobal(QPoint(0, 0))
                
                parent_rect = parent_container.rect()
                new_local_pos.setX(max(0, min(new_local_pos.x(), parent_rect.right() - overlay.width())))
                new_local_pos.setY(max(0, min(new_local_pos.y(), parent_rect.bottom() - overlay.height())))
                
                overlay.move(new_local_pos)
    
    def mouseReleaseEvent(self, event):
        self.dragging = False
        # 拖动结束时保存位置
        if event.button() == Qt.MouseButton.LeftButton:
            overlay = self.parent()
            if overlay:
                self._save_overlay_position(overlay)
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter, self._title_text)
    
    def _save_overlay_position(self, overlay):
        """保存悬浮窗口位置到配置文件"""
        try:
            x = overlay.x()
            y = overlay.y()
            width = overlay.width()
            height = overlay.height()
            save_overlay_position(x, y, width, height)
            logger.debug(f"保存悬浮窗口位置: x={x}, y={y}, width={width}, height={height}")
        except Exception as e:
            logger.warning(f"保存悬浮窗口位置失败: {e}")


class ResizableOverlay(QWidget):
    """可移动、可调整大小的覆盖层"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.resizing = False
        self.resize_handle_size = 15
        self.resize_start_pos = QPoint()
        self.resize_start_size = None
        self.is_transparent = False
        
        self.setGeometry(0, 0, 400, 400)
        # self.setStyleSheet("background-color: rgba(34, 34, 34, 200);")
        self.setWindowOpacity(1.0)
        
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            rect = self.rect()
            corner_rect = QRect(
                rect.width() - self.resize_handle_size,
                rect.height() - self.resize_handle_size,
                self.resize_handle_size,
                self.resize_handle_size
            )
            if corner_rect.contains(event.pos()):
                self.resizing = True
                self.resize_start_pos = event.pos()
                self.resize_start_size = self.size()
    
    def mouseMoveEvent(self, event):
        if self.resizing:
            delta = event.pos() - self.resize_start_pos
            new_width = max(200, self.resize_start_size.width() + delta.x())
            new_height = max(200, self.resize_start_size.height() + delta.y())
            
            if self.parent():
                parent_rect = self.parent().rect()
                new_width = min(new_width, parent_rect.width() - self.x())
                new_height = min(new_height, parent_rect.height() - self.y())
            
            self.resize(new_width, new_height)
            
            if hasattr(self, 'gl_widget') and self.gl_widget:
                title_bar_h = 30
                new_gl_height = max(200, new_height - title_bar_h)
                self.gl_widget.setMinimumSize(new_width, new_gl_height)
                self.gl_widget.resize(new_width, new_gl_height)
            
            # 通知父窗口更新标签位置
            if self.parent() and hasattr(self.parent(), 'parent'):
                main_window = self.parent().parent()
                if main_window and hasattr(main_window, 'update_overlay_labels'):
                    main_window.update_overlay_labels()
    
    def mouseReleaseEvent(self, event):
        if self.resizing:
            self.resizing = False
            # 调整大小结束时保存位置
            self._save_overlay_position()
        else:
            self.resizing = False
    
    def _save_overlay_position(self):
        """保存悬浮窗口位置到配置文件"""
        try:
            x = self.x()
            y = self.y()
            width = self.width()
            height = self.height()
            save_overlay_position(x, y, width, height)
            logger.debug(f"保存悬浮窗口位置: x={x}, y={y}, width={width}, height={height}")
        except Exception as e:
            logger.warning(f"保存悬浮窗口位置失败: {e}")
    
    def mouseDoubleClickEvent(self, event):
        """双击切换半透明状态"""
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_transparent = not self.is_transparent
            self.setWindowOpacity(0.5 if self.is_transparent else 1.0)
    
    def resizeEvent(self, event):
        """调整大小时更新标签位置"""
        super().resizeEvent(event)
        # 通过父窗口更新标签位置
        if self.parent() and hasattr(self.parent(), 'parent'):
            main_window = self.parent().parent()
            if main_window and hasattr(main_window, 'update_overlay_labels'):
                main_window.update_overlay_labels()
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        rect = self.rect()
        painter.setPen(QPen(Qt.GlobalColor.cyan, 2))
        painter.setBrush(Qt.GlobalColor.transparent)
        painter.drawRect(rect.adjusted(1, 1, -1, -1))
        
        handle_rect = QRect(
            rect.width() - self.resize_handle_size,
            rect.height() - self.resize_handle_size,
            self.resize_handle_size,
            self.resize_handle_size
        )
        painter.fillRect(handle_rect, Qt.GlobalColor.cyan)

class MainWindow(QMainWindow):
    """主窗口 - 两列布局"""
    def __init__(self, video_url="http://192.168.0.39:8080/raw", full_screen=True):
        super().__init__()
        self.video_url = video_url
        self.full_screen = full_screen
        # 先初始化标志，避免在init_ui中访问时出错
        self._overlay_position_restored = False  # 标记是否已恢复悬浮窗口位置
        self.matrix_label_w = 180
        self.matrix_label_h = 60
        self.title_bar_h = 30
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle('Ultrasound Navi App')
        self.setGeometry(100, 100, 1400, 700)

        # 添加状态栏用于显示视频流状态
        self.statusBar().showMessage("就绪")
        
        # 主布局容器
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # ========== 左列：按钮区域 ==========
        left_panel = QWidget()
        left_panel.setMaximumWidth(150)
        left_panel.setMinimumWidth(150)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setSpacing(10)
        left_layout.setContentsMargins(10, 10, 10, 10)

        # 顶部 Logo
        logo_label = QLabel()
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_label.setStyleSheet("padding: 5px;")
        logo_path = Path(__file__).parent.parent / "images" / "logo.png"
        if logo_path.exists():
            max_width = 100
            pixmap = QPixmap(str(logo_path))
            if not pixmap.isNull():
                pixmap = pixmap.scaledToWidth(max_width, Qt.TransformationMode.SmoothTransformation)
                logo_label.setPixmap(pixmap)
        else:
            logger.warning(f"Logo 文件不存在: {logo_path}")
        left_layout.addWidget(logo_label, 0, Qt.AlignmentFlag.AlignCenter)
        
        
        # 上方：心脏位置按钮
        position_label = QLabel('Cardiac')
        position_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        position_label.setStyleSheet("font-size: 16px; font-weight: bold; padding: 8px; color: #FFF;")
        left_layout.addWidget(position_label)
        
        self.btn_pos1 = QPushButton("4AC")
        
        # 设置按钮样式
        button_style = """
            QPushButton {
                padding: 15px;
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
        """
        
        self.btn_pos1.setStyleSheet(button_style)
        
        left_layout.addWidget(self.btn_pos1)
        
        # 添加弹性空间
        left_layout.addStretch()
        
        # 下方：功能按钮
        function_label = QLabel('Controls')
        function_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        function_label.setStyleSheet("font-size: 16px; font-weight: bold; padding: 8px; color: #FFF;")
        left_layout.addWidget(function_label)
        
        # self.btn_open = QPushButton("Open")
        self.btn_mark = QPushButton("Select")
        self.btn_record = QPushButton("Record")
        self.btn_inference = QPushButton("Inference")
        self.btn_exit = QPushButton("Exit")
        self.btn_shutdown = QPushButton("Shutdown")
        
        # 功能按钮样式
        function_button_style = """
            QPushButton {
                padding: 15px;
                font-size: 14px;
                background-color: #50c878;
                color: white;
                border: none;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #45b369;
            }
            QPushButton:pressed {
                background-color: #3a9d5a;
            }
        """
        # 激活（橘色）样式，用于正在运行的模式按钮（record 或 inference）
        active_button_style = """
            QPushButton {
                padding: 15px;
                font-size: 14px;
                background-color: #ff9900;
                color: white;
                border: none;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #e68a00;
            }
            QPushButton:pressed {
                background-color: #cc7a00;
            }
        """
        # 保存样式到实例以便其它方法修改按钮状态时使用
        self._function_button_style = function_button_style
        self._active_button_style = active_button_style
        
        exit_button_style = """
            QPushButton {
                padding: 15px;
                font-size: 14px;
                background-color: #e74c3c;
                color: white;
                border: none;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #c0392b;
            }
            QPushButton:pressed {
                background-color: #a93226;
            }
        """
        
        self.btn_mark.setStyleSheet(self._function_button_style)
        self.btn_record.setStyleSheet(self._function_button_style)
        # inference按钮暂时设置为普通样式，稍后会根据状态调整
        self.btn_inference.setStyleSheet(self._function_button_style)
        self.btn_exit.setStyleSheet(exit_button_style)
        self.btn_shutdown.setStyleSheet(exit_button_style)
        # self.btn_open.setStyleSheet(function_button_style)
        
        # left_layout.addWidget(self.btn_open)
        left_layout.addWidget(self.btn_mark)
        left_layout.addWidget(self.btn_record)
        left_layout.addWidget(self.btn_inference)
        left_layout.addWidget(self.btn_exit)
        left_layout.addWidget(self.btn_shutdown)
        
        # ========== 右列：影像显示区域 ==========
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(5)
        
        # ROT（3D渲染）显示区域作为主区域，视频作为悬浮小窗
        rot_container = QWidget()
        rot_container.setStyleSheet("background-color: #000;")
        rot_layout = QVBoxLayout(rot_container)
        rot_layout.setContentsMargins(0, 0, 0, 0)
        
        # 创建3D渲染部件（放在主区域中）
        self.gl_widget = GLWidget(rot_container)
        self.gl_widget.setMinimumSize(300, 300)
        rot_layout.addWidget(self.gl_widget)
        
        # 创建可移动、可调整大小的视频悬浮窗口（作为rot_container的子窗口）
        self.video_overlay = ResizableOverlay(rot_container)
        self.video_overlay.raise_()
        self.video_overlay.setGeometry(10, 10, 480, 360)

        # 创建主布局（video overlay）内部结构： title + video label
        video_overlay_layout = QVBoxLayout(self.video_overlay)
        video_overlay_layout.setContentsMargins(0, 0, 0, 0)
        video_overlay_layout.setSpacing(0)

        # 创建标题栏（显示为 Video）
        self.title_bar = TitleBar(self.video_overlay)
        self.title_bar._title_text = "Video"
        video_overlay_layout.addWidget(self.title_bar)

        # 视频标签放在悬浮窗口中
        self.video_label = DrawableVideoLabel('Waiting HDMI...')
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setStyleSheet("background-color: #000; color: white; font-size: 16px;")
        video_overlay_layout.addWidget(self.video_label)

        # 保存rot_container引用用于位置计算
        self.rot_container = rot_container

        # 旋转矩阵标签放在rot_container上（覆盖在GLWidget上方）
        if get_show_result():
            self.rotation_matrix_label = QLabel("[--, --, --]\n[--, --, --]\n[--, --, --]")
            self.rotation_matrix_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            self.rotation_matrix_label.setStyleSheet("color: #00ff00; background-color: rgba(0, 0, 0, 150); padding: 5px; font-family: monospace; font-size: 11px; font-weight: bold;")
            self.rotation_matrix_label.setWordWrap(True)
            self.rotation_matrix_label.setParent(self.rot_container)
            self.rotation_matrix_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        right_layout.addWidget(rot_container)
       
        # 添加到主布局
        main_layout.addWidget(left_panel, 0)  # 左列固定宽度
        main_layout.addWidget(right_panel, 1)  # 右列占据剩余空间
        
        # 绑定按钮事件
        self.btn_pos1.clicked.connect(lambda: self.gl_widget.set_probe_t_position(0))
        
        self.btn_mark.clicked.connect(self.on_mark_clicked)
        self.btn_record.clicked.connect(self.on_record_clicked)
        self.btn_inference.clicked.connect(self.on_inference_clicked)
        self.btn_exit.clicked.connect(self.close)
        self.btn_shutdown.clicked.connect(self.on_shutdown_clicked)
        # self.btn_open.clicked.connect(self.on_open_clicked)
        
        # 标记模式状态
        self.marking_mode = False
        
        # 当前数据源（hdmi/file）
        self.current_source = "hdmi"
        self.video_thread = None
        self.start_hdmi_thread()
        # 默认开启 inference 模式（程序启动时为 inference 模式）
        self._is_inference = True
        self._is_recording = False
        # 确保按钮状态正确显示
        self._set_button_active(self.btn_inference, True)
        self._set_button_active(self.btn_record, False)
        
        # 初始化帧尺寸变量（用于坐标转换）
        self.original_frame_size = (1920, 1088)  # 默认值
        self.scaled_pixmap_size = (1920, 1088)  # 默认值
        
        # 显示覆盖层（需要在窗口显示后）
        if self.full_screen:
            logger.info("以全屏模式显示主窗口")
            self.showFullScreen()
        else:
            logger.info("以窗口模式显示主窗口")
            self.resize(1200, 800)
    
    def showEvent(self, event):
        """窗口显示时，显示覆盖层"""
        super().showEvent(event)
        if hasattr(self, 'rot_container'):
            # 先显示视频悬浮层
            if hasattr(self, 'video_overlay'):
                self.video_overlay.show()
                self.video_overlay.raise_()
            
            # 使用QTimer延迟恢复位置，确保窗口完全显示后再恢复
            if not self._overlay_position_restored:
                QTimer.singleShot(100, self._restore_overlay_position)
            else:
                # 如果已经恢复过，确保位置仍然有效
                QTimer.singleShot(50, self._validate_overlay_position)
            
            # 确保旋转矩阵标签在3D渲染上方
            if hasattr(self, 'rotation_matrix_label') and get_show_result():
                self.rotation_matrix_label.show()
                self.rotation_matrix_label.raise_()
                # 设置旋转矩阵标签位置（左上角）
                # rotation label anchored to rot_container
                overlay_rect = self.rot_container.rect()
                self.rotation_matrix_label.setGeometry(
                    5,
                    self.title_bar_h + 5,
                    self.matrix_label_w,
                    self.matrix_label_h
                )
    
    def _restore_overlay_position(self):
        """恢复悬浮窗口位置（延迟调用，确保窗口完全显示）"""
        if not hasattr(self, 'video_overlay') or not hasattr(self, 'rot_container'):
            return
        
        if self._overlay_position_restored:
            return
        
        self._overlay_position_restored = True
        
        # 尝试从配置读取悬浮窗位置
        overlay_pos = get_overlay_position()
        if overlay_pos and self.rot_container:
            # 使用rect()获取容器大小（video_overlay是rot_container的子窗口，坐标相对于父容器）
            container_rect = self.rot_container.rect()
            if container_rect.width() > 0 and container_rect.height() > 0:
                x, y, width, height = overlay_pos
                # 确保位置在容器范围内
                x = max(0, min(x, container_rect.width() - width))
                y = max(0, min(y, container_rect.height() - height))
                # 确保大小合理
                width = max(200, min(width, container_rect.width()))
                height = max(200, min(height, container_rect.height()))
                self.video_overlay.setGeometry(x, y, width, height)
                logger.info(f"恢复视频悬浮窗口位置: x={x}, y={y}, width={width}, height={height}, 容器大小: {container_rect.width()}x{container_rect.height()}")
            else:
                # 容器大小无效，延迟重试
                logger.warning(f"容器大小无效，延迟重试恢复位置: {container_rect.width()}x{container_rect.height()}")
                self._overlay_position_restored = False  # 重置标志，允许重试
                QTimer.singleShot(100, self._restore_overlay_position)
        else:
            # 没有保存的位置，使用默认位置
            self._set_default_overlay_position()
    
    def _set_default_overlay_position(self):
        """设置默认悬浮窗口位置（右上角）"""
        if not hasattr(self, 'video_overlay') or not hasattr(self, 'rot_container'):
            return
        
        # 使用rect()获取容器大小（video_overlay是rot_container的子窗口，坐标相对于父容器）
        container_rect = self.rot_container.rect()
        if container_rect.width() > 0 and container_rect.height() > 0:
            overlay_width = 400
            overlay_height = 400
            margin = 5  # 边距
            x = container_rect.width() - overlay_width - margin
            y = margin
            self.video_overlay.setGeometry(x, y, overlay_width, overlay_height)
            logger.info(f"设置默认视频悬浮窗口位置: x={x}, y={y}, width={overlay_width}, height={overlay_height}, 容器大小: {container_rect.width()}x{container_rect.height()}")
        else:
            # 容器大小无效，延迟重试
            logger.warning(f"容器大小无效，延迟重试设置默认位置: {container_rect.width()}x{container_rect.height()}")
            QTimer.singleShot(100, self._set_default_overlay_position)
            # 容器大小无效，延迟重试
            logger.warning(f"容器大小无效，延迟重试设置默认位置: {container_rect.width()}x{container_rect.height()}")
            QTimer.singleShot(100, self._set_default_overlay_position)
    
    def _validate_overlay_position(self):
        """验证并修正悬浮窗口位置（确保在容器范围内）"""
        if not hasattr(self, 'video_overlay') or not hasattr(self, 'rot_container'):
            return
        
        # container is rot_container
        if not hasattr(self, 'rot_container'):
            return
        overlay_rect = self.video_overlay.geometry()
        container_rect = self.rot_container.geometry()
        position_changed = False
        new_x, new_y = overlay_rect.x(), overlay_rect.y()
        
        # 检查并修正位置
        if overlay_rect.right() > container_rect.right():
            new_x = container_rect.right() - overlay_rect.width()
            position_changed = True
        if overlay_rect.bottom() > container_rect.bottom():
            new_y = container_rect.bottom() - overlay_rect.height()
            position_changed = True
        if overlay_rect.x() < 0:
            new_x = 0
            position_changed = True
        if overlay_rect.y() < 0:
            new_y = 0
            position_changed = True
        
        if position_changed:
            self.video_overlay.move(new_x, new_y)
            # 保存修正后的位置
            try:
                save_overlay_position(new_x, new_y, overlay_rect.width(), overlay_rect.height())
                logger.info(f"修正视频悬浮窗口位置: x={new_x}, y={new_y}")
            except Exception as e:
                logger.warning(f"保存悬浮窗口位置失败: {e}")
    
    def update_video_frame(self, frame):
        # 检查是否应该显示视频帧（只有在inference或recording状态下才显示）
        should_display = getattr(self, '_is_inference', False) or getattr(self, '_is_recording', False)

        if should_display:
            height, width, channel = frame.shape
            bytes_per_line = channel * width
            q_image = QImage(frame.data, width, height, bytes_per_line, QImage.Format.Format_RGB888)
            pixmap = QPixmap.fromImage(q_image).scaled(
                self.video_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.video_label.setPixmap(pixmap)

            # 保存原始帧尺寸和缩放后的pixmap尺寸用于坐标转换
            self.original_frame_size = (width, height)
            self.scaled_pixmap_size = (pixmap.width(), pixmap.height())
        else:
            # 如果不在inference或recording状态，显示停止提示
            self.video_label.setText("视频已停止")
            self.video_label.setStyleSheet("background-color: #000; color: #666; font-size: 14px;")

    def _set_button_active(self, btn, active: bool):
        """切换按钮到激活/非激活样式"""
        try:
            if active:
                btn.setStyleSheet(self._active_button_style)
            else:
                btn.setStyleSheet(self._function_button_style)
        except Exception:
            pass
    
    def update_processing_time(self, processing_time_ms):
        """更新处理时间显示（保留但不显示在悬浮窗口）"""
        pass  # 处理时间不再显示在悬浮窗口
    
    def update_rotation_matrix(self, rotation_matrix):
        """更新旋转矩阵显示"""
        if rotation_matrix is not None:
            # 更新标签显示
            if hasattr(self, 'rotation_matrix_label'):
                # 格式化旋转矩阵为字符串
                matrix_str = "旋转矩阵:\n"
                for i in range(3):
                    row = rotation_matrix[i]
                    matrix_str += f"[{row[0]:7.4f}, {row[1]:7.4f}, {row[2]:7.4f}]\n"
                self.rotation_matrix_label.setText(matrix_str.strip())
                self.rotation_matrix_label.raise_()
            
            # 更新3D渲染中的旋转矩阵，用于计算绿色圆锥位置
            if hasattr(self, 'gl_widget'):
                self.gl_widget.update_rotation_matrix(rotation_matrix)
    
    def _disconnect_video_signals(self, thread):
        """断开视频线程信号，避免重复连接"""
        if not thread:
            return
        try:
            thread.frame_updated.disconnect(self.update_video_frame)
        except Exception:
            pass
        try:
            thread.rotation_matrix_updated.disconnect(self.update_rotation_matrix)
        except Exception:
            pass
        try:
            thread.processing_time_updated.disconnect(self.update_processing_time)
        except Exception:
            pass
        if hasattr(thread, 'finished_playback'):
            try:
                thread.finished_playback.disconnect(self.on_file_finished)
            except Exception:
                pass
    
    def _connect_video_signals(self, thread):
        """连接视频线程信号"""
        thread.frame_updated.connect(self.update_video_frame)
        thread.rotation_matrix_updated.connect(self.update_rotation_matrix)
        thread.processing_time_updated.connect(self.update_processing_time)
        if hasattr(thread, 'finished_playback'):
            thread.finished_playback.connect(self.on_file_finished)
        # 连接数据包保存完成信号（如果线程支持）
        try:
            if hasattr(thread, 'package_saved'):
                thread.package_saved.connect(self._on_package_saved)
        except Exception:
            pass
        # 连接线程保护信号
        try:
            if hasattr(thread, 'thread_error'):
                thread.thread_error.connect(self.on_video_thread_error)
            if hasattr(thread, 'thread_recovered'):
                thread.thread_recovered.connect(self.on_video_thread_recovered)
        except Exception:
            pass
    
    def stop_video_thread(self):
        """停止当前视频线程"""
        if hasattr(self, 'video_thread') and self.video_thread:
            self._disconnect_video_signals(self.video_thread)
            try:
                self.video_thread.stop()
            except Exception:
                pass
            self.video_thread = None
    
    def start_hdmi_thread(self):
        """启动HDMI流线程"""
        self.stop_video_thread()
        logger.info("启动 HDMI 视频流线程")
        thread = VideoStreamThread(self.video_url)
        self._connect_video_signals(thread)
        self.video_thread = thread
        self.current_source = "hdmi"
        thread.start()
    
    def start_file_thread(self, file_path):
        """启动本地视频播放线程"""
        self.stop_video_thread()
        logger.info(f"启动本地视频播放: {file_path}")
        thread = VideoFileThread(file_path)
        self._connect_video_signals(thread)
        self.video_thread = thread
        self.current_source = "file"
        thread.start()
    
    def on_file_finished(self):
        """本地视频播放结束后恢复HDMI"""
        logger.info("本地视频播放结束，恢复HDMI流")
        if self.current_source == "file":
            self.start_hdmi_thread()
    
    def on_mark_clicked(self):
        """标记按钮点击事件"""
        if not self.marking_mode:
            # 进入标记模式
            self.marking_mode = True
            self.btn_mark.setText("Confirm")
            self.video_label.start_drawing()
            logger.info("进入标记模式，请在视频区域绘制矩形")
        else:
            # 确认并保存
            rect = self.video_label.get_rect()
            if rect:
                # 将QLabel中的坐标转换为原始视频帧的坐标
                label_width = self.video_label.width()
                label_height = self.video_label.height()
                pixmap_width, pixmap_height = self.scaled_pixmap_size
                original_width, original_height = self.original_frame_size
                
                # 计算pixmap在label中的位置（KeepAspectRatio居中显示）
                offset_x = (label_width - pixmap_width) / 2
                offset_y = (label_height - pixmap_height) / 2
                
                # 将label坐标转换为pixmap坐标
                pixmap_x = rect.x() - offset_x
                pixmap_y = rect.y() - offset_y
                pixmap_width_rect = rect.width()
                pixmap_height_rect = rect.height()
                
                # 转换为原始帧坐标
                frame_x = int(pixmap_x * original_width / pixmap_width)
                frame_y = int(pixmap_y * original_height / pixmap_height)
                frame_width = int(pixmap_width_rect * original_width / pixmap_width)
                frame_height = int(pixmap_height_rect * original_height / pixmap_height)
                
                # 确保坐标在有效范围内
                frame_x = max(0, min(frame_x, original_width - 1))
                frame_y = max(0, min(frame_y, original_height - 1))
                frame_width = max(1, min(frame_width, original_width - frame_x))
                frame_height = max(1, min(frame_height, original_height - frame_y))
                
                try:
                    save_crop_region(frame_x, frame_y, frame_width, frame_height)
                    logger.info(f"保存裁剪区域: x={frame_x}, y={frame_y}, width={frame_width}, height={frame_height}")
                except Exception as e:
                    logger.error(f"保存裁剪区域失败: {e}", exc_info=True)
            else:
                logger.warning("未绘制矩形区域")
            
            # 退出标记模式
            self.marking_mode = False
            self.btn_mark.setText("Select")
            self.video_label.stop_drawing()
    
    def on_record_clicked(self):
        """记录按钮点击事件"""
        logger.info("用户点击了记录按钮")

        # 切换录制状态：点击开始录制，再次点击停止并保存
        if not getattr(self, '_is_recording', False):
            # 开始录制
            self._is_recording = True
            self.btn_record.setText("Stop")
            # 录制与推理互斥：如果当前正在 inference，先禁用 inference，但保留视频流线程用于更新UI与录制
            if getattr(self, '_is_inference', False):
                try:
                    if self.video_thread:
                        self.video_thread.enable_analyzer(False)
                except Exception:
                    pass
                self._is_inference = False
                # 将 inference 按钮恢复为非激活样式
                self._set_button_active(self.btn_inference, False)
            # 将 record 按钮设为激活样式（橘色）
            self._set_button_active(self.btn_record, True)

            save_root = get_save_root()
            # Ensure directory exists
            try:
                Path(save_root).mkdir(parents=True, exist_ok=True)
            except Exception as e:
                logger.error(f"创建保存目录失败: {save_root}, {e}", exc_info=True)
                self._is_recording = False
                self.btn_record.setText("Record")
                return

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            save_path = str(Path(save_root) / f"{timestamp}.upkg")

            width = get_frame_width()
            height = get_frame_height()
            fps = get_fps()

            package = DataPackage(save_path, image_type='nv12', width=width, height=height, realtime=True)
            try:
                package.start_recording()
            except Exception as e:
                logger.error(f"启动数据包录制失败: {e}", exc_info=True)
                self._is_recording = False
                self.btn_record.setText("Record")
                return

            # 保存引用并通过 VideoStreamThread 写入（避免重复 HTTP 拉取且保证 UI 更新不丢帧）
            self._record_package = package
            try:
                if self.video_thread:
                    self.video_thread.start_recording_package(package)
                else:
                    # 没有视频线程时回退到旧逻辑（不推荐）
                    logger.warning("没有活动的视频线程，录制可能无法进行")
            except Exception as e:
                logger.error(f"开始写入数据包失败: {e}", exc_info=True)
                self._is_recording = False
                self._set_button_active(self.btn_record, False)
                self.btn_record.setText("Record")
                return
        else:
            # 停止录制：通知 VideoStreamThread 停止写入并异步保存包
            logger.info("停止录制请求")
            try:
                if self.video_thread:
                    self.video_thread.stop_recording_package()
            except Exception as e:
                logger.error(f"请求停止写入数据包失败: {e}", exc_info=True)
            # UI 先显示保存中状态，实际保存完成后由 package_saved 信号恢复按钮文本
            self.btn_record.setText("Saving...")
            self._is_recording = False
            self._set_button_active(self.btn_record, False)

            # 如果既没有在inference也没有在recording，清除视频显示
            if not getattr(self, '_is_inference', False) and not getattr(self, '_is_recording', False):
                if hasattr(self, 'video_label'):
                    self.video_label.setText("视频已停止")
                    self.video_label.setStyleSheet("background-color: #000; color: #666; font-size: 14px;")
    
    def on_inference_clicked(self):
        """推理按钮点击事件"""
        logger.info("用户点击了推理按钮")
        # 切换 inference 状态
        if not getattr(self, '_is_inference', False):
            # 要开启 inference：如果正在录制，先停止录制
            if getattr(self, '_is_recording', False):
                logger.info("开启推理前，先停止正在进行的录制")
                stop_event = getattr(self, '_record_stop_event', None)
                if stop_event:
                    stop_event.set()
                # 让记录线程处理保存（不阻塞）
                self._is_recording = False
                self._set_button_active(self.btn_record, False)

            # 启动 HDMI 线程（包含 AI 分析）
            try:
                self.start_hdmi_thread()
                self._is_inference = True
                self._set_button_active(self.btn_inference, True)
                # 开启inference时显示红色矩形
                if hasattr(self, 'gl_widget'):
                    self.gl_widget.set_show_red_rectangle(True)
            except Exception as e:
                logger.error(f"启动 inference 失败: {e}", exc_info=True)
        else:
            # 关闭 inference：停止视频线程（包含 AI）
            try:
                self.stop_video_thread()
                self._is_inference = False
                self._set_button_active(self.btn_inference, False)
                # 关闭inference时隐藏红色矩形
                if hasattr(self, 'gl_widget'):
                    self.gl_widget.set_show_red_rectangle(False)
                # 清除视频显示
                if hasattr(self, 'video_label'):
                    self.video_label.setText("视频已停止")
                    self.video_label.setStyleSheet("background-color: #000; color: #666; font-size: 14px;")
            except Exception as e:
                logger.error(f"停止 inference 失败: {e}", exc_info=True)

    def _on_package_saved(self, path: str):
        """DataPackage 保存完成回调（在视频线程中发出）"""
        logger.info(f"数据包保存完成: {path}")
        try:
            QTimer.singleShot(0, lambda: self.btn_record.setText("Record"))
        except Exception:
            pass

    def on_video_thread_error(self, error_msg: str):
        """视频线程错误处理"""
        logger.error(f"视频线程错误: {error_msg}")
        # 在状态栏显示错误信息（如果有状态栏的话）
        try:
            if hasattr(self, 'statusBar'):
                self.statusBar().showMessage(f"视频流错误: {error_msg}", 5000)  # 显示5秒
        except Exception:
            pass

        # 可以在这里添加更多用户通知，比如弹窗或声音提示
        # 例如：QMessageBox.warning(self, "视频流错误", error_msg)

    def on_video_thread_recovered(self):
        """视频线程恢复处理"""
        logger.info("视频线程已恢复正常")
        try:
            if hasattr(self, 'statusBar'):
                self.statusBar().showMessage("视频流已恢复正常", 3000)  # 显示3秒
        except Exception:
            pass

    def on_open_clicked(self):
        """打开本地MP4文件并播放"""
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 MP4 文件",
            "",
            "Video Files (*.mp4);;All Files (*)"
        )
        if not file_path:
            logger.info("用户取消选择视频文件")
            return
        logger.info(f"用户选择视频文件: {file_path}")
        self.start_file_thread(file_path)
        
    def on_shutdown_clicked(self):
        """关机按钮点击事件"""
        logger.info("用户点击了关机按钮，执行系统关机命令")
        try:
            # 使用系统关机命令，可能需要管理员权限
            subprocess.Popen(["/sbin/shutdown", "-h", "now"])
        except Exception as e:
            logger.error(f"执行关机命令失败: {e}", exc_info=True)
        
    def closeEvent(self, event):
        logger.info("主窗口关闭事件触发，正在停止所有线程...")
        self.stop_video_thread()
        logger.info("所有线程已停止")
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            if self.isFullScreen():
                self.showNormal()
            else:
                self.close()
    
    def update_overlay_labels(self):
        """更新悬浮窗内标签位置"""
        # update rotation label anchored to rot_container
        if hasattr(self, 'rot_container') and getattr(self, 'rotation_matrix_label', None) is not None:
            self.rotation_matrix_label.setGeometry(
                5, self.title_bar_h + 5,
                self.matrix_label_w, self.matrix_label_h
            )
    
    def resizeEvent(self, event):
        """窗口大小改变时，调整覆盖层位置"""
        super().resizeEvent(event)
        # 如果位置还没有恢复，尝试恢复
        if hasattr(self, 'video_overlay') and hasattr(self, '_overlay_position_restored'):
            if not self._overlay_position_restored:
                QTimer.singleShot(50, self._restore_overlay_position)
        
        # 确保覆盖层在视频容器内
        # ensure video_overlay remains within rot_container
        if hasattr(self, 'video_overlay') and self.video_overlay.isVisible() and hasattr(self, 'rot_container'):
            overlay_rect = self.video_overlay.geometry()
            container_rect = self.rot_container.geometry()
            position_changed = False
            # 如果覆盖层超出容器，调整位置
            if overlay_rect.right() > container_rect.right():
                new_x = container_rect.right() - overlay_rect.width()
                self.video_overlay.move(new_x, overlay_rect.top())
                position_changed = True
            if overlay_rect.bottom() > container_rect.bottom():
                new_y = container_rect.bottom() - overlay_rect.height()
                self.video_overlay.move(overlay_rect.left(), new_y)
                position_changed = True
            # 如果位置被调整，保存新位置
            if position_changed:
                try:
                    x = self.video_overlay.x()
                    y = self.video_overlay.y()
                    width = self.video_overlay.width()
                    height = self.video_overlay.height()
                    save_overlay_position(x, y, width, height)
                    logger.info(f"窗口大小改变，调整并保存视频悬浮窗口位置: x={x}, y={y}, width={width}, height={height}")
                except Exception as e:
                    logger.warning(f"保存悬浮窗口位置失败: {e}")
            # 更新标签位置
            self.update_overlay_labels()

