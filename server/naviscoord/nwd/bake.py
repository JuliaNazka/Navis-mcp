"""ToolBaker storage and handlers (port of Bake/*.cs, Handlers/*.cs and the
ToolBaker/Security helpers the server used).

Same SQLite file as nwd-mcp (``%LOCALAPPDATA%\\Bimwright\\nwd-mcp\\baked\\bake.db``),
same schema, so tools baked with the original server keep working.
"""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .budget import dumps

OPEN, ACCEPTED, DISMISSED, ARCHIVED = "open", "accepted", "dismissed", "archived"
_TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]{2,63}$")

_REGISTRY_SQL = """
CREATE TABLE IF NOT EXISTS registry(
    name TEXT PRIMARY KEY,
    description TEXT NOT NULL,
    source TEXT NOT NULL,
    params_schema TEXT NOT NULL,
    compat_map TEXT NOT NULL,
    source_code TEXT NULL,
    handler_tool TEXT NULL,
    fixed_args TEXT NULL,
    sequence_json TEXT NULL,
    created_from_suggestion_id TEXT NULL,
    reviewed_by_user INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    last_used_at TEXT NULL,
    usage_count INTEGER NOT NULL DEFAULT 0,
    failure_rate REAL NOT NULL DEFAULT 0,
    lifecycle_state TEXT NOT NULL DEFAULT 'accepted',
    version_history_blob TEXT NOT NULL DEFAULT '[]'
)"""
_SUGGESTIONS_SQL = """
CREATE TABLE IF NOT EXISTS suggestions(
    id TEXT PRIMARY KEY,
    cluster_key TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    state TEXT NOT NULL,
    score REAL NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    snooze_until TEXT NULL,
    never_reason TEXT NULL,
    payload_json TEXT NOT NULL,
    version_history_blob TEXT NOT NULL DEFAULT '[]'
)"""
_USAGE_SQL = """
CREATE TABLE IF NOT EXISTS usage_events(
    timestamp TEXT NOT NULL,
    session_id TEXT NOT NULL,
    tool TEXT NOT NULL,
    params_hash TEXT NOT NULL,
    ok INTEGER NOT NULL,
    duration_ms INTEGER NOT NULL
)"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _record_json(row: dict[str, Any]) -> dict[str, Any]:
    """BakedToolRecord as Newtonsoft's JObject.FromObject serialised it (PascalCase)."""
    return {
        "Name": row.get("name") or "",
        "Description": row.get("description") or "",
        "Source": row.get("source") or "",
        "ParamsSchema": row.get("params_schema") or "{}",
        "CompatMap": row.get("compat_map") or "{}",
        "DllBytes": None,
        "SourceCode": row.get("source_code") or "",
        "HandlerTool": row.get("handler_tool") or "",
        "FixedArgs": row.get("fixed_args") or "{}",
        "Sequence": row.get("sequence_json") or "[]",
        "CreatedFromSuggestionId": row.get("created_from_suggestion_id"),
        "ReviewedByUser": bool(row.get("reviewed_by_user")),
        "CreatedAt": row.get("created_at") or "",
        "LastUsedAt": row.get("last_used_at"),
        "UsageCount": int(row.get("usage_count") or 0),
        "FailureRate": float(row.get("failure_rate") or 0.0),
        "LifecycleState": row.get("lifecycle_state") or "accepted",
        "VersionHistoryBlob": row.get("version_history_blob") or "[]",
    }


class BakeDb:
    def __init__(self, directory: Path) -> None:
        self.path = Path(directory) / "bake.db"

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    def migrate(self) -> "BakeDb":
        with closing(self._connect()) as con, con:
            con.execute(_REGISTRY_SQL)
            con.execute(_SUGGESTIONS_SQL)
            con.execute(_USAGE_SQL)
        return self

    def registry(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as con:
            return [dict(r) for r in con.execute("SELECT * FROM registry ORDER BY name")]

    def registry_record(self, name: str) -> dict[str, Any] | None:
        with closing(self._connect()) as con:
            row = con.execute("SELECT * FROM registry WHERE name = ?", (name or "",)).fetchone()
            return dict(row) if row else None

    def insert_registry(self, rec: dict[str, Any]) -> bool:
        cols = ("name", "description", "source", "params_schema", "compat_map", "source_code", "handler_tool",
                "fixed_args", "sequence_json", "created_from_suggestion_id", "reviewed_by_user", "created_at",
                "last_used_at", "usage_count", "failure_rate", "lifecycle_state", "version_history_blob")
        with closing(self._connect()) as con, con:
            cur = con.execute(
                f"INSERT OR IGNORE INTO registry({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
                [rec.get(c) for c in cols])
            return cur.rowcount == 1

    def suggestions(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as con:
            return [dict(r) for r in con.execute("SELECT * FROM suggestions ORDER BY created_at DESC, id")]

    def suggestion(self, sid: str) -> dict[str, Any] | None:
        with closing(self._connect()) as con:
            row = con.execute("SELECT * FROM suggestions WHERE id = ?", (sid or "",)).fetchone()
            return dict(row) if row else None

    def set_suggestion_state(self, sid: str, state: str) -> bool:
        with closing(self._connect()) as con, con:
            cur = con.execute("UPDATE suggestions SET state = ?, updated_at = ? WHERE id = ?",
                              (state or OPEN, _now(), sid or ""))
            return cur.rowcount == 1


# ---------------------------------------------------------------- handlers

def _payload(text: str | None) -> dict[str, Any]:
    try:
        value = json.loads(text or "{}")
        return value if isinstance(value, dict) else {}
    except ValueError:
        return {}


def list_baked_tools(db: BakeDb) -> str:
    tools = [{
        "name": r["name"],
        "description": r["description"],
        "source": r["source"],
        "handler_tool": r.get("handler_tool"),
        "usage_count": r.get("usage_count", 0),
        "created_at": r.get("created_at"),
    } for r in db.registry()]
    return dumps({"tools": tools})


def list_suggestions(db: BakeDb) -> str:
    items = [{
        "id": s["id"],
        "title": s["title"],
        "source": s["source"],
        "score": s["score"],
        "state": s["state"],
        "created_at": s.get("created_at"),
        "output_choices": _payload(s.get("payload_json")).get("output_choices") or ["mcp_only"],
    } for s in db.suggestions() if s["state"] != ARCHIVED]
    return dumps({"suggestions": items})


def issue_draft(db: BakeDb, sid: str) -> str:
    s = db.suggestion(sid)
    if s is None:
        return dumps({"ok": False, "error_code": "not_found", "message": "Bake suggestion was not found."})
    title = "[ToolBaker] " + (s.get("title") or s["id"])
    body = "\n".join([
        "## Summary",
        s.get("description") or "Repeated Navisworks workflow detected.",
        "",
        "## Suggestion",
        f"- id: `{s['id']}`",
        f"- source: `{s['source']}`",
        f"- score: `{s['score']}`",
        "",
        "## Payload",
        "```json",
        s.get("payload_json") or "{}",
        "```",
    ])
    return dumps({"ok": True, "issue": {"title": title, "body": body}})


def dismiss(db: BakeDb, sid: str) -> str:
    if db.suggestion(sid) is None:
        return dumps({"ok": False, "error_code": "not_found", "message": "Bake suggestion was not found."})
    db.set_suggestion_state(sid, DISMISSED)
    return dumps({"ok": True, "id": sid, "state": DISMISSED})


_ASSIGNMENT_SECRET = re.compile(r"(?i)\b(api[_-]?key|auth[_-]?token|password|secret|token)\b\s*=\s*[\"'][^\"']+[\"']")
_TOKEN_SHAPES = re.compile(r"(gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,}|xox[abpr]-[A-Za-z0-9-]{10,}"
                           r"|AKIA[0-9A-Z]{16}|(?i:bearer)\s+[A-Za-z0-9._~+/=-]{20,})")


def redact_source(source: str) -> str:
    if not source:
        return source
    source = _ASSIGNMENT_SECRET.sub(lambda m: f'{m.group(1)} = "<secret>"', source)
    return _TOKEN_SHAPES.sub("<secret>", source)


def _json_type(kind: str) -> str:
    return {"number": "number", "bool": "boolean", "array": "array", "object": "object"}.get(kind, "string")


def _default(kind: str) -> Any:
    return {"number": 0, "bool": False, "array": [], "object": {}}.get(kind, "")


def accept_suggestion(db: BakeDb, sid: str, name: str,
                      plugin_apply: Callable[[dict[str, Any]], dict[str, Any]]) -> str:
    def failure(code: str, message: str) -> str:
        return dumps({"ok": False, "error_code": code, "message": message})

    s = db.suggestion(sid)
    if s is None:
        return failure("not_found", "Bake suggestion was not found.")
    if not name or not _TOOL_NAME.match(name):
        return failure("invalid_name", "Tool name must use snake_case and start with a letter.")
    if any(r["name"] == name for r in db.registry()):
        return failure("duplicate_tool_name", "A baked tool with this name already exists.")

    payload = _payload(s.get("payload_json"))
    source = s.get("source") or "preset"
    handler = payload.get("tool") or ""
    sequence = payload.get("sequence") if isinstance(payload.get("sequence"), list) else None
    kinds = (payload.get("sample") or {}).get("parameter_kinds") or {}
    schema = dumps({"type": "object", "properties": {k: {"type": _json_type(str(v))} for k, v in kinds.items()}})
    fixed = payload.get("fixed_args") if isinstance(payload.get("fixed_args"), dict) else \
        {k: _default(str(v)) for k, v in kinds.items()}
    seq = sequence if sequence is not None else [handler]
    request = {
        "suggestion_id": s["id"],
        "tool_name": name,
        "description": s.get("description") or s.get("title") or name,
        "source": source,
        "output_choice": "mcp_only",
        "params_schema": schema,
        "handler_tool": handler,
        "fixed_args": fixed,
        "sequence": seq,
        "source_code": dumps({"kind": "macro", "sequence": [x for x in seq if isinstance(x, str)]}) if source == "macro"
        else dumps({"kind": "preset", "handler_tool": handler, "fixed_args": fixed}),
        "created_from_suggestion_id": s["id"],
    }
    try:
        result = plugin_apply(request) or {}
    except Exception as exc:  # noqa: BLE001
        return failure("plugin_apply_failed", str(exc))
    if result.get("success") is not True:
        return failure(result.get("error_code") or "plugin_apply_failed",
                       result.get("message") or "Plugin apply_bake failed.")
    if source not in ("preset", "macro") or not (handler or seq):
        return failure("registry_insert_failed", "Baked tool record is incomplete.")

    record = {
        "name": name,
        "description": result.get("description") or request["description"],
        "source": source,
        "params_schema": result.get("params_schema") or schema,
        "compat_map": "{}",
        "source_code": redact_source(result.get("source_code") or request["source_code"]),
        "handler_tool": handler,
        "fixed_args": dumps(fixed),
        "sequence_json": dumps(seq),
        "created_from_suggestion_id": s["id"],
        "reviewed_by_user": 1,
        "created_at": _now(),
        "last_used_at": None,
        "usage_count": 0,
        "failure_rate": 0.0,
        "lifecycle_state": "accepted",
        "version_history_blob": "[]",
    }
    if not db.insert_registry(record):
        return failure("registry_insert_failed", "A baked tool with this name already exists.")
    db.set_suggestion_state(s["id"], ACCEPTED)
    return dumps({"ok": True, "tool_name": name, "state": ACCEPTED})


def record_for_plugin(row: dict[str, Any]) -> dict[str, Any]:
    return _record_json(row)
