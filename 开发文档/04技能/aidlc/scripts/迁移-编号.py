#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给老项目的 CR 目录补上文件编号（2026-10-27 引入的命名规范）。

背景：CR 内的文档从「裸中文名」改为「两位数字前缀 + 中文名」：
    需求.md        → 01-需求.md
    设计/          → 08-设计/，内部 应用设计.md → 08-1-应用设计.md
    审计-张勇.md    → 40-审计-张勇.md

新项目不用跑（初始化就是新命名）。**老项目不跑也能继续用** ——
`汇总.py` / `自检.py` / `预览.py` 的查找统一走 `find_cr_file()`，
`NN-名字.md` 与裸 `名字.md` 两种都认。这个脚本只是「想统一视觉」时用。

用法
    python 迁移-编号.py <项目根>              # 只看会改什么（默认不动）
    python 迁移-编号.py <项目根> --write      # 真改
    python 迁移-编号.py <项目根> --write --only CR-16102704

安全（按重要性排）
    · 默认 dry-run，必须显式 --write 才落盘；
    · **幂等**：已带编号的文件跳过，重复跑不会加两层前缀；
    · **整条 CR 要么全改、要么不改**：任一目标名已存在 ⇒ 该条 CR 整条跳过并报错；
    · 不碰 `证据/`（里面的文件名被文档引用，改了引用就断）、不碰 `_汇总/`（生成物）；
    · 在 git 仓库里，重命名会显示为 rename，`git status` 能看全，可整体回滚。
"""

import argparse
import io
import os
import sys

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _aidlc_common import (AUDIT_LEGACY_PREFIX, AUDIT_PREFIX, CR_FILES,  # noqa: E402
                           DESIGN_DIR, DESIGN_DIR_LEGACY, DESIGN_FILES)

TYPES = ('01需求', '02缺陷', '03技术债')
SKIP_DIRS = ('证据', '_汇总', '__pycache__')


def plan_cr(cr_dir):
    """算出这条 CR 要做的重命名：[(src, dst), …]。已是最新命名的返回 []。"""
    ops = []
    for f in sorted(os.listdir(cr_dir)):
        src = os.path.join(cr_dir, f)
        if os.path.isdir(src):
            continue
        if not f.endswith('.md'):
            continue
        # 审计：一人一份，前缀单独处理（`审计-张勇.md` → `40-审计-张勇.md`）
        if f.startswith(AUDIT_LEGACY_PREFIX) and not f.startswith(AUDIT_PREFIX):
            ops.append((src, os.path.join(cr_dir, AUDIT_PREFIX + f[len(AUDIT_LEGACY_PREFIX):])))
            continue
        if f[:1].isdigit():                       # 已经带号了
            continue
        new = CR_FILES.get(f[:-3])
        if new:
            ops.append((src, os.path.join(cr_dir, new)))

    # 设计目录：`设计/` → `08-设计/`，内部标准 5 份带号
    #
    # 顺序很关键：**先在旧目录里把文件改名，最后才改目录名**。
    # 反过来的话，目录一改，`设计/业务规则.md` 这个源路径当场不存在，
    # 后面的 rename 直接 OSError（2026-10-27 预演时踩到）。
    dir_ops = []
    for dname in (DESIGN_DIR_LEGACY, DESIGN_DIR):
        dsrc = os.path.join(cr_dir, dname)
        if not os.path.isdir(dsrc):
            continue
        dstd = os.path.join(cr_dir, DESIGN_DIR)
        for f in sorted(os.listdir(dsrc)):
            p = os.path.join(dsrc, f)
            if not os.path.isfile(p) or not f.endswith('.md') or f[:1].isdigit():
                continue
            new = DESIGN_FILES.get(f[:-3])
            if new:
                ops.append((p, os.path.join(dsrc, new)))   # 仍落在旧目录里
        if dsrc != dstd:
            dir_ops.append((dsrc, dstd))
        break                      # 只处理一个设计目录（新名优先已由循环顺序保证）
    ops += dir_ops                 # 目录改名放最后
    return ops


def apply_ops(ops, write):
    """执行（或预演）一组重命名。返回 (成功数, 冲突数)。"""
    # 先查冲突：目标已存在就不动，整条 CR 放弃
    clash = [d for _s, d in ops if os.path.exists(d) and
             os.path.normcase(d) not in [os.path.normcase(s) for s, _ in ops]]
    if clash:
        return 0, len(clash)

    done = 0
    for s, d in ops:
        if write:
            parent = os.path.dirname(d)
            if parent and not os.path.isdir(parent):
                os.makedirs(parent, exist_ok=True)
            os.rename(s, d)
        done += 1    # 预演只数数，**绝不落盘**（含建目录）
    return done, 0


def main():
    ap = argparse.ArgumentParser(description='给 CR 目录补文件编号（默认只看不改）')
    ap.add_argument('root', nargs='?', default='.', help='项目根（含 开发文档/ 的目录）')
    ap.add_argument('--write', action='store_true', help='真改（默认只预演）')
    ap.add_argument('--dry-run', action='store_true', help='显式预演（与默认一致）')
    ap.add_argument('--only', default=None, help='只处理某一条 CR，如 CR-16102704')
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    doc = os.path.join(root, '开发文档')
    if not os.path.isdir(doc):
        print('[错误] 找不到 %s' % doc)
        return 2

    write = args.write and not args.dry_run
    total_done = total_clash = total_cr = untouched = 0

    for kind in TYPES:
        kdir = os.path.join(doc, kind)
        if not os.path.isdir(kdir):
            continue
        for d in sorted(os.listdir(kdir)):
            cr = os.path.join(kdir, d)
            if not (d.startswith('CR') and os.path.isdir(cr)):
                continue
            if args.only and not d.startswith(args.only):
                continue
            ops = plan_cr(cr)
            if not ops:
                untouched += 1
                continue
            done, clash = apply_ops(ops, write)
            if clash:
                print('✗ %s：目标名已存在 %d 个，整条跳过（不做半套）' % (d, clash))
                total_clash += clash
                continue
            total_cr += 1
            total_done += done
            print('%s %s（%d 个文件）' % ('已改' if write else '将改', d, done))
            for s, dst in ops:
                print('    %s → %s' % (os.path.basename(s), os.path.relpath(dst, cr)))

    print('')
    print('-' * 60)
    print('%s：%d 条 CR / %d 个文件；%d 条已是新命名，跳过；%d 个冲突'
          % ('已执行' if write else '预演', total_cr, total_done, untouched, total_clash))
    if not write and total_done:
        print('')
        print('确认无误后加 --write 执行。执行前建议先 commit（git 会把改名记成 rename，可整体回滚）。')
    if write and total_done:
        print('')
        print('下一步：git status 看一眼 → 跑 汇总.py --site 重建视图 → 跑 自检.py 确认无 ✗')
    return 0


if __name__ == '__main__':
    sys.exit(main())
