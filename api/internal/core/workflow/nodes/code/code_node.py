#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
@Time    : 2024/11/25 15:42
@Author  : thezehui@gmail.com
@File    : code_node.py
"""
import ast
import json
import logging
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from typing import Optional

from langchain_core.runnables import RunnableConfig

from internal.core.workflow.entities.node_entity import NodeResult, NodeStatus
from internal.core.workflow.entities.variable_entity import VARIABLE_TYPE_DEFAULT_VALUE_MAP
from internal.core.workflow.entities.workflow_entity import WorkflowState
from internal.core.workflow.nodes import BaseNode
from internal.core.workflow.utils.helper import extract_variables_from_state
from internal.exception import FailException
from .code_entity import CodeNodeData


# CR-16102808：沙箱子进程的最小环境变量白名单。
# 说明：docker-compose 通过公共锚点注入了 30+ 变量（数据库连接串、JWT 密钥、各平台 API Key），
#      逐条拉黑以后新增变量就漏，因此改为「只放行必需项」。
SANDBOX_ENV = {
    "PATH": "/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin",
    "LANG": "C.UTF-8",
    "PYTHONIOENCODING": "utf-8",
    "PYTHONDONTWRITEBYTECODE": "1",
}

# ===== CR-16102808：沙箱参数 =====
# 允许导入的模块白名单（与 sandbox_runner.SAFE_MODULES 保持一致，两处都放行才可用）
SANDBOX_ALLOWED_MODULES = frozenset({
    "json", "math", "re", "datetime", "time", "random", "uuid", "hashlib",
    "base64", "itertools", "functools", "collections", "string", "decimal",
    "statistics", "urllib.parse", "html", "textwrap", "csv", "binascii",
    "struct", "unicodedata", "operator", "copy", "typing", "enum", "dataclasses",
    "heapq", "bisect", "calendar", "zoneinfo", "pprint", "difflib",
})
# 禁止调用的内置函数：都是沙箱逃逸的常见跳板
SANDBOX_FORBIDDEN_CALLS = frozenset({
    "eval", "exec", "compile", "open", "__import__", "breakpoint", "input",
    "globals", "locals", "vars", "getattr", "setattr", "delattr",
})
# 墙钟超时（与 runner 内的 RLIMIT_CPU 双保险：一个管算太久，一个管卡住不动）
SANDBOX_TIMEOUT = 5


class CodeNode(BaseNode):
    """Python代码运行节点"""
    node_data: CodeNodeData

    def invoke(self, state: WorkflowState, config: Optional[RunnableConfig] = None) -> WorkflowState:
        """Python代码运行节点，执行的代码函数名字必须为main，并且参数名为params，有且只有一个参数，不允许有额外的其他语句"""
        # 1.从状态中提取输入数据
        start_at = time.perf_counter()
        inputs_dict = extract_variables_from_state(self.node_data.inputs, state)

        # 2.执行Python代码
        # CR-16102808：已从「进程内 exec」改为「独立子进程沙箱」——
        # 代码崩溃/死循环/内存爆炸不影响 API 进程，且子进程拿不到数据库连接串等环境变量
        result = self._execute_function(self.node_data.code, params=inputs_dict)

        # 3.检测函数的返回值是否为字典
        if not isinstance(result, dict):
            raise FailException("main函数的返回值必须是一个字典")

        # 4.提取输出数据
        outputs_dict = {}
        outputs = self.node_data.outputs
        for output in outputs:
            # 5.提取输出数据(非严格校验)
            outputs_dict[output.name] = result.get(
                output.name,
                VARIABLE_TYPE_DEFAULT_VALUE_MAP.get(output.type),
            )

        # 6.构建状态数据并返回
        return {
            "node_results": [
                NodeResult(
                    node_data=self.node_data,
                    status=NodeStatus.SUCCEEDED,
                    inputs=inputs_dict,
                    outputs=outputs_dict,
                    latency=(time.perf_counter() - start_at),
                )
            ]
        }


    @classmethod
    def _module_allowed(cls, name: str) -> bool:
        """模块名是否在白名单内（放行子模块：urllib.parse 通过、urllib.request 拒绝）"""
        if not name:
            return True
        for allowed in SANDBOX_ALLOWED_MODULES:
            if name == allowed or name.startswith(allowed + "."):
                return True
        return False

    @classmethod
    def _validate_sandbox(cls, tree: ast.AST) -> None:
        """静态拦截危险的导入与内置调用，给用户可读原因（真正的兜底在 runner 的受限 builtins）"""
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if not cls._module_allowed(alias.name):
                        raise FailException(f"代码中不允许导入模块 {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if not cls._module_allowed(module):
                    # 兼容 from urllib import parse 这种拆开写的形式
                    joined = [f"{module}.{alias.name}" for alias in node.names]
                    if not any(cls._module_allowed(item) for item in joined):
                        raise FailException(f"代码中不允许导入模块 {module}")
            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id in SANDBOX_FORBIDDEN_CALLS:
                    raise FailException(f"代码中不允许调用 {func.id}")

    @classmethod
    def _kill_group(cls, proc: subprocess.Popen) -> None:
        """杀掉整个进程组，避免代码 fork 出的子进程残留"""
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            try:
                proc.kill()
            except Exception:
                pass
        try:
            proc.wait(timeout=5)
        except Exception:
            pass

    @classmethod
    def _execute_function(cls, code: str, *args, **kwargs):
        """执行Python函数代码

        CR-16102808：不再用 exec 在 API 进程内直接执行，改为起独立子进程跑
        sandbox_runner.py —— 崩溃、死循环、内存爆炸都不会影响主服务，
        且子进程拿不到数据库连接串等环境变量。
        """
        # 1.语法校验（原有行为：语法错统一报"Python代码执行出错"）
        try:
            tree = ast.parse(code)
        except SyntaxError as error:
            logging.warning("代码节点语法错误: %s (line %s)", error.msg, error.lineno)
            raise FailException("Python代码执行出错")

        # 2.保持原有的结构校验，提示文案逐字不变
        main_func = None
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                if node.name == "main":
                    if main_func:
                        raise FailException("代码中只能有一个main函数")
                    if len(node.args.args) != 1 or node.args.args[0].arg != "params":
                        raise FailException("main函数必须只有一个参数，且参数为params")
                    main_func = node
                else:
                    raise FailException("代码中不能包含其他函数，只能有main函数")
            else:
                raise FailException("代码中只能包含函数定义，不允许其他语句存在")

        if not main_func:
            raise FailException("代码中必须包含名为main的函数")

        # 3.新增：危险 import / 调用拦截
        cls._validate_sandbox(tree)

        # 4.子进程沙箱执行
        params = kwargs.get("params") or {}
        payload = json.dumps({"code": code, "params": params}, ensure_ascii=False)
        runner = str(pathlib.Path(__file__).with_name("sandbox_runner.py"))
        workdir = tempfile.mkdtemp(prefix="wf-code-")
        try:
            proc = subprocess.Popen(
                [sys.executable, "-I", "-S", runner],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=workdir,
                env=SANDBOX_ENV,
                start_new_session=True,
            )
            try:
                stdout, stderr = proc.communicate(payload.encode("utf-8"), timeout=SANDBOX_TIMEOUT)
            except subprocess.TimeoutExpired:
                cls._kill_group(proc)
                raise FailException(f"代码执行超时（超过{SANDBOX_TIMEOUT}秒），请检查是否有死循环")
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

        # 5.被信号杀掉：CPU 超限（SIGXCPU）或被内核强杀（SIGKILL，通常是内存）
        if proc.returncode in (-signal.SIGKILL, -signal.SIGXCPU):
            raise FailException("代码执行超出资源限制（超时或内存过大），请检查代码")
        if proc.returncode != 0 and not stdout:
            logging.warning(
                "代码节点沙箱异常退出 rc=%s stderr=%s",
                proc.returncode,
                (stderr or b"")[-2000:].decode("utf-8", "replace"),
            )
            raise FailException("Python代码执行出错")

        # 6.解析子进程返回的 JSON
        try:
            data = json.loads((stdout or b"").decode("utf-8"))
        except Exception:
            logging.warning(
                "代码节点沙箱输出无法解析 stderr=%s",
                (stderr or b"")[-2000:].decode("utf-8", "replace"),
            )
            raise FailException("Python代码执行出错")

        if not data.get("ok"):
            error_msg = data.get("error") or ""
            logging.warning("代码节点沙箱执行失败: %s", data.get("trace") or error_msg)
            # 资源类错误与「返回值不是字典」把原因透给用户（与改造前文案一致），
            # 其余维持原文案，不泄露内部细节
            if "内存超限" in error_msg or "超时" in error_msg:
                raise FailException(error_msg)
            if "返回值必须是一个字典" in error_msg:
                raise FailException("main函数的返回值必须是一个字典")
            raise FailException("Python代码执行出错")

        return data.get("result")
