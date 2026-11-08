"""Loopback client for the nwd Navisworks plug-in (port of PluginClient.cs + TargetRegistry.cs).

Wire protocol, unchanged from nwd-mcp 1.0.0: the plug-in writes a descriptor
``navis-<year>-<pid>.json`` (port, auth token, heartbeat) under
``%LOCALAPPDATA%\\Bimwright\\nwd-mcp``. For each command the client opens a TCP
connection to 127.0.0.1:<port>, writes one JSON envelope plus ``\\n`` and reads
one JSON line back.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import NwdConfig

FILE_OPERATION_TIMEOUT_MS = 300_000
DESCRIPTOR_MAX_AGE_S = 120


class NwdGatewayError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Target:
    target_id: str
    navisworks_year: int
    process_id: int
    host_product: str
    port: int
    auth_token: str
    document_title: str | None
    document_path: str | None
    last_heartbeat: datetime

    def public(self) -> dict[str, Any]:
        # Same keys as the C# anonymous object the original server serialised.
        return {
            "TargetId": self.target_id,
            "NavisworksYear": self.navisworks_year,
            "DocumentTitle": self.document_title,
        }


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def list_targets(directory: Path) -> list[Target]:
    if not directory.is_dir():
        return []
    now = datetime.now(timezone.utc)
    live: list[Target] = []
    for file in directory.glob("*.json"):
        try:
            d = json.loads(file.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        if not isinstance(d, dict):
            continue
        if str(d.get("host_product", "")).lower() != "manage":
            continue
        try:
            year = int(d.get("navisworks_year", 0))
            pid = int(d.get("process_id", 0))
            port = int(d.get("port", 0))
        except (TypeError, ValueError):
            continue
        if not 2022 <= year <= 2027:
            continue
        beat = _parse_time(d.get("last_heartbeat_utc"))
        if beat is None or (now - beat).total_seconds() > DESCRIPTOR_MAX_AGE_S:
            continue
        if not _process_alive(pid):
            continue
        live.append(Target(
            target_id=str(d.get("target_id", "")),
            navisworks_year=year,
            process_id=pid,
            host_product=str(d.get("host_product", "")),
            port=port,
            auth_token=str(d.get("auth_token", "")),
            document_title=d.get("document_title"),
            document_path=d.get("document_path"),
            last_heartbeat=beat,
        ))
    live.sort(key=lambda t: t.last_heartbeat, reverse=True)
    return live


class PluginClient:
    def __init__(self, config: NwdConfig) -> None:
        self._config = config
        self._current: Target | None = None
        self._lock = threading.Lock()

    def list_targets(self) -> list[Target]:
        return list_targets(self._config.descriptor_dir)

    @property
    def current_target(self) -> Target | None:
        live = self.list_targets()
        with self._lock:
            if self._current is not None:
                for t in live:
                    if t.target_id == self._current.target_id:
                        self._current = t  # refresh port/token/title
                        return t
            chosen = None
            if self._config.target_id:
                chosen = next((t for t in live if t.target_id == self._config.target_id), None)
            self._current = chosen or (live[0] if live else None)
            return self._current

    def switch_target(self, target_id: str) -> bool:
        match = next((t for t in self.list_targets() if t.target_id == target_id), None)
        if match is None:
            return False
        with self._lock:
            self._current = match
        return True

    def send(self, command: str, params: dict[str, Any], timeout_ms: int | None = None) -> Any:
        wait_ms = max(timeout_ms or 0, self._config.timeout_ms)
        target = self.current_target
        if target is None:
            raise NwdGatewayError(
                "NO_TARGET",
                "No live Navisworks Manage target. Start Navisworks with the nwd plug-in loaded.",
            )
        envelope = {
            "id": str(uuid.uuid4()),
            "command": command,
            "params": params,
            "timeout_ms": wait_ms,
            "auth_token": target.auth_token,
        }
        try:
            sock = socket.create_connection(("127.0.0.1", target.port), timeout=self._config.timeout_ms / 1000)
        except socket.timeout as exc:
            raise NwdGatewayError("TIMEOUT", f"connect to target {target.target_id} timed out") from exc
        except OSError as exc:
            raise NwdGatewayError("TARGET_UNAVAILABLE", f"cannot reach target {target.target_id}: {exc}") from exc

        with sock:
            try:
                sock.sendall((json.dumps(envelope, ensure_ascii=False) + "\n").encode("utf-8"))
                sock.settimeout(wait_ms / 1000)
                chunks: list[bytes] = []
                size = 0
                while True:
                    chunk = sock.recv(65536)
                    if not chunk:
                        break
                    newline = chunk.find(b"\n")
                    if newline >= 0:
                        chunks.append(chunk[:newline])
                        size += newline
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > self._config.max_response_bytes:
                        break
            except socket.timeout as exc:
                raise NwdGatewayError("TIMEOUT", f"request {command} timed out after {wait_ms} ms") from exc
            except OSError as exc:
                raise NwdGatewayError("TARGET_UNAVAILABLE", f"connection to target lost: {exc}") from exc

        raw = b"".join(chunks)
        if not raw:
            raise NwdGatewayError("TARGET_UNAVAILABLE", "plug-in closed the connection")
        if len(raw) > self._config.max_response_bytes:
            raise NwdGatewayError(
                "RESPONSE_TOO_LARGE",
                f"Response {len(raw)}+ bytes exceeds the configured limit of "
                f"{self._config.max_response_bytes} bytes. Narrow the request and retry.",
            )
        try:
            result = json.loads(raw.decode("utf-8-sig"))
        except ValueError as exc:
            raise NwdGatewayError("API_ERROR", "unparseable response") from exc
        if not isinstance(result, dict):
            raise NwdGatewayError("API_ERROR", "unparseable response")
        if not result.get("ok"):
            error = result.get("error") or {}
            raise NwdGatewayError(error.get("code") or "API_ERROR", error.get("message") or "unknown error")
        return result.get("data")
