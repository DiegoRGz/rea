@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo  === Panorama 360: instalacion ===
echo.

set "PY="
where py >nul 2>&1 && (py -3.12 -c "" >nul 2>&1 && set "PY=py -3.12")
if not defined PY where py >nul 2>&1 && (py -3.11 -c "" >nul 2>&1 && set "PY=py -3.11")
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY (
  echo No se encontro Python. Instala Python 3.11 o 3.12 desde https://www.python.org/downloads/
  echo y marca la casilla "Add python.exe to PATH". Luego vuelve a ejecutar este archivo.
  pause
  exit /b 1
)

if not exist .venv (
  echo Creando entorno virtual en .venv ...
  %PY% -m venv .venv || goto :error
)
set "VPY=.venv\Scripts\python.exe"
%VPY% -m pip install --upgrade pip || goto :error

where nvidia-smi >nul 2>&1
if %errorlevel%==0 (
  echo GPU NVIDIA detectada: instalando PyTorch con CUDA ...
  %VPY% -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128 || goto :error
) else (
  echo No se detecto GPU NVIDIA: instalando PyTorch para CPU (sera lento^) ...
  %VPY% -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu || goto :error
)
%VPY% -m pip install -r requirements.txt || goto :error

echo.
echo  Listo. Ejecuta iniciar.bat para abrir la aplicacion.
echo  (La primera generacion descarga el modelo elegido, unos 7 GB.)
pause
exit /b 0

:error
echo.
echo  La instalacion fallo. Revisa el mensaje de arriba.
pause
exit /b 1
