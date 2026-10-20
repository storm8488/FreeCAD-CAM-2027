# Désinstallation par utilisateur de CAM2027.
#   - supprime les raccourcis Bureau / menu Démarrer ;
#   - supprime les profils (%LOCALAPPDATA%\CAM2027\home du lanceur, %APPDATA%\CAM2027 du logiciel)
#     après avoir copié les bibliothèques d'outils dans Documents\CAM2027-library-backup ;
#   - avec -RemoveApp, supprime aussi le logiciel autonome (%USERPROFILE%\CAM2027).
# Les projets (.FCStd, .nc, bibliothèques exportées) ne sont jamais supprimés, ni aucun FreeCAD installé.
param([switch]$KeepProfile, [switch]$RemoveApp, [string]$App = "$env:USERPROFILE\CAM2027")

foreach ($dir in @([Environment]::GetFolderPath("Desktop"), (Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs"))) {
    $lnk = Join-Path $dir "CAM2027.lnk"
    if (Test-Path $lnk) { Remove-Item $lnk; Write-Host "Supprimé : $lnk" }
}
if (-not $KeepProfile) {
    $backup = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "CAM2027-library-backup"
    foreach ($profile in @((Join-Path $env:LOCALAPPDATA "CAM2027\home"), (Join-Path $env:APPDATA "CAM2027"))) {
        if (-not (Test-Path $profile)) { continue }
        $lib = Get-ChildItem -Path $profile -Recurse -Filter "*.cam2027tools" -ErrorAction SilentlyContinue
        if ($lib) {
            New-Item -ItemType Directory -Force $backup | Out-Null
            $lib | Copy-Item -Destination $backup -Force
            Write-Host "Bibliothèque(s) copiée(s) dans $backup"
        }
        Remove-Item -Recurse -Force $profile
        Write-Host "Profil supprimé : $profile"
    }
}
if ($RemoveApp -and (Test-Path (Join-Path $App "bin\CAM2027.exe"))) {
    Remove-Item -Recurse -Force $App
    Write-Host "Logiciel supprimé : $App"
}
Write-Host "Terminé. Les sources du dépôt et vos projets sont conservés."
