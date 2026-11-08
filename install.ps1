#Requires -Version 5.1
<#
.SYNOPSIS
    Installs Navis-mcp (from the dist folder or the release ZIP) for Navisworks Manage 2027.

.DESCRIPTION
    - NavisCoord add-in -> %APPDATA%\Autodesk\Navisworks Manage 2027\Plugins\NavisCoord
    - nwd plug-in       -> %APPDATA%\Autodesk\ApplicationPlugins\Bimwright.Nwd.bundle
    - MCP server        -> %LOCALAPPDATA%\Navis-mcp\server\navis-mcp.exe
    Replaced folders are moved to %LOCALAPPDATA%\Navis-mcp\backup\<timestamp>\ (outside the folders
    Navisworks scans, so an old copy can never load) until you delete them.
    With -RegisterClaudeCode it also runs `claude mcp add` (user scope) when the CLI is on PATH.

    Navisworks Manage 2027 must be closed. Other Navisworks versions may stay open.
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [switch]$RegisterClaudeCode,
    [string]$Name = 'navisworks'
)

$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$stamp = Get-Date -Format 'yyyyMMddHHmmss'

$nwOpen = Get-Process roamer -ErrorAction SilentlyContinue | Where-Object {
    try { $_.Path -like '*Navisworks Manage 2027*' } catch { $false }
}
if ($nwOpen) { throw "Feche o Navisworks Manage 2027 (PID $($nwOpen.Id -join ', ')) e rode de novo." }

$targets = @(
    @{ From = 'addins\NavisCoord'; To = Join-Path $env:APPDATA 'Autodesk\Navisworks Manage 2027\Plugins\NavisCoord' },
    @{ From = 'addins\Bimwright.Nwd.bundle'; To = Join-Path $env:APPDATA 'Autodesk\ApplicationPlugins\Bimwright.Nwd.bundle' },
    @{ From = 'server\navis-mcp'; To = Join-Path $env:LOCALAPPDATA 'Navis-mcp\server' }
)

foreach ($t in $targets) {
    $src = Join-Path $here $t.From
    if (-not (Test-Path $src)) { throw "Faltando no pacote: $src (rode build.ps1 primeiro)" }
    if ($PSCmdlet.ShouldProcess($t.To, 'instalar')) {
        $parent = Split-Path $t.To -Parent
        New-Item -ItemType Directory -Force $parent | Out-Null
        $stage = Join-Path $env:LOCALAPPDATA "Navis-mcp\staging-$stamp\$(Split-Path $t.To -Leaf)"
        New-Item -ItemType Directory -Force (Split-Path $stage -Parent) | Out-Null
        Copy-Item $src $stage -Recurse
        if (Test-Path $t.To) {
            $backup = Join-Path $env:LOCALAPPDATA "Navis-mcp\backup\$stamp"
            New-Item -ItemType Directory -Force $backup | Out-Null
            Move-Item $t.To (Join-Path $backup ((Split-Path $t.To -Leaf) + "-" + [guid]::NewGuid().ToString('N').Substring(0, 6)))
            Write-Host "backup: $backup"
        }
        Move-Item $stage $t.To
        Write-Host "instalado: $($t.To)" -ForegroundColor Green
    }
}
Remove-Item (Join-Path $env:LOCALAPPDATA "Navis-mcp\staging-$stamp") -Recurse -Force -ErrorAction SilentlyContinue

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
Write-Host 'Abra o Navisworks Manage 2027: os dois add-ins carregam sozinhos.'
