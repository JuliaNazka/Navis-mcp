"""Registration of the nwd_* tools on the Navis-mcp server.

One function per tool, with the same names, parameter names (camelCase, as
the C# SDK published them), defaults, descriptions and annotations as
nwd-mcp 1.0.0, so prompts and habits written for the original keep working.
"""
import json
from typing import Annotated, Any, Callable

from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field

from . import bake
from .budget import ResponseBudget, SpillWriter, dumps, invalid_output, is_failure
from .client import FILE_OPERATION_TIMEOUT_MS, NwdGatewayError, PluginClient
from .config import NwdConfig
from .descriptions import DESCRIPTIONS

INSTRUCTIONS = (
    "nwd_* tools (ported from nwd-mcp): general Navisworks queries over the nwd plug-in. "
    "Lengths are in the model's display units. If more than one Navisworks may be open, call "
    "nwd_list_available_targets then nwd_switch_target. Large results: a _response_warning field marks "
    "results over 64 KiB and the budget is 1 MiB; nwd_get_model_tree, nwd_batch_get_properties, "
    "nwd_find_items_by_name and nwd_run_baked_tool accept output=file to write the full result to a local "
    "file and return its path, schema and a preview. Safety: prefer read tools. Before nwd_open_file with "
    "discard_changes true, nwd_unhide_all, or any change to a file the user did not create in this session, "
    "name the exact file or items and get the user's confirmation. If a permission check denies a call, do "
    "not repeat it through a baked tool or nwd_send_code; report the denial to the user."
)

_HAS_SNAKE = "is_error" in getattr(CallToolResult, "model_fields", {})


def _ann(read_only: bool, destructive: bool, idempotent: bool) -> ToolAnnotations:
    return ToolAnnotations(readOnlyHint=read_only, destructiveHint=destructive,
                           idempotentHint=idempotent, openWorldHint=False)


READ = _ann(True, False, True)

# name -> (toolset, annotations or None). Mirrors the [McpServerTool] attributes of nwd-mcp 1.0.0.
SPEC: dict[str, tuple[str, ToolAnnotations | None]] = {
    "nwd_list_available_targets": ("meta", READ),
    "nwd_get_current_target": ("meta", READ),
    "nwd_switch_target": ("meta", _ann(False, False, True)),
    "nwd_list_recent_files": ("files", READ),
    "nwd_open_file": ("files_write", _ann(False, True, False)),
    "nwd_import_model": ("files_write", _ann(False, False, False)),
    "nwd_get_document_info": ("query", READ),
    "nwd_get_model_statistics": ("query", READ),
    "nwd_get_model_tree": ("query", READ),
    "nwd_get_item_properties": ("query", READ),
    "nwd_batch_get_properties": ("query", READ),
    "nwd_find_items": ("query", READ),
    "nwd_find_items_by_name": ("query", READ),
    "nwd_health_check": ("query", READ),
    "nwd_get_current_selection": ("selection", READ),
    "nwd_clear_selection": ("selection_write", READ),
    "nwd_select_items_by_search": ("selection_write", READ),
    "nwd_list_sets": ("sets", READ),
    "nwd_get_selection_set_items": ("sets", READ),
    "nwd_execute_search_set": ("sets", READ),
    "nwd_list_viewpoints": ("view", READ),
    "nwd_get_current_viewpoint": ("view", READ),
    "nwd_goto_viewpoint": ("view_write", READ),
    "nwd_save_viewpoint": ("view_write", _ann(False, False, False)),
    "nwd_hide_items": ("visibility", _ann(False, True, True)),
    "nwd_unhide_all": ("visibility", _ann(False, True, True)),
    "nwd_send_code": ("code", None),
    "nwd_list_baked_tools": ("toolbaker", READ),
    "nwd_list_bake_suggestions": ("toolbaker", READ),
    "nwd_create_bake_issue_draft": ("toolbaker", READ),
    "nwd_run_baked_tool": ("toolbaker_write", _ann(False, True, False)),
    "nwd_accept_bake_suggestion": ("toolbaker_write", _ann(False, False, False)),
    "nwd_dismiss_bake_suggestion": ("toolbaker_write", _ann(False, True, True)),
}

def _is_read_only(ann: ToolAnnotations | None) -> bool:
    # mcp 2 exposes snake_case attributes, mcp 1 camelCase; both accept camelCase in the constructor.
    if ann is None:
        return False
    return (getattr(ann, "read_only_hint", None) if hasattr(ann, "read_only_hint")
            else getattr(ann, "readOnlyHint", None)) is True


WRITE_TOOLS = {name for name, (_, ann) in SPEC.items() if not _is_read_only(ann)}


def _error(code: str, message: str) -> str:
    return dumps({"ok": False, "error": {"code": code, "message": message}})


def _result(text: str) -> CallToolResult:
    content = [TextContent(type="text", text=text)]
    if _HAS_SNAKE:
        return CallToolResult(content=content, is_error=is_failure(text))
    return CallToolResult(content=content, isError=is_failure(text))  # mcp 1.x


def register(mcp: Any, config: NwdConfig) -> list[str]:
    """Register the enabled nwd_* tools on ``mcp``; returns their names."""
    client = PluginClient(config)
    budget = ResponseBudget(SpillWriter(config.spill_dir), WRITE_TOOLS)
    toolsets = config.resolved_toolsets()

    def db() -> bake.BakeDb:
        return bake.BakeDb(config.bake_dir).migrate()

    def finish(name: str, arguments: dict[str, Any], text: str) -> CallToolResult:
        return _result(budget.apply(name, arguments, text))

    def call(name: str, command: str, params: dict[str, Any], arguments: dict[str, Any] | None = None,
             timeout_ms: int | None = None) -> CallToolResult:
        try:
            text = dumps(client.send(command, params, timeout_ms))
        except NwdGatewayError as exc:
            text = _error(exc.code, exc.message)
        return finish(name, arguments or {}, text)

    def parse_filters(raw: str) -> Any:
        try:
            return json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise NwdGatewayError("INVALID_ARGUMENT", f"filtersJson must be valid JSON: {exc}") from exc

    # ---------------------------------------------------------- meta
    def nwd_list_available_targets() -> CallToolResult:
        return finish("nwd_list_available_targets", {}, dumps([t.public() for t in client.list_targets()]))

    def nwd_get_current_target() -> CallToolResult:
        t = client.current_target
        text = _error("NO_TARGET", "no live target") if t is None else dumps(t.public())
        return finish("nwd_get_current_target", {}, text)

    def nwd_switch_target(targetId: str) -> CallToolResult:
        return finish("nwd_switch_target", {}, dumps({"ok": client.switch_target(targetId), "target_id": targetId}))

    # ---------------------------------------------------------- files
    def nwd_list_recent_files(limit: int = 25) -> CallToolResult:
        return call("nwd_list_recent_files", "list_recent_files", {"limit": limit})

    def nwd_open_file(path: str, discardChanges: bool = False) -> CallToolResult:
        return call("nwd_open_file", "open_file", {"path": path, "discard_changes": discardChanges},
                    timeout_ms=FILE_OPERATION_TIMEOUT_MS)

    def nwd_import_model(path: str, mode: str = "append") -> CallToolResult:
        return call("nwd_import_model", "import_model", {"path": path, "mode": mode},
                    timeout_ms=FILE_OPERATION_TIMEOUT_MS)

    # ---------------------------------------------------------- query
    def nwd_get_document_info() -> CallToolResult:
        return call("nwd_get_document_info", "get_document_info", {})

    def nwd_get_model_statistics() -> CallToolResult:
        return call("nwd_get_model_statistics", "get_model_statistics", {})

    def nwd_get_model_tree(maxDepth: int = 2, maxItems: int = 500, output: str = "inline") -> CallToolResult:
        if (bad := invalid_output(output)) is not None:
            return _result(bad)
        return call("nwd_get_model_tree", "get_model_tree", {"max_depth": maxDepth, "max_items": maxItems},
                    {"output": output})

    def nwd_get_item_properties(itemId: str) -> CallToolResult:
        return call("nwd_get_item_properties", "get_item_properties", {"item_id": itemId})

    def nwd_batch_get_properties(itemIds: list[str], maxItems: int = 200, output: str = "inline") -> CallToolResult:
        if (bad := invalid_output(output)) is not None:
            return _result(bad)
        return call("nwd_batch_get_properties", "batch_get_properties",
                    {"item_ids": list(itemIds), "max_items": maxItems}, {"output": output})

    def nwd_find_items(filtersJson: str, maxItems: int = 500) -> CallToolResult:
        try:
            filters = parse_filters(filtersJson)
        except NwdGatewayError as exc:
            return _result(_error(exc.code, exc.message))
        return call("nwd_find_items", "find_items", {"filters": filters, "max_items": maxItems})

    def nwd_find_items_by_name(name: str, exact: bool = False, maxItems: int = 500,
                               output: str = "inline") -> CallToolResult:
        if (bad := invalid_output(output)) is not None:
            return _result(bad)
        return call("nwd_find_items_by_name", "find_items_by_name",
                    {"name": name, "exact": exact, "max_items": maxItems}, {"output": output})

    def nwd_health_check() -> CallToolResult:
        return call("nwd_health_check", "health_check", {})

    # ---------------------------------------------------------- selection
    def nwd_get_current_selection() -> CallToolResult:
        return call("nwd_get_current_selection", "get_current_selection", {})

    def nwd_clear_selection() -> CallToolResult:
        return call("nwd_clear_selection", "clear_selection", {})

    def nwd_select_items_by_search(filtersJson: str) -> CallToolResult:
        try:
            filters = parse_filters(filtersJson)
        except NwdGatewayError as exc:
            return _result(_error(exc.code, exc.message))
        return call("nwd_select_items_by_search", "select_items_by_search", {"filters": filters})

    # ---------------------------------------------------------- sets
    def nwd_list_sets() -> CallToolResult:
        return call("nwd_list_sets", "list_sets", {})

    def nwd_get_selection_set_items(setId: str) -> CallToolResult:
        return call("nwd_get_selection_set_items", "get_selection_set_items", {"set_id": setId})

    def nwd_execute_search_set(setId: str, select: bool = False) -> CallToolResult:
        params: dict[str, Any] = {"set_id": setId, "select": False if config.read_only else select}
        if config.read_only:
            params["read_only_enforced"] = True
        return call("nwd_execute_search_set", "execute_search_set", params)

    # ---------------------------------------------------------- view
    def nwd_list_viewpoints() -> CallToolResult:
        return call("nwd_list_viewpoints", "list_viewpoints", {})

    def nwd_get_current_viewpoint() -> CallToolResult:
        return call("nwd_get_current_viewpoint", "get_current_viewpoint", {})

    def nwd_goto_viewpoint(viewpointId: str) -> CallToolResult:
        return call("nwd_goto_viewpoint", "goto_viewpoint", {"viewpoint_id": viewpointId})

    def nwd_save_viewpoint(name: str) -> CallToolResult:
        return call("nwd_save_viewpoint", "save_viewpoint", {"name": name})

    # ---------------------------------------------------------- visibility
    def nwd_hide_items(itemIds: list[str], hide: bool = True) -> CallToolResult:
        return call("nwd_hide_items", "hide_items", {"item_ids": list(itemIds), "hide": hide})

    def nwd_unhide_all() -> CallToolResult:
        return call("nwd_unhide_all", "unhide_all", {})

    # ---------------------------------------------------------- code
    def nwd_send_code(code: str) -> CallToolResult:
        return call("nwd_send_code", "send_code", {"code": code})

    # ---------------------------------------------------------- toolbaker
    def nwd_list_baked_tools() -> CallToolResult:
        return finish("nwd_list_baked_tools", {}, bake.list_baked_tools(db()))

    def nwd_list_bake_suggestions() -> CallToolResult:
        return finish("nwd_list_bake_suggestions", {}, bake.list_suggestions(db()))

    def nwd_create_bake_issue_draft(
        id: Annotated[str, Field(description="Suggestion id from nwd_list_bake_suggestions.")],
    ) -> CallToolResult:
        return finish("nwd_create_bake_issue_draft", {}, bake.issue_draft(db(), id))

    def nwd_run_baked_tool(name: str, paramsJson: str, output: str = "inline") -> CallToolResult:
        if (bad := invalid_output(output)) is not None:
            return _result(bad)
        try:
            parsed = json.loads(paramsJson) if paramsJson and paramsJson.strip() else {}
            if not isinstance(parsed, dict):
                raise ValueError("not an object")
        except ValueError as exc:
            return _result(_error("INVALID_ARGUMENT", f"params must be a JSON object: {exc}"))
        record = db().registry_record(name)
        if record is None:
            return _result(_error("INVALID_ARGUMENT", "baked tool not found: " + name))
        return call("nwd_run_baked_tool", "run_baked_tool",
                    {"name": name, "params": parsed, "tool_record": bake.record_for_plugin(record)},
                    {"output": output})

    def nwd_accept_bake_suggestion(suggestionId: str, desiredName: str) -> CallToolResult:
        def apply(request: dict[str, Any]) -> dict[str, Any]:
            data = client.send("apply_bake", request)
            return data if isinstance(data, dict) else {}
        return finish("nwd_accept_bake_suggestion", {}, bake.accept_suggestion(db(), suggestionId, desiredName, apply))

    def nwd_dismiss_bake_suggestion(suggestionId: str) -> CallToolResult:
        return finish("nwd_dismiss_bake_suggestion", {}, bake.dismiss(db(), suggestionId))

    functions: dict[str, Callable[..., CallToolResult]] = {
        fn.__name__: fn for fn in (
            nwd_list_available_targets, nwd_get_current_target, nwd_switch_target,
            nwd_list_recent_files, nwd_open_file, nwd_import_model,
            nwd_get_document_info, nwd_get_model_statistics, nwd_get_model_tree, nwd_get_item_properties,
            nwd_batch_get_properties, nwd_find_items, nwd_find_items_by_name, nwd_health_check,
            nwd_get_current_selection, nwd_clear_selection, nwd_select_items_by_search,
            nwd_list_sets, nwd_get_selection_set_items, nwd_execute_search_set,
            nwd_list_viewpoints, nwd_get_current_viewpoint, nwd_goto_viewpoint, nwd_save_viewpoint,
            nwd_hide_items, nwd_unhide_all, nwd_send_code,
            nwd_list_baked_tools, nwd_list_bake_suggestions, nwd_create_bake_issue_draft,
            nwd_run_baked_tool, nwd_accept_bake_suggestion, nwd_dismiss_bake_suggestion,
        )
    }
    assert set(functions) == set(SPEC) == set(DESCRIPTIONS), "nwd tool tables out of sync"

    registered = []
    for name, (toolset, annotations) in SPEC.items():
        if toolset not in toolsets:
            continue
        kwargs: dict[str, Any] = {"name": name, "description": DESCRIPTIONS[name], "annotations": annotations}
        try:
            mcp.add_tool(functions[name], structured_output=False, **kwargs)
        except TypeError:  # mcp versions without structured_output
            mcp.add_tool(functions[name], **kwargs)
        registered.append(name)
    return registered
