"""2.1.4: janela que estourou o tempo 3 vezes é tentada de novo no fim.

No projeto XPTO, duas janelas do grupo Região Sul estouraram o tempo do modelo
três vezes seguidas (08:47 e 10:21), com o Ollama no ar mas lento por alguns
minutos. Ficavam pendentes "para a próxima execução": se ninguém rodasse a
classificação de novo, o índice terminava com esses buracos. Refeitas depois,
as mesmas janelas responderam em menos de um minuto.
"""

from __future__ import annotations

from gclaude_indexer.classification import ClassifiedItem
from gclaude_indexer.engine_local import OllamaConnectionError, classify_pending

from tests.test_phase8 import TEXTO_LONGO_SEM_MARCADOR, _projeto_pronto_para_classificar


class _MotorLentoNumaJanela:
    """A segunda janela estoura o tempo `lentas` vezes; o servidor segue no ar."""

    def __init__(self, lentas):
        self.lentas = lentas
        self.url_base = "fake"
        self.gpu_plan = None
        self.last_window_warnings = []
        self.last_rejections = []
        self.vistas: list[str] = []

    def is_available(self):
        return True

    def classify(self, paginas):
        primeira, ultima = paginas[0], paginas[-1]
        self.vistas.append(primeira.reference)
        if primeira.reference == "f. 9" and self.lentas > 0:
            self.lentas -= 1
            raise OllamaConnectionError("http://127.0.0.1:11434: timed out")
        return [ClassifiedItem(
            start_ref=primeira.reference, end_ref=ultima.reference, start_order=primeira.order,
            end_order=ultima.order, type="OFÍCIO", date=None, author=None, summary="pelo modelo",
            has_table=False, has_image=False, engine="local", confidence="high",
            files=sorted({p.file_name for p in paginas}),
        )]


def _classificar(tmp_path, monkeypatch, lentas):
    from gclaude_indexer import engine_local

    config, conn = _projeto_pronto_para_classificar(
        tmp_path, [f"{TEXTO_LONGO_SEM_MARCADOR} Página {n}." for n in range(1, 25)],
        pages_per_window=8, overlap=0,
    )
    monkeypatch.setattr(engine_local, "_has_dedicated_gpu", lambda: True)
    motor = _MotorLentoNumaJanela(lentas)
    resultado = classify_pending(conn, config, local_engine=motor)
    pendentes = conn.execute("SELECT key FROM window WHERE status = 'pending'").fetchall()
    eventos = [r[0] for r in conn.execute("SELECT message_key FROM event ORDER BY id")]
    conn.close()
    return motor, resultado, pendentes, eventos


def test_janela_que_estourou_o_tempo_e_tentada_de_novo_no_fim(tmp_path, monkeypatch):
    motor, resultado, pendentes, eventos = _classificar(tmp_path, monkeypatch, lentas=3)
    assert pendentes == []
    # A volta extra vem depois das outras janelas, não logo em seguida.
    assert motor.vistas == ["f. 1", "f. 9", "f. 9", "f. 9", "f. 17", "f. 9"]
    assert "log.local_engine.skipped_retry" in eventos


def test_janela_que_continua_falhando_fica_pendente_depois_da_segunda_volta(tmp_path, monkeypatch):
    motor, resultado, pendentes, _ = _classificar(tmp_path, monkeypatch, lentas=100)
    assert len(pendentes) == 1
    # Uma volta extra só: 3 tentativas na passada, mais 3 no fim.
    assert motor.vistas.count("f. 9") == 6
