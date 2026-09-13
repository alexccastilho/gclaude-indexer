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
brazilianportuguese.RemoveDepsAsk=Deseja remover TAMBÉM o Tesseract, o Ghostscript, o Ollama e o Python 3.12?%n%nResponda Não se outro programa desta máquina usar algum deles.
brazilianportuguese.DepsFailed=O aplicativo foi instalado, mas nem toda dependência pôde ser instalada. Abra o aplicativo e veja a tela Sobre para o diagnóstico.
brazilianportuguese.OpenLog=Deseja abrir o registro da instalação para ver o que houve?
brazilianportuguese.UninstallIntro=O GClaude Indexer será removido. Marque abaixo o que deve sair junto — deixe desmarcado o que outro programa desta máquina usar.
brazilianportuguese.CompTesseract=Tesseract (OCR) e os dados de idioma
brazilianportuguese.CompGhostscript=Ghostscript
brazilianportuguese.CompOllama=Ollama (o servidor de modelos)
brazilianportuguese.CompModels=Modelos já baixados do Ollama (vários GB; rebaixar leva horas)
brazilianportuguese.CompPython=Python 3.12
brazilianportuguese.DepsPageTitle=Dependências
brazilianportuguese.DepsPageSubtitle=O que será baixado e instalado junto
brazilianportuguese.DepsPageText=Tudo é baixado e instalado automaticamente, sem abrir nenhuma janela de comando. As duas primeiras são obrigatórias: sem elas o sistema não consegue ler páginas digitalizadas.
brazilianportuguese.DepTesseract=Tesseract (OCR) e o idioma português — obrigatório
brazilianportuguese.DepGhostscript=Ghostscript (tratamento de PDF) — obrigatório
brazilianportuguese.DepOllama=Ollama (classificação com modelo local)
brazilianportuguese.DepModel=Modelo padrão de classificação (cerca de 3,2 GB)
brazilianportuguese.DepSensors=Bibliotecas de sensor (temperatura, potência, relógios)
brazilianportuguese.DepCpuSensor=Atalho do sensor de CPU na área de trabalho

english.OptionalGroup=Optional:
english.DownloadModel=Download the local classification model now (about 3.2 GB)
english.CpuSensorShortcut=Also create the CPU sensor shortcut
english.InstallingDeps=Installing dependencies. This can take several minutes.
english.KeepCollections=Collections you have already indexed will NOT be deleted, and neither will your project list. The collections live in the output folders you chose, outside the installation folder.
english.RemoveDeps=Also remove Tesseract, Ghostscript, Ollama and Python 3.12
english.RemoveDepsAsk=Do you also want to remove Tesseract, Ghostscript, Ollama and Python 3.12?%n%nAnswer No if another program on this machine uses any of them.
english.DepsFailed=The application was installed, but not every dependency could be. Open the application and check the About screen for the diagnosis.
english.OpenLog=Do you want to open the installation log to see what happened?
english.UninstallIntro=GClaude Indexer will be removed. Tick below whatever should go with it — leave unticked anything another program on this machine uses.
english.CompTesseract=Tesseract (OCR) and its language data
english.CompGhostscript=Ghostscript
english.CompOllama=Ollama (the model server)
english.CompModels=Models already downloaded by Ollama (several GB; re-downloading takes hours)
english.CompPython=Python 3.12
english.DepsPageTitle=Dependencies
english.DepsPageSubtitle=What will be downloaded and installed alongside
english.DepsPageText=Everything is downloaded and installed automatically, without opening any command window. The first two are required: without them the system cannot read a scanned page.
english.DepTesseract=Tesseract (OCR) and the Portuguese language data — required
english.DepGhostscript=Ghostscript (PDF handling) — required
english.DepOllama=Ollama (classification with a local model)
english.DepModel=Default classification model (about 3.2 GB)
english.DepSensors=Sensor libraries (temperature, power, clocks)
english.DepCpuSensor=CPU sensor shortcut on the desktop

spanish.OptionalGroup=Opcionales:
spanish.DownloadModel=Descargar ahora el modelo de clasificación local (unos 3,2 GB)
spanish.CpuSensorShortcut=Crear también el acceso directo del sensor de CPU
spanish.InstallingDeps=Instalando dependencias. Esto puede tardar varios minutos.
spanish.KeepCollections=Las colecciones que ya indexó NO se eliminarán, ni tampoco su lista de proyectos. Las colecciones están en las carpetas de salida que usted eligió, fuera de la carpeta de instalación.
spanish.RemoveDeps=Eliminar también Tesseract, Ghostscript, Ollama y Python 3.12
spanish.RemoveDepsAsk=¿Desea eliminar TAMBIÉN Tesseract, Ghostscript, Ollama y Python 3.12?%n%nResponda No si otro programa de esta máquina usa alguno de ellos.
spanish.DepsFailed=La aplicación se instaló, pero no todas las dependencias pudieron instalarse. Abra la aplicación y consulte la pantalla Acerca de para el diagnóstico.
spanish.OpenLog=¿Desea abrir el registro de instalación para ver qué ocurrió?
spanish.UninstallIntro=GClaude Indexer será eliminado. Marque abajo lo que debe irse con él — deje sin marcar lo que otro programa de esta máquina use.
spanish.CompTesseract=Tesseract (OCR) y sus datos de idioma
spanish.CompGhostscript=Ghostscript
spanish.CompOllama=Ollama (el servidor de modelos)
spanish.CompModels=Modelos ya descargados por Ollama (varios GB; volver a descargarlos lleva horas)
spanish.CompPython=Python 3.12
spanish.DepsPageTitle=Dependencias
spanish.DepsPageSubtitle=Qué se descargará e instalará junto
spanish.DepsPageText=Todo se descarga e instala automáticamente, sin abrir ninguna ventana de comandos. Las dos primeras son obligatorias: sin ellas el sistema no puede leer una página escaneada.
spanish.DepTesseract=Tesseract (OCR) y el idioma portugués — obligatorio
spanish.DepGhostscript=Ghostscript (tratamiento de PDF) — obligatorio
spanish.DepOllama=Ollama (clasificación con modelo local)
spanish.DepModel=Modelo de clasificación predeterminado (unos 3,2 GB)
spanish.DepSensors=Bibliotecas de sensor (temperatura, potencia, relojes)
spanish.DepCpuSensor=Acceso directo del sensor de CPU en el escritorio

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
; The model and the CPU-sensor shortcut used to live here. They moved to the
; Dependencies page, where the rest of what gets downloaded is listed: a
; person deciding whether to spend 3.2 GB should see that choice next to
; the other four, not two pages away from them.

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
const
  { Positions on the dependency page. Named because Values[3] read out of
    context says nothing about which 3.2 GB it is deciding. }
  DEP_TESSERACT = 0;
  DEP_GHOSTSCRIPT = 1;
  DEP_OLLAMA = 2;
  DEP_MODEL = 3;
  DEP_SENSORS = 4;
  DEP_CPUSENSOR = 5;

var
  StatusFilePath: String;
  DoneFilePath: String;
  LogFilePath: String;
  DepsExitCode: Integer;
  RemoveComponents: String;
  DepsPage: TOutputProgressWizardPage;
  DepsChoicePage: TInputOptionWizardPage;

function QuoteForPowerShell(const Value: String): String;
var
  Escaped: String;
begin
  { Single quotes, because a single-quoted PowerShell string takes its
    contents literally and a Windows path is full of backslashes. A folder
    may legitimately contain an apostrophe (C:\Users\O'Brien), and there
    the quote has to be doubled. }
  Escaped := Value;
  StringChangeEx(Escaped, '''', '''''', True);
  Result := '''' + Escaped + '''';
end;

function WriteRunnerScript(const Target, Args, LogPath, DonePath: String): String;
var
  Lines: TArrayOfString;
begin
  { A generated .ps1, and no cmd.exe anywhere.

    What was here before built one long
    `cmd /c ""powershell.exe" -File ""<path>"" ..."` string. The doubled
    quotes that cmd's own parsing needs did not survive PowerShell's: with
    the default folder — C:\Program Files\GClaude Indexer — PowerShell was
    handed -File 'C:\Program', refused it, and fell through to its
    interactive prompt. That is the black window a user reported, standing
    in front of an installation where not one dependency had been
    installed. Both the install and the uninstall went through that same
    command line, which is why both failed the same way.

    A file cannot have its quoting mangled in transit. It also writes the
    sentinel itself, which is the honest version of cmd's
    `& echo %ERRORLEVEL%`: that one ran whether or not PowerShell had ever
    started, and reported success for a script that never existed. }
  Result := ExpandConstant('{tmp}\gclaude-run.ps1');

  SetArrayLength(Lines, 10);
  Lines[0] := '$ErrorActionPreference = ''Continue''';
  Lines[1] := '$code = 1';
  Lines[2] := 'try {';
  { `*>&1 | Out-File -Encoding utf8`, not a bare `*>`. The bare form writes
    UTF-16, and the catch below appends UTF-8 — so the one log anybody ever
    reads, the one from a run that failed, would be half in each encoding.
    Piping every stream through Out-File settles on one. }
  Lines[3] := '  & ' + QuoteForPowerShell(Target) + ' ' + Args +
              ' *>&1 | Out-File -LiteralPath ' + QuoteForPowerShell(LogPath) +
              ' -Encoding utf8';
  Lines[4] := '  if ($null -ne $LASTEXITCODE) { $code = $LASTEXITCODE } else { $code = 0 }';
  Lines[5] := '} catch {';
  Lines[6] := '  $_ | Out-String | Out-File -LiteralPath ' +
              QuoteForPowerShell(LogPath) + ' -Append -Encoding utf8';
  Lines[7] := '  $code = 1';
  Lines[8] := '}';
  Lines[9] := 'Set-Content -LiteralPath ' + QuoteForPowerShell(DonePath) +
              ' -Value $code';

  SaveStringsToFile(Result, Lines, False);
end;

function RunnerCommandLine(const RunnerPath: String): String;
begin
  { -NonInteractive is the belt to the braces: with it, anything that tries
    to read from the console fails immediately instead of waiting forever
    behind a hidden window. -WindowStyle Hidden is PowerShell's own, asked
    for in addition to SW_HIDE because the two are enforced at different
    layers and only one of them survived the last attempt. }
  Result := '-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass'
          + ' -File "' + RunnerPath + '"';
end;

function PowerShellPath(): String;
begin
  { By absolute path, not by name: PATH is inherited from whatever launched
    the installer, and this must not depend on it. }
  Result := ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe');
end;

function DependencyWanted(Index: Integer): Boolean;
begin
  { Before the page exists — a silent install, for instance — everything
    optional is wanted. A silent install has nobody to ask, and answering
    "no" on their behalf would install less than the person asked for. }
  if DepsChoicePage = nil then
    Result := True
  else
    Result := DepsChoicePage.Values[Index];
end;

function BuildScriptArguments(): String;
var
  Args: String;
begin
  { -NoShortcut on purpose: the [Icons] section owns the shortcuts so that
    uninstalling removes them. }
  Args := '-AutoInstall -NoShortcut -StatusFile ' + QuoteForPowerShell(StatusFilePath);
  if DependencyWanted(DEP_CPUSENSOR) then
    Args := Args + ' -CpuSensorShortcut';
  if not DependencyWanted(DEP_MODEL) then
    Args := Args + ' -SkipModelDownload';
  if not DependencyWanted(DEP_OLLAMA) then
    Args := Args + ' -SkipOllama';
  if not DependencyWanted(DEP_SENSORS) then
    Args := Args + ' -SkipSensors';

  Result := Args;
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
  Runner: String;
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

  Runner := WriteRunnerScript(ExpandConstant('{app}\install.ps1'),
                             BuildScriptArguments(), LogFilePath, DoneFilePath);

  if not Exec(PowerShellPath(), RunnerCommandLine(Runner), ExpandConstant('{app}'),
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

  DepsChoicePage := CreateInputOptionPage(wpSelectTasks,
    ExpandConstant('{cm:DepsPageTitle}'),
    ExpandConstant('{cm:DepsPageSubtitle}'),
    ExpandConstant('{cm:DepsPageText}'), False, False);

  DepsChoicePage.Add(ExpandConstant('{cm:DepTesseract}'));
  DepsChoicePage.Add(ExpandConstant('{cm:DepGhostscript}'));
  DepsChoicePage.Add(ExpandConstant('{cm:DepOllama}'));
  DepsChoicePage.Add(ExpandConstant('{cm:DepModel}'));
  DepsChoicePage.Add(ExpandConstant('{cm:DepSensors}'));
  DepsChoicePage.Add(ExpandConstant('{cm:DepCpuSensor}'));

  { Ticked and greyed out rather than hidden. Without OCR and Ghostscript
    the program cannot read a scanned page, which is the entire job, so
    they are not a choice — but they are still the two biggest downloads
    and someone watching a progress bar deserves to know they are coming. }
  DepsChoicePage.Values[DEP_TESSERACT] := True;
  DepsChoicePage.Values[DEP_GHOSTSCRIPT] := True;
  DepsChoicePage.CheckListBox.ItemEnabled[DEP_TESSERACT] := False;
  DepsChoicePage.CheckListBox.ItemEnabled[DEP_GHOSTSCRIPT] := False;

  DepsChoicePage.Values[DEP_OLLAMA] := True;
  DepsChoicePage.Values[DEP_SENSORS] := True;

  { Unticked, with the size in the label: gigabytes started without being
    asked for is how an installation someone expected to take a minute
    becomes twenty. }
  DepsChoicePage.Values[DEP_MODEL] := False;
  DepsChoicePage.Values[DEP_CPUSENSOR] := False;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  { The model is downloaded by Ollama. Offering it while Ollama is
    unticked would promise something the installer cannot deliver. }
  if (DepsChoicePage <> nil) and (CurPageID = DepsChoicePage.ID) then
    DepsChoicePage.CheckListBox.ItemEnabled[DEP_MODEL] :=
      DepsChoicePage.Values[DEP_OLLAMA];
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

function AddComponentBox(Owner: TSetupForm; Parent: TWinControl; Caption: String;
                         var Top: Integer): TNewCheckBox;
begin
  Result := TNewCheckBox.Create(Owner);
  Result.Parent := Parent;
  Result.Left := ScaleX(8);
  Result.Top := Top;
  Result.Width := Parent.ClientWidth - ScaleX(24);
  Result.Height := ScaleY(19);
  Result.Checked := False;
  Result.Caption := Caption;
  Top := Top + ScaleY(23);
end;

function InitializeUninstall(): Boolean;
var
  Form: TSetupForm;
  Intro: TNewStaticText;
  Top: Integer;
  Ok, Cancel: TNewButton;
  BoxTesseract, BoxGhostscript, BoxOllama, BoxModels, BoxPython: TNewCheckBox;
  Parts: String;
begin
  Result := True;
  RemoveComponents := '';

  { Asked here, before anything is removed. The first attempt put a
    checkbox on UninstallProgressForm — the *progress* page, which only
    appears once the uninstall is already running, so the box was there
    but could never be ticked in time. A question the user cannot answer
    before the work starts is not a question.

    The second attempt was a single yes/no for all four dependencies at
    once, which is the wrong shape: someone who wants Ollama gone may
    well still be using Ghostscript. One box each. }
  if UninstallSilent then
    exit;

  { CreateNew, not Create, and the difference is the whole bug.

    Create loads the form's .dfm resource by class name. That resource is
    linked into the setup binary and NOT into the uninstaller, so the call
    compiles and then dies at run time with "Resource TSetupForm not
    found" — which is exactly what a user got when they opened Programs
    and Features. CreateNew builds the form from nothing and asks for no
    resource, which is why everything below sets its own size, position
    and border: there is no .dfm left to inherit them from.

    Measured rather than reasoned about: a throwaway installer was built
    that tries all four constructors inside the uninstaller and writes
    down which survive. Create failed with that exact message; CreateNew
    worked, including with a TNewCheckBox parented to it. }
  Form := TSetupForm.CreateNew(nil, 0);
  try
    Form.Caption := '{#AppName}';
    Form.ClientWidth := ScaleX(440);
    Form.ClientHeight := ScaleY(300);
    Form.Position := poScreenCenter;
    Form.BorderStyle := bsDialog;
    { A form with no .dfm also inherits no font, and the default is the
      1995 one. }
    Form.Font.Name := 'Segoe UI';
    Form.Font.Size := 9;

    Intro := TNewStaticText.Create(Form);
    Intro.Parent := Form;
    Intro.Left := ScaleX(8);
    Intro.Top := ScaleY(8);
    Intro.Width := Form.ClientWidth - ScaleX(20);
    Intro.WordWrap := True;
    Intro.AutoSize := True;
    Intro.Caption := ExpandConstant('{cm:UninstallIntro}') + #13#10#13#10
                   + ExpandConstant('{cm:KeepCollections}');

    Top := Intro.Top + Intro.Height + ScaleY(14);
    BoxTesseract   := AddComponentBox(Form, Form, ExpandConstant('{cm:CompTesseract}'), Top);
    BoxGhostscript := AddComponentBox(Form, Form, ExpandConstant('{cm:CompGhostscript}'), Top);
    BoxOllama      := AddComponentBox(Form, Form, ExpandConstant('{cm:CompOllama}'), Top);
    BoxModels      := AddComponentBox(Form, Form, ExpandConstant('{cm:CompModels}'), Top);
    BoxPython      := AddComponentBox(Form, Form, ExpandConstant('{cm:CompPython}'), Top);

    Ok := TNewButton.Create(Form);
    Ok.Parent := Form;
    Ok.Width := ScaleX(90);
    Ok.Height := ScaleY(25);
    Ok.Left := Form.ClientWidth - ScaleX(196);
    Ok.Top := Form.ClientHeight - ScaleY(35);
    Ok.Caption := SetupMessage(msgButtonOK);
    Ok.ModalResult := mrOk;
    Ok.Default := True;

    Cancel := TNewButton.Create(Form);
    Cancel.Parent := Form;
    Cancel.Width := ScaleX(90);
    Cancel.Height := ScaleY(25);
    Cancel.Left := Form.ClientWidth - ScaleX(98);
    Cancel.Top := Ok.Top;
    Cancel.Caption := SetupMessage(msgButtonCancel);
    Cancel.ModalResult := mrCancel;
    Cancel.Cancel := True;

    if Form.ShowModal() <> mrOk then
    begin
      Result := False;
      exit;
    end;

    Parts := '';
    if BoxTesseract.Checked then Parts := Parts + 'tesseract,';
    if BoxGhostscript.Checked then Parts := Parts + 'ghostscript,';
    if BoxOllama.Checked then Parts := Parts + 'ollama,';
    if BoxModels.Checked then Parts := Parts + 'models,';
    if BoxPython.Checked then Parts := Parts + 'python,';
    if Parts <> '' then
      RemoveComponents := Copy(Parts, 1, Length(Parts) - 1);
  finally
    Form.Free();
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Args: String;
  ResultCode: Integer;
  Script: String;
  Runner: String;
begin
  if CurUninstallStep <> usUninstall then
    exit;

  Script := ExpandConstant('{app}\uninstall.ps1');
  if not FileExists(Script) then
    exit;

  { -KeepDependencies always, and the ticked boxes on top of it. The
    granular list decides the shared components on its own; the flag
    decides everything else, which is what this installation owns and is
    going anyway. With no box ticked the list is empty, the flag applies
    to everything, and nothing shared is touched.

    Neither path removes the project list: that lives behind
    -RemoveUserData, which nothing here passes. }
  Args := '-KeepDependencies';
  if RemoveComponents <> '' then
    Args := Args + ' -Components ' + RemoveComponents;

  { Logged, for the same reason the install is. The first version ran this
    hidden and silent, and when a user reported that nothing had been
    removed there was no way to tell whether the script had failed, run
    partially, or done its job while they looked too early. }
  LogFilePath := ExpandConstant('{localappdata}\GClaudeIndexer\uninstall-log.txt');
  ForceDirectories(ExpandConstant('{localappdata}\GClaudeIndexer'));

  { Through the same generated runner as the install, and for the same
    reason: this call used to be a cmd command line whose doubled quotes
    broke on the space in "C:\Program Files", so the uninstaller reported a
    clean run having removed nothing — and left no log to say otherwise,
    because the redirection was part of the line that never ran. }
  Runner := WriteRunnerScript(Script, Args, LogFilePath,
                              ExpandConstant('{tmp}\gclaude-uninstall-done.txt'));
  Exec(PowerShellPath(), RunnerCommandLine(Runner), ExpandConstant('{app}'),
       SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;
