import numpy as np
from PyQt6.QtOpenGLWidgets import QOpenGLWidget
from PyQt6.QtCore import QPoint

class GLWidget(QOpenGLWidget):
    """OpenGL 3D渲染部件"""
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
        self.probe_s_height = self.sphere_radius * 10
        self.probe_s_slices = 32
        self.probe_s_stacks = 1
        
        # 固定圆锥体参数及位置
        self.probe_t_base_radius = 0.06
        self.probe_t_height = self.sphere_radius * 5
        self.probe_t_slices = 32
        self.probe_t_stacks = 1
        
        # PROBE_TARGET - 预设心脏位置
        self.preset_positions = [
            (1,1,0),    # 位置1
        ]

        self.probe_t_x = self.preset_positions[0][0]  # 固定圆锥X坐标
        self.probe_t_y = self.preset_positions[0][1]   # 固定圆锥Y坐标
        self.probe_t_z = self.preset_positions[0][2]   # 固定圆锥Z坐标
        
        # 绿色圆锥参数（根据旋转矩阵计算位置）
        self.probe_g_base_radius = 0.06
        self.probe_g_height = self.probe_t_height * 1.5
        self.probe_g_slices = 32
        self.probe_g_stacks = 1
        self.probe_g_x = 0.0
        self.probe_g_y = 0.0
        self.probe_g_z = 0.0
        self.rotation_matrix = None  # 存储旋转矩阵
    
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
        self.draw_probe_g()  # 绘制绿色圆锥
        
        glFlush()
    
    def draw_coordinate_system(self):
        from OpenGL.GL import (glColor3f, glBegin, GL_LINES, glVertex3f, glEnd,
                              glDisable, GL_LIGHTING, glEnable)
        
        # 禁用光照以确保网格显示为纯灰色
        glDisable(GL_LIGHTING)
        glColor3f(0.5, 0.5, 0.5)  # 灰色网格
        glBegin(GL_LINES)
        for i in range(-10, 11):
            glVertex3f(-1.0, 0.0, i * 0.1)
            glVertex3f(1.0, 0.0, i * 0.1)
            glVertex3f(i * 0.1, 0.0, -1.0)
            glVertex3f(i * 0.1, 0.0, 1.0)
        glEnd()
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
    
    # 绘制固定的圆锥体（红色）- 尖端在中心
    def draw_probe_t(self):
        from OpenGL.GL import (glMaterialfv, GL_FRONT, GL_AMBIENT_AND_DIFFUSE,
                              GL_SPECULAR, GL_SHININESS, glPushMatrix, 
                              glTranslatef, glRotatef, glPopMatrix)
        from OpenGL.GLUT import glutSolidCone
        
        # 计算从中心指向位置的方向向量
        position_dir = np.array([self.probe_t_x, self.probe_t_y, self.probe_t_z])
        if np.linalg.norm(position_dir) < 0.001:
            return
        position_dir = position_dir / np.linalg.norm(position_dir)
        
        # 红色固定圆锥材质
        glMaterialfv(GL_FRONT, GL_AMBIENT_AND_DIFFUSE, [1.0, 0.0, 0.0, 1.0])  # 红色
        glMaterialfv(GL_FRONT, GL_SPECULAR, [0.9, 0.9, 0.9, 1.0])
        glMaterialfv(GL_FRONT, GL_SHININESS, 30.0)
        
        glPushMatrix()
        # 先平移到中心（尖端在中心）
        glTranslatef(0.0, 0.0, 0.0)
        # 旋转使圆锥指向位置方向（Z轴正方向指向位置）
        self.rotate_to_direction(position_dir)
        # 沿Z轴负方向平移高度，使尖端在中心，底部在位置方向
        glTranslatef(0.0, 0.0, -self.probe_t_height)
        glutSolidCone(
            self.probe_t_base_radius,
            self.probe_t_height,
            self.probe_t_slices,
            self.probe_t_stacks
        )
        glPopMatrix()
    
    # 绘制绿色圆锥体（根据旋转矩阵计算位置）- 尖端在中心
    def draw_probe_g(self):
        from OpenGL.GL import (glMaterialfv, GL_FRONT, GL_AMBIENT_AND_DIFFUSE,
                              GL_SPECULAR, GL_SHININESS, glPushMatrix, 
                              glTranslatef, glRotatef, glPopMatrix)
        from OpenGL.GLUT import glutSolidCone
        
        if self.rotation_matrix is None:
            return
        
        # 直接使用旋转矩阵的第三列（Z轴方向）作为方向向量
        # 这与红色圆锥使用 (probe_t_x, probe_t_y, probe_t_z) 作为方向向量的逻辑一致
        position_dir = np.array([
            self.rotation_matrix[0, 2],
            self.rotation_matrix[1, 2],
            self.rotation_matrix[2, 2]
        ])
        
        if np.linalg.norm(position_dir) < 0.001:
            return
        position_dir = position_dir / np.linalg.norm(position_dir)
        
        # 绿色圆锥材质
        glMaterialfv(GL_FRONT, GL_AMBIENT_AND_DIFFUSE, [0.0, 1.0, 0.0, 1.0])  # 绿色
        glMaterialfv(GL_FRONT, GL_SPECULAR, [0.9, 0.9, 0.9, 1.0])
        glMaterialfv(GL_FRONT, GL_SHININESS, 30.0)
        
        glPushMatrix()
        # 先平移到中心（尖端在中心）
        glTranslatef(0.0, 0.0, 0.0)
        # 旋转使圆锥指向位置方向（Z轴正方向指向位置）
        self.rotate_to_direction(position_dir)
        # 沿Z轴负方向平移高度，使尖端在中心，底部在位置方向
        glTranslatef(0.0, 0.0, -self.probe_g_height)
        glutSolidCone(
            self.probe_g_base_radius,
            self.probe_g_height,
            self.probe_g_slices,
            self.probe_g_stacks
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
    
    def update_rotation_matrix(self, rotation_matrix):
        """更新旋转矩阵，用于计算绿色圆锥位置"""
        self.rotation_matrix = rotation_matrix
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

