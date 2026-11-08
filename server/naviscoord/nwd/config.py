"""Settings for the nwd_* tools (port of NwdMcpConfig.cs + ToolsetFilter.cs)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

KNOWN_TOOLSETS = (
    "meta", "files", "files_write", "query", "selection", "selection_write", "sets",
    "view", "view_write", "visibility", "code", "toolbaker", "toolbaker_write",
)

# Toolsets that can change the open document or local state. Removed in read-only mode.
WRITE_CAPABLE = frozenset({
    "files_write", "selection_write", "view_write", "visibility", "code", "toolbaker_write",
})


def local_app_data() -> Path:
    value = os.environ.get("LOCALAPPDATA")
    return Path(value) if value else Path.home() / "AppData" / "Local"


def _bool(name: str) -> bool | None:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return None
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str) -> int | None:
    try:
        return int(os.environ.get(name, ""))
    except ValueError:
        return None


@dataclass
class NwdConfig:
    read_only: bool = True
    enable_send_code: bool = True
    enable_toolbaker: bool = True
    timeout_ms: int = 30_000
    max_response_bytes: int = 10 * 1024 * 1024
    target_id: str | None = None
    toolsets: list[str] = field(default_factory=list)
    # Same folders as the original server, so the unmodified plug-in finds us and
    # existing baked tools / spill files keep working.
    descriptor_dir: Path = field(default_factory=lambda: local_app_data() / "Bimwright" / "nwd-mcp")
    bake_dir: Path = field(default_factory=lambda: local_app_data() / "Bimwright" / "nwd-mcp" / "baked")
    spill_dir: Path = field(default_factory=lambda: local_app_data() / "Bimwright" / "nwd-mcp" / "spill")

    @classmethod
    def from_env(cls, read_only: bool) -> "NwdConfig":
        """Read the BIMWRIGHT_NWD_* variables of the original server.

        Read-only is NOT read from BIMWRIGHT_NWD_READ_ONLY: Navis-mcp has one
        switch for both halves, decided by the caller.
        """
        cfg = cls(read_only=read_only)
        if (v := _bool("BIMWRIGHT_NWD_ENABLE_SEND_CODE")) is not None:
            cfg.enable_send_code = v
        if (v := _bool("BIMWRIGHT_NWD_ENABLE_TOOLBAKER")) is not None:
            cfg.enable_toolbaker = v
        if (v := _int("BIMWRIGHT_NWD_TIMEOUT_MS")) is not None:
            cfg.timeout_ms = v
        if (v := _int("BIMWRIGHT_NWD_MAX_RESPONSE_BYTES")) is not None:
            cfg.max_response_bytes = v
        target = os.environ.get("BIMWRIGHT_NWD_TARGET", "").strip()
        if target:
            cfg.target_id = target
        toolsets = os.environ.get("BIMWRIGHT_NWD_TOOLSETS", "").strip()
        if toolsets:
            cfg.toolsets = [t.strip() for t in toolsets.split(",") if t.strip()]
        return cfg

    def resolved_toolsets(self) -> set[str]:
        requested = [t.lower() for t in self.toolsets]
        if not requested or "all" in requested:
            selected = set(KNOWN_TOOLSETS)
        else:
            selected = set(requested) & set(KNOWN_TOOLSETS)
        if not self.enable_send_code:
            selected.discard("code")
        if not self.enable_toolbaker:
            selected -= {"toolbaker", "toolbaker_write"}
        if self.read_only:
            selected -= WRITE_CAPABLE
        return selected
