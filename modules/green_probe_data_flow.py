# -*- coding: utf-8 -*-
"""绿色探头（绿尾翼）数据流说明与核心计算代码。

本文件**不参与**主程序 import；用于集中说明「绿探头」方向数据从哪里来，
并把与 ``GLWidget.draw_probe_g`` 一致的数学抽成可单独测试的纯函数。

================================================================================
一、数据从哪来（按时间顺序）
================================================================================

1. **视频原始数据**  
   ``VideoStreamThread`` 用线程池反复调用 ``video_thread.process_frame``。
   该函数对配置的 ``url`` 发 HTTP GET，得到固定长度的 **NV12** 字节流，
   用 OpenCV 转成 ``frame_rgb``（全幅 RGB）。

2. **送入 AI 的图像**  
   若 ``config`` 里配置了裁剪区域 ``get_crop_region()``，则只把 ``frame_rgb``
   的 ROI ``frame_for_ai`` 交给分析器；否则整幅 ``frame_rgb`` 作为
   ``frame_for_ai``。

3. **旋转矩阵的数值来源**  
   ``frame_for_ai`` 进入 ``AIAnalyzer.analyze``（``modules/ai_analyzer.py``）：
   - 图像经 ``torchvision.transforms``：Resize 224×224、归一化等；
   - ``resnet_18_rot(out_dim=9)``（``modules/network.py``）前向推理；
   - 输出长度为 9 的向量，``reshape(3, 3)`` 得到 **3×3 的 ``rotation_matrix``**。
   该矩阵表示网络从当前超声画面估计出的旋转（具体物理含义由训练数据与
   标签定义，代码侧把它当作 SO(3) 近似使用）。

4. **从工作线程回到 GUI**  
   ``process_frame`` 返回 ``(frame_rgb, rotation_matrix, ...)`` 后，
   ``VideoStreamThread._on_frame_processed`` 若 ``rotation_matrix is not None``，
   则 ``emit rotation_matrix_updated(rotation_matrix)``（Qt 信号，跨线程排队到主线程）。

5. **主窗口写入 OpenGL 部件**  
   ``MainWindow._connect_video_signals`` 将信号接到 ``update_rotation_matrix``，
   再调用 ``GLWidget.update_rotation_matrix``，保存为 ``self.rotation_matrix`` 并
   ``update()`` 触发重绘。

6. **绿色几何如何用矩阵画出来**  
   ``paintGL`` 中始终调用 ``draw_probe_g()``（与红色是否显示无关）。
   ``draw_probe_g`` 用 **逆矩阵** 把固定基准方向 ``base_dir = [1,0,0]`` 映射成
   尾翼指向的 ``position_dir``，再 ``rotate_to_direction`` 画绿色薄长方体
   （视觉上像尾翼）。数学与下面 ``green_tail_world_direction`` 一致。

================================================================================
二、与红色尾翼的区别（便于对照）
================================================================================

- **绿色**：方向由 **每帧 AI 输出的 ``rotation_matrix``** 决定（经本文件所述链路）。
- **红色**：方向由 **预设 ``preset_positions`` + ``set_probe_t_position``** 决定；
  是否绘制由 ``show_red_rectangle``（Inference 开关）决定。二者数据源不同。

================================================================================
三、本文件提供的函数
================================================================================
"""

from __future__ import annotations

import numpy as np


def model_output_to_rotation_matrix(model_output: np.ndarray) -> np.ndarray:
    """将网络输出的 9 维向量整理成 3×3 矩阵（与 ``AIAnalyzer.analyze`` 一致）。

    Parameters
    ----------
    model_output :
        shape ``(9,)`` 或 ``(1, 9)`` 等可 squeeze 为一维 9 元素的数组。
    """
    v = np.asarray(model_output, dtype=float).reshape(-1)
    if v.size != 9:
        raise ValueError(f"expected 9 elements, got {v.size}")
    return v.reshape(3, 3)


def green_tail_world_direction(rotation_matrix: np.ndarray) -> np.ndarray:
    """由 ``GLWidget.draw_probe_g`` 抽出的几何：绿尾翼在场景中的指向单位向量。

    实现与 ``modules/gl_widget.py`` 中 ``draw_probe_g`` 一致::

        rot_inv = np.linalg.inv(self.rotation_matrix)
        base_dir = np.array([1.0, 0.0, 0.0])
        position_dir = rot_inv @ base_dir
        position_dir /= ||position_dir||

    即：在代码里把 **逆矩阵作用在 +X 单位向量** 上，得到尾翼从球心向外
    延伸的方向（再经 ``rotate_to_direction`` 画到 OpenGL）。

    Parameters
    ----------
    rotation_matrix :
        3×3，通常为 ``AIAnalyzer.analyze`` 的返回值。

    Returns
    -------
    np.ndarray
        shape ``(3,)``，单位向量。若矩阵不可逆则退化为 ``[1,0,0]``。
    """
    r = np.asarray(rotation_matrix, dtype=float).reshape(3, 3)
    base_dir = np.array([1.0, 0.0, 0.0], dtype=float)
    try:
        rot_inv = np.linalg.inv(r)
    except np.linalg.LinAlgError:
        return base_dir.copy()
    position_dir = rot_inv @ base_dir
    n = float(np.linalg.norm(position_dir))
    if n < 1e-6:
        return base_dir.copy()
    return (position_dir / n).astype(float)


def preprocess_frame_for_ai_note() -> str:
    """仅作文档占位：真实预处理在 ``AIAnalyzer`` 的 ``transform`` 中定义。"""
    return (
        "Resize(224,224); Normalize(mean=[0.0554]*3, std=[0.1291]*3); "
        "详见 modules/ai_analyzer.py 中 transforms.Compose。"
    )


def pipeline_summary() -> str:
    """人类可读的短摘要，便于日志或调试打印。"""
    return (
        "NV12(HTTP) -> RGB -> optional crop -> AIAnalyzer.analyze -> 3x3 R "
        "-> Signal rotation_matrix_updated -> MainWindow.update_rotation_matrix "
        "-> GLWidget.rotation_matrix -> draw_probe_g: inv(R)@[1,0,0] -> 绿尾翼方向"
    )


# ---------------------------------------------------------------------------
# 可选：离线验证逆映射方向（不依赖 Qt / torch）
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # 单位矩阵：逆仍为 I，inv(I) @ ex = ex -> 绿尾翼沿 +X
    r_identity = np.eye(3)
    d0 = green_tail_world_direction(r_identity)
    print("identity R -> direction", d0, "norm", np.linalg.norm(d0))

    # 任意小旋转示例（仅作数值 smoke test）
    theta = 0.3
    c, s = np.cos(theta), np.sin(theta)
    r_y = np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])
    d1 = green_tail_world_direction(r_y)
    print("Ry(theta) -> direction", d1, "norm", np.linalg.norm(d1))
    print(pipeline_summary())
    print(preprocess_frame_for_ai_note())
