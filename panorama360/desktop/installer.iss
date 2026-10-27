; Instalador de Panorama 360 (Inno Setup 6). Lo compila build_windows.ps1:
;   ISCC.exe /DAppVersion=1.0.0 /DBuildDir=..\build installer.iss

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef BuildDir
  #define BuildDir "..\build"
#endif

[Setup]
AppId={{8F2B6C1E-3D4A-4B9E-9A51-0360D0360360}
AppName=Panorama 360
AppVersion={#AppVersion}
AppVerName=Panorama 360 {#AppVersion}
AppPublisher=Panorama 360
DefaultDirName={localappdata}\Programs\Panorama360
DefaultGroupName=Panorama 360
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#BuildDir}\output
OutputBaseFilename=Panorama360-Setup
SetupIconFile={#BuildDir}\assets\icon.ico
UninstallDisplayIcon={app}\Panorama360.exe
UninstallDisplayName=Panorama 360
WizardStyle=modern
WizardImageFile={#BuildDir}\assets\wizard.bmp,{#BuildDir}\assets\wizard@2x.bmp
WizardSmallImageFile={#BuildDir}\assets\wizard_small.bmp,{#BuildDir}\assets\wizard_small@2x.bmp
Compression=lzma2/ultra64
SolidCompression=yes
CloseApplications=yes

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#BuildDir}\dist\Panorama360\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Panorama 360"; Filename: "{app}\Panorama360.exe"
Name: "{autodesktop}\Panorama 360"; Filename: "{app}\Panorama360.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Panorama360.exe"; Description: "{cm:LaunchProgram,Panorama 360}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Entorno de Python y PyTorch que crea la app (varios GB). Tus panoramicas en Imagenes\Panorama360 se conservan.
Type: filesandordirs; Name: "{localappdata}\Panorama360"
