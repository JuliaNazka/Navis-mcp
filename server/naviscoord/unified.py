"""Navis-mcp: one MCP server with NavisCoord (navis_*) and the nwd-mcp port (nwd_*).

Three switches, all decided when the server starts:

* **Read-only** (default ON): ``--read-only`` / ``NAVIS_MCP_READ_ONLY=1``.
  NavisCoord's bridge refuses every write route (``NAVISCOORD_READ_ONLY=1``),
  save/close/exit are not listed, and the write-capable nwd toolsets are not
  registered.
* **Write mode**: ``--allow-write`` / ``NAVIS_MCP_READ_ONLY=0``. Saving a COPY,
  clash statuses, creating and running tests, colouring, closing the document
  and quitting Navisworks become available, plus the nwd write tools.
  Two things stay locked even then, each behind its own extra switch:
* **Overwrite** (``--allow-overwrite`` / ``NAVIS_MCP_ALLOW_OVERWRITE=1``):
  without it ``navis_save`` (save in place) is not listed, ``navis_save_as``
  refuses ``overwrite=true``, and close/exit refuse ``disposition="save"``,
  which also saves in place. Rule of the team that uses this server: never
  save over a file; a new round is a new revision (R00 -> R01).
* **Arbitrary code** (``--allow-send-code`` / ``NAVIS_MCP_SEND_CODE=1``):
  ``nwd_send_code`` runs any C# inside Navisworks, so it stays off unless asked.
"""
from __future__ import annotations

import functools
import os
import sys
from typing import Any, Callable

NAVIS_MCP_VERSION = "1.1.0"

# Listed only when writes are allowed: they save, close the document or quit Navisworks.
HIDDEN_WHEN_READ_ONLY = ("navis_save", "navis_save_as", "navis_close_document", "navis_exit")
# Saves the open file in place: listed only with --allow-overwrite.
HIDDEN_WITHOUT_OVERWRITE = ("navis_save",)

INSTRUCTIONS = (
    f"Navis-mcp {NAVIS_MCP_VERSION}: one MCP server for Autodesk Navisworks Manage 2025 and 2027.\n"
    "- navis_* (from NavisCoord): clash coordination — ranking, grouping, root causes, work plan, "
    "reports, snapshots and comparison between deliveries. Call navis_health first.\n"
    "- nwd_* (port of nwd-mcp): general model queries — document, tree, properties, search, sets, "
    "viewpoints. Call nwd_health_check first.\n"
    "Both need Navisworks Manage open with the Navis-mcp add-ins loaded."
)

WRITE_GUIDE = (
    "Write workflow: every document write needs expected_document_fingerprint (read it from navis_health) "
    "and most writes default to dry_run=true: show the plan to the user, then repeat with dry_run=false. "
    "Create tests: navis_propose_disciplines -> navis_set_disciplines -> navis_configure (sets + clash matrix) "
    "or navis_build_clash_matrix. Run: navis_run (async; poll navis_job_status) or navis_run_tests. "
    "Statuses and colours work on issues from navis_analyze: navis_set_status, navis_color_by_priority, "
    "navis_reset_appearance. Save: navis_save_as to a NEW file name (next revision, e.g. ...-R01.nwd) in the "
    "open document's folder or an allowed root (navis_output_policy). Close: navis_close_document / navis_exit "
    "with disposition 'require_clean' (after saving a copy) or 'discard' (only when the user says to drop the "
    "changes); both default to dry_run=true."
)


def _flag(argv: list[str], cli: str, env: str, default: bool) -> bool:
    if cli in argv:
        return True
    value = os.environ.get(env, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def read_only_from(argv: list[str]) -> bool:
    if "--allow-write" in argv:
        return False
    if "--read-only" in argv:
        return True
    value = os.environ.get("NAVIS_MCP_READ_ONLY", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _remove_tool(mcp: Any, name: str) -> bool:
    try:
        mcp.remove_tool(name)
        return True
    except Exception:  # noqa: BLE001 - older mcp without remove_tool, or already absent
        tools = getattr(getattr(mcp, "_tool_manager", None), "_tools", None)
        if isinstance(tools, dict) and name in tools:
            del tools[name]
            return True
    return False


def _tool(mcp: Any, name: str) -> Any:
    manager = getattr(mcp, "_tool_manager", None)
    getter = getattr(manager, "get_tool", None)
    return getter(name) if getter else None


def _guard_tool(mcp: Any, name: str, check: Callable[[dict[str, Any]], dict[str, Any] | None]) -> bool:
    """Put a policy check in front of a registered tool, keeping its name, schema and description.

    The tool's argument model was built from the original signature, so only
    the callable behind it is swapped: arguments still arrive validated, as
    keyword arguments, and a refusal comes back as a normal result.
    """
    tool = _tool(mcp, name)
    if tool is None or not hasattr(tool, "fn"):
        return False
    original = tool.fn

    @functools.wraps(original)
    def guarded(*args: Any, **kwargs: Any) -> Any:
        refusal = check(kwargs)
        return refusal if refusal is not None else original(*args, **kwargs)

    try:
        tool.fn = guarded
    except (TypeError, ValueError, AttributeError):
        object.__setattr__(tool, "fn", guarded)
    return True


def _refusal(detail: str) -> dict[str, Any]:
    return {
        "error": "sobrescrita_bloqueada",
        "detail": detail,
        "hint": "Salve uma cópia com navis_save_as num nome novo (próxima revisão, ex.: -R01). "
                "Para liberar a sobrescrita, o servidor precisa subir com --allow-overwrite.",
    }


def configure(mcp: Any, argv: list[str] | None = None) -> dict[str, Any]:
    from .nwd import NwdConfig, register
    from .nwd.tools import INSTRUCTIONS as NWD_INSTRUCTIONS

    argv = list(sys.argv[1:] if argv is None else argv)
    read_only = read_only_from(argv)
    allow_overwrite = not read_only and _flag(argv, "--allow-overwrite", "NAVIS_MCP_ALLOW_OVERWRITE", False)
    allow_send_code = not read_only and _flag(argv, "--allow-send-code", "NAVIS_MCP_SEND_CODE", False)

    if read_only:
        os.environ["NAVISCOORD_READ_ONLY"] = "1"
    else:
        os.environ.pop("NAVISCOORD_READ_ONLY", None)

    hidden: list[str] = []
    guarded: list[str] = []
    if read_only:
        hidden = [n for n in HIDDEN_WHEN_READ_ONLY if _remove_tool(mcp, n)]
    elif not allow_overwrite:
        hidden = [n for n in HIDDEN_WITHOUT_OVERWRITE if _remove_tool(mcp, n)]

        def no_overwrite(kwargs: dict[str, Any]) -> dict[str, Any] | None:
            if kwargs.get("overwrite"):
                return _refusal("overwrite=true sobrescreveria um arquivo que já existe.")
            return None

        def no_save_in_place(kwargs: dict[str, Any]) -> dict[str, Any] | None:
            if str(kwargs.get("disposition", "")).strip().lower() == "save":
                return _refusal("disposition='save' grava por cima do arquivo aberto antes de fechar. "
                                "Use 'require_clean' depois de salvar uma cópia, ou 'discard' se o "
                                "usuário mandou descartar.")
            return None

        for name, check in (("navis_save_as", no_overwrite), ("navis_save_export", no_overwrite),
                            ("navis_snapshot", no_overwrite), ("navis_close_document", no_save_in_place),
                            ("navis_exit", no_save_in_place)):
            if _guard_tool(mcp, name, check):
                guarded.append(name)

    nwd_config = NwdConfig.from_env(read_only)
    nwd_config.enable_send_code = allow_send_code
    nwd_tools = register(mcp, nwd_config)

    if read_only:
        mode = "READ-ONLY: nothing is changed or saved; save/close/exit are hidden."
    else:
        mode = ("WRITES ALLOWED: confirm with the user before changing, saving or closing anything. "
                + ("Overwriting files is ALLOWED. " if allow_overwrite
                   else "Overwriting is BLOCKED: save copies under a new name. ")
                + ("nwd_send_code is ON." if allow_send_code else "nwd_send_code is OFF."))
    instructions = f"{INSTRUCTIONS}\nMode: {mode}\n"
    if not read_only:
        instructions += f"\n{WRITE_GUIDE}\n"
    instructions += f"\n{NWD_INSTRUCTIONS}"
    low = getattr(mcp, "_lowlevel_server", None) or getattr(mcp, "_mcp_server", None)
    for target in (low, mcp):
        if target is not None and hasattr(target, "instructions"):
            try:
                target.instructions = instructions
                break
            except (AttributeError, TypeError):
                continue

    summary = {
        "version": NAVIS_MCP_VERSION,
        "read_only": read_only,
        "allow_overwrite": allow_overwrite,
        "send_code": allow_send_code,
        "hidden": hidden,
        "guarded": guarded,
        "nwd_tools": len(nwd_tools),
    }
    print(f"[navis-mcp] {summary}", file=sys.stderr, flush=True)
    return summary
