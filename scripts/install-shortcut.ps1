# Installe (par utilisateur) un raccourci "CAM2027" sur le Bureau et dans le menu Demarrer.
# N'installe rien dans Program Files et ne touche pas a l'installation FreeCAD existante.
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$launcher = Join-Path $root "scripts\cam2027.cmd"
$icon = Join-Path $root "src\Mod\CAM2027\Resources\icons\CAM2027.ico"
if (-not (Test-Path $launcher)) { throw "Lanceur introuvable : $launcher" }
$shell = New-Object -ComObject WScript.Shell
foreach ($dir in @([Environment]::GetFolderPath("Desktop"), (Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs"))) {
    $lnk = Join-Path $dir "CAM2027.lnk"
    $s = $shell.CreateShortcut($lnk)
    $s.TargetPath = $launcher
    $s.WorkingDirectory = (Join-Path $root "scripts")
    $s.Description = "CAM2027 - FreeCAD CAM workbench (separate profile)"
    if (Test-Path $icon) { $s.IconLocation = $icon }
    $s.Save()
    Write-Host "Raccourci cree : $lnk"
}
