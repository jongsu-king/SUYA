; Inno Setup 6 script. Build after PyInstaller:  ISCC.exe packaging\windows\installer.iss
; Produces dist\SUYA-<version>-windows-x64-setup.exe

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#define AppName "SUYA"
#define AppPublisher "Jongsu Lim, Suyeon Park (Incheon National University)"
#define AppURL "https://github.com/jongsu-king/SUYA"
#define AppExeName "SUYA.exe"
#define SourceDir "..\..\dist\SUYA"

[Setup]
AppId={{6E1B0C2A-5C8F-4F5A-9C2E-7A3D1F0B2C44}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=..\..\LICENSE
OutputDir=..\..\dist
OutputBaseFilename=SUYA-{#AppVersion}-windows-x64-setup
SetupIconFile=..\icons\icon.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequiredOverridesAllowed=dialog
PrivilegesRequired=lowest
ChangesEnvironment=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 사용자 데이터(%APPDATA%\SUYA, 문서\SUYA)는 지우지 않습니다.
Type: filesandordirs; Name: "{app}\_internal"
