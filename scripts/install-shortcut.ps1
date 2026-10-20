# Installe (par utilisateur) les raccourcis "CAM2027" sur le Bureau et dans le menu Démarrer.
# Cible : le logiciel autonome fabriqué par build-distribution.ps1 (%USERPROFILE%\CAM2027\bin\CAM2027.exe).
# Repli : le lanceur de développement (scripts\cam2027.cmd) si la distribution n'existe pas.
# N'installe rien dans Program Files et ne touche à aucune installation FreeCAD.
param([string]$App = "$env:USERPROFILE\CAM2027")

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$exe = Join-Path $App "bin\CAM2027.exe"
if (Test-Path $exe) {
    $target = $exe
    $workdir = Join-Path $App "bin"
    $icon = Join-Path $App "branding\cam2027.ico"
    $description = "CAM2027 - FAO / usinage CNC"
} else {
    $target = Join-Path $root "scripts\cam2027.cmd"
    $workdir = Join-Path $root "scripts"
    $icon = Join-Path $root "src\Mod\CAM2027\Resources\icons\CAM2027.ico"
    $description = "CAM2027 (lanceur de développement)"
    Write-Host "Distribution absente ($exe) : raccourci vers le lanceur de développement."
}
$shell = New-Object -ComObject WScript.Shell
foreach ($dir in @([Environment]::GetFolderPath("Desktop"), (Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs"))) {
    $lnk = Join-Path $dir "CAM2027.lnk"
    $s = $shell.CreateShortcut($lnk)
    $s.TargetPath = $target
    $s.WorkingDirectory = $workdir
    $s.Description = $description
    if (Test-Path $icon) { $s.IconLocation = $icon }
    $s.Save()
    Write-Host "Raccourci créé : $lnk -> $target"
}
