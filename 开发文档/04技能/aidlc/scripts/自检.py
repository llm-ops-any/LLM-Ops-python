#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AIDLC 项目自检（doctor）—— 「技能说的话，项目做到了没有？」

为什么要它：技能的规则写在 SKILL.md 里，但**规则不会自己执行**。2026-10-21 一天里踩到两个
同类问题（技能副本落到项目根 `skills/`、装钩子不写 `.gitattributes`），共同点是「本机能跑、
换台机器就静默失效，而且没有任何报错」。这类问题只能靠**主动体检**发现，靠人记住是不行的。

检查 18 类（✓ 通过 / · 不适用或未建 / ⚠ 建议处理 / ✗ 有问题）：

  1. 锚点          AGENTS.md 等有没有 AIDLC 标记段 —— 没有 ⇒ 技能根本不会被触发
  2. 技能副本      在 `开发文档/04技能/aidlc`（固定落点）；项目根有没有多余的 `skills/`
  3. 版本          副本 SKILL.md 的 version；有宿主技能时比新旧（副本是复制品，没人通知它过期）
  4. 钩子          `core.hooksPath` 指向对不对；三个钩子在不在；首行是不是 LF
  5. .gitattributes LF 保护三行齐不齐 —— 缺了换机器 clone 后钩子静默失效
  6. 布局          五个编号目录齐不齐
  7. 规则文件齐全  四份必读（项目概述/团队配置/开发规范/文档结构）在不在 —— 缺了 agent 没有入场地图
  8. 规则文件瘦身  团队配置.md 是不是「整份复制 + 填空」：档位名、五档清单、含义表、测试三档
  9. 生成物        `_汇总/` 下 9 个视图在不在；`index.html` 有没有；`汇总.py --check` 是不是最新
 10. 编号          CR 号有没有重复（并行时撞号的直接证据）
 11. 基线          `需求性质：基线` 有且仅有一条 —— 否则全貌视图分不清基线和增量
 12. 执行计划      已开工却没有 `06-执行计划.md` ⇒ 判错（老命名 CR 只建议）
 13. 前置资源      必需资源「待提供」却已开工 ⇒ 判错
 14. 风险          高影响风险仍「待处理」而 CR 在做 ⇒ 建议确认
 15. 死规则        脚本解析的字段若全项目 0 使用 ⇒ 解析永远空转，报警
 16. 孤儿 CR       CR 目录缺 00-状态.md/01-需求.md/02-问题.md ⇒ 汇总会**静默跳过**它
 17. 页面          `_汇总/index.html` 在不在（md 有了但没页面 = 汇总只做了一半）
 18. CR 时间       `状态.md` 的 `创建` / `更新` 齐不齐、是不是 `YYYY-MM-DD HH:MM:SS`

  文件名一律走 `_aidlc_common.find_cr_file()`：带编号（`01-需求.md`）与老裸名（`需求.md`）
  两种都认，所以老项目不迁移也能照常体检。

用法
    python 开发文档/04技能/aidlc/scripts/自检.py          # 体检
    python 开发文档/04技能/aidlc/scripts/自检.py --fix     # 只修能安全自动修的（补 .gitattributes）
    python 开发文档/04技能/aidlc/scripts/自检.py --quiet   # 只报问题（✓ 不打印）
    python 开发文档/04技能/aidlc/scripts/自检.py --status  # 同体检，退出码用于钩子/CI

退出码：0 全绿｜1 有 ✗（真问题）｜2 只有 ⚠（能用，但建议处理）
"""

import glob
import io
import os
import re
import subprocess
import sys
import time

from _check_common import *  # noqa: F401,F403,E402
from _check_meta import (check_anchors, check_skill_copy, check_version,  # noqa: E402
                          check_hooks, check_gitattributes, check_layout,
                          check_rule_files, check_rules)
from _check_cr import (check_generated, check_baseline, check_numbers,  # noqa: E402
                        check_plan, check_resources, check_risks,
                        check_dead_rules, check_cr_times, check_orphan_cr)
GLYPH = {'v': '✓', 'w': '!', 'x': '✗', 'd': '·'}

def main():
    argv = sys.argv[1:]
    fix = '--fix' in argv
    quiet = '--quiet' in argv

    rows = []
    check_anchors(rows)
    check_skill_copy(rows)
    check_version(rows)
    check_hooks(rows)
    check_gitattributes(rows, fix)
    check_layout(rows)
    check_rule_files(rows)
    check_rules(rows)
    check_generated(rows)
    check_numbers(rows)
    check_baseline(rows)
    check_plan(rows)
    check_resources(rows)
    check_risks(rows)
    check_dead_rules(rows)
    check_cr_times(rows, fix)
    check_orphan_cr(rows)

    print('AIDLC 自检  %s' % ROOT)
    print('-' * 60)
    for lv, name, detail, fixhint in rows:
        if quiet and lv == 'v':
            continue
        print('%s %-13s %s' % (GLYPH[lv], name, detail))
        if fixhint:
            print('  └ %s' % fixhint)

    nv = sum(1 for r in rows if r[0] == 'v')
    nw = sum(1 for r in rows if r[0] == 'w')
    nx = sum(1 for r in rows if r[0] == 'x')
    nd = sum(1 for r in rows if r[0] == 'd')
    print('-' * 60)
    print('%d 通过 · %d 建议 · %d 问题 · %d 跳过' % (nv, nw, nx, nd))
    if nx:
        print('有 %d 个真问题，按上面的「└」修；改不了再问人。' % nx)
        return 1
    if nw:
        print('能跑，但有 %d 条建议 —— 现在不修，换机器/换人时就会变成问题。' % nw)
        return 2
    print('全绿。')
    return 0


if __name__ == '__main__':
    sys.exit(main())


if __name__ == '__main__':
    sys.exit(main())
