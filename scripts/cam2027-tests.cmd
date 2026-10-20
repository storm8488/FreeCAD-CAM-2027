@echo off
rem Lance les tests CAM2027 dans FreeCADCmd (sans interface).
rem Usage : scripts\cam2027-tests.cmd [test_tools] [test_pipeline] ...
setlocal
set "ROOT=%~dp0.."
rem Priorite : FREECAD_BIN, puis la 1.1.4 portable installee a part, puis l'installation 1.0.
set "FC114=%LOCALAPPDATA%\CAM2027\FreeCAD-1.1.4\FreeCAD_1.1.4-Windows-x86_64-py311\bin"
if "%FREECAD_BIN%"=="" if exist "%FC114%\FreeCADCmd.exe" set "FREECAD_BIN=%FC114%"
if "%FREECAD_BIN%"=="" set "FREECAD_BIN=C:\Program Files\FreeCAD 1.0\bin"
if not exist "%FREECAD_BIN%\FreeCADCmd.exe" (
  echo FreeCADCmd.exe introuvable dans "%FREECAD_BIN%". Definir FREECAD_BIN.
  exit /b 2
)
"%FREECAD_BIN%\FreeCADCmd.exe" -M "%ROOT%\src\Mod\CAM2027" "%ROOT%\src\Mod\CAM2027\tests\run_all.py" %*
exit /b %ERRORLEVEL%
