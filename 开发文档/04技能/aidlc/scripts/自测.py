#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AIDLC 技能自测（selftest）—— 改完脚本，先证明「初始化 → 建 CR → 汇总 → 自检」没断。

为什么要它：这个技能的规则几乎全是**真实项目试错**换来的（事故一条条写进 SKILL.md）。
代价是每次改脚本都在拿四个真实项目当验证环境 —— 改坏了要等项目那边报错才知道。
本脚本在临时目录跑一遍最小闭环，把「脚本改坏了」和「项目数据有问题」分开。

用法
    python 开发文档/04技能/aidlc/scripts/自测.py        # 跑全部
    python 开发文档/04技能/aidlc/scripts/自测.py -v     # 同时打印每个子命令的输出

退出码：0 全过｜1 有失败
"""

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
VERBOSE = '-v' in sys.argv

TYPES = ('00规则', '01需求', '02缺陷', '03技术债', '04技能', '_汇总')
RULES = ('项目概述.md', '团队配置.md', '开发规范.md', '文档结构.md', '协作规范.md')
CR = 'CR-16102999-自测'

STATE = """# 00-状态

- 编号：CR-16102999
- 名称：自测
- 负责人：1
- 创建：2026-10-29 09:00:00
- 更新：2026-10-29 09:30:00
- 阶段：requirements-analysis
- 门禁：G1 需求 not-started
- 下一步：等 G1 批准
- 单元：-
- 遗留：-

## 门禁明细
| 门禁 | 状态 | 批准人 | 时间 |
|---|---|---|---|
| G1 需求定稿 | not-started | - | - |

## 执行记录
- [x] workspace-detection
- [x] requirements-analysis
"""

fails = []


def say(ok, name, detail=''):
    mark = 'PASS' if ok else 'FAIL'
    print('  [%s] %s%s' % (mark, name, ('  —— ' + detail) if (detail and not ok) else ''))
    if not ok:
        fails.append(name)


def run(script, *args, **kw):
    cwd = kw.get('cwd')
    cmd = [sys.executable, os.path.join(HERE, script)] + [a for a in args if a]
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                       encoding='utf-8', errors='replace')
    out = (p.stdout or '') + (p.stderr or '')
    if VERBOSE:
        print('    $ %s %s' % (script, ' '.join(args)))
        for line in out.strip().splitlines()[:40]:
            print('      ' + line)
    return p, out


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    io.open(path, 'w', encoding='utf-8', newline='').write(text)


def case_init(root):
    """用例 1：初始化建出该有的目录、五份规则、状态快照。"""
    p, out = run('初始化.py', root, '--entry', 'none', '--no-hooks', '--no-skill')
    say(p.returncode == 0, '初始化退出码 0', out[-200:])
    doc = os.path.join(root, '开发文档')
    missing = [d for d in TYPES if not os.path.isdir(os.path.join(doc, d))]
    say(not missing, '六个目录齐全', '缺：' + '、'.join(missing))
    absent = [r for r in RULES if not os.path.isfile(os.path.join(doc, '00规则', r))]
    say(not absent, '五份规则文件齐全', '缺：' + '、'.join(absent))
    say(os.path.isfile(os.path.join(doc, '状态.md')), '项目级状态快照已建')
    say(not os.path.isdir(os.path.join(doc, '04技能', 'aidlc')),
        '--no-skill 时不复制技能副本')
    return doc


def case_empty_summary(root):
    """用例 2：没有任何 CR 时，汇总给明确提示而不是静默生成空表。"""
    p, out = run('汇总.py', cwd=root)
    say(p.returncode == 2, '空项目汇总退出码 2', '实际 %s' % p.returncode)
    say('没有可汇总的 CR' in out, '空项目汇总给出提示', out[-200:])


def case_cr(doc):
    """用例 3：按新版 00-状态.md 模板建一条 CR。"""
    cdir = os.path.join(doc, '01需求', CR)
    write(os.path.join(cdir, '00-状态.md'), STATE)
    write(os.path.join(cdir, '01-需求.md'),
          '# 需求\n\n- 需求性质：增量\n- 变更请求：CR-16102999\n- 摘要：自测用\n- 号段：FR-01\n')
    say(os.path.isfile(os.path.join(cdir, '00-状态.md')), '建 CR 成功（00-状态.md）')
    return cdir


def case_summary(doc, root):
    """用例 4：汇总必须真正解析出字段 —— 字段名写错时这里会变成 —，能立刻发现。"""
    p, out = run('汇总.py', cwd=root)
    say(p.returncode == 0, '汇总退出码 0', out[-200:])
    view = os.path.join(doc, '_汇总', '状态.md')
    if not os.path.isfile(view):
        say(False, '生成 状态.md 视图', '文件不存在')
        return
    text = io.open(view, encoding='utf-8').read()
    say('CR-16102999' in text, '视图里有 CR 号')
    say('requirements-analysis' in text, '视图解析出「阶段」', '字段名可能被改了')
    say('等 G1 批准' in text, '视图解析出「下一步」', '字段名可能被改了')
    row = [l for l in text.splitlines() if '| **CR-16102999**' in l]
    say(bool(row) and '—' not in row[0], '状态行没有空值占位 —', row[0] if row else '找不到该 CR 行')
    views = [f for f in os.listdir(os.path.join(doc, '_汇总')) if f.endswith('.md')]
    say(len(views) >= 9, '视图数量 ≥ 9', '实际 %d' % len(views))


def case_preview(doc, root):
    """用例 5：建站要落在**当前项目**，不是脚本所在项目（两者同款定位 bug 的回归用例）。"""
    p, out = run('预览.py', '--no-serve', cwd=root)
    say(p.returncode == 0, '预览 --no-serve 退出码 0', out[-200:])
    say(os.path.isfile(os.path.join(doc, '_汇总', 'index.html')),
        '站点生成在当前项目', '可能写到了脚本所在的项目（定位又按脚本路径反推了）')
    say(os.path.isdir(os.path.join(doc, '_汇总', 'docs')), '站点快照 docs/ 已建')


def case_doctor(root):
    """用例 6：自检能跑通，并识别出「五份规则齐全」。"""
    p, out = run('自检.py', cwd=root)
    say(p.returncode in (0, 1, 2), '自检能执行', '退出码 %s' % p.returncode)
    say('规则文件齐全' in out, '自检含「规则文件齐全」项')
    say('五份规则文件齐全' in out, '自检认出五份齐全', out[-400:])
    say('版本' in out, '自检含「版本」项')
    say('Traceback' not in out, '自检无异常堆栈', out[-300:])


def case_migrate(root):
    """用例 7：迁移-编号 预演不炸、不改文件（默认只读）。"""
    p, out = run('迁移-编号.py', root)
    say(p.returncode == 0, '迁移-编号 预演退出码 0', out[-200:])
    say('Traceback' not in out, '迁移-编号 无异常堆栈', out[-300:])


def case_version_field():
    """用例 8：技能自身 SKILL.md 必须有 version（副本靠它判断新旧）。"""
    skill_md = os.path.join(SKILL, 'SKILL.md')
    text = io.open(skill_md, encoding='utf-8').read(4000)
    head = text.split('---')[1] if text.startswith('---') and text.count('---') >= 2 else ''
    say(bool([l for l in head.splitlines() if l.strip().startswith('version:')]),
        'SKILL.md 有 version 字段')


def case_size():
    """用例 9：每个文件 ≤ 25 KB（第三方压缩库除外）—— 2026-10-29 定，防止再次膨胀。"""
    over = []
    for r, ds, fs in os.walk(SKILL):
        if '__pycache__' in r:
            continue
        for f in fs:
            if f == 'docsify.min.js':      # 第三方压缩库，拆开就跑不了
                continue
            p = os.path.join(r, f)
            if os.path.getsize(p) > 25 * 1024:
                over.append('%s(%.0fKB)' % (os.path.relpath(p, SKILL), os.path.getsize(p) / 1024))
    say(not over, '所有文件 ≤ 25KB', '超限：' + '、'.join(over))


def case_board(doc, root):
    """用例 10：看板必须是可用的单文件页面（数据内嵌、有跳转、无残留占位符）。"""
    p = os.path.join(doc, '_汇总', '看板.html')
    say(os.path.isfile(p), '生成 看板.html')
    if not os.path.isfile(p):
        return
    s = io.open(p, encoding='utf-8').read()
    say('%(title)s' not in s and '%(data)s' not in s, '看板无未替换占位符')
    m = re.search(r'var DATA = (\[.*?\]);\n', s, re.S)
    say(bool(m), '看板内嵌 DATA')
    if not m:
        return
    data = json.loads(m.group(1).replace('<\\/', '</'))
    say(len(data) == 1, '看板数据条数与 CR 数一致', '实际 %d 条' % len(data))
    say(all(str(d.get('href', '')).startswith('docs/') for d in data), '看板行都有跳转地址')
    say(all(k in data[0] for k in ('owner', 'kind', 'stage', 'created', 'updated', 'audit')),
        '看板行含筛选所需字段')


def main():
    print('AIDLC 自测  %s' % SKILL)
    print('-' * 60)
    root = tempfile.mkdtemp(prefix='aidlc-selftest-')
    try:
        print('用例 1-2：空项目')
        doc = case_init(root)
        case_empty_summary(root)
        print('用例 3-7：建 CR 后的闭环')
        case_cr(doc)
        case_summary(doc, root)
        case_preview(doc, root)
        case_doctor(root)
        case_board(doc, root)
        case_migrate(root)
        print('用例 8-9：技能自身')
        case_version_field()
        case_size()
    finally:
        shutil.rmtree(root, ignore_errors=True)

    print('-' * 60)
    if fails:
        print('失败 %d 项：%s' % (len(fails), '、'.join(fails)))
        return 1
    print('全部通过')
    return 0


if __name__ == '__main__':
    sys.exit(main())
