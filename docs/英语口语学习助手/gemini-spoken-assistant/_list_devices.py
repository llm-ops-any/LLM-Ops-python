#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File    : _list_devices.py
@Desc    : 列出本机所有音频设备，用来给 .env 的 MIC_DEVICE / OUTPUT_DEVICE 取值

用法：
    python _list_devices.py
"""
import sys

import pyaudio

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def iter_devices(pya: pyaudio.PyAudio):
    """PyAudio 没有设备生成器，只能按索引逐个取"""
    for i in range(pya.get_device_count()):
        try:
            yield pya.get_device_info_by_index(i)
        except OSError:
            continue


def main() -> None:
    pya = pyaudio.PyAudio()
    try:
        print("===== 输入设备（麦克风）=====")
        for info in iter_devices(pya):
            if info.get("maxInputChannels", 0) > 0:
                print(f"  index={info['index']:<3} {info['name']}")

        print("\n===== 输出设备（扬声器/耳机）=====")
        for info in iter_devices(pya):
            if info.get("maxOutputChannels", 0) > 0:
                print(f"  index={info['index']:<3} {info['name']}")

        print("\n===== 系统默认 =====")
        print(f"  默认输入: {pya.get_default_input_device_info()['name']}")
        print(f"  默认输出: {pya.get_default_output_device_info()['name']}")
        print("\n把想要的 index 或名称片段填进 .env：")
        print("  MIC_DEVICE=1      # 或 MIC_DEVICE=USB MIC")
        print("  OUTPUT_DEVICE=3  # 或 OUTPUT_DEVICE=耳机")
    finally:
        pya.terminate()


if __name__ == "__main__":
    main()
