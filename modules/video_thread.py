"""视频流线程模块"""
import time
import numpy as np
import cv2
import requests
import os
from concurrent.futures import ThreadPoolExecutor
from PyQt6.QtCore import QThread, pyqtSignal, QTimer
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


def process_frame(url, output_dir=None, analyzer=None):
    """处理一帧：捕获、转换格式、AI分析"""
    start_time = time.perf_counter()
    
    try:
        response = requests.get(url, timeout=5)
        if response.status_code != 200:
            logger.error(f"HTTP请求失败: {response.status_code}")
            return None, None, (time.perf_counter() - start_time) * 1000
        
        if len(response.content) != FRAME_SIZE_NV12:
            logger.warning(f"数据大小不匹配，期望: {FRAME_SIZE_NV12}, 实际: {len(response.content)}")
            return None, None, (time.perf_counter() - start_time) * 1000
        
        # 转换格式
        frame_data = np.frombuffer(response.content, dtype=np.uint8)
        frame_data = frame_data.reshape((FRAME_H*3//2), FRAME_W)
        frame_rgb = cv2.cvtColor(frame_data, cv2.COLOR_YUV2RGB_NV12)
        
        # 根据配置裁剪区域
        crop_region = get_crop_region()
        frame_for_ai = frame_rgb
        if crop_region:
            x, y, w, h = crop_region
            # 确保裁剪区域在图像范围内
            x = max(0, min(x, FRAME_W - 1))
            y = max(0, min(y, FRAME_H - 1))
            w = max(1, min(w, FRAME_W - x))
            h = max(1, min(h, FRAME_H - y))
            frame_for_ai = frame_rgb[y:y+h, x:x+w]
        
        # AI分析（使用裁剪后的图像）
        rotation_matrix = analyzer.analyze(frame_for_ai) if analyzer else None
        
        # 记录旋转矩阵到日志
        if rotation_matrix is not None:
            matrix_str = "\n".join([
                f"[{row[0]:8.5f}, {row[1]:8.5f}, {row[2]:8.5f}]"
                for row in rotation_matrix
            ])
            logger.info(f"AI预测旋转矩阵:\n{matrix_str}")
        
        # 保存截图（保存裁剪后的图像）
        if SAVE_CAPTURE and output_dir:
            timestamp = datetime.now().strftime("%H%M%S_%f")[:-3]
            frame_bgr = cv2.cvtColor(frame_for_ai, cv2.COLOR_RGB2BGR)
            filepath = os.path.join(output_dir, f"{timestamp}.jpg")
            cv2.imwrite(filepath, frame_bgr)
        
        elapsed_time = (time.perf_counter() - start_time) * 1000
        return frame_rgb, rotation_matrix, elapsed_time
        
    except Exception as e:
        logger.error(f"获取视频流错误: {e}", exc_info=True)
        return None, None, (time.perf_counter() - start_time) * 1000


class VideoStreamThread(QThread):
    """视频流获取线程 - 使用定时器和线程池"""
    frame_updated = pyqtSignal(np.ndarray)
    rotation_matrix_updated = pyqtSignal(np.ndarray)  # 旋转矩阵信号
    processing_time_updated = pyqtSignal(float)  # 处理时间信号（毫秒）
    
    def __init__(self, url):
        super().__init__()
        self.url = url
        self.running = False
        self.timer = None
        self.analyzer = AIAnalyzer()
        self.executor = ThreadPoolExecutor(max_workers=2)
        
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
            frame_rgb, rotation_matrix, processing_time = future.result()
            
            if frame_rgb is not None:
                self.frame_updated.emit(frame_rgb)
            if rotation_matrix is not None:
                self.rotation_matrix_updated.emit(rotation_matrix)
            self.processing_time_updated.emit(processing_time)
        except Exception as e:
            logger.error(f"处理帧回调错误: {e}", exc_info=True)
    
    def run(self):
        """启动定时器"""
        self.running = True
        logger.info(f"视频流线程启动 - URL: {self.url}, FPS: {FPS}, 间隔: {FRAME_INTERVAL_MS}ms")
        
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
        self.executor.shutdown(wait=True)
        self.quit()
        self.wait()
        logger.info("视频流线程已完全停止")

