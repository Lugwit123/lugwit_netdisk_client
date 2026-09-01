# -*- coding: utf-8 -*-
"""触发客户端 GUI 自动测试。

把 tests/gui_suite.py 丢进正在运行的客户端进程（l_script_editor 的 HTTP 接口），
在真窗口、真登录态、真网盘上跑，然后把结果打回来。

前置：客户端已启动
    wuwor lugwit_netdisk_client -- netdisk_client

跑法：
    python tests/run_gui_tests.py
    python tests/run_gui_tests.py --port 8764 --timeout 600
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SUITES = {"gui": HERE / "gui_suite.py", "p4v": HERE / "p4v_suite.py",
          "perf": HERE / "perf_suite.py"}


def get(url: str, timeout: int = 10) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as f:
        return json.loads(f.read().decode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8764)
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--suite", choices=sorted(SUITES) + ["all"], default="all",
                    help="gui=客户端外壳/桥, p4v=P4V 布局走查")
    args = ap.parse_args()
    base = f"http://127.0.0.1:{args.port}"

    try:
        st = get(base + "/status", 5)
    except (urllib.error.URLError, OSError) as exc:
        print(f"连不上脚本编辑器服务 {base}：{exc}")
        print("确认客户端已启动，且标题栏 </> 的 HTTP 服务是开着的。")
        return 2
    if not st.get("editor_available"):
        print(f"服务在跑但编辑器不可用：{st}")
        return 2
    print(f"已连上客户端进程 {base}  server_id={st.get('server_id')}")

    # perf 是性能体检不是回归测试，要单独点名才跑
    names = ["gui", "p4v"] if args.suite == "all" else [args.suite]
    rc = 0
    for name in names:
        suite = SUITES[name]
        if not suite.is_file():
            print(f"找不到测试体：{suite}")
            return 2
        q = urllib.parse.urlencode({"path": str(suite), "timeout": args.timeout})
        print(f"{'=' * 56}\n注入 {suite.name}，超时 {args.timeout}s\n")
        try:
            res = get(f"{base}/execute?{q}", args.timeout + 30)
        except urllib.error.HTTPError as e:
            print(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:500]}")
            rc = max(rc, 2)
            continue

        out = res.get("stdout") or ""
        print(out)
        err = (res.get("stderr") or "").strip()
        if err:
            print("--- stderr ---\n" + err)
        if res.get("error"):
            print(f"--- error ---\n{res['error']}")

        if "RESULT PASS" in out:
            continue
        rc = max(rc, 1 if "RESULT FAIL" in out else 2)
        if "RESULT" not in out:
            print("没拿到测试结论，可能超时或进程崩了。")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
