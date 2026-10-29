#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自检的「CR 内容」检查：生成物 / 基线 / 编号 / 执行计划 / 前置资源 / 风险 / 死规则 / 孤儿 / 时间。

从 `自检.py` 拆出来（2026-10-29，单文件 25KB 上限）。
"""

import glob
import io
import os
import re
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _aidlc_common import find_cr_file  # noqa: E402
from _check_common import *  # noqa: F401,F403
from _check_common import (ROOT, SUMDIR, GENERATED, CR_RE, DECL_RE, read, git,  # noqa: E402
                           is_repo)

def tracked_generated():
    """仍被 git 跟踪的 `_汇总/` 里的文件。非空 ⇒ 并行合并会冲突。"""
    r = git('ls-files', '--', SUMDIR)
    if r.returncode != 0:
        return []
    return [l.strip() for l in r.stdout.splitlines() if l.strip()]


def check_generated(rows):
    # 顺序很重要：先查「是否入库」，这是并行冲突的直接成因
    stuck = tracked_generated()
    if stuck:
        rows.append(('x', '生成物', '根级视图仍被 git 跟踪：%s' % '、'.join(
            x.split('/')[-1] for x in stuck),
            'git rm --cached 掉并补 .gitignore —— 分片入库、根级视图不入库，否则两人合并必冲突'))

    missing = [p for p in GENERATED if not os.path.isfile(os.path.join(ROOT, p))]
    if missing:
        rows.append(('d', '生成物', '本地还没生成：%s' % '、'.join(
            x.split('/')[-1] for x in missing),
            '跑一次 汇总.py（这些是本地视图，不入库）'))
        return
    # 页面是「汇总」的另一半：md 有了却没有 index.html ⇒ 只做了一半。
    # 2026-10-27 opcapp：agent 连跑两遍 汇总.py 就回「汇总做了」，用户拿不到能点开的页面。
    # 只给建议（w）不判错：不用页面、只读 md 的项目（CLI / 纯文档）也合法。
    if not os.path.isfile(os.path.join(SUMDIR, 'index.html')):
        rows.append(('w', '生成物', '只有 md 视图，没有 _汇总/index.html',
                     '要给人看就 汇总.py --site（或 预览.py --no-serve）；不用页面可忽略'))

    sk = proj_skill()
    if not sk:
        rows.append(('d', '生成物', '没有技能副本，跳过新鲜度检查', ''))
        return
    summary = os.path.join(sk, 'scripts', '汇总.py')
    if not os.path.isfile(summary):
        rows.append(('w', '生成物', '技能副本里没有 汇总.py', '重新同步副本'))
        return
    r = subprocess.run([sys.executable, summary, '--check'], cwd=ROOT,
                       capture_output=True, encoding='utf-8', errors='replace')
    if r.returncode == 0:
        rows.append(('v', '生成物', '生成物是最新的', ''))
    else:
        msg = (r.stdout or r.stderr or '').strip().splitlines()
        rows.append(('w', '生成物', '生成物可能过期：%s' % (msg[-1] if msg else 'check 非 0'),
                     '跑 汇总.py 重建'))


# ── 规则四件套：模板是「整份复制 + 填空」，不是「照意思重写」 ──────────────
# 2026-10-26（hld-hj-web 实测）：团队配置.md 5.6 KB → 3.4 KB，审批模式只剩
# 「关键三关　←　G1 / G2 / G3 三处停」一句自编注释，五档可选清单和含义表全丢。
# 文件在、内容瘦了 —— 比缺文件更难发现，所以交给脚本查。
def check_baseline(rows):
    """基线需求应当有且仅有一条（`需求性质：基线`）。

    基线是「第一版需求」的唯一锚点；没有它，`_汇总/当前需求全貌.md` 就拼不出完整脉络；
    多于一条则说明有人把增量误标成基线，全貌的「基线在前」排序会失真。
    """
    found = []
    for d in _cr_dirs():
        rq = find_cr_file(d, '需求')
        if not rq:
            continue
        with io.open(rq, encoding='utf-8', errors='replace') as f:
            head = f.read(1200)
        if re.search(r'^-\s*需求性质[：:]\s*基线\s*$', head, re.M):
            found.append(os.path.basename(d))
    if not _cr_dirs():
        rows.append(('d', '基线', '还没有 CR，跳过（首条需求的 需求.md 里写 `- 需求性质：基线`）', ''))
    elif len(found) == 1:
        rows.append(('v', '基线', '1 条基线（%s）' % found[0], ''))
    elif not found:
        rows.append(('w', '基线', '没有任何 CR 标 `需求性质：基线`',
                     '第一版需求要在 `需求.md` 里写 `- 需求性质：基线`，否则全貌视图分不清基线和增量'))
    else:
        rows.append(('x', '基线', '有 %d 条基线：%s' % (len(found), '、'.join(found)),
                     '基线只能有一条。增量 CR 请写 `- 需求性质：增量`（或不写）'))


# `汇总.py` / `自检.py` 硬依赖的字段 —— 每个都该至少有一个分片在写。
# 某字段全项目 0 使用 ⇒ 脚本在解析一个没人产出的东西，等于空转。
# 左列是**逻辑名**（`需求` / `状态`），实际文件名由 find_cr_file 解析（带不带编号都行）。
CONTRACT_FIELDS = (
    ('需求', '变更请求'),
    ('需求', '摘要'),
    ('需求', '号段'),
    ('需求', '需求性质'),
    ('状态', '编号'),
    ('状态', '名称'),
    ('状态', '负责人'),
    ('状态', '创建'),
    ('状态', '更新'),
    ('状态', '阶段'),
    ('状态', '门禁'),
    ('状态', '下一步'),
)


def _cr_dirs():
    out = []
    for k in ('01需求', '02缺陷', '03技术债'):
        out += glob.glob(os.path.join(ROOT, '开发文档', k, 'CR-*'))
    return [d for d in out if os.path.isdir(d)]


def check_dead_rules(rows):
    """死规则检测：脚本/规则依赖的字段，若全项目 0 使用 ⇒ 空转，报警。

    为什么需要：`汇总.py` 曾解析 `需求.md` 里的 `| 修订既有条目 |` 行，而 10 个需求.md
    一个都没写过 —— 那一节永远只有表头，**看着在跑，其实空转**。这类问题读文档发现不了。
    """
    if not _cr_dirs():
        rows.append(('d', '死规则', '还没有 CR，跳过', ''))
        return
    by_name = {}
    for d in _cr_dirs():
        for name in ('需求', '状态'):
            p = find_cr_file(d, name)
            if p:
                by_name.setdefault(name, []).append(p)

    dead = []
    for logical, field in CONTRACT_FIELDS:
        cands = by_name.get(logical, [])
        used = 0
        for f in cands:
            with io.open(f, encoding='utf-8', errors='replace') as fh:
                if re.search(r'^-\s*' + re.escape(field) + r'\s*[：:]', fh.read(), re.M):
                    used += 1
        if used == 0:
            dead.append('%s 的 `%s`' % (logical, field))

    if dead:
        rows.append(('w', '死规则', '%d 个字段全项目没人写：%s' % (len(dead), '、'.join(dead)),
                     '脚本在解析它们 ⇒ 解析结果永远是空。要么补写，要么把这条规则删掉'))
    else:
        rows.append(('v', '死规则', '契约字段都在用（%d 项）' % len(CONTRACT_FIELDS), ''))


CR_TS_RE = re.compile(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$')


def check_cr_times(rows, fix=False):
    """每条 CR 的 `状态.md` 都要有 `创建` / `更新`，且是 `YYYY-MM-DD HH:MM:SS`。

    为什么要它：这两个时间以前谁都没写，想知道「这条 CR 多久没动」只能翻 git，
    而 git 时间会被批量重构污染 —— 试点2 实测有 3 个 CR 目录的首提交都是同一次重构的
    16:57:04，把重构时刻当成了 CR 创建时刻。

    `--fix` 会按**状态文件的 mtime** 补上缺的两行（真实时间，不是编的）：
    迁移/接管进来的历史 CR 只有这一个可信时刻，补完至少「多久没动」能算。
    """
    dirs = _cr_dirs()
    if not dirs:
        rows.append(('d', 'CR 时间', '还没有 CR，跳过', ''))
        return
    bad, fixed = [], 0
    for d in dirs:
        p = find_cr_file(d, '状态')
        if not p:
            continue
        text = read(p)
        vals = {}
        for m in re.finditer(r'^-\s*(创建|更新)\s*[：:]\s*(.*)$', text, re.M):
            vals.setdefault(m.group(1), m.group(2).strip())
        name = os.path.basename(d)
        miss = [k for k in ('创建', '更新') if not vals.get(k)]
        if miss and fix:
            t = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(os.path.getmtime(p)))
            lines = text.split('\n')
            idx = None
            for i, ln in enumerate(lines):
                if ln.startswith(('- 阶段：', '- 阶段:')):
                    idx = i
                    break
            if idx is None:
                for i, ln in enumerate(lines):
                    if ln.startswith('- 编号'):
                        idx = i
                        break
            add = ['- %s：%s' % (k, t) for k in miss]
            if idx is None:
                lines = [lines[0], ''] + add + lines[1:]
            else:
                lines[idx + 1:idx + 1] = add
            with io.open(p, 'w', encoding='utf-8', newline='\n') as f:
                f.write('\n'.join(lines))
            fixed += 1
            continue
        if miss:
            bad.append('%s 缺 %s' % (name, '/'.join(miss)))
        for k in ('创建', '更新'):
            v = vals.get(k)
            if v and not CR_TS_RE.match(v):
                bad.append('%s 的 %s 写成「%s」' % (name, k, v))
    if fixed:
        rows.append(('v', 'CR 时间', '%d 条 CR 缺创建/更新 → 已按文件时间补（--fix）' % fixed, ''))
    if bad:
        rows.append(('w', 'CR 时间', '%d 处时间缺失或格式不对' % len(bad),
                     '；'.join(bad[:6]) + (' 等' if len(bad) > 6 else '')
                     + ' —— 统一写 `- 创建：YYYY-MM-DD HH:MM:SS`（年月日 时分秒）；'
                       '或跑 --fix 按文件时间自动补'))
    elif not fixed:
        rows.append(('v', 'CR 时间', '%d 条 CR 的创建/更新时间齐全（年月日 时分秒）' % len(dirs), ''))


def check_orphan_cr(rows):
    """CR 目录里既无 `状态.md` 也无 `需求.md`/`问题.md` ⇒ 汇总会静默跳过它。

    静默丢失比报错危险：一条 CR 干了活、写了文档，却不出现在任何视图里，没人会发现。
    """
    orphan = []
    for d in _cr_dirs():
        if not find_cr_file(d, '状态') and not find_cr_file(d, '需求') \
                and not find_cr_file(d, '问题'):
            orphan.append(os.path.basename(d))
    if orphan:
        rows.append(('w', '孤儿 CR', '%d 个 CR 目录缺 00-状态.md / 01-需求.md / 02-问题.md' % len(orphan),
                     '汇总会跳过它们：%s ⇒ 补一个 `00-状态.md`（阶段可先写 not-started）'
                     % '、'.join(orphan[:3])))
    else:
        rows.append(('v', '孤儿 CR', '每条 CR 都有 00-状态.md 或 01-需求.md / 02-问题.md', ''))


def _table(text):
    """取 markdown 第一张表 → [{表头: 单元格}]（与 汇总.py 的 _md_table 同口径）。"""
    head, out = None, []
    for line in text.splitlines():
        s = line.strip()
        if s.startswith('|') and s.endswith('|'):
            cells = [c.strip() for c in s[1:-1].split('|')]
            if head is None:
                head = cells
                continue
            if cells and all(set(c) <= set('-: ') for c in cells):
                continue
            out.append(dict(zip(head, cells)))
        elif out:
            break
    return out


def _get(row, key):
    """按表头前缀取值（表头可能写成「触发信号（怎么知道它发生了）」）。"""
    if key in row:
        return row[key]
    for k, v in row.items():
        if k.startswith(key):
            return v
    return '—'


def _crno(d):
    """目录名 → CR 号。`CR-16102999-反向验证` → `CR-16102999`。

    不能用 `split('-', 1)[0]`：那只会得到 "CR"，报错信息里就看不出是哪一条。
    """
    m = re.match(r'(CR[-_]?\d+)', os.path.basename(d))
    return m.group(1) if m else os.path.basename(d)


def _base(v):
    """去掉括号说明：`已接受（成本>收益）` → `已接受`。"""
    return re.split(r'[（(]', (v or '').strip(), maxsplit=1)[0].strip()


def _stage(cr):
    """当前阶段（小写）。没有状态文件 ⇒ 空串。"""
    p = find_cr_file(cr, '状态')
    if not p:
        return ''
    with io.open(p, encoding='utf-8', errors='replace') as f:
        m = re.search(r'^-\s*阶段[：:]\s*(.+)$', f.read(), re.M)
    return (m.group(1) if m else '').strip().lower()


def _started(cr):
    """这条 CR 是否已经开工。

    不算开工的：`not-started`（占了号没动）、`cancelled`（撤回）、
    **`awaiting-approval`（还在等 G1 批准，一个字都没写）**、阶段空。

    为什么要把 awaiting-approval 排除：2026-10-29 实测（中海油 haiyou）某条技术债
    阶段写 `awaiting-approval`、下一步写「PO 审完批准，批准后本轮仍不实施」——
    它连需求都还没批，却被判「已开工却没有执行计划」，报了一条假 ✗。
    开工的标志是**进入设计/编码**，不是「等批」。
    """
    stage = _stage(cr)
    return not ('not-started' in stage or 'cancelled' in stage
                or 'awaiting-approval' in stage or not stage)


def _closed(cr):
    """已交付 / 已归档的 CR：终态，不再要求「施工图」。

    为什么单独判：迁移老项目时，历史 CR 会被批量补上编号（`状态.md` → `00-状态.md`），
    于是从「老命名 ⇒ 只建议」变成「新命名 ⇒ 判错」——**已交付的 CR 被要求补计划**，
    这是把自检变成噪音。计划是进构建前的施工图，交付完了再补等于事后编造。
    """
    stage = _stage(cr)
    return any(k in stage for k in ('delivered', 'archived', 'done', 'closed', '已交付', '已归档'))


def check_plan(rows):
    """已开工却没有 `06-执行计划.md` ⇒ 判错（老命名 CR 给建议，不一次报一片红）。

    为什么：需求定稿到写第一行代码之间，必须有一份「分几步、改哪个文件、怎么验、不做什么」。
    没有它，agent 拿到需求就直接开写，漏改文件、顺手扩范围、验收对不上 AC 都从这里来。
    **缺陷类也要写，只是版面小**（缺计划的表现与档位无关）。

    为什么对新老项目区别对待：`06-执行计划.md` 是 2026-10-27 才引入的，
    迁移前的老 CR 本来就没有 —— 一上来全判错，只会让人把自检当噪音关掉。
    """
    hard, soft, ok, idle, closed = [], [], 0, 0, []
    for d in _cr_dirs():
        if _closed(d):
            closed.append(_crno(d))
            continue
        if not _started(d):
            idle += 1
            continue
        if find_cr_file(d, '执行计划'):
            ok += 1
            continue
        st = find_cr_file(d, '状态')
        new_style = bool(st) and os.path.basename(st)[:1].isdigit()
        (hard if new_style else soft).append(_crno(d))

    if hard:
        rows.append(('x', '执行计划', '%d 条已开工的 CR 缺 `06-执行计划.md`' % len(hard),
                     '%s ⇒ 补一份（改动清单 + 步骤 + 验收映射），没有它不许进构建'
                     % '、'.join(hard[:4])))
    if soft:
        rows.append(('w', '执行计划', '%d 条老命名 CR 缺 `06-执行计划.md`（迁移前的，可不补）' % len(soft),
                     '%s ⇒ 新 CR 从需求定稿起就写；老 CR 顺手补也行' % '、'.join(soft[:4])))
    if not hard and not soft:
        rows.append(('v', '执行计划', '%d 条已开工 CR 都有执行计划' % ok, ''))
    elif not hard:
        rows.append(('d', '执行计划', '另有 %d 条未开工、%d 条已有计划' % (idle, ok), ''))
    if closed:
        rows.append(('d', '执行计划', '%d 条已交付/归档的历史 CR 无计划（终态，不补）' % len(closed), ''))


def check_resources(rows):
    """前置资源没到位却已经开工 ⇒ 判错。

    `前置资源.md` 里 `必需 + 待提供` 意味着「缺了做不了」。若这条 CR 的阶段已经推进
    （不是 not-started / cancelled），说明在资源没到的情况下开工了 —— 这正是要防的。
    """
    bad, total_file = [], 0
    for d in _cr_dirs():
        p = find_cr_file(d, '前置资源')
        if not p:
            continue
        total_file += 1
        with io.open(p, encoding='utf-8', errors='replace') as f:
            items = _table(f.read())
        missing = [_get(it, '资源') for it in items
                   if _get(it, '必需性') == '必需' and _base(_get(it, '状态')) == '待提供']
        if missing and _started(d):
            bad.append('%s（缺：%s）' % (_crno(d), '、'.join(missing[:3])))
    if bad:
        rows.append(('x', '前置资源', '%d 条 CR 在必需资源「待提供」时就开工了' % len(bad),
                     '；'.join(bad[:3]) + ' ⇒ 要么等资源，要么在 `前置资源.md` 写明降级方案并改状态'))
    elif total_file:
        rows.append(('v', '前置资源', '%d 条 CR 登记了前置资源，无「必需且待提供」' % total_file, ''))
    else:
        rows.append(('d', '前置资源', '还没有 CR 写 前置资源.md', '有外部依赖的 CR（模型/设计图/API Key/设备）应写'))


def check_risks(rows):
    """高风险仍「待处理」，但 CR 还在做 ⇒ 建议确认（不判错）。

    只查「影响=高」：中低风险本来就是边做边看，天天提醒等于噪音。
    """
    hot, total_file = [], 0
    for d in _cr_dirs():
        p = find_cr_file(d, '风险')
        if not p:
            continue
        total_file += 1
        if not _started(d):
            continue        # 还没开工的 CR，风险刚登记、本来就没处理，提醒是噪音
        with io.open(p, encoding='utf-8', errors='replace') as f:
            items = _table(f.read())
        for it in items:
            if _get(it, '影响') == '高' and _base(_get(it, '状态')) in ('待处理', '已发生'):
                hot.append('%s/%s' % (_crno(d), _get(it, '编号')))
    if hot:
        rows.append(('w', '风险', '%d 条高影响风险仍未处理：%s' % (len(hot), '、'.join(hot[:3])),
                     '确认是否已知悉；处理完把状态改成「已缓解」或「已接受」'))
    elif total_file:
        rows.append(('v', '风险', '%d 条 CR 登记了风险，无未处理的高影响项' % total_file, ''))
    else:
        rows.append(('d', '风险', '还没有 CR 写 风险.md', ''))


def check_numbers(rows):
    """检查 CR 号有没有重复。

    号写在**目录名**里（`CR-<8位号>-<简称>`），不再有单独的「号段文件」——
    目录名就是占位凭据，同号必然撞同一路径。
    """
    seen = {}
    dup = []
    # CR 直接挂在类型目录下：开发文档/01需求/CR-xxx、02缺陷/CR-xxx、03技术债/CR-xxx
    for kname in ('01需求', '02缺陷', '03技术债'):
        kdir = os.path.join(ROOT, '开发文档', kname)
        if not os.path.isdir(kdir):
            continue
        for d in os.listdir(kdir):
            if not os.path.isdir(os.path.join(kdir, d)) or not d.startswith('CR'):
                continue
            m = re.match(r'CR[-_]?(\d+)', d)
            if not m:
                continue
            no = m.group(1)
            if no in seen:
                dup.append('%s 与 %s' % (seen[no], d))
            else:
                seen[no] = d
    if dup:
        rows.append(('x', '编号', 'CR 号重复：%s' % '；'.join(dup),
                     '两条 CR 用同一个号 ⇒ 目录名必须不同。号是「人+年末位+月日+当日序号」算出来的，重算'))
    else:
        rows.append(('v', '编号', '%d 条 CR，编号无重复' % len(seen), ''))


# ── 规则四件套：模板是「整份复制 + 填空」，不是「照意思重写」 ──────────────
# 2026-10-26（hld-hj-web 实测）：团队配置.md 5.6 KB → 3.4 KB，审批模式只剩
# 「关键三关　←　G1 / G2 / G3 三处停」一句自编注释，五档可选清单和含义表全丢。
# 文件在、内容瘦了 —— 比缺文件更难发现，所以交给脚本查。
