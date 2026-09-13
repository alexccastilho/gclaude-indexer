; GClaude Indexer — Windows installer.
;
; A shell around install.ps1, not a replacement for it: that script already
; installs Python 3.12, Tesseract, Ghostscript, Ollama and the model, with
; every download's SHA-256 verified. What did not exist before this file is
; an identity for Windows (the Programs and Features entry), a graphical
; face, and a silent contract for winget.
;
; Design: docs/superpowers/specs/2026-09-13-fase-19-instalador-windows-design.md
;
; AppVersion is passed by build.ps1, which reads it from web/app.py. Never
; write a version literal here — two copies of a version drift.

#ifndef AppVersion
  #error AppVersion must be passed with /DAppVersion=x.y.z
#endif

#define AppName "GClaude Indexer"
#define AppPublisher "Alex Camacho Castilho"
#define AppURL "https://github.com/alexccastilho/gclaude-indexer"

[Setup]
; This GUID must never change: it is what makes a new version recognise an
; old one as an upgrade instead of installing alongside it.
AppId={{8F3A6C21-7E4D-4B19-9C2A-1D5E8F0B7A34}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
OutputBaseFilename=GClaude-Indexer-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; The GPL-3.0 text itself, not an EULA. An added restriction would be
; incompatible with the licence this software is distributed under, so the
; acceptance page shows the licence the user is receiving, not terms being
; imposed on them.
LicenseFile=..\LICENSE
; Lowest by default so a silent run never triggers UAC — winget runs
; unelevated, and a prompt in the middle of a silent install is the
; opposite of the contract. The dialog lets an interactive user pick "for
; everyone" and elevate once.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
UninstallDisplayIcon={app}\logo.ico
UninstallDisplayName={#AppName}
SetupIconFile=..\logo.ico
DisableProgramGroupPage=yes
; Shown on the last page, where a first-time user is most likely to read it.
InfoAfterFile=

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[CustomMessages]
brazilianportuguese.OptionalGroup=Opcionais:
brazilianportuguese.DownloadModel=Baixar agora o modelo de classificação local (cerca de 3,2 GB)
brazilianportuguese.CpuSensorShortcut=Criar também o atalho do sensor de CPU
brazilianportuguese.InstallingDeps=Instalando dependências. Isto pode levar vários minutos.
brazilianportuguese.KeepCollections=Os acervos que você já indexou NÃO serão apagados, e a sua lista de projetos também não. Os acervos ficam nas pastas de saída que você escolheu, fora da pasta de instalação.
brazilianportuguese.RemoveDeps=Remover também Tesseract, Ghostscript, Ollama e Python 3.12
brazilianportuguese.DepsFailed=O aplicativo foi instalado, mas nem toda dependência pôde ser instalada. Abra o aplicativo e veja a tela Sobre para o diagnóstico.
brazilianportuguese.OpenLog=Deseja abrir o registro da instalação para ver o que houve?

english.OptionalGroup=Optional:
english.DownloadModel=Download the local classification model now (about 3.2 GB)
english.CpuSensorShortcut=Also create the CPU sensor shortcut
english.InstallingDeps=Installing dependencies. This can take several minutes.
english.KeepCollections=Collections you have already indexed will NOT be deleted, and neither will your project list. The collections live in the output folders you chose, outside the installation folder.
english.RemoveDeps=Also remove Tesseract, Ghostscript, Ollama and Python 3.12
english.DepsFailed=The application was installed, but not every dependency could be. Open the application and check the About screen for the diagnosis.
english.OpenLog=Do you want to open the installation log to see what happened?

spanish.OptionalGroup=Opcionales:
spanish.DownloadModel=Descargar ahora el modelo de clasificación local (unos 3,2 GB)
spanish.CpuSensorShortcut=Crear también el acceso directo del sensor de CPU
spanish.InstallingDeps=Instalando dependencias. Esto puede tardar varios minutos.
spanish.KeepCollections=Las colecciones que ya indexó NO se eliminarán, ni tampoco su lista de proyectos. Las colecciones están en las carpetas de salida que usted eligió, fuera de la carpeta de instalación.
spanish.RemoveDeps=Eliminar también Tesseract, Ghostscript, Ollama y Python 3.12
spanish.DepsFailed=La aplicación se instaló, pero no todas las dependencias pudieron instalarse. Abra la aplicación y consulte la pantalla Acerca de para el diagnóstico.
spanish.OpenLog=¿Desea abrir el registro de instalación para ver qué ocurrió?

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
; Unchecked on purpose, with the size in the label: gigabytes started
; without being asked for is how an installation someone expected to take a
; minute becomes twenty.
Name: "downloadmodel"; Description: "{cm:DownloadModel}"; GroupDescription: "{cm:OptionalGroup}"; Flags: unchecked
Name: "cpusensor"; Description: "{cm:CpuSensorShortcut}"; GroupDescription: "{cm:OptionalGroup}"; Flags: unchecked

[Files]
Source: "..\gclaude_indexer\*"; DestDir: "{app}\gclaude_indexer"; Flags: recursesubdirs ignoreversion; Excludes: "__pycache__,*.pyc"
Source: "..\config\*"; DestDir: "{app}\config"; Flags: recursesubdirs ignoreversion
Source: "..\docs\*"; DestDir: "{app}\docs"; Flags: recursesubdirs ignoreversion
Source: "..\install.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\uninstall.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\Indexer.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\Indexer.vbs"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\Desinstalar.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\launcher.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\run_server.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\CHANGELOG.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\SECURITY.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\logo.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; Created here, not by install.ps1 (which is called with -NoShortcut), so
; that uninstalling removes them. A shortcut created outside the
; installer's control survives as an orphan pointing at a folder that is
; no longer there.
Name: "{group}\{#AppName}"; Filename: "{app}\Indexer.vbs"; IconFilename: "{app}\logo.ico"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\Indexer.vbs"; IconFilename: "{app}\logo.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\Indexer.vbs"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: postinstall nowait skipifsilent shellexec

[Code]
var
  StatusFilePath: String;
  DoneFilePath: String;
  LogFilePath: String;
  DepsExitCode: Integer;
  RemoveDepsCheckBox: TNewCheckBox;
  DepsPage: TOutputProgressWizardPage;

function BuildCommandLine(): String;
var
  Args: String;
begin
  { -NoShortcut on purpose: the [Icons] section owns the shortcuts so that
    uninstalling removes them. }
  Args := '-NoProfile -ExecutionPolicy Bypass -File ""' + ExpandConstant('{app}\install.ps1') + '""'
        + ' -AutoInstall -NoShortcut'
        + ' -StatusFile ""' + StatusFilePath + '""';
  if WizardIsTaskSelected('cpusensor') then
    Args := Args + ' -CpuSensorShortcut';
  if not WizardIsTaskSelected('downloadmodel') then
    Args := Args + ' -SkipModelDownload';

  { Through cmd, for two things Exec alone cannot give us.

    The log: the script's output used to be discarded, and the first time
    it failed on a user's machine the only way to find out why was to
    reproduce it by hand. A three-thousand-line script that installs five
    third-party programs must leave a record.

    The sentinel: Exec with ewNoWait returns no handle, so there is no way
    to ask "has it finished?". Writing the exit code to a file at the end
    answers both that and "did it succeed", and lets the loop below keep
    the window alive and the progress moving while the script runs. }
  Result := '/c ""powershell.exe" ' + Args + ' > ""' + LogFilePath + '"" 2>&1'
          + ' & echo %ERRORLEVEL% > ""' + DoneFilePath + '"""';
end;

procedure ReadProgress();
var
  Lines: TArrayOfString;
  Head: String;
  SepA, SepB, Step, Total: Integer;
begin
  { A missing or unreadable file means "no news yet", never an error:
    progress is a courtesy and must not be able to fail an installation. }
  if not FileExists(StatusFilePath) then
    exit;
  if not LoadStringsFromFile(StatusFilePath, Lines) then
    exit;
  if GetArrayLength(Lines) < 2 then
    exit;

  { First line is "<step>|<total>|<key>" — the machine-readable half of
    the contract in the phase 19 design, section 6.2. }
  Head := Lines[0];
  SepA := Pos('|', Head);
  if SepA = 0 then
    exit;
  SepB := SepA + Pos('|', Copy(Head, SepA + 1, Length(Head)));
  if SepB <= SepA then
    exit;

  Step := StrToIntDef(Copy(Head, 1, SepA - 1), 0);
  Total := StrToIntDef(Copy(Head, SepA + 1, SepB - SepA - 1), 0);
  if (Step <= 0) or (Total <= 0) then
    exit;

  { SetProgress repaints the page itself, which is why this uses an output
    progress page rather than the wizard's own bar: Inno's Pascal Script
    exposes no message pump, so a loop that only assigned to a label would
    leave the window frozen and blank for the whole install. }
  DepsPage.SetText(Lines[1], Format('%d / %d', [Step, Total]));
  DepsPage.SetProgress(Step, Total);
end;

function ReadExitCode(): Integer;
var
  Lines: TArrayOfString;
begin
  Result := -1;
  if not LoadStringsFromFile(DoneFilePath, Lines) then
    exit;
  if GetArrayLength(Lines) >= 1 then
    Result := StrToIntDef(Trim(Lines[0]), -1);
end;

function RunDependencyInstall(): Integer;
var
  ResultCode: Integer;
  Waited: Integer;
begin
  StatusFilePath := ExpandConstant('{tmp}\gclaude-status.txt');
  DoneFilePath := ExpandConstant('{tmp}\gclaude-done.txt');
  // Deliberately not in the temporary folder, which the installer wipes on
  // exit: the log is wanted precisely when something went wrong, which is
  // after the wizard has closed. Line comments here on purpose — a brace
  // comment cannot contain a constant like the one below, because the
  // constant's own closing brace would end the comment.
  LogFilePath := ExpandConstant('{localappdata}\GClaudeIndexer\install-log.txt');
  ForceDirectories(ExpandConstant('{localappdata}\GClaudeIndexer'));

  DepsPage.SetText(ExpandConstant('{cm:InstallingDeps}'), '');
  DepsPage.SetProgress(0, 8);
  DepsPage.Show();

  if not Exec(ExpandConstant('{cmd}'), BuildCommandLine(), ExpandConstant('{app}'),
              SW_HIDE, ewNoWait, ResultCode) then
  begin
    DepsPage.Hide();
    Result := -1;
    exit;
  end;

  { Poll rather than block. ewWaitUntilTerminated would freeze the window
    for as long as the downloads take, which on a fresh machine is several
    minutes of a wizard that looks hung — and the progress this whole
    mechanism exists to show would never be read until it was too late to
    matter. }
  Waited := 0;
  while not FileExists(DoneFilePath) do
  begin
    Sleep(400);
    Waited := Waited + 400;
    ReadProgress();
    { Four hours. Not a guess at how long installing should take, but a
      ceiling on how long this loop may spin if the sentinel never
      appears — a machine on a slow link downloading a multi-gigabyte
      model is legitimate, a lost child process is not. }
    if Waited > 14400000 then
    begin
      DepsPage.Hide();
      Result := -2;
      exit;
    end;
  end;

  ReadProgress();
  DepsPage.Hide();
  Result := ReadExitCode();
end;

procedure InitializeWizard();
begin
  DepsPage := CreateOutputProgressPage(
    ExpandConstant('{cm:InstallingDeps}'), '');
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep <> ssPostInstall then
    exit;

  DepsExitCode := RunDependencyInstall();

  { A non-zero exit means an essential component is missing. The
    application stays installed: it is still usable in a degraded state,
    its own About screen reports what is absent, and removing it here
    would take the diagnosis away along with the app. }
  if (DepsExitCode <> 0) and (not WizardSilent) then
  begin
    if MsgBox(ExpandConstant('{cm:DepsFailed}') + #13#10#13#10
              + ExpandConstant('{cm:OpenLog}') + #13#10 + LogFilePath,
              mbError, MB_YESNO) = IDYES then
      ShellExec('open', LogFilePath, '', '', SW_SHOW, ewNoWait, DepsExitCode);
  end;
end;

procedure InitializeUninstallProgressForm();
var
  Page: TNewNotebookPage;
  Explanation: TNewStaticText;
begin
  { A silent uninstall has no form; CurUninstallStepChanged then finds the
    checkbox unassigned and keeps the dependencies, which is the
    conservative side. }
  if UninstallSilent then
    exit;

  Page := UninstallProgressForm.InnerPage;

  Explanation := TNewStaticText.Create(UninstallProgressForm);
  Explanation.Parent := Page;
  Explanation.Top := UninstallProgressForm.StatusLabel.Top + ScaleY(40);
  Explanation.Width := Page.ClientWidth;
  Explanation.WordWrap := True;
  Explanation.AutoSize := True;
  Explanation.Caption := ExpandConstant('{cm:KeepCollections}');

  RemoveDepsCheckBox := TNewCheckBox.Create(UninstallProgressForm);
  RemoveDepsCheckBox.Parent := Page;
  RemoveDepsCheckBox.Top := Explanation.Top + Explanation.Height + ScaleY(12);
  RemoveDepsCheckBox.Width := Page.ClientWidth;
  RemoveDepsCheckBox.Height := ScaleY(17);
  RemoveDepsCheckBox.Checked := False;
  RemoveDepsCheckBox.Caption := ExpandConstant('{cm:RemoveDeps}');
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Args: String;
  ResultCode: Integer;
  Script: String;
begin
  if CurUninstallStep <> usUninstall then
    exit;

  Script := ExpandConstant('{app}\uninstall.ps1');
  if not FileExists(Script) then
    exit;

  { Assigned() guards the silent path, where the form was never built. }
  if Assigned(RemoveDepsCheckBox) and RemoveDepsCheckBox.Checked then
    Args := '-RemoveAll'
  else
    Args := '-KeepDependencies';

  Exec('powershell.exe',
       '-NoProfile -ExecutionPolicy Bypass -File "' + Script + '" ' + Args,
       ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;
