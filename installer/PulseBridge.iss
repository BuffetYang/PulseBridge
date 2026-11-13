; PulseBridge per-user installer (Inno Setup 6)
; Build:
;   ISCC.exe /DMyAppVersion=2.5.0 installer\PulseBridge.iss
; The build script scripts\build_windows.py does this automatically.

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

#define MyAppName "PulseBridge"
#define MyAppPublisher "BuffetYang"
#define MyAppURL "https://github.com/BuffetYang/PulseBridge"
#define MyAppExeName "PulseBridge.exe"

[Setup]
AppId={{B5D3E4F2-9C1A-4F7E-8B2D-6A1C3E5F7A90}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={localappdata}\Programs\PulseBridge
DefaultGroupName=PulseBridge
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist\installer
OutputBaseFilename=PulseBridge-Setup-{#MyAppVersion}
SetupIconFile=..\assets\pulsebridge.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
LicenseFile=..\LICENSE
InfoAfterFile=..\THIRD_PARTY_NOTICES.md
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
UsePreviousAppDir=yes
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} 健康数据看板
VersionInfoVersion={#MyAppVersion}.0

[Languages]
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"; Flags: unchecked

[Files]
Source: "..\dist\PulseBridge\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\PulseBridge"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\卸载 PulseBridge"; Filename: "{uninstallexe}"
Name: "{autodesktop}\PulseBridge"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 PulseBridge"; Flags: nowait postinstall skipifsilent
