#define AppName "Filo"
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
DefaultDirName={localappdata}\Programs\Filo
DefaultGroupName={#AppName}
UsePreviousGroup=no
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
WizardStyle=modern
SetupIconFile={#Stage}\desktop\assets\downloads.ico
UninstallDisplayIcon={app}\desktop\assets\downloads.ico
UninstallDisplayName={#AppName}
OutputBaseFilename=Filo-{#AppVersion}-Setup-x64
Compression=lzma2/fast
SolidCompression=yes
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Files]
Source: "{#Stage}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs

[InstallDelete]
Type: files; Name: "{userprograms}\다운로드 정리\다운로드 정리.lnk"; Check: OwnsLegacyShortcut
Type: dirifempty; Name: "{userprograms}\다운로드 정리"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\runtime\organizer.exe"; WorkingDir: "{app}"; AppUserModelID: "DownloadsOrganizer.Filo"; IconFilename: "{app}\desktop\assets\downloads.ico"

[Run]
Filename: "{app}\runtime\organizer.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; WorkingDir: "{app}"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{app}\python\python.exe"; Parameters: "-B -X utf8 -m organizer.browser.browser_bridge --unregister"; WorkingDir: "{app}"; Flags: runhidden skipifdoesntexist; RunOnceId: "UnregisterBrowserBridge"


[Code]
function OwnsLegacyShortcut: Boolean;
var
  Link: String;
  Shell, Shortcut: Variant;
begin
  Result := False;
  Link := ExpandConstant('{userprograms}\다운로드 정리\다운로드 정리.lnk');
  if not FileExists(Link) then Exit;
  try
    Shell := CreateOleObject('WScript.Shell');
    Shortcut := Shell.CreateShortcut(Link);
    Result := CompareText(Shortcut.TargetPath, ExpandConstant('{app}\runtime\organizer.exe')) = 0;
  except
    Log('Could not verify legacy shortcut ownership.');
  end;
end;
