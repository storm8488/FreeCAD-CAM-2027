# Desinstallation par utilisateur : supprime les raccourcis et le profil CAM2027.
# Les projets (.FCStd, .nc, bibliotheques exportees) ne sont jamais supprimes.
param([switch]$KeepProfile)
foreach ($dir in @([Environment]::GetFolderPath("Desktop"), (Join-Path ([Environment]::GetFolderPath("StartMenu")) "Programs"))) {
    $lnk = Join-Path $dir "CAM2027.lnk"
    if (Test-Path $lnk) { Remove-Item $lnk; Write-Host "Supprime : $lnk" }
}
$profile = Join-Path $env:LOCALAPPDATA "CAM2027"
if ((Test-Path $profile) -and -not $KeepProfile) {
    # La bibliotheque utilisateur vit dans le profil : on la sauvegarde a cote avant suppression.
    $lib = Get-ChildItem -Path $profile -Recurse -Filter "*.cam2027tools" -ErrorAction SilentlyContinue
    if ($lib) {
        $backup = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "CAM2027-library-backup"
        New-Item -ItemType Directory -Force $backup | Out-Null
        $lib | Copy-Item -Destination $backup -Force
        Write-Host "Bibliotheque(s) copiee(s) dans $backup"
    }
    Remove-Item -Recurse -Force $profile
    Write-Host "Profil supprime : $profile"
}
Write-Host "Termine. Les sources du depot et vos projets sont conserves."
