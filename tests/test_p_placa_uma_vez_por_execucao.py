"""Etapa P: uma execução das etapas lê a placa de vídeo uma vez.

Cada etapa decidia o motor de novo (`diagnose`) e a classificação conferia
a placa de novo (`_has_dedicated_gpu`), cada vez com `nvidia-smi` ou dois
PowerShell. Dentro de uma execução a placa achada é lida uma vez; fora
dela, e na execução seguinte, é lida de novo (uma troca de placa aparece).
Uma leitura que não achou nada (falha passageira do PowerShell) não fica
guardada."""

from __future__ import annotations

from gclaude_indexer import hardware


def _contando(monkeypatch):
    leituras = []

    def nvidia():
        leituras.append("nvidia")
        return None

    def wmi():
        leituras.append("wmi")
        return hardware.GpuInfo(name="Placa", vendor="Advanced Micro Devices, Inc.", vram_mb=8192)

    monkeypatch.setattr(hardware, "_detect_nvidia_gpu", nvidia)
    monkeypatch.setattr(hardware, "_detect_wmi_gpu", wmi)
    return leituras


def test_dentro_de_uma_execucao_a_placa_e_lida_uma_vez(monkeypatch):
    leituras = _contando(monkeypatch)
    with hardware.readings_per_execution({}):
        for _ in range(4):
            assert hardware.detect_gpu().vram_mb == 8192
    # O `nvidia-smi` não achou nada e é perguntado de novo; a placa do WMI fica.
    assert leituras == ["nvidia", "wmi", "nvidia", "nvidia", "nvidia"]


def test_leitura_que_falhou_nao_fica_guardada(monkeypatch):
    respostas = [None, hardware.GpuInfo(name="Placa", vendor="Advanced Micro Devices, Inc.", vram_mb=8192)]
    leituras = []

    def wmi():
        leituras.append("wmi")
        return respostas.pop(0) if respostas else respostas_fim

    respostas_fim = hardware.GpuInfo(name="Outra", vendor="x", vram_mb=1)
    monkeypatch.setattr(hardware, "_detect_nvidia_gpu", lambda: None)
    monkeypatch.setattr(hardware, "_detect_wmi_gpu", wmi)
    with hardware.readings_per_execution({}):
        assert hardware.detect_wmi_gpu() is None
        assert hardware.detect_wmi_gpu().vram_mb == 8192
        assert hardware.detect_wmi_gpu().vram_mb == 8192
    assert leituras == ["wmi", "wmi"]


def test_fora_de_execucao_cada_chamada_le(monkeypatch):
    leituras = _contando(monkeypatch)
    hardware.detect_gpu()
    hardware.detect_gpu()
    assert leituras == ["nvidia", "wmi", "nvidia", "wmi"]


def test_a_execucao_seguinte_le_de_novo(monkeypatch):
    leituras = _contando(monkeypatch)
    with hardware.readings_per_execution({}):
        hardware.detect_gpu()
    with hardware.readings_per_execution({}):
        hardware.detect_gpu()
    assert leituras == ["nvidia", "wmi", "nvidia", "wmi"]


def test_etapas_da_mesma_cadeia_compartilham_a_leitura(monkeypatch):
    """As etapas de "Executar tudo" rodam cada uma na sua thread, com o
    mesmo `run_state`: o dicionário da execução é o que elas compartilham."""
    import threading

    leituras = _contando(monkeypatch)
    da_execucao: dict = {}

    def etapa():
        with hardware.readings_per_execution(da_execucao):
            hardware.detect_gpu()

    for _ in range(3):
        thread = threading.Thread(target=etapa)
        thread.start()
        thread.join()
    assert leituras.count("wmi") == 1
