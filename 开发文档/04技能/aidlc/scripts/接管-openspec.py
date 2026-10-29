#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把已有的 OpenSpec 项目接管成 AIDLC：`openspec/` → `开发文档/` 的 CR 目录。

为什么有它（2026-10-29，中海油 haiyou_web_3d）：
技能里**没有一个字**提到 openspec。用户拿 CodeBuddy 接管一个跑了 69 个 OpenSpec 变更的
存量项目，agent 只能临场决定「迁不迁、迁成什么样」——号怎么取、阶段写什么、门禁怎么标、
delta spec 放哪，全靠即兴。换一次会话就换一个结果，这是不可复现的。

用法
    python 接管-openspec.py <项目根>                 # 只预演，不动盘
    python 接管-openspec.py <项目根> --write         # 真建
    python 接管-openspec.py <项目根> --write --names 命名.tsv

`命名.tsv`（可选，补中文简称）：两列制表符分隔，`变更名<TAB>中文简称`
    add-environment-module\t环境模块
    fix-timeline-bar-ghost-cap\t时间轴端帽残留修复
不提供时简称用**去掉动作前缀的 slug**（`environment-module`），结构正确、名字难看 ——
中文简称是翻译，脚本不猜；要好看就再过一遍 `命名.tsv`。

映射规则（与 SKILL.md「接管已有项目」一节一致）
    openspec/specs/*                      → 01需求/CR-<P><Y>000000-基线能力规格/能力规格/*.md
    openspec/changes/archive/<日期>-<名>/  → <类型目录>/CR-<P><Y><MMDD><N>-<简称>/  （阶段 delivered）
    openspec/changes/<名>/（未归档）        → <类型目录>/CR-<P><Y><MMDD><N>-<简称>/  （阶段 awaiting-approval）
      proposal.md     → 01-需求.md（头部字段 + 原文）
      design.md       → 08-技术设计/设计.md
      tasks.md        → 08-技术设计/任务清单.md
      specs/*/spec.md → 需求规格/<cap>.md（delta spec 原样保留）

类型目录按变更名前缀判定：fix/hotfix → 02缺陷；refactor/perf/optimize → 03技术债；其余 → 01需求。

幂等：已有 CR 的 `00-状态.md` / `01-需求.md` 里出现过同一个 `原变更` 路径 ⇒ 跳过。
不碰 `openspec/` 一个字节（接管不销毁原始记录；是否删除由人决定）。
"""

import argparse
import glob
import io
import os
import re
import sys
import time

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _aidlc_common import DESIGN_DIR  # noqa: E402

TODAY = time.strftime('%Y-%m-%d')
NOW = time.strftime('%Y-%m-%d %H:%M:%S')

# 变更名前缀 → 类型目录（OpenSpec 的 add / fix / refactor 惯例）
KIND_RULES = (
    (('fix', 'bugfix', 'hotfix'), '02缺陷'),
    (('refactor', 'perf', 'optimize', 'optimi', 'chore'), '03技术债'),
)
# 简称里要去掉的动作前缀
STRIP_VERBS = ('add', 'fix', 'bugfix', 'hotfix', 'refactor', 'update', 'remove',
               'optimize', 'optimi', 'improve', 'change', 'introduce', 'implement')


def read(p):
    with io.open(p, encoding='utf-8', errors='replace') as f:
        return f.read()


def first_title(text, fallback):
    """取 md 第一个一级标题；没有就用 fallback（去掉 markdown 修饰）。"""
    m = re.search(r'^#\s+(.+)$', text, re.M)
    return m.group(1).strip() if m else fallback


def base_slug(change):
    """`add-environment-module` → `environment-module`。"""
    parts = change.split('-')
    while len(parts) > 1 and parts[0].lower() in STRIP_VERBS:
        parts.pop(0)
    return '-'.join(parts) or change


def lookup(table, it):
    """映射表按优先级查三种 key：CR 号 → `archive/<日期>-<名>` → 变更名。

    为什么要三种：**同名变更确实存在**（中海油有两个 `extend-interference-simulation`，
    分别在 08-20 和 08-21），只用变更名做 key 时后一条会覆盖前一条，两条拿到同一个简称。
    """
    if not table:
        return None
    for k in ('CR-%s' % it.get('no', ''), it.get('rel', ''), it.get('rel', '').replace('openspec/changes/', ''),
              it['change']):
        if k and k in table:
            return table[k]
    return None


def short_name(it, names):
    return lookup(names, it) or base_slug(it['change'])


def kind_of(change):
    head = change.split('-')[0].lower()
    for verbs, tdir in KIND_RULES:
        if head in verbs:
            return tdir
    return '01需求'


def existing_origins(doc):
    """扫描已有 CR，收集「原变更」路径，用于幂等。"""
    seen = set()
    for d in glob.glob(os.path.join(doc, '0[123]*', 'CR-*')):
        for name in ('00-状态.md', '01-需求.md', '状态.md', '需求.md'):
            p = os.path.join(d, name)
            if os.path.isfile(p):
                for m in re.finditer(r'`(openspec/changes/[^`]+?)`', read(p)):
                    seen.add(m.group(1).rstrip('/'))
    return seen


def load_names(p):
    names = {}
    if not p:
        return names
    for line in read(p).splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '\t' not in line:
            continue
        k, v = line.split('\t', 1)
        names[k.strip()] = v.strip()
    return names


TYPE_ALIAS = {'需求': '01需求', '缺陷': '02缺陷', '技术债': '03技术债',
              '01需求': '01需求', '02缺陷': '02缺陷', '03技术债': '03技术债'}


def load_types(p):
    """`类型.tsv`：变更名<TAB>需求/缺陷/技术债。前缀判不准时用它兜底。"""
    types = {}
    if not p:
        return types
    for line in read(p).splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '\t' not in line:
            continue
        k, v = line.split('\t', 1)
        t = TYPE_ALIAS.get(v.strip())
        if t:
            types[k.strip()] = t
    return types


def build_plan(root, person, year, names, types=None):
    doc = os.path.join(root, '开发文档')
    ch = os.path.join(root, 'openspec', 'changes')
    spec = os.path.join(root, 'openspec', 'specs')

    items = []
    for d in sorted(glob.glob(os.path.join(ch, 'archive', '*'))):
        if not os.path.isdir(d):
            continue
        b = os.path.basename(d)
        # archive 目录名是 `<YYYY-MM-DD>-<变更名>`（带横线）
        m = re.match(r'(\d{4})-(\d{2})-(\d{2})-(.+)$', b)
        if m:
            ymd = m.group(1) + m.group(2) + m.group(3)
            name = m.group(4)
        else:
            ymd, name = time.strftime('%Y%m%d'), b
        items.append({'src': d, 'change': name, 'ymd': ymd, 'mmdd': ymd[4:8],
                      'rel': 'openspec/changes/archive/' + b, 'archived': True})
    for d in sorted(glob.glob(os.path.join(ch, '*'))):
        b = os.path.basename(d)
        if b == 'archive' or not os.path.isdir(d):
            continue
        ymd = time.strftime('%Y%m%d')
        items.append({'src': d, 'change': b, 'ymd': ymd, 'mmdd': ymd[4:8],
                      'rel': 'openspec/changes/' + b, 'archived': False})

    # 同一天按出现顺序取 N：00、01…（号 = P + Y + MMDD + NN，共 8 位）
    used = {}
    for it in items:
        n = used.get(it['mmdd'], 0)
        it['no'] = '%s%s%s%02d' % (person, year, it['mmdd'], n)
        used[it['mmdd']] = n + 1
        it['type'] = lookup(types, it) or kind_of(it['change'])
        short = short_name(it, names)
        it['dir'] = os.path.join(doc, it['type'], 'CR-%s-%s' % (it['no'], short))
        it['stage'] = 'delivered' if it['archived'] else 'awaiting-approval'

    caps = []
    if os.path.isdir(spec):
        for p in sorted(glob.glob(os.path.join(spec, '*'))):
            b = os.path.basename(p)
            if os.path.isdir(p):
                s = os.path.join(p, 'spec.md')
                if os.path.isfile(s):
                    caps.append((b, s))
            elif b.endswith('.md'):
                caps.append((b[:-3], p))
    base = None
    if caps:
        # 基线固定 P + Y + 0000 + 00（月日位写 0000，一眼看出不是某天的活）
        bno = '%s%s000000' % (person, year)
        base = {'no': bno, 'caps': caps,
                'dir': os.path.join(doc, '01需求', 'CR-%s-基线能力规格' % bno)}
    return items, base


def need_md(it, names):
    prop = os.path.join(it['src'], 'proposal.md')
    body = read(prop).strip() if os.path.isfile(prop) else '> 原变更没有 proposal.md，正文待补。'
    title = lookup(names, it) or first_title(body, base_slug(it['change']))
    return '\n'.join([
        '# %s' % title, '',
        '- 需求性质：增量',
        '- 变更请求：CR-%s' % it['no'],
        '- 摘要：见下方 Why（原文迁入，未改写）',
        '- 号段：原变更未必写了 delta spec，FR/AC 需补齐后再进 G1',
        '- 原变更：`%s/`%s' % (it['rel'], '（已归档）' if it['archived'] else '（未归档，进行中）'),
        '- 迁移：%s 自 OpenSpec 迁入，正文未改写' % TODAY,
        '', '---', '', body, ''])


def status_md(it):
    gate = ('G1 approved（历史：随代码合入，未补签）' if it['archived']
            else 'G1 待批（01-需求.md 由原提案迁入，等 PO 批准）')
    nxt = ('无' if it['archived']
           else 'PO 审 01-需求.md → 补 FR/AC 与验收口径 → 批准后进 CONSTRUCTION')
    return '\n'.join([
        '# 状态', '',
        '- 编号：CR-%s' % it['no'],
        '- 名称：%s' % os.path.basename(it['dir']).split('-', 2)[2],
        '- 负责人：—',
        '- 阶段：%s' % it['stage'],
        '- 创建：%s' % NOW,
        '- 更新：%s' % NOW,
        '- 门禁：%s' % gate,
        '- 下一步：%s' % nxt,
        '- 单元：—',
        '- 遗留：—' if it['archived'] else '- 遗留：原提案未写 delta spec 时，需补 FR/AC',
        '',
        '> 迁移记录：%s 自 `%s/` 迁入。' % (TODAY, it['rel']),
        '> 本 CR 在原 OpenSpec 流程中%s，故阶段%s、门禁%s。'
        % ('已完成并归档' if it['archived'] else '尚未完成',
           '直接置终态' if it['archived'] else '停在 G1',
           '标「未补签」' if it['archived'] else '待批'),
        ''])


def write(p, text):
    d = os.path.dirname(p)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with io.open(p, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)


def apply_plan(items, base, names, write_mode):
    created = 0
    for it in items:
        d = it['dir']
        ops = [(os.path.join(d, '00-状态.md'), status_md(it)),
               (os.path.join(d, '01-需求.md'), need_md(it, names))]
        for src_name, dst_name in (('design.md', '设计.md'), ('tasks.md', '任务清单.md')):
            src = os.path.join(it['src'], src_name)
            if os.path.isfile(src):
                ops.append((os.path.join(d, DESIGN_DIR, dst_name), read(src)))
        for s in sorted(glob.glob(os.path.join(it['src'], 'specs', '*', 'spec.md'))):
            cap = os.path.basename(os.path.dirname(s))
            ops.append((os.path.join(d, '需求规格', cap + '.md'), read(s)))
        if write_mode:
            for p, text in ops:
                if not os.path.exists(p):
                    write(p, text)
        created += 1

    if base:
        bd = base['dir']
        lines = ['# 基线能力规格', '',
                 '- 需求性质：基线',
                 '- 变更请求：CR-%s' % base['no'],
                 '- 摘要：接管时从 `openspec/specs/` 迁入的 %d 项能力，一项一个文件。'
                 % len(base['caps']),
                 '- 号段：每份能力文件自带要求段',
                 '- 原变更：`openspec/specs/`（只读历史）',
                 '- 迁移：%s 自 OpenSpec 迁入，正文未改写' % TODAY,
                 '', '---', '', '## 能力清单', '']
        lines += ['- `%s` → `能力规格/%s.md`' % (cap, cap) for cap, _ in base['caps']]
        lines.append('')
        ops = [(os.path.join(bd, '01-需求.md'), '\n'.join(lines)),
               (os.path.join(bd, '00-状态.md'), '\n'.join([
                   '# 状态', '',
                   '- 编号：CR-%s' % base['no'],
                   '- 名称：基线能力规格',
                   '- 负责人：—',
                   '- 阶段：delivered',
                   '- 创建：%s' % NOW,
                   '- 更新：%s' % NOW,
                   '- 门禁：G1 approved（历史：随代码合入，未补签）',
                   '- 下一步：无',
                   '- 单元：—',
                   '- 遗留：—',
                   '',
                   '> 迁移记录：%s 自 `openspec/specs/` 迁入。' % TODAY,
                   '']))]
        ops += [(os.path.join(bd, '能力规格', cap + '.md'), read(p))
                for cap, p in base['caps']]
        if write_mode:
            for p, text in ops:
                if not os.path.exists(p):
                    write(p, text)
    return created


def main():
    ap = argparse.ArgumentParser(description='OpenSpec → AIDLC 接管（默认只看不改）')
    ap.add_argument('root', nargs='?', default='.')
    ap.add_argument('--write', action='store_true', help='真建（默认只预演）')
    ap.add_argument('--names', default=None, help='命名.tsv：变更名<TAB>中文简称')
    ap.add_argument('--types', default=None, help='类型.tsv：变更名<TAB>需求/缺陷/技术债（前缀判不准时用）')
    ap.add_argument('--person', default='1', help='人编号 P（团队配置里的 1~9）')
    ap.add_argument('--year', default=time.strftime('%y')[-1], help='年份末位（2026 → 6）')
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    doc = os.path.join(root, '开发文档')
    if not os.path.isdir(os.path.join(root, 'openspec')):
        print('[跳过] 没有 openspec/ 目录，不像 OpenSpec 项目：%s' % root)
        return 0
    if not os.path.isdir(doc):
        print('[错误] 没有 开发文档/ —— 先跑 初始化.py，再接 openspec')
        return 2

    names = load_names(args.names)
    types = load_types(args.types)
    items, base = build_plan(root, args.person, args.year, names, types)
    seen = existing_origins(doc)
    todo = [i for i in items if i['rel'] not in seen]
    print('变更 %d 条：待接管 %d，已迁过 %d' % (len(items), len(todo), len(items) - len(todo)))

    if base and os.path.isdir(base['dir']):
        print('基线：已存在，跳过')
        base = None
    elif base:
        print('基线：CR-%s（%d 项能力）' % (base['no'], len(base['caps'])))

    for i in todo[:8]:
        print('  %s/CR-%s-%s' % (i['type'], i['no'], os.path.basename(i['dir']).split('-', 2)[2]))
    if len(todo) > 8:
        print('  … 另 %d 条' % (len(todo) - 8))

    n = apply_plan(todo, base, names, args.write)
    print('-' * 56)
    if args.write:
        active = [i for i in todo if not i['archived']]
        print('已接管 %d 条 CR（其中 %d 条未归档、阶段 awaiting-approval）。' % (n, len(active)))
        if active:
            print('注意：这 %d 条还缺 `06-执行计划.md`，自检会红一条 —— 这是**预期**的：'
                  % len(active))
            print('      需求定稿后补计划才能进构建，接管不代写施工图。')
        print('下一步：汇总.py --site → 自检.py')
        if not names:
            print('提示：简称用的是英文 slug。要中文名就 --names 命名.tsv，或事后手工改目录名。')
    else:
        print('预演：将接管 %d 条 CR（未落盘）。确认后加 --write。' % n)
    return 0


if __name__ == '__main__':
    sys.exit(main())
