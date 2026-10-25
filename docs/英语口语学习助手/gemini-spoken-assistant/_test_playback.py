#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File    : _test_playback.py
@Desc    : 扬声器自检 —— 用与正式脚本完全相同的参数（24kHz/16bit/单声道）播 1 秒 440Hz 蜂鸣

用法：
    python _test_playback.py            # 用系统默认输出设备
    python _test_playback.py 5          # 指定 index=5
    python _test_playback.py EDIFIER    # 名称片段匹配（填 ASCII 部分，中文名是乱码）

听到蜂鸣说明该设备配置正确；听不到就换一个 index 再试。
"""
import math
import struct
import sys

import pyaudio

RATE = 24000  # 与 Omni-Realtime 下行采样率一致


def resolve(pya: pyaudio.PyAudio, spec: str) -> int:
    if not spec:
        return int(pya.get_default_output_device_info()["index"])
    if spec.lstrip("-").isdigit():
        return int(spec)
    for i in range(pya.get_device_count()):
        try:
            info = pya.get_device_info_by_index(i)
        except OSError:
            continue
        if info.get("maxOutputChannels", 0) > 0 and spec.lower() in str(info["name"]).lower():
            return int(info["index"])
    raise SystemExit(f"找不到输出设备: {spec}")


def main() -> None:
    spec = sys.argv[1] if len(sys.argv) > 1 else ""
    pya = pyaudio.PyAudio()
    try:
        idx = resolve(pya, spec)
        name = pya.get_device_info_by_index(idx)["name"]
        print(f"输出设备 index={idx}  {name}")

        # 1 秒 440Hz 正弦，末尾留 0.2s 静音
        frames = bytearray()
        for n in range(RATE):
            v = int(12000 * math.sin(2 * math.pi * 440 * n / RATE))
            frames += struct.pack("<h", v)
        frames += b"\x00" * (RATE * 2 // 5)

        stream = pya.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=RATE,
            output=True,
            output_device_index=idx,
        )
        try:
            print("播放中...（1 秒蜂鸣）")
            stream.write(bytes(frames))
        finally:
            stream.stop_stream()
            stream.close()
        print("✅ 播放调用已返回。听到声音了吗？")
    finally:
        pya.terminate()


if __name__ == "__main__":
    main()
