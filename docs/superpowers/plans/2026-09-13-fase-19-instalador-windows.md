# Fase 19 — Instalador do Windows: plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** entregar um instalador gráfico para Windows, com desinstalador
registrado no sistema, modo silencioso compatível com o winget e três
idiomas, sem reescrever a lógica de instalação de dependências que já
existe e funciona.

**Architecture:** Inno Setup como casca em volta do `install.ps1`. O
instalador cuida do que hoje não existe — identidade perante o Windows,
interface e contrato de silêncio — e delega ao script o trabalho de
dependências.

**Tech Stack:** Inno Setup 6 (Pascal Script), PowerShell 5.1, Python 3.12,
GitHub Actions em `windows-latest`, Windows Sandbox.

**Spec:** `docs/superpowers/specs/2026-09-13-fase-19-instalador-windows-design.md`

## Global Constraints

- **Nada de reimplementar o `install.ps1`.** Se o script já sabe fazer, o
  instalador chama. A regra vale inclusive quando reescrever parecer mais
  simples.
- A versão tem **uma fonte só**: `SYSTEM_VERSION` em
  `gclaude_indexer/web/app.py`. Nunca escrita à mão em outro arquivo.
- Todo texto visível ao usuário existe nos três idiomas (pt-BR, en, es).
  O Inno traz a interface padrão traduzida; as mensagens próprias vão em
  `[CustomMessages]`.
- Comentários e nomes de identificador em inglês; nomes de teste em
  português, como no resto do projeto.
- O instalador **nunca** apaga acervo do usuário, em nenhum caminho.
- Modo silencioso: zero interação, e código de saída verdadeiro.
- Nada de assinatura de código nesta fase (decisão registrada na spec).
- Não alterar comportamento existente do `install.ps1` para quem o roda à
  mão: toda adição é aditiva e opcional.

## Nota sobre o código deste plano

O Inno Setup não está instalado nesta máquina (Task 0 resolve isso), então
o código `.iss` abaixo foi escrito sem compilador disponível para
conferir. Trate-o como ponto de partida correto em estrutura e intenção,
não como algo já compilado: confira cada diretiva contra a documentação do
Inno 6 ao implementar, e corrija o plano se algo divergir.

---

### Task 0: Ambiente de build

**Files:** nenhum no repositório.

- [ ] **Step 1: Instalar o Inno Setup 6**

O winget está disponível (`v1.29.290`):

```
winget install --id JRSoftware.InnoSetup --exact --accept-package-agreements --accept-source-agreements
```

- [ ] **Step 2: Confirmar o compilador**

```
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /?
```

Esperado: a ajuda do compilador. Se o caminho diferir, anote o real — o
`build.ps1` da Task 3 precisa localizá-lo.

Nada a commitar.

---

### Task 1: `-StatusFile` no `install.ps1`

**Files:**
- Modify: `install.ps1` (bloco `param`, e cada transição de etapa)
- Test: `tests/test_phase19.py`

**Interfaces:**
- Produces: parâmetro `-StatusFile <caminho>` e a função interna
  `Write-InstallStatus -Step <int> -Total <int> -Key <string> -Text <string>`.

O contrato do arquivo está na spec §6.2 e é normativo: duas linhas, UTF-8,
arquivo reescrito inteiro a cada etapa.

```
<etapa>|<total>|<chave>
<texto para o usuário>
```

Chaves estáveis: `python`, `venv`, `deps`, `tesseract`, `ghostscript`,
`ollama`, `model`, `sensors`.

- [ ] **Step 1: Escrever o teste que falha**

```python
# tests/test_phase19.py
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
POWERSHELL = "powershell"


def _rodar_ps(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True, text=True, timeout=120,
    )


def test_o_arquivo_de_status_tem_duas_linhas_no_formato_do_contrato(tmp_path):
    """O instalador lê este arquivo para atualizar o rótulo da janela. O
    formato é contrato entre dois componentes, não detalhe interno."""
    destino = tmp_path / "status.txt"
    script = (
        f". '{RAIZ / 'install.ps1'}' -WhatIfContract; "
        f"Write-InstallStatus -Step 3 -Total 8 -Key 'tesseract' -Text 'Instalando Tesseract'"
        f" -StatusFile '{destino}'"
    )

    _rodar_ps(script)

    linhas = destino.read_text(encoding="utf-8").splitlines()
    assert len(linhas) == 2
    assert linhas[0] == "3|8|tesseract"
    assert linhas[1] == "Instalando Tesseract"


def test_cada_etapa_reescreve_o_arquivo_em_vez_de_acrescentar(tmp_path):
    """Acrescentar linhas deixaria o instalador ler estado antigo."""
    destino = tmp_path / "status.txt"
    script = (
        f". '{RAIZ / 'install.ps1'}' -WhatIfContract; "
        f"Write-InstallStatus -Step 1 -Total 8 -Key 'python' -Text 'a' -StatusFile '{destino}';"
        f"Write-InstallStatus -Step 2 -Total 8 -Key 'venv' -Text 'b' -StatusFile '{destino}'"
    )

    _rodar_ps(script)

    linhas = destino.read_text(encoding="utf-8").splitlines()
    assert len(linhas) == 2
    assert linhas[0] == "2|8|venv"


def test_sem_statusfile_o_script_nao_escreve_nada(tmp_path):
    """Quem roda o install.ps1 à mão não pode ver diferença nenhuma."""
    script = (
        f". '{RAIZ / 'install.ps1'}' -WhatIfContract; "
        f"Write-InstallStatus -Step 1 -Total 8 -Key 'python' -Text 'a'"
    )

    resultado = _rodar_ps(script)

    assert resultado.returncode == 0
    assert not list(tmp_path.iterdir())
```

Nota sobre `-WhatIfContract`: o `install.ps1` executa ao ser carregado.
Para o teste poder chamar só a função, acrescente ao `param` um
`[switch]$WhatIfContract` que faz o script definir as funções e retornar
sem executar nada. É uma porta de teste explícita, documentada como tal.

- [ ] **Step 2: Rodar e confirmar a falha**

Run: `"C:/Users/alexc/AppData/Local/GClaudeIndexer/venv/Scripts/python.exe" -m pytest tests/test_phase19.py -v`
Expected: FAIL — `Write-InstallStatus` não existe.

- [ ] **Step 3: Implementar**

No `param(` do `install.ps1`, acrescentar:

```powershell
    [string]$StatusFile = "",
    [switch]$WhatIfContract,
```

E a função, junto das outras auxiliares:

```powershell
function Write-InstallStatus {
    <#
    .SYNOPSIS
        Publishes the current step for a graphical installer to read.
    .DESCRIPTION
        The whole file is rewritten on every call, never appended to: the
        installer polls it while this script writes, and a reader that
        caught a half-written append would show a step that is not the
        current one.

        Progress is a courtesy. A failure to write it must never fail the
        installation, which is why every error here is swallowed — see the
        contract in the phase 19 design, section 6.2.
    #>
    param(
        [Parameter(Mandatory)][int]$Step,
        [Parameter(Mandatory)][int]$Total,
        [Parameter(Mandatory)][string]$Key,
        [Parameter(Mandatory)][string]$Text,
        [string]$StatusFile = $script:StatusFile
    )

    if (-not $StatusFile) { return }

    try {
        $content = "$Step|$Total|$Key`n$Text`n"
        [System.IO.File]::WriteAllText($StatusFile, $content, [System.Text.UTF8Encoding]::new($false))
    } catch {
        # Deliberately silent: see above.
    }
}
```

E, logo depois do bloco `param`:

```powershell
if ($WhatIfContract) { return }
```

Depois, chamar `Write-InstallStatus` em cada transição de etapa, com as
oito chaves estáveis e o total 8.

- [ ] **Step 4: Rodar e confirmar que passa**

Run: `... -m pytest tests/test_phase19.py -v`
Expected: PASS.

- [ ] **Step 5: Rodar a suíte inteira**

Run: `... -m pytest -q`
Expected: sem regressão.

- [ ] **Step 6: Commit**

```bash
git add install.ps1 tests/test_phase19.py
git commit -m "feat(install): arquivo de status para o instalador gráfico ler"
```

---

### Task 2: Modo não interativo no `uninstall.ps1`

**Files:**
- Modify: `uninstall.ps1`
- Test: `tests/test_phase19.py`

**Interfaces:**
- Consumes: nada.
- Produces: garantia de que `-RemoveAll` e `-KeepDependencies` não
  produzem nenhuma pergunta.

O desinstalador do Windows não tem console para responder. Qualquer
`Read-Host` alcançável nesse caminho trava a desinstalação num processo
invisível.

- [ ] **Step 1: Escrever o teste que falha**

```python
def test_o_desinstalador_nao_pergunta_nada_nos_modos_automaticos():
    """Chamado pelo desinstalador do Windows, que não tem console."""
    texto = (RAIZ / "uninstall.ps1").read_text(encoding="utf-8")
    linhas = texto.splitlines()

    for numero, linha in enumerate(linhas, start=1):
        if "Read-Host" not in linha:
            continue
        anteriores = "\n".join(linhas[max(0, numero - 12):numero])
        assert "$RemoveAll" in anteriores or "$KeepDependencies" in anteriores, (
            f"Read-Host na linha {numero} não está atrás de um modo automático"
        )
```

- [ ] **Step 2: Rodar e confirmar a falha**

Run: `... -m pytest tests/test_phase19.py -v -k desinstalador`
Expected: FAIL, apontando a linha desprotegida. Se passar de primeira, o
script já está correto — registre isso no relatório e siga.

- [ ] **Step 3: Implementar**

Colocar cada `Read-Host` restante atrás de
`if (-not $RemoveAll -and -not $KeepDependencies)`, com o comportamento
padrão documentado para quando nenhum dos dois é passado.

- [ ] **Step 4: Rodar, suíte inteira, commit**

```bash
git add uninstall.ps1 tests/test_phase19.py
git commit -m "fix(uninstall): silêncio completo nos modos automáticos"
```

---

### Task 3: `build.ps1` e a fonte única da versão

**Files:**
- Create: `installer/build.ps1`
- Test: `tests/test_phase19.py`

**Interfaces:**
- Produces: `installer/build.ps1`, que lê `SYSTEM_VERSION` de
  `gclaude_indexer/web/app.py`, localiza o `ISCC.exe` e compila com
  `/DAppVersion=<versão>`.

- [ ] **Step 1: Escrever o teste que falha**

```python
def test_o_build_le_a_versao_do_app_e_nao_de_um_literal():
    """Versão escrita em dois lugares diverge. Esta fase inteira nasceu de
    valores derivados duas vezes por regras diferentes."""
    build = (RAIZ / "installer" / "build.ps1").read_text(encoding="utf-8")

    assert "web/app.py" in build.replace("\\", "/")
    assert "SYSTEM_VERSION" in build

    app = (RAIZ / "gclaude_indexer" / "web" / "app.py").read_text(encoding="utf-8")
    versao = next(
        linha.split('"')[1] for linha in app.splitlines()
        if linha.startswith("SYSTEM_VERSION")
    )
    assert versao not in build, "a versão está escrita à mão no build"
```

- [ ] **Step 2: Rodar e confirmar a falha**

Expected: FAIL — o arquivo não existe.

- [ ] **Step 3: Implementar**

```powershell
<#
.SYNOPSIS
    Builds the Windows installer.
.DESCRIPTION
    The version is read from `SYSTEM_VERSION` in `web/app.py` and handed to
    the compiler, never written here. Two copies of a version number drift,
    and this project has already paid for that class of mistake more than
    once.
#>
param([string]$OutputDir = "$PSScriptRoot\..\dist")

$ErrorActionPreference = "Stop"

$appPy = Join-Path $PSScriptRoot "..\gclaude_indexer\web\app.py"
$line = Select-String -Path $appPy -Pattern '^SYSTEM_VERSION\s*=\s*"([^"]+)"' |
    Select-Object -First 1
if (-not $line) { throw "SYSTEM_VERSION not found in $appPy" }
$version = $line.Matches[0].Groups[1].Value

$candidates = @(
    "$env:ProgramFiles(x86)\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
)
$iscc = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 not found. Install it: winget install JRSoftware.InnoSetup" }

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

& $iscc "/DAppVersion=$version" "/O$OutputDir" (Join-Path $PSScriptRoot "GClaudeIndexer.iss")
if ($LASTEXITCODE -ne 0) { throw "ISCC failed with exit code $LASTEXITCODE" }

Write-Host "Built GClaude-Indexer-Setup-$version.exe in $OutputDir"
```

- [ ] **Step 4: Rodar, commit**

```bash
git add installer/build.ps1 tests/test_phase19.py
git commit -m "build(installer): compila lendo a versão do app.py"
```

---

### Task 4: O `.iss` básico — arquivos, registro, idiomas, licença

**Files:**
- Create: `installer/GClaudeIndexer.iss`
- Modify: `.gitignore` (ignorar `dist/`)

**Interfaces:**
- Consumes: `/DAppVersion` da Task 3.
- Produces: um instalador que copia arquivos, cria atalhos, registra em
  Programas e Recursos e desinstala — ainda sem dependências.

- [ ] **Step 1: Escrever o `.iss`**

```pascal
; GClaude Indexer — Windows installer.
;
; A shell around install.ps1, not a replacement for it. See
; docs/superpowers/specs/2026-09-13-fase-19-instalador-windows-design.md
;
; AppVersion comes from build.ps1, which reads it from web/app.py. Never
; write a version literal here.

#ifndef AppVersion
  #error AppVersion must be passed with /DAppVersion=x.y.z
#endif

#define AppName "GClaude Indexer"
#define AppPublisher "Alex Camacho Castilho"
#define AppURL "https://github.com/alexccastilho/gclaude-indexer"

[Setup]
AppId={{8F3A6C21-7E4D-4B19-9C2A-1D5E8F0B7A34}
AppName={#AppName}
AppVersion={#AppVersion}
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
; The GPL-3.0 text itself, not an EULA: an added restriction would be
; incompatible with the licence this software ships under.
LicenseFile=..\LICENSE
; Lets the user pick between installing for themselves and for the whole
; machine; silent runs get per-user, which is what winget needs.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
UninstallDisplayIcon={app}\logo.ico
UninstallDisplayName={#AppName}

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Files]
Source: "..\gclaude_indexer\*"; DestDir: "{app}\gclaude_indexer"; Flags: recursesubdirs ignoreversion
Source: "..\config\*"; DestDir: "{app}\config"; Flags: recursesubdirs ignoreversion
Source: "..\docs\*"; DestDir: "{app}\docs"; Flags: recursesubdirs ignoreversion
Source: "..\install.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\uninstall.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\Indexer.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\Indexer.vbs"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\launcher.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\run_server.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\conftest.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\pytest.ini"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\CHANGELOG.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\logo.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; Created here, not by install.ps1 (which is called with -NoShortcut), so
; that uninstalling removes them. A shortcut created outside the
; installer's control survives as an orphan pointing at a folder that no
; longer exists.
Name: "{group}\{#AppName}"; Filename: "{app}\Indexer.vbs"; IconFilename: "{app}\logo.ico"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\Indexer.vbs"; IconFilename: "{app}\logo.ico"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
```

Notas para quem implementa: `{autopf}` resolve para Arquivos de Programas
ou para a pasta local do usuário conforme o modo escolhido, e `{autodesktop}`
segue a mesma lógica — é o par que faz a escolha de modo funcionar sem
ramificação manual. O `AppId` acima é fixo e **nunca pode mudar**: é ele
que faz uma versão nova reconhecer a antiga como atualização em vez de
instalar em paralelo.

- [ ] **Step 2: Compilar e verificar**

```
powershell -NoProfile -ExecutionPolicy Bypass -File installer\build.ps1
```

Esperado: `dist\GClaude-Indexer-Setup-1.3.0.exe`.

- [ ] **Step 3: Instalar no Windows Sandbox e conferir**

Sem Sandbox ainda (Task 10), instale numa pasta de teste e confirme:
entrada em Programas e Recursos com nome, versão, editor e ícone;
atalho no menu Iniciar; desinstalar remove tudo.

- [ ] **Step 4: Commit**

```bash
git add installer/GClaudeIndexer.iss .gitignore
git commit -m "feat(installer): esqueleto do Inno com registro e três idiomas"
```

---

### Task 5: Página de opcionais

**Files:**
- Modify: `installer/GClaudeIndexer.iss`

**Interfaces:**
- Produces: as tarefas `downloadmodel` e `cpusensor`, lidas pela Task 6.

- [ ] **Step 1: Acrescentar ao `[Tasks]`**

```pascal
; Unchecked by default, and the size is in the label: gigabytes started
; without being asked for is how an installation someone expected to take
; a minute turns into twenty.
Name: "downloadmodel"; Description: "{cm:DownloadModel}"; GroupDescription: "{cm:OptionalGroup}"; Flags: unchecked
Name: "cpusensor"; Description: "{cm:CpuSensorShortcut}"; GroupDescription: "{cm:OptionalGroup}"; Flags: unchecked
```

- [ ] **Step 2: Acrescentar `[CustomMessages]` nos três idiomas**

```pascal
[CustomMessages]
brazilianportuguese.OptionalGroup=Opcionais:
brazilianportuguese.DownloadModel=Baixar agora o modelo de classificação local (cerca de 3,2 GB)
brazilianportuguese.CpuSensorShortcut=Criar também o atalho do sensor de CPU
brazilianportuguese.InstallingDeps=Instalando dependências. Isto pode levar vários minutos.
brazilianportuguese.KeepCollections=Os acervos que você já indexou NÃO serão apagados. Eles ficam nas pastas de saída que você escolheu, fora da pasta de instalação.
brazilianportuguese.RemoveDeps=Remover também Tesseract, Ghostscript, Ollama e Python 3.12
brazilianportuguese.RemoveDepsHint=Deixe desmarcado se outro programa desta máquina usar algum deles.

english.OptionalGroup=Optional:
english.DownloadModel=Download the local classification model now (about 3.2 GB)
english.CpuSensorShortcut=Also create the CPU sensor shortcut
english.InstallingDeps=Installing dependencies. This can take several minutes.
english.KeepCollections=Collections you have already indexed will NOT be deleted. They live in the output folders you chose, outside the installation folder.
english.RemoveDeps=Also remove Tesseract, Ghostscript, Ollama and Python 3.12
english.RemoveDepsHint=Leave unchecked if another program on this machine uses any of them.

spanish.OptionalGroup=Opcionales:
spanish.DownloadModel=Descargar ahora el modelo de clasificación local (unos 3,2 GB)
spanish.CpuSensorShortcut=Crear también el acceso directo del sensor de CPU
spanish.InstallingDeps=Instalando dependencias. Esto puede tardar varios minutos.
spanish.KeepCollections=Las colecciones que ya indexó NO se eliminarán. Están en las carpetas de salida que usted eligió, fuera de la carpeta de instalación.
spanish.RemoveDeps=Eliminar también Tesseract, Ghostscript, Ollama y Python 3.12
spanish.RemoveDepsHint=Déjelo sin marcar si otro programa de esta máquina usa alguno de ellos.
```

- [ ] **Step 3: Compilar, conferir as três línguas, commit**

```bash
git add installer/GClaudeIndexer.iss
git commit -m "feat(installer): página de opcionais nos três idiomas"
```

---

### Task 6: Chamar o `install.ps1` com progresso

**Files:**
- Modify: `installer/GClaudeIndexer.iss` (seção `[Code]`)

**Interfaces:**
- Consumes: `-StatusFile` da Task 1; as tarefas da Task 5.
- Produces: `RunDependencyInstall(): Integer`, devolvendo o código de
  saída do PowerShell.

- [ ] **Step 1: Implementar em `[Code]`**

```pascal
[Code]
var
  StatusPage: TOutputProgressWizardPage;
  StatusFilePath: String;

function BuildInstallArguments(): String;
var
  Args: String;
begin
  { -NoShortcut on purpose: the [Icons] section owns the shortcuts, so
    that uninstalling removes them. }
  Args := '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\install.ps1') + '"'
        + ' -AutoInstall -NoShortcut'
        + ' -StatusFile "' + StatusFilePath + '"';
  if WizardIsTaskSelected('cpusensor') then
    Args := Args + ' -CpuSensorShortcut';
  if not WizardIsTaskSelected('downloadmodel') then
    Args := Args + ' -SkipModelDownload';
  Result := Args;
end;

procedure UpdateStatusLabel();
var
  Lines: TArrayOfString;
begin
  { Absent or unreadable means "no news yet", never an error: progress is
    a courtesy and must not be able to fail an installation. }
  if not FileExists(StatusFilePath) then
    exit;
  if not LoadStringsFromFile(StatusFilePath, Lines) then
    exit;
  if GetArrayLength(Lines) >= 2 then
    StatusPage.SetText(Lines[1], '');
end;
```

Nota: o `install.ps1` ainda não tem `-SkipModelDownload`. A Task 7
acrescenta, junto com o contrato de código de saída. Se preferir, inverta
a ordem das duas tarefas.

- [ ] **Step 2: Conferir o progresso numa instalação real**

O rótulo tem de mudar pelo menos uma vez por etapa. Uma barra parada por
dez minutos é indistinguível de travamento, e o usuário mata o processo.

- [ ] **Step 3: Os dois comportamentos que a spec promete na §8**

Nenhum precisa de código novo, mas os dois precisam ser **verificados**,
porque são promessas escritas e ninguém as testaria por acidente:

**Elevação recusada.** Escolher "para todos", clicar Não no prompt do
Windows, e confirmar que o assistente volta à tela de escolha em vez de
morrer — e que nada foi escrito em `HKLM`. O Inno faz isso sozinho quando
se usa `PrivilegesRequiredOverridesAllowed=dialog`; o que se está
verificando é que nenhuma escrita de registro foi antecipada para antes
desse ponto.

**Cancelar durante o download.** Clicar Cancelar enquanto o
`install.ps1` roda, e confirmar que o cancelamento é honrado **entre
etapas**, não no meio de uma transferência, e que o aplicativo fica
instalado no estado degradado já alcançado. `ewWaitUntilTerminated`
significa que o Inno espera o processo corrente terminar — confirme que o
botão comunica isso em vez de parecer travado.

- [ ] **Step 3: Commit**

```bash
git add installer/GClaudeIndexer.iss
git commit -m "feat(installer): executa o install.ps1 e mostra o passo corrente"
```

---

### Task 7: Contrato de código de saída

**Files:**
- Modify: `install.ps1`
- Test: `tests/test_phase19.py`

**Interfaces:**
- Produces: `-SkipModelDownload`; códigos de saída `0` (utilizável) e
  `1` (essencial faltando).

Esta é a tarefa mais importante do plano. Hoje o `install.ps1` avisa e
continua quando um download falha — certo para quem está olhando,
desastroso em silêncio, onde vira sucesso com instalação quebrada e o
winget reportando que deu tudo certo.

**Essencial:** Python 3.12, ambiente virtual, dependências do
`requirements.txt`. Falha aqui é saída diferente de zero.
**Degradável:** Tesseract, Ghostscript, Ollama, modelo. Falha aqui é saída
zero com o que faltou registrado, porque o aplicativo funciona sem eles —
sem OCR no primeiro caso, caindo para o motor de regras no segundo.

- [ ] **Step 1: Escrever os testes**

```python
def test_o_script_distingue_dependencia_essencial_de_degradavel():
    texto = (RAIZ / "install.ps1").read_text(encoding="utf-8")

    assert "$script:EssentialFailed" in texto
    assert "exit 1" in texto


def test_falha_degradavel_nao_derruba_a_instalacao():
    """Sem Tesseract não há OCR, mas PDF com texto funciona. Derrubar a
    instalação por isso entregaria nada em vez de entregar quase tudo."""
    texto = (RAIZ / "install.ps1").read_text(encoding="utf-8")
    trecho = texto[texto.find("function Install-Ghostscript"):]
    trecho = trecho[:3000]

    assert "EssentialFailed" not in trecho
```

- [ ] **Step 2: Implementar**

Acrescentar ao `param`: `[switch]$SkipModelDownload`.

Uma variável de script `$script:EssentialFailed = $false`, marcada apenas
nos pontos essenciais, e no fim:

```powershell
if ($script:EssentialFailed) {
    Write-Host "  Installation incomplete: an essential component could not be installed." -ForegroundColor Red
    exit 1
}
exit 0
```

- [ ] **Step 3: Rodar, suíte inteira, commit**

```bash
git add install.ps1 tests/test_phase19.py
git commit -m "feat(install): código de saída que distingue essencial de degradável"
```

---

### Task 8: Desinstalador

**Files:**
- Modify: `installer/GClaudeIndexer.iss`

- [ ] **Step 1: Página de desinstalação em `[Code]`**

Uma caixa para remover as dependências, **desmarcada**, e o texto do
`{cm:KeepCollections}` visível na mesma página. Quem desinstala um
indexador teme perder o acervo; o silêncio aqui é o que faz a pessoa não
desinstalar, ou desinstalar com medo.

A caixa precisa ser declarada e criada antes de ser lida:

```pascal
var
  RemoveDepsCheckBox: TNewCheckBox;

procedure InitializeUninstallProgressForm();
var
  Page: TNewNotebookPage;
  Explanation: TNewStaticText;
begin
  { Silent uninstall has no form at all; the default is then whatever
    CurUninstallStepChanged reads from an unchecked box: keep the
    dependencies, which is the conservative side. }
  if UninstallSilent then
    exit;

  Page := UninstallProgressForm.InnerPage;

  Explanation := TNewStaticText.Create(UninstallProgressForm);
  Explanation.Parent := Page;
  Explanation.Top := UninstallProgressForm.StatusLabel.Top + 48;
  Explanation.Width := Page.ClientWidth;
  Explanation.WordWrap := True;
  Explanation.AutoSize := True;
  Explanation.Caption := ExpandConstant('{cm:KeepCollections}');

  RemoveDepsCheckBox := TNewCheckBox.Create(UninstallProgressForm);
  RemoveDepsCheckBox.Parent := Page;
  RemoveDepsCheckBox.Top := Explanation.Top + Explanation.Height + 12;
  RemoveDepsCheckBox.Width := Page.ClientWidth;
  RemoveDepsCheckBox.Checked := False;
  RemoveDepsCheckBox.Caption := ExpandConstant('{cm:RemoveDeps}');
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Args: String;
  ResultCode: Integer;
begin
  if CurUninstallStep <> usUninstall then
    exit;
  { Assigned() guards the silent path, where the form was never built. }
  if Assigned(RemoveDepsCheckBox) and RemoveDepsCheckBox.Checked then
    Args := '-RemoveAll'
  else
    Args := '-KeepDependencies';
  Exec('powershell.exe',
       '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\uninstall.ps1') + '" ' + Args,
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;
```

Em modo silencioso a caixa não existe e o padrão é `-KeepDependencies`,
que é o lado conservador.

- [ ] **Step 2: Verificar que o acervo sobrevive**

Crie uma pasta de saída com os quatro Markdown, desinstale com e sem
remover dependências, e confirme que a pasta continua intacta nos dois
casos.

- [ ] **Step 3: Commit**

```bash
git add installer/GClaudeIndexer.iss
git commit -m "feat(installer): desinstalador que pergunta uma coisa e preserva acervos"
```

---

### Task 9: CI — compilar e testar o caminho silencioso

**Files:**
- Create: `.github/workflows/installer.yml`

O caminho silencioso é o contrato com o winget e o único que quebra sem
ninguém ver. A CI não julga aparência; garante o comando que o winget
executa.

- [ ] **Step 1: Escrever o workflow**

```yaml
name: Installer

on:
  push:
    branches: [main]
    paths: ['installer/**', 'install.ps1', 'uninstall.ps1', '.github/workflows/installer.yml']
  pull_request:
    paths: ['installer/**', 'install.ps1', 'uninstall.ps1', '.github/workflows/installer.yml']
  release:
    types: [published]

jobs:
  build:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v5

      - name: Install Inno Setup
        run: winget install --id JRSoftware.InnoSetup --exact --accept-package-agreements --accept-source-agreements --disable-interactivity

      - name: Build
        run: powershell -NoProfile -ExecutionPolicy Bypass -File installer\build.ps1

      - name: Silent install
        run: |
          $exe = Get-ChildItem dist\*.exe | Select-Object -First 1
          & $exe.FullName /VERYSILENT /SUPPRESSMSGBOXES /NORESTART | Out-Null
          if ($LASTEXITCODE -ne 0) { throw "silent install failed with $LASTEXITCODE" }

      - name: The collection must survive an uninstall
        run: |
          $acervo = "$env:USERPROFILE\acervo-de-teste"
          New-Item -ItemType Directory -Force -Path $acervo | Out-Null
          "conteudo" | Out-File "$acervo\index.md"
          $unins = Get-ChildItem "$env:LOCALAPPDATA\Programs\GClaude Indexer\unins*.exe" | Select-Object -First 1
          & $unins.FullName /VERYSILENT | Out-Null
          if (-not (Test-Path "$acervo\index.md")) { throw "uninstall deleted a user collection" }

      - name: Attach to the release
        if: github.event_name == 'release'
        run: gh release upload ${{ github.event.release.tag_name }} (Get-ChildItem dist\*.exe).FullName
        env:
          GH_TOKEN: ${{ github.token }}
```

- [ ] **Step 2: Abrir PR e conferir que o workflow roda**

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/installer.yml
git commit -m "ci: compila o instalador e testa o caminho silencioso"
```

---

### Task 10: Windows Sandbox e roteiro manual

**Files:**
- Create: `installer/sandbox/instalador.wsb`, `installer/sandbox/ROTEIRO.md`

- [ ] **Step 1: Configuração do Sandbox**

```xml
<Configuration>
  <MappedFolders>
    <MappedFolder>
      <HostFolder>C:\caminho\para\dist</HostFolder>
      <SandboxFolder>C:\instalador</SandboxFolder>
      <ReadOnly>true</ReadOnly>
    </MappedFolder>
  </MappedFolders>
  <Networking>Enable</Networking>
  <MemoryInMB>8192</MemoryInMB>
</Configuration>
```

- [ ] **Step 2: Roteiro manual**

A matriz é pequena: dois modos × (instalação nova, atualização por cima,
desinstalação) × (com e sem modelo). Cada célula com o que observar e o
que seria falha. Meia hora por release.

- [ ] **Step 3: Commit**

---

### Task 11: Manifesto do winget

**Files:**
- Create: `installer/winget/manifest.template.yaml`, `installer/winget/gerar.ps1`

- [ ] **Step 1: Modelo e gerador**

Três arquivos no formato de manifesto do winget (versão, instalador e
locale padrão), com `{{VERSION}}`, `{{URL}}` e `{{SHA256}}` substituídos
pelo gerador a partir da release publicada. `InstallerType: inno`, que é o
tipo cujas chaves de silêncio o winget já conhece.

- [ ] **Step 2: Teste do gerador**

```python
def test_o_manifesto_sai_com_a_versao_e_o_hash_da_release(tmp_path):
    """Manifesto com hash errado é rejeitado pela moderação do winget, e o
    erro só aparece depois do PR — caro de descobrir tarde."""
    modelo = tmp_path / "manifest.template.yaml"
    modelo.write_text(
        "PackageVersion: {{VERSION}}\n"
        "InstallerUrl: {{URL}}\n"
        "InstallerSha256: {{SHA256}}\n"
        "InstallerType: inno\n",
        encoding="utf-8",
    )
    saida = tmp_path / "manifest.yaml"

    _rodar_ps(
        f"& '{RAIZ / 'installer' / 'winget' / 'gerar.ps1'}'"
        f" -Template '{modelo}' -Output '{saida}'"
        f" -Version '1.3.0' -Url 'https://exemplo/x.exe' -Sha256 'ABC123'"
    )

    texto = saida.read_text(encoding="utf-8")
    assert "PackageVersion: 1.3.0" in texto
    assert "InstallerSha256: ABC123" in texto
    assert "InstallerType: inno" in texto
    assert "{{" not in texto, "sobrou marcador não substituído"
```

- [ ] **Step 3: Commit**

---

### Task 12: Documentação

**Files:**
- Modify: `README.md`, `docs/README.pt-BR.md`, `docs/README.es.md`,
  `CHANGELOG.md`, `docs/SPECIFICATION.md`, `gclaude_indexer/web/app.py`

- [ ] **Step 1: README nos três idiomas**

A seção de instalação ganha o instalador como caminho recomendado, com o
winget como alternativa, e o script preservado para quem prefere. **Diga
o que o SmartScreen vai mostrar e por quê** — a pessoa que se assusta sem
contexto desinstala e não volta.

- [ ] **Step 2: CHANGELOG, especificação e versão**

Bloco 1.3.0; seção de instalação na especificação; `SYSTEM_VERSION` para
`1.3.0`.

- [ ] **Step 3: Commit**

---

## Critério de aceitação

Os dez itens da §10 da spec. O primeiro e o segundo são os que a CI
garante; o quinto é o que protege o usuário; os demais saem do roteiro de
Sandbox.
