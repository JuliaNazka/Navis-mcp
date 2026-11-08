"""Navis-mcp: one MCP server with NavisCoord (navis_*) and the nwd-mcp port (nwd_*).

Read-only is ONE switch for both halves and is ON unless explicitly turned off:

* ``--allow-write`` or ``NAVIS_MCP_READ_ONLY=0`` turns writes on;
* ``--read-only`` or ``NAVIS_MCP_READ_ONLY=1`` (the default) keeps them off.

In read-only mode NavisCoord's bridge refuses every write route
(``NAVISCOORD_READ_ONLY=1``), the save/close/exit tools are not even listed,
and the write-capable nwd toolsets are not registered.
"""
from __future__ import annotations

import os
import sys
from typing import Any

NAVIS_MCP_VERSION = "1.0.0"

# Listed only when writes are allowed: they save, close the document or quit Navisworks.
HIDDEN_WHEN_READ_ONLY = ("navis_save", "navis_save_as", "navis_close_document", "navis_exit")

INSTRUCTIONS = (
    f"Navis-mcp {NAVIS_MCP_VERSION}: one MCP server for Autodesk Navisworks Manage 2027.\n"
    "- navis_* (from NavisCoord): clash coordination — ranking, grouping, root causes, work plan, "
    "reports, snapshots and comparison between deliveries. Call navis_health first.\n"
    "- nwd_* (port of nwd-mcp): general model queries — document, tree, properties, search, sets, "
    "viewpoints. Call nwd_health_check first.\n"
    "Both need Navisworks Manage 2027 open with the Navis-mcp add-ins loaded."
)


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


def configure(mcp: Any, argv: list[str] | None = None) -> dict[str, Any]:
    from .nwd import NwdConfig, register
    from .nwd.tools import INSTRUCTIONS as NWD_INSTRUCTIONS

    argv = list(sys.argv[1:] if argv is None else argv)
    read_only = read_only_from(argv)
    if read_only:
        os.environ["NAVISCOORD_READ_ONLY"] = "1"
    else:
        os.environ.pop("NAVISCOORD_READ_ONLY", None)

    hidden = [n for n in HIDDEN_WHEN_READ_ONLY if read_only and _remove_tool(mcp, n)]
    nwd_tools = register(mcp, NwdConfig.from_env(read_only))

    mode = ("READ-ONLY: nothing is changed or saved; save/close/exit are hidden."
            if read_only else "WRITES ALLOWED: confirm with the user before changing or saving the model.")
    instructions = f"{INSTRUCTIONS}\nMode: {mode}\n\n{NWD_INSTRUCTIONS}"
    low = getattr(mcp, "_lowlevel_server", None) or getattr(mcp, "_mcp_server", None)
    for target in (low, mcp):
        if target is not None and hasattr(target, "instructions"):
            try:
                target.instructions = instructions
                break
            except (AttributeError, TypeError):
                continue

    summary = {"version": NAVIS_MCP_VERSION, "read_only": read_only, "hidden": hidden, "nwd_tools": len(nwd_tools)}
    print(f"[navis-mcp] {summary}", file=sys.stderr, flush=True)
    return summary
