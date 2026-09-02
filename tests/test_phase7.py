"""Phase 7 tests: hardware diagnostics and automatic model choice."""

from __future__ import annotations

import pytest

from gclaude_indexer import hardware
from gclaude_indexer.config import load_config
from gclaude_indexer.db import connect, init_schema
from gclaude_indexer.events import list_events
from gclaude_indexer.hardware import (
    GB_MB,
    HardwareDiagnostic,
    GpuInfo,
    diagnose,
    choose_model,
)


def _conn(tmp_path):
    caminho = tmp_path / "project.db"
    conn = connect(caminho)
    init_schema(conn)
    return conn


def _diagnostico(gpu=None, ram_mb=0, espaco_mb=999_999):
    return HardwareDiagnostic(
        gpu=gpu,
        ram_mb=ram_mb,
        free_space_mb=espaco_mb,
        checked_folder="C:/qualquer",
        tesseract_present=False,
        tesseract_path=None,
        ghostscript_present=False,
        ghostscript_path=None,
        ollama_present=False,
        ollama_path=None,
    )


# --- diagnóstico ---------------------------------------------------------


def test_diagnose_nao_falha_e_registra_evento(tmp_path):
    conn = _conn(tmp_path)
    diagnostico = diagnose(conn, space_folder=tmp_path)

    assert isinstance(diagnostico, HardwareDiagnostic)
    assert diagnostico.ram_mb >= 0
    assert diagnostico.free_space_mb >= 0

    eventos = list_events(conn, step="diagnostics")
    assert any("hardware:" in e["message"] for e in eventos)

    conn.close()


# --- escolha de modelo: só gemma4:e4b, por VRAM+RAM combinadas -----------


def test_escolhe_gemma4_com_gpu_forte(tmp_path):
    conn = _conn(tmp_path)
    diagnostico = _diagnostico(gpu=GpuInfo("RTX 4090", "NVIDIA", 24 * GB_MB), ram_mb=32 * GB_MB)
    escolha = choose_model(conn, diagnostico)
    assert escolha.model == "gemma4:e4b"
    assert escolha.use_rules_engine is False
    conn.close()


def test_escolhe_gemma4_com_gpu_fraca_transbordando_para_ram(tmp_path):
    """O pedido é usar o máximo de GPU possível e transbordar o resto para
    a RAM — uma GPU fraca não deve mais bloquear o modelo sozinha, desde
    que a soma VRAM+RAM baste (ao contrário da antiga tabela por tiers)."""
    conn = _conn(tmp_path)
    diagnostico = _diagnostico(gpu=GpuInfo("GPU antiga", "NVIDIA", 2 * GB_MB), ram_mb=32 * GB_MB)
    escolha = choose_model(conn, diagnostico)
    assert escolha.model == "gemma4:e4b"
    assert escolha.use_rules_engine is False
    conn.close()


def test_escolhe_gemma4_sem_gpu_so_com_ram(tmp_path):
    conn = _conn(tmp_path)
    diagnostico = _diagnostico(gpu=None, ram_mb=16 * GB_MB)
    escolha = choose_model(conn, diagnostico)
    assert escolha.model == "gemma4:e4b"
    conn.close()


def test_forca_regras_memoria_combinada_insuficiente(tmp_path):
    conn = _conn(tmp_path)
    diagnostico = _diagnostico(gpu=GpuInfo("GPU fraca", "NVIDIA", 1 * GB_MB), ram_mb=2 * GB_MB)
    escolha = choose_model(conn, diagnostico)
    assert escolha.model is None
    assert escolha.use_rules_engine is True
    assert "regras" in escolha.reason

    eventos = list_events(conn, step="diagnostics")
    assert any(e["level"] == "warning" for e in eventos)
    conn.close()


def test_forca_regras_por_falta_de_espaco_em_disco(tmp_path):
    conn = _conn(tmp_path)
    diagnostico = _diagnostico(gpu=GpuInfo("RTX 4090", "NVIDIA", 24 * GB_MB), ram_mb=32 * GB_MB, espaco_mb=100)
    escolha = choose_model(conn, diagnostico)
    assert escolha.model is None
    assert escolha.use_rules_engine is True
    assert "espaço" in escolha.reason.lower()
    conn.close()
