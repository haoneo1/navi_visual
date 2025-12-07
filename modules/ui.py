from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, 
                           QHBoxLayout, QLabel, QPushButton)
from PyQt6.QtGui import QImage, QPixmap, QPainter, QPen
from PyQt6.QtCore import Qt, QPoint, QRect
from .video_thread import VideoStreamThread
from .gl_widget import GLWidget
from .logger import get_logger
from .config import get_crop_region, save_crop_region

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
        self.setStyleSheet("background-color: #2a2a2a; color: white; font-size: 14px; font-weight: bold; padding: 5px;")
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
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "预测")


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
        self.setStyleSheet("background-color: rgba(34, 34, 34, 200);")
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
                title_bar_height = 30
                new_gl_height = max(200, new_height - title_bar_height)
                self.gl_widget.setMinimumSize(new_width, new_gl_height)
                self.gl_widget.resize(new_width, new_gl_height)
            
            # 通知父窗口更新标签位置
            if self.parent() and hasattr(self.parent(), 'parent'):
                main_window = self.parent().parent()
                if main_window and hasattr(main_window, 'update_overlay_labels'):
                    main_window.update_overlay_labels()
    
    def mouseReleaseEvent(self, event):
        self.resizing = False
    
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
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle('心脏超声导航工具')
        self.setGeometry(100, 100, 1400, 700)
        
        # 主布局容器
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # ========== 左列：按钮区域 ==========
        left_panel = QWidget()
        left_panel.setMaximumWidth(200)
        left_panel.setMinimumWidth(180)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setSpacing(15)
        left_layout.setContentsMargins(10, 10, 10, 10)
        
        # 上方：心脏位置按钮
        position_label = QLabel('心脏位置')
        position_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        position_label.setStyleSheet("font-size: 16px; font-weight: bold; padding: 8px; color: #333;")
        left_layout.addWidget(position_label)
        
        self.btn_pos1 = QPushButton("标准4AC")
        
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
        function_label = QLabel('功能')
        function_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        function_label.setStyleSheet("font-size: 16px; font-weight: bold; padding: 8px; color: #333;")
        left_layout.addWidget(function_label)
        
        self.btn_mark = QPushButton("区域")
        self.btn_record = QPushButton("记录")
        self.btn_inference = QPushButton("推理")
        self.btn_exit = QPushButton("退出")
        
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
        
        left_layout.addWidget(self.btn_mark)
        left_layout.addWidget(self.btn_record)
        left_layout.addWidget(self.btn_inference)
        left_layout.addWidget(self.btn_exit)
        
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
        
        self.video_label = DrawableVideoLabel('视频流加载中...')
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
        
        # 创建旋转矩阵显示标签（叠加在3D渲染上方）
        self.rotation_matrix_label = QLabel("旋转矩阵:\n[--, --, --]\n[--, --, --]\n[--, --, --]")
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
        
        # 标记模式状态
        self.marking_mode = False
        
        # 初始化视频流线程
        self.video_thread = VideoStreamThread(self.video_url)
        self.video_thread.frame_updated.connect(self.update_video_frame)
        self.video_thread.rotation_matrix_updated.connect(self.update_rotation_matrix)
        self.video_thread.processing_time_updated.connect(self.update_processing_time)
        
        # 初始化帧尺寸变量（用于坐标转换）
        self.original_frame_size = (1920, 1088)  # 默认值
        self.scaled_pixmap_size = (1920, 1088)  # 默认值
        
        # 启动线程
        logger.info("启动视频流线程")
        self.video_thread.start()
        logger.info("视频流线程已启动")
        
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
            # 设置悬浮窗到右上角
            if hasattr(self, 'video_container') and self.video_container:
                container_rect = self.video_container.rect()
                overlay_width = 400
                overlay_height = 400
                margin = 10  # 边距
                x = container_rect.width() - overlay_width - margin
                y = margin
                self.overlay.setGeometry(x, y, overlay_width, overlay_height)
            
            self.overlay.show()
            self.overlay.raise_()
            # 确保旋转矩阵标签在3D渲染上方
            if hasattr(self, 'rotation_matrix_label'):
                self.rotation_matrix_label.show()
                self.rotation_matrix_label.raise_()
                # 设置旋转矩阵标签位置（左上角）
                overlay_rect = self.overlay.rect()
                matrix_label_width = 180
                matrix_label_height = 100
                title_bar_height = 30
                self.rotation_matrix_label.setGeometry(
                    5,
                    title_bar_height + 5,
                    matrix_label_width,
                    matrix_label_height
                )
    
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
    
    def on_mark_clicked(self):
        """标记按钮点击事件"""
        if not self.marking_mode:
            # 进入标记模式
            self.marking_mode = True
            self.btn_mark.setText("确认")
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
            self.btn_mark.setText("标记")
            self.video_label.stop_drawing()
    
    def on_record_clicked(self):
        """记录按钮点击事件"""
        logger.info("用户点击了记录按钮")
        # TODO: 实现记录功能
    
    def on_inference_clicked(self):
        """推理按钮点击事件"""
        logger.info("用户点击了推理按钮")
        # TODO: 实现推理功能
    
    def closeEvent(self, event):
        logger.info("主窗口关闭事件触发，正在停止所有线程...")
        self.video_thread.stop()
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
            overlay_rect = self.overlay.rect()
            title_bar_height = 30
            
            # 更新旋转矩阵标签位置（左上角）
            if hasattr(self, 'rotation_matrix_label'):
                matrix_label_width = 180
                matrix_label_height = 100
                self.rotation_matrix_label.setGeometry(
                    5,
                    title_bar_height + 5,
                    matrix_label_width,
                    matrix_label_height
                )
    
    def resizeEvent(self, event):
        """窗口大小改变时，调整覆盖层位置"""
        super().resizeEvent(event)
        # 确保覆盖层在视频容器内
        if hasattr(self, 'overlay') and self.overlay.isVisible():
            video_container = self.video_label.parent()
            if video_container:
                overlay_rect = self.overlay.geometry()
                container_rect = video_container.geometry()
                # 如果覆盖层超出容器，调整位置
                if overlay_rect.right() > container_rect.right():
                    self.overlay.move(container_rect.right() - overlay_rect.width(), overlay_rect.top())
                if overlay_rect.bottom() > container_rect.bottom():
                    self.overlay.move(overlay_rect.left(), container_rect.bottom() - overlay_rect.height())
            # 更新标签位置
            self.update_overlay_labels()

