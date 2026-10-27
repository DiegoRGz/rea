# Compila Panorama360.exe y Panorama360-Setup.exe en Windows.
# Uso (desde PowerShell, en la carpeta panorama360):  .\desktop\build_windows.ps1 -Version 1.0.0
param([string]$Version = "1.0.0")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$build = Join-Path $root "build"
New-Item -ItemType Directory -Force $build | Out-Null

Write-Host "== Herramientas de compilacion"
if (-not (Test-Path "$build\venv-build")) { python -m venv "$build\venv-build" }
$py = "$build\venv-build\Scripts\python.exe"
& $py -m pip install --disable-pip-version-check -q pyinstaller==6.22.3 pywebview==6.2.1 uv==0.13.2 pillow numpy
if ($LASTEXITCODE -ne 0) { throw "pip install fallo" }

Write-Host "== Icono e imagenes del instalador"
& $py desktop\make_assets.py "$build\assets"
if ($LASTEXITCODE -ne 0) { throw "make_assets fallo" }

Write-Host "== Codigo de la aplicacion"
$src = "$build\app_src"
if (Test-Path $src) { Remove-Item -Recurse -Force $src }
New-Item -ItemType Directory -Force $src | Out-Null
Copy-Item app.py, requirements.txt -Destination $src
Copy-Item -Recurse config, panorama360 -Destination $src
Get-ChildItem -Path $src -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force
Copy-Item "$build\venv-build\Scripts\uv.exe" "$build\uv.exe" -Force

Write-Host "== Informacion de version del .exe"
$parts = ($Version.Split(".") + @("0", "0", "0", "0"))[0..3] -join ", "
@"
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($parts), prodvers=($parts)),
  kids=[
    StringFileInfo([StringTable('0C0A04B0', [
      StringStruct('CompanyName', 'Panorama 360'),
      StringStruct('FileDescription', 'Panorama 360 - Generador de panoramicas 360 con IA'),
      StringStruct('FileVersion', '$Version'),
      StringStruct('ProductName', 'Panorama 360'),
      StringStruct('ProductVersion', '$Version'),
      StringStruct('OriginalFilename', 'Panorama360.exe')])]),
    VarFileInfo([VarStruct('Translation', [3082, 1200])])
  ]
)
"@ | Set-Content -Encoding UTF8 "$build\version_info.txt"

Write-Host "== PyInstaller"
& $py -m PyInstaller --noconfirm --clean --windowed --onedir --name Panorama360 `
  --icon "$build\assets\icon.ico" --version-file "$build\version_info.txt" `
  --distpath "$build\dist" --workpath "$build\work" --specpath "$build" `
  --add-data "$root\desktop\splash.html;." --add-data "$src;app_src" --add-binary "$build\uv.exe;." `
  --paths "$root\desktop" desktop\launcher.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller fallo" }

Write-Host "== Instalador (Inno Setup)"
$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) {
  choco install innosetup -y --no-progress | Out-Null
  $iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
}
& $iscc "/DAppVersion=$Version" "/DBuildDir=$build" desktop\installer.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup fallo" }
Write-Host "Listo: $build\output\Panorama360-Setup.exe"
