"""Phase 13 tests: GPU telemetry, quality report and visual layouts."""

from __future__ import annotations

import time

import fitz
import pytest
from fastapi.testclient import TestClient

import gclaude_indexer.catalog as catalogo_mod
import gclaude_indexer.hardware as hardware_mod
from gclaude_indexer.engine_local import DEFAULT_LOCAL_MODEL
import gclaude_indexer.sensors as sensors_mod
from gclaude_indexer.web.app import app
from gclaude_indexer.web.background_runs import task_manager


@pytest.fixture(autouse=True)
def limpar_gerenciador():
    task_manager._tasks.clear()
    yield
    task_manager._tasks.clear()


@pytest.fixture(autouse=True)
def isolar_cache_de_contadores_windows():
    """`windows_counters._cache` (revisão final da Fase 13, correção C1) é
    um dict de módulo com validade de ~1s — sem isolamento, um teste que
    roda logo depois de outro dentro dessa janela herdaria uma leitura
    "requentada" de PowerShell mockado por outro teste."""
    import gclaude_indexer.windows_counters as windows_counters_mod

    windows_counters_mod._cache.clear()
    yield
    windows_counters_mod._cache.clear()


@pytest.fixture(autouse=True)
def isolar_sensores_do_hardware_real(tmp_path, monkeypatch):
    """Sem isto, `sensors.py` fala com o hardware de verdade desta máquina —
    as DLLs (`LibreHardwareMonitorLib.dll` e os shims) estão de fato instaladas
    em `%LOCALAPPDATA%\\GClaudeIndexer\\lib\\`, e `Open()` agora funciona de
    verdade aqui. Sem isolamento, testes que não mockam `sensors`/`resources`
    explicitamente acabariam lendo sensores reais (não determinístico, varia
    de máquina para máquina) e poluindo o cache global de `read_sensors()`
    entre testes. Aponta `machine_local_folder` para uma pasta vazia, então por
    padrão `_state()` sempre devolve `(None, "sem_dll")`; testes que
    precisam de outro comportamento monkeypatcham por cima disso normalmente.
    """
    monkeypatch.setattr(sensors_mod, "machine_local_folder", lambda: tmp_path / "sem_sensores")
    sensors_mod._state.cache_clear()
    monkeypatch.setattr(sensors_mod, "_last_reading", None)
    monkeypatch.setattr(sensors_mod, "_last_reading_time", 0.0)
    yield
    # Alguns testes substituem `_state` por um dublê (perde `.cache_clear`);
    # nesse caso não há cache real a limpar — o `monkeypatch` já vai
    # restaurar `_state` original ao desfazer o `setattr` do próprio teste.
    limpar = getattr(sensors_mod._state, "cache_clear", None)
    if limpar is not None:
        limpar()


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    pasta_local = tmp_path / "local_maquina"
    monkeypatch.setattr(catalogo_mod, "machine_local_folder", lambda: pasta_local)
    monkeypatch.setattr(hardware_mod, "machine_local_folder", lambda: pasta_local)
    monkeypatch.setattr(sensors_mod, "machine_local_folder", lambda: pasta_local)
    return TestClient(app)


def _pdf(caminho, texto):
    documento = fitz.open()
    pagina = documento.new_page()
    pagina.insert_textbox((50, 50, 550, 750), texto, fontsize=12)
    documento.save(caminho)
    documento.close()


def _criar_projeto(cliente, tmp_path, nome="Projeto fase 13", **campos_extra):
    origem = tmp_path / "origem" / nome.replace(" ", "_")
    pasta_volume_1 = origem / "volume_1"
    pasta_volume_1.mkdir(parents=True, exist_ok=True)
    saida = tmp_path / f"{nome.replace(' ', '_')}_indexado"
    # Se o chamador já povoou "volume_1" com seus próprios arquivos (caso de
    # testes que montam o próprio acervo antes de criar o projeto), não
    # acrescenta o PDF padrão por cima — isso mudaria a contagem esperada.
    if not any(pasta_volume_1.iterdir()):
        _pdf(pasta_volume_1 / "peca.pdf",
             "OFÍCIO No 1\nAssunto: teste da fase 13, com texto suficiente para não acionar OCR.\n10/01/2024")
    dados = {
        "name": nome, "subject": "Acervo de teste", "source_folder": str(origem), "output_folder": str(saida),
        "collection_type": "processo", "group_mode": "subfolder", "group_pattern": "",
        "extensions": ["pdf", "docx", "imagens"], "pages_per_block": "80", "pages_per_window": "16",
        "overlap": "2", "chars_per_page": "2000", "ocr_language": "por",
        "classification_engine": "rules", "local_model": "gemma4:e4b", "role_instructions": "", "extra_rules": "",
    }
    dados.update(campos_extra)
    resposta = cliente.post("/projects/new", data=dados, follow_redirects=False)
    assert resposta.status_code == 303, resposta.text
    return int(resposta.headers["location"].split("/")[2])


def _esperar_etapa_terminar(projeto_id: int, etapa: str, timeout: float = 30):
    fim = time.monotonic() + timeout
    while time.monotonic() < fim:
        tarefa = task_manager.get(projeto_id, etapa)
        if tarefa is not None and not tarefa.running:
            return tarefa
        time.sleep(0.05)
    raise AssertionError(f"etapa '{etapa}' não terminou em {timeout}s")


# --- Tarefa 1: GPU de qualquer fabricante ----------------------------------


def test_contadores_nunca_levantam_mesmo_com_powershell_quebrado(monkeypatch):
    """A tela de Execução consulta isto a cada 500ms — uma exceção aqui
    derrubaria o gráfico inteiro."""
    from gclaude_indexer import windows_counters

    def _explode(*_a, **_k):
        raise OSError("powershell sumiu")

    monkeypatch.setattr(windows_counters, "run_hidden", _explode)
    assert windows_counters.gpu_usage_percent() is None
    assert windows_counters.vram_used_mb() is None
    assert windows_counters.available() is False


def test_uso_de_gpu_e_percentual_valido_ou_none(monkeypatch):
    from gclaude_indexer import windows_counters

    class _Resultado:
        returncode = 0
        stdout = "37.5\n"

    monkeypatch.setattr(windows_counters, "run_hidden", lambda *a, **k: _Resultado())
    assert windows_counters.gpu_usage_percent() == 37.5


def test_uso_de_gpu_nunca_passa_de_cem(monkeypatch):
    """A soma das engines pode estourar 100 (3D + Copy + Compute simultâneos)."""
    from gclaude_indexer import windows_counters

    class _Resultado:
        returncode = 0
        stdout = "265.0\n"

    monkeypatch.setattr(windows_counters, "run_hidden", lambda *a, **k: _Resultado())
    assert windows_counters.gpu_usage_percent() == 100.0


def test_amostra_usa_contadores_quando_nao_ha_nvidia_smi(monkeypatch):
    """O caso desta máquina: GPU AMD, sem nvidia-smi. Antes devolvia None e a
    tela dizia 'sem GPU NVIDIA detectada' com a GPU em uso."""
    import gclaude_indexer.resources as resources_mod

    resources_mod._vram_total_mb.cache_clear()
    monkeypatch.setattr(resources_mod, "find_tool", lambda _nome: None)
    monkeypatch.setattr(resources_mod, "gpu_usage_percent", lambda: 42.0)
    monkeypatch.setattr(resources_mod, "vram_used_mb", lambda: 5017)
    monkeypatch.setattr(resources_mod, "vram_total_mb", lambda: 8176)

    amostra = resources_mod.sample_resources()
    assert amostra.gpu_percent == 42.0
    assert amostra.gpu_vram_used_mb == 5017


def test_vram_total_vem_do_registro_e_nao_satura_em_4gb(monkeypatch):
    """AdapterRAM é uint32 e satura em 4095 MB; esta placa tem 8 GB."""
    from gclaude_indexer import windows_counters

    class _R:
        returncode = 0
        stdout = "8176\n"

    monkeypatch.setattr(windows_counters, "run_hidden", lambda *a, **k: _R())
    assert windows_counters.vram_total_mb() == 8176


def test_vram_total_devolve_none_em_falha(monkeypatch):
    from gclaude_indexer import windows_counters

    monkeypatch.setattr(windows_counters, "run_hidden",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("sem registro")))
    assert windows_counters.vram_total_mb() is None


def test_amostra_prefere_o_total_do_registro(monkeypatch):
    import gclaude_indexer.resources as resources_mod

    resources_mod._vram_total_mb.cache_clear()
    monkeypatch.setattr(resources_mod, "find_tool", lambda _n: None)
    monkeypatch.setattr(resources_mod, "vram_total_mb", lambda: 8176)
    monkeypatch.setattr(resources_mod, "gpu_usage_percent", lambda: 20.0)
    monkeypatch.setattr(resources_mod, "vram_used_mb", lambda: 1602)

    a = resources_mod.sample_resources()
    assert a.gpu_vram_total_mb == 8176, "não pode cair no AdapterRAM saturado"


def test_vram_total_soma_todas_as_gpus(monkeypatch):
    """Uso e VRAM usada somam todas as GPUs; o total precisa somar também,
    senão numa máquina com integrada + dedicada o usado pode passar do total."""
    from gclaude_indexer import windows_counters

    class _R:
        returncode = 0
        stdout = "10224\n"   # 8176 dedicada + 2048 integrada

    monkeypatch.setattr(windows_counters, "run_hidden", lambda *a, **k: _R())
    assert windows_counters.vram_total_mb() == 10224


def test_cai_nos_contadores_quando_nvidia_smi_existe_mas_falha(monkeypatch):
    """nvidia-smi presente mas quebrado (driver em atualização, permissão)
    não pode zerar o painel: tem de cair nos contadores."""
    import gclaude_indexer.resources as resources_mod

    monkeypatch.setattr(resources_mod, "find_tool", lambda _n: "C:/fake/nvidia-smi.exe")
    monkeypatch.setattr(resources_mod, "_sample_nvidia_gpu", lambda _c: (None, None, None))
    monkeypatch.setattr(resources_mod, "gpu_usage_percent", lambda: 55.0)
    monkeypatch.setattr(resources_mod, "vram_used_mb", lambda: 900)
    resources_mod._vram_total_mb.cache_clear()
    monkeypatch.setattr(resources_mod, "vram_total_mb", lambda: 8176)

    a = resources_mod.sample_resources()
    assert a.gpu_percent == 55.0
    assert a.gpu_vram_used_mb == 900


def test_total_cai_no_adapterram_quando_o_registro_falha(monkeypatch):
    """Registro inacessível não pode virar None se o WMI ainda responde —
    um total impreciso é melhor que nenhum."""
    import gclaude_indexer.resources as resources_mod

    resources_mod._vram_total_mb.cache_clear()
    monkeypatch.setattr(resources_mod, "vram_total_mb", lambda: None)

    class _Gpu:
        vram_mb = 4095

    monkeypatch.setattr(resources_mod, "_detect_nvidia_gpu", lambda: None)
    monkeypatch.setattr(resources_mod, "_detect_wmi_gpu", lambda: _Gpu())

    assert resources_mod._vram_total_mb() == 4095


# --- Tarefa 2: clocks -------------------------------------------------------


def test_clock_de_memoria_e_cacheado_e_inteiro(monkeypatch):
    from gclaude_indexer import windows_counters

    class _R:
        returncode = 0
        stdout = "3600\n"

    chamadas = []
    def _fake(*a, **k):
        chamadas.append(1)
        return _R()

    windows_counters.memory_clock_mhz.cache_clear()
    monkeypatch.setattr(windows_counters, "run_hidden", _fake)
    assert windows_counters.memory_clock_mhz() == 3600
    assert windows_counters.memory_clock_mhz() == 3600
    assert len(chamadas) == 1, "clock de memória não muda: deve ser consultado uma vez só"


def test_clocks_devolvem_none_em_falha(monkeypatch):
    from gclaude_indexer import windows_counters

    windows_counters.memory_clock_mhz.cache_clear()
    monkeypatch.setattr(windows_counters, "run_hidden",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("sem powershell")))
    assert windows_counters.clock_cpu_mhz() is None
    assert windows_counters.memory_clock_mhz() is None
    assert windows_counters.clock_gpu_mhz() is None


def test_amostra_expoe_os_tres_clocks(monkeypatch):
    import gclaude_indexer.resources as resources_mod

    monkeypatch.setattr(resources_mod, "clock_cpu_mhz", lambda: 4400)
    monkeypatch.setattr(resources_mod, "memory_clock_mhz", lambda: 3600)
    monkeypatch.setattr(resources_mod, "clock_gpu_mhz", lambda: None)

    a = resources_mod.sample_resources()
    assert a.clock_cpu_mhz == 4400
    assert a.clock_memory_mhz == 3600
    assert a.clock_gpu_mhz is None, "clock de GPU indisponível vira None, nunca 0"


# --- Tarefa 3: sensores -----------------------------------------------------


def test_sensores_degradam_sem_pythonnet(monkeypatch):
    """Sem a dependência, tudo vira None e o motivo é nomeável — a tela nunca
    mostra 0 °C como se fosse medição."""
    from gclaude_indexer import sensors

    monkeypatch.setattr(sensors, "_import_library", lambda: None)
    sensors._state.cache_clear()

    leitura = sensors.read_sensors()
    # Comparado com `sensors.KEYS`, não com uma lista escrita à mão: o
    # conjunto cresceu na fase 16 (hotspot e ventoinha da GPU) e uma cópia
    # literal aqui quebra a cada leitura nova sem proteger nada — o que este
    # teste garante é que TODA chave venha presente e nula, não quais são.
    assert set(leitura) == set(sensors.KEYS)
    assert all(v is None for v in leitura.values())
    assert sensors.unavailable_reason() in ("sem_dll", "sem_pythonnet", "sem_privilegio")


def test_sensores_nunca_levantam(monkeypatch):
    from gclaude_indexer import sensors

    def _explode():
        raise RuntimeError("driver recusou")

    monkeypatch.setattr(sensors, "_import_library", _explode)
    sensors._state.cache_clear()
    assert (ler := sensors.read_sensors())
    assert all(v is None for v in ler.values())


def test_amostra_inclui_temperatura_e_potencia(monkeypatch):
    import gclaude_indexer.resources as resources_mod

    monkeypatch.setattr(resources_mod, "read_sensors", lambda: {
        "cpu_temp_c": 61.5, "gpu_temp_c": 48.0,
        "cpu_potencia_w": 88.2, "gpu_potencia_w": 130.0, "clock_gpu_mhz": 1750,
        "gpu_hotspot_c": 62.0, "gpu_fan_rpm": 1500,
    })
    a = resources_mod.sample_resources()
    assert a.cpu_temp_c == 61.5
    assert a.gpu_temp_c == 48.0
    assert a.cpu_power_w == 88.2
    assert a.gpu_power_w == 130.0
    assert a.clock_gpu_mhz == 1750, "o clock de GPU vem dos sensores, não dos contadores"


# --- Correção pós-Tarefa 3: zeros falsos sem elevação -----------------------


def test_sensores_tratam_zeros_como_ausencia_de_leitura(monkeypatch):
    """Sem elevação a biblioteca devolve todos os sensores em 0.0 —
    indistinguível de medição. Zero grau e zero watt não é máquina parada,
    é ausência de leitura."""
    from gclaude_indexer import sensors

    class _Sensor:
        def __init__(self, tipo, nome, valor):
            self.SensorType, self.Name, self.Value = tipo, nome, valor

    class _Componente:
        HardwareType = "Cpu"
        Sensors = [_Sensor("Temperature", "Package", 0.0), _Sensor("Power", "Package", 0.0)]

        def Update(self):
            pass

    class _Computador:
        Hardware = [_Componente()]

    sensors._state.cache_clear()
    monkeypatch.setattr(sensors, "_state", lambda: (_Computador(), None))
    monkeypatch.setattr(sensors, "_last_reading", None)
    assert all(v is None for v in sensors.read_sensors().values())


def test_sensores_aceitam_leitura_real(monkeypatch):
    """Com valores diferentes de zero, a leitura passa."""
    from gclaude_indexer import sensors

    class _Sensor:
        def __init__(self, tipo, nome, valor):
            self.SensorType, self.Name, self.Value = tipo, nome, valor

    class _Componente:
        HardwareType = "Cpu"
        Sensors = [_Sensor("Temperature", "Package", 61.5), _Sensor("Power", "Package", 88.2)]

        def Update(self):
            pass

    class _Computador:
        Hardware = [_Componente()]

    sensors._state.cache_clear()
    monkeypatch.setattr(sensors, "_state", lambda: (_Computador(), None))
    monkeypatch.setattr(sensors, "_last_reading", None)
    leitura = sensors.read_sensors()
    assert leitura["cpu_temp_c"] == 61.5
    assert leitura["cpu_potencia_w"] == 88.2


def test_sensores_tratam_zero_parcial_por_chave(monkeypatch):
    """Achado testando nesta máquina de verdade (CPU AMD Ryzen + GPU AMD
    Radeon): sem elevação, os sensores de CPU (Tctl/Tdie, Power Package)
    ficam travados em 0.0 pelo driver de kernel ausente, mas os sensores da
    GPU AMD continuam funcionando por outro caminho e trazem valores reais.
    O filtro "tudo zero" sozinho não pega esse caso parcial: cada campo de
    temperatura/potência precisa ser avaliado por si."""
    from gclaude_indexer import sensors

    class _Sensor:
        def __init__(self, tipo, nome, valor):
            self.SensorType, self.Name, self.Value = tipo, nome, valor

    class _Cpu:
        HardwareType = "Cpu"
        Sensors = [_Sensor("Temperature", "Tctl/Tdie", 0.0), _Sensor("Power", "Package", 0.0)]

        def Update(self):
            pass

    class _Gpu:
        HardwareType = "GpuAmd"
        Sensors = [_Sensor("Temperature", "GPU Core", 49.0), _Sensor("Power", "GPU Package", 36.0)]

        def Update(self):
            pass

    class _Computador:
        Hardware = [_Cpu(), _Gpu()]

    sensors._state.cache_clear()
    monkeypatch.setattr(sensors, "_state", lambda: (_Computador(), None))
    monkeypatch.setattr(sensors, "_last_reading", None)
    leitura = sensors.read_sensors()
    assert leitura["cpu_temp_c"] is None, "0.0 exato de CPU sem elevação é ausência, não medição"
    assert leitura["cpu_potencia_w"] is None
    assert leitura["gpu_temp_c"] == 49.0
    assert leitura["gpu_potencia_w"] == 36.0


# --- Tarefa 4: painel -------------------------------------------------------


def test_json_de_recursos_traz_clocks_temperatura_e_potencia(cliente, tmp_path):
    projeto_id = _criar_projeto(cliente, tmp_path)
    dados = cliente.get(f"/projects/{projeto_id}/run/resources").json()
    for campo in ("clock_cpu_mhz", "clock_memory_mhz", "clock_gpu_mhz",
                  "cpu_temp_c", "gpu_temp_c", "cpu_power_w", "gpu_power_w",
                  "sensors_unavailable_reason"):
        assert campo in dados, f"faltou {campo} no JSON de recursos"


def test_painel_tem_lugar_para_temperatura_e_clocks(cliente, tmp_path):
    projeto_id = _criar_projeto(cliente, tmp_path)
    corpo = cliente.get(f"/projects/{projeto_id}/run").text
    for marcador in ('id="temp-cpu"', 'id="temp-gpu"', 'id="power-cpu"', 'id="power-gpu"',
                     'id="clock-cpu"', 'id="clock-ram"', 'id="clock-gpu"'):
        assert marcador in corpo, marcador


# --- Tarefa 5: "todos" exclusivo --------------------------------------------


def test_formulario_traz_o_script_de_exclusividade_do_todos(cliente):
    corpo = cliente.get("/projects/new").text
    assert 'data-all-category' in corpo
    assert 'name="extensions"' in corpo


# --- Tarefa 6: openrouter removido -------------------------------------------


def test_openrouter_nao_existe_mais_em_lugar_nenhum():
    from gclaude_indexer.classification import VALID_ENGINES
    from gclaude_indexer.config import CLASSIFICATION_ENGINES
    from gclaude_indexer.web.app import CLASSIFICATION_ENGINES_ORDER
    from gclaude_indexer.web.i18n import _TRANSLATIONS

    assert "openrouter" not in CLASSIFICATION_ENGINES
    assert "openrouter" not in VALID_ENGINES
    assert "openrouter" not in CLASSIFICATION_ENGINES_ORDER
    for idioma, tabela in _TRANSLATIONS.items():
        sobrando = [c for c in tabela if "openrouter" in c]
        assert not sobrando, f"{idioma} ainda tem chaves de openrouter: {sobrando}"


def test_projeto_com_openrouter_e_recusado_na_validacao(tmp_path):
    from gclaude_indexer.config import ConfigError, load_config

    with pytest.raises(ConfigError):
        load_config({
            "name": "x", "source_folder": str(tmp_path), "output_folder": str(tmp_path / "s"),
            "classification_engine": "openrouter",
        })


def test_projeto_antigo_com_openrouter_e_convertido_para_regras_com_aviso(tmp_path):
    """Um projeto gravado antes da remoção do openrouter tem
    `motor_classificacao: "openrouter"` no `config_json`. Reabri-lo não pode
    dar `ConfigError` — o projeto do usuário não pode ficar inacessível por
    causa de uma limpeza nossa. A conversão é silenciosa (vira 'rules') mas
    fica registrada como evento de aviso."""
    from gclaude_indexer.config import ProjectConfig
    from gclaude_indexer.events import list_events
    from gclaude_indexer.project import load_project, create_project

    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    config_original = ProjectConfig(
        name="Projeto antigo", source_folder=str(origem), output_folder=str(saida),
        classification_engine="rules",
    )
    conn, _ = create_project(config_original)
    conn.execute("UPDATE project SET config_json = REPLACE(config_json, '\"rules\"', '\"openrouter\"')")
    conn.commit()
    conn.close()

    config, conn = load_project(saida)
    try:
        assert config.classification_engine == "rules"
        eventos = list_events(conn)
        avisos = [e for e in eventos if e["level"] == "warning" and "openrouter" in e["message"]]
        assert avisos, "esperava um evento de aviso sobre a conversão do openrouter"
    finally:
        conn.close()


# --- Tarefa 7: rolagem do log ------------------------------------------------


def test_script_do_log_desliga_o_seguir_ao_rolar_para_cima(cliente, tmp_path):
    projeto_id = _criar_projeto(cliente, tmp_path)
    corpo = cliente.get(f"/projects/{projeto_id}/run").text
    assert 'addEventListener("scroll"' in corpo or "addEventListener('scroll'" in corpo
    # PERTO_DO_FIM -> NEAR_BOTTOM_PX (Tarefa 18, fase 14): identificador JS
    # traduzido junto com o resto do script de run.html.
    assert "NEAR_BOTTOM_PX" in corpo


# --- Tarefa 14: paralelismo -------------------------------------------------


def test_trabalhadores_respeitam_o_modo(monkeypatch):
    from gclaude_indexer import parallelism

    monkeypatch.setattr(parallelism, "_physical_cores", lambda: 8)
    assert parallelism.workers_for("economy") == 1
    assert parallelism.workers_for("automatic") == 7, "deixa um nucleo para a interface"
    assert parallelism.workers_for("maximum") == 8
    assert parallelism.workers_for("desconhecido") == 7


def test_trabalhadores_nunca_menor_que_um(monkeypatch):
    from gclaude_indexer import parallelism

    monkeypatch.setattr(parallelism, "_physical_cores", lambda: 1)
    for modo in ("economy", "automatic", "maximum"):
        assert parallelism.workers_for(modo) >= 1


def test_conversao_paralela_processa_todos_os_arquivos(cliente, tmp_path):
    """O ganho e de tempo, mas o resultado tem de ser identico ao sequencial."""
    from gclaude_indexer.catalog import find_project
    from gclaude_indexer.project import load_project

    nome = "Paralelo"
    origem = tmp_path / "origem" / nome
    (origem / "volume_1").mkdir(parents=True)
    for i in range(1, 6):
        _pdf(origem / "volume_1" / f"p{i}.pdf", f"OFICIO No {i}\nTexto suficiente.\n1{i}/01/2024")

    projeto_id = _criar_projeto(cliente, tmp_path, nome=nome, parallelism="maximum")
    cliente.post(f"/projects/{projeto_id}/run-all")
    # "run-all" dispara uma thread orquestradora que segue até
    # "classification" mesmo que só nos interesse conversão/extração — espera
    # até o fim de verdade, senão essa thread sobrevive ao teste (e ao
    # `tmp_path`, apagado logo em seguida) e pode colidir com o próximo
    # teste que reusar o mesmo id de projeto no `task_manager`.
    for etapa in ("scan", "conversion", "extraction", "windows", "classification"):
        _esperar_etapa_terminar(projeto_id, etapa, timeout=180)

    _config, conn = load_project(find_project(projeto_id).output_folder)
    try:
        convertidos = conn.execute(
            "SELECT COUNT(*) FROM file WHERE status IN ('converted','extracted')"
        ).fetchone()[0]
        falhas = conn.execute("SELECT COUNT(*) FROM file WHERE status='failed'").fetchone()[0]
    finally:
        conn.close()

    assert convertidos == 5, "paralelizar nao pode perder arquivo"


# --- Tarefa 8: o modelo escolhido é o usado --------------------------------


def test_modelo_para_usar_respeita_a_escolha(tmp_path):
    from gclaude_indexer.config import ProjectConfig
    from gclaude_indexer.engine_local import DEFAULT_LOCAL_MODEL, model_to_use

    base = dict(name="x", source_folder=str(tmp_path), output_folder=str(tmp_path / "s"))
    assert model_to_use(None, ProjectConfig(**base, local_model="qwen3:8b")) == "qwen3:8b"
    assert model_to_use(None, ProjectConfig(**base, local_model="automatic")) == DEFAULT_LOCAL_MODEL
    assert model_to_use(None, ProjectConfig(**base, local_model="")) == DEFAULT_LOCAL_MODEL


# --- Tarefa 10: duplicatas não travam a barra ------------------------------


def test_varredura_registra_duplicata_em_vez_de_sumir_com_ela(cliente, tmp_path):
    import shutil
    from gclaude_indexer.catalog import find_project
    from gclaude_indexer.project import load_project

    nome = "Com duplicata"
    origem = tmp_path / "origem" / nome.replace(" ", "_")
    (origem / "volume_1").mkdir(parents=True)
    _pdf(origem / "volume_1" / "a.pdf", "OFÍCIO No 1\nTexto suficiente para não acionar OCR.\n10/01/2024")
    shutil.copy(origem / "volume_1" / "a.pdf", origem / "volume_1" / "copia_de_a.pdf")

    projeto_id = _criar_projeto(cliente, tmp_path, nome=nome)
    cliente.post(f"/projects/{projeto_id}/run-next")
    _esperar_etapa_terminar(projeto_id, "scan")

    _config, conn = load_project(find_project(projeto_id).output_folder)
    try:
        total = conn.execute("SELECT COUNT(*) FROM file").fetchone()[0]
        duplicatas = conn.execute("SELECT COUNT(*) FROM file WHERE status = 'duplicate'").fetchone()[0]
    finally:
        conn.close()

    assert total == 2, "a duplicata precisa existir na tabela para a barra fechar em 100%"
    assert duplicatas == 1


# --- Tarefa 9: relatório de qualidade --------------------------------------


def test_resumo_de_qualidade_conta_confianca_e_lacunas(cliente, tmp_path):
    from gclaude_indexer.catalog import find_project
    from gclaude_indexer.project import load_project
    from gclaude_indexer.quality import quality_summary

    projeto_id = _criar_projeto(cliente, tmp_path)
    cliente.post(f"/projects/{projeto_id}/run-all")
    for etapa in ("scan", "conversion", "extraction", "windows", "classification"):
        _esperar_etapa_terminar(projeto_id, etapa, timeout=60)
    # `peca` só é povoada por "Importar e gerar relatórios" (import_items.py) —
    # a classificação em si grava em raw_items.jsonl. quality_summary lê
    # a tabela `peca`, então o teste precisa desse passo antes de checar.
    cliente.post(f"/projects/{projeto_id}/import-and-generate")

    config, conn = load_project(find_project(projeto_id).output_folder)
    try:
        resumo = quality_summary(conn, config)
    finally:
        conn.close()

    assert resumo["total_items"] >= 1
    assert set(resumo["confidence"]) == {"high", "medium", "low"}
    assert sum(resumo["confidence"].values()) == resumo["total_items"]
    assert resumo["engine"] == "rules"
    assert 0 <= resumo["score"] <= 100


def test_resumo_de_qualidade_em_projeto_vazio_nao_quebra(cliente, tmp_path):
    from gclaude_indexer.catalog import find_project
    from gclaude_indexer.project import load_project
    from gclaude_indexer.quality import quality_summary

    projeto_id = _criar_projeto(cliente, tmp_path)
    config, conn = load_project(find_project(projeto_id).output_folder)
    try:
        resumo = quality_summary(conn, config)
    finally:
        conn.close()

    assert resumo["total_items"] == 0
    assert resumo["score"] == 0, "sem peças não há qualidade a pontuar"


def test_resumo_de_qualidade_recusa_coluna_fora_da_allowlist(tmp_path, monkeypatch):
    """Tarefa 16: nome de coluna não pode ser parâmetro `?`, então
    `_count_nulls` interpola o nome direto na query — a allowlist
    (`_NULLABLE_COLUMNS`) é o que impede uma coluna não prevista de chegar
    lá. Esvaziando a allowlist, as próprias colunas que `quality_summary`
    sempre usou ("type"/"date"/"summary") passam a estar "fora da lista" e
    devem levantar `ValueError` — provando que a validação está de fato no
    caminho, sem expor a função aninhada."""
    from gclaude_indexer import quality as quality_mod
    from gclaude_indexer.config import ProjectConfig
    from gclaude_indexer.db import connect, init_schema

    conn = connect(tmp_path / "p.db")
    init_schema(conn)
    conn.execute(
        "INSERT INTO item (group_key, start_ref, end_ref, start_order, end_order, "
        "engine, confidence, type, date, summary, files) "
        "VALUES ('grupo1', 'f. 1', 'f. 1', 0, 0, 'rules', 'high', 'OFICIO', '2024-01-10', 'x', '')"
    )
    conn.commit()

    monkeypatch.setattr(quality_mod, "_NULLABLE_COLUMNS", frozenset())
    config = ProjectConfig(name="p", source_folder=str(tmp_path), output_folder=str(tmp_path / "saida"))

    with pytest.raises(ValueError):
        quality_mod.quality_summary(conn, config)

    with pytest.raises(ValueError):
        quality_mod._engine_quality(conn, "rules")

    conn.close()


def test_tela_de_resultado_mostra_o_relatorio_de_qualidade(cliente, tmp_path):
    projeto_id = _criar_projeto(cliente, tmp_path)
    cliente.post(f"/projects/{projeto_id}/run-all")
    for etapa in ("scan", "conversion", "extraction", "windows", "classification"):
        _esperar_etapa_terminar(projeto_id, etapa, timeout=60)

    cliente.post(f"/projects/{projeto_id}/import-and-generate")

    corpo = cliente.get(f"/projects/{projeto_id}/result").text
    assert 'class="quality-box"' in corpo
    assert "rules" in corpo


# --- Tarefa 15: benchmark ---------------------------------------------------


def test_execucao_registra_tempo_por_etapa(cliente, tmp_path):
    from gclaude_indexer.catalog import find_project
    from gclaude_indexer.project import load_project

    projeto_id = _criar_projeto(cliente, tmp_path)
    cliente.post(f"/projects/{projeto_id}/run-next")
    _esperar_etapa_terminar(projeto_id, "scan")

    _config, conn = load_project(find_project(projeto_id).output_folder)
    try:
        linhas = conn.execute(
            "SELECT step, started_at, finished_at, items FROM run"
        ).fetchall()
    finally:
        conn.close()

    assert linhas, "nenhuma execucao registrada — sem isso nao ha benchmark"
    etapa, inicio, fim, itens = linhas[0]
    assert etapa == "scan"
    assert fim is not None and fim >= inicio
    assert itens >= 1


def test_execucao_registra_motor_efetivo_nao_automatico(cliente, tmp_path):
    """Defeito: `execucao_bg.py` gravava `motor = config.classification_engine`
    em `run.engine` — o motor *configurado*, não o que de fato rodou. Com o
    padrão `classification_engine="automatic"`, `run.engine` ficava
    "automatic" enquanto `item.engine` recebia o motor que a classificação
    escolheu de verdade (`rules` ou `local`), e `compare_runs` (que agrupa
    por `run.engine` e filtra `item.engine`) nunca casava um grupo com o
    outro — o benchmark, pedido explícito do usuário, nunca funcionava com
    o motor no padrão. `run.engine` tem de gravar o motor *efetivo*,
    resolvido por `orchestrator.resolve_effective_engine` — nunca o
    sentinela "automatic"."""
    from gclaude_indexer.catalog import find_project
    from gclaude_indexer.project import load_project

    projeto_id = _criar_projeto(cliente, tmp_path, classification_engine="automatic")
    cliente.post(f"/projects/{projeto_id}/run-all")
    for etapa in ("scan", "conversion", "extraction", "windows", "classification"):
        _esperar_etapa_terminar(projeto_id, etapa, timeout=120)

    _config, conn = load_project(find_project(projeto_id).output_folder)
    try:
        motor = conn.execute(
            "SELECT engine FROM run WHERE step = 'classification' ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
    finally:
        conn.close()

    assert motor != "automatic", "run.engine gravou o motor configurado, nao o efetivo"
    assert motor in ("rules", "local"), f"motor efetivo esperado ('rules' ou 'local'), veio {motor!r}"


def test_comparacao_agrupa_por_motor_e_modelo(cliente, tmp_path):
    from gclaude_indexer.catalog import find_project
    from gclaude_indexer.project import load_project
    from gclaude_indexer.quality import compare_runs

    projeto_id = _criar_projeto(cliente, tmp_path)
    cliente.post(f"/projects/{projeto_id}/run-all")
    for etapa in ("scan", "conversion", "extraction", "windows", "classification"):
        _esperar_etapa_terminar(projeto_id, etapa, timeout=120)

    _config, conn = load_project(find_project(projeto_id).output_folder)
    try:
        linhas = compare_runs(conn)
    finally:
        conn.close()

    assert linhas
    for linha in linhas:
        for campo in ("engine", "model", "total_seconds", "items_per_minute", "score"):
            assert campo in linha, f"faltou {campo} na comparacao"


def test_banco_antigo_sem_tabela_execucao_ganha_a_tabela_ao_carregar(tmp_path):
    """`load_project` precisa rodar `init_schema` também ao
    reabrir um projeto já existente, não só ao criar um novo — senão um
    projeto criado antes desta tarefa ficaria sem `execucao` para sempre,
    mesmo depois de atualizar o sistema."""
    import json
    import sqlite3
    from datetime import datetime

    from gclaude_indexer.project import load_project

    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "projeto_antigo"
    saida.mkdir()

    conn = sqlite3.connect(str(saida / "project.db"))
    conn.execute(
        """
        CREATE TABLE project (
            id INTEGER PRIMARY KEY, name TEXT, subject TEXT, source_folder TEXT,
            output_folder TEXT, config_json TEXT, created_at TEXT
        )
        """
    )
    config_json = json.dumps({"name": "Antigo", "source_folder": str(origem), "output_folder": str(saida)})
    conn.execute(
        "INSERT INTO project (name, subject, source_folder, output_folder, config_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("Antigo", None, str(origem), str(saida), config_json, datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()

    _config, conn = load_project(saida)
    try:
        tabelas = {
            linha[0] for linha in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    finally:
        conn.close()

    assert "run" in tabelas, "banco antigo precisa ganhar a tabela nova ao reabrir"


# --- Tarefa 13: instalacao em maquina nova ---------------------------------


def test_diagnostico_lista_todas_as_dependencias():
    from gclaude_indexer.install_diagnostics import check_installation

    itens = {i["key"]: i for i in check_installation()}
    for chave in ("python", "tesseract", "ghostscript", "ollama", "default_model", "gpu_runtime"):
        assert chave in itens, f"faltou diagnosticar {chave}"
    for item in itens.values():
        assert isinstance(item["present"], bool)
        assert "required" in item
        if not item["present"] and item["required"]:
            assert item["install_command"], f"{item['key']} ausente sem comando de instalacao"


def test_diagnostico_nunca_levanta(monkeypatch):
    import gclaude_indexer.install_diagnostics as dm

    monkeypatch.setattr(dm, "find_tool", lambda _n: (_ for _ in ()).throw(OSError("boom")))
    itens = dm.check_installation()
    assert isinstance(itens, list) and itens, "o diagnostico tem de degradar, nao explodir"


def test_tela_sobre_mostra_o_diagnostico(cliente):
    corpo = cliente.get("/about").text
    assert 'class="install-diagnostics"' in corpo
    assert "tesseract" in corpo.lower()


# --- Tarefa 18: diagnostico de GPU/sensores traduzido no "Sobre" -----------


def test_diagnostico_gpu_rdna1_e_sensores_traduz_por_idioma(monkeypatch):
    """Defect 4 (Task 18, redirected from the brief's `hardware.py` — the
    real leak was here: `_diagnose_gpu_runtime`/`_diagnose_hardware_sensors`
    built fixed Portuguese sentences, and the raw code from
    `sensors.unavailable_reason()` (e.g. `sem_privilegio`) leaked straight
    into the "Version" column, in any language)."""
    import gclaude_indexer.install_diagnostics as dm
    from gclaude_indexer.hardware import GpuInfo
    from gclaude_indexer.i18n import translate

    monkeypatch.setattr(dm, "_detect_nvidia_gpu", lambda: None)
    monkeypatch.setattr(dm, "_detect_wmi_gpu", lambda: GpuInfo("AMD Radeon RX 5700 XT", "AMD", 8192))
    monkeypatch.setattr(dm, "dll_path", lambda: type("FakePath", (), {"is_file": lambda self: True})())
    monkeypatch.setattr(dm, "unavailable_reason", lambda: "sem_privilegio")

    for idioma in ("pt", "en", "es"):
        itens = {i["key"]: i for i in dm.check_installation(idioma)}

        # Fase 15, Tarefa 2: esta linha esperava `rdna1_configured`, que
        # dizia que a RX 5700 XT precisava de HSA_OVERRIDE_GFX_VERSION.
        # Medido: o Ollama 0.33.2 a serve por Vulkan e a variável é inerte,
        # entao o `install.ps1` passou a remove-la e a chave saiu do i18n.
        # O que este teste existe para provar continua igual: a coluna
        # "Versao" vem traduzida, nunca em portugues fixo nem com codigo cru.
        gpu_version = itens["gpu_runtime"]["version"]
        esperado_gpu = translate(
            idioma, "diagnostics.gpu_runtime.driver_sufficient", name="AMD Radeon RX 5700 XT"
        )
        assert gpu_version == esperado_gpu, (idioma, gpu_version)
        assert "HSA_OVERRIDE_GFX_VERSION" not in (gpu_version or "")
        assert not itens["gpu_runtime"]["install_command"], (
            f"{idioma}: o 'Sobre' nao pode mandar gravar o que o instalador remove"
        )

        sensor_version = itens["hardware_sensors"]["version"]
        assert sensor_version is not None
        assert "sem_privilegio" not in sensor_version, f"{idioma}: raw code leaked: {sensor_version!r}"
        assert sensor_version == translate(idioma, "resources.sensors.no_privilege"), (idioma, sensor_version)


def test_tela_sobre_em_espanhol_nao_vaza_codigo_cru_do_sensor(cliente, monkeypatch):
    """Same defect as above, exercised through the real route — the exact
    reproduction the coordinator confirmed live on this machine (AMD Radeon
    RX 5700 XT, RDNA1, sensors unavailable without administrator)."""
    from gclaude_indexer.hardware import GpuInfo
    import gclaude_indexer.install_diagnostics as dm

    monkeypatch.setattr(dm, "_detect_nvidia_gpu", lambda: None)
    monkeypatch.setattr(dm, "_detect_wmi_gpu", lambda: GpuInfo("AMD Radeon RX 5700 XT", "AMD", 8192))
    monkeypatch.setattr(dm, "dll_path", lambda: type("FakePath", (), {"is_file": lambda self: True})())
    monkeypatch.setattr(dm, "unavailable_reason", lambda: "sem_privilegio")

    cliente.cookies.set("language", "es")
    corpo = cliente.get("/about").text
    assert "sem_privilegio" not in corpo
    assert "administrador" in corpo.lower()


# --- Tarefa 11: infraestrutura de layouts ----------------------------------


def test_layout_valido_aceita_os_quatro_e_recusa_desconhecido():
    from gclaude_indexer.web.layout import AVAILABLE_LAYOUTS, DEFAULT_LAYOUT, valid_layout

    assert AVAILABLE_LAYOUTS == ("standard", "technical", "editorial", "compact")
    for nome in AVAILABLE_LAYOUTS:
        assert valid_layout(nome) == nome
    assert valid_layout("inexistente") == DEFAULT_LAYOUT
    assert valid_layout(None) == DEFAULT_LAYOUT


def test_cabecalho_traz_seletor_de_layout(cliente):
    corpo = cliente.get("/projects").text
    assert 'name="layout"' in corpo
    for nome in ("standard", "technical", "editorial", "compact"):
        assert f'<option value="{nome}"' in corpo


def test_escolher_layout_aplica_no_html(cliente):
    resposta = cliente.post("/preferences/layout", data={"layout": "editorial"}, follow_redirects=False)
    assert resposta.status_code in (302, 303)
    assert 'data-layout="editorial"' in cliente.get("/projects").text


def test_layout_e_tema_sao_independentes(cliente):
    cliente.post("/preferences/layout", data={"layout": "technical"}, follow_redirects=False)
    cliente.post("/preferences/theme", data={"theme": "sepia"}, follow_redirects=False)
    corpo = cliente.get("/projects").text
    assert 'data-layout="technical"' in corpo
    assert 'data-theme="sepia"' in corpo


# --- Tarefa 12: identidades visuais ----------------------------------------


def test_cada_layout_define_regras_proprias():
    from pathlib import Path
    import gclaude_indexer.web.app as app_mod

    css = (Path(app_mod.WEB_ROOT) / "static" / "layouts.css").read_text(encoding="utf-8")
    for nome in ("technical", "editorial", "compact"):
        bloco = css.split(f'html[data-layout="{nome}"]', 1)
        assert len(bloco) > 1, f"layout {nome} sem regra"
    # cada um precisa de identidade própria, não só um seletor vazio
    assert css.count("font-family") >= 3, "os layouts precisam variar tipografia, não só espaçamento"


def test_layouts_nao_redefinem_cores():
    """Cor é responsabilidade do tema. Um layout que defina --color-* quebra a
    previsibilidade das 16 combinações layout × paleta."""
    import re
    from pathlib import Path
    import gclaude_indexer.web.app as app_mod

    css = (Path(app_mod.WEB_ROOT) / "static" / "layouts.css").read_text(encoding="utf-8")
    definicoes = re.findall(r"(--color-[a-z0-9-]+)\s*:", css)
    assert not definicoes, f"layouts.css não pode definir cores: {definicoes}"


def test_nenhum_layout_usa_fonte_generica_ou_remota():
    from pathlib import Path
    import gclaude_indexer.web.app as app_mod

    css = (Path(app_mod.WEB_ROOT) / "static" / "layouts.css").read_text(encoding="utf-8")
    baixo = css.lower()
    for proibida in ("inter", "roboto", "arial", "fonts.googleapis", "fonts.gstatic", "@import url("):
        assert proibida not in baixo, f"proibido no sistema offline: {proibida}"


# --- Correcoes finais da Fase 13 (revisao de entrega) -----------------------


def test_amostra_de_recursos_e_rapida_o_bastante_para_o_poll(monkeypatch):
    """A tela pede uma amostra a cada 500ms. Sem cache, cada uma custava ~6s de
    PowerShell e as requisicoes se acumulavam ate travar a barra e o log."""
    from gclaude_indexer import windows_counters

    chamadas = []

    def _lento(*a, **k):
        chamadas.append(1)

        class _R:
            returncode = 0
            stdout = "10\n"

        return _R()

    monkeypatch.setattr(windows_counters, "run_hidden", _lento)
    monkeypatch.setattr(windows_counters, "_cache", {})
    windows_counters.gpu_usage_percent()
    n1 = len(chamadas)
    windows_counters.gpu_usage_percent()
    assert len(chamadas) == n1, "segunda leitura dentro da janela de cache nao pode chamar PowerShell de novo"


def test_cache_de_contadores_expira_apos_a_janela(monkeypatch):
    """O cache e curto (~1s) para nao travar a leitura por muito tempo depois
    que a maquina de verdade mudou de estado - so evita chamadas repetidas
    dentro do intervalo de poll (500ms)."""
    import time

    from gclaude_indexer import windows_counters

    chamadas = []

    def _lento(*a, **k):
        chamadas.append(1)

        class _R:
            returncode = 0
            stdout = "10\n"

        return _R()

    monkeypatch.setattr(windows_counters, "run_hidden", _lento)
    monkeypatch.setattr(windows_counters, "_cache", {})
    monkeypatch.setattr(windows_counters, "_CACHE_TTL_S", 0.05)
    windows_counters.gpu_usage_percent()
    time.sleep(0.1)
    windows_counters.gpu_usage_percent()
    assert len(chamadas) == 2, "cache nao pode durar para sempre"


def test_cache_de_contadores_e_por_metrica(monkeypatch):
    """O cache de uma metrica (uso de GPU) nao pode fazer outra (clock de
    CPU) devolver um valor requentado antes mesmo de ser consultada."""
    from gclaude_indexer import windows_counters

    monkeypatch.setattr(windows_counters, "_cache", {})

    def _fake_consultar(comando):
        if comando is windows_counters._PS_GPU_USAGE:
            return "50"
        if comando is windows_counters._PS_CPU_CLOCK:
            return "3000"
        return None

    monkeypatch.setattr(windows_counters, "_query", _fake_consultar)
    assert windows_counters.gpu_usage_percent() == 50.0
    assert windows_counters.clock_cpu_mhz() == 3000


def test_comparacao_nao_atribui_pontuacao_de_um_modelo_a_outro(tmp_path):
    """peca.motor guarda 'local', nunca o modelo - sem essa protecao, um modelo
    que nao classificou nada herda a pontuacao do que classificou."""
    from gclaude_indexer.db import connect, init_schema
    from gclaude_indexer.quality import compare_runs

    conn = connect(tmp_path / "p.db")
    init_schema(conn)
    conn.execute(
        "INSERT INTO run (step,engine,model,parallelism,started_at,finished_at,items,ok) "
        "VALUES ('classification','local','gemma4:e4b','automatic','2026-01-01T10:00:00','2026-01-01T10:00:20',4,1)"
    )
    conn.execute(
        "INSERT INTO run (step,engine,model,parallelism,started_at,finished_at,items,ok) "
        "VALUES ('classification','local','qwen3:8b','automatic','2026-01-01T10:01:00','2026-01-01T10:01:20',0,1)"
    )
    # pecas da ultima importacao registrada em `peca` (colunas NOT NULL do
    # schema real preenchidas com valores triviais, ja que o teste so olha
    # motor/confianca/tipo/data/resumo).
    for i in range(4):
        conn.execute(
            "INSERT INTO item (group_key, start_ref, end_ref, start_order, end_order, "
            "engine, confidence, type, date, summary, files) "
            "VALUES (?, 'f. 1', 'f. 1', ?, ?, 'local', 'high', 'OFICIO', '2024-01-10', 'x', '')",
            (f"grupo{i}", i, i),
        )
    conn.commit()

    linhas = {(l["engine"], l["model"]): l for l in compare_runs(conn)}
    conn.close()

    assert len(linhas) == 2
    # exatamente um grupo pode ter pontuacao - o da ultima importacao
    com_pontuacao = [k for k, v in linhas.items() if v["score"] is not None]
    assert len(com_pontuacao) <= 1, f"mais de um grupo pontuado: {com_pontuacao}"
    # e o outro grupo nao pode herdar a mesma distribuicao de confianca
    sem_pontuacao = [k for k, v in linhas.items() if v["score"] is None]
    for chave in sem_pontuacao:
        assert linhas[chave]["confidence"] is None


def test_comparacao_sem_nenhuma_execucao_nao_pontua_nada(tmp_path):
    """Sem historico de execucao de classificacao nao ha como saber a quem as
    pecas pertencem - nenhum grupo pode ser pontuado."""
    from gclaude_indexer.db import connect, init_schema
    from gclaude_indexer.quality import compare_runs

    conn = connect(tmp_path / "p.db")
    init_schema(conn)
    conn.execute(
        "INSERT INTO run (step,engine,model,parallelism,started_at,finished_at,items,ok) "
        "VALUES ('classification','rules',NULL,'automatic','2026-01-01T10:00:00',NULL,4,0)"
    )
    conn.commit()

    linhas = compare_runs(conn)
    conn.close()

    assert all(l["score"] is None for l in linhas)


def test_extracao_paralela_aplica_resultados_conforme_completam(tmp_path, monkeypatch):
    """I1: antes da correcao, a extracao paralela computava TUDO antes de
    gravar qualquer coisa - a barra ficava em 0% durante a etapa inteira.
    Com a correcao, o resultado de cada arquivo e aplicado (gravado e
    commitado) assim que fica pronto, sem esperar os demais. Este teste
    trava (ou expira por timeout) sob o comportamento antigo: nada libera
    `liberar_apos_commit` ate um segundo processo, consultando o banco por
    uma conexao propria (igual a tela de progresso faz de verdade), observar
    b.txt como 'extracted' antes de a.txt sequer terminar de computar."""
    import threading
    import time as time_mod
    from concurrent.futures import ThreadPoolExecutor

    from gclaude_indexer import extraction as extracao_mod
    from gclaude_indexer.config import ProjectConfig
    from gclaude_indexer.db import connect, init_schema

    monkeypatch.setattr(extracao_mod, "ProcessPoolExecutor", ThreadPoolExecutor)

    liberar_apos_commit = threading.Event()

    def _fake_extrair(config, linha):
        if linha["relative_path"] == "a.txt":
            liberado = liberar_apos_commit.wait(timeout=5)
            assert liberado, "a.txt ficou preso esperando b.txt ser aplicado"
        return [("texto", 0, False)]

    monkeypatch.setattr(extracao_mod, "_extract_file_pages", _fake_extrair)

    caminho_db = tmp_path / "p.db"
    conn = connect(caminho_db)
    init_schema(conn)
    for nome in ("a.txt", "b.txt"):
        conn.execute(
            "INSERT INTO file (relative_path, name, extension, size, sha256, group_key, status) "
            "VALUES (?, ?, 'txt', 1, 'x', NULL, 'converted')",
            (nome, nome),
        )
    conn.commit()

    # `sqlite3.Connection` só pode ser usada na mesma thread em que foi
    # criada (mesmo sendo uma conexão dedicada a esta thread) — por isso
    # abre a conexão de observação dentro da própria thread, e não antes.
    def _observar():
        conn_observador = connect(caminho_db)
        try:
            for _ in range(500):
                linha = conn_observador.execute(
                    "SELECT status FROM file WHERE relative_path = 'b.txt'"
                ).fetchone()
                if linha["status"] == "extracted":
                    liberar_apos_commit.set()
                    return
                time_mod.sleep(0.01)
        finally:
            conn_observador.close()

    threading.Thread(target=_observar, daemon=True).start()

    config = ProjectConfig(name="p", source_folder=str(tmp_path), output_folder=str(tmp_path / "saida"))
    monkeypatch.setattr(extracao_mod, "workers_for", lambda modo: 2)

    resultado = extracao_mod.extract_pages(conn, config)

    status = {
        l["relative_path"]: l["status"]
        for l in conn.execute("SELECT relative_path, status FROM file").fetchall()
    }
    conn.close()

    assert resultado.files_processed == 2
    assert status == {"a.txt": "extracted", "b.txt": "extracted"}


def test_extracao_paralela_preserva_numeracao_de_folhas_fora_de_ordem(tmp_path, monkeypatch):
    """A aplicacao incremental (I1) nao pode embaralhar a numeracao de folhas
    quando o segundo arquivo de um agrupador termina de computar antes do
    primeiro."""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from gclaude_indexer import extraction as extracao_mod
    from gclaude_indexer.config import ProjectConfig
    from gclaude_indexer.db import connect, init_schema

    monkeypatch.setattr(extracao_mod, "ProcessPoolExecutor", ThreadPoolExecutor)

    liberar_a = threading.Event()

    def _fake_extrair(config, linha):
        if linha["relative_path"] == "grupo/a.txt":
            liberar_a.wait(timeout=5)
            return [("pagina a1", 0, False)]
        return [("pagina b1", 0, False), ("pagina b2", 0, False)]

    monkeypatch.setattr(extracao_mod, "_extract_file_pages", _fake_extrair)

    conn = connect(tmp_path / "p.db")
    init_schema(conn)
    for nome in ("grupo/a.txt", "grupo/b.txt"):
        conn.execute(
            "INSERT INTO file (relative_path, name, extension, size, sha256, group_key, status) "
            "VALUES (?, ?, 'txt', 1, 'x', 'grupo', 'converted')",
            (nome, nome.rsplit("/", 1)[-1]),
        )
    conn.commit()

    threading.Timer(0.1, liberar_a.set).start()

    config = ProjectConfig(name="p", source_folder=str(tmp_path), output_folder=str(tmp_path / "saida"))
    monkeypatch.setattr(extracao_mod, "workers_for", lambda modo: 2)

    extracao_mod.extract_pages(conn, config)

    referencias = {
        (arq["relative_path"], pag["number"]): pag["reference"]
        for arq in conn.execute("SELECT id, relative_path FROM file").fetchall()
        for pag in conn.execute("SELECT number, reference FROM page WHERE file_id = ?", (arq["id"],)).fetchall()
    }
    conn.close()

    assert referencias[("grupo/a.txt", 1)] == "f. 1"
    assert referencias[("grupo/b.txt", 1)] == "f. 2"
    assert referencias[("grupo/b.txt", 2)] == "f. 3"


def test_extracao_trunca_texto_dentro_do_worker(tmp_path):
    """I2: o truncamento por `caracteres_por_pagina` acontecia so na
    gravacao - o worker devolvia o texto completo da pagina, inflando RAM e
    o custo de pickle no caminho paralelo. Deve truncar antes de devolver."""
    import fitz

    from gclaude_indexer.config import ProjectConfig
    from gclaude_indexer.extraction import _extract_file_pages

    caminho_pdf = tmp_path / "grande.pdf"
    documento = fitz.open()
    pagina = documento.new_page()
    texto_longo = "A" * 5000
    pagina.insert_text((10, 72), texto_longo)
    documento.save(caminho_pdf)
    documento.close()

    config = ProjectConfig(
        name="p", source_folder=str(tmp_path), output_folder=str(tmp_path / "saida"), chars_per_page=50
    )
    linha = {"extension": "pdf", "relative_path": "grande.pdf", "needs_ocr": False}

    paginas = _extract_file_pages(config, linha)

    assert len(paginas[0][0]) <= 50, "o worker deve truncar antes de devolver, nao so na gravacao"


def test_worker_morto_nao_condena_arquivos_nao_iniciados_na_extracao(tmp_path, monkeypatch):
    """I3: quando o pool quebra (`BrokenProcessPool`), TODOS os futuros
    pendentes recebem a mesma excecao - inclusive arquivos que nunca
    chegaram a rodar. Eles nao podem ser marcados 'failed' (o que os
    excluiria de toda reexecucao futura); devem manter o status original
    para serem retomados."""
    from concurrent.futures import Future
    from concurrent.futures.process import BrokenProcessPool

    from gclaude_indexer import extraction as extracao_mod
    from gclaude_indexer.config import ProjectConfig
    from gclaude_indexer.db import connect, init_schema

    class _ExecutorQuebrado:
        # `initializer` (fase 16, item 1): o pool real recebe
        # `no_window.install`, para que cada worker esconda as janelas
        # de console que o `pytesseract` abriria ao chamar o Tesseract.
        def __init__(self, max_workers=None, initializer=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def submit(self, fn, *args, **kwargs):
            futuro = Future()
            futuro.set_exception(BrokenProcessPool("pool morreu (falta de memoria)"))
            return futuro

    monkeypatch.setattr(extracao_mod, "ProcessPoolExecutor", _ExecutorQuebrado)
    monkeypatch.setattr(extracao_mod, "workers_for", lambda modo: 4)

    conn = connect(tmp_path / "p.db")
    init_schema(conn)
    for nome in ("a.txt", "b.txt", "c.txt"):
        conn.execute(
            "INSERT INTO file (relative_path, name, extension, size, sha256, group_key, status) "
            "VALUES (?, ?, 'txt', 1, 'x', NULL, 'converted')",
            (nome, nome),
        )
    conn.commit()

    config = ProjectConfig(name="p", source_folder=str(tmp_path), output_folder=str(tmp_path / "saida"))
    resultado = extracao_mod.extract_pages(conn, config)

    status = {
        l["relative_path"]: l["status"]
        for l in conn.execute("SELECT relative_path, status FROM file").fetchall()
    }
    eventos = conn.execute("SELECT message FROM event WHERE step = 'extraction' AND level = 'error'").fetchall()
    conn.close()

    assert resultado.failed == 0, "arquivo nao iniciado nao pode ser marcado como falha"
    assert status == {"a.txt": "converted", "b.txt": "converted", "c.txt": "converted"}
    assert any("pool" in e["message"].lower() for e in eventos)


def test_worker_morto_nao_condena_arquivos_nao_iniciados_na_conversao(tmp_path, monkeypatch):
    """Mesma correcao (I3) do lado da conversao (`conversao.py`)."""
    from concurrent.futures import Future
    from concurrent.futures.process import BrokenProcessPool

    from gclaude_indexer import conversion as conversao_mod
    from gclaude_indexer.config import ProjectConfig
    from gclaude_indexer.db import connect, init_schema

    class _ExecutorQuebrado:
        # `initializer` (fase 16, item 1): o pool real recebe
        # `no_window.install`, para que cada worker esconda as janelas
        # de console que o `pytesseract` abriria ao chamar o Tesseract.
        def __init__(self, max_workers=None, initializer=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def submit(self, fn, *args, **kwargs):
            futuro = Future()
            futuro.set_exception(BrokenProcessPool("pool morreu (falta de memoria)"))
            return futuro

    monkeypatch.setattr(conversao_mod, "ProcessPoolExecutor", _ExecutorQuebrado)
    monkeypatch.setattr(conversao_mod, "workers_for", lambda modo: 4)
    monkeypatch.setattr(conversao_mod, "_physical_cores", lambda: 4)

    conn = connect(tmp_path / "p.db")
    init_schema(conn)
    for nome in ("a.txt", "b.txt", "c.txt"):
        conn.execute(
            "INSERT INTO file (relative_path, name, extension, size, sha256, group_key, status) "
            "VALUES (?, ?, 'txt', 1, 'x', NULL, 'discovered')",
            (nome, nome),
        )
    conn.commit()

    config = ProjectConfig(name="p", source_folder=str(tmp_path), output_folder=str(tmp_path / "saida"))
    resultado = conversao_mod.convert(conn, config)

    status = {
        l["relative_path"]: l["status"]
        for l in conn.execute("SELECT relative_path, status FROM file").fetchall()
    }
    eventos = conn.execute("SELECT message FROM event WHERE step = 'conversion' AND level = 'error'").fetchall()
    conn.close()

    assert resultado.failed == 0, "arquivo nao iniciado nao pode ser marcado como falha"
    assert status == {"a.txt": "discovered", "b.txt": "discovered", "c.txt": "discovered"}
    assert any("pool" in e["message"].lower() for e in eventos)


def test_jobs_ocrmypdf_dividido_pelos_trabalhadores_do_pool(tmp_path, monkeypatch):
    """Minor (a) + correcao definitiva: em modo 'maximum' com N processos no
    pool, cada um chamando `ocrmypdf --jobs N` multiplicava para N^2
    tesseracts simultaneos em N nucleos. Deve dividir os nucleos fisicos
    pelos trabalhadores do pool, com piso 2 (dividir para 1 e conservador
    demais e devolve boa parte do paralelismo perdido)."""
    from gclaude_indexer import conversion as conversao_mod
    from gclaude_indexer.config import ProjectConfig
    from gclaude_indexer.db import connect, init_schema

    capturado = {}

    def _fake_convert_in_parallel(
        conn, config, linhas, trabalhadores, jobs_ocrmypdf, should_stop, resultado, language=None
    ):
        capturado["trabalhadores"] = trabalhadores
        capturado["jobs_ocrmypdf"] = jobs_ocrmypdf

    monkeypatch.setattr(conversao_mod, "_convert_in_parallel", _fake_convert_in_parallel)
    monkeypatch.setattr(conversao_mod, "workers_for", lambda modo: 8)
    monkeypatch.setattr(conversao_mod, "_physical_cores", lambda: 8)

    conn = connect(tmp_path / "p.db")
    init_schema(conn)
    for i in range(5):
        conn.execute(
            "INSERT INTO file (relative_path, name, extension, size, sha256, group_key, status) "
            "VALUES (?, ?, 'pdf', 1, 'x', NULL, 'discovered')",
            (f"a{i}.pdf", f"a{i}.pdf"),
        )
    conn.commit()

    config = ProjectConfig(
        name="p", source_folder=str(tmp_path), output_folder=str(tmp_path / "saida"), parallelism="maximum"
    )
    conversao_mod.convert(conn, config)
    conn.close()

    assert capturado["trabalhadores"] == 8
    assert capturado["jobs_ocrmypdf"] == 2, "8 nucleos / 8 trabalhadores = 1, mas o piso e 2"


def test_ler_sensores_thread_safe_sob_concorrencia(monkeypatch):
    """Minor (b): `Computer.Update()` do LibreHardwareMonitor nao e
    thread-safe, e `_state()` e `lru_cache` (objeto unico compartilhado).
    Duas threads que caem juntas na janela de cache expirado nao podem
    chamar `_read_sensors_uncached()` (que faz o `Update()`) ao mesmo
    tempo - o `threading.Lock` deve serializar essa secao."""
    import threading
    import time as time_mod

    from gclaude_indexer import sensors as sensors_mod

    chamadas_simultaneas = []
    contador = {"ativas": 0}
    trava_contador = threading.Lock()

    def _lenta_sem_cache():
        with trava_contador:
            contador["ativas"] += 1
            chamadas_simultaneas.append(contador["ativas"])
        time_mod.sleep(0.05)
        with trava_contador:
            contador["ativas"] -= 1
        return dict(sensors_mod._EMPTY)

    monkeypatch.setattr(sensors_mod, "_read_sensors_uncached", _lenta_sem_cache)
    monkeypatch.setattr(sensors_mod, "_last_reading", None)
    monkeypatch.setattr(sensors_mod, "_last_reading_time", 0.0)

    threads = [threading.Thread(target=sensors_mod.read_sensors) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert max(chamadas_simultaneas) == 1, "duas threads entraram ao mesmo tempo em _read_sensors_uncached()"


# --- Correcao definitiva do defeito C1 (amostrador em background) ----------


@pytest.fixture(autouse=True)
def isolar_amostrador_continuo():
    """`resources._sampler` (correcao definitiva do C1) e um singleton de
    modulo com uma thread de fundo. Sem isolamento, a thread iniciada por um
    teste continuaria rodando (e chamando funcoes possivelmente mockadas por
    aquele teste) durante os testes seguintes, com risco real de interferir
    em contadores de chamada de outros testes (ex.: `_lento`/`chamadas` em
    `test_amostra_de_recursos_e_rapida_o_bastante_para_o_poll`)."""
    yield
    import gclaude_indexer.resources as resources_mod

    resources_mod._sampler.stop()
    resources_mod._sampler = resources_mod.ContinuousSampler()


def test_endpoint_de_recursos_responde_sem_esperar_a_coleta(cliente, tmp_path):
    """A coleta custa ~6s; a tela pede a cada 500ms. O endpoint tem de
    devolver o último valor conhecido, não coletar na hora — senão ocupa as
    conexões do navegador e trava a barra de progresso e o log."""
    import time

    projeto_id = _criar_projeto(cliente, tmp_path)
    cliente.get(f"/projects/{projeto_id}/run/resources")  # dispara o amostrador

    inicio = time.monotonic()
    for _ in range(3):
        resposta = cliente.get(f"/projects/{projeto_id}/run/resources")
        assert resposta.status_code == 200
    decorrido = time.monotonic() - inicio

    assert decorrido < 1.5, f"3 leituras levaram {decorrido:.1f}s — o endpoint está coletando em vez de ler cache"


def test_primeira_leitura_sem_coleta_ainda_traz_cpu_e_ram(monkeypatch):
    """Antes da primeira coleta completa terminar, `latest_sample()` nao
    pode bloquear nem devolver lixo - deve trazer CPU/RAM (rapidos, via
    psutil) de verdade e os campos lentos como None."""
    import gclaude_indexer.resources as resources_mod

    amostrador = resources_mod.ContinuousSampler(interval_s=999)
    monkeypatch.setattr(resources_mod, "_sampler", amostrador)

    amostra = resources_mod.latest_sample()
    assert amostra.cpu_percent is not None
    assert amostra.ram_total_mb > 0
    assert amostra.gpu_percent is None
    assert amostra.clock_cpu_mhz is None

    amostrador.stop()


def test_amostrador_continuo_mantem_amostra_anterior_se_coleta_falhar(monkeypatch):
    """A thread de fundo nao pode derrubar o servidor nem zerar a ultima
    amostra conhecida quando uma coleta falha."""
    import gclaude_indexer.resources as resources_mod

    chamadas = {"n": 0}

    def _amostrar_instavel():
        chamadas["n"] += 1
        if chamadas["n"] == 1:
            return resources_mod.ResourceSample(
                cpu_percent=1.0, cpu_name="x", ram_percent=2.0, ram_used_mb=1, ram_total_mb=2,
                gpu_percent=None, gpu_vram_used_mb=None, gpu_vram_total_mb=None, gpu_name=None,
            )
        raise RuntimeError("coleta falhou")

    monkeypatch.setattr(resources_mod, "sample_resources", _amostrar_instavel)

    amostrador = resources_mod.ContinuousSampler(interval_s=0.05)
    amostrador._ensure_thread()
    for _ in range(100):
        if chamadas["n"] >= 2:
            break
        time.sleep(0.02)
    assert chamadas["n"] >= 2, "a thread nao chegou a tentar uma segunda coleta"

    amostra = amostrador.latest_sample()
    assert amostra.cpu_percent == 1.0, "uma coleta que falhou zerou a ultima amostra boa"

    amostrador.stop()


def test_amostrador_hiberna_sem_leituras(monkeypatch):
    """Abrir a tela uma vez não pode deixar um powershell.exe coletando para
    sempre — a thread para sozinha quando ninguém está olhando.

    `sample_resources()` de verdade chama Performance Counters via
    PowerShell e custa ~6,4s por amostra nesta máquina (bem mais que os
    `INTERVAL_S`/`SECONDS_UNTIL_HIBERNATE` reduzidos usados aqui para o teste
    ser rápido) — por isso é trocado por um dublê instantâneo, como já faz
    `test_amostrador_continuo_mantem_amostra_anterior_se_coleta_falhar`
    acima. O que este teste prova é só o ciclo liga/hiberna/religa.
    """
    import time
    from gclaude_indexer import resources as resources_mod

    monkeypatch.setattr(resources_mod, "sample_resources", lambda: resources_mod._partial_sample())
    monkeypatch.setattr(resources_mod, "SECONDS_UNTIL_HIBERNATE", 0.3)
    monkeypatch.setattr(resources_mod.ContinuousSampler, "INTERVAL_S", 0.1, raising=False)

    resources_mod.latest_sample()
    assert resources_mod._sampler_active(), "a thread devia estar rodando após a leitura"

    time.sleep(1.0)
    assert not resources_mod._sampler_active(), "a thread devia ter hibernado sem leituras"

    resources_mod.latest_sample()
    assert resources_mod._sampler_active(), "uma nova leitura devia religar a thread"


# --- Correção de uso real (pós Fase 13): Defeito 1 — VRAM saturada no log --


def _resultado_wmi_fake(vram_adapter_ram_mb=4095):
    import json as json_mod

    class _Resultado:
        returncode = 0
        stdout = json_mod.dumps(
            {
                "Name": "AMD Radeon RX 5700 XT",
                "AdapterRAM": vram_adapter_ram_mb * 1024 * 1024,
                "AdapterCompatibility": "Advanced Micro Devices, Inc.",
            }
        )

    return _Resultado()


def test_detectar_gpu_wmi_usa_vram_do_registro_em_vez_do_adapter_ram_saturado(monkeypatch):
    """Defeito 1: o log de diagnóstico dizia 'AMD Radeon RX 5700 XT (4095 MB
    VRAM)' numa placa de 8 GB, porque `_detect_wmi_gpu` só olhava
    `Win32_VideoController.AdapterRAM` (32 bits, satura em 4095 MB). Agora
    ele prioriza `windows_counters.vram_total_mb()` (lê o registro, QWORD
    de 64 bits) e só cai para `AdapterRAM` se aquele devolver `None`."""
    monkeypatch.setattr(hardware_mod, "run_hidden", lambda *a, **k: _resultado_wmi_fake())
    monkeypatch.setattr(hardware_mod.windows_counters, "vram_total_mb", lambda: 8176)

    gpu = hardware_mod._detect_wmi_gpu()

    assert gpu is not None
    assert gpu.vram_mb == 8176, "usou o AdapterRAM saturado (4095) em vez da VRAM real do registro"


def test_detectar_gpu_wmi_cai_para_adapter_ram_quando_registro_indisponivel(monkeypatch):
    """Sem `windows_counters.vram_total_mb()` (contador indisponível nesta
    máquina), continua funcionando com o valor antigo — mesmo que saturado —
    em vez de derrubar a detecção de GPU inteira."""
    monkeypatch.setattr(hardware_mod, "run_hidden", lambda *a, **k: _resultado_wmi_fake())
    monkeypatch.setattr(hardware_mod.windows_counters, "vram_total_mb", lambda: None)

    gpu = hardware_mod._detect_wmi_gpu()

    assert gpu is not None
    assert gpu.vram_mb == 4095


def test_diagnosticar_registra_vram_real_no_evento_nao_o_adapter_ram(tmp_path, monkeypatch):
    """Ponta a ponta: o texto do evento de diagnóstico (o que vira log) tem
    que trazer a VRAM real (8176 MB), não o valor saturado do AdapterRAM
    (4095 MB) que o usuário viu no log da execução real."""
    from gclaude_indexer.db import connect, init_schema
    from gclaude_indexer.events import list_events

    monkeypatch.setattr(hardware_mod, "_detect_nvidia_gpu", lambda: None)
    monkeypatch.setattr(hardware_mod, "run_hidden", lambda *a, **k: _resultado_wmi_fake())
    monkeypatch.setattr(hardware_mod.windows_counters, "vram_total_mb", lambda: 8176)

    conn = connect(tmp_path / "project.db")
    init_schema(conn)
    diagnostico = hardware_mod.diagnose(conn, space_folder=tmp_path)

    assert diagnostico.gpu.vram_mb == 8176

    eventos = list_events(conn, step="diagnostics")
    texto = " ".join(e["message"] for e in eventos)
    assert "8176" in texto
    assert "4095" not in texto
    conn.close()


# --- Correção de uso real: Defeito 2 — log afirma um modelo que não é o usado


def test_escolher_modelo_reporta_o_modelo_realmente_usado_nao_o_padrao(tmp_path, monkeypatch):
    """Defeito 2: com `qwen3.5:9b` escolhido pelo usuário, o log dizia
    "Modelo 'gemma4:e4b' escolhido" — `choose_model` sempre citava
    `DEFAULT_LOCAL_MODEL`, e não recebia o modelo que ia rodar de fato."""
    from gclaude_indexer.db import connect, init_schema
    from gclaude_indexer.events import list_events
    from gclaude_indexer.hardware import GB_MB, HardwareDiagnostic, GpuInfo

    monkeypatch.setattr(hardware_mod, "_real_model_size_mb", lambda modelo, timeout_s=2.0: None)

    conn = connect(tmp_path / "project.db")
    init_schema(conn)
    diagnostico = HardwareDiagnostic(
        gpu=GpuInfo("RTX 4090", "NVIDIA", 24 * GB_MB), ram_mb=32 * GB_MB,
        free_space_mb=999_999, checked_folder=str(tmp_path),
        tesseract_present=False, tesseract_path=None,
        ghostscript_present=False, ghostscript_path=None,
        ollama_present=False, ollama_path=None,
    )

    escolha = hardware_mod.choose_model(conn, diagnostico, "qwen3.5:9b")

    assert escolha.model == "qwen3.5:9b"
    eventos = list_events(conn, step="diagnostics")
    assert any("qwen3.5:9b" in e["message"] for e in eventos), "o evento não nomeia o modelo real"
    assert not any(f"'{DEFAULT_LOCAL_MODEL}' escolhido" in e["message"] for e in eventos), "o evento ainda afirma que o modelo padrão foi o escolhido"
    conn.close()


def test_resolver_motor_efetivo_repassa_o_modelo_do_config_para_escolher_modelo(tmp_path, monkeypatch):
    """Ponta a ponta: `orchestrator.resolve_effective_engine` precisa repassar
    `model_to_use(conn, config)` — o modelo que o usuário escolheu no
    formulário — para `choose_model`, e não deixá-lo cair no padrão."""
    from gclaude_indexer import orchestrator as orchestrator_mod
    from gclaude_indexer.config import ProjectConfig
    from gclaude_indexer.db import connect, init_schema
    from gclaude_indexer.events import list_events
    from gclaude_indexer.hardware import GB_MB, HardwareDiagnostic, GpuInfo

    diagnostico_fake = HardwareDiagnostic(
        gpu=GpuInfo("RTX 4090", "NVIDIA", 24 * GB_MB), ram_mb=32 * GB_MB,
        free_space_mb=999_999, checked_folder=str(tmp_path),
        tesseract_present=False, tesseract_path=None,
        ghostscript_present=False, ghostscript_path=None,
        ollama_present=False, ollama_path=None,
    )
    monkeypatch.setattr(orchestrator_mod, "diagnose", lambda conn, language=None: diagnostico_fake)
    monkeypatch.setattr(hardware_mod, "_real_model_size_mb", lambda modelo, timeout_s=2.0: None)

    conn = connect(tmp_path / "project.db")
    init_schema(conn)
    config = ProjectConfig(
        name="Projeto", source_folder=str(tmp_path / "origem"), output_folder=str(tmp_path / "saida"),
        classification_engine="automatic", local_model="qwen3.5:9b",
    )

    motor = orchestrator_mod.resolve_effective_engine(conn, config)

    assert motor == "local"
    eventos = list_events(conn, step="diagnostics")
    assert any("qwen3.5:9b" in e["message"] for e in eventos)
    assert not any(f"'{DEFAULT_LOCAL_MODEL}' escolhido" in e["message"] for e in eventos)
    conn.close()


def test_escolher_modelo_usa_tamanho_real_do_ollama_quando_disponivel(tmp_path, monkeypatch):
    """`ESTIMATED_MODEL_SIZE_MB` (3232 MB desde a 1.0.1) é calibrado para o
    modelo padrão; para outro modelo, `choose_model` tenta primeiro o tamanho
    real via `/api/tags` do Ollama (`_real_model_size_mb`) antes de recorrer à
    estimativa — a conta de memória/disco fica errada com um modelo de
    tamanho bem diferente (qwen3.5:9b tem ~6,3 GB, não ~3,2 GB)."""
    from gclaude_indexer.db import connect, init_schema
    from gclaude_indexer.events import list_events
    from gclaude_indexer.hardware import GB_MB, ESTIMATED_MODEL_SIZE_MB, HardwareDiagnostic, GpuInfo

    monkeypatch.setattr(hardware_mod, "_real_model_size_mb", lambda modelo, timeout_s=2.0: 6289)

    conn = connect(tmp_path / "project.db")
    init_schema(conn)
    diagnostico = HardwareDiagnostic(
        gpu=GpuInfo("RTX 4090", "NVIDIA", 24 * GB_MB), ram_mb=32 * GB_MB,
        free_space_mb=999_999, checked_folder=str(tmp_path),
        tesseract_present=False, tesseract_path=None,
        ghostscript_present=False, ghostscript_path=None,
        ollama_present=False, ollama_path=None,
    )

    escolha = hardware_mod.choose_model(conn, diagnostico, "qwen3.5:9b")

    assert escolha.use_rules_engine is False
    eventos = list_events(conn, step="diagnostics")
    texto = " ".join(e["message"] for e in eventos)
    assert "6289" in texto, "não usou o tamanho real devolvido pelo Ollama"
    assert str(ESTIMATED_MODEL_SIZE_MB) not in texto, "citou a estimativa mesmo tendo o tamanho real"
    conn.close()


def test_escolher_modelo_cai_para_estimativa_e_avisa_quando_ollama_nao_informa_tamanho(tmp_path, monkeypatch):
    """Quando o Ollama não responde ou o modelo ainda não foi baixado,
    `choose_model` cai para `ESTIMATED_MODEL_SIZE_MB`, mas o motivo
    registrado deixa explícito que é uma estimativa (calibrada para outro
    modelo) — não finge que é o tamanho real."""
    from gclaude_indexer.db import connect, init_schema
    from gclaude_indexer.events import list_events
    from gclaude_indexer.hardware import GB_MB, ESTIMATED_MODEL_SIZE_MB, HardwareDiagnostic, GpuInfo

    monkeypatch.setattr(hardware_mod, "_real_model_size_mb", lambda modelo, timeout_s=2.0: None)

    conn = connect(tmp_path / "project.db")
    init_schema(conn)
    diagnostico = HardwareDiagnostic(
        gpu=GpuInfo("RTX 4090", "NVIDIA", 24 * GB_MB), ram_mb=32 * GB_MB,
        free_space_mb=999_999, checked_folder=str(tmp_path),
        tesseract_present=False, tesseract_path=None,
        ghostscript_present=False, ghostscript_path=None,
        ollama_present=False, ollama_path=None,
    )

    escolha = hardware_mod.choose_model(conn, diagnostico, "modelo-desconhecido:1b")

    assert escolha.use_rules_engine is False
    eventos = list_events(conn, step="diagnostics")
    texto = " ".join(e["message"] for e in eventos)
    assert str(ESTIMATED_MODEL_SIZE_MB) in texto
    assert "estimad" in texto.lower(), "não deixou claro que o tamanho usado é uma estimativa"
    conn.close()


# --- Correção de uso real: Defeito 3 — modelos != gemma4 geram 0 peças ------
#
# Diagnóstico (rodando o prompt real contra gemma4:e4b e qwen3.5:9b, ambos
# instalados nesta máquina): a hipótese original — o modelo devolve a
# referência num formato ligeiramente diferente ('f.1', 'fl. 1' etc.) — NÃO
# se confirmou. Com o mesmo prompt, qwen3.5:9b devolveu as referências no
# formato exato esperado ('f. 1', 'f. 2', ...). A causa real é outra: sem
# `"think": false` no pedido ao Ollama, qwen3.5:9b (modelo com capacidade de
# "pensamento") despeja a resposta inteira no campo `thinking` e devolve
# `response` vazio; `_generate` só lia `response`, então `_extract_items_json`
# recebia string vazia e toda janela virava 0 peças — nada a ver com
# comparação de referência. gemma4:e4b não entra nesse modo por padrão, por
# isso funcionava. A correção real foi em `_generate` (envia `think: false` e,
# como rede de segurança, cai para `thinking` se `response` vier vazio) —
# ver `engine_local.py`. A normalização de referência abaixo continua válida
# como proteção adicional (o formato pode variar entre modelos por outros
# motivos) e satisfaz os testes obrigatórios pedidos, mas não foi a causa
# do 0-peças observado no acervo real.


def test_normalize_reference_aceita_variacoes_mas_nao_funde_prefixos_diferentes():
    from gclaude_indexer.engine_local import _normalize_reference

    equivalentes = ["f. 1", "f.1", "F. 1", "  f.   1  ", "fl. 1", "fl.1", "FL.1", "fl1"]
    chaves = {_normalize_reference(referencia) for referencia in equivalentes}
    assert len(chaves) == 1, f"variações que deveriam ser equivalentes normalizaram diferente: {chaves}"

    assert _normalize_reference("p. 1") != _normalize_reference("f. 1"), (
        "referências com prefixos diferentes ('p.' folha vs 'f.') não podem ser fundidas"
    )
    assert _normalize_reference("f. 1") != _normalize_reference("f. 12"), (
        "números diferentes não podem virar a mesma referência"
    )


def test_dict_to_item_aceita_referencia_com_variacao_de_caixa_e_abreviacao(tmp_path):
    """Peça aceita mesmo quando o modelo devolve a referência com
    maiúscula/espaçamento diferente ou a abreviação alternativa 'fl.' —
    e o resultado usa a referência canônica da janela, não a variação bruta."""
    from gclaude_indexer.classification import WindowPage
    from gclaude_indexer.engine_local import _dict_to_item

    paginas = [
        WindowPage("f. 1", "doc.pdf", "texto 1", has_table=False, image_count=0),
        WindowPage("f. 2", "doc.pdf", "texto 2", has_table=False, image_count=0),
    ]
    bruto = {"ref_start": "F.1", "ref_end": "fl. 2", "confidence": "high"}

    peca = _dict_to_item(bruto, paginas)

    assert peca is not None, "referência só diferente em caixa/espaço/abreviação não pode ser recusada"
    assert peca.start_ref == "f. 1"
    assert peca.end_ref == "f. 2"


def test_dict_to_item_nao_funde_referencias_de_prefixos_diferentes(tmp_path):
    """'p. 1' não pode ser aceito como equivalente a 'f. 1' — são referências
    diferentes por definição, mesmo depois da normalização tolerante."""
    from gclaude_indexer.classification import WindowPage
    from gclaude_indexer.engine_local import _dict_to_item

    paginas = [WindowPage("f. 1", "doc.pdf", "texto", False, 0)]
    bruto = {"ref_start": "p. 1", "ref_end": "p. 1", "confidence": "high"}

    assert _dict_to_item(bruto, paginas) is None


def test_classificar_pendentes_registra_aviso_quando_peca_e_recusada_por_referencia(tmp_path, monkeypatch):
    """Defeito 3, ponto 2: descarte silencioso é inaceitável. Antes desta
    correção, uma peça recusada por referência não reconhecida sumia sem
    nenhum evento — foi exatamente o que aconteceu na execução real com
    qwen3.5:9b (7 janelas, 0 peças, nada no log). Agora vira evento de
    aviso, com a referência recebida e as esperadas."""
    from gclaude_indexer.config import load_config
    from gclaude_indexer.conversion import convert
    from gclaude_indexer.db import connect, init_schema
    from gclaude_indexer.events import list_events
    from gclaude_indexer.extraction import extract_pages
    from gclaude_indexer.windows_prep import prepare_windows
    from gclaude_indexer.engine_local import LocalEngine, classify_pending
    from gclaude_indexer.scanning import scan

    origem = tmp_path / "origem"
    (origem / "volume_1").mkdir(parents=True)
    saida = tmp_path / "origem_indexado"

    documento = fitz.open()
    pagina = documento.new_page()
    pagina.insert_textbox(
        (50, 50, 550, 750),
        "Texto de teste longo o bastante para nao acionar OCR nem nada esquisito por aqui, so texto normal mesmo.",
        fontsize=12,
    )
    documento.save(str(origem / "volume_1" / "doc.pdf"))
    documento.close()

    config = load_config({"name": "Defeito 3", "source_folder": str(origem), "output_folder": str(saida)})
    conn = connect(saida / "project.db")
    init_schema(conn)
    scan(conn, config)
    convert(conn, config)
    extract_pages(conn, config)
    prepare_windows(conn, config)

    # `per_page=False`: este teste exercita o modo de FAIXAS, que é onde a
    # recusa por referência acontece — o modo por página identifica a
    # página por número e não tem essa classe de erro.
    motor = LocalEngine(model="fake-model", per_page=False)
    monkeypatch.setattr(motor, "is_available", lambda: True)
    monkeypatch.setattr(
        motor, "_generate",
        lambda prompt: '{"items": [{"ref_start": "f. 99", "ref_end": "f. 99", "confidence": "high"}]}',
    )

    resultado = classify_pending(conn, config, local_engine=motor)

    # A peça inválida continua sendo recusada, e o aviso continua sendo
    # emitido (é o que este teste protege). O que mudou na fase 16: a
    # página não fica mais de fora do índice por causa disso — entra como
    # peça de cobertura, com confiança baixa e sem tipo. O requisito é que
    # nada do acervo desapareça, nem quando o modelo erra.
    assert resultado.items_generated == 1, "a página tem de entrar no índice, ainda que como cobertura"
    assert resultado.low_confidence + resultado.medium_confidence == 1
    assert resultado.high_confidence == 0, "a peça recusada não pode virar uma classificação confiante"
    assert resultado.windows_via_rules_fallback == 0, "ollama respondeu; não é uma queda de conexão"

    avisos = [e for e in list_events(conn, step="classification") if e["level"] == "warning"]
    texto_avisos = " ".join(a["message"] for a in avisos)
    assert avisos, "peça recusada por referência não pode sumir sem nenhum evento"
    assert "f. 99" in texto_avisos
    assert "refer" in texto_avisos.lower()
    conn.close()


def test_motor_local_usa_thinking_quando_response_vem_vazio():
    """Causa real do Defeito 3 (achada rodando o prompt real do sistema
    contra gemma4:e4b e qwen3.5:9b via Ollama nesta máquina): modelos com
    canal de 'pensamento' despejam a resposta inteira em `thinking` e
    devolvem `response` vazio quando `think` não é desligado explicitamente
    no pedido. `_generate` manda `think: false`; este teste cobre a rede de
    segurança para quando, ainda assim, o texto só vier em `thinking`."""
    import http.server
    import json as json_mod
    import threading

    from gclaude_indexer.classification import WindowPage
    from gclaude_indexer.engine_local import LocalEngine

    corpo_resposta = json_mod.dumps(
        {
            "response": "",
            "thinking": json_mod.dumps(
                {"items": [{"ref_start": "f. 1", "ref_end": "f. 1", "confidence": "high"}]}
            ),
        }
    ).encode("utf-8")

    class _HandlerThinking(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self._responder(json_mod.dumps({"version": "0.0.0-fake"}).encode("utf-8"))

        def do_POST(self):
            tamanho = int(self.headers.get("Content-Length", 0))
            self.rfile.read(tamanho)
            self._responder(corpo_resposta)

        def _responder(self, corpo: bytes):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)

        def log_message(self, *args):
            pass

    servidor = http.server.HTTPServer(("127.0.0.1", 0), _HandlerThinking)
    thread = threading.Thread(target=servidor.serve_forever, daemon=True)
    thread.start()
    try:
        porta = servidor.server_address[1]
        motor = LocalEngine(model="fake-model", url_base=f"http://127.0.0.1:{porta}")
        paginas = [WindowPage("f. 1", "doc.pdf", "texto", False, 0)]

        pecas = motor.classify(paginas)

        assert len(pecas) == 1, "não aproveitou o conteúdo que veio em 'thinking' com 'response' vazio"
        assert pecas[0].start_ref == "f. 1"
    finally:
        servidor.shutdown()
        thread.join(timeout=2)
