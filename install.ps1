#Requires -Version 5.1
<#
.SYNOPSIS
    Installs Navis-mcp (from the dist folder or the release ZIP) for the Navisworks Manage years in the package.

.DESCRIPTION
    - NavisCoord add-in -> %APPDATA%\Autodesk\ApplicationPlugins\NavisCoord.bundle       (one component per year)
    - nwd plug-in       -> %APPDATA%\Autodesk\ApplicationPlugins\Bimwright.Nwd.bundle   (one component per year)
    - MCP server        -> %LOCALAPPDATA%\Navis-mcp\server\navis-mcp.exe
    Older NavisCoord copies under %APPDATA%\Autodesk\Navisworks Manage <year>\Plugins\NavisCoord are moved
    out so the add-in never loads twice. Replaced folders go to %LOCALAPPDATA%\Navis-mcp\backup\<timestamp>\
    (outside the folders Navisworks scans) until you delete them.
    With -RegisterClaudeCode it also runs `claude mcp add` (user scope) when the CLI is on PATH.

    Navisworks Manage must be closed.
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [switch]$RegisterClaudeCode,
    [string]$Name = 'navisworks'
)

$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$stamp = Get-Date -Format 'yyyyMMddHHmmss'
$backup = Join-Path $env:LOCALAPPDATA "Navis-mcp\backup\$stamp"

$nwOpen = Get-Process roamer -ErrorAction SilentlyContinue
if ($nwOpen) { throw "Feche o Navisworks (PID $($nwOpen.Id -join ', ')) e rode de novo." }

function Move-ToBackup([string]$path, [string]$label) {
    New-Item -ItemType Directory -Force $backup | Out-Null
    Move-Item $path (Join-Path $backup $label)
    Write-Host "backup: $(Join-Path $backup $label)"
}

# Legacy per-year Plugins copies (Navis-mcp < 1.0.1 and the official NavisCoord installer).
Get-ChildItem (Join-Path $env:APPDATA 'Autodesk') -Directory -Filter 'Navisworks Manage *' -ErrorAction SilentlyContinue | ForEach-Object {
    $legacy = Join-Path $_.FullName 'Plugins\NavisCoord'
    if ((Test-Path $legacy) -and $PSCmdlet.ShouldProcess($legacy, 'mover para backup')) {
        Move-ToBackup $legacy ("NavisCoord-Plugins-" + ($_.Name -replace '\D', ''))
    }
}

$targets = @(
    @{ From = 'addins\NavisCoord.bundle'; To = Join-Path $env:APPDATA 'Autodesk\ApplicationPlugins\NavisCoord.bundle' },
    @{ From = 'addins\Bimwright.Nwd.bundle'; To = Join-Path $env:APPDATA 'Autodesk\ApplicationPlugins\Bimwright.Nwd.bundle' },
    @{ From = 'server\navis-mcp'; To = Join-Path $env:LOCALAPPDATA 'Navis-mcp\server' }
)

$i = 0
foreach ($t in $targets) {
    $i++
    $src = Join-Path $here $t.From
    if (-not (Test-Path $src)) { throw "Faltando no pacote: $src (rode build.ps1 primeiro)" }
    if ($PSCmdlet.ShouldProcess($t.To, 'instalar')) {
        New-Item -ItemType Directory -Force (Split-Path $t.To -Parent) | Out-Null
        $stage = Join-Path $env:LOCALAPPDATA "Navis-mcp\staging-$stamp\$i"
        New-Item -ItemType Directory -Force (Split-Path $stage -Parent) | Out-Null
        Copy-Item $src $stage -Recurse
        if (Test-Path $t.To) { Move-ToBackup $t.To ("$i-" + (Split-Path $t.To -Leaf)) }
        Move-Item $stage $t.To
        Write-Host "instalado: $($t.To)" -ForegroundColor Green
    }
}
Remove-Item (Join-Path $env:LOCALAPPDATA "Navis-mcp\staging-$stamp") -Recurse -Force -ErrorAction SilentlyContinue

$years = @(Get-ChildItem (Join-Path $here 'addins\NavisCoord.bundle\Contents') -Directory | ForEach-Object { $_.Name })
$exe = Join-Path $env:LOCALAPPDATA 'Navis-mcp\server\navis-mcp.exe'
Write-Host "`nServidor MCP: $exe"
if ($RegisterClaudeCode) {
    $claude = Get-Command claude -ErrorAction SilentlyContinue
    if ($claude) {
        & $claude.Source mcp remove --scope user $Name 2>$null | Out-Null
        & $claude.Source mcp add --transport stdio --scope user $Name -- $exe
    } else {
        Write-Warning "CLI 'claude' não está no PATH. Registre manualmente:"
    }
}
Write-Host "Claude Code: claude mcp add --transport stdio --scope user $Name -- `"$exe`""
Write-Host 'Modo padrão: SOMENTE LEITURA. Para liberar escrita, acrescente --allow-write ao comando.'
Write-Host "Abra o Navisworks Manage ($($years -join ' ou ')): os dois add-ins carregam sozinhos."
