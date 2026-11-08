"""Smoke test over stdio, no Navisworks needed.

    python tests/smoke_stdio.py <server command...>
    python tests/smoke_stdio.py dist\\Navis-mcp\\server\\navis-mcp.exe
    python tests/smoke_stdio.py .venv\\Scripts\\python.exe -m naviscoord.mcp_server

Checks: initialize, the expected tool counts in read-only mode, hidden tools,
one navis_* and one nwd_* call routed to their bridges (both answer "no
Navisworks" when it is closed), and output=file validation.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

EXPECTED_NAVIS = 49   # 53 NavisCoord tools minus save/save_as/close_document/exit
EXPECTED_NWD = 21     # nwd-mcp read-only toolsets


def main() -> int:
    cmd = sys.argv[1:]
    if not cmd:
        print(__doc__)
        return 2
    env = {**os.environ, "NAVIS_MCP_READ_ONLY": "1", "PYTHONPATH": os.path.join(os.path.dirname(__file__), "..", "server")}
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    threading.Thread(target=lambda: [sys.stderr.write("  | " + l.decode("utf-8", "replace")) for l in proc.stderr],
                     daemon=True).start()
    next_id = 0

    def rpc(method: str, params: dict | None = None) -> dict:
        nonlocal next_id
        next_id += 1
        msg = {"jsonrpc": "2.0", "id": next_id, "method": method}
        if params is not None:
            msg["params"] = params
        proc.stdin.write((json.dumps(msg) + "\n").encode())
        proc.stdin.flush()
        while True:
            line = proc.stdout.readline()
            if not line:
                raise SystemExit(f"server closed stdout during {method}")
            reply = json.loads(line)
            if reply.get("id") == next_id:
                return reply

    failures: list[str] = []

    def check(ok: bool, label: str) -> None:
        print(("ok   " if ok else "FAIL ") + label)
        if not ok:
            failures.append(label)

    t0 = time.time()
    init = rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                              "clientInfo": {"name": "smoke", "version": "1"}})["result"]
    proc.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
    proc.stdin.flush()
    check(init["serverInfo"]["name"] == "navis-mcp", f"serverInfo {init['serverInfo']} ({time.time() - t0:.1f}s)")
    check("READ-ONLY" in (init.get("instructions") or ""), "instructions announce read-only mode")

    tools = [t["name"] for t in rpc("tools/list")["result"]["tools"]]
    navis = [t for t in tools if t.startswith("navis_")]
    nwd = [t for t in tools if t.startswith("nwd_")]
    check(len(navis) == EXPECTED_NAVIS, f"navis_* tools: {len(navis)} (expected {EXPECTED_NAVIS})")
    check(len(nwd) == EXPECTED_NWD, f"nwd_* tools: {len(nwd)} (expected {EXPECTED_NWD})")
    check(not {"navis_save", "navis_exit", "nwd_send_code", "nwd_open_file"} & set(tools), "write tools hidden")

    def call(name: str, args: dict | None = None) -> tuple[dict, str]:
        res = rpc("tools/call", {"name": name, "arguments": args or {}})
        if "error" in res:
            return res, json.dumps(res["error"])
        result = res["result"]
        return result, "".join(c.get("text", "") for c in result.get("content", []))

    _, text = call("navis_health")
    check("error" in text or "version" in text, "navis_health answered: " + text[:110].replace("\n", " "))
    result, text = call("nwd_health_check")
    check("NO_TARGET" in text or '"ok":true' in text or "year" in text, "nwd_health_check answered: " + text[:110])
    if "NO_TARGET" in text:
        check(result.get("isError") is True, "nwd failure sets isError")
    _, text = call("nwd_get_model_tree", {"output": "csv"})
    check("INVALID_ARGUMENT" in text, "output must be inline|file")
    _, text = call("nwd_list_available_targets")
    check(text.startswith("["), "nwd_list_available_targets returns a list: " + text[:80])
    _, text = call("nwd_list_baked_tools")
    check('"tools"' in text, "nwd_list_baked_tools reads bake.db")
    res = rpc("tools/call", {"name": "navis_save", "arguments": {}})
    blocked = "error" in res or res.get("result", {}).get("isError")
    check(bool(blocked), "navis_save refused in read-only mode")

    proc.stdin.close()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    print(f"\n{len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
