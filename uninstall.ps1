#Requires -Version 5.1
<#
.SYNOPSIS
    Removes what install.ps1 put in place (add-ins for every year, and the server).
    Backups in %LOCALAPPDATA%\Navis-mcp\backup are left alone.
#>
[CmdletBinding(SupportsShouldProcess)]
param()

$ErrorActionPreference = 'Stop'
$nwOpen = Get-Process roamer -ErrorAction SilentlyContinue
if ($nwOpen) { throw "Feche o Navisworks (PID $($nwOpen.Id -join ', ')) e rode de novo." }

$paths = @(Get-ChildItem (Join-Path $env:APPDATA 'Autodesk') -Directory -Filter 'Navisworks Manage *' -ErrorAction SilentlyContinue |
    ForEach-Object { Join-Path $_.FullName 'Plugins\NavisCoord' })
$paths += Join-Path $env:APPDATA 'Autodesk\ApplicationPlugins\Bimwright.Nwd.bundle'
$paths += Join-Path $env:LOCALAPPDATA 'Navis-mcp\server'

foreach ($p in $paths) {
    if ((Test-Path $p) -and $PSCmdlet.ShouldProcess($p, 'remover')) {
        Remove-Item $p -Recurse -Force
        Write-Host "removido: $p"
    }
}
Write-Host "Se registrou no Claude Code: claude mcp remove --scope user navisworks"
