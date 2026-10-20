# SPDX-License-Identifier: LGPL-2.1-or-later
# Fabrique le logiciel autonome CAM2027 à partir d'une distribution FreeCAD 1.1.x portable :
#   - copie de FreeCAD SANS les modules inutiles (dossiers Mod\ et binaires lib\*.pyd supprimés) ;
#   - ajout du module CAM2027 ;
#   - bin\branding.xml : nom CAM2027, titre, icône, écran de démarrage, atelier de départ,
#     dossier de réglages propre (%APPDATA%\CAM2027), réglages par défaut ;
#   - exécutables CAM2027.exe (interface) et CAM2027Cmd.exe (console).
# Le FreeCAD source n'est jamais modifié.
#
# Usage : powershell -ExecutionPolicy Bypass -File scripts\build-distribution.ps1 [-Source <dossier>] [-Dest <dossier>]

param(
    [string]$Source = "$env:LOCALAPPDATA\CAM2027\FreeCAD-1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311",
    [string]$Dest = "$env:USERPROFILE\CAM2027",
    [string[]]$KeepExtra = @()
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

# Modules FreeCAD supprimés : ateliers de modélisation, calcul, dessin, etc.
# Chaque entrée a été retirée puis validée par les tests (voir docs\cam2027\DISTRIBUTION.md).
$Remove = @(
    "AddonManager", "Assembly", "BIM", "Fem", "Help", "Idf", "Inspection", "OpenSCAD", "Plot", "Points",
    "ReverseEngineering", "Robot", "Spreadsheet", "Start", "Surface", "TechDraw", "Test", "Tux", "Web", "Measure"
) | Where-Object { $KeepExtra -notcontains $_ }

# Binaires associés (lib\*.pyd) par module
$Binaries = @{
    "Assembly" = @("AssemblyApp.pyd", "AssemblyGui.pyd")
    "Fem" = @("Fem.pyd", "FemGui.pyd")
    "Inspection" = @("Inspection.pyd", "InspectionGui.pyd")
    "Points" = @("Points.pyd", "PointsGui.pyd")
    "ReverseEngineering" = @("ReverseEngineering.pyd", "ReverseEngineeringGui.pyd")
    "Robot" = @("Robot.pyd", "RobotGui.pyd")
    # Spreadsheet.pyd et Measure.pyd gardés : TechDraw.pyd est lié à ces deux binaires
    "Spreadsheet" = @("SpreadsheetGui.pyd")
    "Start" = @("Start.pyd", "StartGui.pyd")
    "Surface" = @("Surface.pyd", "SurfaceGui.pyd")
    # TechDraw.pyd est gardé : l'ébauche adaptative appelle TechDraw.findShapeOutline (calcul pur) ;
    # l'atelier (Mod\TechDraw) et son interface (TechDrawGui.pyd) sont supprimés.
    "TechDraw" = @("TechDrawGui.pyd")
    "Web" = @("Web.pyd", "WebGui.pyd")
    "Measure" = @("MeasureGui.pyd")
}

if (-not (Test-Path "$Source\bin\FreeCAD.exe")) { throw "FreeCAD introuvable dans $Source" }

Write-Host "Copie de FreeCAD vers $Dest (sans les modules supprimés)..."
if (Test-Path $Dest) { Remove-Item -Recurse -Force $Dest }
New-Item -ItemType Directory -Force $Dest | Out-Null
$excludeDirs = $Remove | ForEach-Object { Join-Path "$Source\Mod" $_ }
robocopy $Source $Dest /E /NFL /NDL /NJH /NJS /NP /XD $excludeDirs | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy a échoué ($LASTEXITCODE)" }

foreach ($m in $Remove) {
    if ($Binaries.ContainsKey($m)) {
        foreach ($f in $Binaries[$m]) {
            $p = Join-Path "$Dest\lib" $f
            if (Test-Path $p) { Remove-Item -Force $p }
        }
    }
}

Write-Host "Ajout du module CAM2027..."
robocopy "$Root\src\Mod\CAM2027" "$Dest\Mod\CAM2027" /E /NFL /NDL /NJH /NJS /NP /XD "__pycache__" "screenshots" | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy CAM2027 a échoué ($LASTEXITCODE)" }

Write-Host "Identité du logiciel (branding)..."
New-Item -ItemType Directory -Force "$Dest\branding" | Out-Null
Copy-Item "$Root\src\Mod\CAM2027\Resources\branding\*" "$Dest\branding\" -Force
$version = [regex]::Match((Get-Content "$Root\src\Mod\CAM2027\cam2027\version.py" -Raw), '__version__ = "([^"]+)"').Groups[1].Value
$brandingXml = (Get-Content "$Root\src\Mod\CAM2027\Resources\branding\branding.xml" -Raw -Encoding UTF8).Replace("@VERSION@", $version)
[System.IO.File]::WriteAllText("$Dest\bin\branding.xml", $brandingXml, (New-Object System.Text.UTF8Encoding($false)))
Remove-Item "$Dest\branding\branding.xml" -ErrorAction SilentlyContinue

Copy-Item "$Dest\bin\FreeCAD.exe" "$Dest\bin\CAM2027.exe" -Force
Copy-Item "$Dest\bin\FreeCADCmd.exe" "$Dest\bin\CAM2027Cmd.exe" -Force

Write-Host "Icône Windows (.ico 16 à 256 px)..."
$env:CAM2027_ICON_SRC = "$Dest\branding\cam2027-icon.png"
$env:CAM2027_ICON_OUT = "$Dest\branding\cam2027.ico"
& "$Dest\bin\CAM2027Cmd.exe" "$Root\scripts\make-icon.py" 2>&1 | Out-Null
if (-not (Test-Path "$Dest\branding\cam2027.ico")) { Write-Warning "icône .ico non générée" }

$size = (Get-ChildItem $Dest -Recurse -File | Measure-Object Length -Sum).Sum / 1MB
$mods = (Get-ChildItem "$Dest\Mod" -Directory | Select-Object -ExpandProperty Name) -join ", "
Write-Host ("CAM2027 prêt : {0}  ({1:N0} Mo)" -f $Dest, $size)
Write-Host ("Modules présents : {0}" -f $mods)
