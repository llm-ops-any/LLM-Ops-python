#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自检第 3 类：技能副本「是不是新版」。

2026-11-18 从 `_check_meta.py` 拆出（加指纹校验后那个文件顶到 25 KB 上限）。

判据是**内容指纹**，不是 `SKILL.md` 的 `version`：版本号是手写的，实测出现过
五个项目副本内容各不相同却都标 `2.6.0`。指纹由文件内容唯一决定，见 `_fingerprint.py`。

两件事：
  ① 本地一致：副本的 `VERSION` 与当前内容对不对得上 —— 抓「改了技能忘了升版」
  ② 跨副本：与宿主技能比指纹 —— 指纹相同就是同一版，版本号只用来解释谁落后
"""

import os

import _fingerprint as _fp
from _check_common import (HOST_SKILLS, SKILL_REL, _skill_version, _vtuple,  # noqa: F401
                           proj_skill)


def check_version(rows):
    """副本 SKILL.md 有没有 version；副本 VERSION 与内容是否一致；与宿主技能比指纹。

    为什么要它：项目里的是**复制品**，技能升级后没有任何机制通知项目「你这份旧了」。
    2026-10-29 五个项目的副本内容已各不相同，全靠人记 —— 人记不住。
    """
    sk = proj_skill()
    if not sk:
        rows.append(('d', '版本', '项目里没有技能副本，跳过', '复制副本后才能比对版本'))
        return
    path = os.path.join(sk, 'SKILL.md')
    if not os.path.isfile(path):
        return
    mine = _skill_version(path)
    if not mine:
        rows.append(('w', '版本', '技能副本 SKILL.md 没有 version 字段',
                     '在 frontmatter 加 `version: x.y.z` —— 否则技能升级后，'
                     '项目里这份旧副本没人能判断要不要同步'))
        return

    myfp, _n = _fp.fingerprint(sk)

    # ① 本地：VERSION 记的指纹与实算是否一致 —— 不一致就是「改了没升版」
    st, msg = _fp.verify(sk)
    if st == 'missing':
        rows.append(('w', '版本', '副本缺 VERSION 文件，无法判断是不是新版',
                     '跑 `python %s/scripts/版本.py --write` 生成（4 行，可入库）' % SKILL_REL))
    elif st == 'stale':
        rows.append(('x', '版本', '技能内容与 VERSION 不一致：%s' % msg,
                     '改了技能没更新 VERSION —— 这份副本的版本号已经不可信；'
                     '先升 version 再跑 `版本.py --write`'))

    # ② 与宿主技能（「真身」）比：内容优先，版本号只作解释
    host = None
    for p in HOST_SKILLS:
        p2 = os.path.expanduser(p)
        if os.path.isfile(p2):
            host = (os.path.dirname(p2), _skill_version(p2))
            break
    tail = ' · 指纹 %s' % myfp
    if not host:
        rows.append(('v', '版本', '版本 %s%s（本机没找到宿主技能，无从比对）' % (mine, tail), ''))
        return
    hdir, theirs = host
    hfp, _hn = _fp.fingerprint(hdir)
    if hfp and hfp == myfp:
        rows.append(('v', '版本', '版本 %s%s —— 与宿主内容一致' % (mine, tail), ''))
    elif _vtuple(mine) < _vtuple(theirs or '0'):
        rows.append(('w', '版本', '副本 %s 落后于宿主 %s（指纹不同）' % (mine, theirs),
                     '从 %s 整份覆盖副本（覆盖前确认项目里没有本地改动）；'
                     '先 `版本.py --check --diff` 看清差异' % hdir))
    elif _vtuple(mine) == _vtuple(theirs or '0'):
        rows.append(('w', '版本', '版本号都是 %s，但内容不同（副本 %s / 宿主 %s）'
                     % (mine, myfp, hfp),
                     '有一边改了没升版 —— 跑 `版本.py --check --diff` 看差在哪，'
                     '**别直接覆盖**，先判断哪边是新改动'))
    else:
        rows.append(('w', '版本', '副本 %s 比宿主 %s 新（指纹不同）' % (mine, theirs),
                     '把副本改动回收进基准再广播，否则以后重建项目会退回旧版'))
