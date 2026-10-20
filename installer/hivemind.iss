; Hivemind's Windows installer (RL6i): Hivemind-Setup.exe, a normal
; Next / Install / Finish wizard, per user (no admin prompt), into
; %LOCALAPPDATA%\Programs\Hivemind, with Start-menu and desktop shortcuts and
; an uninstaller in Settings > Apps.
;
; Built by installer\build.ps1, which passes the three defines below:
;   AppVersion  pyproject.toml's version (numbers only: x.y.z)
;   AppDir      the built app folder (python\ src\ scripts\ data\ tesseract\)
;   Images      the folder make_icon.py wrote hivemind.ico and the wizard bitmaps to

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef AppDir
  #define AppDir "build\app"
#endif
#ifndef Images
  #define Images "build"
#endif

#ifdef Preview
; THE UI PREVIEW (the owner, 2026-10-22: "a test UI for people to look at and
; see if they like. like no features or anything"): the app opens only the
; built-in demo (--demo: invented numbers under a DEMO banner) and Start is off
; there (gui/window._start). Its own name, AppId and folder, so it installs
; beside a real Hivemind and never upgrades or removes it.
  #define AppName "Hivemind UI Preview"
#else
  #define AppName "Hivemind"
#endif
; The taskbar identity: the same string as APP_ID in src\hivemind\gui\app.py,
; so the window groups under the shortcut's Hivemind icon, not Python's.
#define AppUserModel "Hivemind.Hivemind"
#define Launcher "{app}\python\pythonw.exe"
; -X utf8: the GUI reads data/ with read_text(); without UTF-8 mode Python
; reads cp1252 here. MEASURED 2026-10-22 on the built app: bees.yaml,
; stickbug.yaml and a README raised UnicodeDecodeError, five more read
; garbled; with -X utf8, none. (The bot itself gets PYTHONUTF8=1 already,
; gui/launcher UTF8_ENV.)
#ifdef Preview
  #define LaunchArgs "-X utf8 -m hivemind.gui --demo --loop"
#else
  #define LaunchArgs "-X utf8 -m hivemind.gui"
#endif

[Setup]
; NEVER CHANGE the AppId: Windows matches upgrades and the uninstaller by it.
#ifdef Preview
; NEVER CHANGE either AppId (the preview's is its own, made 2026-10-22).
AppId={{1CF3DC13-FAEE-4BCC-8CA2-B57D32633B92}
#else
AppId={{15800294-2D34-42D4-B241-0FB5EDD39B41}
#endif
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Project Hivemind
AppComments=Autonomous Bee Swarm Simulator player
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoDescription={#AppName} Setup
; Per user: no UAC prompt; {autopf} is then %LOCALAPPDATA%\Programs.
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#AppName}
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Windows 10 1903: the first with window capture (Windows Graphics Capture).
MinVersion=10.0.18362
#ifdef Preview
OutputBaseFilename=Hivemind-UI-Preview
#else
#ifdef Split
; For sending over Telegram (bots upload at most 50 MB): its own NAME, so it is
; never mistaken for the one-file installer (2026-10-22: the owner ran a split
; Hivemind-Setup.exe without its -3.bin and got "Please insert Disk 3").
; Hivemind-Setup-PARTS.exe plus -PARTS-1.bin, -2.bin ... of 45 MB, one folder.
OutputBaseFilename=Hivemind-Setup-PARTS
DiskSpanning=yes
DiskSliceSize=45000000
#else
OutputBaseFilename=Hivemind-Setup
#endif
#endif
SetupIconFile={#Images}\hivemind.ico
UninstallDisplayIcon={app}\hivemind.ico
UninstallDisplayName={#AppName}
WizardStyle=modern
DisableWelcomePage=no
WizardImageFile={#Images}\wizard-large-100.bmp,{#Images}\wizard-large-200.bmp
WizardSmallImageFile={#Images}\wizard-small-100.bmp,{#Images}\wizard-small-200.bmp
Compression=lzma2/max
SolidCompression=yes
; A running Hivemind holds python\*.dll open: Setup offers to close it.
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[InstallDelete]
; An upgrade gets a fresh copy of the program, so a file removed upstream does
; not linger. var\ (the bot's logs and what it has learned) is never touched.
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\src"
Type: filesandordirs; Name: "{app}\scripts"
Type: filesandordirs; Name: "{app}\data"
Type: filesandordirs; Name: "{app}\tesseract"

[Files]
Source: "{#AppDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; THE SAFE FIRST RUN: settings.yaml only when there is none (an upgrade or a
; reinstall keeps the user's), and the same file as a preset to go back to.
; {localappdata}\Hivemind is datapaths.config_dir() on Windows (platformdirs).
Source: "{#AppDir}\data\presets\safe-first-run.yaml"; DestDir: "{localappdata}\Hivemind"; DestName: "settings.yaml"; Flags: onlyifdoesntexist uninsneveruninstall
Source: "{#AppDir}\data\presets\safe-first-run.yaml"; DestDir: "{localappdata}\Hivemind\presets"; DestName: "Safe first run.yaml"; Flags: onlyifdoesntexist uninsneveruninstall

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{#Launcher}"; Parameters: "{#LaunchArgs}"; WorkingDir: "{app}"; IconFilename: "{app}\hivemind.ico"; AppUserModelID: "{#AppUserModel}"; Comment: "Hivemind, the Bee Swarm Simulator bot"
Name: "{autodesktop}\{#AppName}"; Filename: "{#Launcher}"; Parameters: "{#LaunchArgs}"; WorkingDir: "{app}"; IconFilename: "{app}\hivemind.ico"; AppUserModelID: "{#AppUserModel}"; Comment: "Hivemind, the Bee Swarm Simulator bot"; Tasks: desktopicon

[Run]
Filename: "{#Launcher}"; Parameters: "{#LaunchArgs}"; WorkingDir: "{app}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; What Python wrote beside the installed files (__pycache__, comtypes' generated
; modules). var\ stays: the user's logs and learning, like their settings in
; %LOCALAPPDATA%\Hivemind; delete the folder by hand to remove those too.
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\src"
Type: filesandordirs; Name: "{app}\scripts"
Type: filesandordirs; Name: "{app}\data"
Type: filesandordirs; Name: "{app}\tesseract"
#ifdef Preview
; The preview's own throwaway settings and var (datapaths.use_demo_dirs,
; platformdirs' user_data_dir "Hivemind Demo" = %LOCALAPPDATA%\Hivemind Demo):
; nothing in them is the user's, so they go with it.
Type: filesandordirs; Name: "{localappdata}\Hivemind Demo"
Type: filesandordirs; Name: "{app}\var"
#endif

[Code]
// OWNER 2026-10-20: "make it look for a original copy or atleast update old copy".
// An earlier INSTALL upgrades in place by AppId (same folder, var\ kept). An old
// PORTABLE kit (the .bat zip) keeps its var\ (logs, what the bot learned) in its
// own folder: find it in Downloads / Desktop / Documents and copy var\ across
// when this install has none yet. Settings live in %LOCALAPPDATA%\Hivemind for
// both, so they are already shared.
var OldKit: String;

function IsKit(Dir: String): Boolean;
begin
  Result := FileExists(Dir + '\Start Hivemind.bat') and DirExists(Dir + '\src\hivemind');
end;

function FindKitIn(Base: String; Depth: Integer): String;
var FR: TFindRec;
begin
  Result := '';
  if IsKit(Base) then begin Result := Base; exit; end;
  if Depth = 0 then exit;
  if FindFirst(Base + '\*', FR) then
  try
    repeat
      if (FR.Attributes and FILE_ATTRIBUTE_DIRECTORY <> 0) and (FR.Name <> '.') and (FR.Name <> '..') then
      begin
        Result := FindKitIn(Base + '\' + FR.Name, Depth - 1);
        if Result <> '' then exit;
      end;
    until not FindNext(FR);
  finally
    FindClose(FR);
  end;
end;

procedure CopyTree(Src, Dst: String);
var FR: TFindRec;
begin
  ForceDirectories(Dst);
  if FindFirst(Src + '\*', FR) then
  try
    repeat
      if (FR.Name <> '.') and (FR.Name <> '..') then
        if FR.Attributes and FILE_ATTRIBUTE_DIRECTORY <> 0 then
          CopyTree(Src + '\' + FR.Name, Dst + '\' + FR.Name)
        else
          CopyFile(Src + '\' + FR.Name, Dst + '\' + FR.Name, False);
    until not FindNext(FR);
  finally
    FindClose(FR);
  end;
end;

function InitializeSetup(): Boolean;
var Home: String;
begin
  Home := GetEnv('USERPROFILE');
  OldKit := FindKitIn(Home + '\Downloads', 3);
  if OldKit = '' then OldKit := FindKitIn(Home + '\Desktop', 3);
  if OldKit = '' then OldKit := FindKitIn(Home + '\Documents', 3);
#ifdef Preview
  OldKit := '';      // the UI preview is a demo: it takes nothing from an old kit
#endif
  Result := True;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and (OldKit <> '') and DirExists(OldKit + '\var')
     and not DirExists(ExpandConstant('{app}\var')) then
  begin
    CopyTree(OldKit + '\var', ExpandConstant('{app}\var'));
    if not WizardSilent then
      MsgBox('Found your old Hivemind in' + #13#10 + OldKit + #13#10#13#10 +
             'Your settings and what it learned were carried over. ' +
             'You can delete that old folder now.', mbInformation, MB_OK);
  end;
end;
