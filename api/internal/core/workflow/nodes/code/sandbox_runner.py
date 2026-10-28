#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@File    : sandbox_runner.py
@Desc    : CR-16102808 代码节点沙箱 —— 子进程侧执行体

设计要点（对应 08-设计/08-1-应用设计.md）：
1. 本文件由 CodeNode 以独立子进程方式启动，**不 import 项目内任何模块**
   （启动参数 -I 隔离模式 + -S 跳过 site，cwd 是临时空目录）。
2. 资源上限在**本进程内**设置，而不是父进程的 preexec_fn ——
   preexec_fn 在多线程（gunicorn gthread）下官方标注不安全，容易死锁。
3. 用户的 print 会被引到 stderr，结果只通过原始 stdout fd 输出一段 JSON，
   避免被用户输出污染。
4. 除了父进程的 AST 校验，这里再做一层「受限 builtins」兜底：
   即使 AST 被绕过，import / open / eval / exec 依然拿不到。

协议：
    入参 stdin  : {"code": "<python source>", "params": {...}}
    出参 stdout : {"ok": true, "result": {...}}
              或  {"ok": false, "error": "...", "trace": "..."}
"""
import builtins
import json
import os
import resource
import sys
import traceback

# 与 code_node.SAFE_MODULES 保持一致（两处都放行才可用，一处拦就拒）
SAFE_MODULES = {
    "json", "math", "re", "datetime", "time", "random", "uuid", "hashlib",
    "base64", "itertools", "functools", "collections", "string", "decimal",
    "statistics", "urllib.parse", "html", "textwrap", "csv", "binascii",
    "struct", "unicodedata", "operator", "copy", "typing", "enum", "dataclasses",
    "heapq", "bisect", "calendar", "zoneinfo", "pprint", "difflib", "unicodedata",
}

# 资源上限（与设计文档 §三 一致）
LIMIT_CPU_SECONDS = 5
LIMIT_AS_BYTES = 512 * 1024 * 1024
LIMIT_FSIZE_BYTES = 0          # 禁止写任何文件
LIMIT_NOFILE = 64


def _apply_limits() -> None:
    """在执行业务代码前收紧资源上限"""
    # 1.CPU 时间：超了内核直接 SIGKILL，防死循环
    resource.setrlimit(resource.RLIMIT_CPU, (LIMIT_CPU_SECONDS, LIMIT_CPU_SECONDS + 1))
    # 2.地址空间：防内存炸弹（runner 自身此时只占几 MB，不会误伤）
    resource.setrlimit(resource.RLIMIT_AS, (LIMIT_AS_BYTES, LIMIT_AS_BYTES))
    # 3.可写文件大小置 0：彻底禁写盘（stdout 是 pipe，不受此限）
    resource.setrlimit(resource.RLIMIT_FSIZE, (LIMIT_FSIZE_BYTES, LIMIT_FSIZE_BYTES))
    # 4.打开文件数，防止刷 fd
    resource.setrlimit(resource.RLIMIT_NOFILE, (LIMIT_NOFILE, LIMIT_NOFILE))


def _module_allowed(name: str) -> bool:
    """模块名是否在白名单内（含子模块；urllib.parse 放行、urllib.request 拒绝）"""
    if not name:
        return True
    for allowed in SAFE_MODULES:
        if name == allowed or name.startswith(allowed + "."):
            return True
    return False


def _build_safe_builtins() -> dict:
    """构造受限的 __builtins__：去掉能直接突破沙箱的几个，import 换成白名单版"""
    real_import = builtins.__import__

    def safe_import(name, globals=None, locals=None, fromlist=(), level=0):
        root = (name or "").split(".")[0]
        if not _module_allowed(name) and not _module_allowed(root):
            raise ImportError(f"模块 {name} 不允许导入")
        return real_import(name, globals, locals, fromlist, level)

    safe = dict(vars(builtins))
    safe["__import__"] = safe_import
    # 这几个是沙箱逃逸的常用跳板，直接移出内置命名空间
    for name in ("eval", "exec", "compile", "open", "breakpoint", "input",
                 "globals", "locals", "vars", "getattr", "setattr", "delattr"):
        safe.pop(name, None)
    return safe


def _run(payload: dict) -> dict:
    """执行用户代码并调用 main(params)"""
    code = payload.get("code") or ""
    params = payload.get("params") or {}

    _apply_limits()

    namespace: dict = {}
    safe_builtins = _build_safe_builtins()
    exec(compile(code, "<workflow-code>", "exec"), {"__builtins__": safe_builtins}, namespace)

    main_func = namespace.get("main")
    if not callable(main_func):
        raise RuntimeError("main函数必须是一个可调用的函数")

    result = main_func(params)
    if not isinstance(result, dict):
        raise RuntimeError("main函数的返回值必须是一个字典")

    # default=str：允许返回值里混入 datetime / Decimal 等不可直接序列化的类型
    return json.loads(json.dumps(result, ensure_ascii=False, default=str))


def main() -> None:
    # 1.先保住真实 stdout，后面把 sys.stdout 换成 stderr
    #   这样用户代码里的 print 只会进 stderr（父进程可当日志），不会污染结果
    result_fd = None
    try:
        result_fd = os.dup(1)
    except OSError:
        result_fd = 1

    raw = sys.stdin.read()
    sys.stdout = sys.stderr

    try:
        payload = json.loads(raw)
        out = json.dumps({"ok": True, "result": _run(payload)}, ensure_ascii=False)
    except MemoryError:
        out = json.dumps({
            "ok": False,
            "error": f"代码执行内存超限（上限 {LIMIT_AS_BYTES // (1024 * 1024)}MB）",
        }, ensure_ascii=False)
    except Exception as error:
        out = json.dumps({
            "ok": False,
            "error": f"{type(error).__name__}: {error}"[:500],
            # trace 只给开发排查，父进程只写日志不返回给用户
            "trace": traceback.format_exc()[-2000:],
        }, ensure_ascii=False)

    try:
        os.write(result_fd, out.encode("utf-8"))
    except OSError:
        # 兜底：fd 异常时退回普通 write
        sys.__stdout__.write(out)


if __name__ == "__main__":
    main()
