"""2.1.6: com mais de uma placa de vídeo, toda a leitura vem da mesma placa.

A VRAM já vinha da placa de maior memória, mas a temperatura, a potência e a
ventoinha vinham da primeira placa listada, e o clock da última. Num notebook
com a integrada AMD listada antes da dedicada, o vigia de temperatura olhava
a integrada enquanto o modelo esquentava a dedicada."""

from __future__ import annotations

from gclaude_indexer import sensors
from tests.test_phase32 import _Computer, _Hardware, _Sensor, _como_admin


def _integrada():
    return _Hardware("GpuAmd", "AMD Radeon(TM) Graphics", [
        _Sensor("SmallData", "GPU Memory Used", 300.0, "/gpu-amd/0/smalldata/0"),
        _Sensor("SmallData", "GPU Memory Total", 512.0, "/gpu-amd/0/smalldata/1"),
        _Sensor("Temperature", "GPU Core", 45.0, "/gpu-amd/0/temperature/0"),
        _Sensor("Power", "GPU Package", 9.0, "/gpu-amd/0/power/0"),
        _Sensor("Fan", "GPU Fan", 1100.0, "/gpu-amd/0/fan/0"),
        _Sensor("Clock", "GPU Core", 600.0, "/gpu-amd/0/clock/0"),
    ], ident="/gpu-amd/0")


def _dedicada():
    return _Hardware("GpuNvidia", "Placa dedicada", [
        _Sensor("SmallData", "GPU Memory Used", 6000.0, "/gpu-nvidia/0/smalldata/0"),
        _Sensor("SmallData", "GPU Memory Total", 8192.0, "/gpu-nvidia/0/smalldata/1"),
        _Sensor("Temperature", "GPU Core", 78.0, "/gpu-nvidia/0/temperature/0"),
        _Sensor("Temperature", "GPU Hot Spot", 88.0, "/gpu-nvidia/0/temperature/1"),
        _Sensor("Power", "GPU Package", 95.0, "/gpu-nvidia/0/power/0"),
        _Sensor("Fan", "GPU Fan", 2400.0, "/gpu-nvidia/0/fan/0"),
        _Sensor("Clock", "GPU Core", 1800.0, "/gpu-nvidia/0/clock/0"),
    ], ident="/gpu-nvidia/0")


def test_temperatura_potencia_ventoinha_e_clock_vem_da_placa_da_vram(monkeypatch):
    for ordem in ((_integrada(), _dedicada()), (_dedicada(), _integrada())):
        _como_admin(monkeypatch, _Computer(*ordem))
        leitura = sensors._read_library_sensors()
        assert (leitura["gpu_vram_usada_mb"], leitura["gpu_vram_total_mb"]) == (6000, 8192)
        assert leitura["gpu_temp_c"] == 78.0
        assert leitura["gpu_hotspot_c"] == 88.0
        assert leitura["gpu_potencia_w"] == 95.0
        assert leitura["gpu_fan_rpm"] == 2400
        assert leitura["clock_gpu_mhz"] == 1800


def test_placa_unica_sem_memoria_continua_dando_temperatura(monkeypatch):
    placa = _Hardware("GpuAmd", "Placa", [
        _Sensor("Temperature", "GPU Core", 61.0, "/gpu-amd/0/temperature/0"),
    ], ident="/gpu-amd/0")
    _como_admin(monkeypatch, _Computer(placa))
    assert sensors._read_library_sensors()["gpu_temp_c"] == 61.0
