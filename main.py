import sys
import time
import numpy as np
import cv2
import requests
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                           QHBoxLayout, QLabel, QFrame)
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QTimer
from OpenGL.GL import *
from OpenGL.GLU import *
from PyQt5.QtOpenGL import QGLWidget

# 视频流获取线程
class VideoStreamThread(QThread):
    frame_updated = pyqtSignal(np.ndarray)
    
    def __init__(self, url):
        super().__init__()
        self.url = url
        self.running = False
        
    def run(self):
        self.running = True
        while self.running:
            try:
                # 从URL获取一帧图像
                response = requests.get(self.url, timeout=5)
                if response.status_code == 200:
                    # 将响应内容转换为OpenCV格式
                    frame = cv2.imdecode(np.frombuffer(response.content, dtype=np.uint8), 
                                        cv2.IMREAD_COLOR)
                    if frame is not None:
                        # 转换为RGB格式（Qt使用RGB，OpenCV默认BGR）
                        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                        self.frame_updated.emit(frame)
                # 控制帧率
                time.sleep(0.05)  # 约20fps
            except Exception as e:
                print(f"视频流获取错误: {e}")
                time.sleep(1)  # 出错时等待1秒再重试
    
    def stop(self):
        self.running = False
        self.wait()

# 3D坐标计算线程（模拟）
class CoordinateCalculationThread(QThread):
    coordinates_updated = pyqtSignal(float, float, float)
    
    def __init__(self):
        super().__init__()
        self.running = False
        self.t = 0  # 用于生成连续变化的坐标
    
    def run(self):
        self.running = True
        while self.running:
            # 生成连续变化的坐标（模拟从图像计算得到）
            x = np.sin(self.t) * 0.5
            y = np.cos(self.t) * 0.5
            z = np.sin(self.t * 0.7) * 0.3
            
            self.coordinates_updated.emit(x, y, z)
            self.t += 0.05
            
            # 控制更新频率
            time.sleep(0.5)
    
    def stop(self):
        self.running = False
        self.wait()

# OpenGL 3D渲染部件
class GLWidget(QGLWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.x = 0.0
        self.y = 0.0
        self.z = 0.0
        self.rotation_x = 30
        self.rotation_y = 45
        self.last_pos = None
        
    def initializeGL(self):
        # 设置背景色为黑色
        glClearColor(0.1, 0.1, 0.1, 1)
        # 启用深度测试
        glEnable(GL_DEPTH_TEST)
        # 设置光照
        self.setup_lighting()
        
    def setup_lighting(self):
        glEnable(GL_LIGHTING)
        glEnable(GL_LIGHT0)
        
        # 光源位置和颜色
        light_pos = [1.0, 1.0, 1.0, 0.0]  # 方向光
        light_ambient = [0.2, 0.2, 0.2, 1.0]
        light_diffuse = [1.0, 1.0, 1.0, 1.0]
        light_specular = [1.0, 1.0, 1.0, 1.0]
        
        glLightfv(GL_LIGHT0, GL_POSITION, light_pos)
        glLightfv(GL_LIGHT0, GL_AMBIENT, light_ambient)
        glLightfv(GL_LIGHT0, GL_DIFFUSE, light_diffuse)
        glLightfv(GL_LIGHT0, GL_SPECULAR, light_specular)
    
    def resizeGL(self, width, height):
        # 设置视口
        glViewport(0, 0, width, height)
        # 设置透视投影
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        gluPerspective(45, width / height, 0.1, 50.0)
        
    def paintGL(self):
        # 清除颜色和深度缓冲区
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        
        # 设置模型视图矩阵
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()
        # 相机位置
        gluLookAt(0, 0, 2,  # 相机位置
                  0, 0, 0,  # 目标点
                  0, 1, 0)  # 上方向
        
        # 应用旋转
        glRotatef(self.rotation_x, 1, 0, 0)
        glRotatef(self.rotation_y, 0, 1, 0)
        
        # 绘制坐标系
        self.draw_coordinate_system()
        
        # 绘制点
        self.draw_point()
        
        # 刷新
        glFlush()
    
    def draw_coordinate_system(self):
        # 绘制网格平面
        glColor3f(0.3, 0.3, 0.3)
        glBegin(GL_LINES)
        for i in range(-10, 11):
            # 水平线
            glVertex3f(-1.0, 0.0, i * 0.1)
            glVertex3f(1.0, 0.0, i * 0.1)
            # 垂直线
            glVertex3f(i * 0.1, 0.0, -1.0)
            glVertex3f(i * 0.1, 0.0, 1.0)
        glEnd()
        
        # X轴（红色）
        glColor3f(1, 0, 0)
        glBegin(GL_LINES)
        glVertex3f(0, 0, 0)
        glVertex3f(1, 0, 0)
        glEnd()
        
        # Y轴（绿色）
        glColor3f(0, 1, 0)
        glBegin(GL_LINES)
        glVertex3f(0, 0, 0)
        glVertex3f(0, 1, 0)
        glEnd()
        
        # Z轴（蓝色）
        glColor3f(0, 0, 1)
        glBegin(GL_LINES)
        glVertex3f(0, 0, 0)
        glVertex3f(0, 0, 1)
        glEnd()
    
    def draw_point(self):
        # 绘制点（黄色）
        glColor3f(1, 1, 0)
        glPointSize(10)
        glBegin(GL_POINTS)
        glVertex3f(self.x, self.y, self.z)
        glEnd()
        
        # 绘制点到原点的连接线
        glColor3f(0.5, 0.5, 0.5)
        glBegin(GL_LINES)
        glVertex3f(0, 0, 0)
        glVertex3f(self.x, self.y, self.z)
        glEnd()
    
    def update_coordinates(self, x, y, z):
        self.x = x
        self.y = y
        self.z = z
        self.updateGL()
    
    def mousePressEvent(self, event):
        self.last_pos = event.pos()
    
    def mouseMoveEvent(self, event):
        if self.last_pos:
            dx = event.x() - self.last_pos.x()
            dy = event.y() - self.last_pos.y()
            
            self.rotation_y += dx
            self.rotation_x += dy
            
            self.last_pos = event.pos()
            self.updateGL()

# 主窗口
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.init_ui()
        
    def init_ui(self):
        # 设置窗口标题和大小
        self.setWindowTitle('视频流与3D坐标可视化')
        self.setGeometry(100, 100, 1200, 600)
        
        # 创建中心部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 主布局（水平布局）
        main_layout = QHBoxLayout(central_widget)
        
        # 左侧：视频显示区域
        video_frame = QFrame()
        video_frame.setFrameShape(QFrame.StyledPanel)
        video_layout = QVBoxLayout(video_frame)
        
        self.video_label = QLabel('视频流加载中...')
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setMinimumSize(640, 480)
        video_layout.addWidget(self.video_label)
        
        # 右侧：3D显示区域
        gl_frame = QFrame()
        gl_frame.setFrameShape(QFrame.StyledPanel)
        gl_layout = QVBoxLayout(gl_frame)
        
        self.gl_widget = GLWidget()
        self.gl_widget.setMinimumSize(640, 480)
        gl_layout.addWidget(self.gl_widget)
        
        # 坐标显示标签
        self.coord_label = QLabel('坐标: (0.0, 0.0, 0.0)')
        self.coord_label.setAlignment(Qt.AlignCenter)
        gl_layout.addWidget(self.coord_label)
        
        # 添加到主布局
        main_layout.addWidget(video_frame, 1)
        main_layout.addWidget(gl_frame, 1)
        
        # 初始化视频流线程
        self.video_thread = VideoStreamThread("http://192.168.0.39:8080/video_feed")
        self.video_thread.frame_updated.connect(self.update_video_frame)
        
        # 初始化坐标计算线程
        self.coord_thread = CoordinateCalculationThread()
        self.coord_thread.coordinates_updated.connect(self.update_coordinates)
        
        # 启动线程
        self.video_thread.start()
        self.coord_thread.start()
    
    def update_video_frame(self, frame):
        # 将OpenCV帧转换为Qt图像并显示
        height, width, channel = frame.shape
        bytes_per_line = channel * width
        q_image = QImage(frame.data, width, height, bytes_per_line, QImage.Format_RGB888)
        self.video_label.setPixmap(QPixmap.fromImage(q_image).scaled(
            self.video_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
    
    def update_coordinates(self, x, y, z):
        # 更新3D视图中的坐标点
        self.gl_widget.update_coordinates(x, y, z)
        # 更新坐标显示文本
        self.coord_label.setText(f'坐标: ({x:.2f}, {y:.2f}, {z:.2f})')
    
    def closeEvent(self, event):
        # 停止线程
        self.video_thread.stop()
        self.coord_thread.stop()
        event.accept()

if __name__ == '__main__':
    # 确保中文显示正常
    import matplotlib
    matplotlib.rcParams["font.family"] = ["SimHei", "WenQuanYi Micro Hei", "Heiti TC"]
    
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
