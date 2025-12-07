from PyQt6.QtWidgets import QSplashScreen
from PyQt6.QtGui import QPixmap, QGuiApplication, QPainter, QFont
from PyQt6.QtCore import Qt

class SplashScreen(QSplashScreen):
    """启动Logo显示类"""
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

