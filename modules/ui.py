"""主界面：左侧控制区 + 右侧 3D/视频双栏。

整体流程
--------
1. ``MainWindow`` 构建 UI 后启动 ``VideoStreamThread``（HDMI 或 dummy），视频帧始终刷新到右侧视频区域。
2. **Record**：在 ``get_save_root()`` 下新建 ``capture_<时间戳>/``，其中 ``video.upkg`` 存 NV12 流，
   ``viper_poses.jsonl`` 存录制期间从 USB 解析的位姿帧；``meta.json`` 记录分辨率、fps、源 URL 等。
3. **Exit**：关闭窗口并停止视频与 Viper 轮询。
4. 右侧区域固定为左右等宽双栏：左侧 ``GLWidget``（3D），右侧 ``QLabel``（视频）。
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

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
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
)
from .data_package import DataPackage
from .gl_widget import GLWidget
from .logger import get_logger
from .video_thread import VideoStreamThread

logger = get_logger()

# Viper 位置（毫米）→ OpenGL 场景
_VIPER_MM_TO_SCENE = 0.015
_NV12_SAVE_ROOT = Path(__file__).resolve().parent.parent / "data" / "Data_save"


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

class MainWindow(QMainWindow):
    """主窗口 - 两列布局"""
    def __init__(self, video_url="http://192.168.0.39:8080/raw", full_screen=True):
        super().__init__()
        self.video_url = video_url
        self.full_screen = full_screen
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
        right_layout = QHBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        gl_container = QWidget()
        gl_container.setStyleSheet("background-color: #000;")
        gl_layout = QVBoxLayout(gl_container)
        gl_layout.setContentsMargins(0, 0, 0, 0)

        self.gl_widget = GLWidget(gl_container)
        self.gl_widget.setMinimumSize(300, 300)
        self.gl_widget.set_show_red_rectangle(False)
        gl_layout.addWidget(self.gl_widget)
        self.xyz_info_label = QLabel("X: 0.000   Y: 0.000   Z: 0.000")
        self.xyz_info_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.xyz_info_label.setFixedHeight(30)
        self.xyz_info_label.setStyleSheet(
            "background-color: #111; color: #ffd84d; font-size: 13px; padding: 6px; border-top: 1px solid #333;"
        )
        gl_layout.addWidget(self.xyz_info_label)

        video_container = QWidget()
        video_container.setStyleSheet("background-color: #000;")
        video_layout = QVBoxLayout(video_container)
        video_layout.setContentsMargins(0, 0, 0, 0)

        self.video_label = QLabel("Waiting HDMI...")
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setStyleSheet("background-color: #000; color: white; font-size: 16px;")
        video_layout.addWidget(self.video_label)

        right_layout.addWidget(gl_container, 1)
        right_layout.addWidget(video_container, 1)

        self.rot_container = gl_container
        return right_panel

    def _connect_action_signals(self):
        self.btn_record.clicked.connect(self.on_record_clicked)
        self.btn_exit.clicked.connect(self.close)

    def _init_stream_state(self):
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
        self._update_xyz_info_label()

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

    def _update_xyz_info_label(self):
        if not hasattr(self, "gl_widget") or not hasattr(self, "xyz_info_label"):
            return
        self.xyz_info_label.setText(
            f"X: {float(self.gl_widget.x):.3f}   Y: {float(self.gl_widget.y):.3f}   Z: {float(self.gl_widget.z):.3f}"
        )
    
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
        self._update_xyz_info_label()

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
        """启动视频流线程（实时流或 dummy 由配置控制）"""
        self.stop_video_thread()
        logger.info("启动 HDMI 视频流线程")
        thread = VideoStreamThread(self.video_url)
        self._connect_video_signals(thread)
        self.video_thread = thread
        thread.start()
    
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
            save_root = _NV12_SAVE_ROOT
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
    
