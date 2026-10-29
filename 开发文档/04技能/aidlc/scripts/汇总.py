#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""汇总：把分片的状态 / 需求 / 审计合成三个只读视图。

设计原则：**人只写自己的分片，全局视图由本脚本生成，且生成物不进版本库。**

生成物（本地生成、**不入库**，`.gitignore` 里排除）：
  开发文档/_汇总/状态.md       ← 扫 开发文档/<类型目录>/*/状态.md
  开发文档/_汇总/需求索引.md   ← 扫 开发文档/<类型目录>/*/需求.md（头部字段）
  开发文档/_汇总/审计视图.md    ← 合并各 CR 的 审计-<人>.md 按时间倒序

为什么不入库（2026-10-21 试点2 实测）：生成物是「扫分片算出来的」，两条并行线各自跑过汇总，
内容必然不同（各自多一行 CR、生成时间也不同）→ 入库就会在合并时三方冲突。
实测一次合并：`状态.md` 冲突 3 处、`需求索引.md` 1 处，全是纯生成物，**手工解冲突毫无意义**
（正确结果只能重算）。不入库后，冲突面只剩源代码和手写文档，而文档是一人一目录，天然不冲突。

真实来源永远是分片：`<类型目录>/CR-<8位号>/{需求,状态}.md`（审计在 CR 目录内的 `审计-<人>.md`）。

本脚本随 AIDLC 技能分发（`<技能副本>/scripts/汇总.py`），靠「往上找 `开发文档/`」定位项目，
放在哪都能跑。用法：
  python <技能副本>/scripts/汇总.py            # 生成；无变化则静默
  python <技能副本>/scripts/汇总.py --verbose  # 生成并打印明细
  python <技能副本>/scripts/汇总.py --site     # 生成 + 出页面（_汇总/index.html），不起服务
  python <技能副本>/scripts/汇总.py --check    # 只检查是否过期，过期退出码 1

`--site` 为什么要单独给：用户口中的「汇总」常常指**能点开的页面**，而本脚本默认只出 md。
转调 `预览.py --no-serve` 生成 index.html / _sidebar.md / vendor / docs 快照，全套自包含。
钩子里不默认跑它（每次 commit 重建站点太慢）。

若生成物仍被 git 跟踪，脚本会提示 `git rm --cached`（否则并行合并照样冲突）。

退出码：0 正常；1 --check 发现过期；2 读文件出错
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

from _views_base import *  # noqa: F401,F403,E402
from _views_base import (_normalize, _rel, _demote, _body_of, _sec,  # noqa: E402
                         _md_table, _base, _get, _ST, _RS,
                         ROOT, DOC, SUMDIR, TYPES, KIND_DIR, SUM_NAME)
from _views_more import render_scope, render_risks, render_audit  # noqa: E402
from _board import render_board  # noqa: E402

BOARD = os.path.join(SUMDIR, '看板.html')

def collect():
    rows = []
    for kind in TYPES:
        kdir = os.path.join(DOC, KIND_DIR[kind])
        if not os.path.isdir(kdir):
            continue
        for p in sorted(glob.glob(os.path.join(kdir, 'CR-*')),
                        key=lambda x: sort_key(os.path.basename(x))):
            if not os.path.isdir(p):
                continue
            d = os.path.basename(p)
            # 文件名走共用查找：带编号（01-需求.md）与老裸名（需求.md）都认
            st_path = find_cr_file(p, '状态')
            rq_path = find_cr_file(p, '需求')
            st = fields(st_path) if st_path else {}
            rq = fields(rq_path, header_only=True) if rq_path else {}
            if not st and not rq:
                continue
            rows.append({
                'kind': kind,
                'dir': d,
                'path': p,
                'no': st.get('编号') or rq.get('变更请求') or d.split('-')[0],
                'name': st.get('名称') or d.split('-', 2)[-1],
                'owner': st.get('负责人', '—'),
                'created': fmt_time(st.get('创建')),
                'updated': fmt_time(st.get('更新')),
                'stage': st.get('阶段', '—'),
                'gate': st.get('门禁', '—'),
                'next': st.get('下一步', '—'),
                'left': st.get('遗留', '—'),
                'unit': st.get('单元', '—'),
                'summary': rq.get('摘要', '—'),
                'seg': rq.get('号段', '—'),
                # 需求性质：基线（第一版 / v1.0）或 增量（基线之后追加的改动）。
                # 缺省按「增量」——基线是少数，只有它需要显式标注。
                'nature': rq.get('需求性质', '增量') if rq_path else '—',
                'has_req': bool(rq_path),
            })
    return rows


STAGE_LABEL = {
    'delivered': '已交付',
    'in-progress': '进行中',
    'awaiting-approval': '待批',
    'blocked': '阻塞',
    'fixed': '已修复',
    'not-started': '未开始',
    'cancelled': '已撤回',
}


def render_status(rows, stamp):
    live = [r for r in rows if r['stage'] not in ('delivered', 'fixed', 'cancelled')]
    todo = [r for r in rows if r['next'] not in ('无', '—', '')]

    out = ['# 状态（自动生成）', '',
           '> 本文件由 `scripts/汇总.py` 生成，**不要手改** —— 手改会在下次生成时被覆盖。',
           '> 要改进度：改 `<类型目录>/CR-<8位号>-<简称>/00-状态.md`；项目级事实见各 CR 的 `32-变更说明.md`。',
           '> 生成时间：%s' % stamp, '',
           '## 一览', '']
    for kind in TYPES:
        group = [r for r in rows if r['kind'] == kind]
        if not group:
            continue
        out += ['### %s（%d）' % (kind, len(group)), '',
                '| 编号 | 名称 | 负责人 | 创建 | 更新 | 阶段 | 下一步 |',
                '|---|---|---|---|---|---|---|']
        for r in group:
            stage = STAGE_LABEL.get(r['stage'], r['stage'])
            out.append('| **%s** | %s | %s | %s | %s | %s | %s |' % (
                r['no'], r['name'], r['owner'], r['created'], r['updated'], stage, r['next']))
        out.append('')
    out += ['', '## 汇总', '',
            '- 共 **%d** 条线（%s）：%s' % (len(rows),
                '、'.join('%s %d' % (k, sum(1 for r in rows if r['kind'] == k))
                         for k in TYPES if any(x['kind'] == k for x in rows)),
                '、'.join(
                '%s %d' % (STAGE_LABEL.get(k, k), sum(1 for r in rows if r['stage'] == k))
                for k in ('delivered', 'fixed', 'in-progress', 'awaiting-approval', 'blocked', 'cancelled')
                if any(r['stage'] == k for r in rows))),
            '- 进行中：%s' % ('、'.join('%s %s' % (r['no'], r['name']) for r in live) if live else '**无**'),
            '- 待人工处理：**%d** 条（见上表「下一步」列）' % len(todo), '']

    out += ['## 门禁明细', '']
    for r in rows:
        out.append('- **%s %s**：%s' % (r['no'], r['name'], r['gate']))
    left = [r for r in rows if r['left'] not in ('无', '—', '')]
    out += ['', '## 遗留', '']
    if left:
        for r in left:
            out.append('- **%s %s**：%s' % (r['no'], r['name'], r['left']))
    else:
        out.append('- 无')
    out += ['', '---', '',
            '项目级事实（部署、存储、扩展开关、身份）见 `项目现状.md`；'
            'CR 怎么找见 `_汇总/需求索引.md`。', '']
    return '\n'.join(out)


SEG_RE = re.compile(r'^([A-Z]+)-(?:(\d+[a-z]?)[~-]([A-Z]+-)?(\d+[a-z]?)|(\d+[a-z]?))$')


def parse_segments(seg):
    items = []
    for token in re.split(r'[、,，]\s*', seg.strip()):
        token = token.strip()
        if not token or token == '—':
            continue
        m = SEG_RE.match(token.replace(' ', ''))
        if not m:
            # 容错：号段字段常被写成 `AC-01~AC-04（CR 内编号）` 这类带说明的形式。
            # 能捞出 `X-数字` 就用，捞不出就跳过 —— **不能因为一行格式不规整就让整个汇总崩掉**。
            m2 = re.search(r'(N?FR|AC|S|A)-?(\d+)', token, re.I)
            if m2:
                items.append((m2.group(1).upper(), m2.group(2), m2.group(2)))
            continue
        prefix = m.group(1)
        if m.group(5):
            items.append((prefix, m.group(5), m.group(5)))
        else:
            items.append((prefix, m.group(2), m.group(4)))
    def _num(v):
        mm = re.match(r'(\d+)', str(v or ''))
        return int(mm.group(1)) if mm else 9999
    items.sort(key=lambda x: ({'FR': 0, 'NFR': 1, 'AC': 2, 'S': 3, 'A': 4}.get(x[0], 9), _num(x[1])))
    return items


def render_index(rows, stamp):
    out = ['# 需求索引（自动生成）', '',
           '> 由 `scripts/汇总.py` 生成，**不要手改**。改需求请改各 `CR-<8位号>/需求.md` 的头部字段。',
           '> 生成时间：%s' % stamp, '',
           '## 一、CR 一览', '']
    for kind in TYPES:
        group = [r for r in rows if r['kind'] == kind]
        if not group:
            continue
        out += ['### %s（%d）' % (kind, len(group)), '',
                '| 目录 | 编号 | 性质 | 摘要 | 号段 | 阶段 | 创建 | 更新 |',
                '|---|---|---|---|---|---|---|---|']
        for r in group:
            nature = '**基线**' if r['nature'] == '基线' else r['nature']
            out.append('| `%s/%s/` | **%s** | %s | %s | %s | %s | %s | %s |' % (
                KIND_DIR[kind], r['dir'], r['no'], nature, r['summary'], r['seg'],
                STAGE_LABEL.get(r['stage'], r['stage']), r['created'], r['updated']))
        out.append('')

    out += ['', '## 二、ID 号段 → 文件', '',
            '路径相对 `开发文档/`（类型目录 `01需求` / `02缺陷` / `03技术债`）。', '',
            '| ID | 号段 | 文件 |', '|---|---|---|']
    for r in rows:
        for prefix, lo, hi in parse_segments(r['seg']):
            span = '%s-%s' % (prefix, lo) if lo == hi else '%s-%s ~ %s-%s' % (prefix, lo, prefix, hi)
            out.append('| %s | %s | `%s/%s` |' % (prefix, span, KIND_DIR[r['kind']] + '/' + r['dir'],
                                                  '01-需求.md' if r['has_req'] else '00-状态.md'))

    out += ['', '## 三、新增一个需求的步骤', '',
            '1. **算号**：`P + Y + MMDD + N` 共 8 位 —— 人编号 1 位（见 `00规则/团队配置.md`）、'
            '年末位 1 位、月日 2 位、当天第几个 2 位（**从 00 起**）。例 `16102100` = 人1 / 2026 / 10-21 / 当天第 00 个。',
            '2. **建目录**：`CR-<8位号>-<中文简称>/`（**目录名就是号，不需要号段文件**），例 `CR-16102100-导出CSV/`；'
            '   里面至少放一个 `00-状态.md`（阶段可写 `not-started` = 占了号还没开工）。'
            '   首位是人 ⇒ 两人永不撞；一天最多 100 个（00~99）。',
            '3. **写 `01-需求.md`**，头部必须有这几个字段（索引和全貌靠它生成）：',
            '   `- 需求性质：增量`（基线写 `基线`，全项目仅一条）、`- 变更请求：CR-16102100`、'
            '`- 摘要：一句话`、`- 号段：FR-01~FR-03、AC-01~AC-02`（**CR 内编号**，'
            '跨 CR 引用写 `CR-16102100/FR-01`，不复制正文）。',
            '4. **写 `00-状态.md`**，字段：`编号/名称/负责人/创建/更新/阶段/门禁/下一步/单元/遗留`。'
            '`创建` 在占号时写一次；`更新` **每改一次状态就刷一次**；两条都写 `YYYY-MM-DD HH:MM:SS`（年月日 时分秒，24 小时制）。',
            '5. 按需加 `06-执行计划.md` / `08-技术设计/08-1-应用设计.md` / `20-测试记录.md` / '
            '`30-验收报告.md` / `02-问题.md`，**不建空文件**（编号固定，没有那份就空着号）。',
            '6. 跑一次 `python <技能副本>/scripts/汇总.py --site` 刷新本索引和页面。', '',
            '> **唯一标识一律用 `CR-<8位号>`**（目录名就是号）。不要另造 `R7`、`CR-2` 之类的短号 —— 两套号并存，迟早对不上。', '']
    return '\n'.join(out)


def render_design(rows, stamp):
    """技术设计 = 各 CR 的「执行计划 + `08-技术设计/*.md`」按 CR 顺序拼接。

    **执行计划排在设计之前**：先看打算怎么落地（步骤、改动清单、验收映射），
    再看设计细节（结构、规则、数据模型）。顺序反了，读者得先啃完设计才知道要干什么。
    """
    entries = []
    for r in rows:
        plan = find_cr_file(r['path'], '执行计划')
        if plan:
            entries.append((r['no'], '执行计划', read(plan).strip(), plan))
        for p in design_files(r['path']):
            title = os.path.splitext(os.path.basename(p))[0]
            # `08-1-应用设计` → `应用设计`：编号只负责排序，不该出现在标题里
            m = re.match(r'^\d+(?:-\d+)?-(.+)$', title)
            if m:
                title = m.group(1)
            entries.append((r['no'], title, read(p).strip(), p))
    out = ['# 技术设计（自动生成）', '',
           '> 由 `scripts/汇总.py` 合并各 CR 的 `06-执行计划.md` 与 `08-技术设计/*.md`，按 CR 号顺序，**不要手改**。',
           '> 每条 CR 先计划后设计；真正的内容在 `<类型目录>/CR-<8位号>/` 下 —— 各写各的，互不冲突。',
           '> 生成时间：%s ｜ 共 **%d** 节' % (stamp, len(entries)), '', '---', '']
    for no, title, body, src in entries:
        out += _sec(no, title, body, src)
    if not entries:
        out.append('_（还没有任何 CR 写设计增量或执行计划）_')
    return '\n'.join(out)


def render_ops(rows, stamp):
    """运维说明 = 各 CR 的 `31-运维说明.md`（只有部署类 CR 才有）。"""
    entries = []
    for r in rows:
        p = find_cr_file(r['path'], '运维说明')
        if p:
            entries.append((r['no'], read(p).strip(), p))
    out = ['# 运维说明（自动生成）', '',
           '> 由 `scripts/汇总.py` 合并各 CR 的 `运维说明.md`，**不要手改**。',
           '> 只有部署 / 上线类 CR 才有这一份；平时在各自 `CR-<8位号>/运维说明.md` 里写。',
           '> 生成时间：%s ｜ 共 **%d** 条' % (stamp, len(entries)), '', '---', '']
    for no, body, src in entries:
        out += ['## %s' % no, '', _body_of(body), '', '> 来源：`%s`' % _rel(src), '', '---', '']
    if not entries:
        out.append('_（本项目还没有部署类 CR）_')
    return '\n'.join(out)


def render_project(rows, stamp):
    """项目现状 = 各 CR 的 `变更说明.md`（对项目级事实的影响）。

    身份 / 审批模式 / 测试策略 / 团队这类**不随 CR 变**的东西留在 `00规则/团队配置.md`，不进本文件。
    """
    entries = []
    for r in rows:
        p = find_cr_file(r['path'], '变更说明')
        if p:
            entries.append((r['no'], read(p).strip(), p))
    out = ['# 项目现状（自动生成）', '',
           '> 由 `scripts/汇总.py` 合并各 CR 的 `32-变更说明.md`，**不要手改**。',
           '> 项目级配置（身份 / 审批模式 / 测试策略 / 团队）见 `00规则/团队配置.md`。',
           '> 生成时间：%s ｜ 共 **%d** 条变更' % (stamp, len(entries)), '', '---', '']
    for no, body, src in entries:
        out += ['## %s' % no, '', _body_of(body), '', '> 来源：`%s`' % _rel(src), '', '---', '']
    if not entries:
        out.append('_（还没有任何 CR 写变更说明）_')
    return '\n'.join(out)


def render_decisions(rows, stamp):
    """跨 CR 的决策台账：整个项目做过哪些技术取舍、为什么、谁定的。

    单条 CR 的决策在 `CR-<8位号>/决策记录.md`；这份是给人回顾用的索引（交付汇报、交接、复盘）。
    """
    entries = []
    for r in rows:
        p = find_cr_file(r['path'], '决策记录')
        if p:
            entries.append((r['no'], read(p).strip(), p))
    out = ['# 决策记录（自动生成）', '',
           '> 由 `scripts/汇总.py` 合并各 CR 的 `07-决策记录.md`，**不要手改**。',
           '> 这里记「为什么这么做」：选型对比、被否掉的方案、决策人和时间。',
           '> **项目复盘 / 交接时先看这份** —— 它比代码更能说明当初的边界在哪。',
           '> 生成时间：%s ｜ 共 **%d** 条 CR 有决策' % (stamp, len(entries)), '', '---', '']
    for no, body, src in entries:
        out += ['## %s' % no, '', _body_of(body), '', '> 来源：`%s`' % _rel(src), '', '---', '']
    if not entries:
        out.append('_（还没有任何 CR 写决策记录）_')
    return '\n'.join(out)


def build_site():
    """生成 `_汇总/index.html`（自包含文档站，**不起服务**）。

    为什么要有这个开关（2026-10-27，opcapp 实测）：
    用户说「做一下汇总」，agent 跑完本脚本（只出 9 个 md）就回「汇总做了」，
    用户拿不到能点开的页面 —— 因为页面一直是另一个脚本 `预览.py` 的事，而那段说明写着「可选」。
    **一次指令要能出全套**，所以本脚本提供 `--site`，转调 `预览.py --no-serve`。

    为什么不做成默认：
    钩子每次 commit 都会调本脚本，默认建站要把所有 CR 文档快照复制一遍，纯属浪费；
    站点是「要给人看」时才需要的东西，显式开关更合适。

    实现上直接转调、不复制逻辑 —— 页面怎么搭只允许有一处权威（`预览.py`）。
    """
    here = os.path.dirname(os.path.abspath(__file__))
    script = os.path.join(here, '预览.py')
    if not os.path.isfile(script):
        print('')
        print('! 技能副本里没有 预览.py，页面没生成（副本不完整，重新同步技能副本）')
        return 1
    print('')
    print('生成页面（_汇总/index.html）…')
    sys.stdout.flush()          # 不然子进程的输出会抢在提示前面，看着像没跑
    rc = subprocess.call([sys.executable or 'python', script, '--no-serve'], cwd=ROOT)
    if rc == 0:
        idx = os.path.join(SUMDIR, 'index.html')
        rel = os.path.relpath(idx, ROOT).replace(os.sep, '/')
        print('')
        print('页面：%s' % rel)
        print('  看：浏览器直接打开它，或 `cd 开发文档/_汇总 && python -m http.server 8090`')
        print('  给：`_汇总/` 整目录打包发出去即可（自包含，不连 CDN）')
    return rc


def site_hint():
    """没带 --site 时提一句页面通道 —— 不说的话，agent 和用户都以为「汇总 = 几个 md」。"""
    idx = os.path.join(SUMDIR, 'index.html')
    rel = os.path.relpath(idx, ROOT).replace(os.sep, '/')
    print('')
    if os.path.isfile(idx):
        print('页面：%s（数据刚更新过的话，加 --site 重跑才同步）' % rel)
    else:
        print('页面还没生成：%s' % rel)
        print('  要给人看（含侧边栏、可整目录打包）：本脚本加 --site，或跑 预览.py --no-serve')


def main():
    argv = sys.argv[1:]
    verbose = '--verbose' in argv or '-v' in argv
    check_only = '--check' in argv
    site = '--site' in argv or '--html' in argv

    if not os.path.isdir(DOC):
        print('找不到 %s' % DOC)
        return 2

    rows = collect()
    if not rows:
        print('没有可汇总的 CR（找不到 %s 下的 CR-*/00-状态.md）' % ' / '.join(KIND_DIR.values()))
        print('  期望布局：开发文档/<类型目录>/CR-<8位号>-<简称>/{00-状态.md, 01-需求.md}')
        print('  还没建需求目录时属正常；先按技能第 E 节的编号目录建出来。')
        return 2

    stamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    targets = {
        GENERATED['status']: render_status(rows, stamp),
        GENERATED['index']: render_index(rows, stamp),
        GENERATED['design']: render_design(rows, stamp),
        GENERATED['ops']: render_ops(rows, stamp),
        GENERATED['project']: render_project(rows, stamp),
        GENERATED['decisions']: render_decisions(rows, stamp),
        GENERATED['scope']: render_scope(rows, stamp),
        GENERATED['risks']: render_risks(rows, stamp),
        GENERATED['audit']: render_audit(stamp),
    }
    # 看板带「生成时间」，每次内容都不同 —— 放进 targets 会让 `--check` 永远报「已过期」。
    # 所以它只在真正生成时写，不参与一致性比对。
    if not check_only:
        targets[BOARD] = render_board(rows, stamp)
    if not check_only:
        try:
            os.makedirs(SUMDIR, exist_ok=True)
        except OSError:
            pass

    changed = []
    for path, text in targets.items():
        old = read(path) if os.path.exists(path) else None
        if old is not None and _normalize(old) == _normalize(text):
            if verbose:
                print('  无变化  %s' % os.path.relpath(path, ROOT))
            continue
        changed.append(path)
        if not check_only:
            write_if_changed(path, text, verbose)

    if check_only:
        if changed:
            print('生成物已过期：')
            for p in changed:
                print('  %s' % os.path.relpath(p, ROOT))
            print('\n跑一次 `python <技能副本>/scripts/汇总.py` 重新生成。')
            return 1
        print('生成物是最新的。')
        return 0

    if changed:
        print('已在本地生成 %d 个视图（**不入库**，别提交）：' % len(changed))
        for p in changed:
            print('  %s' % os.path.relpath(p, ROOT))
    elif verbose:
        print('视图全部最新，无需改动。')

    stuck = tracked_generated()
    if stuck:
        print('')
        print('⚠ 这些生成物仍被 git 跟踪 —— 不处理的话，两人并行合并照样冲突：')
        for p in stuck:
            print('  %s' % p)
        print('  一次性移除：git rm --cached --%s' % ''.join(' "%s"' % p for p in stuck))
        print('  再跑一次 安装钩子.py，会把它们补进 .gitignore')

    # md 只是数据；用户要的「汇总」通常还包括能点开的页面。--site 一次出全套。
    if site:
        return build_site()
    site_hint()
    return 0


if __name__ == '__main__':
    sys.exit(main())
