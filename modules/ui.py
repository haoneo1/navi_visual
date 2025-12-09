import subprocess

from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, 
                           QHBoxLayout, QLabel, QPushButton, QFileDialog)
from PyQt6.QtGui import QImage, QPixmap, QPainter, QPen
from PyQt6.QtCore import Qt, QPoint, QRect, QTimer
from pathlib import Path
from .video_thread import VideoStreamThread, VideoFileThread
from .gl_widget import GLWidget
from .logger import get_logger
from .config import get_crop_region, save_crop_region, get_show_result, get_overlay_position, save_overlay_position

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
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter, "ROT")
    
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
        
        self.btn_mark.setStyleSheet(function_button_style)
        self.btn_record.setStyleSheet(function_button_style)
        self.btn_inference.setStyleSheet(function_button_style)
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
        
        # 视频显示区域（带覆盖层）
        video_container = QWidget()
        video_container.setStyleSheet("background-color: #000;")
        video_layout = QVBoxLayout(video_container)
        video_layout.setContentsMargins(0, 0, 0, 0)
        
        self.video_label = DrawableVideoLabel('Waiting HDMI...')
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setStyleSheet("background-color: #000; color: white; font-size: 16px;")
        video_layout.addWidget(self.video_label)
        
        # 创建可移动、可调整大小的覆盖层（作为视频容器的子窗口）
        self.overlay = ResizableOverlay(video_container)
        self.overlay.raise_()  # 确保覆盖层在视频上方
        
        # 保存video_container引用，用于计算右上角位置
        self.video_container = video_container
        
        # 设置覆盖层初始大小（适合3D渲染，位置将在showEvent中设置为右上角）
        self.overlay.setGeometry(0, 0, 400, 400)
        
        # 创建主布局
        overlay_layout = QVBoxLayout(self.overlay)
        overlay_layout.setContentsMargins(0, 0, 0, 0)
        overlay_layout.setSpacing(0)
        
        # 创建标题栏
        self.title_bar = TitleBar(self.overlay)
        overlay_layout.addWidget(self.title_bar)
        
        # 创建3D渲染部件（放在悬浮窗口中）
        self.gl_widget = GLWidget(self.overlay)
        self.gl_widget.setMinimumSize(300, 300)
        overlay_layout.addWidget(self.gl_widget)
        
        # 保存引用以便调整大小时更新
        self.overlay.gl_widget = self.gl_widget
        
        if get_show_result():
            # 创建旋转矩阵显示标签（叠加在3D渲染上方）
            self.rotation_matrix_label = QLabel("[--, --, --]\n[--, --, --]\n[--, --, --]")
            self.rotation_matrix_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            self.rotation_matrix_label.setStyleSheet("color: #00ff00; background-color: rgba(0, 0, 0, 150); padding: 5px; font-family: monospace; font-size: 11px; font-weight: bold;")
            self.rotation_matrix_label.setWordWrap(True)
            self.rotation_matrix_label.setParent(self.overlay)
            self.rotation_matrix_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)  # 允许鼠标事件穿透
        
        right_layout.addWidget(video_container)
       
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
        if hasattr(self, 'overlay'):
            # 先显示覆盖层
            self.overlay.show()
            self.overlay.raise_()
            
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
                overlay_rect = self.overlay.rect()
                self.rotation_matrix_label.setGeometry(
                    5,
                    self.title_bar_h + 5,
                    self.matrix_label_w,
                    self.matrix_label_h
                )
    
    def _restore_overlay_position(self):
        """恢复悬浮窗口位置（延迟调用，确保窗口完全显示）"""
        if not hasattr(self, 'overlay') or not hasattr(self, 'video_container'):
            return
        
        if self._overlay_position_restored:
            return
        
        self._overlay_position_restored = True
        
        # 尝试从配置读取悬浮窗位置
        overlay_pos = get_overlay_position()
        if overlay_pos and self.video_container:
            # 使用rect()获取容器大小（overlay是video_container的子窗口，坐标相对于父容器）
            container_rect = self.video_container.rect()
            if container_rect.width() > 0 and container_rect.height() > 0:
                x, y, width, height = overlay_pos
                # 确保位置在容器范围内
                x = max(0, min(x, container_rect.width() - width))
                y = max(0, min(y, container_rect.height() - height))
                # 确保大小合理
                width = max(200, min(width, container_rect.width()))
                height = max(200, min(height, container_rect.height()))
                self.overlay.setGeometry(x, y, width, height)
                logger.info(f"恢复悬浮窗口位置: x={x}, y={y}, width={width}, height={height}, 容器大小: {container_rect.width()}x{container_rect.height()}")
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
        if not hasattr(self, 'overlay') or not hasattr(self, 'video_container'):
            return
        
        # 使用rect()获取容器大小（overlay是video_container的子窗口，坐标相对于父容器）
        container_rect = self.video_container.rect()
        if container_rect.width() > 0 and container_rect.height() > 0:
            overlay_width = 400
            overlay_height = 400
            margin = 5  # 边距
            x = container_rect.width() - overlay_width - margin
            y = margin
            self.overlay.setGeometry(x, y, overlay_width, overlay_height)
            logger.info(f"设置默认悬浮窗口位置: x={x}, y={y}, width={overlay_width}, height={overlay_height}, 容器大小: {container_rect.width()}x{container_rect.height()}")
        else:
            # 容器大小无效，延迟重试
            logger.warning(f"容器大小无效，延迟重试设置默认位置: {container_rect.width()}x{container_rect.height()}")
            QTimer.singleShot(100, self._set_default_overlay_position)
            # 容器大小无效，延迟重试
            logger.warning(f"容器大小无效，延迟重试设置默认位置: {container_rect.width()}x{container_rect.height()}")
            QTimer.singleShot(100, self._set_default_overlay_position)
    
    def _validate_overlay_position(self):
        """验证并修正悬浮窗口位置（确保在容器范围内）"""
        if not hasattr(self, 'overlay') or not hasattr(self, 'video_container'):
            return
        
        video_container = self.video_label.parent() if hasattr(self, 'video_label') else None
        if not video_container:
            return
        
        overlay_rect = self.overlay.geometry()
        container_rect = video_container.geometry()
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
            self.overlay.move(new_x, new_y)
            # 保存修正后的位置
            try:
                save_overlay_position(new_x, new_y, overlay_rect.width(), overlay_rect.height())
                logger.info(f"修正悬浮窗口位置: x={new_x}, y={new_y}")
            except Exception as e:
                logger.warning(f"保存悬浮窗口位置失败: {e}")
    
    def update_video_frame(self, frame):
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
        # TODO: 实现记录功能
    
    def on_inference_clicked(self):
        """推理按钮点击事件"""
        logger.info("用户点击了推理按钮")
        # TODO: 实现推理功能
    
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
        if hasattr(self, 'overlay') and self.overlay.isVisible():
            # 更新旋转矩阵标签位置（左上角）
            if hasattr(self, 'rotation_matrix_label'):
                self.rotation_matrix_label.setGeometry(
                    5, self.title_bar_h + 5,
                    self.matrix_label_w, self.matrix_label_h
                )
    
    def resizeEvent(self, event):
        """窗口大小改变时，调整覆盖层位置"""
        super().resizeEvent(event)
        # 如果位置还没有恢复，尝试恢复
        if hasattr(self, 'overlay') and hasattr(self, '_overlay_position_restored'):
            if not self._overlay_position_restored:
                QTimer.singleShot(50, self._restore_overlay_position)
        
        # 确保覆盖层在视频容器内
        if hasattr(self, 'overlay') and self.overlay.isVisible():
            video_container = self.video_label.parent()
            if video_container:
                overlay_rect = self.overlay.geometry()
                container_rect = video_container.geometry()
                position_changed = False
                # 如果覆盖层超出容器，调整位置
                if overlay_rect.right() > container_rect.right():
                    new_x = container_rect.right() - overlay_rect.width()
                    self.overlay.move(new_x, overlay_rect.top())
                    position_changed = True
                if overlay_rect.bottom() > container_rect.bottom():
                    new_y = container_rect.bottom() - overlay_rect.height()
                    self.overlay.move(overlay_rect.left(), new_y)
                    position_changed = True
                # 如果位置被调整，保存新位置
                if position_changed:
                    try:
                        x = self.overlay.x()
                        y = self.overlay.y()
                        width = self.overlay.width()
                        height = self.overlay.height()
                        save_overlay_position(x, y, width, height)
                        logger.info(f"窗口大小改变，调整并保存悬浮窗口位置: x={x}, y={y}, width={width}, height={height}")
                    except Exception as e:
                        logger.warning(f"保存悬浮窗口位置失败: {e}")
            # 更新标签位置
            self.update_overlay_labels()

