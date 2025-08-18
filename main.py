import sys
import time
import numpy as np
import cv2
import requests
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                           QHBoxLayout, QLabel, QFrame, QSplashScreen, QPushButton)
from PyQt6.QtGui import QImage, QPixmap, QGuiApplication, QPainter, QFont, QPen, QBrush, QPolygonF
from PyQt6.QtCore import QThread, pyqtSignal, Qt, QPoint, QTimer, QRectF, QPointF
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from datetime import datetime
import os 


FRAME_W = 1920
FRAME_H = 1088
FRAME_SIZE_NV12 = FRAME_W * FRAME_H *3 //2
FULL_SCREEN = True
SPLASH = 'logo.jpg'
SAVE_CAPTURE = False
SAVE_ROOT = '/data/capture'
DUMMY_FRAME = 'dummy_frames.txt'
DUMMY_PATH = 'dummy_path.txt'

# 启动Logo显示类
class SplashScreen(QSplashScreen):
    def __init__(self, logo_path=None):
        if logo_path:
            pixmap = QPixmap(logo_path)
        else:
            pixmap = QPixmap(800, 600)
            pixmap.fill(Qt.GlobalColor.black)
            painter = QPainter(pixmap)
            painter.setPen(Qt.GlobalColor.white)
            
            # 设置字体大小
            font = painter.font()
            font.setPointSize(48)
            painter.setFont(font)
            
            painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "正在加载超声导航工具...")
            painter.end()
            
        super().__init__(pixmap, Qt.WindowType.FramelessWindowHint)
        self.move((QGuiApplication.primaryScreen().geometry().width() - self.width()) // 2,
                  (QGuiApplication.primaryScreen().geometry().height() - self.height()) // 2)

# 视频流获取线程
class VideoStreamThread(QThread):
    frame_updated = pyqtSignal(np.ndarray)
    
    def __init__(self, url):
        super().__init__()
        self.url = url
        self.running = False
        if SAVE_CAPTURE:
            output_dir = os.path.join(SAVE_ROOT,'capture',datetime.now().strftime("%Y%m%d_%H%M%S"))
            os.makedirs(output_dir, exist_ok=True)
            print("save capture to:", output_dir)
            self.output_dir = output_dir
        
    def run(self):
        self.running = True
        dummy_filelist = []
        index = 0
        if os.path.exists(DUMMY_FRAME):
            with open(DUMMY_FRAME, 'r') as fp:
                dummy_filelist = fp.readlines()

        while self.running:
            try:
                if len(dummy_filelist):
                    file = dummy_filelist[index].removesuffix('\n')
                    file = os.path.join(SAVE_ROOT, file)
                    print("load_dummy", file)
                    frame = cv2.imread(file)
                    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    self.frame_updated.emit(frame_rgb)
                    index += 1
                    time.sleep(0.1)

                else:
                    response = requests.get(self.url, timeout=5)
                    if response.status_code == 200:
                        current_time =datetime.now().strftime("%H%M%S_%f")[:-3]
                        if len(response.content) != FRAME_SIZE_NV12:
                            print(f"数据大小不匹配，期望: {FRAME_SIZE_NV12}, 实际: {len(response.content)}")
                            continue
                        
                        frame_data = np.frombuffer(response.content, dtype=np.uint8)
                        frame_data = frame_data.reshape((FRAME_H*3//2), FRAME_W)
                        frame_rgb = cv2.cvtColor(frame_data, cv2.COLOR_YUV2RGB_NV12)
                        # frame_rgb = processor.process_frame(frame_data, FRAME_W, FRAME_H)
                        self.frame_updated.emit(frame_rgb)
                        print(f"{current_time} 正在获取视频帧...".format(current_time), end='\r')
                        if SAVE_CAPTURE:
                            frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
                            filepath = os.path.join(self.output_dir, current_time+'.jpg')
                            cv2.imwrite(filepath, frame_bgr)
                    # t_total = time.time()-t_start
                    # if t_total < 0.1:
                    #     time.sleep(0.1-t_total)
                    # elif t_total<0.2:
                    #     time.sleep(0.2-t_total)
                    # else:
                    #     time.sleep(0.5)
            except Exception as e:
                # print(f"视频流获取错误: {e}")
                time.sleep(5)
    
    def stop(self):
        self.running = False
        self.wait()

# 3D坐标计算线程
class CoordinateCalculationThread(QThread):
    coordinates_updated = pyqtSignal(float, float, float)
    
    def __init__(self):
        super().__init__()
        self.running = False
        self.path = [[2,2,2]]
        self.index = 0

        if os.path.exists(DUMMY_PATH):
            with open(DUMMY_PATH) as fp:
                tmp = []
                for line in fp.readlines():
                    data = line.removesuffix('\n').split(',')
                    tmp.append([float(data[0]),float(data[1]),float(data[2])])
                self.path = tmp
        self.total = len(tmp)
            
    def run(self):
        self.running = True
        while self.running:
            if self.index < self.total:
                x,y,z = self.path[self.index]
                self.coordinates_updated.emit(x, y, z)
                self.index += 1

            time.sleep(0.2)
    
    def stop(self):
        self.running = False
        self.wait()

    def reset(self):
        self.index = 0

# 方向指示显示部件
class DirectionIndicator(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.moving_pos = (0, 0, 0)
        self.fixed_pos = (0.3, 0.3, 0.0)
        self.setMinimumSize(200, 200)
        self.setStyleSheet("background-color: #222222;")
    
    def update_positions(self, moving_pos, fixed_pos):
        self.moving_pos = moving_pos
        self.fixed_pos = fixed_pos
        self.update()
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # 绘制背景和坐标系
        rect = self.rect()
        center_x, center_y = rect.width() // 2, rect.height() // 2
        
        # 绘制网格
        painter.setPen(QPen(Qt.GlobalColor.gray, 1))
        for i in range(-5, 6):
            x = center_x + i * 20
            painter.drawLine(x, center_y - 100, x, center_y + 100)
            y = center_y + i * 20
            painter.drawLine(center_x - 100, y, center_x + 100, y)
        
        # 绘制坐标轴
        painter.setPen(QPen(Qt.GlobalColor.white, 2))
        painter.drawLine(center_x, center_y - 100, center_x, center_y + 100)  # Y轴
        painter.drawLine(center_x - 100, center_y, center_x + 100, center_y)  # X轴
        
        # 计算相对位置
        dx = self.moving_pos[0] - self.fixed_pos[0]
        dy = self.moving_pos[1] - self.fixed_pos[1]
        dz = self.moving_pos[2] - self.fixed_pos[2]
        
        # 归一化方向向量
        length = np.sqrt(dx**2 + dy**2 + dz**2)
        if length < 0.001:
            return
            
        dx_norm = dx / length
        dy_norm = dy / length
        
        # 绘制固定圆锥位置（白色）
        painter.setBrush(QBrush(Qt.GlobalColor.white))
        painter.drawEllipse(center_x - 5, center_y - 5, 10, 10)
        
        # 绘制移动运动圆锥位置（黄色）
        painter.setBrush(Qt.GlobalColor.yellow)
        indicator_x = center_x + int(dx_norm * 80)
        indicator_y = center_y - int(dy_norm * 80)  # Y轴反转，因为屏幕Y轴向下
        painter.drawEllipse(indicator_x - 5, indicator_y - 5, 10, 10)
        
        # 绘制黄色箭头表示方向
        painter.setPen(QPen(Qt.GlobalColor.yellow, 2))
        painter.setBrush(Qt.GlobalColor.yellow)
        
        # 箭头起点（固定圆锥）
        start_x, start_y = center_x, center_y
        # 箭头终点（运动圆锥方向）
        end_x, end_y = indicator_x, indicator_y
        
        # 绘制箭头线
        painter.drawLine(start_x, start_y, end_x, end_y)
        
        # 计算箭头角度
        angle = np.arctan2(end_y - start_y, end_x - start_x) * 180 / np.pi
        
        # 绘制箭头头部
        painter.save()
        painter.translate(end_x, end_y)
        painter.rotate(angle)
        painter.drawPolygon(
            QPolygonF([
                QPointF(0, 0),
                QPointF(-8, -4),
                QPointF(-8, 4)
            ])
        )
        painter.restore()

# OpenGL 3D渲染部件
class GLWidget(QOpenGLWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.x = 0.0
        self.y = 0.0
        self.z = 0.0
        self.rotation_x = 30
        self.rotation_y = 45
        self.last_pos = QPoint()
        self.setMinimumSize(640, 480)
        
        # 球体参数（中心红色球体）
        self.sphere_radius = 0.1
        self.sphere_slices = 32
        self.sphere_stacks = 32
        
        # 移动圆锥体参数
        self.probe_s_base_radius = 0.06
        self.probe_s_height = 0.15
        self.probe_s_slices = 32
        self.probe_s_stacks = 1
        
        # 固定圆锥体参数及位置
        self.probe_t_base_radius = 0.06
        self.probe_t_height = 0.15
        self.probe_t_slices = 32
        self.probe_t_stacks = 1
        
        # PROBE_TARGET
        self.preset_positions = [
            (0.4, 0.2, 0.1),    # 位置1
            (-0.3, 0.4, -0.2),  # 位置2
            (0.1, -0.3, 0.3)    # 位置3
        ]

        self.probe_t_x = self.preset_positions[0][0]  # 固定圆锥X坐标
        self.probe_t_y = self.preset_positions[0][1]   # 固定圆锥Y坐标
        self.probe_t_z = self.preset_positions[0][2]   # 固定圆锥Z坐标
        
        # 方向指示器引用
        self.direction_indicator = None
    
    def set_direction_indicator(self, indicator):
        self.direction_indicator = indicator
    
    def initializeGL(self):
        from OpenGL.GL import glClearColor, glEnable, GL_DEPTH_TEST
        glClearColor(0.1, 0.1, 0.1, 1)
        glEnable(GL_DEPTH_TEST)
        self.setup_lighting()
        
        # 初始化glut
        from OpenGL.GLUT import glutInit
        glutInit()
        
    def setup_lighting(self):
        from OpenGL.GL import (glEnable, GL_LIGHTING, GL_LIGHT0,
                              glLightfv, GL_POSITION, GL_AMBIENT,
                              GL_DIFFUSE, GL_SPECULAR)
                              
        glEnable(GL_LIGHTING)
        glEnable(GL_LIGHT0)
        
        light_pos = [1.0, 1.0, 1.0, 0.0]
        light_ambient = [0.2, 0.2, 0.2, 1.0]
        light_diffuse = [1.0, 1.0, 1.0, 1.0]
        light_specular = [1.0, 1.0, 1.0, 1.0]
        
        glLightfv(GL_LIGHT0, GL_POSITION, light_pos)
        glLightfv(GL_LIGHT0, GL_AMBIENT, light_ambient)
        glLightfv(GL_LIGHT0, GL_DIFFUSE, light_diffuse)
        glLightfv(GL_LIGHT0, GL_SPECULAR, light_specular)
    
    def resizeGL(self, width, height):
        from OpenGL.GL import glViewport, glMatrixMode, glLoadIdentity, GL_PROJECTION
        from OpenGL.GLU import gluPerspective
        
        glViewport(0, 0, width, height)
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        gluPerspective(45, width / height, 0.1, 50.0)
        
    def paintGL(self):
        from OpenGL.GL import (glClear, GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT,
                              glMatrixMode, GL_MODELVIEW, glLoadIdentity,
                              glRotatef, glFlush, glDisable, GL_LIGHTING,
                              glColor3f, glBegin, GL_LINES, glVertex3f, glEnd,
                              glEnable, glMaterialfv, GL_FRONT, GL_AMBIENT_AND_DIFFUSE,
                              GL_SPECULAR, GL_SHININESS, glPushMatrix, glTranslatef,
                              glPopMatrix)
        from OpenGL.GLU import gluLookAt
        from OpenGL.GLUT import glutSolidSphere, glutSolidCone
        
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()
        gluLookAt(0, 0, 2, 0, 0, 0, 0, 1, 0)
        
        glRotatef(self.rotation_x, 1, 0, 0)
        glRotatef(self.rotation_y, 0, 1, 0)
        
        self.draw_coordinate_system()
        self.draw_center_sphere()
        self.draw_probe_s()
        self.draw_probe_t()
        
        # 更新方向指示器
        if self.direction_indicator:
            self.direction_indicator.update_positions(
                (self.x, self.y, self.z),
                (self.probe_t_x, self.probe_t_y, self.probe_t_z)
            )
        
        glFlush()
    
    def draw_coordinate_system(self):
        from OpenGL.GL import glColor3f, glBegin, GL_LINES, glVertex3f, glEnd
        
        glColor3f(0.3, 0.3, 0.3)
        glBegin(GL_LINES)
        for i in range(-10, 11):
            glVertex3f(-1.0, 0.0, i * 0.1)
            glVertex3f(1.0, 0.0, i * 0.1)
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
    
    def draw_center_sphere(self):
        from OpenGL.GL import (glMaterialfv, GL_FRONT, GL_AMBIENT_AND_DIFFUSE,
                              GL_SPECULAR, GL_SHININESS, glPushMatrix, 
                              glTranslatef, glPopMatrix)
        from OpenGL.GLUT import glutSolidSphere
        
        # 红色球体材质
        glMaterialfv(GL_FRONT, GL_AMBIENT_AND_DIFFUSE, [1.0, 0.0, 0.0, 1.0])
        glMaterialfv(GL_FRONT, GL_SPECULAR, [0.8, 0.8, 0.8, 1.0])
        glMaterialfv(GL_FRONT, GL_SHININESS, 50.0)
        
        glPushMatrix()
        glTranslatef(0.0, 0.0, 0.0)
        glutSolidSphere(self.sphere_radius, self.sphere_slices, self.sphere_stacks)
        glPopMatrix()
    
    # 绘制移动的圆锥体（指向中心）
    def draw_probe_s(self):
        from OpenGL.GL import (glMaterialfv, GL_FRONT, GL_AMBIENT_AND_DIFFUSE,
                              GL_SPECULAR, GL_SHININESS, glPushMatrix, 
                              glTranslatef, glRotatef, glPopMatrix,
                              glDisable, GL_LIGHTING, glColor3f,
                              glBegin, GL_LINES, glVertex3f, glEnd, glEnable)
        from OpenGL.GLUT import glutSolidCone
        
        # 计算从圆锥到中心的方向向量
        center_dir = np.array([-self.x, -self.y, -self.z])
        if np.linalg.norm(center_dir) < 0.001:
            return
            
        center_dir = center_dir / np.linalg.norm(center_dir)
        
        # 黄色移动圆锥材质
        glMaterialfv(GL_FRONT, GL_AMBIENT_AND_DIFFUSE, [1.0, 1.0, 0.0, 1.0])
        glMaterialfv(GL_FRONT, GL_SPECULAR, [0.8, 0.8, 0.8, 1.0])
        glMaterialfv(GL_FRONT, GL_SHININESS, 30.0)
        
        glPushMatrix()
        glTranslatef(self.x, self.y, self.z)
        self.rotate_to_direction(center_dir)
        glRotatef(180, 0, 1, 0)
        glutSolidCone(
            self.probe_s_base_radius,
            self.probe_s_height,
            self.probe_s_slices,
            self.probe_s_stacks
        )
        glPopMatrix()
        
        # 绘制连接线
        glDisable(GL_LIGHTING)
        glColor3f(0.5, 0.5, 0.5)
        glBegin(GL_LINES)
        glVertex3f(0, 0, 0)
        glVertex3f(self.x, self.y, self.z)
        glEnd()
        glEnable(GL_LIGHTING)
    
    # 绘制固定的圆锥体（白色）
    def draw_probe_t(self):
        from OpenGL.GL import (glMaterialfv, GL_FRONT, GL_AMBIENT_AND_DIFFUSE,
                              GL_SPECULAR, GL_SHININESS, glPushMatrix, 
                              glTranslatef, glRotatef, glPopMatrix)
        from OpenGL.GLUT import glutSolidCone
        
        center_dir = np.array([-self.probe_t_x, -self.probe_t_y, -self.probe_t_z])  
        fixed_direction = center_dir / np.linalg.norm(center_dir)
        
        # 白色固定圆锥材质
        glMaterialfv(GL_FRONT, GL_AMBIENT_AND_DIFFUSE, [1.0, 1.0, 1.0, 1.0])  # 白色
        glMaterialfv(GL_FRONT, GL_SPECULAR, [0.9, 0.9, 0.9, 1.0])
        glMaterialfv(GL_FRONT, GL_SHININESS, 30.0)
        
        glPushMatrix()
        glTranslatef(self.probe_t_x, self.probe_t_y, self.probe_t_z)
        self.rotate_to_direction(fixed_direction)
        glRotatef(180, 0, 1, 0)
        glutSolidCone(
            self.probe_t_base_radius,
            self.probe_t_height,
            self.probe_t_slices,
            self.probe_t_stacks
        )
        glPopMatrix()
    
    # 设置固定圆锥到指定位置
    def set_probe_t_position(self, position_index):
        if 0 <= position_index < len(self.preset_positions):
            self.probe_t_x, self.probe_t_y, self.probe_t_z = self.preset_positions[position_index]
            self.update()
    
    # 辅助方法：计算旋转角度使锥体指向目标方向
    def rotate_to_direction(self, target_dir):
        from OpenGL.GL import glRotatef
        
        default_dir = np.array([0, 0, -1])
        cross = np.cross(default_dir, target_dir)
        cross_norm = np.linalg.norm(cross)
        
        dot = np.dot(default_dir, target_dir)
        angle = np.arccos(np.clip(dot, -1.0, 1.0)) * 180 / np.pi
        
        if cross_norm > 0.001:
            cross = cross / cross_norm
            glRotatef(angle, cross[0], cross[1], cross[2])
    
    def update_coordinates(self, x, y, z):
        self.x = x
        self.y = y
        self.z = z
        self.update()
    
    def mousePressEvent(self, event):
        self.last_pos = event.pos()
    
    def mouseMoveEvent(self, event):
        dx = event.position().x() - self.last_pos.x()
        dy = event.position().y() - self.last_pos.y()
        
        self.rotation_y += dx
        self.rotation_x += dy
        
        self.last_pos = event.pos()
        self.update()

# 主窗口
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.init_ui()
        
    def init_ui(self):
        self.setWindowTitle('心脏超声导航工具')
        self.setGeometry(100, 100, 1400, 700)
        
        # 主布局容器
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        
        # 左侧：视频显示区域
        video_frame = QFrame()
        video_frame.setFrameShape(QFrame.Shape.StyledPanel)
        video_layout = QVBoxLayout(video_frame)
        
        self.video_label = QLabel('视频流加载中...')
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setMinimumSize(640, 480)
        video_layout.addWidget(self.video_label)
        
        # 右侧上半部分：3D显示和方向指示
        right_top = QWidget()
        right_top_layout = QHBoxLayout(right_top)
        
        # 3D显示区域
        gl_frame = QFrame()
        gl_frame.setFrameShape(QFrame.Shape.StyledPanel)
        gl_layout = QVBoxLayout(gl_frame)
        
        self.gl_widget = GLWidget()
        gl_layout.addWidget(self.gl_widget)
        
        self.coord_label = QLabel('坐标: (0.0, 0.0, 0.0)')
        self.coord_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.coord_label.setStyleSheet("color: white; background-color: #333; padding: 5px;")
        gl_layout.addWidget(self.coord_label)
        
        # 方向指示区域
        direction_frame = QFrame()
        direction_frame.setFrameShape(QFrame.Shape.StyledPanel)
        direction_layout = QVBoxLayout(direction_frame)
        
        direction_label = QLabel('相对方向指示')
        direction_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        direction_label.setStyleSheet("color: white; background-color: #444; padding: 5px;")
        
        self.direction_indicator = DirectionIndicator()
        self.gl_widget.set_direction_indicator(self.direction_indicator)
        
        direction_layout.addWidget(direction_label)
        direction_layout.addWidget(self.direction_indicator)
        
        # 组装右侧上半部分
        right_top_layout.addWidget(gl_frame, 3)
        right_top_layout.addWidget(direction_frame, 1)
        
        # 右侧下半部分：按钮控制区域
        button_frame = QFrame()
        button_frame.setFrameShape(QFrame.Shape.StyledPanel)
        button_layout = QHBoxLayout(button_frame)
        
        # 三个位置控制按钮
        self.btn_pos1 = QPushButton("心脏位置 1")
        self.btn_pos2 = QPushButton("心脏位置 2")
        self.btn_pos3 = QPushButton("心脏位置 3")
        
        # 设置按钮样式
        self.btn_pos1.setStyleSheet("padding: 10px; font-size: 14px;")
        self.btn_pos2.setStyleSheet("padding: 10px; font-size: 14px;")
        self.btn_pos3.setStyleSheet("padding: 10px; font-size: 14px;")
        
        # 绑定按钮事件
        self.btn_pos1.clicked.connect(lambda: (
            self.gl_widget.set_probe_t_position(0),
            self.coord_thread.reset()
            ))
        self.btn_pos2.clicked.connect(lambda: self.gl_widget.set_probe_t_position(1))
        self.btn_pos3.clicked.connect(lambda: self.gl_widget.set_probe_t_position(2))
        
        button_layout.addWidget(self.btn_pos1)
        button_layout.addWidget(self.btn_pos2)
        button_layout.addWidget(self.btn_pos3)
        
        # 右侧整体布局
        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.addWidget(right_top, 8)
        right_layout.addWidget(button_frame, 2)
        
        # 添加到主布局
        main_layout.addWidget(video_frame, 3)
        main_layout.addWidget(right_container, 1)
        
        # 初始化视频流线程
        self.video_thread = VideoStreamThread("http://192.168.0.39:8080/raw")
        self.video_thread.frame_updated.connect(self.update_video_frame)
        
        # 初始化坐标计算线程
        self.coord_thread = CoordinateCalculationThread()
        self.coord_thread.coordinates_updated.connect(self.update_coordinates)
        
        # 启动线程
        self.video_thread.start()
        self.coord_thread.start()

        if FULL_SCREEN:
            self.showFullScreen()
        else:
            self.resize(800,600)
    
    def update_video_frame(self, frame):
        height, width, channel = frame.shape
        bytes_per_line = channel * width
        q_image = QImage(frame.data, width, height, bytes_per_line, QImage.Format.Format_RGB888)
        self.video_label.setPixmap(QPixmap.fromImage(q_image).scaled(
            self.video_label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
    
    def update_coordinates(self, x, y, z):
        self.gl_widget.update_coordinates(x, y, z)
        self.coord_label.setText(f'坐标: ({x:.2f}, {y:.2f}, {z:.2f})')
    
    def closeEvent(self, event):
        self.video_thread.stop()
        self.coord_thread.stop()
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            if self.isFullScreen():
                self.showNormal()
            else:
                self.close()

if __name__ == '__main__':
    import matplotlib
    matplotlib.rcParams["font.family"] = ["SimHei", "WenQuanYi Micro Hei", "Heiti TC"]
    
    app = QApplication(sys.argv)

    # 显示启动Logo
    if SPLASH:
        splash = SplashScreen(logo_path=SPLASH)
        splash.show()
        splash.raise_()
    
    app.processEvents()
    # 初始化主窗口
    window = MainWindow()

    if SPLASH:
        window.hide()
        
        # 5秒后显示主窗口
        def show_main_window():
            window.show()
            splash.close()
        
        QTimer.singleShot(5000, show_main_window)
    else:
        window.show()
    
    sys.exit(app.exec())
    