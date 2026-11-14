#ifndef Payload
  #error Payload must point to a validated self-contained publish
#endif
#ifdef LocalPreview
  #ifndef DevelopmentOnly
    #error LocalPreview requires DevelopmentOnly
  #endif
#endif
#ifndef ProductId
  #define ProductId "{B781D214-B734-49AD-931C-41EAE3BA87A2}"
#endif
#ifndef DevelopmentOnly
  #ifndef SignedBuild
    #error Unsigned output must be explicitly DevelopmentOnly
  #endif
#endif
#ifdef DevelopmentOnly
  #define DisplayName "ESAIF Tutorials (DEVELOPMENT-ONLY)"
#else
  #define DisplayName "ESAIF Tutorials"
#endif

[Setup]
AppId={{#ProductId}
AppName={#DisplayName}
AppVersion={#AppVersion}
AppVerName={#DisplayName} {#AppVersion}
AppPublisher=Asom Records AB
AppPublisherURL=https://github.com/jostrm/azure-enterprise-scale-ml
DefaultDirName={localappdata}\Programs\ESAIF.TutorialApp
DefaultGroupName=ESAIF Tutorials
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0.22000
DisableProgramGroupPage=yes
DisableDirPage=yes
UsePreviousAppDir=no
CloseApplications=no
RestartApplications=no
UninstallDisplayIcon={app}\versions\{#AppVersion}\ESAIF.TutorialApp.exe
OutputDir={#OutputDirectory}
OutputBaseFilename={#OutputName}
VersionInfoVersion={#AppVersion}
Compression=lzma2
SolidCompression=yes
DiskSpanning=no
InfoBeforeFile={#SupportFile}
#ifdef SignedBuild
SignTool=TutorialSign
SignedUninstaller=yes
SignToolRetryCount=2
#endif

[Files]
#ifdef LocalPreview
Source: "{#Payload}\*"; DestDir: "{app}\versions\{#AppVersion}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.pdb,*.pfx,*.p12,tutorialsettings*.json"
#else
Source: "{#Payload}\*"; DestDir: "{app}\versions\{#AppVersion}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.pdb,*.pfx,*.p12,Tutorials\*,tutorialcatalog.json,tutorialsettings*.json,previewcode*.json"
#endif

[Icons]
Name: "{group}\ESAIF Tutorials"; Filename: "{app}\versions\{#AppVersion}\ESAIF.TutorialApp.exe"; WorkingDir: "{app}\versions\{#AppVersion}"
Name: "{group}\Uninstall ESAIF Tutorials"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\versions\{#AppVersion}\ESAIF.TutorialApp.exe"; Description: "Open ESAIF Tutorials"; Flags: nowait postinstall skipifsilent

[Code]
function CompareVersions(const Left, Right: String): Integer;
var
  L, R, I, LV, RV: Integer;
  LS, RS: String;
begin
  LS := Left + '.';
  RS := Right + '.';
  Result := 0;
  for I := 1 to 4 do
  begin
    L := Pos('.', LS);
    R := Pos('.', RS);
    LV := StrToIntDef(Copy(LS, 1, L - 1), 0);
    RV := StrToIntDef(Copy(RS, 1, R - 1), 0);
    if LV < RV then begin Result := -1; Exit; end;
    if LV > RV then begin Result := 1; Exit; end;
    if L > 0 then Delete(LS, 1, L);
    if R > 0 then Delete(RS, 1, R);
  end;
end;

function InitializeSetup: Boolean;
var
  ExistingVersion: String;
begin
  Result := True;
  if RegQueryStringValue(HKCU,
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\{#ProductId}_is1',
    'DisplayVersion', ExistingVersion) then
  begin
    if (CompareVersions('{#AppVersion}', ExistingVersion) < 0) and
       (ExpandConstant('{param:ALLOWDOWNGRADE|0}') <> '1') then
    begin
      MsgBox('A newer ESAIF Tutorials version is installed. Back up your settings/progress and obtain state-compatibility approval before using /ALLOWDOWNGRADE=1. Uninstall/reinstall is the explicit clean-binary rollback option; personal data is retained.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if CompareText(ExpandConstant('{app}'), ExpandConstant('{localappdata}\Programs\ESAIF.TutorialApp')) <> 0 then
    Result := 'Install only in the TutorialApp-owned per-user directory. Custom /DIR overrides are not supported.';
end;
