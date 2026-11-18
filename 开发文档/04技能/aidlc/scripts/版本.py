#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AIDLC 技能版本 —— 「别的地方用的是不是新版？」

`SKILL.md` 里的 `version` 是给人看的，**不能当判据**：2026-11-04 实测五个项目副本
内容各不相同，却全都标 `2.6.0`。真正的判据是内容指纹（见 `_fingerprint.py`），
本脚本把它落到 `VERSION` 文件里，并提供跨副本比对。

VERSION 文件（技能根目录，四行，无时间戳、无项目名，各副本可逐字节 diff）
    skill: aidlc
    version: 2.6.2
    fingerprint: 0a1b2c3d4e5f6071
    files: 90

用法
    python 开发文档/04技能/aidlc/scripts/版本.py
        看本副本：版本、指纹、VERSION 是否与内容对得上

    python 开发文档/04技能/aidlc/scripts/版本.py --write
        重算并写 VERSION —— **改完技能文件必须跑**，忘了跑 VERSION 就会说谎

    python 开发文档/04技能/aidlc/scripts/版本.py --verify
        只校验不写（CI/钩子用）；不一致退出码 1

    python 开发文档/04技能/aidlc/scripts/版本.py --check <目录> [<目录> ...]
        与指定副本比；`--diff` 再列出到底哪些文件不同

    python 开发文档/04技能/aidlc/scripts/版本.py --scan <根目录> [<根目录> ...]
        自动搜出这些根下所有技能副本，按指纹分组 —— 一眼看出谁旧了、谁改了没回收
        `--base <目录>` 指定基准（默认取副本最多的那组为「主流」）

退出码：0 一致 / 全扫完无异常｜1 有差异或 VERSION 过期｜2 用法错误
"""

import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)          # 脚本所在技能目录（本副本）
sys.path.insert(0, HERE)

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

import _fingerprint as fp  # noqa: E402

# --scan 不进的目录：都不是技能内容，进去只是浪费时间
SKIP_DIRS = {'.git', 'node_modules', 'dist', '__pycache__', '_汇总', 'build',
             'target', '.venv', 'venv', '.idea', '.next', '.nuxt'}
MAX_DEPTH = 8


def _label(skill_dir):
    """给副本一个短名字：`<项目>/开发文档/04技能/aidlc` 取项目名，其余取末三段。"""
    d = os.path.abspath(skill_dir)
    parts = d.replace('\\', '/').rstrip('/').split('/')
    if len(parts) >= 4 and parts[-3:] == ['开发文档', '04技能', 'aidlc']:
        return parts[-4]
    return '/'.join(parts[-3:])


def _rel(c, roots):
    """相对某个扫描根的路径，用来区分同名项目。"""
    for r in roots:
        try:
            rel = os.path.relpath(c, r)
        except ValueError:
            continue
        if not rel.startswith('..'):
            return rel.replace(os.sep, '/')
    return c


def _is_backup(path):
    """备份目录里也躺着 aidlc 副本（`skills_backup_20261029/` 之类）。

    它们**不是在用副本**，算进「谁旧了」只会让报告一片红 —— 单独列出、不计入统计。
    """
    low = path.replace('\\', '/').lower()
    return any(k in low for k in ('backup', '备份', '-bak', '_bak/', '/bak/'))


def find_copies(root):
    """在 root 下找所有技能副本（含 SKILL.md 的 aidlc 目录），找到即剪枝。"""
    hits = []
    root = os.path.abspath(root)
    for cur, dirs, files in os.walk(root):
        rel = os.path.relpath(cur, root)
        depth = 0 if rel == '.' else rel.count(os.sep) + 1
        if depth >= MAX_DEPTH:
            dirs[:] = []
            continue
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        if os.path.basename(cur) == 'aidlc' and 'SKILL.md' in files:
            hits.append(cur)
            dirs[:] = []
    return hits


def cmd_show(skill_dir):
    v = fp.read_version_file(skill_dir)
    cur = fp.skill_version(skill_dir)
    f, n = fp.fingerprint(skill_dir)
    st, msg = fp.verify(skill_dir)
    print('技能目录 : %s' % skill_dir)
    print('SKILL.md : version %s' % (cur or '（没有 version 字段）'))
    print('实算指纹 : %s（%d 个文件）' % (f, n))
    if v:
        print('VERSION  : version %s · 指纹 %s · %s 个文件'
              % (v.get('version'), v.get('fingerprint'), v.get('files')))
    print('状态     : %s' % ('✓ ' + msg if st == 'ok' else '✗ ' + msg))
    if st == 'missing':
        print('          跑一次 `版本.py --write` 生成')
    elif st == 'stale':
        print('          改了技能却没更新 VERSION —— 这个副本的版本号已经不可信，跑 `--write`')
    return 0 if st == 'ok' else 1


def cmd_write(skill_dir):
    v = fp.write_version_file(skill_dir)
    print('✓ 已写入 %s' % os.path.join(skill_dir, fp.VERSION_FILE))
    print('  version %s · 指纹 %s · %s 个文件'
          % (v.get('version'), v.get('fingerprint'), v.get('files')))
    print('  提醒：改了内容就要同步升 SKILL.md 的 version 与 updated，别让版本号停在原地')
    return 0


def cmd_check(base, others, show_diff):
    rc = 0
    print('基准 : %s（%s）' % (base, fp.skill_version(base) or '?'))
    for o in others:
        if not os.path.isdir(o):
            print('  ✗ %s —— 目录不存在' % o)
            rc = 1
            continue
        st, msg = fp.compare(base, o)
        mark = '✓' if st == 'same' else '✗'
        print('  %s %s\n      %s' % (mark, o, msg))
        if st != 'same':
            rc = 1
            if show_diff:
                changed, only_a, only_b = fp.diff_files(base, o)
                for k in changed:
                    print('        改动 %s' % k)
                for k in only_a:
                    print('        仅基准有 %s' % k)
                for k in only_b:
                    print('        仅该副本有 %s' % k)
    return rc


def cmd_scan(roots, base_dir):
    copies = []
    for r in roots:
        if not os.path.isdir(r):
            print('跳过（不存在）：%s' % r)
            continue
        copies.extend(find_copies(r))
    copies = sorted(set(os.path.abspath(c) for c in copies))
    if not copies:
        print('这些根目录下没找到任何技能副本（找的是含 SKILL.md 的 aidlc 目录）')
        return 1

    # 备份目录里的副本不是「在用的」，单列，不参与主流判定
    backs = [c for c in copies if _is_backup(c)]
    live = [c for c in copies if not _is_backup(c)]
    if not live:
        print('只找到备份副本（%d 份），没有在用的副本' % len(backs))
        return 1

    groups = {}
    for c in live:
        f, n = fp.fingerprint(c)
        groups.setdefault(f, []).append(c)

    # 主流 = 副本最多的那一组；并列时取 version 最高
    def key(item):
        f, cs = item
        ver = fp.skill_version(cs[0]) or '0'
        t = tuple(int(x) for x in re.findall(r'\d+', ver)) or (0,)
        return (len(cs), t)
    main_fp, main_copies = max(groups.items(), key=key)

    base = base_dir or main_copies[0]
    print('扫描 %d 个根：%d 个在用副本%s，%d 种内容\n' % (
        len([r for r in roots if os.path.isdir(r)]), len(live),
        ('（另有 %d 份备份未计入）' % len(backs)) if backs else '', len(groups)))

    order = sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    labels = {c: _label(c) for c in copies}
    dup = {n for n in labels.values() if list(labels.values()).count(n) > 1}
    for i, (f, cs) in enumerate(order, 1):
        ver = fp.skill_version(cs[0]) or '?'
        n = len(fp.iter_files(cs[0]))
        tag = '  ← 主流' if f == main_fp else ''
        print('[%d] 指纹 %s · version %s · %d 文件 · %d 份%s' % (i, f, ver, n, len(cs), tag))
        for c in cs:
            name = labels[c]
            if name in dup:                     # 同名项目（不同根）补相对路径
                name = '%s  (%s)' % (name, _rel(c, roots))
            if f == main_fp:
                print('      %s' % name)
            else:
                st, msg = fp.compare(base, c)
                hint = msg.split('；')[-1] if st != 'same' else ''
                print('      %s  ✗ 与主流不同（%s）' % (name, hint or msg))
        print()

    if backs:
        bset = {}
        for c in backs:
            f, _n = fp.fingerprint(c)
            bset.setdefault((f, fp.skill_version(c) or '?'), []).append(c)
        for (f, ver), cs in sorted(bset.items(), key=lambda kv: -len(kv[1])):
            print('备份 · 指纹 %s · version %s · %d 份（不计入副本统计）' % (f, ver, len(cs)))
            for c in cs[:3]:
                print('      %s' % _rel(c, roots))
            if len(cs) > 3:
                print('      …另有 %d 份' % (len(cs) - 3))
        print()

    if len(groups) == 1:
        print('✓ 全部 %d 份在用副本内容一致' % len(live))
        return 0
    print('✗ %d 种内容并存 —— 上面标 ✗ 的与本表主流不同，'
          '先用 `--check --diff <目录>` 看差在哪，再决定「同步过去」还是「回收进基准」' % len(groups))
    return 1


def main():
    ap = argparse.ArgumentParser(
        description='AIDLC 技能版本与内容指纹（判据是内容，不是版本号）',
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument('--dir', default=SKILL, help='技能目录（默认：本脚本所在技能）')
    ap.add_argument('--write', action='store_true', help='重算并写 VERSION')
    ap.add_argument('--verify', action='store_true', help='校验 VERSION 与内容是否一致')
    ap.add_argument('--check', nargs='+', metavar='DIR', help='与这些副本比对')
    ap.add_argument('--scan', nargs='+', metavar='ROOT', help='搜这些根下的所有副本')
    ap.add_argument('--base', help='--scan 时的基准副本目录')
    ap.add_argument('--diff', action='store_true', help='--check 时列出差异文件')
    a = ap.parse_args()

    if not os.path.isfile(os.path.join(a.dir, 'SKILL.md')):
        print('不是技能目录（没有 SKILL.md）：%s' % a.dir)
        return 2
    if a.write:
        return cmd_write(a.dir)
    if a.verify:
        st, msg = fp.verify(a.dir)
        print('%s %s' % ('✓' if st == 'ok' else '✗', msg))
        return 0 if st == 'ok' else 1
    if a.check:
        return cmd_check(a.dir, a.check, a.diff)
    if a.scan:
        return cmd_scan(a.scan, a.base)
    return cmd_show(a.dir)


if __name__ == '__main__':
    sys.exit(main())
