#Requires -Version 5.1
<#
.SYNOPSIS
    Removes what install.ps1 put in place (add-ins and server). Backups (*.bak-*) are left alone.
#>
[CmdletBinding(SupportsShouldProcess)]
param()

$ErrorActionPreference = 'Stop'
$nwOpen = Get-Process roamer -ErrorAction SilentlyContinue | Where-Object {
    try { $_.Path -like '*Navisworks Manage 2027*' } catch { $false }
}
if ($nwOpen) { throw "Feche o Navisworks Manage 2027 (PID $($nwOpen.Id -join ', ')) e rode de novo." }

foreach ($p in @(
    (Join-Path $env:APPDATA 'Autodesk\Navisworks Manage 2027\Plugins\NavisCoord'),
    (Join-Path $env:APPDATA 'Autodesk\ApplicationPlugins\Bimwright.Nwd.bundle'),
    (Join-Path $env:LOCALAPPDATA 'Navis-mcp\server')
)) {
    if ((Test-Path $p) -and $PSCmdlet.ShouldProcess($p, 'remover')) {
        Remove-Item $p -Recurse -Force
        Write-Host "removido: $p"
    }
}
Write-Host "Se registrou no Claude Code: claude mcp remove --scope user navisworks"
