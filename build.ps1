#Requires -Version 5.1
<#
.SYNOPSIS
    Builds Navis-mcp from source into dist\Navis-mcp (and dist\Navis-mcp-<version>-win-x64.zip).

.DESCRIPTION
    1. Python server (NavisCoord navis_* + nwd_* port) -> one standalone navis-mcp.exe (PyInstaller, onedir)
    2. NavisCoord add-in for Navisworks Manage 2027 (net48)
    3. nwd plug-in for Navisworks Manage 2027 (net48), packaged as an ApplicationPlugins bundle
    4. Installer, licences and README next to them

    Needs: Windows, Navisworks Manage 2027 installed (its API DLLs are referenced, never copied),
    .NET SDK 8+, and uv (https://docs.astral.sh/uv/) to create the Python build environment.

.EXAMPLE
    .\build.ps1
    .\build.ps1 -NavisworksDir "D:\Autodesk\Navisworks Manage 2027" -SkipTests
#>
[CmdletBinding()]
param(
    [string]$NavisworksDir = 'C:\Program Files\Autodesk\Navisworks Manage 2027',
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

if (-not (Test-Path (Join-Path $NavisworksDir 'Autodesk.Navisworks.Api.dll'))) {
    throw "Navisworks Manage 2027 não encontrado em '$NavisworksDir'. Use -NavisworksDir."
}

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

Step 'Add-in NavisCoord (Navisworks Manage 2027)'
$ncProj = Join-Path $root 'addins\NavisCoord.Addin\NavisCoord.Addin.csproj'
Run dotnet build $ncProj -c Release -nologo -v minimal '-p:NavisworksYear=2027' "-p:NavisworksDir=$NavisworksDir"
$ncBin = Join-Path $root 'addins\NavisCoord.Addin\bin\Release'
$ncOut = Join-Path $out 'addins\NavisCoord'
New-Item -ItemType Directory -Force (Join-Path $ncOut 'en-US') | Out-Null
foreach ($f in 'NavisCoord.dll', 'NavisCoordRibbon.xaml', 'nc_16.png', 'nc_32.png') { Copy-Item (Join-Path $ncBin $f) $ncOut }
Copy-Item (Join-Path $ncBin 'en-US\NavisCoordRibbon.xaml') (Join-Path $ncOut 'en-US')
Copy-Item (Join-Path $root 'profiles\example-profile.json') $ncOut
Copy-Item (Join-Path $root 'third_party\naviscoord\LICENSE') $ncOut
Copy-Item (Join-Path $root 'third_party\naviscoord\NOTICE') $ncOut

Step 'Plug-in nwd (Navisworks Manage 2027)'
$nwProj = Join-Path $root 'addins\nwd\plugin-navis27\Bimwright.Nwd.Plugin.Navis27.csproj'
Run dotnet build $nwProj -c Release -nologo -v minimal "-p:NavisworksInstallDir=$NavisworksDir"
$nwBin = Join-Path $root 'addins\nwd\plugin-navis27\bin\Release\net48'
$bundle = Join-Path $out 'addins\Bimwright.Nwd.bundle'
New-Item -ItemType Directory -Force (Join-Path $bundle 'Contents\2027') | Out-Null
Get-ChildItem $nwBin -File | Where-Object { $_.Extension -in '.dll', '.pdb' } | Copy-Item -Destination (Join-Path $bundle 'Contents\2027')
# Nw24 = Navisworks 2027 (Nw22 = 2025), as in nwd-mcp's PackageContents template.
@'
<?xml version="1.0" encoding="utf-8"?>
<ApplicationPackage SchemaVersion="1.0" AppVersion="1.0.0" AutodeskProduct="Navisworks" Name="Bimwright.Nwd" Description="nwd plug-in (Navis-mcp build) for Autodesk Navisworks Manage 2027" ProductCode="{9B3F7B2D-1C4E-4D5F-9A6B-7E8C9D0F1A2B}">
  <CompanyDetails Name="Bimwright (built by Navis-mcp)" />
  <Components>
    <RuntimeRequirements OS="Win64" Platform="NAVMAN" SeriesMin="Nw24" SeriesMax="Nw24" />
    <ComponentEntry AppName="Bimwright.Nwd.Plugin.Navis27" AppType="ManagedPlugin" ModuleName="./Contents/2027/Bimwright.Nwd.Plugin.Navis27.dll" />
  </Components>
</ApplicationPackage>
'@ | Set-Content -Encoding UTF8 (Join-Path $bundle 'PackageContents.xml')
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
