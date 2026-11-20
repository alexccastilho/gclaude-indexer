"""Etapa B: o quadro de qualidade (`quality.quality_summary`) mostra o
modelo que de fato roda (`local_models.model_to_use`), não só a tradução do
perfil. Antes, `automatic` aparecia como "automatic", e o perfil de
qualidade aparecia como o modelo 9B mesmo numa máquina que só tem o 4B
baixado (onde a execução usa o 4B)."""

from __future__ import annotations

import pytest

from gclaude_indexer import local_models, ollama_models
from gclaude_indexer.config import load_config
from gclaude_indexer.db import connect, init_schema
from gclaude_indexer.local_models import QUALITY_LOCAL_MODEL
from gclaude_indexer.ollama_models import DEFAULT_LOCAL_MODEL
from gclaude_indexer.quality import quality_summary


@pytest.fixture
def so_o_4b_baixado(monkeypatch):
    monkeypatch.setattr(ollama_models, "model_downloaded_on_disk", lambda nome: nome == DEFAULT_LOCAL_MODEL)
    monkeypatch.setattr(local_models, "gpu_vram_mb", lambda: 12288)


def _resumo(tmp_path, modelo):
    config = load_config({
        "name": "x", "subject": "y", "source_folder": str(tmp_path), "output_folder": str(tmp_path / "saida"),
        "classification_engine": "local", "local_model": modelo,
    })
    conn = connect(tmp_path / "project.db")
    init_schema(conn)
    try:
        return quality_summary(conn, config, pending={})
    finally:
        conn.close()


@pytest.mark.parametrize("modelo", ["quality", "automatic"])
def test_quadro_mostra_o_modelo_que_roda(tmp_path, so_o_4b_baixado, modelo):
    assert QUALITY_LOCAL_MODEL != DEFAULT_LOCAL_MODEL
    assert _resumo(tmp_path, modelo)["model"] == DEFAULT_LOCAL_MODEL


def test_nome_de_modelo_escolhido_aparece_como_esta(tmp_path, so_o_4b_baixado):
    assert _resumo(tmp_path, "gemma4:e4b")["model"] == "gemma4:e4b"
