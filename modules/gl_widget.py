try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    print("Warning: numpy not available, 3D rendering will be limited")

from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtCore import QPoint, QTimer
from .config import (
    get_3d_view_rotation,
    save_3d_view_rotation,
    get_use_dummy_3d,
    get_dummy_path,
    get_fps,
)

class GLWidget(QOpenGLWidget):
    """OpenGL 3D渲染部件"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.x = 0.0
        self.y = 0.0
        self.z = 0.0

        # 从配置文件加载视角角度
        self.rotation_x, self.rotation_y = get_3d_view_rotation()

        self.last_pos = QPoint()
        self.setMinimumSize(640, 480)

        # 控制红色矩形显示的标志
        self.show_red_rectangle = True
        
        # 球体参数（中心红色球体）
        self.sphere_radius = 0.1
        self.sphere_slices = 32
        self.sphere_stacks = 32
        
        # 移动圆锥体参数
        self.probe_s_base_radius = 0.06
        self.probe_s_height = self.sphere_radius * 10
        self.probe_s_slices = 32
        self.probe_s_stacks = 1
        # 黄探头改为长方体（起点原点，终点当前坐标）
        self.probe_s_width = 0.05
        self.probe_s_thickness = 0.02
        
        # 固定圆锥体参数及位置
        self.probe_t_base_radius = 0.06
        self.probe_t_height = self.sphere_radius * 5
        self.probe_t_slices = 32
        self.probe_t_stacks = 1
        
        # PROBE_TARGET - 预设心脏位置
        # 固定圆锥放置在 X 轴正向，指向中心球体
        self.preset_positions = [
            (1, 0, 0),    # 位置1：沿 X 轴
        ]

        self.probe_t_x = self.preset_positions[0][0]  # 固定圆锥X坐标
        self.probe_t_y = self.preset_positions[0][1]   # 固定圆锥Y坐标
        self.probe_t_z = self.preset_positions[0][2]   # 固定圆锥Z坐标

        # dummy_path 模式下由内部定时器推黄探头；否则由 MainWindow 用 Viper 位姿 update_coordinates
        self._dummy_enabled = bool(get_use_dummy_3d())
        self._dummy_points = []
        self._dummy_idx = 0
        self._dummy_timer = None
        if self._dummy_enabled:
            self._load_dummy_points()
            self._start_dummy_playback()


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

    def _load_dummy_points(self):
        """加载 dummy_path.txt 的坐标点。"""
        path = get_dummy_path()
        points = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    raw = line.strip()
                    if not raw:
                        continue
                    parts = [p.strip() for p in raw.split(",")]
                    if len(parts) != 3:
                        continue
                    try:
                        x, y, z = float(parts[0]), float(parts[1]), float(parts[2])
                    except ValueError:
                        continue
                    points.append((x, y, z))
        except Exception as e:
            print(f"加载 dummy_path 失败: {e}")
            points = []

        self._dummy_points = points
        self._dummy_idx = 0

    def _start_dummy_playback(self):
        """按 FPS 定时推进 dummy 坐标。"""
        if not self._dummy_points:
            print("dummy 模式启用，但 dummy_path 无有效点")
            return
        interval_ms = int(1000.0 / max(float(get_fps()), 1.0))
        self._dummy_timer = QTimer(self)
        self._dummy_timer.timeout.connect(self._advance_dummy_point)
        self._dummy_timer.start(interval_ms)
        self._advance_dummy_point()

    def _advance_dummy_point(self):
        if not self._dummy_enabled or not self._dummy_points:
            return
        x, y, z = self._dummy_points[self._dummy_idx]
        self.x = x
        self.y = y
        self.z = z
        self._dummy_idx = (self._dummy_idx + 1) % len(self._dummy_points)
        self.update()
    
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
        from OpenGL.GLUT import glutSolidSphere
        
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()
        # 调整相机位置，从斜上方观察，能看到X和Y轴的锥面
        # 相机位置：(2, 2, 2) - 从斜上方观察
        # 观察目标：(0, 0, 0) - 原点
        # 上方向：(0, 1, 0) - Y轴正方向
        gluLookAt(2, 2, 2, 0, 0, 0, 0, 1, 0)
        
        glRotatef(self.rotation_x, 1, 0, 0)
        glRotatef(self.rotation_y, 0, 1, 0)
        
        self.draw_coordinate_system()
        self.draw_center_sphere()
        self.draw_probe_s()
        if self.show_red_rectangle:
            self.draw_probe_t()

        glFlush()
    
    def draw_coordinate_system(self):
        from OpenGL.GL import (glColor3f, glBegin, GL_LINES, glVertex3f, glEnd,
                              glDisable, GL_LIGHTING, glEnable, glPushMatrix,
                              glTranslatef, glPopMatrix, glRotatef)
        from OpenGL.GLUT import glutSolidCone
        
        # 禁用光照，网格与坐标轴使用纯色显示
        glDisable(GL_LIGHTING)

        # 1) 地面网格（XZ 平面）
        glColor3f(0.5, 0.5, 0.5)  # 灰色网格
        glBegin(GL_LINES)
        for i in range(-10, 11):
            glVertex3f(-1.0, 0.0, i * 0.1)
            glVertex3f(1.0, 0.0, i * 0.1)
            glVertex3f(i * 0.1, 0.0, -1.0)
            glVertex3f(i * 0.1, 0.0, 1.0)
        glEnd()

        # 2) 三维坐标轴（X红 / Y绿 / Z蓝）
        axis_len = 1.1
        cone_base = 0.02
        cone_h = 0.08

        # X 轴
        glColor3f(1.0, 0.2, 0.2)
        glBegin(GL_LINES)
        glVertex3f(0.0, 0.0, 0.0)
        glVertex3f(axis_len, 0.0, 0.0)
        glEnd()
        glPushMatrix()
        glTranslatef(axis_len, 0.0, 0.0)
        glRotatef(90.0, 0.0, 1.0, 0.0)  # 将默认 +Z 箭头转到 +X
        glutSolidCone(cone_base, cone_h, 20, 1)
        glPopMatrix()

        # Y 轴
        glColor3f(0.2, 1.0, 0.2)
        glBegin(GL_LINES)
        glVertex3f(0.0, 0.0, 0.0)
        glVertex3f(0.0, axis_len, 0.0)
        glEnd()
        glPushMatrix()
        glTranslatef(0.0, axis_len, 0.0)
        glRotatef(-90.0, 1.0, 0.0, 0.0)  # 将默认 +Z 箭头转到 +Y
        glutSolidCone(cone_base, cone_h, 20, 1)
        glPopMatrix()

        # Z 轴
        glColor3f(0.2, 0.4, 1.0)
        glBegin(GL_LINES)
        glVertex3f(0.0, 0.0, 0.0)
        glVertex3f(0.0, 0.0, axis_len)
        glEnd()
        glPushMatrix()
        glTranslatef(0.0, 0.0, axis_len)
        glutSolidCone(cone_base, cone_h, 20, 1)  # 默认沿 +Z
        glPopMatrix()

        glEnable(GL_LIGHTING)  # 重新启用光照
           
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
    
    # 绘制黄色长方体：从原点延伸到当前坐标
    def draw_probe_s(self):
        from OpenGL.GL import (glMaterialfv, GL_FRONT, GL_AMBIENT_AND_DIFFUSE,
                              GL_SPECULAR, GL_SHININESS, glPushMatrix, 
                              glTranslatef, glPopMatrix,
                              glBegin, glEnd, glVertex3f, glNormal3f, GL_QUADS)
        
        # 当前点向量（原点 -> 当前坐标）
        if not HAS_NUMPY:
            return

        pos = np.array([float(self.x), float(self.y), float(self.z)], dtype=float)
        n = float(np.linalg.norm(pos))
        if n < 1e-5:
            return
        direction = pos / n
        
        # 黄色材质
        glMaterialfv(GL_FRONT, GL_AMBIENT_AND_DIFFUSE, [1.0, 1.0, 0.0, 1.0])
        glMaterialfv(GL_FRONT, GL_SPECULAR, [0.8, 0.8, 0.8, 1.0])
        glMaterialfv(GL_FRONT, GL_SHININESS, 30.0)
        
        # 以原点为起点，沿方向延伸长度 n
        rect_length = n
        hw = self.probe_s_width / 2.0
        hl = rect_length / 2.0
        ht = self.probe_s_thickness / 2.0

        glPushMatrix()
        glTranslatef(0.0, 0.0, 0.0)
        self.rotate_to_direction(direction)
        # 将长方体中心移动到长度中点，使其一端对齐原点
        glTranslatef(0.0, 0.0, rect_length / 2.0)

        # Front face (+Z)
        glBegin(GL_QUADS)
        glNormal3f(0.0, 0.0, 1.0)
        glVertex3f(-hw, -ht, hl)
        glVertex3f(hw, -ht, hl)
        glVertex3f(hw, ht, hl)
        glVertex3f(-hw, ht, hl)
        glEnd()

        # Back face (-Z)
        glBegin(GL_QUADS)
        glNormal3f(0.0, 0.0, -1.0)
        glVertex3f(-hw, -ht, -hl)
        glVertex3f(-hw, ht, -hl)
        glVertex3f(hw, ht, -hl)
        glVertex3f(hw, -ht, -hl)
        glEnd()

        # Top face
        glBegin(GL_QUADS)
        glNormal3f(0.0, 1.0, 0.0)
        glVertex3f(-hw, ht, -hl)
        glVertex3f(-hw, ht, hl)
        glVertex3f(hw, ht, hl)
        glVertex3f(hw, ht, -hl)
        glEnd()

        # Bottom face
        glBegin(GL_QUADS)
        glNormal3f(0.0, -1.0, 0.0)
        glVertex3f(-hw, -ht, -hl)
        glVertex3f(hw, -ht, -hl)
        glVertex3f(hw, -ht, hl)
        glVertex3f(-hw, -ht, hl)
        glEnd()

        # Left face
        glBegin(GL_QUADS)
        glNormal3f(-1.0, 0.0, 0.0)
        glVertex3f(-hw, -ht, -hl)
        glVertex3f(-hw, -ht, hl)
        glVertex3f(-hw, ht, hl)
        glVertex3f(-hw, ht, -hl)
        glEnd()

        # Right face
        glBegin(GL_QUADS)
        glNormal3f(1.0, 0.0, 0.0)
        glVertex3f(hw, -ht, -hl)
        glVertex3f(hw, ht, -hl)
        glVertex3f(hw, ht, hl)
        glVertex3f(hw, -ht, hl)
        glEnd()

        glPopMatrix()
    
    # 绘制固定的圆锥体（红色）- 尖端在中心
    def draw_probe_t(self):
        from OpenGL.GL import (glMaterialfv, GL_FRONT, GL_AMBIENT_AND_DIFFUSE,
                              GL_SPECULAR, GL_SHININESS, glPushMatrix, 
                              glTranslatef, glRotatef, glPopMatrix)
        from OpenGL.GL import glBegin, glEnd, glVertex3f, glNormal3f, GL_QUADS
        # draw a rectangular tail (thin box) instead of cone
        
        # 计算从中心指向位置的方向向量
        if not HAS_NUMPY:
            return

        position_dir = np.array([self.probe_t_x, self.probe_t_y, self.probe_t_z])
        if np.linalg.norm(position_dir) < 0.001:
            return
        position_dir = position_dir / np.linalg.norm(position_dir)
        
        # 红色尾翼（长方形）参数
        rect_length = 0.3  # how far the rectangle extends from the center
        rect_width = 0.12
        rect_thickness = 0.02

        # 材质（使用同样的材质设置）
        glMaterialfv(GL_FRONT, GL_AMBIENT_AND_DIFFUSE, [1.0, 0.0, 0.0, 1.0])  # 红色
        glMaterialfv(GL_FRONT, GL_SPECULAR, [0.9, 0.9, 0.9, 1.0])
        glMaterialfv(GL_FRONT, GL_SHININESS, 30.0)

        glPushMatrix()
        # place at center and orient so local +Z points toward the position_dir
        glTranslatef(0.0, 0.0, 0.0)
        self.rotate_to_direction(position_dir)
        # move the rectangle so its inner edge touches the center and it extends outward along +Z
        glTranslatef(0.0, 0.0, rect_length / 2.0)

        # draw a thin box centered at origin with size (rect_width x rect_thickness x rect_length)
        hw = rect_width / 2.0
        hl = rect_length / 2.0
        ht = rect_thickness / 2.0

        # Front face (facing +Z)
        glBegin(GL_QUADS)
        glNormal3f(0.0, 0.0, 1.0)
        glVertex3f(-hw, -ht, hl)
        glVertex3f(hw, -ht, hl)
        glVertex3f(hw, ht, hl)
        glVertex3f(-hw, ht, hl)
        glEnd()

        # Back face (facing -Z)
        glBegin(GL_QUADS)
        glNormal3f(0.0, 0.0, -1.0)
        glVertex3f(-hw, -ht, -hl)
        glVertex3f(-hw, ht, -hl)
        glVertex3f(hw, ht, -hl)
        glVertex3f(hw, -ht, -hl)
        glEnd()

        # Top face
        glBegin(GL_QUADS)
        glNormal3f(0.0, 1.0, 0.0)
        glVertex3f(-hw, ht, -hl)
        glVertex3f(-hw, ht, hl)
        glVertex3f(hw, ht, hl)
        glVertex3f(hw, ht, -hl)
        glEnd()

        # Bottom face
        glBegin(GL_QUADS)
        glNormal3f(0.0, -1.0, 0.0)
        glVertex3f(-hw, -ht, -hl)
        glVertex3f(hw, -ht, -hl)
        glVertex3f(hw, -ht, hl)
        glVertex3f(-hw, -ht, hl)
        glEnd()

        # Left face
        glBegin(GL_QUADS)
        glNormal3f(-1.0, 0.0, 0.0)
        glVertex3f(-hw, -ht, -hl)
        glVertex3f(-hw, -ht, hl)
        glVertex3f(-hw, ht, hl)
        glVertex3f(-hw, ht, -hl)
        glEnd()

        # Right face
        glBegin(GL_QUADS)
        glNormal3f(1.0, 0.0, 0.0)
        glVertex3f(hw, -ht, -hl)
        glVertex3f(hw, ht, -hl)
        glVertex3f(hw, ht, hl)
        glVertex3f(hw, -ht, hl)
        glEnd()

        glPopMatrix()
    
    # 设置固定圆锥到指定位置
    def set_probe_t_position(self, position_index):
        if 0 <= position_index < len(self.preset_positions):
            self.probe_t_x, self.probe_t_y, self.probe_t_z = self.preset_positions[position_index]
            self.update()
    
    # 辅助方法：计算旋转角度使锥体指向目标方向
    def rotate_to_direction(self, target_dir):
        from OpenGL.GL import glRotatef

        if not HAS_NUMPY:
            return

        default_dir = np.array([0, 0, -1])
        cross = np.cross(default_dir, target_dir)
        cross_norm = np.linalg.norm(cross)

        dot = np.dot(default_dir, target_dir)
        angle = np.arccos(np.clip(dot, -1.0, 1.0)) * 180 / np.pi

        if cross_norm > 0.001:
            cross = cross / cross_norm
            glRotatef(angle, cross[0], cross[1], cross[2])
    
    def update_coordinates(self, x, y, z):
        # dummy_path 模式由本控件内部定时器驱动，不接受外部 Viper 坐标
        if self._dummy_enabled:
            return
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)
        self.update()
    
    def set_show_red_rectangle(self, show: bool):
        """设置是否显示红色矩形。"""
        self.show_red_rectangle = show
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

        # 保存当前视角到配置文件
        try:
            save_3d_view_rotation(self.rotation_x, self.rotation_y)
        except Exception as e:
            # 保存失败时不影响用户操作，只在控制台输出错误
            print(f"保存3D视角失败: {e}")

