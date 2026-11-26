#define AppName "다운로드 정리"
#define Publisher "Downloads Organizer Team"
#define ProjectURL "https://github.com/downloads-organizer-team/downloads-organizer"

[Setup]
AppId={{BD44DEAC-A699-4C71-B471-9ABE30C90184}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#Publisher}
AppPublisherURL={#ProjectURL}
AppSupportURL={#ProjectURL}/issues
VersionInfoVersion={#AppVersion}.0
VersionInfoProductName={#AppName}
DefaultDirName={localappdata}\Programs\Downloads Organizer
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
WizardStyle=modern
SetupIconFile={#Stage}\desktop\assets\downloads.ico
UninstallDisplayIcon={app}\desktop\assets\downloads.ico
UninstallDisplayName={#AppName}
OutputBaseFilename=Downloads-Organizer-{#AppVersion}-Setup-x64
Compression=lzma2/fast
SolidCompression=yes
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Files]
Source: "{#Stage}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\runtime\organizer.exe"; WorkingDir: "{app}"; IconFilename: "{app}\desktop\assets\downloads.ico"

[Run]
Filename: "{app}\runtime\organizer.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; WorkingDir: "{app}"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{app}\python\python.exe"; Parameters: "-B -X utf8 ""{app}\browser_bridge.py"" --unregister"; WorkingDir: "{app}"; Flags: runhidden skipifdoesntexist; RunOnceId: "UnregisterBrowserBridge"
