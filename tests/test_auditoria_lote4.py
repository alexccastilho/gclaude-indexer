"""2.1.6: pequenas correções da auditoria (lote 4)."""
from __future__ import annotations

from dataclasses import replace

from gclaude_indexer import conversion, parallelism
from gclaude_indexer.config import ProjectConfig


def _config(mode: str) -> ProjectConfig:
    return replace(ProjectConfig(name="XPTO", source_folder="", output_folder=""), parallelism=mode)


def test_ocr_dos_legados_respeita_o_modo_economia(monkeypatch):
    monkeypatch.setattr(parallelism, "_physical_cores", lambda: 8)
    monkeypatch.setattr(conversion, "_physical_cores", lambda: 8)

    assert conversion._legacy_ocr_jobs(_config("economy")) == 1
    assert conversion._legacy_ocr_jobs(_config("automatic")) == 4
    assert conversion._legacy_ocr_jobs(_config("maximum")) == 4
