# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Fase 19: o instalador do Windows e os scripts que ele chama.

Estes testes exercitam PowerShell, não Python: o instalador é uma casca
em volta do `install.ps1`, e o que pode quebrar em silêncio mora do lado
de lá — um cmdlet que some do ambiente por causa de outra versão do
PowerShell instalada, ou um catálogo de projetos tratado como cache.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
POWERSHELL = "powershell"


def _rodar_ps(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True, text=True, timeout=180,
    )


# --- o catálogo de projetos não é lixo de instalação ------------------------


def _confirm_step(argumentos: str, extra: str = "") -> str:
    """Chama `Confirm-Step` isoladamente, sem executar o desinstalador.

    `uninstall.ps1` roda ao ser carregado, então o teste precisa de uma
    porta explícita para só definir as funções e voltar.
    """
    script = (
        f". '{RAIZ / 'uninstall.ps1'}' -DryRunContract {extra}; "
        f"if (Confirm-Step -Title 'x' {argumentos}) {{ 'REMOVE' }} else {{ 'MANTEM' }}"
    )
    # `Confirm-Step` also prints the title and the reason for its answer,
    # which is the point of it — the verdict is the last line.
    linhas = [l for l in _rodar_ps(script).stdout.splitlines() if l.strip()]
    return linhas[-1].strip() if linhas else ""


def test_o_catalogo_de_projetos_sobrevive_a_desinstalacao_padrao():
    """O `projects.json` é a lista dos acervos do usuário. Perdê-lo não
    apaga acervo nenhum, mas obriga a pessoa a lembrar onde cada um estava
    e reapontar um por um. Foi o que aconteceu numa desinstalação real."""
    assert _confirm_step("-IsUserData", "-KeepDependencies") == "MANTEM"


def test_nem_o_remove_all_apaga_dados_do_usuario():
    """`-RemoveAll` é o que a caixa 'remover também as dependências' do
    desinstalador do Windows aciona, e essa caixa fala de Tesseract,
    Ghostscript, Ollama e Python — não da lista de projetos."""
    assert _confirm_step("-IsUserData", "-RemoveAll") == "MANTEM"


def test_dados_do_usuario_saem_so_quando_pedidos_explicitamente():
    assert _confirm_step("-IsUserData", "-RemoveUserData") == "REMOVE"


def test_estado_de_instalacao_continua_saindo_com_keep_dependencies():
    """A correção não pode transformar o desinstalador em algo que não
    desinstala: o que pertence a esta instalação continua saindo."""
    assert _confirm_step("", "-KeepDependencies") == "REMOVE"


def test_dependencia_compartilhada_continua_preservada():
    assert _confirm_step("-IsSharedDependency", "-KeepDependencies") == "MANTEM"


def test_o_catalogo_nao_esta_na_lista_de_estado_descartavel():
    """Guarda estrutural: mesmo que a decisão acima mude, o arquivo não
    pode voltar a ser tratado como cache."""
    texto = (RAIZ / "uninstall.ps1").read_text(encoding="utf-8")
    inicio = texto.find("Installation state")
    assert inicio != -1, "bloco de estado de instalação não encontrado"
    bloco = texto[inicio:inicio + 900]

    assert "projects.json" not in bloco
    assert "settings.json" not in bloco
    assert "tools.json" in bloco


# --- nenhum terminal, em momento nenhum ------------------------------------


def test_nenhum_start_process_do_instalador_abre_janela():
    """O instalador é gráfico. Um console preto piscando no meio dele —
    ou pior, ficando aberto — é o que o usuário relatou ver.

    `Start-Process` cria janela por padrão. Com `-Verb RunAs` não se pode
    usar `-NoNewWindow`, porque o verbo exige ShellExecute; nesse caso a
    janela tem de ser escondida com `-WindowStyle Hidden`. Qualquer
    chamada nova precisa de uma das duas.
    """
    texto = (RAIZ / "install.ps1").read_text(encoding="utf-8")
    linhas = texto.splitlines()

    for numero, linha in enumerate(linhas, start=1):
        nua = linha.strip()
        # Só invocações: `Start-ProcessElevated` é o nome de uma função
        # daqui e contém a cadeia procurada, e uma definição não abre
        # janela nenhuma.
        if "Start-Process " not in linha and "Start-Process@" not in linha:
            continue
        if nua.startswith("#") or nua.startswith("function "):
            continue
        if "Start-ProcessElevated" in linha:
            continue
        # Chamadas por splatting: a decisão está no dicionário montado
        # nas linhas acima.
        contexto = "\n".join(linhas[max(0, numero - 25):numero + 1])
        assert ("WindowStyle" in contexto) or ("NoNewWindow" in contexto), (
            f"Start-Process na linha {numero} pode abrir uma janela visível"
        )


def test_a_elevacao_esconde_a_janela_mas_nao_tenta_esconder_o_uac():
    """A janela do processo elevado é nossa e fica oculta. O prompt do UAC
    é do Windows, desenhado na área de trabalho segura, e nenhum programa
    pode suprimi-lo — nem deveria."""
    texto = (RAIZ / "install.ps1").read_text(encoding="utf-8")
    inicio = texto.find("function Start-ProcessElevated")
    assert inicio != -1
    # A função é precedida de um docstring longo; a janela precisa
    # alcançar o corpo, que é onde a decisão mora.
    bloco = texto[inicio:inicio + 4000]

    assert '$startArguments["Verb"] = "RunAs"' in bloco
    assert '$startArguments["WindowStyle"] = "Hidden"' in bloco


# --- remoção por componente, não tudo ou nada -------------------------------


def test_componente_nomeado_e_removido():
    assert _confirm_step(
        "-IsSharedDependency -Component 'ollama'", "-Components ollama"
    ) == "REMOVE"


def test_componente_nao_nomeado_fica():
    """O caso que motivou a mudança: quem quer o Ollama fora pode muito
    bem continuar usando o Ghostscript."""
    assert _confirm_step(
        "-IsSharedDependency -Component 'ghostscript'", "-Components ollama"
    ) == "MANTEM"


def test_a_lista_vence_o_remove_all():
    """Uma lista explícita é mais informativa que um 'sim para tudo'.
    Adivinhar por cima dela seria dar uma resposta pior que a recebida."""
    assert _confirm_step(
        "-IsSharedDependency -Component 'python'", "-Components ollama -RemoveAll"
    ) == "MANTEM"


def test_a_lista_vence_o_keep_dependencies():
    assert _confirm_step(
        "-IsSharedDependency -Component 'tesseract'",
        "-Components tesseract -KeepDependencies"
    ) == "REMOVE"


def test_sem_lista_nada_muda_para_quem_ja_usava_os_modos_antigos():
    assert _confirm_step("-IsSharedDependency", "-RemoveAll") == "REMOVE"
    assert _confirm_step("-IsSharedDependency", "-KeepDependencies") == "MANTEM"


def test_o_que_a_instalacao_possui_sai_mesmo_em_modo_granular():
    """O instalador passa -KeepDependencies junto da lista: os componentes
    nomeados obedecem à lista, e o resto — que é desta instalação e vai
    embora de qualquer forma — obedece à flag."""
    assert _confirm_step("", "-Components ollama -KeepDependencies") == "REMOVE"


def test_toda_dependencia_pode_ser_escolhida():
    """Guarda contra uma dependência nova entrar sem poder ser escolhida:
    ela cairia no modo antigo e sairia junto sem ninguém marcar."""
    texto = (RAIZ / "uninstall.ps1").read_text(encoding="utf-8")
    wingets = texto.count("WingetId = ")
    componentes = set(re.findall(r'-?Component\s*=?\s*"([a-z]+)"', texto))

    assert len(componentes) >= wingets, (
        f"{wingets} dependências mas só {len(componentes)} nomes de componente"
    )


def test_a_tela_do_desinstalador_oferece_todos_os_componentes():
    """O nome do componente é um contrato entre duas linguagens: o Pascal
    do instalador o escreve na linha de comando, o PowerShell o lê. Um
    lado que ganhe um componente sem o outro produz ou uma caixinha que
    não faz nada, ou uma dependência que ninguém consegue remover."""
    ps = (RAIZ / "uninstall.ps1").read_text(encoding="utf-8")
    iss = (RAIZ / "installer" / "GClaudeIndexer.iss").read_text(encoding="utf-8")

    no_script = set(re.findall(r'-?Component\s*=?\s*"([a-z]+)"', ps))
    na_tela = set(re.findall(r"Parts \+ '([a-z]+),'", iss))

    assert no_script == na_tela, (
        f"só no script: {sorted(no_script - na_tela)}; "
        f"só na tela: {sorted(na_tela - no_script)}"
    )


# --- remover de verdade exige direitos que o desinstalador não tem ---------


def test_a_deteccao_de_elevacao_responde():
    """Tesseract, Ghostscript e Python são instalados para a máquina toda,
    e o desinstalador herda os privilégios da instalação — que numa
    instalação por usuário são nenhum. Sem pedir elevação, o winget recusa
    os três e o desinstalador termina dizendo que correu bem sem ter
    removido nada. Foi o que um usuário real viu."""
    script = (
        f". '{RAIZ / 'uninstall.ps1'}' -DryRunContract; "
        "if (Test-IsElevated) { 'ELEVADO' } else { 'COMUM' }"
    )
    saida = _rodar_ps(script).stdout.strip()
    assert saida in ("ELEVADO", "COMUM"), saida


def test_a_remocao_compartilhada_passa_por_um_caminho_elevado():
    """Guarda estrutural: um `winget uninstall` chamado direto do laço,
    sem o ramo elevado, volta a falhar em silêncio."""
    texto = (RAIZ / "uninstall.ps1").read_text(encoding="utf-8")
    inicio = texto.find("$Approved = New-Object")
    assert inicio != -1, "laço de dependências compartilhadas não encontrado"
    bloco = texto[inicio:]

    assert "Test-IsElevated" in bloco
    assert "Invoke-ElevatedWingetUninstall" in bloco


def test_o_resumo_conta_o_que_a_maquina_diz():
    """O código de saída do winget responde 'o comando deu certo'. Quem lê
    o resumo está perguntando 'sumiu?'. São perguntas diferentes sempre que
    o comando falha por um motivo que o winget engoliu."""
    texto = (RAIZ / "uninstall.ps1").read_text(encoding="utf-8")
    inicio = texto.find("$Approved = New-Object")
    bloco = texto[inicio:]

    verificacao = bloco.find("Test-WingetPackageInstalled")
    registro = bloco.find("$Removed.Add($dependency.Title)")
    assert verificacao != -1, "resultado não é conferido depois da remoção"
    assert verificacao < registro, "conta como removido antes de conferir"


# --- o caminho com espaço, que derrubou a instalação inteira ---------------

ISS = RAIZ / "installer" / "GClaudeIndexer.iss"


def test_nada_no_instalador_passa_por_cmd():
    """A causa raiz de três relatos seguidos. O instalador montava
    `cmd /c ""powershell.exe" -File ""<caminho>"" ..."`, e as aspas
    dobradas que o cmd exige não sobrevivem ao parser do PowerShell: na
    pasta padrão — C:\\Program Files\\GClaude Indexer — o PowerShell
    recebia `-File 'C:\\Program'`, recusava, e caía no prompt interativo.

    Era essa a janela preta que o usuário via, na frente de uma instalação
    onde nenhuma dependência tinha sido instalada. A desinstalação usava a
    mesma linha e falhava igual, sem sequer deixar log — o redirecionamento
    fazia parte da linha que nunca rodou.
    """
    texto = ISS.read_text(encoding="utf-8")
    for linha in texto.splitlines():
        nua = linha.strip()
        if nua.startswith("{") or nua.startswith("//") or nua.startswith(";"):
            continue
        assert "ExpandConstant('{cmd}')" not in linha, linha


def test_o_lancamento_nao_pode_abrir_janela_nem_esperar_por_ninguem():
    """SW_HIDE é a camada do Windows; -WindowStyle Hidden é a do próprio
    PowerShell. Só uma das duas sobreviveu à tentativa anterior, e quando
    o processo caiu em modo interativo foi a janela que apareceu. As duas,
    mais -NonInteractive: o que tentar ler do console falha na hora em vez
    de esperar para sempre atrás de uma janela oculta."""
    texto = ISS.read_text(encoding="utf-8")
    inicio = texto.find("function RunnerCommandLine")
    assert inicio != -1
    bloco = texto[inicio:inicio + 1200]

    assert "-NonInteractive" in bloco
    assert "-WindowStyle Hidden" in bloco
    assert "-NoProfile" in bloco


def test_o_runner_sobrevive_a_um_caminho_com_espaco(tmp_path):
    """O teste que o defeito exigia: a mesma forma de wrapper que o
    instalador escreve, apontando para uma pasta com espaço no nome, tem
    de executar o script, registrar a saída e gravar o código de saída."""
    pasta = tmp_path / "Program Files Falso" / "GClaude Indexer"
    pasta.mkdir(parents=True)

    alvo = pasta / "alvo.ps1"
    alvo.write_text(
        "param([switch]$AutoInstall, [string]$StatusFile = '', [switch]$SkipOllama)\n"
        "Write-Host \"rodou AutoInstall=$AutoInstall SkipOllama=$SkipOllama\"\n"
        "exit 0\n",
        encoding="utf-8",
    )

    log = pasta / "log.txt"
    done = pasta / "done.txt"
    status = pasta / "status.txt"

    def aspas(caminho):
        return "'" + str(caminho).replace("'", "''") + "'"

    runner = pasta / "runner.ps1"
    runner.write_text(
        "$ErrorActionPreference = 'Continue'\n"
        "$code = 1\n"
        "try {\n"
        f"  & {aspas(alvo)} -AutoInstall -StatusFile {aspas(status)} -SkipOllama"
        f" *>&1 | Out-File -LiteralPath {aspas(log)} -Encoding utf8\n"
        "  if ($null -ne $LASTEXITCODE) { $code = $LASTEXITCODE } else { $code = 0 }\n"
        "} catch {\n"
        f"  $_ | Out-String | Out-File -LiteralPath {aspas(log)} -Append -Encoding utf8\n"
        "  $code = 1\n"
        "}\n"
        f"Set-Content -LiteralPath {aspas(done)} -Value $code\n",
        encoding="utf-8",
    )

    subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
         "-ExecutionPolicy", "Bypass", "-File", str(runner)],
        capture_output=True, text=True, timeout=120,
    )

    assert done.exists(), "o sentinela não foi escrito"
    assert done.read_text(encoding="utf-8").strip() == "0"
    # UTF-8, por escolha: `*>` sozinho grava UTF-16 e o `catch` acrescenta
    # UTF-8, então o log de uma execução que falhou sairia metade em cada.
    assert "rodou AutoInstall=True SkipOllama=True" in log.read_text(encoding="utf-8")


def test_as_opcoes_da_tela_viram_argumentos():
    """Cada caixa desmarcada tem de virar um -Skip correspondente, e cada
    -Skip tem de existir no script. Um nome errado de um lado produz uma
    caixa que não faz nada — pior que não ter a caixa."""
    iss = ISS.read_text(encoding="utf-8")
    ps = (RAIZ / "install.ps1").read_text(encoding="utf-8")

    inicio = iss.find("function BuildScriptArguments")
    assert inicio != -1
    bloco = iss[inicio:iss.index("end;", inicio)]

    for switch in ("-SkipModelDownload", "-SkipOllama", "-SkipSensors",
                   "-CpuSensorShortcut"):
        assert switch in bloco, f"{switch} não é passado pela tela"
        assert f"${switch[1:]}" in ps, f"{switch} não existe em install.ps1"
