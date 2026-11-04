#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自检的「项目结构」检查：锚点 / 技能副本 / 版本 / 钩子 / gitattributes / 布局 / 规则文件。

从 `自检.py` 拆出来（2026-10-29，单文件 25KB 上限）。
"""

import os
import re
import subprocess
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _check_common import *  # noqa: F401,F403
from _check_common import (ROOT, HERE, SELF, SKILL_REL, MARK, LAYOUT, REQUIRED_DIRS,  # noqa: E402
                           git, read, is_repo, proj_skill, _skill_version, _vtuple,
                           HOST_SKILLS)

def check_anchors(rows):
    # 先看各平台 —— 有的项目刻意不让 AGENTS.md 接管（比如上游仓库自有 AGENTS.md，
    # 只允许写 CLAUDE.md）。那种情况不是错，但要说清楚「入口在哪」。
    platforms = (
        ('CLAUDE.md', 'Claude Code'),
        ('.cursor/rules/aidlc.mdc', 'Cursor'),
        ('.windsurf/rules/aidlc.md', 'Windsurf'),
        ('.github/copilot-instructions.md', 'Copilot'),
        ('.trae/rules/aidlc.md', 'Trae'),
        ('.codebuddy/rules/aidlc.mdc', 'CodeBuddy'),
        ('.workbuddy/memory/MEMORY.md', 'WorkBuddy'),
    )
    marked = []
    for rel, why in platforms:
        t = read(os.path.join(ROOT, rel))
        if t is None:
            rows.append(('d', '锚点', '%s 无（未用 %s）' % (rel, why), ''))
        elif MARK not in t:
            rows.append(('w', '锚点', '%s 存在但没有标记段' % rel, '重跑 install-project-anchors.py'))
        else:
            marked.append(rel)
            rows.append(('v', '锚点', '%s 含标记段' % rel, ''))

    p = os.path.join(ROOT, 'AGENTS.md')
    txt = read(p)
    alt = '、'.join(marked) or '其它平台'
    if txt is None:
        if marked:
            rows.append(('w', '锚点', 'AGENTS.md 不存在（入口走 %s）' % alt,
                         '本项目的入口不在 AGENTS.md；要它接管就再跑 --platforms agents'))
        else:
            rows.append(('x', '锚点', 'AGENTS.md 不存在，且没有任何平台入口',
                         '跑 install-project-anchors.py <项目根> —— 没有锚点，技能不会被触发'))
    elif MARK not in txt:
        if marked:
            rows.append(('w', '锚点', 'AGENTS.md 没有标记段（入口走 %s）' % alt,
                         '刻意不接管 AGENTS.md 的话可以忽略；否则跑 --platforms agents 补上'))
        else:
            rows.append(('x', '锚点', 'AGENTS.md 没有 AIDLC 标记段',
                         '重跑 install-project-anchors.py，它会整段补齐（不动你原有内容）'))
    else:
        rows.append(('v', '锚点', 'AGENTS.md 含 AIDLC:v2 段', ''))


# 技能副本固定落点。测试阶段不做旧落点兼容（兼容分支是死代码）。
def check_skill_copy(rows):
    main = os.path.join(ROOT, SKILL_REL)
    if os.path.isfile(os.path.join(main, 'SKILL.md')):
        n = sum(1 for d, _dn, fs in os.walk(main) for _f in fs if '__pycache__' not in d)
        rows.append(('v', '技能副本', '%s/（%d 个文件）' % (SKILL_REL, n), ''))
    else:
        rows.append(('x', '技能副本', '找不到 %s/SKILL.md' % SKILL_REL,
                     '跑 install-project-anchors.py <项目根> --with-skill，项目才能自包含'))

    root_skills = os.path.join(ROOT, 'skills')
    if os.path.isdir(root_skills):
        # 只有「把 aidlc 放错位置」才算错。项目自带 skills/（agent 技能仓库、OPC 的 paperclip
        # 技能包）是正常内容，不能一概判错 —— 2026-10-26 opcapp 实测误报。
        misplaced = (os.path.isfile(os.path.join(root_skills, 'aidlc', 'SKILL.md'))
                     or os.path.isfile(os.path.join(root_skills, 'SKILL.md')))
        if misplaced:
            rows.append(('x', '技能副本', '项目根 skills/ 里放的是 aidlc 副本',
                         '项目根不放技能副本，只放 %s/' % SKILL_REL))
        else:
            rows.append(('d', '技能副本', '项目根 skills/ 是项目自己的（不含 aidlc），不影响', ''))
    pyc = [d for d, _dn, _fn in os.walk(main) if os.path.basename(d) == '__pycache__']
    if pyc:
        rows.append(('w', '技能副本', '技能副本里有 __pycache__',
                     '会让副本与技能源 diff 出差异；删掉（别提交）'))


def check_version(rows):
    """副本 SKILL.md 有没有 version；有宿主技能时比一下新旧。

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

    host = None
    for p in HOST_SKILLS:
        p2 = os.path.expanduser(p)
        if os.path.isfile(p2):
            host = (_skill_version(p2), p2)
            break
    if not host:
        rows.append(('v', '版本', '副本版本 %s（本机没找到宿主技能，无从比对）' % mine, ''))
        return
    theirs, where = host
    if not theirs:
        rows.append(('v', '版本', '副本版本 %s（宿主未标版本：%s）' % (mine, where), ''))
    elif _vtuple(mine) < _vtuple(theirs):
        rows.append(('w', '版本', '副本 %s 落后于宿主 %s' % (mine, theirs),
                     '从 %s 整份覆盖副本（覆盖前确认项目里没有本地改动）' % where))
    elif _vtuple(mine) == _vtuple(theirs):
        rows.append(('v', '版本', '副本与宿主一致：%s' % mine, ''))
    else:
        rows.append(('w', '版本', '副本 %s 比宿主 %s 新' % (mine, theirs),
                     '把副本的改动合回宿主技能，否则以后重建项目会退回旧版'))


def check_hooks(rows):
    if not is_repo():
        rows.append(('d', '钩子', '不是 git 仓库，跳过', '需要自动汇总时再 git init'))
        return
    sk = proj_skill()
    if not sk:
        rows.append(('x', '钩子', '项目里没有技能副本，钩子无从检查',
                     '跑 install-project-anchors.py <项目根> --with-skill'))
        return
    hdir = os.path.join(sk, 'scripts', 'hooks')
    rel = os.path.relpath(hdir, ROOT).replace(os.sep, '/')

    cur = git('config', '--local', '--get', 'core.hooksPath').stdout.strip()
    if not cur:
        rows.append(('x', '钩子', 'core.hooksPath 未设置（合并后不会自动汇总）',
                     '跑 %s/scripts/安装钩子.py' % rel.rsplit('/scripts/', 1)[0]))
    elif cur.replace('\\', '/').rstrip('/') != rel:
        rows.append(('w', '钩子', 'core.hooksPath = %s（期望 %s）' % (cur, rel),
                     '重跑 安装钩子.py'))
    else:
        rows.append(('v', '钩子', 'core.hooksPath = %s' % rel, ''))

    bad = 0
    for h in ('post-merge', 'post-commit', 'post-rewrite', '_summary.sh'):
        p = os.path.join(hdir, h)
        if not os.path.isfile(p):
            rows.append(('x', '钩子', '缺 %s' % h, '技能副本不完整，重新同步副本'))
            bad += 1
            continue
        with open(p, 'rb') as f:
            first = f.readline()
        if b'\r' in first:
            rows.append(('x', '钩子', '%s 首行是 CRLF（shebang 带 \\r，静默不执行）' % h,
                         '补 .gitattributes 后重新 checkout；或转成 LF'))
            bad += 1
        elif h != '_summary.sh' and not first.startswith(b'#!'):
            rows.append(('w', '钩子', '%s 首行不是 shebang' % h, '检查文件是否被改坏'))
            bad += 1
    if not bad:
        rows.append(('v', '钩子', '四个钩子文件齐全且首行为 LF（merge / commit / rebase 三路径都在）', ''))


def check_gitattributes(rows, fix):
    path = os.path.join(ROOT, '.gitattributes')
    hint = '跑本脚本 --fix，或 安装钩子.py（缺它则换机器 clone 后钩子静默失效）'
    txt = read(path)

    # 非 git 仓库里没有 .gitattributes 谈不上「缺」—— 钩子那项已经跳过，这里跟着跳过。
    # 2026-10-27 修：新项目刚跑完 初始化.py、还没 git init 时，这里会挂一个 ✗，
    # 与上一行「钩子 不是 git 仓库，跳过」自相矛盾，看着像初始化失败。
    # 文件已存在就照常检查 —— 有人习惯 git init 前先写好规则，也该被校验。
    if txt is None and not is_repo():
        rows.append(('d', 'gitattributes', '不是 git 仓库，跳过',
                     'git init 后跑一次自检，或 安装钩子.py'))
        return

    if txt is None:
        if not fix:
            rows.append(('x', 'gitattributes', '文件不存在', hint))
            return
        with io.open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(GITATTR_HEAD + '\n' + '\n'.join(GITATTR_LINES) + '\n')
        rows.append(('v', 'gitattributes', '文件不存在 → 已新建（--fix）', ''))
        return

    miss = gitattributes_missing(txt)
    if not miss:
        rows.append(('v', 'gitattributes', 'LF 保护与生成物合并策略齐全', ''))
        return
    if not fix:
        rows.append(('x', 'gitattributes', '缺 %d 行：%s' % (len(miss), '；'.join(miss)),
                     '跑 --fix 自动补（只追加，不动原有内容）'))
        return
    eol = '\r\n' if '\r\n' in txt else '\n'
    prefix = '' if (not txt or txt.endswith(('\n', '\r'))) else eol
    with io.open(path, 'a', encoding='utf-8', newline='') as f:
        f.write(prefix + eol.join(miss) + eol)
    rows.append(('v', 'gitattributes', '缺 %d 行 → 已补（--fix）' % len(miss), ''))


def check_layout(rows):
    doc = os.path.join(ROOT, '开发文档')
    if not os.path.isdir(doc):
        rows.append(('x', '布局', '没有 开发文档/ 目录', '按技能第 E 节建编号目录（00规则 / 01需求 / 02缺陷 / 03技术债 / 04技能）'))
        return
    have = [d for d in LAYOUT if os.path.isdir(os.path.join(doc, d))]
    miss = [d for d in LAYOUT if d not in have]
    if not miss:
        rows.append(('v', '布局', '%d 个编号目录齐全（%s）' % (len(LAYOUT), ' '.join(LAYOUT)), ''))
        return
    for d in miss:
        if d in REQUIRED_DIRS:
            rows.append(('x', '布局', '缺 %s/' % d, '建目录；它装的是流程必需的档案'))
        else:
            rows.append(('d', '布局', '%s/ 未建（跳过阶段可不建）' % d, ''))


RULE_FILE = '开发文档/00规则/团队配置.md'
APPROVAL_MODES = ('全自动', '仅需求审批', '关键三关', '每阶段', '只在交付验收')
TEST_MODES = ('全量', '仅回归', '仅静态')
NO_GATE_MODES = ('全自动', '仅需求审批', '只在交付验收')


# 四份「必读」规则文件：缺了脚本不会报错，但 agent 进来就没有入场地图 / 门禁口径，
# 只能自己发明一套 —— 比「文件内容被写瘦」更早的失效点（2026-10-29：试点2 缺 项目概述.md 没人发现）。
# 第五份 `协作规范.md` 单人可不建（SKILL.md §3 明确允许），但要在 文档结构.md 写明「暂不建 + 为什么」。
REQUIRED_RULES = (
    ('项目概述.md', '没有入场地图：定位 / 技术栈 / 核心链路 / 硬约束全得靠现场猜'),
    ('团队配置.md', '门禁 / 身份判定 / 取号没有依据'),
    ('开发规范.md', '语言版本 / 交付形态 / 测试框架没有约定，代码风格靠猜'),
    ('文档结构.md', '额外目录与「哪些是生成物」没声明，agent 会另造一套目录'),
)
OPTIONAL_RULES = ('协作规范.md',)


def check_rule_files(rows):
    """四份必读规则文件在不在（只看存在性，内容瘦身交给 check_rules）。"""
    doc = os.path.join(ROOT, '开发文档')
    if not os.path.isdir(doc):
        return
    ruledir = os.path.join(doc, '00规则')
    if not os.path.isdir(ruledir):
        return  # 布局检查已经报过，不重复刷屏

    absent = [(n, why) for n, why in REQUIRED_RULES
              if not os.path.isfile(os.path.join(ruledir, n))]
    # 团队配置 缺失由 check_rules 单独报（那条会带上模板来源与后果），这里不重复刷屏。
    report = [(n, why) for n, why in absent if n != '团队配置.md']
    if report:
        rows.append(('w', '规则文件齐全',
                     '缺 %d 份必读规则文件：%s' % (len(report), '、'.join(n for n, _ in report)),
                     '从 references/ 下同名模板整份复制再填空（' +
                     '；'.join('%s ⇒ %s' % (n, why) for n, why in report) +
                     '）。缺得越久，后来的 agent 越会自己发明一套规则，两套并存比不建更乱'))
    elif not absent and not os.path.isfile(os.path.join(ruledir, OPTIONAL_RULES[0])):
        rows.append(('v', '规则文件齐全', '四份必读齐全（%s 未建，单人可省）' % OPTIONAL_RULES[0], ''))
    elif not absent:
        rows.append(('v', '规则文件齐全', '五份规则文件齐全', ''))


def check_rules(rows):
    """团队配置.md 有没有被写成精简版：档位名、五档清单、含义表、测试三档、人编号。"""
    if not os.path.isdir(os.path.join(ROOT, '开发文档')):
        return
    path = os.path.join(ROOT, RULE_FILE)
    if not os.path.isfile(path):
        rows.append(('x', '规则文件', '缺 %s' % RULE_FILE,
                     '从 references/team-profile.template.md 整份复制到 开发文档/00规则/ 再填空；'
                     '没有它，门禁 / 身份判定 / 取号全得靠猜'))
        return
    text = read(path) or ''
    rel = RULE_FILE

    def pick(keyword):
        """取「- **审批模式**：…」这种字段行：优先列表项，退一步找任意非表格行。

        不能直接取第一个含关键字的行 —— 文件开头的引言常写「…（交付形态 / 审批模式 / 测试策略）」，
        取到它就会误报「没有合法档位名」（2026-10-26 试点2 自测踩到）。"""
        cands = [l for l in text.splitlines()
                 if keyword in l and not l.lstrip().startswith('|')]
        for l in cands:
            if l.lstrip().startswith(('-', '*')):
                return l
        return cands[0] if cands else ''

    line = pick('审批模式')
    if not line:
        rows.append(('x', '规则文件', '%s 里没有「审批模式」这一行' % rel,
                     '五档必须显式选一个写下来，不能靠默认'))
        return

    hits = sorted((line.find(m), m) for m in APPROVAL_MODES if m in line)
    mode = hits[0][1] if hits else ''
    lost = [m for m in APPROVAL_MODES if m not in line]
    if not mode:
        rows.append(('x', '规则文件', '审批模式那行没有合法档位名',
                     '只能写这五个之一：' + '、'.join(APPROVAL_MODES)
                     + '（别写「三关」「仅审需求」这类变体，下一个 agent 认不出来）'))
    elif lost:
        rows.append(('x', '规则文件', '审批模式行丢了 %d 档：%s' % (len(lost), '、'.join(lost)),
                     '行尾必须保留「五档可选：全自动｜仅需求审批｜关键三关｜每阶段｜只在交付验收」；'
                     '只写当前档，等于把别人的选项藏了'))
    absent = [m for m in APPROVAL_MODES if m not in text]
    if mode and len(absent) >= 3:
        rows.append(('x', '规则文件', '「审批模式（五选一）」含义表缺失（5 档只出现 %d 个）' % (5 - len(absent)),
                     '整张表是内容不是占位文字：换档时得靠它判断行为，缺了就只能猜'))

    tline = pick('测试策略')
    tlost = [m for m in TEST_MODES if m not in tline]
    if not tline or len(tlost) == len(TEST_MODES):
        rows.append(('x', '规则文件', '测试策略行缺失或没有档位名',
                     '三选一：' + '、'.join(TEST_MODES)))
    elif tlost:
        rows.append(('w', '规则文件', '测试策略行少了可选档：%s' % '、'.join(tlost),
                     '保留「三档可选：全量｜仅回归｜仅静态」，格式与审批模式行一致'))

    if '人编号' not in text:
        rows.append(('w', '规则文件', '角色表没有「人编号」列',
                     '人编号是 CR 号首位；缺了没法两人并行取号'))

    # 仅静态 × 构建命令：钩子读到非空命令就会在合并后执行，等于偷偷跑了构建。
    #
    # 只认「- 构建命令：xxx」这种**字段行**。不能拿 pick() 的结果就判：项目里常有一句
    # 「- **未声明「构建命令」**：本项目构建产物不入库…」，那是说明，不是命令（2026-10-29 误报）。
    if '仅静态' in tline:
        cmd = ''
        for l in text.splitlines():
            if not re.match(r'^\s*-\s*\**构建命令', l):
                continue
            val = re.split(r'[：:]', l, maxsplit=1)[-1]
            val = re.sub(r'^[（(].*', '', val).strip().strip('*` ')
            if val and not val.startswith(('（', '不', '留空', '无', '未')):
                cmd = val
            break
        if cmd:
            rows.append(('w', '规则文件', '测试策略＝仅静态，却声明了构建命令：%s' % cmd[:40],
                         '这个档位不执行任何脚本命令，钩子却会在合并后跑它 —— 要么把这行留空，'
                         '要么把档位升到 全量/仅回归'))

    if mode in NO_GATE_MODES and '不生效' not in text and '无门禁' not in text:
        rows.append(('w', '规则文件', '档位＝%s，但门禁表没标哪些门不生效' % mode,
                     '把 G2/G3 标「本模式不生效」，或整表换成「无门禁」—— 否则读者以为这里真会停'))

    if not any(r[1] == '规则文件' for r in rows):
        rows.append(('v', '规则文件', '%s：档位 %s、五档清单、测试三档、人编号齐全' % (rel, mode), ''))


# 不强制「点 + TLD」：git 里真有人配出 `xpz.qq@.com` 这种残废地址（葫芦岛 2026-11-04），
# 强制 TLD 会让那行登记形同不存在，自检一直喊「没登记」。
EMAIL_RE = re.compile(r'[\w.+-]+@[\w.-]+')


def _team_emails(text):
    """从表格行里抓 (email, 人编号, 姓名)。表格列固定：角色｜姓名｜git email｜人编号｜说明。"""
    out = []
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith('|'):
            continue
        cells = [c.strip() for c in s.strip('|').split('|')]
        for i, c in enumerate(cells):
            m = EMAIL_RE.search(c)
            if not m:
                continue
            num = 0
            if i + 1 < len(cells):
                num = int(re.sub(r'[^0-9]', '', cells[i + 1]) or 0)
            # 姓名去掉括号注释（「姜辉（个人邮箱）」和「姜辉」是同一个人，别当成重名冲突）
            name = re.sub(r'[（(].*', '', cells[1] if len(cells) > 1 else '').strip()
            out.append((m.group(0).lower(), num, name))
            break
    return out


def check_team_git(rows):
    """团队配置.md 登记的人 vs git 里的实际提交者（2026-11-04 加）。

    两件事：
    1. **人编号不能 ≥10** —— CR 号是 `人编号(1位)+年(1位)+月日(4位)+序号(2位)` 共 8 位，
       编号 10 以上根本拼不出合法号。`初始化.py --refresh-team` 会无脑顺延（发射场实测排到 22），
       所以必须自检兜住。
    2. **git 里出现、表里没登记** —— 取号靠 email 查表，查不到就会卡住或乱猜，久了审计签署人对不上人。

    只查「git 有、表没有」这一个方向：反方向（表里有、git 没提交）是正常的，新人刚登记还没提交。
    同一个人多个邮箱是**合法**的（表里就该多行同编号），所以按 email 比对，不按姓名。
    """
    text = read(os.path.join(ROOT, RULE_FILE))
    if not text:
        return                      # 缺文件由 check_rules 报，不重复刷屏
    pairs = _team_emails(text)
    if not pairs:
        rows.append(('w', '团队配置', '读不出角色表的 email 列',
                     '表头保留「角色｜姓名｜git email｜人编号｜说明」五列 —— 取号靠它查表'))
        return
    registered = {e for e, _n, _m in pairs}

    over = sorted({n for _e, n, _m in pairs if n > 9})
    if over:
        rows.append(('x', '团队配置', '人编号超出 1~9：%s' % '、'.join(map(str, over)),
                     'CR 号只有 8 位、人编号占 1 位，≥10 拼不出合法号。'
                     '历史贡献者的人编号写 `-`（不取号），不要顺着往下排'))

    # 同一编号挂了不同姓名：要么把两个人错并成一个号（取号会撞），要么真同名 —— 都要人看一眼
    by_num = {}
    for _e, n, name in pairs:
        if n:
            by_num.setdefault(n, set()).add(name)
    clash = sorted((n, sorted(v)) for n, v in by_num.items() if len(v) > 1)
    if clash:
        rows.append(('w', '团队配置', '同一人编号对应多个姓名：%s'
                     % '；'.join('%d=%s' % (n, '/'.join(v)) for n, v in clash),
                     '错并成一个号会让两人撞号段；真同名就把姓名写全（如「张伟（前端）」）区分'))

    # 同一个 email 挂到了两个不同的人编号：取号查到哪个算哪个，CR 号会随机串
    # （同一 email 多行本身是合法的：一人多角色、或 PO/DEV/REV 各一行）
    seen, bad = {}, []
    for e, n, _m in pairs:
        seen.setdefault(e, set()).add(n)
        if len(seen[e]) > 1:
            bad.append(e)
    if bad:
        rows.append(('w', '团队配置', '%d 个邮箱对应多个不同编号：%s'
                     % (len(set(bad)), '、'.join(sorted(set(bad))[:3])),
                     '同一个人所有行必须填同一个人编号；编号不同 ⇒ 取号时按哪行全凭运气'))

    if not is_repo():
        rows.append(('d', '团队配置', '不是 git 仓库，跳过提交者比对', ''))
        return
    r = git('log', '--all', '--format=%ae')
    if r.returncode != 0:
        rows.append(('d', '团队配置', 'git log 读不到，跳过提交者比对', ''))
        return
    cnt = {}
    for e in (r.stdout or '').splitlines():
        e = e.strip().lower()
        if e:
            cnt[e] = cnt.get(e, 0) + 1
    if not cnt:
        rows.append(('d', '团队配置', 'git 里还没有提交，无从比对', ''))
        return

    missing = sorted(((c, e) for e, c in cnt.items() if e not in registered), reverse=True)
    if missing:
        head = '、'.join('%s(%d)' % (e, c) for c, e in missing[:5])
        more = ' 等 %d 个' % len(missing) if len(missing) > 5 else ''
        rows.append(('w', '团队配置', 'git 里 %d 个提交者没登记：%s%s' % (len(missing), head, more),
                     '补进 `00规则/团队配置.md`：要走流程的放角色表、给 1~9 的空号；'
                     '历史作者放「历史贡献者」表、人编号写 `-`；agent 提交身份放「AI 代理」表'))
        return
    rows.append(('v', '团队配置', '%d 个 git 提交者全部已登记（表里 %d 个邮箱）' % (len(cnt), len(registered)), ''))


COMMIT_RE = re.compile(r'^(?:feat|fix|refactor|docs|perf|chore|revert)\((?:CR-\d{8}|repo|aidlc)\): \S')


def check_commit_style(rows):
    """提交信息有没有按 `<type>(CR-<8位号>): <中文摘要>` 写（2026-11-04 加）。

    为什么自检要管提交：规范写在 `references/git-提交.md` 里，但**没人读就不会执行**。
    发射场实测：写进 `00规则/开发规范.md` 之后，近 200 条提交里带 CR 号的 **0 条** ——
    全靠自觉的规则等于没有。只查最近 12 条：噪声小，纠偏快，历史提交不追究。
    """
    if not is_repo():
        rows.append(('d', '提交规范', '不是 git 仓库，跳过', ''))
        return
    r = git('log', '-12', '--no-merges', '--format=%s')
    if r.returncode != 0:
        rows.append(('d', '提交规范', 'git log 读不到，跳过', ''))
        return
    subs = [s.strip() for s in (r.stdout or '').splitlines() if s.strip()]
    if not subs:
        rows.append(('d', '提交规范', '还没有提交', ''))
        return
    bad = [s for s in subs if not COMMIT_RE.match(s)]
    if not bad:
        rows.append(('v', '提交规范', '最近 %d 条提交都带 CR 号' % len(subs), ''))
        return
    rows.append(('w', '提交规范', '最近 %d 条里有 %d 条没按 `<type>(CR-<8位号>): 摘要` 写（如「%s」）'
                 % (len(subs), len(bad), bad[0][:36]),
                 '历史提交不用改；**新提交**带 8 位 CR 号，仓库杂务用 `(repo)` '
                 '—— 细则见 `references/git-提交.md`'))
