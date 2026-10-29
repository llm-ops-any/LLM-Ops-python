#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自检的公共底座：项目定位、git 小工具、技能副本与版本判定。

从 `自检.py` 拆出来（2026-10-29，单文件 25KB 上限）。三个模块共用这些函数与常量。
"""

import glob
import io
import os
import re
import subprocess
import sys
import time

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HERE = os.path.dirname(os.path.abspath(__file__))
# 不生成 __pycache__：技能副本是只读资源，在里面写字节码会污染项目（git 还会看见）
sys.dont_write_bytecode = True

sys.path.insert(0, HERE)
from _aidlc_common import (GITATTR_HEAD, GITATTR_LINES, find_cr_file,  # noqa: E402
                           gitattributes_missing)
MARK = 'AIDLC:v2 BEGIN'
LAYOUT = ('00规则', '01需求', '02缺陷', '03技术债', '04技能')
REQUIRED_DIRS = ('00规则', '01需求', '02缺陷', '03技术债')
SUMDIR = '开发文档/_汇总'
GENERATED = (
    SUMDIR + '/状态.md',
    SUMDIR + '/需求索引.md',
    SUMDIR + '/技术设计.md',
    SUMDIR + '/运维说明.md',
    SUMDIR + '/项目现状.md',
    SUMDIR + '/决策记录.md',
    SUMDIR + '/当前需求全貌.md',
    SUMDIR + '/风险与资源.md',
    SUMDIR + '/审计视图.md',
)
CR_RE = re.compile(r'CR[-_]?(\d+)')
DECL_RE = re.compile(r'^[-*]\s*CR[：:]\s*CR[-_]?(\d+)', re.M)

try:                       # GBK 控制台下打印 ✓ 会抛 UnicodeEncodeError（试点1 踩过）
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass


def find_root(start):
    """找项目根：先问 git，再退回「往上找含 开发文档/ 的目录」，都没有返回 None。

    `encoding='utf-8'` 不能省：Windows 下 `text=True` 走 locale(cp936)，git 输出的
    UTF-8 中文路径会变乱码，交给 `cwd=` 就是 WinError 267。"""
    r = subprocess.run(['git', 'rev-parse', '--show-toplevel'], cwd=start,
                       capture_output=True, encoding='utf-8', errors='replace')
    if r.returncode == 0 and r.stdout.strip():
        return r.stdout.strip()
    d = os.path.abspath(start)
    while True:
        if os.path.isdir(os.path.join(d, '开发文档')):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


# 先看「我在哪」，再看「脚本在哪」—— 脚本可能被从宿主技能目录直接调用，
# 那时若按脚本位置算，会去体检技能自己（2026-10-21 实测踩到）。
ROOT = find_root(os.getcwd()) or find_root(HERE)
if not ROOT:
    print('不在任何 AIDLC 项目里：从 %s 往上没找到 开发文档/，也不在 git 仓库内。' % os.getcwd())
    print('用法：cd <项目根> 再跑本脚本。')
    sys.exit(2)
SELF = os.path.basename(os.path.abspath(__file__))


def git(*args):
    return subprocess.run(['git'] + list(args), cwd=ROOT,
                          capture_output=True, encoding='utf-8', errors='replace')


def read(path):
    try:
        with io.open(path, encoding='utf-8', errors='replace') as f:
            return f.read()
    except (IOError, OSError):
        return None


def is_repo():
    return git('rev-parse', '--is-inside-work-tree').stdout.strip() == 'true'


# ── 检查项 ────────────────────────────────────────────────────────────────
SKILL_REL = '开发文档/04技能/aidlc'


def _skill_version(path):
    """从 SKILL.md 的 frontmatter 读 version；没有或不合法返回 None。"""
    try:
        text = io.open(path, encoding='utf-8').read(4000)
    except Exception:
        return None
    if not text.startswith('---'):
        return None
    parts = text.split('---')
    if len(parts) < 2:
        return None
    for line in parts[1].splitlines():
        m = re.match(r'^\s*version\s*:\s*([0-9][0-9A-Za-z.\-]*)', line)
        if m:
            return m.group(1).strip()
    return None


# 宿主技能（「真身」）可能落在这几个位置；项目副本是复制品。
HOST_SKILLS = (
    '~/.workbuddy/skills/aidlc/SKILL.md',
    '~/.claude/skills/aidlc/SKILL.md',
    '~/.codex/skills/aidlc/SKILL.md',
    '~/.cursor/skills/aidlc/SKILL.md',
)


def _vtuple(s):
    return tuple(int(x) for x in re.findall(r'\d+', s or '')) or (0,)


def proj_skill():
    """项目自带的技能副本目录；没有就返回 None。
    注意：**不能退回脚本自己所在的 HOST 技能目录** —— 那样会拿宿主技能自带的钩子
    去给项目打绿勾，等于自欺（2026-10-21 实测踩到）。"""
    cand = os.path.join(ROOT, SKILL_REL)
    return cand if os.path.isdir(cand) else None
