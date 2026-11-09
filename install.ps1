#Requires -Version 5.1
<#
.SYNOPSIS
    Installs Navis-mcp (from the dist folder or the release ZIP) for the Navisworks Manage years in the package.

.DESCRIPTION
    - NavisCoord add-in -> %APPDATA%\Autodesk\ApplicationPlugins\NavisCoord.bundle       (one component per year)
    - nwd plug-in       -> %APPDATA%\Autodesk\ApplicationPlugins\Bimwright.Nwd.bundle   (one component per year)
    - MCP server        -> %LOCALAPPDATA%\Navis-mcp\server-<version>\navis-mcp.exe   (one folder per version)
    Older NavisCoord copies under %APPDATA%\Autodesk\Navisworks Manage <year>\Plugins\NavisCoord are moved
    out so the add-in never loads twice. Replaced folders go to %LOCALAPPDATA%\Navis-mcp\backup\<timestamp>\
    (outside the folders Navisworks scans) until you delete them.
    With -RegisterClaudeCode it also runs `claude mcp add` (user scope) when the CLI is on PATH.

    Navisworks Manage must be closed, unless -ServerOnly: that replaces only the MCP server
    (when the add-ins did not change) and may run with Navisworks open. Restart the MCP client
    afterwards so it starts the new server.
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [switch]$RegisterClaudeCode,
    [switch]$ServerOnly,
    [string]$Name = 'navisworks'
)

$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$stamp = Get-Date -Format 'yyyyMMddHHmmss'
$backup = Join-Path $env:LOCALAPPDATA "Navis-mcp\backup\$stamp"

if (-not $ServerOnly) {
    $nwOpen = Get-Process roamer -ErrorAction SilentlyContinue
    if ($nwOpen) { throw "Feche o Navisworks (PID $($nwOpen.Id -join ', ')) e rode de novo, ou use -ServerOnly se só o servidor mudou." }
}

function Move-ToBackup([string]$path, [string]$label) {
    New-Item -ItemType Directory -Force $backup | Out-Null
    Move-Item $path (Join-Path $backup $label)
    Write-Host "backup: $(Join-Path $backup $label)"
}

if (-not $ServerOnly) {
    # Legacy per-year Plugins copies (Navis-mcp < 1.0.1 and the official NavisCoord installer).
    Get-ChildItem (Join-Path $env:APPDATA 'Autodesk') -Directory -Filter 'Navisworks Manage *' -ErrorAction SilentlyContinue | ForEach-Object {
        $legacy = Join-Path $_.FullName 'Plugins\NavisCoord'
        if ((Test-Path $legacy) -and $PSCmdlet.ShouldProcess($legacy, 'mover para backup')) {
            Move-ToBackup $legacy ("NavisCoord-Plugins-" + ($_.Name -replace '\D', ''))
        }
    }
}

$targets = @()
if (-not $ServerOnly) {
    $targets += @{ From = 'addins\NavisCoord.bundle'; To = Join-Path $env:APPDATA 'Autodesk\ApplicationPlugins\NavisCoord.bundle' }
    $targets += @{ From = 'addins\Bimwright.Nwd.bundle'; To = Join-Path $env:APPDATA 'Autodesk\ApplicationPlugins\Bimwright.Nwd.bundle' }
}
# One folder per server version: a running MCP server (any open Claude session) locks its files,
# so replacing a fixed folder in place fails half-way. A new version goes beside the old one.
$version = if (Test-Path (Join-Path $here 'VERSION')) { (Get-Content (Join-Path $here 'VERSION') -Raw).Trim() } else { 'dev' }
$serverDir = Join-Path $env:LOCALAPPDATA "Navis-mcp\server-$version"
$targets += @{ From = 'server\navis-mcp'; To = $serverDir }

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

# Older server folders that nothing is running from any more.
Get-ChildItem (Join-Path $env:LOCALAPPDATA 'Navis-mcp') -Directory -ErrorAction SilentlyContinue |
    Where-Object { ($_.Name -eq 'server' -or $_.Name -like 'server-*') -and $_.FullName -ne $serverDir } |
    ForEach-Object {
        $dir = $_.FullName
        $inUse = Get-CimInstance Win32_Process -Filter "Name='navis-mcp.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($dir, [StringComparison]::OrdinalIgnoreCase) }
        if ($inUse) { Write-Host "mantido (em uso por outra sessão): $dir" }
        elseif ($PSCmdlet.ShouldProcess($dir, 'remover servidor antigo')) {
            try { Remove-Item $dir -Recurse -Force -ErrorAction Stop; Write-Host "removido servidor antigo: $dir" }
            catch { Write-Host "não deu para remover agora: $dir" }
        }
    }

$years = @(Get-ChildItem (Join-Path $here 'addins\NavisCoord.bundle\Contents') -Directory | ForEach-Object { $_.Name })
$exe = Join-Path $serverDir 'navis-mcp.exe'
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
Write-Host 'Modo padrão: SOMENTE LEITURA. Para liberar escrita, acrescente --allow-write ao comando (depois de --).'
Write-Host 'Reinicie o cliente MCP para ele subir o servidor novo.'
Write-Host "Abra o Navisworks Manage ($($years -join ' ou ')): os dois add-ins carregam sozinhos."
