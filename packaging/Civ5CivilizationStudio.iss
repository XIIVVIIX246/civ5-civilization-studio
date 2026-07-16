#ifndef AppVersion
  #error AppVersion must be supplied by build_installer.ps1
#endif
#ifndef SourceDir
  #error SourceDir must be supplied by build_installer.ps1
#endif
#ifndef AppExeName
  #error AppExeName must be supplied by build_installer.ps1
#endif
#ifndef OutputDir
  #error OutputDir must be supplied by build_installer.ps1
#endif

#define AppName "Civ V Civilization Studio"
#define AppPublisher "Civ V Modding Tools"
#define AppProjectType "Civ5Studio.Project"

[Setup]
AppId={{0B84C47C-C0C9-4A49-A7B6-8E47D7F9630D}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\Civ V Civilization Studio
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ChangesAssociations=yes
OutputDir={#OutputDir}
OutputBaseFilename=Civ5-Civilization-Studio-{#AppVersion}-Setup
UninstallDisplayIcon={app}\{#AppExeName}
SetupLogging=yes
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}
VersionInfoVersion={#AppVersion}

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Registry]
; Register as an Open With application for JSON without hijacking all .json files.
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExeName}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExeName}"" ""%1"""; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExeName}\SupportedTypes"; ValueType: string; ValueName: ".json"; ValueData: ""; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Civ V Modding Tools\Civ5Studio"; ValueType: string; ValueName: "InstallPath"; ValueData: "{app}"; Flags: uninsdeletekey

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
