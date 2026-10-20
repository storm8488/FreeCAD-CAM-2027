# SPDX-License-Identifier: LGPL-2.1-or-later
# Étape 3 : compile le fork (FreeCAD 1.1.4 + module CAM2027) avec seulement les modules que garde CAM2027.
#
# Prérequis (installés une fois) : Visual Studio 2022 Build Tools (C++, SDK Windows), CMake 3.31.6,
# LibPack FreeCAD 1.1.0 v3.1.1.3 (même version que la CI du tag 1.1.4), sous-modules GSL et OndselSolver.
#
# Usage : powershell -ExecutionPolicy Bypass -File scripts\build-from-source.ps1 [-Work D:\CAM2027-build] [-Step configure|build|install|all]
# Résultat : <Work>\install (arborescence FreeCAD compilée) ; la distribution CAM2027 se fabrique ensuite avec
#   scripts\build-distribution.ps1 -Source <Work>\install

param(
    [string]$Work = "D:\CAM2027-build",
    [string]$LibPack = "",
    [string]$CMake = "",
    [ValidateSet("configure", "build", "install", "all")][string]$Step = "all",
    [int]$Jobs = 0
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not $LibPack) { $LibPack = Join-Path $Work "libpack\LibPack-1.1.0-v3.1.1.3-Release" }
if (-not $CMake) { $CMake = Join-Path $Work "tools\cmake-3.31.6-windows-x86_64\bin\cmake.exe" }
if (-not $Jobs) { $Jobs = [Environment]::ProcessorCount }
$Build = Join-Path $Work "build"
$Install = Join-Path $Work "install"
$Icon = Join-Path $Work "cam2027.ico"

foreach ($p in @($LibPack, $CMake, (Join-Path $Root "src\3rdParty\GSL\include"))) {
    if (-not (Test-Path $p)) { throw "introuvable : $p" }
}
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$vs = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vs) { throw "Visual Studio 2022 avec les outils C++ introuvable" }

# icône des exécutables : celle de CAM2027 (même fabrication que la distribution)
if (-not (Test-Path $Icon)) {
    $fc = "$env:LOCALAPPDATA\CAM2027\FreeCAD-1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311\bin\FreeCADCmd.exe"
    if (-not (Test-Path $fc)) { $fc = "$env:USERPROFILE\CAM2027\bin\CAM2027Cmd.exe" }
    $env:CAM2027_ICON_SRC = Join-Path $Root "src\Mod\CAM2027\Resources\branding\cam2027-icon.png"
    $env:CAM2027_ICON_OUT = $Icon
    & $fc (Join-Path $Root "scripts\make-icon.py") | Out-Null
    if (-not (Test-Path $Icon)) { throw "icône non générée : $Icon" }
}

# Modules : ceux de la distribution CAM2027 (CAM, Part, Mesh, MeshPart, Draft, Import, Material, Show,
# Sketcher, PartDesign) et leurs dépendances de compilation (TechDraw, Spreadsheet, Measure : Draft et
# l'ébauche adaptative en ont besoin). Tout le reste est désactivé.
$off = @("BUILD_FEM", "BUILD_BIM", "BUILD_ADDONMGR", "BUILD_HELP", "BUILD_IDF", "BUILD_INSPECTION", "BUILD_OPENSCAD",
         "BUILD_ASSEMBLY", "BUILD_PLOT", "BUILD_POINTS", "BUILD_REVERSEENGINEERING", "BUILD_ROBOT", "BUILD_START",
         "BUILD_TEST", "BUILD_TUX", "BUILD_WEB", "BUILD_SURFACE", "BUILD_FLAT_MESH", "BUILD_JTREADER",
         "BUILD_DESIGNER_PLUGIN", "ENABLE_DEVELOPER_TESTS")
$on = @("BUILD_GUI", "BUILD_CAM", "BUILD_PART", "BUILD_MESH", "BUILD_MESH_PART", "BUILD_DRAFT", "BUILD_IMPORT",
        "BUILD_MATERIAL", "BUILD_SHOW", "BUILD_SKETCHER", "BUILD_PART_DESIGN", "BUILD_TECHDRAW", "BUILD_SPREADSHEET",
        "BUILD_MEASURE")

if ($Step -in @("configure", "all")) {
    $defs = @("-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_POLICY_VERSION_MINIMUM=3.5", "-DFREECAD_USE_PCH=OFF",
              "-DFREECAD_RELEASE_PDB=OFF", "-DCMAKE_VS_NO_COMPILE_BATCHING=ON",
              "-DFREECAD_LIBPACK_DIR=$LibPack", "-DFREECAD_COPY_DEPEND_DIRS_TO_BUILD=ON",
              "-DFREECAD_COPY_LIBPACK_BIN_TO_BUILD=ON", "-DFREECAD_COPY_PLUGINS_BIN_TO_BUILD=ON",
              "-DCMAKE_INSTALL_PREFIX=$Install", "-DFREECAD_APP_ICON=$Icon")
    $defs += $off | ForEach-Object { "-D$_=OFF" }
    $defs += $on | ForEach-Object { "-D$_=ON" }
    & $CMake -S $Root -B $Build -G "Visual Studio 17 2022" -A x64 @defs
    if ($LASTEXITCODE -ne 0) { throw "configuration CMake échouée ($LASTEXITCODE)" }
}
if ($Step -in @("build", "all")) {
    & $CMake --build $Build --config Release --parallel $Jobs -- /p:TrackFileAccess=false /nologo /verbosity:minimal
    if ($LASTEXITCODE -ne 0) { throw "compilation échouée ($LASTEXITCODE)" }
}
if ($Step -in @("install", "all")) {
    & $CMake --install $Build --config Release
    if ($LASTEXITCODE -ne 0) { throw "installation échouée ($LASTEXITCODE)" }
}
Write-Host "Terminé : $Step (construction : $Build ; installation : $Install)"
