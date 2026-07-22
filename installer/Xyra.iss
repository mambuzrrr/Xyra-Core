#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceExe
  #define SourceExe "..\release_artifacts\Xyra.exe"
#endif
#ifndef OutputDir
  #define OutputDir "..\release_artifacts"
#endif

[Setup]
AppId={{B9B47477-D71F-49DC-A269-E708A0217426}
AppName=Xyra
AppVersion={#AppVersion}
AppPublisher=Brejax
AppPublisherURL=https://github.com/mambuzrrr/Xyra-Core
AppSupportURL=https://github.com/mambuzrrr/Xyra-Core/issues
DefaultDirName={autopf}\Xyra
DefaultGroupName=Xyra
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#OutputDir}
OutputBaseFilename=Xyra-Setup-{#AppVersion}-x64
SetupIconFile=..\assets\xyra.ico
UninstallDisplayIcon={app}\Xyra.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
DisableProgramGroupPage=yes

[Files]
Source: "{#SourceExe}"; DestDir: "{app}"; DestName: "Xyra.exe"; Flags: ignoreversion

[Icons]
Name: "{group}\Xyra"; Filename: "{app}\Xyra.exe"
Name: "{autodesktop}\Xyra"; Filename: "{app}\Xyra.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Run]
Filename: "{app}\Xyra.exe"; Description: "Launch Xyra"; Flags: nowait postinstall skipifsilent
