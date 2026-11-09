#Requires -Version 5.1
<#
.SYNOPSIS
    Removes what install.ps1 put in place (both bundles and the server), plus any legacy
    %APPDATA%\Autodesk\Navisworks Manage <year>\Plugins\NavisCoord copy.
    Backups in %LOCALAPPDATA%\Navis-mcp\backup are left alone.
#>
[CmdletBinding(SupportsShouldProcess)]
param()

$ErrorActionPreference = 'Stop'
$nwOpen = Get-Process roamer -ErrorAction SilentlyContinue
if ($nwOpen) { throw "Feche o Navisworks (PID $($nwOpen.Id -join ', ')) e rode de novo." }

$paths = @(Get-ChildItem (Join-Path $env:APPDATA 'Autodesk') -Directory -Filter 'Navisworks Manage *' -ErrorAction SilentlyContinue |
    ForEach-Object { Join-Path $_.FullName 'Plugins\NavisCoord' })
$paths += Join-Path $env:APPDATA 'Autodesk\ApplicationPlugins\NavisCoord.bundle'
$paths += Join-Path $env:APPDATA 'Autodesk\ApplicationPlugins\Bimwright.Nwd.bundle'
$paths += @(Get-ChildItem (Join-Path $env:LOCALAPPDATA 'Navis-mcp') -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -eq 'server' -or $_.Name -like 'server-*' } | ForEach-Object { $_.FullName })

foreach ($p in $paths) {
    if ((Test-Path $p) -and $PSCmdlet.ShouldProcess($p, 'remover')) {
        Remove-Item $p -Recurse -Force
        Write-Host "removido: $p"
    }
}
Write-Host "Se registrou no Claude Code: claude mcp remove --scope user navisworks"
