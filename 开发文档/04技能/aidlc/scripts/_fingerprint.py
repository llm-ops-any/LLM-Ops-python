#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""技能内容指纹 —— 判断两份技能副本是不是同一版。

为什么不拿 `version` 判断新旧：version 是**手写**的。2026-11-04 实测五个项目副本
内容已经各不相同，却全都标着 `2.6.0`；靠版本号比新旧，等于问人「你改完记得改号了吗」，
而人记不住（这正是 `自检.py` 要存在的原因）。

指纹只由**文件内容**决定，规则固定：

1. 收集技能目录下所有文件；剔除运行产物与外部注入（见下面的排除表）
2. 行尾归一化 CRLF → LF。`.gitattributes` 只保护一部分文件，同一份技能在
   Windows 工作区里可能是 CRLF、在 Linux 里是 LF，字节不同但内容等价 —— 不归一化会误报
3. 按相对路径排序，逐个算 SHA256，把「路径 + 内容哈希」喂进总哈希
4. 取前 16 位十六进制

结果与机器、行尾、文件系统顺序无关，只与内容有关。VERSION 文件本身不参与计算
（否则自指），`scripts/hooks/` 下 git-lfs 写入的两个钩子也不算 —— 那是 `git lfs install`
的副作用，不是技能内容（2026-11-05 在 haiyou_web_3d 实测到）。
"""

import hashlib
import io
import os
import re

# 运行产物 / 版本库 / 编辑器目录：会随环境变化，不属于技能内容
EXCLUDE_DIRS = {'__pycache__', '.git', 'node_modules', '.idea', '.vscode'}
# 操作系统写的垃圾文件
EXCLUDE_NAMES = {'.DS_Store', 'Thumbs.db', 'desktop.ini'}
# VERSION 自指；后两个是 git-lfs 注入的钩子（不是技能文件，别删也别算）
EXCLUDE_REL = {'VERSION', 'scripts/hooks/post-checkout', 'scripts/hooks/pre-push'}

VERSION_FILE = 'VERSION'
FP_LEN = 16


def iter_files(skill_dir):
    """按相对路径排序产出 (rel, full)。排序是为了让指纹与文件系统枚举顺序无关。"""
    out = []
    for root, dirs, files in os.walk(skill_dir):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for fn in files:
            if fn in EXCLUDE_NAMES:
                continue
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, skill_dir).replace(os.sep, '/')
            if rel in EXCLUDE_REL:
                continue
            out.append((rel, full))
    out.sort(key=lambda x: x[0])
    return out


def _norm_content(path):
    """读字节并做行尾归一化。二进制文件（含 NUL）按原样参与，只丢掉 CRLF 替换。"""
    with open(path, 'rb') as f:
        b = f.read()
    return b.replace(b'\r\n', b'\n')


def fingerprint(skill_dir):
    """返回 (16 位指纹, 参与计算的文件数)。目录不存在返回 (None, 0)。"""
    if not os.path.isdir(skill_dir):
        return None, 0
    files = iter_files(skill_dir)
    h = hashlib.sha256()
    for rel, full in files:
        h.update(rel.encode('utf-8'))
        h.update(b'\0')
        h.update(hashlib.sha256(_norm_content(full)).digest())
    return h.hexdigest()[:FP_LEN], len(files)


def file_hashes(skill_dir):
    """rel -> sha256(归一化内容)。`--diff` 用来定位到底哪个文件不同。"""
    out = {}
    for rel, full in iter_files(skill_dir):
        out[rel] = hashlib.sha256(_norm_content(full)).hexdigest()
    return out


def skill_version(skill_dir):
    """从 SKILL.md 的 frontmatter 读 version；读不到返回 None。"""
    path = os.path.join(skill_dir, 'SKILL.md')
    try:
        with io.open(path, encoding='utf-8', errors='replace') as f:
            text = f.read(4000)
    except (IOError, OSError):
        return None
    if not text.startswith('---'):
        return None
    parts = text.split('---')
    if len(parts) < 2:
        return None
    for line in parts[1].splitlines():
        m = re.match(r'^\s*version\s*:\s*([0-9][0-9A-Za-z.\-]*)', line)
        if m:
            return m.group(1).strip()
    return None


def read_version_file(skill_dir):
    """解析 VERSION。缺文件返回 None；文件在但缺字段，该字段为 None。"""
    path = os.path.join(skill_dir, VERSION_FILE)
    try:
        with io.open(path, encoding='utf-8', errors='replace') as f:
            text = f.read()
    except (IOError, OSError):
        return None
    data = {}
    for line in text.splitlines():
        if ':' not in line:
            continue
        k, v = line.split(':', 1)
        data[k.strip()] = v.strip()
    return {
        'skill': data.get('skill'),
        'version': data.get('version'),
        'fingerprint': data.get('fingerprint'),
        'files': data.get('files'),
    }


def render_version_file(skill_dir):
    """按当前内容算出 VERSION 的完整文本。

    **不含时间戳、不含项目名** —— 这样各副本的 VERSION 可以逐字节 diff。
    「什么时候改的」写在 SKILL.md 的 `updated:` 里，那是给人看的。
    """
    fp, n = fingerprint(skill_dir)
    ver = skill_version(skill_dir)
    return (
        'skill: aidlc\n'
        'version: %s\n'
        'fingerprint: %s\n'
        'files: %d\n'
    ) % (ver or 'unknown', fp or 'unknown', n)


def write_version_file(skill_dir):
    """重算并写 VERSION。返回写入的 dict。**改完技能文件必须跑一次。**"""
    text = render_version_file(skill_dir)
    path = os.path.join(skill_dir, VERSION_FILE)
    with io.open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
    return read_version_file(skill_dir)


def verify(skill_dir):
    """VERSION 与当前内容是否一致。

    返回 (状态, 说明)：
      'ok'      一致
      'missing' 没有 VERSION
      'stale'   内容变了但 VERSION 没更新 ⇒ 版本号已经不可信
      'nover'   VERSION 在，但 SKILL.md frontmatter 没 version
    """
    v = read_version_file(skill_dir)
    if not v:
        return 'missing', '没有 VERSION 文件'
    fp, n = fingerprint(skill_dir)
    if not v.get('fingerprint') or v['fingerprint'] != fp:
        return 'stale', '内容与 VERSION 记录不一致（记 %s，实算 %s，%s 个文件）' % (
            v.get('fingerprint') or '—', fp, n)
    if str(v.get('files')) != str(n):
        return 'stale', '文件数与 VERSION 记录不一致（记 %s，实 %d）' % (v.get('files'), n)
    cur = skill_version(skill_dir)
    if not cur:
        return 'nover', 'SKILL.md 没有 version 字段'
    if v.get('version') != cur:
        return 'stale', 'VERSION 记 version %s，SKILL.md 却是 %s' % (v.get('version'), cur)
    return 'ok', 'version %s，%s 个文件' % (cur, n)


def compare(a, b):
    """比两份副本。**只认指纹**，版本号只用来解释谁落后。

    返回 (状态, 说明)，状态：
      'same'   内容完全相同
      'diff'   内容不同（说明里给版本号线索与差异文件数）
    """
    fa, na = fingerprint(a)
    fb, nb = fingerprint(b)
    va, vb = skill_version(a), skill_version(b)
    if fa and fa == fb:
        return 'same', '内容完全相同（指纹 %s，%s 个文件）' % (fa, na)
    ta = tuple(int(x) for x in re.findall(r'\d+', va or '')) or (0,)
    tb = tuple(int(x) for x in re.findall(r'\d+', vb or '')) or (0,)
    if ta < tb:
        rel = 'A 落后 B'
    elif ta > tb:
        rel = 'A 比 B 新'
    elif va and va == vb:
        rel = '**版本号相同但内容不同** —— 有人改了没升版'
    else:
        rel = '版本号不可比，以内容为准'
    ha, hb = file_hashes(a), file_hashes(b)
    only_a = sorted(set(ha) - set(hb))
    only_b = sorted(set(hb) - set(ha))
    changed = sorted(k for k in set(ha) & set(hb) if ha[k] != hb[k])
    detail = '差异 %d 个文件' % (len(only_a) + len(only_b) + len(changed))
    bits = []
    if changed:
        bits.append('改动 %d' % len(changed))
    if only_a:
        bits.append('A 独有 %d' % len(only_a))
    if only_b:
        bits.append('B 独有 %d' % len(only_b))
    if bits:
        detail += '（%s）' % '，'.join(bits)
    return 'diff', '内容不同：A %s/%s · B %s/%s · %s；%s' % (
        va or '?', fa or '?', vb or '?', fb or '?', rel, detail)


def diff_files(a, b):
    """返回 (改动, A 独有, B 独有) 三个已排序列表，供 --diff 打印。"""
    ha, hb = file_hashes(a), file_hashes(b)
    changed = sorted(k for k in set(ha) & set(hb) if ha[k] != hb[k])
    only_a = sorted(set(ha) - set(hb))
    only_b = sorted(set(hb) - set(ha))
    return changed, only_a, only_b
