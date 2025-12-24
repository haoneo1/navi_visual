"""日志记录模块"""
import logging
from datetime import datetime
from pathlib import Path


class Logger:
    """日志管理器 - 单例模式"""
    _instance = None
    _logger = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._setup_logger()
        return cls._instance
    
    def _setup_logger(self):
        """设置日志配置"""
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        
        log_file = log_dir / f"log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        
        self._logger = logging.getLogger('navi_visual')
        self._logger.setLevel(logging.DEBUG)
        self._logger.handlers.clear()
        
        # 文件handler
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            '%Y-%m-%d %H:%M:%S'
        ))
        self._logger.addHandler(file_handler)
        
        # 控制台handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(logging.Formatter('%(levelname)s - %(message)s'))
        self._logger.addHandler(console_handler)
        
        self._logger.info(f"日志系统初始化完成，日志文件: {log_file}")
    
    @property
    def logger(self):
        return self._logger


def get_logger():
    """获取logger实例"""
    return Logger().logger


if __name__ == '__main__':
    logger = get_logger()
    logger.info("测试日志")
    logger.warning("测试警告")
    logger.error("测试错误")
    logger.debug("测试调试")
    logger.critical("测试严重")
    logger.fatal("测试致命")
    logger.info("测试日志")
    logger.warning("测试警告")
    logger.error("测试错误")
    logger.debug("测试调试")
    logger.critical("测试严重")
    logger.fatal("测试致命")
