"""AI分析模块 - 调用network.py进行图像分析"""
import torch
import numpy as np
from torchvision import transforms
from pathlib import Path
from .logger import get_logger
from .network import resnet_18_rot

logger = get_logger()

# 项目根目录
_project_root = Path(__file__).parent.parent


class AIAnalyzer:
    """AI分析器 - 使用network.py进行旋转矩阵预测"""
    
    def __init__(self, model_path="best.pth"):
        """初始化AI分析器"""
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = None
        self.model_path = model_path
        self._load_model()
        
        # 图像预处理
        self.transform = transforms.Compose([
            transforms.ToPILImage(),
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            # transforms.Normalize(mean=[0.485, 0.456, 0.406], 
            #                    std=[0.229, 0.224, 0.225])
        ])
    
    def _load_model(self):
        """加载模型"""
        try:
            model_file = _project_root / self.model_path
            logger.info(f"Loading model from: {model_file}")
            if not model_file.exists():
                model_file = Path(self.model_path)
            
            if model_file.exists():
                self.model = resnet_18_rot(out_dim=9)
                self.model.load_state_dict(torch.load(str(model_file), map_location=self.device))
                self.model.to(self.device)
                self.model.eval()
                logger.info(f"AI模型加载成功: {model_file}")
            else:
                logger.warning(f"模型文件不存在: {model_file}")
        except Exception as e:
            logger.error(f"加载AI模型错误: {e}", exc_info=True)
            self.model = None
    
    def analyze(self, frame_rgb):
        """分析图像，返回旋转矩阵"""
        if self.model is None:
            return None
        
        try:
            frame_tensor = self.transform(frame_rgb).unsqueeze(0).to(self.device)
            with torch.no_grad():
                output = self.model(frame_tensor)
            return output.cpu().numpy()[0].reshape(3, 3)
        except Exception as e:
            logger.error(f"AI分析错误: {e}", exc_info=True)
            return None

