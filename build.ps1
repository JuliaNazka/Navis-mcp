#Requires -Version 5.1
<#
.SYNOPSIS
    Builds Navis-mcp from source into dist\Navis-mcp (and dist\Navis-mcp-<version>-win-x64.zip).

.DESCRIPTION
    1. Python server (NavisCoord navis_* + nwd_* port) -> one standalone navis-mcp.exe (PyInstaller, onedir)
    2. NavisCoord add-in for each Navisworks Manage year in -Years (net48)
    3. nwd plug-in for each year, packaged as one ApplicationPlugins bundle
    4. Installer, licences and README next to them

    Needs: Windows, the Navisworks Manage years to build installed (their API DLLs are referenced,
    never copied), .NET SDK 8+, and uv (https://docs.astral.sh/uv/) for the Python build environment.
    A year that is not installed is skipped with a warning.

.EXAMPLE
    .\build.ps1
    .\build.ps1 -Years 2027 -SkipTests
    .\build.ps1 -AutodeskDir "D:\Autodesk"
#>
[CmdletBinding()]
param(
    [int[]]$Years = @(2025, 2027),
    [string]$AutodeskDir = 'C:\Program Files\Autodesk',
    [string]$Python = '3.13',
    [switch]$SkipTests
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$version = '1.0.0'
$dist = Join-Path $root 'dist'
$out = Join-Path $dist 'Navis-mcp'
$venvPy = Join-Path $root '.venv\Scripts\python.exe'

function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Run($exe) {
    $argList = $args
    & $exe @argList
    if ($LASTEXITCODE -ne 0) { throw "falhou ($LASTEXITCODE): $exe $($argList -join ' ')" }
}

# Autodesk's bundle series per year (nwd-mcp's PackageContents template).
$series = @{ 2022 = 'Nw19'; 2023 = 'Nw20'; 2024 = 'Nw21'; 2025 = 'Nw22'; 2026 = 'Nw23'; 2027 = 'Nw24' }
$built = @()
foreach ($y in $Years) {
    $dir = Join-Path $AutodeskDir "Navisworks Manage $y"
    if (-not $series.ContainsKey($y)) { throw "Ano não suportado: $y" }
    if (-not (Test-Path (Join-Path $root "addins\nwd\plugin-navis$($y % 100)"))) { throw "Falta addins\nwd\plugin-navis$($y % 100)" }
    if (Test-Path (Join-Path $dir 'Autodesk.Navisworks.Api.dll')) { $built += $y }
    else { Write-Warning "Navisworks Manage $y não encontrado em '$dir': pulando esse ano." }
}
if (-not $built) { throw "Nenhum Navisworks Manage de $($Years -join ', ') instalado em '$AutodeskDir'." }

Step 'Ambiente Python (uv + dependências travadas por hash)'
if (-not (Test-Path $venvPy)) { Run uv venv (Join-Path $root '.venv') --python $Python }
Run uv pip install --python $venvPy --require-hashes -r (Join-Path $root 'scripts\requirements.lock')
Run uv pip install --python $venvPy 'pyinstaller>=6.11,<7'

if (-not $SkipTests) {
    Step 'Testes do servidor (fonte)'
    Run $venvPy (Join-Path $root 'tests\test_nwd_protocol.py')
    Run $venvPy (Join-Path $root 'tests\smoke_stdio.py') $venvPy -m naviscoord.mcp_server
}

if (Test-Path $out) { Remove-Item $out -Recurse -Force }
New-Item -ItemType Directory -Force $out | Out-Null

Step 'Servidor MCP único -> navis-mcp.exe'
$work = Join-Path $dist 'pyinstaller-work'
Run $venvPy -m PyInstaller --noconfirm --clean --onedir --console --name navis-mcp `
    --distpath (Join-Path $out 'server') --workpath $work --specpath $dist `
    --paths (Join-Path $root 'server') `
    --add-data ((Join-Path $root 'server\naviscoord\profiles') + ';naviscoord/profiles') `
    --collect-data reportlab --collect-submodules PIL --collect-submodules naviscoord `
    --copy-metadata mcp (Join-Path $root 'scripts\frozen_entry.py')

$ncProj = Join-Path $root 'addins\NavisCoord.Addin\NavisCoord.Addin.csproj'
$bundle = Join-Path $out 'addins\Bimwright.Nwd.bundle'
$components = @()
foreach ($y in $built) {
    $nwDir = Join-Path $AutodeskDir "Navisworks Manage $y"
    $yy = $y % 100

    Step "Add-in NavisCoord (Navisworks Manage $y)"
    $ncBin = Join-Path $root "addins\NavisCoord.Addin\bin\Release\$y\"
    Run dotnet build $ncProj -c Release -nologo -v minimal "-p:NavisworksYear=$y" "-p:NavisworksDir=$nwDir" `
        "-p:OutDir=$ncBin" "-p:IntermediateOutputPath=obj\Release\$y\"
    $ncOut = Join-Path $out "addins\NavisCoord\$y"
    New-Item -ItemType Directory -Force (Join-Path $ncOut 'en-US') | Out-Null
    foreach ($f in 'NavisCoord.dll', 'NavisCoordRibbon.xaml', 'nc_16.png', 'nc_32.png') { Copy-Item (Join-Path $ncBin $f) $ncOut }
    Copy-Item (Join-Path $ncBin 'en-US\NavisCoordRibbon.xaml') (Join-Path $ncOut 'en-US')
    Copy-Item (Join-Path $root 'profiles\example-profile.json') $ncOut
    Copy-Item (Join-Path $root 'third_party\naviscoord\LICENSE') $ncOut
    Copy-Item (Join-Path $root 'third_party\naviscoord\NOTICE') $ncOut

    Step "Plug-in nwd (Navisworks Manage $y)"
    $nwProj = Join-Path $root "addins\nwd\plugin-navis$yy\Bimwright.Nwd.Plugin.Navis$yy.csproj"
    Run dotnet build $nwProj -c Release -nologo -v minimal "-p:NavisworksInstallDir=$nwDir"
    $nwBin = Join-Path $root "addins\nwd\plugin-navis$yy\bin\Release\net48"
    New-Item -ItemType Directory -Force (Join-Path $bundle "Contents\$y") | Out-Null
    Get-ChildItem $nwBin -File | Where-Object { $_.Extension -in '.dll', '.pdb' } | Copy-Item -Destination (Join-Path $bundle "Contents\$y")
    $components += @"
  <Components>
    <RuntimeRequirements OS="Win64" Platform="NAVMAN" SeriesMin="$($series[$y])" SeriesMax="$($series[$y])" />
    <ComponentEntry AppName="Bimwright.Nwd.Plugin.Navis$yy" AppType="ManagedPlugin" ModuleName="./Contents/$y/Bimwright.Nwd.Plugin.Navis$yy.dll" />
  </Components>
"@
}
@"
<?xml version="1.0" encoding="utf-8"?>
<ApplicationPackage SchemaVersion="1.0" AppVersion="$version" AutodeskProduct="Navisworks" Name="Bimwright.Nwd" Description="nwd plug-in (Navis-mcp build) for Autodesk Navisworks Manage $($built -join ', ')" ProductCode="{9B3F7B2D-1C4E-4D5F-9A6B-7E8C9D0F1A2B}">
  <CompanyDetails Name="Bimwright (built by Navis-mcp)" />
$($components -join "`n")
</ApplicationPackage>
"@ | Set-Content -Encoding UTF8 (Join-Path $bundle 'PackageContents.xml')
Copy-Item (Join-Path $root 'third_party\nwd-mcp\LICENSE') $bundle

Step 'Instalador, licenças e README'
foreach ($f in 'install.ps1', 'uninstall.ps1', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'README.md') { Copy-Item (Join-Path $root $f) $out }
Copy-Item (Join-Path $root 'third_party') (Join-Path $out 'third_party') -Recurse

if (-not $SkipTests) {
    Step 'Teste do exe compilado'
    Run $venvPy (Join-Path $root 'tests\smoke_stdio.py') (Join-Path $out 'server\navis-mcp\navis-mcp.exe')
}

Step 'ZIP'
$zip = Join-Path $dist "Navis-mcp-$version-win-x64.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path $out -DestinationPath $zip
$hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
"$hash  $(Split-Path $zip -Leaf)" | Set-Content -Encoding ASCII "$zip.sha256"
Write-Host "`nPronto: $out`n        $zip`n        sha256 $hash" -ForegroundColor Green
