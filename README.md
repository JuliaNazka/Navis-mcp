# Navis-mcp

A single MCP server for **Autodesk Navisworks Manage 2025 and 2027**. It combines, in one process and one executable:

- **`navis_*`** (from [NavisCoord](https://github.com/HorizunGroup/naviscoord-mcp)), for coordination and clash detection: clash ranking, grouping, root causes, work plan, PDF reports, snapshots and comparison between rounds.
- **`nwd_*`** (a Python port of [nwd-mcp](https://github.com/bimwright/nwd-mcp)), for general model queries: document, tree, properties, search, sets and viewpoints.

Works with Claude Code, Claude Desktop or any MCP client over stdio.

*Leia em português: [README.pt-BR.md](README.pt-BR.md)*

<!-- DEMO: put a screenshot or short GIF here (Claude ranking clashes, or the generated PDF report).
![demo](docs/demo.gif) -->

## How it works

```
MCP client ──stdio──► navis-mcp.exe (Python, one process)
                        ├─ navis_*  ──HTTP loopback──► NavisCoord add-in ─┐
                        └─ nwd_*    ──TCP  loopback──► nwd plug-in ───────┴─► Navisworks Manage 2025 / 2027
```

The nwd-mcp server, originally in C#/.NET 8, was rewritten in Python inside the NavisCoord server. It speaks the same protocol to the same plug-in. Both add-ins remain in C# and run inside Navisworks.

## Read-only mode (default)

The server starts **read-only**, and a single switch covers both parts:

- NavisCoord refuses any write route;
- `navis_save`, `navis_save_as`, `navis_close_document` and `navis_exit` are not even exposed;
- the `nwd_*` write tools are not registered (`nwd_send_code`, opening or importing a file, hiding, viewpoints, ToolBaker).

Read-only mode exposes 70 tools: 49 `navis_*` and 21 `nwd_*`. To enable writing, use `--allow-write` or `NAVIS_MCP_READ_ONLY=0`.

## Install

With Navisworks **closed**:

```powershell
# from the release ZIP or the dist\Navis-mcp folder
powershell -ExecutionPolicy Bypass -File .\install.ps1 -RegisterClaudeCode
```

This installs:

| What | Where |
|---|---|
| NavisCoord add-in | `%APPDATA%\Autodesk\ApplicationPlugins\NavisCoord.bundle` (2025 and 2027; NW 2027 no longer loads add-ins from the per-user `Plugins` folder) |
| nwd plug-in | `%APPDATA%\Autodesk\ApplicationPlugins\Bimwright.Nwd.bundle` |
| MCP server | `%LOCALAPPDATA%\Navis-mcp\server\navis-mcp.exe` |

To register it in Claude Code by hand:

```powershell
claude mcp add --transport stdio --scope user navisworks -- "$env:LOCALAPPDATA\Navis-mcp\server\navis-mcp.exe"
```

Then open Navisworks (2025 or 2027) with the model and ask: *"call navis_health and nwd_health_check, then analyze the clashes without saving"*.

To uninstall: `.\uninstall.ps1`.

## Build from source

Requirements: Windows, Navisworks Manage 2025 and/or 2027 installed (the build compiles every year it finds; `-Years` picks which) (the API DLLs are referenced, never copied), .NET SDK 8+ and [uv](https://docs.astral.sh/uv/).

```powershell
.\build.ps1
```

The build:

1. creates `.venv` with hash-locked dependencies (`scripts/requirements.lock`);
2. runs the server tests;
3. builds `navis-mcp.exe` with PyInstaller;
4. compiles both add-ins for each year (2025 and 2027);
5. tests the exe;
6. assembles `dist\Navis-mcp\` and `dist\Navis-mcp-1.0.0-win-x64.zip` with its sha256.

## Tests

```powershell
.venv\Scripts\python.exe tests\test_nwd_protocol.py      # nwd_* against a fake plug-in (TCP + descriptor)
.venv\Scripts\python.exe tests\smoke_stdio.py dist\Navis-mcp\server\navis-mcp\navis-mcp.exe
```

## Layout

```
server/naviscoord/          MCP server (NavisCoord) + unified.py
server/naviscoord/nwd/      port of the nwd-mcp server (client, tools, budget, bake)
addins/NavisCoord.Addin/    NavisCoord add-in (C#, net48)
addins/nwd/                 nwd plug-in (C#, net48): shared/ + plugin-navis25/ + plugin-navis27/
scripts/                    exe entry point and dependency lock
tests/                      tests that run without Navisworks
third_party/                original licenses
```

## License

Navis-mcp code is MIT (© 2026 Julia Nazka); see [LICENSE](LICENSE). NavisCoord is MIT (© Horizun Group) and nwd-mcp is Apache-2.0 (© Khoa Le); their licenses apply to the parts that came from each. Details and list of changes in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Navis-mcp is not affiliated with Autodesk. Navisworks is a trademark of Autodesk, Inc.
