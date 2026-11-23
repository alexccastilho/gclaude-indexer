"""Brecha de duplicação no reenfileiramento (`requeue_fallback_windows`).

Uma queda entre o commit e a poda deixa as janelas `pending` com as linhas
de queda (`"fallback": true`) ainda no `raw_items.jsonl` (ec9ebd1): quem
termina o serviço é a próxima devolução. Mas a devolução só roda com o
modelo no ar ou com placa de vídeo. Sem placa e com o modelo fora, a
corrida seguinte classificava essas janelas de novo pelo motor de regras e
o arquivo ficava com as linhas delas em dobro."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from gclaude_indexer.paths import RAW_ITEMS_FILE_NAME


class _MotorFora:
    url_base = "fake"
    gpu_plan = None
    last_window_warnings: list = []
    last_rejections: list = []

    def is_available(self):
        return False

    def classify(self, paginas):  # pragma: no cover - nunca chamado: está fora
        raise AssertionError("o modelo está fora do ar")


def _linhas_por_janela(config) -> Counter:
    caminho = Path(config.output_folder) / RAW_ITEMS_FILE_NAME
    return Counter(
        json.loads(linha)["window"]
        for linha in caminho.read_text(encoding="utf-8").split("\n")
        if linha.strip()
    )


def _classificar_sem_modelo_nem_placa(conn, config, monkeypatch):
    from gclaude_indexer import engine_local

    monkeypatch.setattr(engine_local, "_has_dedicated_gpu", lambda: False)
    monkeypatch.setattr(engine_local, "MODEL_RETRY_SECONDS", 0.0)
    monkeypatch.setattr(engine_local, "_try_restart_ollama", lambda *a, **k: False)
    return engine_local.classify_pending(conn, config, local_engine=_MotorFora())


def test_janelas_devolvidas_antes_da_queda_nao_ficam_com_linhas_em_dobro(tmp_path, monkeypatch):
    from .test_phase8 import TEXTO_LONGO_SEM_MARCADOR, _projeto_pronto_para_classificar

    config, conn = _projeto_pronto_para_classificar(
        tmp_path, [f"{TEXTO_LONGO_SEM_MARCADOR} Página {n}." for n in range(1, 24 + 1)], pages_per_window=8, overlap=0
    )
    primeira = _classificar_sem_modelo_nem_placa(conn, config, monkeypatch)
    assert primeira.windows_via_rules_fallback > 0
    antes = _linhas_por_janela(config)
    assert antes

    # O estado que a queda deixa: o banco já devolveu as janelas, a poda
    # do arquivo não aconteceu.
    conn.execute("UPDATE window SET status = 'pending'")
    conn.commit()

    _classificar_sem_modelo_nem_placa(conn, config, monkeypatch)

    assert _linhas_por_janela(config) == antes
    assert conn.execute("SELECT COUNT(*) FROM window WHERE status = 'pending'").fetchone()[0] == 0
    conn.close()


def test_sem_modelo_janela_de_queda_ja_concluida_fica_como_esta(tmp_path, monkeypatch):
    """Com o modelo fora, a janela de queda `done` não volta para a fila: só
    seria classificada de novo pelo mesmo motor de regras."""
    from .test_phase8 import TEXTO_LONGO_SEM_MARCADOR, _projeto_pronto_para_classificar

    config, conn = _projeto_pronto_para_classificar(
        tmp_path, [f"{TEXTO_LONGO_SEM_MARCADOR} Página {n}." for n in range(1, 16 + 1)], pages_per_window=8, overlap=0
    )
    _classificar_sem_modelo_nem_placa(conn, config, monkeypatch)
    caminho = Path(config.output_folder) / RAW_ITEMS_FILE_NAME
    conteudo = caminho.read_bytes()

    segunda = _classificar_sem_modelo_nem_placa(conn, config, monkeypatch)

    assert segunda.windows_processed == 0
    assert caminho.read_bytes() == conteudo
    conn.close()
