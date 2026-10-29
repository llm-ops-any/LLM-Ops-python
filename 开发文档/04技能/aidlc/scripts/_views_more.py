#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""汇总的「辅助视图」：需求全貌 / 风险与资源 / 审计流水。

从 `汇总.py` 拆出来（2026-10-29，单文件 25KB 上限）。这三个视图代码量大，
独立成文件后 `汇总.py` 只负责调度。
"""

from _views_base import *  # noqa: F401,F403
from _views_base import (_md_table, _get, _base, _ST, _RS,  # noqa: E402
                         _rel, _demote, _body_of, _sec, _normalize,
                         ROOT, DOC, SUMDIR, TYPES, KIND_DIR)

def render_scope(rows, stamp):
    """当前需求全貌：基线 + 各增量 CR 的需求正文，按演进顺序拼成一份。

    单条 CR 只回答「这次改了什么」。想知道「系统现在一共要满足什么」，得把基线和
    各增量拼起来读 —— 这个视图就是拼好的结果，**不手写、不入库**。
    """
    base = [r for r in rows if r['nature'] == '基线']
    incr = sorted([r for r in rows if r['nature'] == '增量'], key=lambda r: sort_key(r['dir']))
    defects = [r for r in rows if r['nature'] == '—']
    ordered = base + incr

    out = ['# 当前需求全貌（自动生成）', '',
           '> 由 `scripts/汇总.py` 合成：**基线需求 + 各增量 CR 的需求正文**，按编号（约等于时间）排序。',
           '> **不要手改** —— 改对应 CR 的 `需求.md` 后重跑脚本即可。',
           '> 想知道「这个系统现在一共要满足什么」，看这一份就够，不用逐个翻 CR 目录。',
           '> 生成时间：%s ｜ 基线 **%d** 条 · 增量 **%d** 条' % (stamp, len(base), len(incr)), '',
           '## 一、清单', '']

    if not ordered:
        out.append('_（还没有任何 CR 写需求文档）_')
        return '\n'.join(out)

    out += ['| 性质 | 编号 | 名称 | 摘要 | FR/AC 号段 |',
            '|---|---|---|---|---|']
    for r in ordered:
        nature = '**基线**' if r['nature'] == '基线' else '增量'
        out.append('| %s | **%s** | %s | %s | %s |' % (
            nature, r['no'], r['name'], r['summary'], r['seg']))
    out.append('')

    out += ['## 二、正文', '',
            '> 顺序：基线在前，增量按编号（≈时间）升序。每节都标了来源 CR。', '']
    for r in ordered:
        rq = find_cr_file(r['path'], '需求')
        if not rq:
            continue
        tag = '基线' if r['nature'] == '基线' else '增量'
        out += ['## %s · %s %s' % (tag, r['no'], r['name']), '',
                _body_of(read(rq), levels=2), '',
                '> 来源：`%s`' % _rel(rq), '', '---', '']

    if defects:
        out += ['> 另有 **%d** 条缺陷 CR 不在本视图：缺陷记的是「与已批准预期不符」，不是需求。'
                % len(defects),
                '> 见 `%s`。' % _rel(GENERATED['index']), '']
    return '\n'.join(out)


# 风险/资源的排序权重：数字越小越该先看
_LV = {'高': 0, '中': 1, '低': 2, '—': 3, '': 3}


def render_risks(rows, stamp):
    """风险台账 + 前置资源清单，合成一份「开工前 / 交付前」的检查单。

    为什么要有这份：风险写在各自 CR 的 `风险.md` 里，看单条 CR 时很清楚，
    但「这个项目现在卡在哪、哪儿可能炸」必须跨 CR 汇总才看得出来。
    """
    risks, res = [], []
    for r in rows:
        rp = find_cr_file(r['path'], '风险')
        if rp:
            for it in _md_table(read(rp)):
                if _get(it, '风险') == '—':
                    continue
                risks.append({
                    'cr': r['no'], 'name': r['name'], 'kind': r['kind'],
                    'id': _get(it, '编号'), 'risk': _get(it, '风险'),
                    'p': _get(it, '可能性'), 'i': _get(it, '影响'),
                    'sig': _get(it, '触发信号'), 'act': _get(it, '应对'),
                    'st': _get(it, '状态'),
                })
        rp2 = find_cr_file(r['path'], '前置资源')
        if rp2:
            for it in _md_table(read(rp2)):
                if _get(it, '资源') == '—':
                    continue
                res.append({
                    'cr': r['no'], 'name': r['name'],
                    'res': _get(it, '资源'), 'type': _get(it, '类型'),
                    'need': _get(it, '必需性'), 'st': _get(it, '状态'),
                    'who': _get(it, '谁提供'),
                    'alt': _get(it, '替代方案'),
                })

    # 状态列允许带理由（`已接受（成本 > 收益）`），排序与统计只认前半段
    for x in risks:
        x['stk'] = _base(x['st'])
    for x in res:
        x['stk'] = _base(x['st'])

    active = [x for x in risks if x['stk'] in ('待处理', '已发生', '—', '')]
    high = [x for x in active if x['i'] == '高']
    pending = [x for x in res if x['stk'] == '待提供']
    pending_need = [x for x in pending if x['need'] == '必需']

    out = ['# 风险与前置资源（自动生成）', '',
           '> 由 `scripts/汇总.py` 合并各 CR 的 `风险.md` 与 `前置资源.md`，**不要手改**。',
           '> **开工前看第一节**（资源没到位就别开工）；**交付前看第二节**（高风险是否都已处理）。',
           '> 生成时间：%s' % stamp, '',
           '**活跃风险 %d 条**（其中高影响 **%d** 条）｜**资源待提供 %d 项**（其中必需 **%d** 项）'
           % (len(active), len(high), len(pending), len(pending_need)), '', '---', '']

    # 一、资源
    out += ['## 一、前置资源（待提供在最前）', '']
    if not res:
        out.append('_（还没有任何 CR 写 `前置资源.md`）_')
    else:
        out += ['| CR | 资源 | 类型 | 必需性 | 状态 | 谁提供 / 在哪 | 替代方案 |',
                '|---|---|---|---|---|---|---|']
        for x in sorted(res, key=lambda y: (_RS.get(y['stk'], 3),
                                           0 if y['need'] == '必需' else 1, y['cr'])):
            mark = '**%s**' % x['res'] if x['st'] == '待提供' else x['res']
            out.append('| %s %s | %s | %s | %s | %s | %s | %s |' % (
                x['cr'], x['name'], mark, x['type'], x['need'], x['st'], x['who'], x['alt']))
    out += ['', '---', '']

    # 二、风险
    out += ['## 二、风险台账（影响 × 可能性，活跃的在前）', '']
    if not risks:
        out.append('_（还没有任何 CR 写 `风险.md`）_')
    else:
        out += ['| CR | 编号 | 风险 | 可能性 | 影响 | 触发信号 | 应对 | 状态 |',
                '|---|---|---|---|---|---|---|---|']
        for x in sorted(risks, key=lambda y: (_ST.get(y['stk'], 2), _LV.get(y['i'], 3),
                                             _LV.get(y['p'], 3), y['cr'])):
            out.append('| %s | %s | %s | %s | %s | %s | %s | %s |' % (
                x['cr'], x['id'], x['risk'], x['p'], x['i'], x['sig'], x['act'], x['st']))

    if risks or res:
        out += ['', '> 数据来源：`01需求|02缺陷|03技术债/CR-*/{风险,前置资源}.md`。',
                '> 新增或改状态后重跑 `汇总.py`；本视图不入库。']
    return '\n'.join(out)


def render_audit(stamp):
    entries = []
    # 审计跟着 CR 走：`CR-*/40-审计-<人>.md`（一人一份，追加式，天然不冲突）
    # 老项目是 `审计-<人>.md`，find_audit_files 两种都收
    paths = []
    for kind in TYPES:
        for cr in sorted(glob.glob(os.path.join(DOC, KIND_DIR[kind], 'CR-*'))):
            if os.path.isdir(cr):
                paths += find_audit_files(cr)
    for path in paths:
        if os.path.basename(path) == '视图.md':
            continue
        text = read(path)
        src = os.path.relpath(path, DOC).replace(os.sep, '/')
        for chunk in ENTRY_RE.split(text):
            chunk = chunk.strip()
            if not chunk.startswith('## '):
                continue
            h = HDR_TS_RE.match(chunk)
            m = TS_RE.search(chunk)
            ts = h.group(1) if h else (m.group(1) if m else '')
            entries.append((ts, src, chunk.rstrip()))

    entries.sort(key=lambda x: x[0], reverse=True)

    out = ['# 审计视图（自动生成）', '',
           '> 由 `scripts/汇总.py` 合并 `CR-*/审计-<人>.md` 生成，**按时间倒序**，**不要手改**。',
           '> 原始条目在各 CR 的 `审计-<人>.md`，一人一份、只追加；本文件只读不写回。',
           '> 生成时间：%s ｜ 共 **%d** 条' % (stamp, len(entries)), '', '---', '']
    for ts, src, body in entries:
        out.append(body)
        out.append('')
        out.append('> 来源：`%s`' % src)
        out.append('')
        out.append('---')
        out.append('')
    return '\n'.join(out)
