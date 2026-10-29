#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""汇总的公共底座：项目定位、常量、字段解析、markdown 小工具。

从 `汇总.py` 拆出来（2026-10-29，单文件 25KB 上限）。视图脚本和 `汇总.py` 共用这些函数。
**不要在这里放具体视图的渲染逻辑** —— 那是 `_views_more.py` 和 `汇总.py` 的事。
"""

import io
import os
import re
import sys
import glob
import subprocess
import datetime

# 技能副本是只读资源，脚本 import 同目录模块时别在里面生 __pycache__
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _aidlc_common import (design_files, find_audit_files,  # noqa: E402
                           find_cr_file)

def _find_doc_dir(start):
    """从 start 往上找含 `开发文档/` 的目录，返回 (项目根, 文档根)；找不到返回 None。"""
    d = os.path.abspath(start)
    while True:
        cand = os.path.join(d, '开发文档')
        if os.path.isdir(cand):
            return d, cand
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def _resolve_dirs():
    """优先按**当前目录**定位项目，找不到才退回脚本自身位置。

    只按脚本位置反推会错位：用宿主技能（`~/.xxx/skills/aidlc`）跑别的项目的汇总，
    视图会写进宿主上溯到的那个项目；在临时目录/自测环境里更是直接写错地方
    （2026-10-29 写自测脚本时踩到）。宿主技能上溯找不到 `开发文档/`，靠 cwd 才能正确定位。
    """
    for start in (os.getcwd(), os.path.dirname(os.path.abspath(__file__))):
        got = _find_doc_dir(start)
        if got:
            return got
    raise SystemExit('找不到含 `开发文档/` 的项目根（当前目录和脚本位置往上都没有）')


ROOT, DOC = _resolve_dirs()

# 目录名带序号，保证编辑器里顺序稳定。改这里就能适配别的编号方案。
# 类型目录直接挂在 `开发文档/` 下（不再套一层容器目录），编号 01/02/03 定死顺序。
TYPES = ('需求', '缺陷', '技术债')
KIND_DIR = {'需求': '01需求', '缺陷': '02缺陷', '技术债': '03技术债'}

# 所有跨 CR 的视图都收口到 `开发文档/_汇总/`，整个目录 gitignore（本地生成、不入库）。
# 这样「共享单文件」不再进版本库，两人并行合并时不会冲突。
SUM_NAME = '_汇总'
SUMDIR = os.path.join(DOC, SUM_NAME)

GENERATED = {
    'status': os.path.join(SUMDIR, '状态.md'),
    'index': os.path.join(SUMDIR, '需求索引.md'),
    'design': os.path.join(SUMDIR, '技术设计.md'),
    'ops': os.path.join(SUMDIR, '运维说明.md'),
    'project': os.path.join(SUMDIR, '项目现状.md'),
    'decisions': os.path.join(SUMDIR, '决策记录.md'),
    'scope': os.path.join(SUMDIR, '当前需求全貌.md'),
    'risks': os.path.join(SUMDIR, '风险与资源.md'),
    'audit': os.path.join(SUMDIR, '审计视图.md'),
}

FIELD_RE = re.compile(r'^- ([^：:]{1,12})[：:]\s*(.*)$')
# 审计条目起始，兼容两种写法（2026-10-21 修：原先只认 `## [`，中文格式被静默丢弃 → 视图 0 条）
#   awslabs 原始：`## [2026-10-21T18:05:41+08:00] 标题`
#   本技能中文 ：`## 2026-10-21T18:05:41+08:00 · 标题`
ENTRY_RE = re.compile(r'(?m)^(?=## (?:\[|\d{4}-\d{2}-\d{2}))')
TS_RE = re.compile(r'\*\*Timestamp\*\*[：:]\s*(\S+)')
HDR_TS_RE = re.compile(
    r'^## \[?(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?(?:[+-]\d{2}:?\d{2})?)')


def read(path):
    with io.open(path, encoding='utf-8') as f:
        return f.read()


STAMP_RE = re.compile(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}')


def _normalize(text):
    """抹掉生成时间再比，否则每跑一次都算「有变化」，--check 永远报过期。"""
    return STAMP_RE.sub('<STAMP>', text)


def write_if_changed(path, text, verbose=False):
    """只在内容变化时写盘。返回 True 表示有变化。"""
    old = read(path) if os.path.exists(path) else None
    if old is not None and _normalize(old) == _normalize(text):
        if verbose:
            print('  无变化  %s' % os.path.relpath(path, ROOT))
        return False
    with io.open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
    if verbose:
        print('  已更新  %s' % os.path.relpath(path, ROOT))
    return True


def fields(path, header_only=False):
    """解析文件头部的 `- 键：值` 行。header_only 时只看第一个 `## ` 之前。"""
    text = read(path)
    if header_only:
        m = re.search(r'(?m)^## ', text)
        if m:
            text = text[:m.start()]
    out = {}
    for line in text.splitlines():
        m = FIELD_RE.match(line.strip())
        if m:
            key = m.group(1).strip()
            if key not in out:
                out[key] = m.group(2).strip()
    return out


TIME_IN_RE = re.compile(r'^(\d{4}-\d{2}-\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?\s*(?:[+-]\d{2}:?\d{2}|Z)?$')


def fmt_time(v):
    """把 `创建` / `更新` 规整成 `YYYY-MM-DD HH:MM:SS`（年月日 + 时分秒）。

    认 `T` 分隔、带时区、缺秒三种写法；**只写日期或认不出就原样返回** ——
    宁可显示得难看，也不替人补一个假的 `00:00:00`。格式不合规由 `自检.py` 报出来。
    """
    v = (v or '').strip()
    if not v or v == '—':
        return '—'
    m = TIME_IN_RE.match(v)
    if not m:
        return v
    d, hh, mm, ss = m.group(1), m.group(2), m.group(3), m.group(4) or '00'
    return '%s %s:%s:%s' % (d, hh, mm, ss)


def sort_key(dirname):
    """CR-00, CR-01…, D-01 —— 基线在前，缺陷在后。"""
    m = re.match(r'CR-(\d+)', dirname)
    if m:
        return (0, int(m.group(1)))
    m = re.match(r'D-(\d+)', dirname)
    if m:
        return (1, int(m.group(1)))
    return (2, 0)


def tracked_generated():
    """仍被 git 跟踪的生成物。非空 ⇒ 并行合并会冲突，必须 git rm --cached。"""
    rels = [os.path.relpath(p, ROOT) for p in GENERATED.values()]
    try:
        r = subprocess.run(['git', 'ls-files', '--'] + rels, cwd=ROOT, check=False,
                           capture_output=True, encoding='utf-8', errors='replace')
    except Exception:
        return []
    if r.returncode != 0:
        return []
    return [l.strip() for l in r.stdout.splitlines() if l.strip()]


# CR 分三类，各在 `开发文档/<编号><类型>/CR-...` 下。判据见 SKILL.md「三种类型怎么判」。

def _rel(p):
    return os.path.relpath(p, DOC).replace(os.sep, '/')


def _demote(body, levels=1):
    """把分片正文里的标题降级：`## 一、xxx` → `### 一、xxx`（levels=2 时连降两级）。

    否则分片的 `##` 会和视图自己的节标题平级，目录结构就乱了。
    `当前需求全貌.md` 的每条 CR 已经是 `##`，正文要降两级才挂得住。
    """
    for _ in range(levels):
        body = re.sub(r'(?m)^(#{1,5}) ', r'#\1 ', body)
    return body


def _body_of(text, levels=1):
    """去掉分片自己的 H1（视图已经有节标题了），其余标题降 `levels` 级。"""
    lines = text.strip().splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and lines[0].startswith('# '):
        lines = lines[1:]
    return _demote('\n'.join(lines).strip(), levels)


def _sec(no, title, body, src):
    return ['## %s / %s' % (no, title), '', _body_of(body), '', '> 来源：`%s`' % _rel(src), '', '---', '']

_ST = {'待处理': 0, '已发生': 0, '已缓解': 1, '已接受': 2, '已关闭': 3, '': 2}
_RS = {'待提供': 0, '可替代': 1, '已有': 2, '不适用': 3, '': 3}


def _md_table(text):
    """取 markdown 里的**第一张表**，返回 [{表头: 单元格}]。

    只取第一张：这两份文件的约定就是「先一张表，后面随便写说明」，
    多表混解析会让列名对不上（比如两张表都有「状态」）。
    """
    head = None
    out = []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith('|') and s.endswith('|'):
            cells = [c.strip() for c in s[1:-1].split('|')]
            if head is None:
                head = cells
                continue
            if cells and all(set(c) <= set('-: ') for c in cells):
                continue                      # 分隔行 |---|---|
            out.append(dict(zip(head, cells)))
        elif out:
            break                             # 第一张表结束
    return out


def _base(v):
    """去掉括号说明：`已接受（成本>收益）` → `已接受`。

    状态列允许带理由（这是好事），但排序和统计只认前半段。
    """
    return re.split(r'[（(]', (v or '').strip(), maxsplit=1)[0].strip()


def _get(row, key):
    """按表头**前缀**取值：表头常写成「触发信号（怎么知道它发生了）」这种带说明的形式。

    精确匹配会取不到，整列变成「—」，而「—」看起来像"没有这个风险"，比报错更难发现。
    """
    if key in row:
        return row[key]
    for k, v in row.items():
        if k.startswith(key):
            return v
    return '—'
