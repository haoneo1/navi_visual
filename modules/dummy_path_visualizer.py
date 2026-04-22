#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Dummy path 3D visualization demo.

模仿 viper_signal/viper_main.py 的展示方式：
- 使用 matplotlib 进行主线程实时刷新
- 上方 3D 轨迹动画，下方文本信息
- 从 ./data/dummy_path.txt 读取三维路径
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


@dataclass
class PathSample:
    x: float
    y: float
    z: float


def load_dummy_path(path_file: Path) -> np.ndarray:
    """Load xyz points from dummy_path.txt.

    每行格式示例：0.703974, 0.802862, 0.487245
    """
    if not path_file.is_file():
        raise FileNotFoundError(f"dummy_path 文件不存在: {path_file}")

    points: list[PathSample] = []
    with path_file.open("r", encoding="utf-8") as fp:
        for idx, line in enumerate(fp, start=1):
            raw = line.strip()
            if not raw:
                continue
            chunks = [c.strip() for c in raw.split(",")]
            if len(chunks) != 3:
                raise ValueError(f"第 {idx} 行格式非法（应为 x,y,z）: {raw}")
            try:
                x, y, z = (float(chunks[0]), float(chunks[1]), float(chunks[2]))
            except ValueError as exc:
                raise ValueError(f"第 {idx} 行包含非数字: {raw}") from exc
            points.append(PathSample(x, y, z))

    if not points:
        raise ValueError(f"dummy_path 文件为空: {path_file}")

    return np.array([[p.x, p.y, p.z] for p in points], dtype=np.float64)


class DummyPath3DVisualizer:
    """Real-time 3D path visualizer for dummy path."""

    def __init__(
        self,
        points: np.ndarray,
        fps: float = 30.0,
        trail_length: int = 200,
        loop: bool = True,
        style: str = "classic",
    ):
        self.points = points
        self.total_points = points.shape[0]
        self.fps = max(1.0, fps)
        self.update_interval = 1.0 / self.fps
        self.trail_length = max(2, trail_length)
        self.loop = loop
        self.style = style

        self.running = True
        self.frame_idx = 0
        self.last_update_time = 0.0

        self.fig = None
        self.ax = None
        self.info_ax = None

        mins = self.points.min(axis=0)
        maxs = self.points.max(axis=0)
        spans = np.maximum(maxs - mins, 1e-6)
        pad = spans * 0.2 + 0.02
        # 强制坐标范围包含原点，确保“原点 -> 当前点”箭头起点可见
        self.axis_min = np.minimum(mins - pad, np.array([0.0, 0.0, 0.0], dtype=np.float64))
        self.axis_max = np.maximum(maxs + pad, np.array([0.0, 0.0, 0.0], dtype=np.float64))

    def init_plot(self) -> None:
        plt.ion()
        self.fig = plt.figure(figsize=(14, 10))
        gs = self.fig.add_gridspec(2, 1, height_ratios=[3, 1], hspace=0.3)

        self.ax = self.fig.add_subplot(gs[0], projection="3d")
        self.info_ax = self.fig.add_subplot(gs[1])
        self.info_ax.axis("off")

        self._setup_axes()
        plt.tight_layout()

    def _setup_axes(self) -> None:
        assert self.ax is not None
        self.ax.set_xlabel("X")
        self.ax.set_ylabel("Y")
        self.ax.set_zlabel("Z")
        self.ax.set_title("Dummy Path Real-time 3D Motion Demo")
        self.ax.grid(True)
        self.ax.view_init(elev=20, azim=45)
        self.ax.set_xlim([self.axis_min[0], self.axis_max[0]])
        self.ax.set_ylim([self.axis_min[1], self.axis_max[1]])
        self.ax.set_zlim([self.axis_min[2], self.axis_max[2]])
        if self.style == "cyber":
            self._apply_cyber_axes_style()

    def _apply_cyber_axes_style(self) -> None:
        assert self.fig is not None and self.ax is not None and self.info_ax is not None
        self.fig.patch.set_facecolor("#060a14")
        self.ax.set_facecolor("#050914")
        self.info_ax.set_facecolor("#060a14")
        self.ax.grid(True, color="#2de2e680", linewidth=0.6)
        self.ax.tick_params(colors="#9ae6ff")
        self.ax.xaxis.label.set_color("#6ef7ff")
        self.ax.yaxis.label.set_color("#6ef7ff")
        self.ax.zaxis.label.set_color("#6ef7ff")
        self.ax.title.set_color("#00f5d4")
        # Pane colors for darker sci-fi look
        self.ax.xaxis.set_pane_color((0.03, 0.05, 0.10, 0.95))
        self.ax.yaxis.set_pane_color((0.03, 0.05, 0.10, 0.95))
        self.ax.zaxis.set_pane_color((0.03, 0.05, 0.10, 0.95))

    def _update_info(self, current: np.ndarray, progress: float) -> None:
        assert self.info_ax is not None
        self.info_ax.clear()
        self.info_ax.axis("off")

        text = "\n".join(
            [
                "Dummy Path Playback:",
                "=" * 70,
                f"Frame: {self.frame_idx + 1:>5} / {self.total_points:<5}",
                f"Progress: {progress * 100:>6.2f}%",
                f"X: {current[0]:>10.6f}   Y: {current[1]:>10.6f}   Z: {current[2]:>10.6f}",
                f"FPS(target): {self.fps:.1f}    Loop: {self.loop}",
            ]
        )
        self.info_ax.text(
            0.02,
            0.95,
            text,
            transform=self.info_ax.transAxes,
            fontsize=10,
            family="monospace",
            verticalalignment="top",
            color="#d6f8ff" if self.style == "cyber" else "black",
            bbox=(
                {"boxstyle": "round", "facecolor": "#081326", "edgecolor": "#2de2e6", "alpha": 0.85}
                if self.style == "cyber"
                else {"boxstyle": "round", "facecolor": "wheat", "alpha": 0.8}
            ),
        )

    def _draw_frame(self) -> None:
        assert self.ax is not None
        current = self.points[self.frame_idx]
        origin = np.array([0.0, 0.0, 0.0], dtype=np.float64)

        self.ax.clear()
        self._setup_axes()

        if self.style == "cyber":
            # 当前点双层散点做“发光”
            self.ax.scatter(current[0], current[1], current[2], c="#00e5ff", s=360, alpha=0.20, marker="o")
            self.ax.scatter(
                current[0], current[1], current[2], c="#00e5ff", s=120, alpha=1.0, marker="o", edgecolors="#7df9ff", label="PROBE"
            )
            self.ax.text(current[0], current[1], current[2], "  PROBE", fontsize=9, color="#b7fbff")
            # 原点 -> 当前点方向箭头（科技感样式）
            self.ax.quiver(
                origin[0],
                origin[1],
                origin[2],
                current[0] - origin[0],
                current[1] - origin[1],
                current[2] - origin[2],
                color="#ffe066",
                linewidth=2.0,
                arrow_length_ratio=0.08,
                alpha=0.95,
                label="ORIGIN->PROBE",
            )
        else:
            # 仅显示当前位置
            self.ax.scatter(
                current[0], current[1], current[2], c="orange", s=130, marker="o", edgecolors="black", label="Probe"
            )
            self.ax.text(current[0], current[1], current[2], " Probe", fontsize=9)
            # 原点 -> 当前点方向箭头（经典样式）
            self.ax.quiver(
                origin[0],
                origin[1],
                origin[2],
                current[0] - origin[0],
                current[1] - origin[1],
                current[2] - origin[2],
                color="gold",
                linewidth=1.8,
                arrow_length_ratio=0.08,
                alpha=0.9,
                label="Origin->Probe",
            )

        legend = self.ax.legend(loc="upper left", fontsize=9)
        if self.style == "cyber" and legend is not None:
            legend.get_frame().set_facecolor("#081326")
            legend.get_frame().set_edgecolor("#2de2e6")
            legend.get_frame().set_alpha(0.85)
            for txt in legend.get_texts():
                txt.set_color("#b9f6ff")
        self._update_info(current=current, progress=self.frame_idx / max(1, self.total_points - 1))
        plt.draw()
        plt.pause(0.001)

    def _step_frame(self) -> None:
        if self.frame_idx + 1 < self.total_points:
            self.frame_idx += 1
            return
        if self.loop:
            self.frame_idx = 0
        else:
            self.running = False

    def run(self) -> None:
        self.init_plot()
        self.last_update_time = time.time()
        print("Starting dummy path 3D visualization (Close window or Ctrl+C to stop)...")

        try:
            while self.running:
                if self.fig is None or not plt.fignum_exists(self.fig.number):
                    print("Window closed, exiting...")
                    break

                now = time.time()
                if now - self.last_update_time >= self.update_interval:
                    self._draw_frame()
                    self._step_frame()
                    self.last_update_time = now
                else:
                    remain = self.update_interval - (now - self.last_update_time)
                    plt.pause(min(max(remain, 0.001), 0.01))
        except KeyboardInterrupt:
            print("\nStopping...")
        finally:
            self.running = False
            if self.fig is not None:
                plt.close(self.fig)


def parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parent.parent
    default_path = repo_root / "data" / "dummy_path.txt"

    parser = argparse.ArgumentParser(description="Visualize dummy_path.txt in 3D (viper-style demo)")
    parser.add_argument("--path", type=Path, default=default_path, help="Path to dummy_path.txt")
    parser.add_argument("--fps", type=float, default=30.0, help="Playback FPS")
    parser.add_argument("--trail", type=int, default=200, help="Trail length")
    parser.add_argument(
        "--style",
        type=str,
        choices=("classic", "cyber"),
        default="cyber",
        help="Visualization style",
    )
    parser.add_argument("--no-loop", action="store_true", help="Play once instead of loop")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    points = load_dummy_path(args.path)
    visualizer = DummyPath3DVisualizer(
        points=points, fps=args.fps, trail_length=args.trail, loop=not args.no_loop, style=args.style
    )
    visualizer.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
