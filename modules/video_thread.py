"""视频流线程模块"""
import time
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    print("Warning: numpy not available, video processing will be limited")

import cv2
import requests
import os
from concurrent.futures import ThreadPoolExecutor
from PySide6.QtCore import QObject, QThread, Signal, QTimer, Qt
from datetime import datetime
from .config import (
    get_frame_width,
    get_frame_height,
    get_save_capture,
    get_save_root,
    get_dummy_frames_path,
    get_use_dummy,
    get_dummy_root,
    get_fps,
    get_crop_region
)
from .ai_analyzer import AIAnalyzer
from .logger import get_logger
from .data_package import DataPackage

logger = get_logger()

# 视频流配置常量（从配置文件加载）
FRAME_W = get_frame_width()
FRAME_H = get_frame_height()
FRAME_SIZE_NV12 = FRAME_W * FRAME_H * 3 // 2
SAVE_ROOT = get_save_root()
SAVE_CAPTURE = get_save_capture()
DUMMY_FRAME = get_dummy_frames_path()
USE_DUMMY = get_use_dummy()
DUMMY_ROOT = get_dummy_root()
FPS = get_fps()
# 计算每帧之间的时间间隔（毫秒）
FRAME_INTERVAL_MS = int(1000.0 / FPS) if FPS > 0 else 1000


class _VideoRestartBridge(QObject):
    """将重启逻辑投递到视频 QThread 内执行（线程池回调不能直接接触 QTimer）。"""

    def __init__(self, owner: "VideoStreamThread"):
        super().__init__()
        self._owner = owner

    def run_restart(self):
        self._owner._restart_thread()


def process_frame(url, output_dir=None, analyzer=None):
    """处理一帧：捕获、转换格式、AI分析"""
    start_time = time.perf_counter()

    if not HAS_NUMPY:
        return None, None, (time.perf_counter() - start_time) * 1000

    try:
        response = requests.get(url, timeout=1)
        if response.status_code != 200:
            logger.error(f"HTTP请求失败: {response.status_code}")
            return None, None, (time.perf_counter() - start_time) * 1000

        if len(response.content) != FRAME_SIZE_NV12:
            logger.warning(f"数据大小不匹配，期望: {FRAME_SIZE_NV12}, 实际: {len(response.content)}")
            return None, None, (time.perf_counter() - start_time) * 1000

        # raw bytes（NV12）
        raw_bytes = response.content
        # 转换格式
        frame_data = np.frombuffer(raw_bytes, dtype=np.uint8)
        frame_data = frame_data.reshape((FRAME_H*3//2), FRAME_W)
        frame_rgb = cv2.cvtColor(frame_data, cv2.COLOR_YUV2RGB_NV12)
        
        # 根据配置裁剪区域
        crop_region = get_crop_region()
        if crop_region:
            x, y, w, h = crop_region
            # 确保裁剪区域在图像范围内
            x = max(0, min(x, FRAME_W - 1))
            y = max(0, min(y, FRAME_H - 1))
            w = max(1, min(w, FRAME_W - x))
            h = max(1, min(h, FRAME_H - y))
            frame_for_ai = frame_rgb[y:y+h, x:x+w]
        else:
            frame_for_ai = frame_rgb
        
        # AI分析（使用裁剪后的图像）
        rotation_matrix = analyzer.analyze(frame_for_ai) if analyzer else None
        
        # 记录旋转矩阵到日志
        if rotation_matrix is not None:
            matrix_str = ";".join([
                f"[{row[0]:8.5f}, {row[1]:8.5f}, {row[2]:8.5f}]"
                for row in rotation_matrix
            ])
            logger.info(f"ROT_AI: {matrix_str}")
        
        # 保存截图（保存裁剪后的图像）
        if SAVE_CAPTURE and output_dir:
            timestamp = datetime.now().strftime("%H%M%S_%f")[:-3]
            frame_bgr = cv2.cvtColor(frame_for_ai, cv2.COLOR_RGB2BGR)
            filepath = os.path.join(output_dir, f"{timestamp}.jpg")
            cv2.imwrite(filepath, frame_bgr)
        
        elapsed_time = (time.perf_counter() - start_time) * 1000
        # 返回RGB用于UI显示，以及原始NV12 bytes用于记录
        return frame_rgb, rotation_matrix, elapsed_time, raw_bytes
        
    except Exception as e:
        logger.error(f"获取视频流错误: {e}", exc_info=True)
        return None, None, (time.perf_counter() - start_time) * 1000


class VideoStreamThread(QThread):
    """视频流获取线程 - 使用定时器和线程池"""
    if HAS_NUMPY:
        frame_updated = Signal(np.ndarray)
        rotation_matrix_updated = Signal(np.ndarray)  # 旋转矩阵信号
    else:
        frame_updated = Signal(object)  # 使用object代替np.ndarray
        rotation_matrix_updated = Signal(object)  # 使用object代替np.ndarray
    processing_time_updated = Signal(float)  # 处理时间信号（毫秒）
    package_saved = Signal(str)  # 当 DataPackage 保存完成时发出（传递保存路径）
    thread_error = Signal(str)  # 线程错误警告信号
    thread_recovered = Signal()  # 线程恢复信号
    # 由线程池回调触发，排队到本 QThread 再执行 _restart_thread，避免在非 Qt 线程操作 QTimer 导致崩溃退出
    _restart_requested = Signal()

    def __init__(self, url):
        super().__init__()
        self.url = url
        self.running = False
        self.timer = None
        self.analyzer = AIAnalyzer()
        self.executor = ThreadPoolExecutor(max_workers=2)
        self._restart_bridge = None
        self._restart_in_progress = False
        # 当前正在写入的数据包（由 UI 启动录制时传入）
        self._recording_package = None

        # 线程保护机制
        self._consecutive_failures = 0  # 连续失败次数
        self._max_consecutive_failures = 5  # 最大连续失败次数
        self._last_successful_frame = time.time()  # 最后成功获取帧的时间
        self._health_check_timer = None  # 健康检查定时器
        self._auto_restart_enabled = True  # 自动重启启用标志
        
        # 设置保存目录
        if SAVE_CAPTURE:
            self.output_dir = os.path.join(SAVE_ROOT, datetime.now().strftime("%Y%m%d_%H%M%S"))
            os.makedirs(self.output_dir, exist_ok=True)
            logger.info(f"视频截图保存目录: {self.output_dir}")
        else:
            self.output_dir = None
    
    def _on_timer_timeout(self):
        """定时器触发时，在线程池中处理帧"""
        if not self.running:
            if self.timer and self.timer.isActive():
                self.timer.stop()
            self.quit()
            return
        
        future = self.executor.submit(process_frame, self.url, self.output_dir, self.analyzer)
        future.add_done_callback(self._on_frame_processed)
    
    def _on_frame_processed(self, future):
        """帧处理完成回调"""
        try:
            # 现在 process_frame 返回 (frame_rgb, rotation_matrix, processing_time_ms, raw_bytes)
            result = future.result()
            # 兼容老版本返回三个元素
            if isinstance(result, tuple) and len(result) == 4:
                frame_rgb, rotation_matrix, processing_time, raw_bytes = result
            else:
                frame_rgb, rotation_matrix, processing_time = result
                raw_bytes = None

            # 检查帧是否成功获取
            if frame_rgb is not None:
                # 成功获取帧，重置失败计数
                self._consecutive_failures = 0
                self._last_successful_frame = time.time()
                if self._consecutive_failures > 0:
                    logger.info("视频流恢复正常")
                    self.thread_recovered.emit()

                self.frame_updated.emit(frame_rgb)
                if rotation_matrix is not None:
                    self.rotation_matrix_updated.emit(rotation_matrix)
                self.processing_time_updated.emit(processing_time)

                # 如果开启了录制，将原始NV12写入数据包（在工作线程中写，避免阻塞主线程）
                if self._recording_package is not None and raw_bytes is not None and HAS_NUMPY:
                    try:
                        nv12_arr = np.frombuffer(raw_bytes, dtype=np.uint8)
                        # 使用当前时间作为时间戳
                        self._recording_package.add_frame(time.time(), nv12_arr, trace={})
                    except Exception as e:
                        logger.error(f"写入数据包帧失败: {e}", exc_info=True)
            else:
                # 帧获取失败，增加失败计数
                self._consecutive_failures += 1
                logger.warning(f"视频帧获取失败，连续失败次数: {self._consecutive_failures}")

                # 如果连续失败次数过多，发出警告
                if self._consecutive_failures >= self._max_consecutive_failures:
                    error_msg = f"视频流严重故障：连续{self._consecutive_failures}次获取失败"
                    logger.error(error_msg)
                    self.thread_error.emit(error_msg)

                    # 如果启用了自动重启，尝试重启线程
                    if self._auto_restart_enabled and self.running:
                        logger.info("尝试自动重启视频流线程...")
                        self._restart_requested.emit()
                else:
                    # 发送空的处理时间信号以保持UI更新
                    self.processing_time_updated.emit(processing_time)

        except Exception as e:
            # 帧处理异常，增加失败计数
            self._consecutive_failures += 1
            logger.error(f"处理帧回调错误 (连续失败{self._consecutive_failures}): {e}", exc_info=True)

            if self._consecutive_failures >= self._max_consecutive_failures:
                error_msg = f"视频流处理严重故障：连续{self._consecutive_failures}次处理失败"
                self.thread_error.emit(error_msg)

                if self._auto_restart_enabled and self.running:
                    self._restart_requested.emit()

    def run(self):
        """启动定时器"""
        self.running = True
        logger.info(f"视频流线程启动 - URL: {self.url}, FPS: {FPS}, 间隔: {FRAME_INTERVAL_MS}ms")

        self._restart_bridge = _VideoRestartBridge(self)
        self._restart_bridge.moveToThread(QThread.currentThread())
        self._restart_requested.connect(
            self._restart_bridge.run_restart,
            Qt.ConnectionType.QueuedConnection,
        )

        # 启动健康检查定时器（每5秒检查一次）
        self._health_check_timer = QTimer()
        self._health_check_timer.timeout.connect(self._health_check)
        self._health_check_timer.start(5000)  # 5秒检查一次

        self.timer = QTimer()
        self.timer.timeout.connect(self._on_timer_timeout)
        self.timer.start(FRAME_INTERVAL_MS)
        self._on_timer_timeout()

        self.exec()
        logger.info("视频流线程已停止")
    
    def stop(self):
        """停止定时器和线程池"""
        logger.info("正在停止视频流线程...")
        self.running = False

        if self.timer and self.timer.isActive():
            self.timer.stop()

        # 停止健康检查定时器
        if self._health_check_timer and self._health_check_timer.isActive():
            self._health_check_timer.stop()

        try:
            self.executor.shutdown(wait=True)
        except Exception as e:
            logger.warning("线程池关闭时出现异常（可忽略）: %s", e)

        self.quit()
        self.wait()
        logger.info("视频流线程已完全停止")

    def start_recording_package(self, package: 'DataPackage'):
        """开始将原始 NV12 写入传入的 DataPackage（在工作线程中写入）"""
        try:
            self._recording_package = package
            logger.info(f"VideoStreamThread: 开始将帧写入数据包: {package.save_path}")
        except Exception as e:
            logger.error(f"start_recording_package 失败: {e}", exc_info=True)

    def stop_recording_package(self):
        """停止写入并在后台保存数据包"""
        pkg = self._recording_package
        self._recording_package = None
        if pkg is None:
            return

        def _save_pkg():
            try:
                pkg.save()
                logger.info(f"VideoStreamThread: 数据包保存完成: {pkg.save_path}")
                try:
                    # emit signal to notify UI（在非主线程发射信号也可以）
                    self.package_saved.emit(str(pkg.save_path))
                except Exception:
                    pass
            except Exception as e:
                logger.error(f"VideoStreamThread: 数据包保存失败: {e}", exc_info=True)

        # 在线程池中保存，避免阻塞线程
        try:
            self.executor.submit(_save_pkg)
        except Exception as e:
            # 回退到直接保存
            _save_pkg()

    def enable_analyzer(self, enable: bool):
        """启用或禁用 AI 分析器（在运行时切换）"""
        try:
            if enable:
                if self.analyzer is None:
                    self.analyzer = AIAnalyzer()
                    logger.info("VideoStreamThread: AI 分析器已启用")
            else:
                self.analyzer = None
                logger.info("VideoStreamThread: AI 分析器已禁用")
        except Exception as e:
            logger.error(f"enable_analyzer 失败: {e}", exc_info=True)

    def _health_check(self):
        """健康检查 - 定期检查线程状态"""
        if not self.running:
            return

        current_time = time.time()
        time_since_last_frame = current_time - self._last_successful_frame

        # 如果超过30秒没有成功获取帧，发出警告
        if time_since_last_frame > 30.0:
            warning_msg = f"视频流无响应：{time_since_last_frame:.1f}秒未获取到有效帧"
            logger.warning(warning_msg)
            self.thread_error.emit(warning_msg)

            # 如果启用了自动重启，尝试重启
            if self._auto_restart_enabled and self._consecutive_failures >= 3:
                logger.info("检测到长时间无响应，尝试自动重启视频流线程...")
                self._restart_thread()

    def _restart_thread(self):
        """在本 QThread 内重启定时器与线程池（须在拥有事件循环的线程调用）。"""
        if self._restart_in_progress:
            return
        if not self.running:
            return
        self._restart_in_progress = True
        try:
            logger.info("正在重启视频流线程...")

            # 停止当前定时器
            if self.timer and self.timer.isActive():
                self.timer.stop()

            # 停止健康检查定时器
            if self._health_check_timer and self._health_check_timer.isActive():
                self._health_check_timer.stop()

            # 关闭线程池，等待在途任务结束，避免与 QTimer 竞态导致进程异常退出
            if hasattr(self, "executor") and self.executor is not None:
                try:
                    self.executor.shutdown(wait=True, cancel_futures=False)
                except TypeError:
                    self.executor.shutdown(wait=True)

            time.sleep(0.1)

            # 重置状态
            self._consecutive_failures = 0
            self._last_successful_frame = time.time()

            if not self.running:
                return

            # 重新创建线程池
            self.executor = ThreadPoolExecutor(max_workers=2)

            # 重新启动健康检查
            self._health_check_timer = QTimer()
            self._health_check_timer.timeout.connect(self._health_check)
            self._health_check_timer.start(5000)

            # 重新启动视频获取定时器
            self.timer = QTimer()
            self.timer.timeout.connect(self._on_timer_timeout)
            self.timer.start(FRAME_INTERVAL_MS)

            logger.info("视频流线程重启完成")
            self.thread_recovered.emit()

        except Exception as e:
            error_msg = f"视频流线程重启失败: {e}"
            logger.error(error_msg, exc_info=True)
            self.thread_error.emit(error_msg)
        finally:
            self._restart_in_progress = False

    def set_auto_restart(self, enabled: bool):
        """设置是否启用自动重启功能"""
        self._auto_restart_enabled = enabled
        logger.info(f"视频流自动重启功能: {'启用' if enabled else '禁用'}")


class VideoFileThread(QThread):
    """本地 MP4 播放线程"""
    if HAS_NUMPY:
        frame_updated = Signal(np.ndarray)
        rotation_matrix_updated = Signal(np.ndarray)
    else:
        frame_updated = Signal(object)  # 使用object代替np.ndarray
        rotation_matrix_updated = Signal(object)  # 使用object代替np.ndarray
    processing_time_updated = Signal(float)
    finished_playback = Signal()

    def __init__(self, file_path):
        super().__init__()
        self.file_path = file_path
        self.running = False
        self.analyzer = AIAnalyzer()

    def run(self):
        self.running = True
        cap = cv2.VideoCapture(self.file_path)
        if not cap.isOpened():
            logger.error(f"无法打开视频文件: {self.file_path}")
            self.finished_playback.emit()
            return

        fps = cap.get(cv2.CAP_PROP_FPS)
        fps = fps if fps and fps > 1 else 30.0
        frame_interval = 1.0 / fps

        logger.info(f"开始播放视频文件: {self.file_path}, FPS: {fps:.2f}")

        while self.running:
            start_time = time.perf_counter()
            ret, frame_bgr = cap.read()
            if not ret:
                logger.info("视频播放结束")
                break

            try:
                frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)

                # 根据配置裁剪区域
                crop_region = get_crop_region()
                if crop_region:
                    x, y, w, h = crop_region
                    h_total, w_total, _ = frame_rgb.shape
                    x = max(0, min(x, w_total - 1))
                    y = max(0, min(y, h_total - 1))
                    w = max(1, min(w, w_total - x))
                    h = max(1, min(h, h_total - y))
                    frame_for_ai = frame_rgb[y:y + h, x:x + w]
                else:
                    frame_for_ai = frame_rgb

                rotation_matrix = self.analyzer.analyze(frame_for_ai) if self.analyzer else None

                if rotation_matrix is not None:
                    matrix_str = ";".join([
                        f"[{row[0]:8.5f}, {row[1]:8.5f}, {row[2]:8.5f}]"
                        for row in rotation_matrix
                    ])
                    logger.info(f"ROT_FILE: {matrix_str}")

                elapsed_time = (time.perf_counter() - start_time) * 1000

                self.frame_updated.emit(frame_rgb)
                if rotation_matrix is not None:
                    self.rotation_matrix_updated.emit(rotation_matrix)
                self.processing_time_updated.emit(elapsed_time)
            except Exception as e:
                logger.error(f"播放视频帧错误: {e}", exc_info=True)

            # 控制播放速度
            elapsed = time.perf_counter() - start_time
            sleep_time = frame_interval - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)

        cap.release()
        self.finished_playback.emit()
        logger.info("视频文件线程结束")

    def stop(self):
        self.running = False

