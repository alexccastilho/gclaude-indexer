"""Fase 15, Tarefa 3: opção de executar como administrador para o monitor de CPU.

O que estes testes protegem, em uma frase: **elevação é opção, nunca
exigência**, e o que sobe com privilégio é o leitor de sensores — não o
servidor, não a indexação, não os documentos do usuário.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
CAMINHO_INSTALAR_PS1 = RAIZ / "install.ps1"
CAMINHO_INDEXADOR_BAT = RAIZ / "Indexer.bat"
CAMINHO_INDEXADOR_VBS = RAIZ / "Indexer.vbs"

NOME_DO_ATALHO = "GClaude Indexer (CPU sensor)"

LEITURA_COMPLETA = {
    "cpu_temp_c": 47.5,
    "gpu_temp_c": 47.0,
    "cpu_potencia_w": 63.1,
    "gpu_potencia_w": 37.0,
    # Hotspot e ventoinha (fase 16, pedido explícito): numa placa moderna o
    # ponto quente fica dezenas de graus acima do núcleo e é ele que dita o
    # quanto a placa reduz o clock.
    "gpu_hotspot_c": 61.0,
    "gpu_fan_rpm": 1450,
    "clock_gpu_mhz": 109,
}


@pytest.fixture
def pasta_local(monkeypatch, tmp_path):
    """Isola o snapshot desta máquina: sem isso os testes leem e escrevem no
    `%LOCALAPPDATA%` de verdade, onde o auxiliar elevado publica."""
    from gclaude_indexer import sensors

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    # `read_sensors` mantém um cache de 2s em variável de módulo; sem zerar,
    # um teste herda a leitura do anterior.
    monkeypatch.setattr(sensors, "_last_reading", None)
    monkeypatch.setattr(sensors, "_last_reading_time", 0.0)
    return tmp_path / "GClaudeIndexer"


def _fingir_motivo(monkeypatch, motivo: str | None, computador: object | None = object()):
    from gclaude_indexer import sensors

    monkeypatch.setattr(sensors, "_state", lambda: (computador, motivo))


# --- o canal entre o auxiliar elevado e o servidor sem privilégio -----------


def test_snapshot_vai_e_volta(pasta_local):
    from gclaude_indexer import sensors

    sensors.write_snapshot(LEITURA_COMPLETA)
    assert sensors.snapshot_path() == pasta_local / "sensor_snapshot.json"
    assert sensors.read_snapshot() == LEITURA_COMPLETA


def test_snapshot_sem_arquivo_e_none(pasta_local):
    from gclaude_indexer import sensors

    assert sensors.read_snapshot() is None


def test_snapshot_velho_e_descartado(pasta_local):
    """O auxiliar morreu: a tela volta a dizer que não mediu, em vez de
    congelar uma temperatura antiga como se ainda fosse a de agora."""
    from gclaude_indexer import sensors

    sensors.write_snapshot(LEITURA_COMPLETA)
    conteudo = json.loads(sensors.snapshot_path().read_text(encoding="utf-8"))
    conteudo["written_at"] = time.time() - (sensors.SNAPSHOT_MAX_AGE_S + 5)
    sensors.snapshot_path().write_text(json.dumps(conteudo), encoding="utf-8")

    assert sensors.read_snapshot() is None


@pytest.mark.parametrize(
    "conteudo",
    [
        "isto não é json",
        json.dumps([1, 2, 3]),
        json.dumps({"reading": LEITURA_COMPLETA}),  # sem carimbo de tempo
        json.dumps({"written_at": "agora", "reading": LEITURA_COMPLETA}),
        json.dumps({"written_at": time.time(), "reading": {"cpu_temp_c": 40.0}}),  # chaves de menos
        json.dumps({"written_at": time.time(), "reading": {**LEITURA_COMPLETA, "extra": 1}}),
        json.dumps({"written_at": time.time(), "reading": {**LEITURA_COMPLETA, "cpu_temp_c": "quente"}}),
        json.dumps({"written_at": time.time(), "reading": {**LEITURA_COMPLETA, "cpu_temp_c": True}}),
    ],
)
def test_snapshot_estragado_nunca_vira_medicao(pasta_local, conteudo):
    """Um valor exibido ao usuário como medição não pode vir de um arquivo
    que ninguém conferiu — e nada disso pode levantar exceção."""
    from gclaude_indexer import sensors

    sensors.snapshot_path().parent.mkdir(parents=True, exist_ok=True)
    sensors.snapshot_path().write_text(conteudo, encoding="utf-8")

    assert sensors.read_snapshot() is None


def test_so_apaga_o_snapshot_que_e_seu(pasta_local):
    """Dois atalhos abertos: o segundo servidor não consegue a porta e cai,
    levando o auxiliar dele junto. Esse auxiliar não pode apagar a leitura
    que o primeiro ainda está publicando."""
    from gclaude_indexer import sensors

    sensors.write_snapshot(LEITURA_COMPLETA)
    conteudo = json.loads(sensors.snapshot_path().read_text(encoding="utf-8"))
    conteudo["pid"] = 999_999  # de outro processo
    sensors.snapshot_path().write_text(json.dumps(conteudo), encoding="utf-8")

    sensors.clear_snapshot()
    assert sensors.snapshot_path().exists()
    assert sensors.read_snapshot() == LEITURA_COMPLETA

    sensors.write_snapshot(LEITURA_COMPLETA)  # agora é nosso
    sensors.clear_snapshot()
    assert not sensors.snapshot_path().exists()


def test_apagar_snapshot_inexistente_nao_levanta(pasta_local):
    from gclaude_indexer import sensors

    sensors.clear_snapshot()  # sem arquivo nenhum
    assert sensors.read_snapshot() is None


def test_snapshot_do_futuro_e_descartado(pasta_local):
    from gclaude_indexer import sensors

    sensors.snapshot_path().parent.mkdir(parents=True, exist_ok=True)
    sensors.snapshot_path().write_text(
        json.dumps({"written_at": time.time() + 600, "reading": LEITURA_COMPLETA}), encoding="utf-8"
    )
    assert sensors.read_snapshot() is None


# --- o que a tela passa a mostrar ------------------------------------------


def test_com_o_auxiliar_no_ar_a_cpu_aparece_e_o_aviso_some(pasta_local, monkeypatch):
    """Servidor sem privilégio + auxiliar elevado publicando = leitura
    completa e nenhum aviso — a tela não pode continuar mandando o usuário
    fazer o que ele já fez."""
    from gclaude_indexer import sensors

    _fingir_motivo(monkeypatch, "sem_privilegio")
    sensors.write_snapshot(LEITURA_COMPLETA)

    assert sensors.unavailable_reason() is None
    assert sensors.read_sensors() == LEITURA_COMPLETA


def test_sem_o_auxiliar_o_motivo_continua_o_de_sempre(pasta_local, monkeypatch):
    from gclaude_indexer import sensors

    _fingir_motivo(monkeypatch, "sem_privilegio")
    assert sensors.unavailable_reason() == "sem_privilegio"


def test_o_snapshot_nao_encobre_biblioteca_faltando(pasta_local, monkeypatch):
    """O auxiliar roda na mesma máquina e na mesma pasta: ele não pode ter a
    DLL que falta aqui. Deixar o snapshot valer para `sem_dll` seria um
    caminho encobrindo o defeito do outro."""
    from gclaude_indexer import sensors

    _fingir_motivo(monkeypatch, "sem_dll", computador=None)
    sensors.write_snapshot(LEITURA_COMPLETA)

    assert sensors.unavailable_reason() == "sem_dll"
    assert sensors.read_sensors() == dict.fromkeys(sensors.KEYS)


# --- elevação é opção, nunca exigência -------------------------------------


@pytest.mark.parametrize("valor", ["1", "true", "TRUE", "yes", "on"])
def test_o_sinalizador_liga_a_opcao(monkeypatch, valor):
    from gclaude_indexer import sensor_service

    monkeypatch.setenv(sensor_service.ELEVATION_REQUEST_ENV, valor)
    assert sensor_service.elevation_requested() is True


@pytest.mark.parametrize("ambiente", [{}, {"GCLAUDE_INDEXER_CPU_SENSOR": ""},
                                      {"GCLAUDE_INDEXER_CPU_SENSOR": "0"},
                                      {"GCLAUDE_INDEXER_CPU_SENSOR": "talvez"}])
def test_sem_sinalizador_claro_nao_se_pede_nada(ambiente):
    """Qualquer coisa que não seja um sim explícito é não: o lado seguro de
    uma chave cujo único efeito é pedir administrador."""
    from gclaude_indexer import sensor_service

    assert sensor_service.elevation_requested(ambiente) is False


def test_o_lancador_padrao_nunca_chama_o_uac(monkeypatch):
    from gclaude_indexer import sensor_service

    monkeypatch.delenv(sensor_service.ELEVATION_REQUEST_ENV, raising=False)

    def _nao_deveria(*_args, **_kwargs):
        raise AssertionError("o lançador padrão não pode pedir elevação")

    monkeypatch.setattr(sensor_service, "_shell_execute_runas", _nao_deveria)
    assert sensor_service.start_elevated_helper(parent_pid=123) == "not_requested"


def test_recusar_o_uac_nao_e_erro(monkeypatch):
    """O usuário clicou "Não". Isso é uma decisão, não uma falha: nada
    levanta, nada aparece na cara dele, e o sistema segue igual ao padrão."""
    from gclaude_indexer import sensor_service

    monkeypatch.setenv(sensor_service.ELEVATION_REQUEST_ENV, "1")
    monkeypatch.setattr(sensor_service.sensors, "_is_admin", lambda: False)
    monkeypatch.setattr(sensor_service, "_shell_execute_runas",
                        lambda *_a: sensor_service._SE_ERR_ACCESSDENIED)

    assert sensor_service.start_elevated_helper(parent_pid=123) == "refused"


def test_falha_inesperada_da_elevacao_degrada_igual(monkeypatch):
    from gclaude_indexer import sensor_service

    monkeypatch.setenv(sensor_service.ELEVATION_REQUEST_ENV, "1")
    monkeypatch.setattr(sensor_service.sensors, "_is_admin", lambda: False)

    def _explode(*_args):
        raise OSError("shell32 recusou")

    monkeypatch.setattr(sensor_service, "_shell_execute_runas", _explode)
    assert sensor_service.start_elevated_helper(parent_pid=123) == "unavailable"


def test_ja_elevado_nao_abre_um_segundo_leitor(monkeypatch):
    from gclaude_indexer import sensor_service

    monkeypatch.setenv(sensor_service.ELEVATION_REQUEST_ENV, "1")
    monkeypatch.setattr(sensor_service.sensors, "_is_admin", lambda: True)
    monkeypatch.setattr(sensor_service, "_shell_execute_runas",
                        lambda *_a: pytest.fail("já elevado: não há o que pedir"))

    assert sensor_service.start_elevated_helper(parent_pid=123) == "already_elevated"


def test_pedido_aceito_sobe_o_auxiliar(monkeypatch):
    from gclaude_indexer import sensor_service

    monkeypatch.setenv(sensor_service.ELEVATION_REQUEST_ENV, "1")
    monkeypatch.setattr(sensor_service.sensors, "_is_admin", lambda: False)
    monkeypatch.setattr(sensor_service, "_shell_execute_runas", lambda *_a: 42)

    assert sensor_service.start_elevated_helper(parent_pid=123) == "started"


# --- o processo elevado ----------------------------------------------------


def test_comando_do_auxiliar_nao_escreve_pycache_e_e_sem_janela():
    """`-B` explícito porque o processo elevado é criado pelo serviço do
    Windows e não herda o ambiente daqui — e a pasta do projeto é
    sincronizada pelo Drive (seção 11.1)."""
    from gclaude_indexer import sensor_service

    programa, argumentos = sensor_service.helper_command(4321)

    assert argumentos[0] == "-B"
    assert argumentos[1:3] == ["-m", "gclaude_indexer.sensor_service"]
    assert argumentos[3:5] == ["--parent-pid", "4321"]
    # A pasta local do servidor vai explícita: elevar com credenciais de
    # OUTRO administrador troca o `%LOCALAPPDATA%` do filho, e o auxiliar
    # publicaria a leitura numa pasta que o servidor nunca lê.
    assert argumentos[5] == "--local-folder"
    assert argumentos[6] == str(sensor_service.machine_local_folder())
    assert sensor_service.MODULE_NAME == sensor_service.__name__
    assert programa.lower().endswith("python.exe") or programa.lower().endswith("pythonw.exe")


def test_o_auxiliar_publica_a_cada_ciclo_e_limpa_ao_sair(pasta_local, monkeypatch):
    from gclaude_indexer import sensor_service

    monkeypatch.setattr(sensor_service, "_open_parent_handle", lambda _pid: "handle")
    monkeypatch.setattr(sensor_service, "_wait_for_parent", lambda _h, _ms: False)
    monkeypatch.setattr(sensor_service, "_close_handle", lambda _h: None)
    monkeypatch.setattr(sensor_service.sensors, "read_sensors", lambda: dict(LEITURA_COMPLETA))

    publicadas: list[dict] = []
    monkeypatch.setattr(sensor_service.sensors, "write_snapshot", lambda leitura: publicadas.append(leitura))
    limpou: list[bool] = []
    monkeypatch.setattr(sensor_service.sensors, "clear_snapshot", lambda: limpou.append(True))

    assert sensor_service.run_helper(123, interval_s=0.0, max_cycles=3) == "max_cycles"
    assert publicadas == [LEITURA_COMPLETA] * 3
    assert limpou == [True], "sair sem apagar deixaria a tela com uma leitura que ninguém atualiza"


def test_o_auxiliar_morre_junto_com_o_servidor(pasta_local, monkeypatch):
    """Nenhum processo administrador sobrevive à janela que o pediu."""
    from gclaude_indexer import sensor_service

    monkeypatch.setattr(sensor_service, "_open_parent_handle", lambda _pid: "handle")
    monkeypatch.setattr(sensor_service, "_wait_for_parent", lambda _h, _ms: True)
    monkeypatch.setattr(sensor_service, "_close_handle", lambda _h: None)
    monkeypatch.setattr(sensor_service.sensors, "read_sensors", lambda: dict(LEITURA_COMPLETA))

    assert sensor_service.run_helper(123, interval_s=0.0) == "parent_exited"
    assert sensor_service.sensors.read_snapshot() is None


def test_servidor_ja_morto_nao_ganha_auxiliar(pasta_local, monkeypatch):
    from gclaude_indexer import sensor_service

    monkeypatch.setattr(sensor_service, "_open_parent_handle", lambda _pid: None)
    monkeypatch.setattr(sensor_service.sensors, "write_snapshot",
                        lambda _l: pytest.fail("não há a quem servir"))

    assert sensor_service.run_helper(123, interval_s=0.0) == "parent_gone"


def test_erro_ao_gravar_nao_derruba_o_auxiliar(pasta_local, monkeypatch):
    from gclaude_indexer import sensor_service

    monkeypatch.setattr(sensor_service, "_open_parent_handle", lambda _pid: "handle")
    monkeypatch.setattr(sensor_service, "_wait_for_parent", lambda _h, _ms: False)
    monkeypatch.setattr(sensor_service, "_close_handle", lambda _h: None)
    monkeypatch.setattr(sensor_service.sensors, "read_sensors", lambda: dict(LEITURA_COMPLETA))

    def _falha(_leitura):
        raise OSError("pasta ocupada")

    monkeypatch.setattr(sensor_service.sensors, "write_snapshot", _falha)
    monkeypatch.setattr(sensor_service.sensors, "clear_snapshot", lambda: None)

    assert sensor_service.run_helper(123, interval_s=0.0, max_cycles=2) == "max_cycles"


# --- onde a decisão é tomada -----------------------------------------------


def test_a_elevacao_e_pedida_na_subida_do_servidor(monkeypatch):
    from gclaude_indexer.web import app as modulo_app

    chamadas: list[str] = []
    monkeypatch.setattr(modulo_app, "_request_cpu_sensor_helper", lambda: chamadas.append("pediu"))

    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda *_a, **_k: None)
    modulo_app.start_server()

    assert chamadas == ["pediu"], "a decisão é tomada uma vez, na abertura"


def test_nenhuma_rota_http_pode_disparar_uac():
    """O servidor escuta em 127.0.0.1 e qualquer página aberta no navegador
    do usuário consegue fazer um POST para lá. Uma rota que elevasse daria a
    qualquer site o poder de fazer o prompt aparecer — e numa máquina com
    `ConsentPromptBehaviorAdmin = 0` nem prompt haveria, só um processo
    elevado."""
    from gclaude_indexer.web import app as modulo_app

    pontas = {getattr(rota, "endpoint", None) for rota in modulo_app.app.routes}
    assert modulo_app._request_cpu_sensor_helper not in pontas

    fonte = (RAIZ / "gclaude_indexer" / "web" / "app.py").read_text(encoding="utf-8")
    for linha in fonte.splitlines():
        if "start_elevated_helper" in linha:
            assert "@app." not in linha


def test_pedir_elevacao_nunca_derruba_o_servidor(monkeypatch):
    from gclaude_indexer.web import app as modulo_app
    from gclaude_indexer import sensor_service

    def _explode():
        raise RuntimeError("shell32 sumiu")

    monkeypatch.setattr(sensor_service, "start_elevated_helper", _explode)
    assert modulo_app._request_cpu_sensor_helper() == "unavailable"


# --- os lançadores ---------------------------------------------------------


def test_o_bat_so_liga_o_sensor_com_o_sinalizador():
    texto = CAMINHO_INDEXADOR_BAT.read_text(encoding="utf-8-sig")

    assert '"%~1"=="--cpu-sensor"' in texto
    assert 'set "GCLAUDE_INDEXER_CPU_SENSOR=1"' in texto
    # a variável aparece só dentro do ramo do sinalizador
    linhas_com_a_variavel = [l for l in texto.splitlines() if "GCLAUDE_INDEXER_CPU_SENSOR=1" in l]
    assert len(linhas_com_a_variavel) == 1


def test_o_bat_nao_eleva_a_si_mesmo():
    """O lançador padrão continua exatamente como estava: nada de RunAs,
    nada de requireAdministrator."""
    texto = CAMINHO_INDEXADOR_BAT.read_text(encoding="utf-8-sig").lower()

    assert "runas" not in texto
    assert "-verb" not in texto


def test_o_vbs_repassa_so_o_sinalizador_conhecido():
    texto = CAMINHO_INDEXADOR_VBS.read_text(encoding="utf-8-sig")

    assert "WScript.Arguments" in texto
    assert '"--cpu-sensor"' in texto
    # o valor vai para uma linha de comando: tem de ser reemitido literal,
    # nunca concatenado do que chegou
    assert 'ExtraArgument = " --cpu-sensor"' in texto
    assert "WScript.Arguments(0)" not in texto.split("ExtraArgument = \" --cpu-sensor\"")[1]


# --- o instalador ofereceu ---------------------------------------------------


def _texto_ps1() -> str:
    return CAMINHO_INSTALAR_PS1.read_text(encoding="utf-8-sig")


def test_instalador_oferece_o_atalho_do_sensor_perguntando():
    texto = _texto_ps1()

    assert "GClaude Indexer (CPU sensor).lnk" in texto
    assert "wscript.exe" in texto
    assert "--cpu-sensor" in texto
    assert 'Read-Host "  Create the ""GClaude Indexer (CPU sensor)"" shortcut too? (Y/N)"' in texto


def test_instalador_diz_o_que_se_ganha_e_o_que_se_paga():
    """Sem isso o usuário aceita sem entender."""
    texto = _texto_ps1()

    assert "What you gain: CPU temperature and power draw on the Run screen." in texto
    assert "What you pay:  Windows asks for administrator every time you open it." in texto
    assert "Only the sensor reader is elevated" in texto


def test_o_atalho_do_sensor_respeita_noshortcut():
    texto = _texto_ps1()

    corpo = texto.split("--- 5b. Optional CPU-sensor shortcut")[1]
    assert "if (-not $NoShortcut) {" in corpo
    assert "CPU sensor shortcut not created (-NoShortcut)." in corpo


def test_autoinstall_sozinho_nao_arma_um_uac_recorrente():
    texto = _texto_ps1()

    corpo = texto.split("--- 5b. Optional CPU-sensor shortcut")[1]
    assert "if ($AutoInstall) {" in corpo
    assert "-AutoInstall does not create this one" in corpo
    assert "[switch]$CpuSensorShortcut," in texto


def test_o_atalho_padrao_continua_sem_argumento_nenhum():
    """Requisito central: o lançador padrão não mudou."""
    texto = _texto_ps1()

    bloco_padrao = texto.split("# --- 5. Desktop shortcut")[1].split("# --- 5b.")[0]
    assert "New-DesktopShortcut -TargetPath $IndexerVbsPath -WorkingDirectory $ProjectRoot -IconPath $ShortcutIconPath" in bloco_padrao
    assert "--cpu-sensor" not in bloco_padrao
    assert "cpu" not in bloco_padrao.lower().split("$createdshortcutpath")[0]


# --- a interface aponta o caminho, nos três idiomas -------------------------


def test_os_tres_idiomas_nomeiam_o_atalho_exato():
    from gclaude_indexer.i18n import translate

    for idioma in ("pt", "en", "es"):
        texto = translate(idioma, "resources.sensors.no_privilege")
        assert NOME_DO_ATALHO in texto, idioma
        assert "install.ps1" in texto, idioma


def test_os_tres_idiomas_dizem_que_so_o_leitor_eleva():
    """A frase não pode dizer "rode o sistema como administrador": não é
    isso que o atalho faz, e não é isso que se quer que o usuário faça."""
    from gclaude_indexer.i18n import translate

    esperado = {
        "pt": "só o leitor de sensores, não o sistema todo",
        "en": "only the sensor reader, not the whole system",
        "es": "solo el lector de sensores, no todo el sistema",
    }
    for idioma, trecho in esperado.items():
        assert trecho in translate(idioma, "resources.sensors.no_privilege"), idioma


def test_a_tela_sobre_aponta_o_mesmo_caminho_e_nao_contradiz_o_instalador(monkeypatch):
    """A tarefa anterior teve de remover um ramo desta tela que mandava
    gravar de volta o que o instalador acabara de apagar. Aqui a orientação
    é a mesma que o instalador oferece — e a coluna do comando continua
    vazia, porque a DLL está presente e não há nada a instalar."""
    import gclaude_indexer.install_diagnostics as dm
    from gclaude_indexer.i18n import translate

    monkeypatch.setattr(dm, "dll_path", lambda: type("Falso", (), {"is_file": lambda self: True})())
    monkeypatch.setattr(dm, "unavailable_reason", lambda: "sem_privilegio")

    for idioma in ("pt", "en", "es"):
        item = {i["key"]: i for i in dm.check_installation(idioma)}["hardware_sensors"]
        assert item["version"] == translate(idioma, "resources.sensors.no_privilege")
        assert NOME_DO_ATALHO in item["version"], idioma
        assert not item["install_command"], idioma


def test_a_tela_de_execucao_leva_o_texto_novo_pelo_mesmo_caminho():
    """`run.html` monta `SENSOR_REASON_TEXTS` no template, com `| tojson`: é
    isso que faz as aspas tipográficas e a pontuação do texto novo chegarem
    inteiras ao JavaScript, em vez de quebrarem o script da tela."""
    modelo = (RAIZ / "gclaude_indexer" / "web" / "templates" / "run.html").read_text(encoding="utf-8")
    assert "sem_privilegio: {{ t('resources.sensors.no_privilege') | tojson }}" in modelo


# --- tarefa 4: o instalador instala o Python 3.12 sozinho --------------------


def test_instalador_instala_o_python_em_vez_de_so_avisar():
    """Detectar não é resolver: o bloco tem de ter as duas rotas — winget e o
    instalador oficial do python.org, com versão fixada e hash conferido —
    e não pode mais sair com `exit 1` na primeira ausência."""
    texto = _texto_ps1()

    assert "function Install-PythonRuntime {" in texto
    assert '$PythonInstallerVersion = "3.12.10"' in texto
    assert '$PythonUrlPrefix = "https://www.python.org/ftp/python/"' in texto
    assert "67b5635e80ea51072b87941312d00ec8927c4db9ba18938f7ad2d27b328b95fb" in texto

    corpo = texto.split("function Install-PythonRuntime {")[1].split("$PythonBase = Find-PythonBase")[0]
    assert "winget install --id $PythonWingetId -e --scope user" in corpo
    assert "Get-VerifiedDownload" in corpo
    assert "-ExpectedSha256 $pin.Sha256" in corpo
    # a elevação existe, e é a que o arquivo já tinha
    assert "Start-ProcessElevated" in corpo


def test_o_python_entra_ao_lado_e_nao_por_cima_do_que_ja_existe():
    """`PrependPath=0` e `AssociateFiles=0` são a promessa "lado a lado"
    escrita como parâmetro: o `python` do PATH e o duplo clique num `.py`
    continuam apontando para onde apontavam."""
    texto = _texto_ps1()
    corpo = texto.split("function Install-PythonRuntime {")[1].split("$PythonBase = Find-PythonBase")[0]

    assert '"InstallAllUsers=0", "PrependPath=0", "AssociateFiles=0"' in corpo
    assert '"PrependPath=1"' not in corpo
    # o escopo de usuário do winget existe pelo mesmo motivo
    assert "--scope user" in corpo


def test_o_instalador_procura_o_python_sem_depender_do_path():
    """O miolo da tarefa: o processo não enxerga um PATH escrito depois de
    ele nascer, então a redetecção recarrega o PATH do registro e ainda tem
    duas rotas que não dependem de PATH nenhum."""
    texto = _texto_ps1()

    assert "function Resolve-PythonAfterInstall {" in texto
    corpo = texto.split("function Resolve-PythonAfterInstall {")[1].split("function Install-PythonRuntime {")[0]
    assert "Update-SessionPath" in corpo
    assert "Find-PythonBase" in corpo

    assert "function Get-PythonFromRegistry {" in texto
    assert r"Software\Python\PythonCore" in texto
    assert "function Get-PythonKnownFolder {" in texto

    # e cada rota termina perguntando a versão ao próprio interpretador,
    # porque esta máquina tinha uma chave de registro 3.12 órfã
    procura = texto.split("function Find-PythonBase {")[1].split("function Resolve-PythonAfterInstall {")[0]
    assert procura.count("-eq $RequiredPythonVersion") == 4

    # o mesmo defeito existia em dois vizinhos: quem instala pelo winget
    # conferia o PATH velho logo depois de instalar
    for bloco in (
        texto.split("function Install-IfMissing {")[1].split("function Get-VerifiedDownload")[0],
        texto.split("--- 4d. Ollama")[1].split("--- 4e.")[0],
    ):
        depois = bloco.split("winget install --id")[-1]
        assert "Update-SessionPath" in depois.split("Find-Command")[0]


def test_a_orientacao_manual_continua_para_quando_nao_ha_mais_o_que_fazer():
    """A mensagem de hoje continua certa quando todas as rotas se esgotaram
    ou o usuário recusou — só deixou de ser a primeira resposta."""
    texto = _texto_ps1()

    assert "Python $RequiredPythonVersion is missing and could not be installed automatically." in texto
    assert "Install it with:  $PythonWingetCommand" in texto
    assert "leaves your other versions alone" in texto


# --- tarefa 5: o Ghostscript entra sozinho, sem UAC e sem janela pendurada ---
#
# O que estes testes protegem: o Ghostscript é **descompactado** na pasta do
# próprio usuário, e o instalador do fornecedor — que exige administrador e
# para numa janela "Finish" — sobrou como rota de reserva, onde a espera é
# pela condição (o binário responder) e não pelo fim do processo.


def _bloco_ps1(inicio: str, fim: str) -> str:
    texto = _texto_ps1()
    assert inicio in texto and fim in texto
    return texto.split(inicio)[1].split(fim)[0]


def test_o_ghostscript_vai_para_a_pasta_da_maquina_nao_para_program_files():
    """`%LOCALAPPDATA%\\GClaudeIndexer` é onde o venv, a `lib` e o catálogo já
    moram. Program Files exigia administrador e não dava nada em troca: o
    Ghostscript acha seus recursos pelo caminho do executável."""
    texto = _texto_ps1()

    assert '$GhostscriptFolder = Join-Path $LocalFolder "gs"' in texto
    assert '$GhostscriptBinFolder = Join-Path $GhostscriptFolder "bin"' in texto
    assert '$GhostscriptExePath = Join-Path $GhostscriptBinFolder "gswin64c.exe"' in texto
    # a rota antiga apontava para cá; não pode ter sobrado
    assert 'Join-Path ${env:ProgramFiles} "gs\\gs$GhostscriptVersion\\bin"' not in texto


def test_o_download_continua_fixado_e_com_hash_conferido():
    """Os dois arquivos de terceiros passam pelo mesmo portão: URL com
    prefixo exigido e SHA-256 conferido, sem ramo de "avisa e segue"."""
    texto = _texto_ps1()

    assert '$GhostscriptUrlPrefix = "https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/"' in texto
    assert "3a4c28d0aac47aa7cccd35a5932c55110376e9dbd966898dde388b7faba444a4" in texto
    assert '$SevenZipUrlPrefix = "https://github.com/ip7z/7zip/releases/download/"' in texto
    assert "db407a4f6d4999e5c7bc00ce8a882be94717b56e7fa68140fe3f12605d91643e" in texto

    extrator = _bloco_ps1("function Get-SevenZipExtractor {", "function Expand-Ghostscript {")
    assert "Get-VerifiedDownload" in extrator
    assert "-ExpectedSha256 $SevenZipSha256" in extrator
    assert "-RequiredPrefix $SevenZipUrlPrefix" in extrator

    instalar = _bloco_ps1("function Install-Ghostscript {", "Write-Host \"\"")
    assert "-ExpectedSha256 $GhostscriptSha256" in instalar
    assert "-RequiredPrefix $GhostscriptUrlPrefix" in instalar


def test_a_rota_normal_nao_pede_administrador_em_lugar_nenhum():
    """Descompactar não eleva: `msiexec /a` só copia os arquivos do pacote, e
    `Start-QuietProcess` usa `-NoNewWindow`, ou seja UseShellExecute = $false
    — um processo lançado assim não consegue elevar nem se quiser."""
    extrator = _bloco_ps1("function Get-SevenZipExtractor {", "function Expand-Ghostscript {")
    descompactar = _bloco_ps1("function Expand-Ghostscript {", "function New-GhostscriptUnattendedScript {")

    assert '"/a", "`"$package`"", "/qn", "TARGETDIR=`"$target`""' in extrator
    for bloco in (extrator, descompactar):
        assert "Start-QuietProcess" in bloco
        assert "Start-ProcessElevated" not in bloco
        assert "Invoke-ElevatedScript" not in bloco
        assert "Verb" not in bloco


def test_a_espera_e_pela_condicao_e_a_janela_e_fechada():
    """O miolo: o processo do instalador do fornecedor não termina sozinho —
    ele fica na página "Finish". Espera-se o binário responder a `--version`
    e, com isso feito, mata-se o processo. A instalação já acabou ali."""
    gerado = _bloco_ps1("function New-GhostscriptUnattendedScript {", "function Install-Ghostscript {")

    assert "--version" in gerado
    assert "`$process.HasExited" in gerado
    assert "`$process.Kill()" in gerado
    assert "`$deadline = (Get-Date).AddSeconds($TimeoutSeconds)" in gerado
    assert "Start-Sleep -Seconds 2" in gerado
    # sucesso e desistência têm códigos diferentes, e quem chama confere
    assert "if (`$ready) { exit 0 }" in gerado
    assert "exit 3" in gerado
    # `/D=` vai inteiro, sem aspas e por último: o NSIS lê o resto da linha
    assert '-ArgumentList "/S /D=`$destination"' in gerado


def test_o_limite_de_tempo_existe_e_a_falha_so_avisa():
    """Estourar o tempo degrada como as outras dependências: aviso amarelo e
    `return $false`, nunca `exit` no meio da instalação."""
    texto = _texto_ps1()
    instalar = _bloco_ps1("function Install-Ghostscript {", "Write-Host \"\"")

    assert "$GhostscriptWaitSeconds = 600" in texto
    assert "-TimeoutSeconds ($GhostscriptWaitSeconds + 120)" in instalar
    assert "did not produce a working binary within $GhostscriptWaitSeconds s" in instalar
    assert "exit 1" not in instalar
    assert instalar.count("return $false") >= 3


def test_um_ghostscript_que_ja_existe_e_respeitado():
    """Ache primeiro, instale só se faltar: nem o Ghostscript do usuário em
    Program Files nem o que uma execução anterior descompactou são tocados,
    e a segunda execução não baixa nada."""
    instalar = _bloco_ps1("function Install-Ghostscript {", "Write-Host \"\"")
    antes = instalar.split("Get-VerifiedDownload")[0]

    assert "$found = Find-Command $GhostscriptBinaries" in antes
    assert "Test-GhostscriptAnswers -Path $GhostscriptExePath" in antes
    assert 'Write-Host "Ghostscript OK: $found"' in antes
    # e o retorno acontece antes de qualquer download
    assert antes.index("Ghostscript OK: $found") < antes.index("Ghostscript not found.")


def test_o_path_alterado_e_o_do_usuario_nunca_o_da_maquina():
    """A pasta `bin` precisa entrar no PATH do usuário e na sessão de agora;
    escrever no PATH da máquina traria de volta a elevação que a tarefa
    inteira existe para eliminar."""
    texto = _texto_ps1()
    helper = _bloco_ps1("function Add-UserPathEntry {", "# --- 4a.")

    assert '[Microsoft.Win32.Registry]::CurrentUser.OpenSubKey("Environment", $true)' in helper
    assert "DoNotExpandEnvironmentNames" in helper
    assert "$env:Path = $env:Path.TrimEnd(';') + ';' + $Folder" in helper
    assert "LocalMachine" not in helper
    assert '"Machine"' not in helper
    # e a mudança é anunciada, senão só valeria no próximo login
    assert "Publish-EnvironmentChange" in helper
    assert "WM_SETTINGCHANGE" in texto or "0x1A" in texto

    instalar = _bloco_ps1("function Install-Ghostscript {", "Write-Host \"\"")
    assert instalar.count("Add-UserPathEntry -Folder $GhostscriptBinFolder") >= 3


def test_o_codigo_de_saida_de_um_instalador_deixou_de_ser_invisivel():
    """`Start-Process -PassThru` devolve um objeto cujo ExitCode fica `$null`
    para sempre; sem ler o handle, todo aviso "returned code N" deste arquivo
    era código morto."""
    texto = _texto_ps1()

    assert texto.count("try { $null = $process.Handle } catch { }") == 2
    for nome, fim in (
        ("function Start-ProcessElevated {", "function Start-QuietProcess {"),
        ("function Start-QuietProcess {", "function Invoke-ElevatedScript {"),
    ):
        assert "try { $null = $process.Handle } catch { }" in _bloco_ps1(nome, fim)
