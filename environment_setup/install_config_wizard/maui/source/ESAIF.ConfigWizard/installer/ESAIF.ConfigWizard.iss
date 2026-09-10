#ifndef Payload
  #error Payload must point to the self-contained publish directory
#endif
#ifndef ProductId
  #define ProductId "{A6B3C23C-9718-4E61-8CE5-823EAB0E5BCD}"
#endif

[Setup]
AppId={code:GetInstallAppId}
UsePreviousLanguage=no
AppName=Enterprise Scale AI Factory
AppVersion={#AppVersion}
AppVerName=Enterprise Scale AI Factory {#AppVersion}
AppPublisher=Enterprise Scale AI Factory
AppPublisherURL=https://github.com/jostrm/azure-enterprise-scale-ml
DefaultDirName={localappdata}\Programs\ESAIF.ConfigWizard
DefaultGroupName=Enterprise Scale AI Factory
AllowNoIcons=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0.22000
WizardStyle=modern
SetupIconFile={#AppIcon}
UninstallDisplayIcon={app}\ESAIF.ConfigWizard.exe
UninstallDisplayName=Enterprise Scale AI Factory
OutputBaseFilename=ESAIF.ConfigWizard-{#AppVersion}-win-x64-setup
VersionInfoVersion={#AppVersion}
Compression=lzma2/max
SolidCompression=yes
DiskSpanning=yes
DiskSliceSize=96000000
SlicesPerDisk=1
CloseApplications=yes
CloseApplicationsFilter=ESAIF.ConfigWizard.exe,aifactory-api.exe
RestartApplications=no
InfoBeforeFile=SUPPORT.txt

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "{#Payload}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.pdb,*.runtimeconfig.dev.json"

[Icons]
Name: "{group}\Enterprise Scale AI Factory"; Filename: "{app}\ESAIF.ConfigWizard.exe"; WorkingDir: "{app}"; Check: not IsSmokeTest
Name: "{group}\Uninstall Enterprise Scale AI Factory"; Filename: "{uninstallexe}"; Check: not IsSmokeTest
Name: "{userdesktop}\Enterprise Scale AI Factory"; Filename: "{app}\ESAIF.ConfigWizard.exe"; WorkingDir: "{app}"; Tasks: desktopicon; Check: not IsSmokeTest

[Run]
Filename: "{app}\ESAIF.ConfigWizard.exe"; Description: "Open Enterprise Scale AI Factory"; Flags: nowait postinstall skipifsilent

[Code]
function IsSmokeTest: Boolean;
begin
  Result := ExpandConstant('{param:SMOKETEST|0}') = '1';
end;

function GetInstallAppId(Param: String): String;
begin
  Result := '{#ProductId}';
  if IsSmokeTest then
    Result := Result + '-SmokeTest';
end;

function HasWebView2: Boolean;
var
  Version: String;
  ClientKey: String;
begin
  ClientKey := 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  Result := (RegQueryStringValue(HKLM32, ClientKey, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0')) or
    (RegQueryStringValue(HKLM64, ClientKey, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0')) or
    (RegQueryStringValue(HKCU, ClientKey, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0'));
end;

function InitializeSetup: Boolean;
begin
  if IsSmokeTest and (ExpandConstant('{param:DIR|}') = '') then
  begin
    MsgBox('Smoke tests require an explicit isolated /DIR.', mbError, MB_OK);
    Result := False;
    Exit;
  end;
  Result := HasWebView2;
  if not Result then
    MsgBox('Microsoft Edge WebView2 Runtime is required. Install the Evergreen x64 Runtime from https://developer.microsoft.com/microsoft-edge/webview2/ and run Setup again. No .NET or Python installation is needed for the desktop app.', mbError, MB_OK);
end;
