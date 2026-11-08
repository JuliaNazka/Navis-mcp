"""Response-size policy for nwd_* results.

Port of ResponseSizePolicy.cs, MutationResponseCompactor.cs, ResponseSpillWriter.cs
and ResponseBudget.cs: ``output=file`` and oversized arbitrary-code output spill
to a local file, then the remaining text is warned (64/256 KiB), rejected past
the 1 MiB budget, or, for a completed mutation, compacted into a summary.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

WARN_BYTES = 64 * 1024
STRONG_WARN_BYTES = 256 * 1024
BUDGET_BYTES = 1024 * 1024

PREVIEW_MAX_BYTES = 48 * 1024
SCHEMA_MAX_BYTES = 64 * 1024
MAX_RETAINED_FILES = 50
MAX_FILE_AGE_S = 24 * 3600

SEND_CODE_TOOL = "nwd_send_code"
RUN_BAKED_TOOL = "nwd_run_baked_tool"

OPT_IN_FORMATS = {
    "nwd_get_model_tree": "json",
    "nwd_batch_get_properties": "sqlite",
    "nwd_find_items_by_name": "ndjson",
    RUN_BAKED_TOOL: "auto",
}

_FALLBACK_HINT = "Retry with a smaller explicit ID list or a more selective filter supported by this tool."
_NARROWING_HINTS = {
    "nwd_get_model_tree": "Retry with a lower max_depth or max_items, or use output=file for the full tree.",
    "nwd_batch_get_properties": "Retry with fewer item_ids or a smaller max_items, or use output=file.",
    "nwd_find_items_by_name": "Retry with exact=true or a smaller max_items, or use output=file.",
    "nwd_find_items": "Retry with more selective filtersJson filters or a smaller max_items.",
    "nwd_get_item_properties": "Retry against a smaller item, or read properties for fewer items via nwd_batch_get_properties.",
    "nwd_get_current_selection": "Reduce the active selection in Navisworks and retry.",
    "nwd_get_selection_set_items": "Retry with a smaller selection or search set (set_id).",
    "nwd_execute_search_set": "Retry with a narrower search set (set_id) or select=false.",
    "nwd_list_viewpoints": "Retry after narrowing the saved-viewpoint set.",
    "nwd_list_recent_files": "Retry with a smaller limit.",
    SEND_CODE_TOOL: "Return less data from the script; output above the budget auto-spills to a file.",
    RUN_BAKED_TOOL: "Use output=file or narrow the baked tool's paramsJson; oversized inline output auto-spills.",
}


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def utf8_len(text: str) -> int:
    return len(text.encode("utf-8"))


def is_failure(text: str | None) -> bool:
    """Port of ToolErrorFlag.IsFailure: a JSON object whose ``ok`` is false."""
    if not text or not text.lstrip().startswith("{"):
        return False
    try:
        ok = json.loads(text).get("ok")
    except (ValueError, AttributeError):
        return False
    return ok is False


def invalid_output(output: str | None) -> str | None:
    if isinstance(output, str) and output.lower() in {"inline", "file"}:
        return None
    return dumps({"ok": False, "error": {
        "code": "INVALID_ARGUMENT", "message": f"output must be 'inline' or 'file' (got '{output}').",
    }})


def _try_parse(text: str) -> Any:
    stripped = (text or "").lstrip()
    if not stripped or stripped[0] not in "{[":
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


# ---------------------------------------------------------------- compactor

_MAX_SCALAR_CHARS = 2048
_MAX_PREVIEW_IDS = 20


def _is_scalar(v: Any) -> bool:
    return v is None or isinstance(v, (str, int, float, bool))


def _is_id_property(name: str) -> bool:
    return name.lower() == "id" or name.endswith("Id") or name.lower().endswith("_id")


def compact_mutation(data: Any, original_bytes: int) -> dict[str, Any]:
    source = data if isinstance(data, dict) else ({} if data is None else {"value": data})
    summary: dict[str, Any] = {}
    counts: dict[str, Any] = {}
    id_preview: dict[str, Any] = {}
    for name, value in source.items():
        if isinstance(value, list):
            counts[name] = len(value)
            ids = []
            for item in value[:_MAX_PREVIEW_IDS]:
                if isinstance(item, (str, int)) and not isinstance(item, bool):
                    ids.append(item)
                elif isinstance(item, dict):
                    key = next((k for k in item if _is_id_property(k)), None)
                    v = item.get(key) if key else None
                    if isinstance(v, (str, int)) and not isinstance(v, bool):
                        ids.append(v)
            if ids:
                id_preview[name] = ids
        elif isinstance(value, dict):
            small = {k: v for k, v in value.items()
                     if _is_scalar(v) and not (isinstance(v, str) and len(v) > _MAX_SCALAR_CHARS)}
            if small:
                summary[name] = small
        elif isinstance(value, str) and len(value) > _MAX_SCALAR_CHARS:
            summary[name + "_char_count"] = len(value)
            summary[name + "_preview"] = value[:_MAX_SCALAR_CHARS]
        else:
            summary[name] = value

    applied = not (source.get("dry_run") is True or source.get("dryRun") is True
                   or source.get("rolledBack") is True or source.get("success") is False
                   or source.get("ok") is False)
    return {
        "ok": True,
        "mutation_applied": applied,
        "response_compacted": True,
        "original_byte_count": original_bytes,
        "summary": summary,
        "collection_counts": counts,
        "id_preview": id_preview,
        "warning": "The command completed successfully, but oversized per-item response detail was compacted. "
                   "Inspect the summary before deciding whether another call is needed.",
    }


# ---------------------------------------------------------------- spill writer

def _sanitize_sql(value: str | None, fallback: str) -> str:
    out = "".join(c if (c.isalnum() or c == "_") else "_" for c in (value or ""))
    return out or fallback


def _take_prefix(text: str, max_bytes: int) -> tuple[str, bool]:
    data = text.encode("utf-8")
    if len(data) <= max_bytes:
        return text, False
    return data[:max_bytes].decode("utf-8", errors="ignore"), True


def _merge_columns(schema: dict[str, list[str]], path: str, names) -> None:
    columns = schema.setdefault(path, [])
    for n in names:
        if n not in columns:
            columns.append(n)


def _describe(token: Any, path: str, schema: dict[str, list[str]]) -> None:
    if isinstance(token, dict):
        _merge_columns(schema, path, token.keys())
        for k, v in token.items():
            if isinstance(v, (dict, list)):
                _describe(v, path + "_" + _sanitize_sql(k, "value"), schema)
    elif isinstance(token, list):
        objects = [i for i in token if isinstance(i, dict)]
        if objects:
            for obj in objects:
                _merge_columns(schema, path, obj.keys())
            for obj in objects:
                for k, v in obj.items():
                    if isinstance(v, (dict, list)):
                        _describe(v, path + "_" + _sanitize_sql(k, "value"), schema)
        else:
            _merge_columns(schema, path, ["value"])
    else:
        _merge_columns(schema, path, ["value"])


def _signature(token: Any) -> str:
    if isinstance(token, dict):
        return "object:" + "|".join(sorted(token.keys()))
    return type(token).__name__


def detect_format(token: Any) -> str:
    if isinstance(token, str):
        try:
            return detect_format(json.loads(token))
        except ValueError:
            return "text"
    if isinstance(token, dict):
        return "json"
    if not isinstance(token, list):
        return "text"
    if len(token) <= 1:
        return "ndjson"
    first = _signature(token[0])
    return "ndjson" if all(_signature(i) == first for i in token[1:]) else "json"


class _Table:
    def __init__(self, name: str) -> None:
        self.name = name
        self.columns: list[str] = []
        self.rows: list[dict[str, Any]] = []

    def add(self, row: dict[str, Any]) -> None:
        for c in row:
            if c not in self.columns:
                self.columns.append(c)
        self.rows.append(row)


def _add_column(row: dict[str, Any], raw: str, value: Any) -> None:
    base = _sanitize_sql(raw, "value")
    name, n = base, 2
    while name in row:
        name, n = f"{base}_{n}", n + 1
    row[name] = value


def _flatten(row: dict[str, Any], prefix: str, value: dict[str, Any]) -> None:
    for k, v in value.items():
        name = prefix + "_" + k
        if isinstance(v, dict):
            _flatten(row, name, v)
        elif isinstance(v, list):
            _add_column(row, name, dumps(v))
        else:
            _add_column(row, name, v)


def _collect(tables: list[_Table], name: str, items: list[Any], parent: str | None, parent_row: int | None) -> None:
    table = next((t for t in tables if t.name == name), None)
    if table is None:
        table = _Table(name)
        tables.append(table)
    for item in items:
        row: dict[str, Any] = {}
        if parent is not None:
            row["_parent_table"] = parent
            row["_parent_row"] = parent_row
        nested: list[tuple[str, list[Any]]] = []
        if isinstance(item, dict):
            for k, v in item.items():
                if isinstance(v, list):
                    nested.append((k, v))
                elif isinstance(v, dict):
                    _flatten(row, k, v)
                else:
                    _add_column(row, k, v)
        else:
            row["value"] = item
        index = len(table.rows)
        table.add(row)
        for k, v in nested:
            _collect(tables, _sanitize_sql(name + "_" + k, "records"), v, table.name, index)


def _relationalize(token: Any) -> list[_Table]:
    tables: list[_Table] = []
    if isinstance(token, dict):
        root_row: dict[str, Any] = {}
        for k, v in token.items():
            if isinstance(v, list):
                _collect(tables, _sanitize_sql(k, "records"), v, None, None)
            elif isinstance(v, dict):
                _flatten(root_row, k, v)
            else:
                _add_column(root_row, k, v)
        if root_row:
            root = _Table("_root")
            root.add(root_row)
            tables.insert(0, root)
    elif isinstance(token, list):
        _collect(tables, "records", token, None, None)
    else:
        root = _Table("_root")
        root.add({"value": token})
        tables.append(root)
    return tables or [_Table("_root")]


def _sql_type(table: _Table, column: str) -> str:
    real = False
    for row in table.rows:
        v = row.get(column)
        if v is None or isinstance(v, (bool, int)):
            continue
        if isinstance(v, float):
            real = True
            continue
        return "TEXT"
    return "REAL" if real else "INTEGER"


def _sql_value(v: Any) -> Any:
    if v is None or isinstance(v, (int, float, str)):
        return int(v) if isinstance(v, bool) else v
    return dumps(v)


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


class SpillWriter:
    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    def write(self, tool: str, payload: Any, fmt: str) -> dict[str, Any]:
        self.directory.mkdir(parents=True, exist_ok=True)
        token = payload
        if fmt == "auto":
            fmt = detect_format(token)
            if isinstance(token, str) and fmt != "text":
                token = json.loads(token)
        if fmt == "json":
            schema: dict[str, list[str]] = {}
            _describe(token, "root", schema)
            return self._text(tool, dumps(token), ".json", "json",
                              len(token) if isinstance(token, list) else 1, schema)
        if fmt == "ndjson":
            return self._ndjson(tool, token)
        if fmt == "sqlite":
            return self._sqlite(tool, token)
        if fmt == "text":
            return self._text(tool, token if isinstance(token, str) else dumps(token), ".txt", "text", 1,
                              {"root": ["text"]})
        raise ValueError(f"Spill format is not implemented: {fmt}")

    def _path(self, tool: str, ext: str) -> Path:
        safe = "".join(c if (c.isalnum() or c in "_-") else "_" for c in (tool or "response"))[:48] or "response"
        utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")[:-3] + "Z"
        digest = hashlib.sha256(f"{safe}|{utc}|{uuid.uuid4().hex}".encode()).hexdigest()[:8]
        return self.directory / f"{safe}_{os.getpid()}_{utc}_{digest}{ext}"

    def _ndjson(self, tool: str, token: Any) -> dict[str, Any]:
        lines: list[str] = []
        schema: dict[str, Any] = {}
        if isinstance(token, list):
            lines = [dumps(i) for i in token]
            schema["records"] = sorted({k for i in token if isinstance(i, dict) for k in i})
        elif isinstance(token, dict):
            root = {"_record_type": "root", **{k: v for k, v in token.items() if not isinstance(v, list)}}
            if len(root) > 1:
                lines.append(dumps(root))
                schema["_root"] = list(root.keys())
            for k, v in token.items():
                if not isinstance(v, list):
                    continue
                schema[k] = sorted({kk for i in v if isinstance(i, dict) for kk in i})
                for idx, item in enumerate(v):
                    lines.append(dumps({"_record_type": "collection_item", "_collection": k, "_index": idx, "data": item}))
        else:
            lines.append(dumps({"_record_type": "value", "data": token}))
            schema["records"] = ["data"]
        content = ("\n".join(lines) + "\n") if lines else ""
        return self._text(tool, content, ".ndjson", "ndjson", len(lines), schema)

    def _sqlite(self, tool: str, token: Any) -> dict[str, Any]:
        tables = _relationalize(token)
        path = self._path(tool, ".sqlite")
        with sqlite3.connect(path) as con:
            for t in tables:
                cols = t.columns or ["_row"]
                con.execute(f"CREATE TABLE {_quote(t.name)} ("
                            + ", ".join(f"{_quote(c)} {_sql_type(t, c)}" for c in cols) + ")")
                if t.rows:
                    con.executemany(
                        f"INSERT INTO {_quote(t.name)} ({', '.join(_quote(c) for c in cols)}) "
                        f"VALUES ({', '.join('?' for _ in cols)})",
                        [[_sql_value(r.get(c)) for c in cols] for r in t.rows],
                    )
        con.close()
        self._cleanup(path)
        schema = {t.name: (t.columns or ["_row"]) for t in tables}
        records = sum(len(t.rows) for t in tables if t.name != "_root")
        preview_obj = {t.name: [{c: r.get(c) for c in t.columns} for r in t.rows[:20]] for t in tables}
        preview, truncated = _take_prefix(dumps(preview_obj), PREVIEW_MAX_BYTES)
        return self._envelope(path, "sqlite", records, schema, preview, truncated)

    def _text(self, tool: str, content: str, ext: str, fmt: str, records: int, schema: dict[str, Any]) -> dict[str, Any]:
        path = self._path(tool, ext)
        path.write_text(content, encoding="utf-8")
        self._cleanup(path)
        preview, truncated = _take_prefix(content, PREVIEW_MAX_BYTES)
        return self._envelope(path, fmt, records, schema, preview, truncated)

    def _envelope(self, path: Path, fmt: str, records: int, schema: dict[str, Any],
                  preview: str, preview_truncated: bool) -> dict[str, Any]:
        schema_truncated = utf8_len(dumps(schema)) > SCHEMA_MAX_BYTES
        if schema_truncated:
            schema = {"_truncated": "Schema exceeded the envelope limit; inspect the local artifact directly."}
        return {
            "ok": True,
            "output_mode": "file",
            "path": str(path),
            "format": fmt,
            "byte_count": path.stat().st_size,
            "schema": schema,
            "schema_truncated": schema_truncated,
            "record_count": records,
            "preview": preview,
            "preview_truncated": preview_truncated,
            "note": "Local same-machine file. Query with SQL/jq or another local tool; "
                    "do not re-call this tool for the full dataset.",
        }

    def _cleanup(self, keep: Path) -> None:
        try:
            files = [p for p in self.directory.iterdir() if p.is_file()]
        except OSError:
            return
        cutoff = time.time() - MAX_FILE_AGE_S
        retained = []
        for p in files:
            try:
                if p != keep and p.stat().st_mtime < cutoff:
                    p.unlink()
                else:
                    retained.append(p)
            except OSError:
                pass
        retained.sort(key=lambda p: (p == keep, p.stat().st_mtime if p.exists() else 0, p.name), reverse=True)
        for p in retained[MAX_RETAINED_FILES:]:
            try:
                p.unlink()
            except OSError:
                pass


# ---------------------------------------------------------------- budget

class ResponseBudget:
    def __init__(self, writer: SpillWriter, write_tools: set[str]) -> None:
        self._writer = writer
        self._write_tools = write_tools

    @staticmethod
    def _indeterminate(tool: str) -> bool:
        return tool in (SEND_CODE_TOOL, RUN_BAKED_TOOL)

    def apply(self, tool: str, arguments: dict[str, Any], text: str) -> str:
        failure = is_failure(text)
        text = self._spill(tool, arguments, text, failure)
        size = utf8_len(text)
        hint = _NARROWING_HINTS.get(tool, _FALLBACK_HINT)
        if size > BUDGET_BYTES:
            if tool in self._write_tools and not failure:
                compacted = compact_mutation(_try_parse(text) if _try_parse(text) is not None else text, size)
                if self._indeterminate(tool):
                    compacted["mutation_applied"] = None
                out = dumps(compacted)
                if utf8_len(out) <= BUDGET_BYTES:
                    return out
                return dumps({"ok": True, "mutation_applied": compacted["mutation_applied"],
                              "response_compacted": True, "original_byte_count": size,
                              "warning": "Command completed successfully; oversized response detail was omitted. "
                                         "Inspect the summary before another call."})
            return dumps({"ok": False, "error": {
                "code": "RESPONSE_TOO_LARGE",
                "message": f"Response exceeded the {BUDGET_BYTES}-byte response budget ({size} bytes) for {tool}. "
                           f"{hint} Do not retry the same unscoped request.",
            }})
        if size >= WARN_BYTES:
            warning = (f"Oversized response strong warning: {size} bytes. {hint}" if size > STRONG_WARN_BYTES
                       else f"Oversized response warning: {size} bytes. Consider narrowing the next request. {hint}")
            parsed = _try_parse(text)
            if isinstance(parsed, dict):
                parsed["_response_warning"] = warning
                candidate = dumps(parsed)
                if utf8_len(candidate) <= BUDGET_BYTES:
                    return candidate
        return text

    def _spill(self, tool: str, arguments: dict[str, Any], text: str, failure: bool) -> str:
        if failure or (tool not in OPT_IN_FORMATS and not self._indeterminate(tool)):
            return text
        data = _try_parse(text)
        if data is None:
            return text
        original = utf8_len(text)
        automatic = False
        output = arguments.get("output")
        if tool in OPT_IN_FORMATS and isinstance(output, str) and output.lower() == "file":
            fmt = OPT_IN_FORMATS[tool]
        elif self._indeterminate(tool) and original > BUDGET_BYTES:
            fmt, automatic = "auto", True
        else:
            return text
        try:
            env = self._writer.write(tool, data, fmt)
            env["tool"] = tool
            env["automatic"] = automatic
            env["original_response_byte_count"] = original
            if automatic:
                env["note"] = ("Oversized arbitrary output auto-spilled to a local same-machine file. "
                               "Query it locally; do not re-run the executed command for the full result.")
            if self._indeterminate(tool):
                env["summary"] = compact_mutation(data, original)["summary"]
            out = dumps(env)
            if utf8_len(out) > BUDGET_BYTES:
                env["preview"] = ""
                env["preview_truncated"] = True
                env["schema"] = {"_truncated": "Schema omitted from envelope to preserve the response budget; "
                                               "inspect the local artifact directly."}
                env["schema_truncated"] = True
                out = dumps(env)
            return out
        except Exception as exc:  # noqa: BLE001 - reported to the caller
            return dumps({
                "ok": False,
                "error": {"code": "SPILL_FAILED", "message": "Failed to write spill file: " + str(exc)},
                "operation_completed": True,
                "mutation_applied": None if self._indeterminate(tool) else (tool in self._write_tools),
                "original_response_byte_count": original,
                "note": "The command already completed but its oversized output could not be persisted. "
                        "Do not blindly retry a mutation.",
            })
