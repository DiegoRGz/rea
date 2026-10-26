@echo off
REM Compila el instalador (.exe) de ReelForge Studio en Windows.
REM Requisitos: Node.js 20+ y Python 3.10-3.12 con Pillow (pip install pillow).
setlocal
cd /d "%~dp0\.."
echo [1/3] Instalando dependencias de Electron...
call npm install || goto :error
echo [2/3] Generando icono...
python scripts\make_icon.py || py -3 scripts\make_icon.py || goto :error
echo [3/3] Empaquetando...
call npm run dist || goto :error
echo.
echo Listo. Instalador y version portable en la carpeta "release".
explorer release
goto :eof
:error
echo.
echo Algo fallo. Revisa los mensajes anteriores.
pause
exit /b 1
