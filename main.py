import sys
import matplotlib
matplotlib.rcParams["font.family"] = ["SimHei", "WenQuanYi Micro Hei", "Heiti TC"]

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from modules import SplashScreen, MainWindow
from modules.config import (
    get_full_screen,
    get_splash_path,
    get_splash_duration,
    get_video_url
)
from modules.logger import get_logger

if __name__ == '__main__':
    logger = get_logger()
    logger.info("=" * 60)
    logger.info("程序启动")
    logger.info("=" * 60)
    
    app = QApplication(sys.argv)
    full_screen = get_full_screen()
    splash_path = get_splash_path()
    splash_duration = get_splash_duration()
    video_url = get_video_url()
    logger.info(f"配置加载完成 - 全屏模式: {full_screen}, 视频URL: {video_url}")

    splash = None
    if splash_path:
        try:
            splash = SplashScreen(logo_path=splash_path)
            splash.show()
            splash.raise_()
        except Exception as e:
            logger.error(f"无法加载启动画面: {e}", exc_info=True)
    
    app.processEvents()
    
    window = MainWindow(video_url=video_url, full_screen=full_screen)

    if splash:
        window.hide()
        def show_main_window():
            window.show()
            if splash:
                splash.close()
        QTimer.singleShot(splash_duration, show_main_window)
    else:
        window.show()
    
    logger.info("进入应用程序主循环")
    exit_code = app.exec()
    logger.info(f"应用程序退出，退出码: {exit_code}")
    logger.info("=" * 60)
    sys.exit(exit_code)
    