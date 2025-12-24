"""配置加载模块"""
import tomllib
import os
from pathlib import Path
from typing import Optional, Tuple

try:
    import tomli_w
except ImportError:
    tomli_w = None

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent

# 配置文件路径
CONFIG_FILE = PROJECT_ROOT / 'config.toml'

# 全局配置字典
_config: Optional[dict] = None


def load_config() -> dict:
    """加载配置文件"""
    global _config
    if _config is not None:
        return _config
    
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(f"配置文件不存在: {CONFIG_FILE}")
    
    with open(CONFIG_FILE, 'rb') as f:
        _config = tomllib.load(f)
    
    return _config


def get_config(section: str, key: str, default=None):
    """获取配置值"""
    config = load_config()
    return config.get(section, {}).get(key, default)


def get_app_config(key: str, default=None):
    """获取应用配置"""
    return get_config('app', key, default)


def get_video_config(key: str, default=None):
    """获取视频配置"""
    return get_config('video', key, default)

def get_capture_config(key: str, default=None):
    """获取捕获配置"""
    return get_config('capture', key, default)


def get_dummy_config(key: str, default=None):
    """获取数据配置"""
    return get_config('dummy', key, default)


# 便捷访问函数
def get_full_screen() -> bool:
    """获取是否全屏"""
    return get_app_config('full_screen', True)


def get_splash_path() -> Optional[str]:
    """获取启动画面路径（绝对路径）"""
    splash = get_app_config('splash')
    if splash:
        return str(PROJECT_ROOT / splash)
    return None


def get_splash_duration() -> int:
    """获取启动画面显示时长（毫秒）"""
    return get_app_config('splash_duration', 5000)

def get_show_result() -> bool:
    return get_app_config("show_result", False)


def get_video_url() -> str:
    """获取视频流URL"""
    return get_video_config('video_url', 'http://192.168.0.39:8080/raw')


def get_frame_width() -> int:
    """获取视频帧宽度"""
    return get_video_config('frame_width', 1920)


def get_frame_height() -> int:
    """获取视频帧高度"""
    return get_video_config('frame_height', 1088)


def get_fps() -> float:
    """获取每秒捕获帧数（FPS）"""
    return float(get_video_config('fps', 10))


def get_save_capture() -> bool:
    """获取是否保存捕获"""
    return get_capture_config('save_capture', False)


def get_save_root() -> str:
    """获取保存根目录"""
    return get_capture_config('save_root', '/data/capture')


def get_dummy_frames_path() -> str:
    """获取dummy frames文件路径（绝对路径）"""
    dummy_frames = get_dummy_config('dummy_frames', 'data_dummy/dummy_frames.txt')
    return str(PROJECT_ROOT / dummy_frames)


def get_dummy_path() -> str:
    """获取dummy path文件路径（绝对路径）"""
    dummy_path = get_dummy_config('dummy_path', 'data_dummy/dummy_path.txt')
    return str(PROJECT_ROOT / dummy_path)


def get_use_dummy() -> bool:
    """获取是否使用dummy模式"""
    return get_dummy_config('use_dummy', False)


def get_dummy_root() -> str:
    """获取dummy根目录（绝对路径）"""
    dummy_root = get_dummy_config('dummy_root', './data/capture')
    # 如果是相对路径，转换为绝对路径
    if not os.path.isabs(dummy_root):
        return str(PROJECT_ROOT / dummy_root)
    return dummy_root


def get_crop_region() -> Optional[Tuple[int, int, int, int]]:
    """获取裁剪区域 (x, y, width, height)，如果未配置则返回None"""
    x = get_video_config('crop_x')
    y = get_video_config('crop_y')
    width = get_video_config('crop_width')
    height = get_video_config('crop_height')
    
    if x is not None and y is not None and width is not None and height is not None:
        return (int(x), int(y), int(width), int(height))
    return None


def save_crop_region(x: int, y: int, width: int, height: int) -> bool:
    """保存裁剪区域到配置文件"""
    if tomli_w is None:
        raise ImportError("需要安装 tomli-w 库来写入TOML文件: pip install tomli-w")
    
    # 重新加载配置以获取最新内容
    global _config
    _config = None
    config = load_config()
    
    # 更新crop区域配置
    if 'video' not in config:
        config['video'] = {}
    
    config['video']['crop_x'] = x
    config['video']['crop_y'] = y
    config['video']['crop_width'] = width
    config['video']['crop_height'] = height
    
    # 写入文件
    try:
        with open(CONFIG_FILE, 'wb') as f:
            tomli_w.dump(config, f)
        
        # 清除缓存，强制重新加载
        _config = None
        return True
    except Exception as e:
        raise IOError(f"保存配置文件失败: {e}")


def get_overlay_position() -> Optional[Tuple[int, int, int, int]]:
    """获取悬浮窗口位置 (x, y, width, height)，如果未配置则返回None"""
    x = get_app_config('overlay_x')
    y = get_app_config('overlay_y')
    width = get_app_config('overlay_width')
    height = get_app_config('overlay_height')
    
    if x is not None and y is not None and width is not None and height is not None:
        return (int(x), int(y), int(width), int(height))
    return None


def save_overlay_position(x: int, y: int, width: int, height: int) -> bool:
    """保存悬浮窗口位置到配置文件"""
    if tomli_w is None:
        raise ImportError("需要安装 tomli-w 库来写入TOML文件: pip install tomli-w")

    # 重新加载配置以获取最新内容
    global _config
    _config = None
    config = load_config()

    # 更新悬浮窗口位置配置
    if 'app' not in config:
        config['app'] = {}

    config['app']['overlay_x'] = x
    config['app']['overlay_y'] = y
    config['app']['overlay_width'] = width
    config['app']['overlay_height'] = height

    # 写入文件
    try:
        with open(CONFIG_FILE, 'wb') as f:
            tomli_w.dump(config, f)

        # 清除缓存，强制重新加载
        _config = None
        return True
    except Exception as e:
        raise IOError(f"保存配置文件失败: {e}")


def get_3d_view_rotation() -> Tuple[float, float]:
    """获取3D视图旋转角度 (rotation_x, rotation_y)"""
    rotation_x = get_app_config('rotation_x', 35.0)
    rotation_y = get_app_config('rotation_y', 45.0)
    return (float(rotation_x), float(rotation_y))


def save_3d_view_rotation(rotation_x: float, rotation_y: float) -> bool:
    """保存3D视图旋转角度到配置文件"""
    if tomli_w is None:
        raise ImportError("需要安装 tomli-w 库来写入TOML文件: pip install tomli-w")

    # 重新加载配置以获取最新内容
    global _config
    _config = None
    config = load_config()

    # 更新3D视图旋转配置
    if 'app' not in config:
        config['app'] = {}

    config['app']['rotation_x'] = rotation_x
    config['app']['rotation_y'] = rotation_y

    # 写入文件
    try:
        with open(CONFIG_FILE, 'wb') as f:
            tomli_w.dump(config, f)

        # 清除缓存，强制重新加载
        _config = None
        return True
    except Exception as e:
        raise IOError(f"保存配置文件失败: {e}")


if __name__ == '__main__':
    load_config()
    print(_config)