#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
CR-16102808 验收脚本：代码节点沙箱

用法（容器内）：
    PYTHONPATH=/app/api python /tmp/crn_sandbox_check.py

覆盖 AC-01 ~ AC-08。
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, "/app/api")

from internal.core.workflow.nodes.code.code_node import CodeNode, SANDBOX_ENV  # noqa: E402
from internal.exception import FailException  # noqa: E402

RESULTS = []


def record(ac, name, ok, detail=""):
    RESULTS.append((ac, name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {ac} {name}" + (f" — {detail}" if detail else ""))


def run(code, params=None):
    """调用被测方法，返回 (成功与否, 结果或错误信息)"""
    try:
        return True, CodeNode._execute_function(code, params=params or {})
    except FailException as e:
        # CustomException 构造时没把 message 传给 Exception，str(e) 是空串，
        # 真实文案在 e.message 上
        return False, (getattr(e, "message", None) or str(e) or "")
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


# ─────────────────────────────────────────────────────────────
# AC-01 现有工作流兼容（库里真实的快递鸟签名代码）
# ─────────────────────────────────────────────────────────────
REAL_CODE = '''def main(params):
    import json
    import hashlib
    import base64

    logistic_code = str(params.get("logistic_code") or "").strip()
    shipper_code = str(params.get("shipper_code") or "").strip()
    customer_name = str(params.get("customer_name") or "").strip()

    request_data = {"LogisticCode": logistic_code}
    if shipper_code:
        request_data["ShipperCode"] = shipper_code
    if customer_name:
        request_data["CustomerName"] = customer_name

    request_data_str = json.dumps(request_data, ensure_ascii=False)

    api_key = "c0c4957c-f85f-4cd5-b294-b420e3547e83"
    md5_hash = hashlib.md5((request_data_str + api_key).encode("utf-8")).hexdigest()
    data_sign = base64.b64encode(md5_hash.encode("utf-8")).decode("utf-8")

    return {
        "RequestType": 8002,
        "EBusinessID": 1939839,
        "DataSign": data_sign,
        "RequestData": request_data_str,
    }
'''

PARAMS = {"logistic_code": "SF1234567890", "shipper_code": "SF", "customer_name": ""}

# 旧实现（进程内 exec）作为基准
def legacy_exec(code, params):
    tree = __import__("ast").parse(code)
    local_vars = {}
    exec(code, {}, local_vars)  # noqa: S102
    return local_vars["main"](params)


ok, new_result = run(REAL_CODE, PARAMS)
try:
    old_result = legacy_exec(REAL_CODE, PARAMS)
except Exception as e:  # noqa: BLE001
    old_result = {"error": str(e)}
record("AC-01", "现有工作流输出与改造前一致", ok and new_result == old_result,
       f"新={str(new_result)[:80]}" if ok else f"失败: {new_result}")

# ─────────────────────────────────────────────────────────────
# AC-02 死循环：应在 ~5 秒内被终止，且不影响 API
# ─────────────────────────────────────────────────────────────
t0 = time.time()
ok, err = run('def main(params):\n    while True:\n        pass\n')
cost = time.time() - t0
record("AC-02", f"死循环被终止（耗时 {cost:.1f}s）", (not ok) and cost <= 9,
       f"提示: {err}")

# ─────────────────────────────────────────────────────────────
# AC-03 内存炸弹
# ─────────────────────────────────────────────────────────────
ok, err = run('def main(params):\n    x = [0] * (10 ** 8)\n    return {"n": len(x)}\n')
record("AC-03", "超大内存分配被限制", not ok, f"提示: {err}")

# ─────────────────────────────────────────────────────────────
# AC-04 危险模块导入
# ─────────────────────────────────────────────────────────────
cases = {
    "import os": 'def main(params):\n    import os\n    return {}\n',
    "import subprocess": 'def main(params):\n    import subprocess\n    return {}\n',
    "import socket": 'def main(params):\n    import socket\n    return {}\n',
    "from os import system": 'def main(params):\n    from os import system\n    return {}\n',
    "import urllib.request": 'def main(params):\n    import urllib.request\n    return {}\n',
}
all_blocked = True
details = []
for label, code in cases.items():
    ok, err = run(code)
    blocked = (not ok) and ("不允许导入" in err)
    details.append(f"{label}→{'拦' if blocked else '漏'}")
    all_blocked = all_blocked and blocked
record("AC-04", "危险模块导入被拦截", all_blocked, "; ".join(details))

# 反向：白名单模块必须仍可用
ok, res = run('def main(params):\n    import math\n    return {"pi": round(math.pi, 2)}\n')
record("AC-04b", "白名单模块仍可用（math）", ok and res.get("pi") == 3.14, str(res))

# ─────────────────────────────────────────────────────────────
# AC-05 环境变量净化
#   ① AST 层：import os 被拦
#   ② 直连子进程（绕过 AST），验证 SANDBOX_ENV 里确实没有敏感变量
# ─────────────────────────────────────────────────────────────
ok, err = run('def main(params):\n    import os\n    return {"env": dict(os.environ)}\n')
ast_blocked = (not ok) and ("不允许导入" in err)

probe = subprocess.run(
    [sys.executable, "-I", "-S", "-c",
     "import os, json; print(json.dumps(dict(os.environ)))"],
    capture_output=True, text=True, env=SANDBOX_ENV, timeout=30, check=False,
)
child_env = json.loads(probe.stdout or "{}")
sensitive = [k for k in child_env if any(
    token in k.upper() for token in ("PASSWORD", "SECRET", "DATABASE", "SQLALCHEMY", "JWT", "API_KEY", "REDIS")
)]
record("AC-05", "子进程拿不到敏感环境变量", ast_blocked and not sensitive,
       f"AST拦截={ast_blocked}, 子进程可见变量={list(child_env.keys())}")

# ─────────────────────────────────────────────────────────────
# AC-06 写文件被拒
# ─────────────────────────────────────────────────────────────
ok, err = run('def main(params):\n    open("/tmp/crn_should_not_exist", "w").write("x")\n    return {}\n')
record("AC-06", "open 写文件被拒", (not ok) and ("不允许调用 open" in err),
       f"提示: {err}; 文件存在={os.path.exists('/tmp/crn_should_not_exist')}")

# ─────────────────────────────────────────────────────────────
# AC-07 原有 5 类校验提示不变
# ─────────────────────────────────────────────────────────────
legacy_cases = [
    ("无 main（空代码）", '', "代码中必须包含名为main的函数"),
    ("只有其他函数", 'def other(params):\n    return {}\n', "代码中不能包含其他函数，只能有main函数"),
    ("两个 main", 'def main(params):\n    return {}\ndef main(params):\n    return {}\n', "代码中只能有一个main函数"),
    ("参数不是 params", 'def main(a):\n    return {}\n', "main函数必须只有一个参数，且参数为params"),
    ("顶层有额外语句", 'import json\ndef main(params):\n    return {}\n', "代码中只能包含函数定义，不允许其他语句存在"),
    ("语法错误", 'def main(params)\n    return {}\n', "Python代码执行出错"),
]
legacy_ok = True
legacy_detail = []
for label, code, expect in legacy_cases:
    ok, err = run(code)
    hit = (not ok) and (err == expect)
    legacy_detail.append(f"{label}→{'对' if hit else err}")
    legacy_ok = legacy_ok and hit
record("AC-07", "原有校验提示文案不变", legacy_ok, "; ".join(legacy_detail))

# 返回值非 dict
ok, err = run('def main(params):\n    return [1, 2]\n')
record("AC-07b", "返回值非 dict 报错", (not ok), f"提示: {err}")

# ─────────────────────────────────────────────────────────────
# AC-08 额外开销
# ─────────────────────────────────────────────────────────────
SIMPLE = 'def main(params):\n    return {"v": params.get("a", 0) + 1}\n'
t0 = time.time()
for _ in range(20):
    run(SIMPLE, {"a": 1})
avg_new = (time.time() - t0) / 20 * 1000

t0 = time.time()
for _ in range(20):
    legacy_exec(SIMPLE, {"a": 1})
avg_old = (time.time() - t0) / 20 * 1000

record("AC-08", f"单节点开销 {avg_new:.1f}ms（旧 {avg_old:.2f}ms，增 {avg_new - avg_old:.1f}ms）",
       avg_new < 200, f"阈值 200ms")

# ─────────────────────────────────────────────────────────────
print("\n" + "=" * 66)
passed = sum(1 for item in RESULTS if item[2])
print(f"合计：{passed}/{len(RESULTS)} 通过")
failed = [item for item in RESULTS if not item[2]]
if failed:
    print("未通过：")
    for ac, name, _ok, detail in failed:
        print(f"  - {ac} {name}: {detail}")
    sys.exit(1)
print("全部通过")
