#Requires -Version 5.1
<#
.SYNOPSIS
    Installs Navis-mcp (from the dist folder or the release ZIP) for the Navisworks Manage years in the package.

.DESCRIPTION
    - NavisCoord add-in -> %APPDATA%\Autodesk\Navisworks Manage <year>\Plugins\NavisCoord   (one per year)
    - nwd plug-in       -> %APPDATA%\Autodesk\ApplicationPlugins\Bimwright.Nwd.bundle     (one bundle, all years)
    - MCP server        -> %LOCALAPPDATA%\Navis-mcp\server\navis-mcp.exe
    Replaced folders are moved to %LOCALAPPDATA%\Navis-mcp\backup\<timestamp>\ (outside the folders
    Navisworks scans, so an old copy can never load) until you delete them.
    With -RegisterClaudeCode it also runs `claude mcp add` (user scope) when the CLI is on PATH.

    Every Navisworks Manage year in the package must be closed.
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [switch]$RegisterClaudeCode,
    [string]$Name = 'navisworks'
)

$ErrorActionPreference = 'Stop'
$here = $PSScriptRoot
$stamp = Get-Date -Format 'yyyyMMddHHmmss'

$years = @(Get-ChildItem (Join-Path $here 'addins\NavisCoord') -Directory | Where-Object { $_.Name -match '^\d{4}$' } | ForEach-Object { $_.Name })
if (-not $years) { throw "Pacote sem add-ins (rode build.ps1 primeiro)." }

$nwOpen = Get-Process roamer -ErrorAction SilentlyContinue | Where-Object {
    $path = try { $_.Path } catch { '' }
    $years | Where-Object { $path -like "*Navisworks Manage $_*" }
}
if ($nwOpen) { throw "Feche o Navisworks (PID $($nwOpen.Id -join ', ')) e rode de novo." }

$targets = @()
foreach ($y in $years) {
    $targets += @{ From = "addins\NavisCoord\$y"; To = Join-Path $env:APPDATA "Autodesk\Navisworks Manage $y\Plugins\NavisCoord" }
}
$targets += @{ From = 'addins\Bimwright.Nwd.bundle'; To = Join-Path $env:APPDATA 'Autodesk\ApplicationPlugins\Bimwright.Nwd.bundle' }
$targets += @{ From = 'server\navis-mcp'; To = Join-Path $env:LOCALAPPDATA 'Navis-mcp\server' }

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
        if (Test-Path $t.To) {
            $backup = Join-Path $env:LOCALAPPDATA "Navis-mcp\backup\$stamp"
            New-Item -ItemType Directory -Force $backup | Out-Null
            Move-Item $t.To (Join-Path $backup ("$i-" + (Split-Path $t.To -Leaf)))
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
Write-Host "Abra o Navisworks Manage ($($years -join ' ou ')): os dois add-ins carregam sozinhos."
