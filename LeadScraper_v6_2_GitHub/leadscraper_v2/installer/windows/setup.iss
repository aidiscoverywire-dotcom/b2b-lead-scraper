; Inno Setup script — builds Setup_LeadScraper_v6.exe
; Compile with:  "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" setup.iss
; (or just run build-windows.bat — it does everything)

#define MyAppName "B2B AI Lead Scraper"
#define MyAppVersion "1.6.2"
#define MyAppPublisher "LeadScraper"
#define MyAppExeName "LeadScraper.exe"

[Setup]
AppId={{8F3A2B1C-4D5E-4F6A-9B0C-1D2E3F4A5B6C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\LeadScraper
DefaultGroupName=LeadScraper
; Per-user install — no admin rights needed
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename=Setup_LeadScraper_v6_2
SetupIconFile=assets\app.ico
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Double-click setup.exe -> Next -> Next -> Install -> Finish. That's it.

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; PyInstaller output folder (build-windows.bat creates it)
Source: "..\..\dist\LeadScraper\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\B2B AI Lead Scraper"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Reset Password"; Filename: "{app}\ResetPassword.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\B2B AI Lead Scraper"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Run]
; Offer to launch right after install
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,B2B AI Lead Scraper}"; Flags: nowait postinstall skipifsilent shellexec
