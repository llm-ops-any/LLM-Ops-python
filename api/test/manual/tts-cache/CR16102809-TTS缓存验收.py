#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
CR-16102809 验收脚本：TTS 合成结果缓存

用法（容器内，需先把目标应用的 draft_app_config.text_to_speech.enable 置为 true）：
    PYTHONPATH=/app/api python /tmp/crn_tts_cache_check.py

设计：全程用假 provider + 假 config，**不调用阿里百炼**，不消耗额度。
"""
import glob
import json
import os
import pathlib
import sys
import time
from types import SimpleNamespace
from uuid import UUID

sys.path.insert(0, "/app/api")

import internal.service.audio_service as mod  # noqa: E402
from app.http.app import app  # noqa: E402
from app.http.module import injector  # noqa: E402
from internal.model import Account, Message  # noqa: E402
from internal.service import AudioService  # noqa: E402
from pkg.sqlalchemy import SQLAlchemy  # noqa: E402

MESSAGE_ID = UUID("d8fea187-0bcc-4849-a7e6-89510423f610")
RESULTS = []


def record(ac, name, ok, detail=""):
    RESULTS.append((ac, name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {ac} {name}" + (f" — {detail}" if detail else ""))


class FakeProvider:
    """假 provider：记录被调用次数，返回固定 3 个块"""
    supports_tts = True

    def __init__(self):
        self.calls = 0
        self.tag = ""          # 由测试按当前音色设置，模拟「不同音色 -> 不同音频」

    def tts_stream(self, text):
        self.calls += 1
        for i in range(3):
            yield {"audio": f"chunk-{i}-{self.tag}-{text[:8]}", "sample_rate": 22050}


def make_config(engine="dashscope", voice="longxiaochun_v3", model="cosyvoice-v3-flash"):
    return SimpleNamespace(engine=engine, voice=voice, model=model, has_api_key=True)


def drain(gen):
    """把生成器跑完，返回 (chunk 内容列表, 是否出现 tts_end)"""
    chunks, ended = [], False
    for line in gen:
        if line.startswith("event: tts_message"):
            payload = json.loads(line.split("data: ", 1)[1])
            chunks.append(payload.get("audio"))
        elif line.startswith("event: tts_end"):
            ended = True
    return chunks, ended


def clear_cache():
    for f in glob.glob(str(mod.TTS_CACHE_DIR / "*")):
        os.remove(f)


with app.app_context():
    db = injector.get(SQLAlchemy)
    svc = injector.get(AudioService)
    message = db.session.query(Message).filter(Message.id == MESSAGE_ID).one()
    account = db.session.query(Account).filter(Account.id == message.created_by).one()

    fake = FakeProvider()
    mod.create_tts_provider = lambda cfg: fake          # 不碰真实 API

    clear_cache()
    cfg1 = make_config()

    def call(cfg):
        fake.tag = cfg.voice          # 音色不同 -> 合成结果不同，才能验证缓存不串
        svc.speech_provider_service.get_active_config = lambda: cfg
        return drain(svc.message_to_audio(MESSAGE_ID, account))

    # ── AC-01 / AC-02 首次合成 + 第二次命中 ──────────────────────
    c1, e1 = call(cfg1)
    first_calls = fake.calls
    c2, e2 = call(cfg1)
    record("AC-01", "第二次请求不再调用 provider",
           first_calls == 1 and fake.calls == 1,
           f"第一次后 calls={first_calls}，第二次后 calls={fake.calls}")
    record("AC-02", "两次音频内容一致且都有 tts_end",
           c1 == c2 and e1 and e2,
           f"chunks={len(c1)} vs {len(c2)}")

    # ── AC-03 换音色必须重新合成 ───────────────────────────────
    cfg2 = make_config(voice="longwan_v2")
    c3, _ = call(cfg2)
    record("AC-03", "换音色后重新合成（未命中旧缓存）",
           fake.calls == 2 and c3 != c1,
           f"calls={fake.calls}, 内容不同={c3 != c1}")

    # ── AC-05 中断不写缓存 ─────────────────────────────────────
    cfg3 = make_config(voice="longcheng_v2")
    svc.speech_provider_service.get_active_config = lambda: cfg3
    key3 = mod._build_tts_cache_key(message, cfg3)
    gen = svc.message_to_audio(MESSAGE_ID, account)
    next(gen)                      # 只取第一个块
    gen.close()                    # 模拟客户端断开
    path3 = mod.TTS_CACHE_DIR / f"{key3}.json"
    record("AC-05", "中途断开不产生缓存文件", not path3.exists(),
           f"provider 调用={fake.calls}, 文件存在={path3.exists()}")

    # ── AC-06 过期缓存被清理并重新合成 ─────────────────────────
    key1 = mod._build_tts_cache_key(message, cfg1)
    path1 = mod.TTS_CACHE_DIR / f"{key1}.json"
    existed = path1.exists()
    if existed:
        old = time.time() - mod.TTS_CACHE_TTL_SECONDS - 3600
        os.utime(path1, (old, old))
    before = fake.calls
    call(cfg1)
    record("AC-06", "过期缓存被删除并重新合成",
           existed and fake.calls == before + 1 and path1.exists(),
           f"过期前存在={existed}, 重新合成={fake.calls == before + 1}")

    # ── 额外：损坏文件自动丢弃 ─────────────────────────────────
    path1.write_text("{ not json", encoding="utf-8")
    before = fake.calls
    call(cfg1)
    record("AC-06b", "损坏缓存被丢弃并重建",
           fake.calls == before + 1 and path1.read_text(encoding="utf-8").startswith("{"),
           f"重新合成={fake.calls == before + 1}")

    # ── 额外：缓存目录与文件形态 ───────────────────────────────
    files = [p for p in mod.TTS_CACHE_DIR.glob("*.json")]
    record("MISC", "缓存文件落在 storage/tts_cache",
           str(mod.TTS_CACHE_DIR).endswith("storage/tts_cache") and len(files) >= 1,
           f"目录={mod.TTS_CACHE_DIR}, 文件数={len(files)}")

print("\n" + "=" * 60)
passed = sum(1 for r in RESULTS if r[2])
print(f"合计：{passed}/{len(RESULTS)} 通过")
if passed != len(RESULTS):
    for ac, name, _ok, detail in RESULTS:
        if not _ok:
            print(f"  - {ac} {name}: {detail}")
    sys.exit(1)
