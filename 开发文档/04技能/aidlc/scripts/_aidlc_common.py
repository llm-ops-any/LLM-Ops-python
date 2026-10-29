# -*- coding: utf-8 -*-
"""AIDLC 脚本共用常量 —— 只放「两个以上脚本都要用」的东西。

为什么不各写一份：2026-10-21 一天里，「同一规则两处定义」已经造成两次腐化
（技能副本落点写死 `skills/`、`.gitattributes` 只在一处补）。规则只能有一个来源。
"""

import glob
import os

GITATTR_HEAD = '# AIDLC：git 钩子必须是 LF —— CRLF 会让 shebang 失效，钩子静默不执行'

GITATTR_LINES = (
    '*.sh text eol=lf',
    '.gitattributes text eol=lf',
    '**/scripts/hooks/* text eol=lf',
)

# 所有跨 CR 的视图都收口到 `开发文档/_汇总/`：整个目录**本地生成、不入库**。
#
# 为什么：它们是「扫各 CR 分片算出来的」。只要入库，两条并行线各自跑过汇总内容必然不同
# （各自多一行 CR、生成时间也不同）→ 合并时三方合并必冲突，而手工解冲突毫无意义。
# 2026-10-21 实测：两个并行 CR 合并时 `状态.md` 冲突 5 处、`需求索引.md` 3 处，全是纯生成物；
# 换成按 CR 拆目录 + 视图集中到 _汇总/ 后，冲突面只剩源代码。
#
# 真实来源永远是分片：`<类型目录>/CR-<8位号>/{需求,状态,设计,测试记录,验收报告,问题,运维说明,变更说明,审计-<人>}.md`
GENERATED_DIR = '开发文档/_汇总/'
GENERATED_IGNORE = (
    GENERATED_DIR,
    # Python 字节码缓存：技能副本里的脚本 import 同目录模块时会生成，
    # 不同 Python 版本文件名不同（cpython-311 / 313），一旦入库就会互相污染。
    '__pycache__/',
    '*.pyc',
)

GITIGNORE_HEAD = '# AIDLC：生成物与 Python 缓存，都不入库（视图本地生成；pyc 跨版本会互相污染）'


def gitattributes_missing(text):
    """返回 .gitattributes 里缺的行（用于幂等补齐）。"""
    have = set(l.strip() for l in text.splitlines())
    return [l for l in GITATTR_LINES if l not in have]


def gitignore_missing(text):
    """返回 .gitignore 里缺的生成物行（用于幂等补齐）。"""
    have = set(l.strip().replace('\\', '/').lstrip('/') for l in text.splitlines())
    return [l for l in GENERATED_IGNORE if l not in have]


# ── CR 目录内的标准文件名 ────────────────────────────────────────────────
#
# 编号是**排序用的固定位**，不是「第几步」：
#   · 某份文档没有就不建，号**空着**，绝不把后面的号往前挪 —— 一重排，路径变、
#     引用断、git 历史也断；
#   · 号段留空档（0x 想清楚 / 1x 设计 / 2x 构建 / 3x 交付 / 4x 审计），
#     将来加文件不用挤号。
#
# 2026-10-27 引入。老项目可以不带编号（软兼容），所有查找统一走 find_cr_file()。
CR_FILES = {
    '状态': '00-状态.md',
    '需求': '01-需求.md',
    '问题': '02-问题.md',
    '前置资源': '03-前置资源.md',
    '风险': '04-风险.md',
    '用户故事': '05-用户故事.md',
    '执行计划': '06-执行计划.md',
    '决策记录': '07-决策记录.md',
    '测试记录': '20-测试记录.md',
    '构建说明': '21-构建说明.md',
    '验收报告': '30-验收报告.md',
    '运维说明': '31-运维说明.md',
    '变更说明': '32-变更说明.md',
}

DESIGN_DIR = '08-技术设计'
# 两代旧名，都认：`08-设计/`（2026-10-27 ~ 10-29）、`设计/`（2026-10-27 之前的裸名）
DESIGN_DIR_LEGACY = ('08-设计', '设计')
# 逐级编号：目录 08，内部 08-N。**超过 9 份就写 08-01 两位**，否则字符串排序会乱
# （'08-10' < '08-2'）。
DESIGN_FILES = {
    '应用设计': '08-1-应用设计.md',
    '功能设计': '08-2-功能设计.md',
    '业务规则': '08-3-业务规则.md',
    '代码结构': '08-4-代码结构.md',
    '工作单元': '08-5-工作单元.md',
}

# 审计一人一份，号相同靠人名区分（`40-审计-张勇.md` / `40-审计-张勇2.md`）
AUDIT_PREFIX = '40-审计-'
AUDIT_LEGACY_PREFIX = '审计-'


def find_cr_file(cr_dir, name):
    """在 CR 目录里找一份标准文档，返回路径；找不到返回 None。

    两种命名都认（编号是 2026-10-27 加的，老项目未必迁）：
      ① `NN-名字.md` —— 新，带编号，排序稳定；
      ② `名字.md`    —— 老项目原样，不动它。

    找不到就返回 None，由调用方决定「这份文档不存在」怎么处理 ——
    **绝不返回一个不存在的路径**，那会让 `os.path.exists` 悄悄为假、问题被吞掉。

    参数 `name` 带不带 `.md` 都行（`'状态'` / `'状态.md'` 等价）。
    """
    base = name[:-3] if name.endswith('.md') else name
    target = CR_FILES.get(base, base + '.md')
    p = os.path.join(cr_dir, target)
    if os.path.isfile(p):
        return p
    legacy = os.path.join(cr_dir, base + '.md')   # 编号名没命中，退回裸名
    if target != base + '.md' and os.path.isfile(legacy):
        return legacy
    return None


def find_audit_files(cr_dir):
    """CR 下的审计分片，一人一份。新旧两种前缀都收（混用时不漏）。"""
    hits = set(glob.glob(os.path.join(cr_dir, AUDIT_PREFIX + '*.md')))
    hits |= set(glob.glob(os.path.join(cr_dir, AUDIT_LEGACY_PREFIX + '*.md')))
    return sorted(hits)


def design_dir(cr_dir):
    """设计目录：`08-技术设计/`，老项目依次退回 `08-设计/`、`设计/`。都没有返回 None。"""
    for name in (DESIGN_DIR,) + DESIGN_DIR_LEGACY:
        p = os.path.join(cr_dir, name)
        if os.path.isdir(p):
            return p
    return None


def design_files(cr_dir):
    """`08-技术设计/` 下所有 .md，**按文件名排序**。

    逐级编号（`08-1-` `08-2-`）天然有序，所以不用维护阅读顺序表；
    老项目的裸名（`应用设计.md`）则退化为字典序，能读就行。
    """
    ddir = design_dir(cr_dir)
    if not ddir:
        return []
    return sorted(os.path.join(ddir, f) for f in os.listdir(ddir) if f.endswith('.md'))
