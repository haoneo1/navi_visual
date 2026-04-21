"""主界面：左侧控制区 + 右侧 GL 场景与可拖拽视频浮层。

整体流程
--------
1. ``MainWindow`` 构建 UI 后启动 ``VideoStreamThread``（HDMI），分析器默认关闭，视频帧始终刷新到浮层。
2. **Record**：在 ``get_save_root()`` 下新建 ``capture_<时间戳>/``，其中 ``video.upkg`` 存 NV12 流，
   ``viper_poses.jsonl`` 存录制期间从 USB 解析的位姿帧；``meta.json`` 记录分辨率、fps、源 URL 等。
3. **Exit**：关闭窗口并停止视频与 Viper 轮询。
4. 视频浮层由 ``ResizableOverlay`` + ``TitleBar`` 拖动/缩放，几何写入配置文件以便下次恢复。
5. Viper USB 与 ``viper_main.py`` 一致：``ViperUSBComm`` + 守护线程 ``read_usb_data``；解析结果写入
   ``viper_usb_comm._latest_frame``（等同 ``viper_ui_display`` 的 ``latest_data``），黄探头从该快照更新；
   ``queue`` 仅用于录制 drain；满队列时 USB 侧丢旧保新，避免 matplotlib 路线下曾出现的「丢新帧不跟手」。
"""

import json
import queue
import shutil
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtGui import QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .config import (
    get_fps,
    get_frame_height,
    get_frame_width,
    get_overlay_position,
    get_save_root,
    save_overlay_position,
)
from .data_package import DataPackage
from .gl_widget import GLWidget
from .logger import get_logger
from .video_thread import VideoFileThread, VideoStreamThread

logger = get_logger()

# Viper 位置（毫米）→ OpenGL 场景
_VIPER_MM_TO_SCENE = 0.015


def _ensure_viper_signal_on_path(repo_root: Path) -> bool:
    """将 ``viper_signal`` 加入 ``sys.path``，以便与 ``viper_main.py`` 相同方式 ``import viper_usb_comm``。"""
    viper_dir = repo_root / "viper_signal"
    if not (viper_dir / "viper_usb_comm.py").is_file():
        logger.warning("未找到 viper_signal 目录或 viper_usb_comm.py: %s", viper_dir)
        return False
    p = str(viper_dir.resolve())
    if p not in sys.path:
        sys.path.insert(0, p)
    return True

# MainWindow 按钮样式（集中定义，避免 init 内大段字符串）
_STYLE_CONTROL_BUTTON = """
    QPushButton {
        padding: 15px;
        font-size: 14px;
        background-color: #50c878;
        color: white;
        border: none;
        border-radius: 5px;
    }
    QPushButton:hover { background-color: #45b369; }
    QPushButton:pressed { background-color: #3a9d5a; }
"""
_STYLE_CONTROL_ACTIVE = """
    QPushButton {
        padding: 15px;
        font-size: 14px;
        background-color: #ff9900;
        color: white;
        border: none;
        border-radius: 5px;
    }
    QPushButton:hover { background-color: #e68a00; }
    QPushButton:pressed { background-color: #cc7a00; }
"""
_STYLE_DANGER_BUTTON = """
    QPushButton {
        padding: 15px;
        font-size: 14px;
        background-color: #e74c3c;
        color: white;
        border: none;
        border-radius: 5px;
    }
    QPushButton:hover { background-color: #c0392b; }
    QPushButton:pressed { background-color: #a93226; }
"""


def _persist_overlay_geometry(x: int, y: int, width: int, height: int) -> None:
    try:
        save_overlay_position(x, y, width, height)
        logger.debug("保存悬浮窗口位置: x=%s, y=%s, width=%s, height=%s", x, y, width, height)
    except Exception as e:
        logger.warning("保存悬浮窗口位置失败: %s", e)


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
        _persist_overlay_geometry(overlay.x(), overlay.y(), overlay.width(), overlay.height())


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
            self._save_overlay_position()
        super().mouseReleaseEvent(event)

    def _save_overlay_position(self):
        _persist_overlay_geometry(self.x(), self.y(), self.width(), self.height())
    
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
        # Viper：与 viper_main.py 相同对象（见 _start_viper_usb_tracker / _stop_viper_usb）
        self._viper_queue: queue.Queue | None = None
        self._viper_comm = None
        self._viper_read_thread: threading.Thread | None = None
        self._viper_poll_timer: QTimer | None = None
        self._viper_pose_fp = None
        self._record_session_dir: Path | None = None
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle("Ultrasound Navi App")
        self.setGeometry(100, 100, 1400, 700)
        self.statusBar().showMessage("就绪")

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)

        main_layout.addWidget(self._build_left_panel(), 0)
        main_layout.addWidget(self._build_right_panel(), 1)

        self._connect_action_signals()
        self._init_stream_state()
        self._start_viper_usb_tracker()

        if self.full_screen:
            logger.info("以全屏模式显示主窗口")
            self.showFullScreen()
        else:
            logger.info("以窗口模式显示主窗口")
            self.resize(1200, 800)

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(150)
        layout = QVBoxLayout(panel)
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)

        logo_label = QLabel()
        logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_label.setStyleSheet("padding: 5px;")
        logo_path = Path(__file__).parent.parent / "images" / "logo.png"
        if logo_path.exists():
            pixmap = QPixmap(str(logo_path))
            if not pixmap.isNull():
                logo_label.setPixmap(
                    pixmap.scaledToWidth(100, Qt.TransformationMode.SmoothTransformation)
                )
        else:
            logger.warning("Logo 文件不存在: %s", logo_path)
        layout.addWidget(logo_label, 0, Qt.AlignmentFlag.AlignCenter)

        layout.addStretch()

        self._function_button_style = _STYLE_CONTROL_BUTTON
        self._active_button_style = _STYLE_CONTROL_ACTIVE

        self.btn_record = QPushButton("Record")
        self.btn_exit = QPushButton("Exit")

        self.btn_record.setStyleSheet(self._function_button_style)
        self.btn_exit.setStyleSheet(_STYLE_DANGER_BUTTON)

        layout.addWidget(self.btn_record)
        layout.addWidget(self.btn_exit)
        return panel

    def _build_right_panel(self) -> QWidget:
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(5)

        rot_container = QWidget()
        rot_container.setStyleSheet("background-color: #000;")
        rot_layout = QVBoxLayout(rot_container)
        rot_layout.setContentsMargins(0, 0, 0, 0)

        self.gl_widget = GLWidget(rot_container)
        self.gl_widget.setMinimumSize(300, 300)
        self.gl_widget.set_show_red_rectangle(False)
        rot_layout.addWidget(self.gl_widget)

        self.video_overlay = ResizableOverlay(rot_container)
        self.video_overlay.raise_()
        self.video_overlay.setGeometry(10, 10, 480, 360)

        overlay_layout = QVBoxLayout(self.video_overlay)
        overlay_layout.setContentsMargins(0, 0, 0, 0)
        overlay_layout.setSpacing(0)

        self.title_bar = TitleBar(self.video_overlay)
        self.title_bar._title_text = "Video"
        overlay_layout.addWidget(self.title_bar)

        self.video_label = QLabel("Waiting HDMI...")
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setStyleSheet("background-color: #000; color: white; font-size: 16px;")
        overlay_layout.addWidget(self.video_label)

        self.rot_container = rot_container

        right_layout.addWidget(rot_container)
        return right_panel

    def _connect_action_signals(self):
        self.btn_record.clicked.connect(self.on_record_clicked)
        self.btn_exit.clicked.connect(self.close)

    def _init_stream_state(self):
        self.current_source = "hdmi"
        self.video_thread = None
        self.start_hdmi_thread()
        self._is_recording = False
        self._set_button_active(self.btn_record, False)
        self.original_frame_size = (1920, 1088)
        self.scaled_pixmap_size = (1920, 1088)

    def _start_viper_usb_tracker(self):
        """对齐 ``viper_signal/viper_main.py``：Queue(maxsize=10) → ViperUSBComm → Thread(read_usb_data)；
        此处用主线程 ``QTimer`` 轮询队列并驱动 ``GLWidget``（对应 viper_main 中主线程 ``visualizer.run()``）。"""
        repo_root = Path(__file__).resolve().parent.parent
        if not _ensure_viper_signal_on_path(repo_root):
            return
        try:
            from viper_usb_comm import ViperUSBComm  # type: ignore[import-untyped]
        except ImportError as e:
            logger.warning("无法导入 viper_usb_comm（需安装 pyusb）: %s", e)
            return

        trace_dir = repo_root / "viper_signal" / "trace"
        trace_dir.mkdir(parents=True, exist_ok=True)

        self._viper_queue = queue.Queue(maxsize=256)
        self._viper_comm = ViperUSBComm(data_queue=self._viper_queue, trace_dir=str(trace_dir))

        if not self._viper_comm.connect():
            logger.warning("Viper USB 连接失败（参考 viper_main: connect）")
            try:
                self._viper_comm.disconnect()
            except Exception:
                pass
            self._viper_comm = None
            self._viper_queue = None
            return

        if not self._viper_comm.start_continuous():
            logger.warning("Viper 未能进入 continuous 模式（参考 viper_main: start_continuous）")
            try:
                self._viper_comm.disconnect()
            except Exception:
                pass
            self._viper_comm = None
            self._viper_queue = None
            return

        self._viper_comm.keep_reading = True
        self._viper_read_thread = threading.Thread(target=self._viper_comm.read_usb_data, daemon=True)
        self._viper_read_thread.start()

        # viper_ui_display 约 10 FPS；黄探头用 latest_frame + 视频帧旁路刷新，定时器主要 drain 录制队列
        self._viper_poll_timer = QTimer(self)
        self._viper_poll_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._viper_poll_timer.setInterval(16)
        self._viper_poll_timer.timeout.connect(self._poll_viper_queue_to_gl)
        self._viper_poll_timer.start()
        logger.info("Viper：已按 viper_main.py 启动（Queue + read_usb_data 守护线程 + 主线程 QTimer 消费队列）")

    def _append_viper_pose_line(self, frame: dict) -> None:
        """录制时把整帧 USB 位姿写入会话目录下的 JSONL。"""
        fp = getattr(self, "_viper_pose_fp", None)
        if fp is None:
            return
        row = {
            "wall_time": time.time(),
            "frame_num": frame.get("frame_num"),
            "seuid": frame.get("seuid"),
            "sensors": [
                {"num": s["num"], "pos": list(s["pos"]), "ori": list(s["ori"])}
                for s in frame.get("sensors", [])
            ],
        }
        fp.write(json.dumps(row, ensure_ascii=False) + "\n")
        fp.flush()

    def _apply_latest_viper_to_gl(self) -> None:
        """与 viper_ui_display.run 中「latest_data」一致：从 USB 线程更新的 latest 读位姿，驱动黄探头。"""
        if not hasattr(self, "gl_widget"):
            return
        comm = getattr(self, "_viper_comm", None)
        if comm is None:
            return
        lock = getattr(comm, "_latest_frame_lock", None)
        if lock is None:
            return
        try:
            with lock:
                snap = comm._latest_frame
        except Exception:
            return
        if not snap:
            return
        sensors = snap.get("sensors") or []
        if not sensors:
            return
        px, py, pz = sensors[0]["pos"]
        self.gl_widget.update_coordinates(
            px * _VIPER_MM_TO_SCENE,
            py * _VIPER_MM_TO_SCENE,
            pz * _VIPER_MM_TO_SCENE,
        )

    def _drain_viper_queue_for_recording(self) -> None:
        if self._viper_queue is None:
            return
        while True:
            try:
                f = self._viper_queue.get_nowait()
            except queue.Empty:
                break
            if getattr(self, "_is_recording", False):
                self._append_viper_pose_line(f)

    def _poll_viper_queue_to_gl(self):
        """主线程：黄探头跟 latest_frame；队列仅用于录制时落盘 drain。"""
        self._apply_latest_viper_to_gl()
        self._drain_viper_queue_for_recording()

    def _stop_viper_usb(self):
        """对齐 viper_main.py 的 finally：停轮询、停读、join、disconnect。"""
        if self._viper_poll_timer is not None:
            self._viper_poll_timer.stop()
            self._viper_poll_timer = None
        if self._viper_comm is not None:
            self._viper_comm.keep_reading = False
            try:
                self._viper_comm.is_continuous = False
            except Exception:
                pass
            if self._viper_read_thread is not None and self._viper_read_thread.is_alive():
                self._viper_read_thread.join(timeout=2)
            self._viper_read_thread = None
            try:
                self._viper_comm.disconnect()
            except Exception as e:
                logger.debug("Viper disconnect: %s", e)
            self._viper_comm = None
        self._viper_queue = None

    def _set_video_stopped_placeholder(self):
        if hasattr(self, "video_label"):
            self.video_label.setText("视频已停止")
            self.video_label.setStyleSheet("background-color: #000; color: #666; font-size: 14px;")
    
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
            logger.warning(
                "容器大小无效，延迟重试设置默认位置: %sx%s",
                container_rect.width(),
                container_rect.height(),
            )
            QTimer.singleShot(100, self._set_default_overlay_position)
    
    def _validate_overlay_position(self):
        """验证并修正悬浮窗口位置（确保在容器范围内）"""
        if not hasattr(self, 'video_overlay') or not hasattr(self, 'rot_container'):
            return

        overlay_rect = self.video_overlay.geometry()
        # video_overlay 的父控件是 rot_container，必须用 rect()（局部坐标），勿用 geometry()
        container_rect = self.rot_container.rect()
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
            _persist_overlay_geometry(new_x, new_y, overlay_rect.width(), overlay_rect.height())
            logger.info("修正视频悬浮窗口位置: x=%s, y=%s", new_x, new_y)
    
    def update_video_frame(self, frame):
        height, width, channel = frame.shape
        bytes_per_line = channel * width
        q_image = QImage(frame.data, width, height, bytes_per_line, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(q_image).scaled(
            self.video_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.video_label.setPixmap(pixmap)
        self.original_frame_size = (width, height)
        self.scaled_pixmap_size = (pixmap.width(), pixmap.height())
        self._apply_latest_viper_to_gl()

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
    
    def _disconnect_video_signals(self, thread):
        """断开视频线程信号，避免重复连接"""
        if not thread:
            return
        pairs = [
            (thread.frame_updated, self.update_video_frame),
            (thread.processing_time_updated, self.update_processing_time),
        ]
        for sig, slot in pairs:
            try:
                sig.disconnect(slot)
            except Exception:
                pass
        if hasattr(thread, "finished_playback"):
            try:
                thread.finished_playback.disconnect(self.on_file_finished)
            except Exception:
                pass
        for sig, slot in (
            (getattr(thread, "package_saved", None), self._on_package_saved),
            (getattr(thread, "thread_error", None), self.on_video_thread_error),
            (getattr(thread, "thread_recovered", None), self.on_video_thread_recovered),
        ):
            if sig is not None:
                try:
                    sig.disconnect(slot)
                except Exception:
                    pass
    
    def _connect_video_signals(self, thread):
        """连接视频线程信号"""
        thread.frame_updated.connect(self.update_video_frame)
        thread.processing_time_updated.connect(self.update_processing_time)
        if hasattr(thread, "finished_playback"):
            thread.finished_playback.connect(self.on_file_finished)
        pkg = getattr(thread, "package_saved", None)
        if pkg is not None:
            pkg.connect(self._on_package_saved)
        err = getattr(thread, "thread_error", None)
        if err is not None:
            err.connect(self.on_video_thread_error)
        rec = getattr(thread, "thread_recovered", None)
        if rec is not None:
            rec.connect(self.on_video_thread_recovered)
    
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
        try:
            thread.enable_analyzer(False)
        except Exception:
            pass

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
    
    def _close_viper_pose_log(self) -> None:
        if getattr(self, "_viper_pose_fp", None) is not None:
            try:
                self._viper_pose_fp.close()
            except Exception:
                pass
            self._viper_pose_fp = None
        self._record_session_dir = None

    def on_record_clicked(self):
        """Record：开始/停止录制；视频写入会话目录内 upkg，USB 位姿写入同目录 viper_poses.jsonl。"""
        logger.info("用户点击了记录按钮")

        if not getattr(self, "_is_recording", False):
            save_root = Path(get_save_root())
            try:
                save_root.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                logger.error("创建保存根目录失败: %s, %s", save_root, e, exc_info=True)
                return

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            session_dir = save_root / f"capture_{timestamp}"
            try:
                session_dir.mkdir(parents=True, exist_ok=False)
            except FileExistsError:
                session_dir = save_root / f"capture_{timestamp}_{int(time.time() * 1000) % 100000}"
                session_dir.mkdir(parents=True, exist_ok=True)

            self._record_session_dir = session_dir
            video_path = session_dir / "video.upkg"

            meta = {
                "created": datetime.now().isoformat(),
                "video_url": self.video_url,
                "frame_width": get_frame_width(),
                "frame_height": get_frame_height(),
                "fps": get_fps(),
                "video_file": video_path.name,
                "viper_poses_file": "viper_poses.jsonl",
            }
            try:
                (session_dir / "meta.json").write_text(
                    json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            except Exception as e:
                logger.error("写入 meta.json 失败: %s", e, exc_info=True)

            try:
                self._viper_pose_fp = open(session_dir / "viper_poses.jsonl", "w", encoding="utf-8")
            except Exception as e:
                logger.error("无法创建 viper_poses.jsonl: %s", e, exc_info=True)
                self._record_session_dir = None
                shutil.rmtree(session_dir, ignore_errors=True)
                return

            width = get_frame_width()
            height = get_frame_height()
            package = DataPackage(str(video_path), image_type="nv12", width=width, height=height, realtime=True)
            try:
                package.start_recording()
            except Exception as e:
                logger.error("启动数据包录制失败: %s", e, exc_info=True)
                self._close_viper_pose_log()
                shutil.rmtree(session_dir, ignore_errors=True)
                return

            self._is_recording = True
            self.btn_record.setText("Stop")
            self._set_button_active(self.btn_record, True)
            self._record_package = package
            try:
                if self.video_thread:
                    self.video_thread.start_recording_package(package)
                else:
                    logger.warning("没有活动的视频线程，仅写入 USB 位姿文件")
            except Exception as e:
                logger.error("开始写入数据包失败: %s", e, exc_info=True)
                self._is_recording = False
                self._set_button_active(self.btn_record, False)
                self.btn_record.setText("Record")
                self._close_viper_pose_log()
                shutil.rmtree(session_dir, ignore_errors=True)
                return

            logger.info("开始录制，会话目录: %s", session_dir)
        else:
            logger.info("停止录制请求")
            self._close_viper_pose_log()
            try:
                if self.video_thread:
                    self.video_thread.stop_recording_package()
                else:
                    pkg = getattr(self, "_record_package", None)
                    if pkg is not None:
                        try:
                            pkg.save()
                            logger.info("数据包保存完成: %s", pkg.save_path)
                        except Exception as e:
                            logger.error("无视频线程时保存数据包失败: %s", e, exc_info=True)
                        self.btn_record.setText("Record")
                        self._set_button_active(self.btn_record, False)
            except Exception as e:
                logger.error("请求停止写入数据包失败: %s", e, exc_info=True)
            if self.video_thread:
                self.btn_record.setText("Saving...")
            self._is_recording = False
            self._set_button_active(self.btn_record, False)

    def _on_package_saved(self, path: str):
        """DataPackage 保存完成回调（在视频线程中发出）"""
        logger.info(f"数据包保存完成: {path}")
        try:
            def _restore():
                self.btn_record.setText("Record")
                self._set_button_active(self.btn_record, False)

            QTimer.singleShot(0, _restore)
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
        
    def closeEvent(self, event):
        logger.info("主窗口关闭事件触发，正在停止所有线程...")
        if getattr(self, "_is_recording", False):
            self._close_viper_pose_log()
            try:
                if self.video_thread:
                    self.video_thread.stop_recording_package()
                else:
                    pkg = getattr(self, "_record_package", None)
                    if pkg is not None:
                        try:
                            pkg.save()
                        except Exception:
                            pass
            except Exception:
                pass
            self._is_recording = False
        self._stop_viper_usb()
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
        """悬浮层布局变化时的占位回调（如 ResizableOverlay 缩放时调用）。"""
        pass

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
            container_rect = self.rot_container.rect()
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
                _persist_overlay_geometry(
                    self.video_overlay.x(),
                    self.video_overlay.y(),
                    self.video_overlay.width(),
                    self.video_overlay.height(),
                )
                logger.info(
                    "窗口大小改变，调整并保存视频悬浮窗口位置: x=%s, y=%s, width=%s, height=%s",
                    self.video_overlay.x(),
                    self.video_overlay.y(),
                    self.video_overlay.width(),
                    self.video_overlay.height(),
                )
            # 更新标签位置
            self.update_overlay_labels()

