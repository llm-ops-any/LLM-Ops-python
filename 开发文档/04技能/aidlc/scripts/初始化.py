#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AIDLC 项目初始化：一次把「开发文档/」骨架建全，而不是让人/agent 凭记忆一步步来。

为什么有它（2026-10-26，uino-opc/opcapp 实测）：
用户说「初始化项目，入口用 CLAUDE.md，不要改 AGENTS」，agent 只写了一个 CLAUDE.md 就收工了 ——
`开发文档/` 一个目录都没建。SKILL.md 里「建布局」散在第 E 节和启动第 3 步，全是散文，
漏一步不报错，也没有任何提示。**能脚本化的部分就不该交给记性。**

用法
    python <技能>/scripts/初始化.py                     # 初始化当前目录
    python <技能>/scripts/初始化.py D:/path/to/proj      # 指定项目根
    python <技能>/scripts/初始化.py --entry claude       # 入口只写 CLAUDE.md，AGENTS.md 一字不动
    python <技能>/scripts/初始化.py --entry claude --full-entry   # CLAUDE.md 放全文规范（不是一句指针）
    python <技能>/scripts/初始化.py --dry-run            # 只说要做什么
    python <技能>/scripts/初始化.py --no-skill --no-hooks

做的事（幂等，已存在的一律跳过，绝不覆盖用户内容）
    1. 建 开发文档/{00规则,01需求,02缺陷,03技术债,04技能,_汇总}
    2. 00规则/ 五份规则文件 ← 技能模板（项目概述 / 团队配置 / 开发规范 / 文档结构 / 协作规范）
    3. 开发文档/状态.md 快照（可选；每条 CR 的真实状态在 CR-*/00-状态.md）
    4. 技能副本 → 开发文档/04技能/aidlc（项目自包含，换机器/换 agent 都能跑）
    5. 入口锚点（--entry 决定写哪个，见下）
    6. git 钩子（clean merge / 冲突解决后提交 / rebase 收尾自动重建视图）
    7. 重建 _汇总/ 视图 + 跑一次自检

--entry 取值
    auto（默认）  AGENTS.md + CLAUDE.md 始终写；其余平台**项目里有对应目录**才写
    agents        只写 AGENTS.md（通用约定，全文）
    claude        只写 CLAUDE.md 的指针段，**不碰 AGENTS.md**（项目自有 AGENTS.md 时用这个）
    cursor / windsurf / copilot / trae / codebuddy / workbuddy   只写对应平台那一份
    none          不写任何锚点（只建 开发文档/）
"""

import argparse
import io
import os
import re
import subprocess
import sys

sys.dont_write_bytecode = True      # 技能是只读资源，别在里面生 __pycache__

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
TPL = os.path.join(SKILL, 'references')

DIRS = ('00规则', '01需求', '02缺陷', '03技术债', '04技能', '_汇总')
RULES = (
    ('项目概述.template.md', '项目概述.md'),
    ('team-profile.template.md', '团队配置.md'),
    ('dev-conventions.template.md', '开发规范.md'),
    ('文档结构.template.md', '文档结构.md'),
    ('协作规范.template.md', '协作规范.md'),
)

# 模板里的「用法 / 怎么用」是写给复制者的，落到项目里就是噪音。复制时顺手改掉：
#   H1 去掉「（模板）」，紧跟的那段引用块换成一句「本项目声明」。
FINALIZE = {
    '项目概述.md': ('# 项目概述（模板）', '# 项目概述',
                '> 本文件是项目的「入场地图」：定位 / 交付形态 / 技术栈 / 运行时拓扑 / 目录地图 / '
                '核心链路 / 外部依赖 / 硬约束。由人维护，agent 可提修改建议但不得自行扩写；'
                '**不写进度、待办、CR 列表**（进度在 CR，视图在 `_汇总/`）。'),
    '团队配置.md': ('# 团队配置模板', '# 团队配置',
                '> 本文件由人维护：**审批模式、测试策略、角色分工由人定，agent 不得自行改写**。'
                'agent 每次进入门禁前读它。'),
    '开发规范.md': ('# 开发规范（模板）', '# 开发规范',
                '> 本文件由人维护，**写代码前必读**。与 AIDLC 流程规则冲突时，流程以技能为准；'
                '代码风格以本文件为准。'),
    '协作规范.md': ('# 协作规范', '# 协作规范',
                '> 本文件只写**本项目要执行**的差异，通用道理不抄（全文见 '
                '`04技能/aidlc/references/common/parallel-collaboration.md`）。'
                '**单人作业**：保留第 1、5 节（取号 / 开工自检），第 2~4 节删掉，'
                '并在 `文档结构.md` 写明「暂不建 + 为什么」；**多人并行**：全留，人编号表在 `团队配置.md`。'),
}
STATE = '''# AIDLC State

## Current
- Phase: INCEPTION
- Stage: 未开始
- Unit: -

## Executed
- [ ] workspace-detection

## Extension Configuration
| Extension | Enabled | Scope |
|---|---|---|
| security-baseline | no | - |
| property-based-testing | no | - |
| role-gates | yes | 见 00规则/团队配置.md 的审批模式 |
| approve-continue | no | - |
| audit-signature | yes | 取 git config |
| doc-sync | yes | 仅关键变更 |

## Gates
| Gate | Status | Approved by | At |
|---|---|---|---|
| G1 需求定稿 | not-started | - | - |
| G2 设计定稿 | not-started | - | - |
| G3 代码合入 | not-started | - | - |

## Identity
- 当前角色：-（来源：团队配置.md 匹配 / 用户指定）
'''


def run_quiet(cmd, cwd):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, encoding='utf-8', errors='replace')
    return r.returncode, (r.stdout or '') + (r.stderr or '')


def git(*args, cwd='.'):
    r = subprocess.run(['git'] + list(args), cwd=cwd, capture_output=True,
                       encoding='utf-8', errors='replace')
    return r.stdout.strip() if r.returncode == 0 else ''


def find_root(argv_root):
    if argv_root:
        return os.path.abspath(argv_root)
    top = git('rev-parse', '--show-toplevel')
    return top or os.getcwd()


def read(path):
    try:
        with io.open(path, encoding='utf-8', errors='replace') as f:
            return f.read()
    except (IOError, OSError):
        return None


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)


def finalize(text, dst):
    """把「模板」改成「本项目文件」：换 H1、去掉用法说明块。只在这一处动，别的不碰。"""
    spec = FINALIZE.get(dst)
    if not spec:
        return text
    old_h1, new_h1, note = spec
    lines = text.splitlines()
    if not lines or lines[0].strip() != old_h1:
        return text                      # 已经被改过 / 人手改过 → 原样返回，绝不覆盖
    j = 1
    while j < len(lines) and lines[j].strip() == '':
        j += 1
    if j < len(lines) and lines[j].lstrip().startswith('>'):
        while j < len(lines) and (lines[j].lstrip().startswith('>') or lines[j].strip() == ''):
            j += 1
        lines = [new_h1, '', note, ''] + lines[j:]
    else:
        lines[0] = new_h1
    return '\n'.join(lines).rstrip() + '\n'


def fill_project_line(text, name, repo):
    """只动「- 项目名：」「- 仓库：」两行，别的字一个不碰。"""
    out = []
    for line in text.splitlines():
        if line.startswith('- 项目名：') and name:
            line = '- 项目名：%s' % name
        elif line.startswith('- 仓库：') and repo:
            line = '- 仓库：`%s`' % repo
        out.append(line)
    return '\n'.join(out) + '\n'


def git_people(root):
    """从 git 历史读参与人：按**首次提交顺序**返回 [(人编号, 姓名, email, 提交数)]。

    为什么按首次提交排序：人编号是 CR 号第一位，一号一人、永不改；按「谁先进项目」
    分配最接近人的直觉，也最不容易在后续插入新人时重排（新人总是拿最大号）。
    一个人多个 email（工作/个人/另一台机器）→ 每个 email 一行、人编号相同，
    因为取号是查 email，不是查姓名。
    """
    raw = git('log', '--reverse', '--format=%ae\t%an', cwd=root)
    if not raw:
        return []
    order, counts, last_name = [], {}, {}
    for line in raw.splitlines():
        if '\t' not in line:
            continue
        email, name = line.split('\t', 1)
        email = email.strip().lower()
        name = name.strip() or email
        if not email:
            continue
        counts[email] = counts.get(email, 0) + 1
        last_name[email] = name          # 用最近一次提交里的写法（改名后取新名）
        if email not in order:
            order.append(email)
    people, num = [], 0
    for email in order:
        num += 1
        people.append((num, last_name[email], email, counts[email]))
    return people


def fill_team_rows(text, people):
    """把角色表里三行空模板换成 git 读到的人（第一个兼 PO / REV，其余 DEV）。

    只替换那三行；表头、下面的说明块、其它章节一个字不碰。
    """
    if not people:
        return text
    lines = text.splitlines()
    start = None
    for i, ln in enumerate(lines):
        if ln.startswith('| `PO`') and '|' in ln[7:]:
            start = i
            break
    if start is None:
        return text
    end = start
    while end < len(lines) and lines[end].startswith('|'):
        end += 1
    block = []
    for num, name, email, cnt in people:
        note = '提交 %d 次' % cnt
        if num == 1:
            block.append('| `PO` | %s | `%s` | %d | 定范围、验收（%s） |' % (name, email, num, note))
            block.append('| `DEV` | %s | `%s` | %d | 设计实现、写代码 |' % (name, email, num))
            block.append('| `REV` | %s | `%s` | %d | 交叉评审（%s） |' % (name, email, num, note))
        else:
            block.append('| `DEV` | %s | `%s` | %d | 按需参与（%s） |' % (name, email, num, note))
    if len(people) > 9:
        block.append('| — | **超过 9 人** | — | — | 人编号只有 1~9：拆项目或给多人共用编号 + `AIDLC_PERSON` |')
    note = ('> 上表由 `初始化.py` 按 **git 首次提交顺序**自动生成：人编号 = 提交先后，'
            '**分配后不要改**（CR 号第一位）；角色（PO/DEV/REV）是按「第一人兼三角」给的初稿，'
            '按实际分工改；一个人多个 email 就再加行、人编号填同一个。')
    lines[start:end] = block + ['', note]
    return '\n'.join(lines) + '\n'


def _team_rows(text):
    """取 `## 角色` 段里的表格行 → [(行号, [cells]), ...]。"""
    lines = text.splitlines()
    try:
        i = lines.index('## 角色')
    except ValueError:
        return lines, []
    rows, j = [], i + 1
    while j < len(lines):
        if lines[j].startswith('## '):
            break
        if lines[j].lstrip().startswith('|'):
            rows.append((j, [c.strip() for c in lines[j].strip().strip('|').split('|')]))
        j += 1
    return lines, rows


def refresh_team(text, people, maps=None):
    """把 git 里出现、但表里没有的人**追加**进角色表；**已有人编号一律不动**。

    为什么不重排：人编号是 CR 号的第一位（`16102100` 的 `1`）。重排等于让历史 CR 对不上人，
    比「编号不连续」贵得多。新来的人永远拿 max+1。
    `maps`：{email: 人编号}，用于「这个人不是新人，只是多了个邮箱」。
    """
    maps = maps or {}
    lines, rows = _team_rows(text)
    if not rows:
        return text, []
    have, maxnum = {}, 0
    for _j, cells in rows:
        if len(cells) < 5:
            continue
        email = cells[2].strip().strip('`').lower()
        try:
            num = int(re.sub(r'[^0-9]', '', cells[3]) or 0)
        except ValueError:
            num = 0
        if email:
            have[email] = num
        maxnum = max(maxnum, num)
    added, insert_at = [], None
    for _num, name, email, cnt in people:
        e = email.lower()
        if e in have:
            continue
        num = maps.get(e) or maps.get(email)
        if num:
            num = int(num)
            note = 'git 提交 %d 次（同一个人另一个邮箱）' % cnt
        else:
            maxnum += 1
            num = maxnum
            note = 'git 提交 %d 次（身份待确认，改姓名即可）' % cnt
        added.append((num, '| `DEV` | %s | `%s` | %d | %s |' % (name, email, num, note)))
        have[e] = num
    if not added:
        return text, []
    added.sort(key=lambda x: x[0])
    for j, cells in rows:
        insert_at = j
    lines[insert_at + 1:insert_at + 1] = [r for _n, r in added]
    return '\n'.join(lines) + '\n', added


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument('root', nargs='?', default=None, help='项目根（默认：git 顶层，或当前目录）')
    ap.add_argument('--entry', default='auto',
                    choices=('auto', 'agents', 'claude', 'cursor', 'windsurf', 'copilot',
                             'trae', 'codebuddy', 'workbuddy', 'none'),
                    help='入口锚点写哪个；claude = 只写 CLAUDE.md，不碰 AGENTS.md')
    ap.add_argument('--name', default='', help='项目名（默认取目录名）')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--full-entry', action='store_true',
                    help='入口文件放全文规范（默认只放一句指针）；配合 --entry claude 时，'
                         '整个 AIDLC 规矩写进 CLAUDE.md，AGENTS.md 仍一字不动')
    ap.add_argument('--no-skill', action='store_true', help='不复制技能副本')
    ap.add_argument('--no-hooks', action='store_true', help='不装 git 钩子')
    ap.add_argument('--no-verify', action='store_true', help='跑完不自检')
    ap.add_argument('--refresh-team', action='store_true',
                    help='把 git 里出现、角色表还没有的人追加进 团队配置.md（已有人编号不动）')
    ap.add_argument('--map', action='append', default=[],
                    help='email=人编号，用于「不是新人，只是多一个邮箱」，可多次')
    ap.add_argument('--refresh-templates', action='store_true',
                    help='只把已存在规则文件的「模板头」改成项目格式（H1 + 用法块），不动正文')
    args = ap.parse_args()

    root = find_root(args.root)
    if not os.path.isdir(root):
        print('✗ 不是目录：%s' % root)
        return 2
    name = args.name or os.path.basename(root.rstrip('\\/'))
    repo = git('remote', 'get-url', 'origin', cwd=root)
    doc = os.path.join(root, '开发文档')
    dry = args.dry_run

    print('AIDLC 初始化  %s' % root)
    print('入口文件：%s　　技能：%s' % (args.entry, SKILL))
    print('-' * 60)

    # 1. 目录
    made, kept = [], []
    for d in DIRS:
        p = os.path.join(doc, d)
        if os.path.isdir(p):
            kept.append(d)
        else:
            made.append(d)
            if not dry:
                os.makedirs(p)
    print('1 目录      %s' % ('新建 %s' % ' '.join(made) if made else '六个目录都在'))

    # 2. 规则文件
    for src, dst in RULES:
        sp, dp = os.path.join(TPL, src), os.path.join(doc, '00规则', dst)
        if os.path.exists(dp):
            if args.refresh_templates:
                cur = read(dp) or ''
                new = finalize(cur, dst)
                if new != cur and not dry:
                    write(dp, new)
                    print('2 规则      %-12s 已改成本项目格式（模板头去掉）' % dst)
                else:
                    print('2 规则      %-12s 已是本项目格式' % dst)
            elif dst == '团队配置.md' and args.refresh_team:
                cur = read(dp) or ''
                maps = {}
                for kv in args.map:
                    if '=' in kv:
                        k, v = kv.split('=', 1)
                        maps[k.strip().lower()] = v.strip()
                new, added = refresh_team(cur, git_people(root), maps)
                if added and not dry:
                    write(dp, new)
                    print('2 团队      %-12s 追加 %d 人：%s' % (
                        dst, len(added), '、'.join(re.sub(r'^.*?\|\s*`([^`]+)`\s*\|\s*(\d+)\s*\|.*$',
                                                          r'\1(#\2)', r) for _n, r in added)))
                elif added:
                    print('2 团队      %-12s 将追加 %d 人' % (dst, len(added)))
                else:
                    print('2 团队      %-12s 与 git 一致，无新人' % dst)
            else:
                print('2 规则      %-12s 已存在，跳过（不覆盖）' % dst)
            continue
        text = read(sp)
        if text is None:
            print('2 规则      %-12s ✗ 找不到模板 %s' % (dst, src))
            continue
        text = finalize(text, dst)
        suffix = ''
        if dst == '团队配置.md':
            text = fill_project_line(text, name, repo)
            people = [] if dry else git_people(root)
            if people:
                text = fill_team_rows(text, people)
                suffix = '，人编号已按 git 的 %d 位参与人预填' % len(people)
            else:
                suffix = '，未读到 git 参与人，角色表待填'
        if dry:
            print('2 规则      %-12s 将复制' % dst)
        else:
            write(dp, text)
            print('2 规则      %-12s 已复制（待填）%s' % (dst, suffix))

    # --refresh-templates 只改规则文件的「模板头」，别的什么都不做。
    # （2026-10-26 踩到：这个模式曾继续走锚点步骤，entry 默认 auto ⇒ 顺手把 AGENTS.md 也接管了，
    #   而用户明确说过「不要改 AGENTS」。只改文本的开关不能有写别的文件的副作用。）
    if args.refresh_templates:
        print('-' * 60)
        print('完成：只刷新了规则文件头，目录 / 状态 / 技能副本 / 锚点 / 钩子全部跳过。')
        return 0

    # 3. 状态
    sp = os.path.join(doc, '状态.md')
    if os.path.exists(sp):
        print('3 状态      已存在，跳过')
    elif dry:
        print('3 状态      将新建骨架')
    else:
        write(sp, STATE)
        print('3 状态      已建骨架')

    # 4~5. 技能副本 + 锚点：交给 anchors 脚本（幂等、不覆盖原文）
    anchor = os.path.join(HERE, 'install-project-anchors.py')
    cmd = [sys.executable, anchor, root]
    if args.entry == 'none':
        # --no-skill 必须压过 --skill-only，否则这个参数组合等于没写（2026-10-29 自测踩到）
        if not args.no_skill:
            cmd.append('--skill-only')
    else:
        cmd += ['--platforms', 'auto' if args.entry == 'auto' else args.entry]
        if args.full_entry:
            cmd.append('--full')
        if not args.no_skill:
            cmd.append('--with-skill')
    if dry:
        cmd.append('--dry-run')
    rc, out = run_quiet(cmd, root)
    print('4 技能+锚点')
    for line in out.splitlines():
        if line.strip():
            print('   ' + line)
    if rc != 0:
        print('   ✗ 锚点脚本异常（继续，其余步骤不受影响）')

    # 6. 钩子：必须在技能副本存在之后，且得有 git
    dest = os.path.join(doc, '04技能', 'aidlc')
    hooks = os.path.join(dest, 'scripts', '安装钩子.py')
    if args.no_hooks:
        print('6 钩子      按参数跳过')
    elif not os.path.isdir(os.path.join(root, '.git')):
        print('6 钩子      不是 git 仓库，跳过')
    elif dry:
        print('6 钩子      将安装（core.hooksPath → 开发文档/04技能/aidlc/scripts/hooks）')
    elif not os.path.isfile(hooks):
        print('6 钩子      没有技能副本，跳过（加 --with-skill 或去掉 --no-skill）')
    else:
        rc, out = run_quiet([sys.executable, hooks], root)
        lines = [l for l in out.splitlines() if l.strip()]
        print('6 钩子      %s' % (lines[0] if lines else '(无输出)'))
        if rc != 0:
            print('   ✗ 钩子安装失败，原始输出：')
            for l in lines[:12]:
                print('     ' + l)

    # 7. 视图 + 自检
    summary = os.path.join(dest, 'scripts', '汇总.py')
    check = os.path.join(dest, 'scripts', '自检.py')
    has_cr = any(
        f.startswith('CR') and os.path.isdir(os.path.join(doc, t, f))
        for t in ('01需求', '02缺陷', '03技术债')
        for f in (os.listdir(os.path.join(doc, t)) if os.path.isdir(os.path.join(doc, t)) else [])
    )
    if dry:
        print('7 视图+自检 预演跳过')
        print('\n预演结束。去掉 --dry-run 执行。')
        return 0
    if not has_cr:
        print('7 视图      跳过（还没有 CR，等第一条 CR 建目录后再跑 汇总.py）')
    elif os.path.isfile(summary):
        rc, out = run_quiet([sys.executable, summary], root)
        tail = [l for l in out.splitlines() if l.strip()][-1:]
        print('7 视图      %s' % (tail[0] if tail else '(无输出)'))
    if os.path.isfile(check) and not args.no_verify:
        rc, out = run_quiet([sys.executable, check, '--quiet'], root)
        print('8 自检      %s' % ('' if rc == 0 else '有问题，见下'))
        for line in out.splitlines():
            if line.strip() and not line.startswith('AIDLC 自检'):
                print('   ' + line)

    print('-' * 60)
    print('下一步（必须人工做，脚本不代劳）：')
    print('  1. 填 开发文档/00规则/项目概述.md：一句话定位、技术栈版本、运行时拓扑、核心链路、外部依赖、硬约束')
    print('  2. 填 开发文档/00规则/团队配置.md：审批模式（五档选一）、测试策略（三选一）、角色与邮箱、人编号')
    print('  3. 填 开发文档/00规则/开发规范.md：语言/语法版本、交付形态、测试框架、目录分层')
    print('  4. 填 开发文档/00规则/文档结构.md 第四节「本项目补充」')
    print('  5. 过一遍 开发文档/00规则/协作规范.md：单人就删掉第 2~4 节，多人补人编号表（团队配置.md）')
    print('  6. 若项目里已有 openspec/：python 04技能/aidlc/scripts/接管-openspec.py <项目根> --write')
    print('     （先把历史变更迁成 CR，再接新需求；迁移前后都跑 汇总.py + 自检.py）')
    print('  7. 逐条过 references/初始化自检清单.md，再开始第一条 CR')
    return 0


if __name__ == '__main__':
    sys.exit(main())
