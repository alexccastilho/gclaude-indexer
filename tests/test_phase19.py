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

    for switch in ("-SkipModelDownload", "-SkipOllama", "-SkipSensors"):
        assert switch in bloco, f"{switch} não é passado pela tela"
        assert f"${switch[1:]}" in ps, f"{switch} não existe em install.ps1"


# --- o Ollama precisa estar no ar, não só instalado -----------------------


def _carregar_funcoes(nomes):
    """Carrega funções soltas do install.ps1 sem executar o script.

    O script instala cinco programas ao ser carregado, então dot-source
    está fora de questão. O parser do próprio PowerShell devolve o texto
    exato de cada função, que é tudo o que um teste precisa.
    """
    lista = ", ".join(f"'{n}'" for n in nomes)
    return (
        f"$caminho = '{RAIZ / 'install.ps1'}'; "
        "$ast = [System.Management.Automation.Language.Parser]::ParseFile("
        "$caminho, [ref]$null, [ref]$null); "
        f"$alvos = @({lista}); "
        "$ast.FindAll({ param($n) "
        "$n -is [System.Management.Automation.Language.FunctionDefinitionAst] "
        "-and $alvos -contains $n.Name }, $true) | "
        "ForEach-Object { Invoke-Expression $_.Extent.Text }; "
    )


def test_o_instalador_sobe_o_ollama_antes_de_perguntar_qualquer_coisa():
    """Ter o binário no disco não é ter o servidor no ar, e depois de uma
    instalação nova do winget normalmente não está. Numa máquina real isso
    produziu duas respostas erradas na mesma execução: `ollama list` falhou
    e o script concluiu que o modelo faltava, e em seguida `ollama pull`
    devolveu "a máquina de destino as recusou ativamente" e o usuário foi
    mandado rodar o comando à mão. Nada disso era verdade."""
    texto = (RAIZ / "install.ps1").read_text(encoding="utf-8")

    subida = texto.find("Start-OllamaIfNeeded -OllamaPath $OllamaPath")
    listagem = texto.find("& $OllamaPath list")
    baixada = texto.find("& $OllamaPath pull $DefaultModel")

    assert subida != -1, "o servidor nunca é iniciado"
    assert subida < listagem, "pergunta a lista antes de haver servidor"
    assert subida < baixada, "tenta baixar antes de haver servidor"


def test_a_deteccao_do_servidor_ollama_responde_sem_lancar():
    """A detecção é um connect TCP: precisa responder sim ou não em
    milissegundos, e nunca derrubar a instalação por não conseguir."""
    script = _carregar_funcoes(["Test-OllamaResponding"]) + (
        "if (Test-OllamaResponding -TimeoutMs 200) { 'SIM' } else { 'NAO' }"
    )
    linhas = [l for l in _rodar_ps(script).stdout.splitlines() if l.strip()]
    assert linhas and linhas[-1].strip() in ("SIM", "NAO")


# --- o construtor que existe no instalador e não no desinstalador ---------


def test_o_formulario_do_desinstalador_nao_usa_o_construtor_que_falha():
    """`TSetupForm.Create` carrega o recurso .dfm da classe. Esse recurso
    está ligado ao binário do instalador e não ao do desinstalador, então
    a chamada compila e morre em execução com "Resource TSetupForm not
    found" — foi o que apareceu ao abrir Programas e Recursos.

    Medido, não deduzido: um instalador descartável foi construído para
    tentar os quatro construtores dentro do desinstalador e anotar quais
    sobrevivem. `Create` falhou com essa mensagem exata; `CreateNew`
    funcionou, inclusive com um TNewCheckBox dentro."""
    texto = ISS.read_text(encoding="utf-8")

    assert "TSetupForm.Create(nil)" not in texto
    assert "TSetupForm.CreateNew(nil, 0)" in texto


def test_um_formulario_sem_dfm_define_o_que_o_dfm_daria():
    """CreateNew não herda nada: tamanho, posição, borda e fonte deixam de
    vir prontos e passam a ser responsabilidade de quem constrói."""
    texto = ISS.read_text(encoding="utf-8")
    inicio = texto.find("Form := TSetupForm.CreateNew(nil, 0);")
    assert inicio != -1
    bloco = texto[inicio:inicio + 900]

    for propriedade in ("Form.ClientWidth", "Form.ClientHeight",
                        "Form.Position", "Form.BorderStyle", "Form.Font.Name"):
        assert propriedade in bloco, f"{propriedade} não é definida"


# --- o atalho do sensor de CPU --------------------------------------------


def test_o_atalho_do_sensor_e_criado_pelo_instalador_e_nao_pelo_script():
    """A caixa marcada não criava atalho nenhum, e o aplicativo mandava o
    usuário abrir pelo atalho que não existia.

    O bloco inteiro do atalho no install.ps1 fica dentro de
    `if (-not $NoShortcut)`, e -NoShortcut é o que este instalador sempre
    passa — de propósito, para que a desinstalação consiga remover os
    atalhos. Passar -CpuSensorShortcut para um script que já decidiu não
    criar atalho nenhum não podia dar em nada."""
    iss = ISS.read_text(encoding="utf-8")
    ps = (RAIZ / "install.ps1").read_text(encoding="utf-8")

    # A premissa que torna a correção necessária, verificada e não suposta.
    bloco_ps = ps[ps.index("# --- 5b. Optional CPU-sensor shortcut"):]
    assert "if (-not $NoShortcut) {" in bloco_ps[:2000]

    # E a correção: o atalho passou a ser do instalador.
    icones = iss[iss.index("[Icons]"):iss.index("[Run]")]
    assert "--cpu-sensor" in icones
    assert "Check: CpuSensorShortcutWanted" in icones


def test_o_atalho_do_sensor_nao_aparece_sozinho_numa_instalacao_silenciosa():
    """Ao contrário das dependências, este não vale o padrão 'sim quando
    não há quem responda': ele arma um pedido de administrador em toda
    abertura futura do sistema."""
    iss = ISS.read_text(encoding="utf-8")
    inicio = iss.index("function CpuSensorShortcutWanted")
    bloco = iss[inicio:iss.index("end;", inicio)]

    assert "DepsChoicePage <> nil" in bloco
    # A chamada, não a palavra: o comentário cita DependencyWanted
    # justamente para dizer por que não a usa.
    assert "DependencyWanted(" not in bloco


# --- o segundo atalho com o sistema já aberto -----------------------------
#
# Estes exercitam funções Python, ao contrário do resto do arquivo, porque
# é ali que o segundo atalho deixava de funcionar: o atalho existia, era
# clicado, e o pedido morria num processo de vida curta.

import socket
import sys

sys.path.insert(0, str(RAIZ))


def test_a_porta_ocupada_e_detectada():
    from gclaude_indexer.sensor_service import server_listening

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as servidor:
        servidor.bind(("127.0.0.1", 0))
        servidor.listen(1)
        porta = servidor.getsockname()[1]

        assert server_listening("127.0.0.1", porta) is True

    # Fechado o socket, a mesma porta deixa de responder.
    assert server_listening("127.0.0.1", porta) is False


def test_o_dono_da_porta_e_identificado():
    """O ajudante elevado sobrevive a exatamente um processo: aquele cujo
    handle ele espera. Com o sistema já aberto, esse processo é o servidor
    que já está rodando — e sem descobrir o pid dele o ajudante morreria
    junto com o processo de vida curta que o pediu."""
    import os

    from gclaude_indexer.sensor_service import pid_listening_on

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as servidor:
        servidor.bind(("127.0.0.1", 0))
        servidor.listen(1)
        porta = servidor.getsockname()[1]

        encontrado = pid_listening_on(porta)

    # None é uma resposta legítima (o psutil recusa enumerar sockets de
    # outros usuários em algumas máquinas) e quem chama trata isso.
    if encontrado is not None:
        assert encontrado == os.getpid()


def test_um_segundo_servidor_nao_tenta_mais_tomar_a_porta():
    """Guarda contra a volta do erro 10048. O log da máquina do usuário
    tinha quatro inícios de servidor e três terminaram assim, cada um
    deles um clique no atalho que não produziu leitura nenhuma."""
    texto = (RAIZ / "gclaude_indexer" / "web" / "app.py").read_text(encoding="utf-8")
    inicio = texto.index("def start_server(")
    bloco = texto[inicio:]

    guarda = bloco.find("server_listening(host, port)")
    execucao = bloco.find("uvicorn.run(")
    assert guarda != -1, "não verifica se a porta já está tomada"
    assert guarda < execucao, "verifica tarde demais"


def test_o_ajudante_e_amarrado_ao_servidor_que_existe():
    texto = (RAIZ / "gclaude_indexer" / "web" / "app.py").read_text(encoding="utf-8")
    assert "start_elevated_helper(parent_pid=existing_pid)" in texto


# --- escopo de usuário contra escopo de máquina ---------------------------


def test_a_remocao_tenta_sem_elevacao_antes_de_elevar():
    """Uma desinstalação real removeu o Tesseract e deixou Ollama e Python
    para trás, com o usuário tendo de remover o Ollama à mão. O log conta
    a diferença entre eles: o Tesseract instala para a máquina inteira, os
    outros dois no perfil do próprio usuário. Um winget elevado é o
    contexto errado para um pacote que pertence ao perfil.

    Daí a ordem: pedir como o usuário primeiro, elevar depois só para o
    que sobrou. Nada se perde — um pacote de máquina apenas falha a
    primeira passada e sai na segunda."""
    texto = (RAIZ / "uninstall.ps1").read_text(encoding="utf-8")
    inicio = texto.find("Removing shared packages through winget")
    assert inicio != -1
    bloco = texto[inicio:]

    primeira = bloco.find("Uninstall-WingetPackage -Id $dependency.WingetId")
    sobrou = bloco.find("$StillThere = @(")
    elevada = bloco.find("Invoke-ElevatedWingetUninstall")

    assert primeira != -1, "não há passada sem elevação"
    assert primeira < sobrou < elevada, "a elevação não é a última tentativa"


def test_a_elevacao_so_recebe_o_que_sobrou():
    """Elevar para um pacote que já saiu é um pedido de administrador que
    não compra nada."""
    texto = (RAIZ / "uninstall.ps1").read_text(encoding="utf-8")
    inicio = texto.find("if ($StillThere.Count -gt 0")
    assert inicio != -1
    bloco = texto[inicio:inicio + 400]

    assert "$StillThere | ForEach-Object { $_.WingetId }" in bloco


def test_o_ollama_e_fechado_antes_de_ser_removido():
    """Um desinstalador não apaga arquivo aberto, e o servidor do Ollama
    normalmente está no ar: o Windows inicia o aplicativo de bandeja no
    logon, e o indexador sobe `ollama serve` sozinho quando precisa
    classificar."""
    texto = (RAIZ / "uninstall.ps1").read_text(encoding="utf-8")

    assert "function Stop-OllamaProcesses" in texto

    inicio = texto.find("Removing shared packages through winget")
    bloco = texto[inicio:]
    parada = bloco.find("Stop-OllamaProcesses")
    remocao = bloco.find("Uninstall-WingetPackage -Id $dependency.WingetId")
    assert parada != -1, "o Ollama nunca é fechado"
    assert parada < remocao, "fecha depois de tentar remover"


def test_fechar_o_ollama_funciona_com_ele_ausente():
    """Ninguém marca o Ollama numa máquina que não o tem, mas um
    desinstalador que lança exceção ao não encontrar um processo pararia
    no meio e deixaria o resto instalado."""
    script = (
        f". '{RAIZ / 'uninstall.ps1'}' -DryRunContract; "
        "Stop-OllamaProcesses; 'SOBREVIVEU'"
    )
    resultado = _rodar_ps(script)
    linhas = [l for l in resultado.stdout.splitlines() if l.strip()]
    assert linhas and linhas[-1].strip() == "SOBREVIVEU", resultado.stderr
