"""Smoke test of WRITE mode over stdio, no Navisworks needed.

    python tests/smoke_write.py <server command...>

Starts the server with --allow-write (overwrite and send_code left locked) and checks:
the write tools are listed, navis_save and nwd_send_code are not, and the overwrite
guards refuse before anything reaches Navisworks.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading

EXPECTED_NAVIS = 52   # 53 NavisCoord tools minus navis_save (overwrite locked)
EXPECTED_NWD = 32     # 33 nwd tools minus nwd_send_code (send_code locked)


def main() -> int:
    cmd = sys.argv[1:]
    if not cmd:
        print(__doc__)
        return 2
    env = {**os.environ, "PYTHONPATH": os.path.join(os.path.dirname(__file__), "..", "server")}
    for k in ("NAVIS_MCP_READ_ONLY", "NAVIS_MCP_ALLOW_OVERWRITE", "NAVIS_MCP_SEND_CODE"):
        env.pop(k, None)
    proc = subprocess.Popen(cmd + ["--allow-write"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, env=env)
    threading.Thread(target=lambda: [sys.stderr.write("  | " + l.decode("utf-8", "replace")) for l in proc.stderr],
                     daemon=True).start()
    n = 0

    def rpc(method: str, params: dict | None = None) -> dict:
        nonlocal n
        n += 1
        proc.stdin.write((json.dumps({"jsonrpc": "2.0", "id": n, "method": method, "params": params or {}}) + "\n").encode())
        proc.stdin.flush()
        while True:
            line = proc.stdout.readline()
            if not line:
                raise SystemExit(f"server closed stdout during {method}")
            reply = json.loads(line)
            if reply.get("id") == n:
                return reply

    failures: list[str] = []

    def check(ok: bool, label: str) -> None:
        print(("ok   " if ok else "FAIL ") + label)
        if not ok:
            failures.append(label)

    def call(name: str, args: dict) -> str:
        res = rpc("tools/call", {"name": name, "arguments": args})
        if "error" in res:
            return json.dumps(res["error"])
        return "".join(c.get("text", "") for c in res["result"].get("content", []))

    init = rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                              "clientInfo": {"name": "smoke-write", "version": "1"}})["result"]
    proc.stdin.write(b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
    proc.stdin.flush()
    instructions = init.get("instructions") or ""
    check("WRITES ALLOWED" in instructions and "Overwriting is BLOCKED" in instructions,
          "instructions announce write mode with overwrite blocked")

    tools = [t["name"] for t in rpc("tools/list")["result"]["tools"]]
    navis = [t for t in tools if t.startswith("navis_")]
    nwd = [t for t in tools if t.startswith("nwd_")]
    check(len(navis) == EXPECTED_NAVIS, f"navis_* tools: {len(navis)} (expected {EXPECTED_NAVIS})")
    check(len(nwd) == EXPECTED_NWD, f"nwd_* tools: {len(nwd)} (expected {EXPECTED_NWD})")
    for t in ("navis_save_as", "navis_set_status", "navis_configure", "navis_build_clash_matrix", "navis_run",
              "navis_run_tests", "navis_color_by_priority", "navis_reset_appearance", "navis_close_document",
              "navis_exit", "nwd_open_file", "nwd_save_viewpoint", "nwd_hide_items"):
        check(t in tools, f"listed: {t}")
    check("navis_save" not in tools, "navis_save (save in place) hidden without --allow-overwrite")
    check("nwd_send_code" not in tools, "nwd_send_code hidden without --allow-send-code")

    text = call("navis_save_as", {"path": r"C:\x\teste.nwd", "expected_document_fingerprint": "abc", "overwrite": True})
    check("sobrescrita_bloqueada" in text, "navis_save_as overwrite=true refused")
    text = call("navis_close_document", {"disposition": "save", "expected_document_fingerprint": "abc", "dry_run": True})
    check("sobrescrita_bloqueada" in text, "navis_close_document disposition=save refused")
    text = call("navis_exit", {"disposition": "save", "expected_document_fingerprint": "abc", "dry_run": True})
    check("sobrescrita_bloqueada" in text, "navis_exit disposition=save refused")
    text = call("navis_save_as", {"path": r"C:\x\teste.nwd", "expected_document_fingerprint": "abc"})
    check("sobrescrita_bloqueada" not in text, "navis_save_as without overwrite passes the guard: " + " ".join(text.split())[:90])

    proc.stdin.close()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
    print(f"\n{len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
