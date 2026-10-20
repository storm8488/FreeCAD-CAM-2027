@echo off
rem Lanceur CAM2027 : FreeCAD avec l'atelier CAM2027 et une configuration separee
rem de l'installation FreeCAD habituelle (profil utilisateur dans %LOCALAPPDATA%\CAM2027).
setlocal
set "ROOT=%~dp0.."
rem Priorite : FREECAD_BIN, puis la 1.1.4 portable installee a part, puis l'installation 1.0.
set "FC114=%LOCALAPPDATA%\CAM2027\FreeCAD-1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311\bin"
if "%FREECAD_BIN%"=="" if exist "%FC114%\FreeCAD.exe" set "FREECAD_BIN=%FC114%"
if "%FREECAD_BIN%"=="" set "FREECAD_BIN=C:\Program Files\FreeCAD 1.0\bin"
if not exist "%FREECAD_BIN%\FreeCAD.exe" (
  echo FreeCAD.exe introuvable dans "%FREECAD_BIN%". Definir la variable FREECAD_BIN.
  pause
  exit /b 2
)
set "CAM2027_HOME=%LOCALAPPDATA%\CAM2027"
if not exist "%CAM2027_HOME%\home" mkdir "%CAM2027_HOME%\home"
if not exist "%CAM2027_HOME%\home\user.cfg" copy /y "%ROOT%\scripts\user.cfg.template" "%CAM2027_HOME%\home\user.cfg" >nul
rem FREECAD_USER_HOME isole preferences, macros et modules supplementaires.
set "FREECAD_USER_HOME=%CAM2027_HOME%\home"
set "CAM2027_LANG=fr"
start "" "%FREECAD_BIN%\FreeCAD.exe" -l -M "%ROOT%\src\Mod\CAM2027" %*
