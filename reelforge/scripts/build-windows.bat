@echo off
REM Compila el instalador (.exe) de ReelForge Studio en Windows.
REM Requisitos: Node.js 20+ y Python 3.10-3.12 instalados y en el PATH.
setlocal
cd /d "%~dp0\.."
title Compilando ReelForge Studio

where npm >nul 2>nul
if errorlevel 1 (
  echo [X] No se encontro Node.js. Instalalo desde https://nodejs.org ^(version LTS^) y vuelve a ejecutar este archivo.
  goto :error
)
set "PY=py -3"
%PY% --version >nul 2>nul
if errorlevel 1 set "PY=python"
%PY% --version >nul 2>nul
if errorlevel 1 (
  echo [X] No se encontro Python. Instala Python 3.12 desde https://www.python.org marcando "Add python.exe to PATH".
  goto :error
)

echo [1/3] Instalando dependencias de Electron ^(la primera vez tarda unos minutos^)...
call npm install --no-audit --no-fund || goto :error

echo [2/3] Generando icono...
%PY% -m pip install --quiet --user pillow || goto :error
%PY% scripts\make_icon.py || goto :error

echo [3/3] Empaquetando...
set CSC_IDENTITY_AUTO_DISCOVERY=false
call npm run dist || goto :error

echo.
echo ============================================================
echo  Listo. El ejecutable esta en la carpeta "release":
echo    - ReelForge Studio Setup 1.0.0.exe  ^(instalador^)
echo    - ReelForgeStudio-1.0.0-portable.exe ^(sin instalar^)
echo ============================================================
explorer release
pause
goto :eof

:error
echo.
echo Algo fallo. Copia los mensajes de arriba para revisarlos.
pause
exit /b 1
