"""Protocol test for the nwd_* port against a fake nwd plug-in (no Navisworks needed).

    python tests/test_nwd_protocol.py

The fake listens on loopback, writes a target descriptor exactly like the real
plug-in (navis-<year>-<pid>.json with port, token and heartbeat) and answers
one NDJSON envelope per connection. Then the real tool functions are called
through a minimal stand-in for the MCP server.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))

from naviscoord.nwd.config import NwdConfig  # noqa: E402
from naviscoord.nwd.tools import register  # noqa: E402

TOKEN = "f" * 64
seen: list[dict] = []


def fake_plugin(server: socket.socket) -> None:
    while True:
        try:
            conn, _ = server.accept()
        except OSError:
            return
        with conn:
            data = b""
            while not data.endswith(b"\n"):
                chunk = conn.recv(65536)
                if not chunk:
                    break
                data += chunk
            env = json.loads(data)
            seen.append(env)
            if env["auth_token"] != TOKEN:
                reply = {"id": env["id"], "ok": False, "error": {"code": "UNAUTHORIZED", "message": "bad token"}}
            elif env["command"] == "get_document_info":
                reply = {"id": env["id"], "ok": True, "data": {"title": "Torre A — federado.nwf", "models": 3}}
            elif env["command"] == "get_model_tree":
                nodes = [{"id": f"n{i}", "name": f"Parede {i}", "depth": 1} for i in range(2000)]
                reply = {"id": env["id"], "ok": True, "data": {"nodes": nodes, "truncated": False}}
            else:
                reply = {"id": env["id"], "ok": False, "error": {"code": "UNKNOWN_COMMAND", "message": env["command"]}}
            conn.sendall((json.dumps(reply, ensure_ascii=False) + "\n").encode("utf-8"))


class FakeServer:
    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def add_tool(self, fn, name, description, annotations, structured_output=None):
        self.tools[name] = fn


def text_of(result) -> str:
    return "".join(c.text for c in result.content)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="navis-mcp-test-"))
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen()
    threading.Thread(target=fake_plugin, args=(server,), daemon=True).start()
    (tmp / f"navis-2027-{os.getpid()}.json").write_text(json.dumps({
        "target_id": "navis-2027-test", "navisworks_year": 2027, "process_id": os.getpid(),
        "host_product": "Manage", "port": server.getsockname()[1], "auth_token": TOKEN,
        "document_title": "Torre A — federado.nwf", "document_path": None,
        # Newtonsoft's DateTimeOffset format: 7 fractional digits and an explicit offset.
        "last_heartbeat_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f") + "0+00:00",
    }), encoding="utf-8")

    cfg = NwdConfig(read_only=True, descriptor_dir=tmp, bake_dir=tmp / "baked", spill_dir=tmp / "spill")
    fake = FakeServer()
    names = register(fake, cfg)
    failures = []

    def check(ok: bool, label: str) -> None:
        print(("ok   " if ok else "FAIL ") + label)
        if not ok:
            failures.append(label)

    check(len(names) == 21, f"{len(names)} read-only tools registered")
    targets = json.loads(text_of(fake.tools["nwd_list_available_targets"]()))
    check(targets and targets[0]["TargetId"] == "navis-2027-test", f"descriptor discovered: {targets}")

    r = fake.tools["nwd_get_document_info"]()
    check(json.loads(text_of(r)) == {"title": "Torre A — federado.nwf", "models": 3}, "document info round-trip: " + text_of(r))
    env = seen[-1]
    check(env["command"] == "get_document_info" and env["auth_token"] == TOKEN and env["timeout_ms"] == 30000,
          "envelope fields: id/command/params/timeout_ms/auth_token")

    r = fake.tools["nwd_get_model_tree"](maxDepth=1, maxItems=2000, output="inline")
    body = json.loads(text_of(r))
    check("_response_warning" in body, f"inline >64 KiB carries _response_warning ({len(text_of(r))} bytes)")
    check(seen[-1]["params"] == {"max_depth": 1, "max_items": 2000}, "snake_case params sent to the plug-in")

    r = fake.tools["nwd_get_model_tree"](maxDepth=1, maxItems=2000, output="file")
    env = json.loads(text_of(r))
    check(env.get("output_mode") == "file" and Path(env["path"]).is_file() and env["format"] == "json",
          f"output=file spills to {env.get('path')}")

    r = fake.tools["nwd_get_item_properties"](itemId="x")
    check(r.is_error if hasattr(r, "is_error") else r.isError, "plug-in error -> isError: " + text_of(r))

    for f in tmp.glob("navis-*.json"):
        f.unlink()
    r = fake.tools["nwd_health_check"]()
    check("NO_TARGET" in text_of(r), "no descriptor -> NO_TARGET")
    server.close()
    print(f"\n{len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
