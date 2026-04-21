#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实时在终端输出 Viper（Polhemus）探头 PNO 数据。

流程与 ``viper_main.py`` 一致：``ViperUSBComm.connect`` → ``start_continuous`` →
守护线程 ``read_usb_data``；本脚本在主线程轮询 ``_latest_frame``（与主程序 UI 同源，
不依赖 bounded queue 是否积压）。

用法（建议在 ``viper_signal`` 目录下执行，或在任意目录用绝对路径调用）::

    cd viper_signal && python viper_print_stream.py
    python viper_print_stream.py --json > poses.jsonl
    python viper_print_stream.py --hz 20
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from viper_usb_comm import ViperUSBComm  # noqa: E402


def _format_text(frame: dict) -> str:
    parts = [
        f"fn={frame.get('frame_num')} seuid=0x{frame.get('seuid', 0):08x}",
    ]
    for s in frame.get("sensors", []):
        p = s["pos"]
        o = s["ori"]
        parts.append(
            f"S{s['num']}: pos=({p[0]:.3f},{p[1]:.3f},{p[2]:.3f}) "
            f"ori=({o[0]:.4f},{o[1]:.4f},{o[2]:.4f},{o[3]:.4f})"
        )
    return " | ".join(parts)


def _snapshot_json(frame: dict, wall_time: float) -> str:
    payload = {
        "wall_time": wall_time,
        "frame_num": frame.get("frame_num"),
        "seuid": frame.get("seuid"),
        "sensors": [
            {"num": s["num"], "pos": list(s["pos"]), "ori": list(s["ori"])}
            for s in frame.get("sensors", [])
        ],
    }
    return json.dumps(payload, ensure_ascii=False)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Viper USB continuous PNO → stdout（实时探头位姿）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="每行输出一条 JSON（与主程序录制的 viper_poses.jsonl 结构相近）",
    )
    parser.add_argument(
        "--trace-dir",
        type=str,
        default=str(_THIS_DIR / "trace"),
        help="USB 模块写 trace 的目录（默认 viper_signal/trace）",
    )
    parser.add_argument(
        "--hz",
        type=float,
        default=0.0,
        metavar="N",
        help="限制打印频率为 N Hz；0 表示尽量跟设备（仍受终端 I/O 限制）",
    )
    args = parser.parse_args()

    viper = ViperUSBComm(data_queue=None, trace_dir=args.trace_dir)

    try:
        if not viper.connect():
            print("USB connect 失败", file=sys.stderr)
            return 1
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1

    if not viper.start_continuous():
        print("进入 continuous PNO 失败", file=sys.stderr)
        viper.disconnect()
        return 1

    viper.keep_reading = True
    read_thread = threading.Thread(target=viper.read_usb_data, daemon=True)
    read_thread.start()

    period = 1.0 / args.hz if args.hz and args.hz > 0 else 0.0
    next_print = 0.0
    last_frame_num: int | None = None

    print("Viper 数据流已启动；Ctrl+C 结束。", file=sys.stderr)

    try:
        while True:
            now = time.time()
            snap = None
            try:
                lock = viper._latest_frame_lock
                with lock:
                    snap = viper._latest_frame
            except AttributeError:
                pass

            if snap is None:
                time.sleep(0.002)
                continue

            fn = snap.get("frame_num")
            if period <= 0 and isinstance(fn, int) and fn == last_frame_num:
                time.sleep(0.001)
                continue

            if period > 0 and now < next_print:
                time.sleep(0.0005)
                continue

            if args.json:
                print(_snapshot_json(snap, now), flush=True)
            else:
                print(_format_text(snap), flush=True)

            last_frame_num = fn if isinstance(fn, int) else last_frame_num
            if period > 0:
                next_print = now + period
            else:
                time.sleep(0.0005)

    except KeyboardInterrupt:
        print("\n退出中…", file=sys.stderr)
    finally:
        viper.keep_reading = False
        try:
            viper.is_continuous = False
        except Exception:
            pass
        if read_thread.is_alive():
            read_thread.join(timeout=2.0)
        viper.disconnect()

    return 0


if __name__ == "__main__":
    sys.exit(main())
