# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Fase 36 — contexto sem corte, teto por hardware e backend no log.

Numa rodada (RX 6700 XT, Ollama 0.40.13, qwen3.5:9b), parte dos pedidos ao
modelo foi cortada em silêncio pelo Ollama: janelas de dezenas de milhares
de tokens reduzidas a 8194, cada uma custando uma tentativa
perdida antes de a guarda `linhas < páginas` dividi-la. O teto de contexto
era fixo em 16384 enquanto a placa tinha 3 GB livres — a janela inteira
caberia em 32768 (medido: `size_vram == size` até 49152). Esta fase calcula
o teto pela placa e pelo modelo, manda `truncate: false`, trata recusa e
corte como falha da tentativa, sobe o contexto antes de dividir, divide
antes de pedir, e registra no log qual backend está em uso e por quê.
"""

from __future__ import annotations

from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent


# --- Task 1: o KV só existe nas camadas de atenção plena ---------------------


def test_kv_conta_so_as_camadas_de_atencao_plena():
    from gclaude_indexer.gpu_budget import ModelShape, _attention_layer_count

    info = {
        "general.architecture": "qwen35",
        "qwen35.attention.recurrent_layers": [True, True, True, False] * 8,
        "qwen35.full_attention_interval": 4,
    }
    assert _attention_layer_count(info, 32) == 8
    assert _attention_layer_count({"general.architecture": "qwen35", "qwen35.full_attention_interval": 4}, 32) == 8
    assert _attention_layer_count({"general.architecture": "gemma4"}, 42) == 42

    forma = ModelShape(
        total_bytes=1, layer_count=32, embedding_length=4096, head_count=16,
        head_count_kv=4, attention_layer_count=8,
    )
    # 2 (K e V) × 8 camadas × 4 cabeças × 256 × 1 byte (q8_0) = 16 KiB por
    # token → 256 MiB em 16384 (o runner mediu 272 MiB).
    assert forma.kv_bytes_per_token(1) == 16384
    todas = ModelShape(total_bytes=1, layer_count=32, embedding_length=4096, head_count=16, head_count_kv=4)
    assert todas.kv_bytes_per_token(1) == 65536


def test_describe_model_le_as_camadas_de_atencao_plena(monkeypatch):
    from gclaude_indexer import gpu_budget as gb

    respostas = {
        "/api/show": {"model_info": {
            "general.architecture": "qwen35", "qwen35.block_count": 32,
            "qwen35.attention.head_count": 16, "qwen35.attention.head_count_kv": 4,
            "qwen35.embedding_length": 4096, "qwen35.context_length": 262144,
            "qwen35.attention.recurrent_layers": [True, True, True, False] * 8,
        }},
        "/api/tags": {"models": [{"name": "qwen3.5:9b", "size": 5912815205}]},
    }
    monkeypatch.setattr(
        gb, "_get_json",
        lambda url, payload=None, timeout=5.0: next(v for k, v in respostas.items() if url.endswith(k)),
    )
    forma = gb.describe_model("qwen3.5:9b", "http://127.0.0.1:9")
    assert forma is not None and forma.attention_layer_count == 8


# --- Task 2: teto de contexto calculado pela placa e pela RAM ---------------

_QWEN = dict(
    total_bytes=5912815205, layer_count=32, embedding_length=4096, head_count=16,
    head_count_kv=4, context_length=262144, attention_layer_count=8,
)


def test_teto_pela_placa_e_multiplo_de_4096_e_desconta_modelo_e_margens():
    from gclaude_indexer import gpu_budget as gb

    forma = gb.ModelShape(**_QWEN)
    # 12 GB livres (modelo ainda não carregado): sobra = 12288 − margem −
    # modelo − buffers de cálculo; KV = 16 KiB por token.
    sobra = 12288 - gb.SAFETY_MARGIN_MB - 5639 - gb._COMPUTE_RESERVE_MB
    esperado = min((sobra * gb.MB // 16384) // 4096 * 4096, gb.CONTEXT_CEILING_MAX)
    assert gb.context_ceiling(forma, 12288, "q8_0") == esperado
    assert esperado >= 32768, "uma janela de 26 mil tokens tem de caber inteira"
    assert gb.context_ceiling(forma, 8192, "f16") < gb.context_ceiling(forma, 8192, "q8_0"), "f16 dobra o KV e baixa o teto"
    assert gb.context_ceiling(gb.ModelShape(**{**_QWEN, "context_length": 8192}), 12288, "q8_0") == 8192
    assert gb.context_ceiling(forma, 1_000_000, "q8_0") == gb.CONTEXT_CEILING_MAX


def test_teto_pela_placa_e_zero_quando_o_modelo_nao_cabe_inteiro():
    from gclaude_indexer import gpu_budget as gb

    forma = gb.ModelShape(**{**_QWEN, "total_bytes": 9_100 * gb.MB})  # RX 5700 XT de 8 GB
    assert gb.context_ceiling(forma, 8192, "q8_0") == 0
    assert gb.context_ceiling(forma, None, "q8_0") == 0


def test_teto_sem_metadados_de_cabeca_mantem_o_16384_antigo_quando_o_modelo_cabe(monkeypatch):
    """Revisão da fase 36: antes desta fase um modelo sem `head_count` cabia
    inteiro e recebia 16384; o teto novo caía para 4096 e dividia janelas
    de 16 páginas em pedaços de 2 — regressão contra "nunca pior"."""
    from gclaude_indexer import gpu_budget as gb, ollama_backend

    sem_cabeca = gb.ModelShape(**{**_QWEN, "head_count": 0})
    assert sem_cabeca.kv_bytes_per_token(1) == 0
    assert gb.context_ceiling(sem_cabeca, 12288, "q8_0") == 16384
    assert gb.context_ceiling(gb.ModelShape(**{**_QWEN, "head_count": 0, "context_length": 8192}), 12288, "q8_0") == 8192
    assert gb.context_ceiling(gb.ModelShape(**{**_QWEN, "head_count": 0, "total_bytes": 9_100 * gb.MB}), 8192, "q8_0") == 0
    assert gb.ram_context_ceiling(sem_cabeca, 24_000, "q8_0") == 4096, "na RAM o piso é o comportamento anterior"
    monkeypatch.setattr(ollama_backend, "read_backend", lambda *a, **k: None)
    monkeypatch.setattr(gb, "describe_model", lambda m, u: sem_cabeca)
    monkeypatch.setattr(gb, "free_vram_mb", lambda m=None, u="": 12288)
    teto, detalhes = gb.measure_context_ceiling("x", "http://127.0.0.1:9")
    assert (teto, detalhes["source"], detalhes["reason"]) == (16384, "gpu", "kv_desconhecido")


def test_teto_pela_ram_limita_a_32768_e_nunca_abaixo_de_4096():
    from gclaude_indexer import gpu_budget as gb

    forma = gb.ModelShape(**_QWEN)
    assert gb.ram_context_ceiling(forma, 24_000, "q8_0") == 32768
    assert gb.ram_context_ceiling(forma, 6_000, "q8_0") == 4096
    assert gb.ram_context_ceiling(forma, None, "q8_0") == 4096
    assert gb.ram_context_ceiling(gb.ModelShape(**{**_QWEN, "context_length": 16384}), 24_000, "q8_0") == 16384


def test_medicao_do_teto_cai_na_ram_sem_placa_e_em_4096_sem_metadados(monkeypatch):
    from gclaude_indexer import gpu_budget as gb, ollama_backend

    monkeypatch.setattr(ollama_backend, "read_backend", lambda *a, **k: None)
    monkeypatch.setattr(gb, "describe_model", lambda m, u: gb.ModelShape(**_QWEN))
    monkeypatch.setattr(gb, "free_vram_mb", lambda m=None, u="": None)
    monkeypatch.setattr(gb, "available_ram_mb", lambda: 24_000)
    teto, detalhes = gb.measure_context_ceiling("qwen3.5:9b", "http://127.0.0.1:9")
    assert (teto, detalhes["source"]) == (32768, "ram")
    teto, detalhes = gb.measure_context_ceiling("qwen3.5:9b", "http://127.0.0.1:9", use_gpu=False)
    assert (teto, detalhes["source"]) == (32768, "ram")
    monkeypatch.setattr(gb, "describe_model", lambda m, u: None)
    teto, detalhes = gb.measure_context_ceiling("x", "http://127.0.0.1:9")
    assert (teto, detalhes["source"], detalhes["reason"]) == (4096, "none", "sem_metadados")


def test_medicao_do_teto_prefere_a_placa_quando_ha_vram(monkeypatch):
    from gclaude_indexer import gpu_budget as gb, ollama_backend

    monkeypatch.setattr(ollama_backend, "read_backend", lambda *a, **k: None)
    monkeypatch.setattr(gb, "describe_model", lambda m, u: gb.ModelShape(**_QWEN))
    monkeypatch.setattr(gb, "free_vram_mb", lambda m=None, u="": 12288)
    monkeypatch.setattr(gb, "available_ram_mb", lambda: 24_000)
    monkeypatch.delenv("OLLAMA_KV_CACHE_TYPE", raising=False)
    teto, detalhes = gb.measure_context_ceiling("qwen3.5:9b", "http://127.0.0.1:9")
    assert detalhes["source"] == "gpu" and teto == gb.context_ceiling(gb.ModelShape(**_QWEN), 12288, "q8_0")
    assert detalhes["attention_layers"] == 8 and detalhes["kv_per_token_bytes"] == 16384


def test_plano_usa_o_tipo_de_cache_do_ambiente_efetivo(monkeypatch):
    from gclaude_indexer import gpu_budget as gb, ollama_backend

    monkeypatch.setattr(ollama_backend, "read_backend", lambda *a, **k: None)
    monkeypatch.delenv("OLLAMA_FLASH_ATTENTION", raising=False)
    visto = {}
    monkeypatch.setattr(gb, "describe_model", lambda m, u: gb.ModelShape(**_QWEN))
    monkeypatch.setattr(gb, "free_vram_mb", lambda m=None, u="": 12288)
    monkeypatch.setattr(gb, "layers_that_fit", lambda *a, **k: visto.update(k) or 33)
    monkeypatch.setenv("OLLAMA_KV_CACHE_TYPE", "f16")
    gb.plan("qwen3.5:9b", "http://127.0.0.1:9", 16384)
    assert visto["cache_type"] == "f16"


# --- Task 3: o motor usa o teto calculado, inclusive no modo "cpu" ----------


def test_teto_e_medido_uma_vez_e_limita_o_contexto(monkeypatch):
    from gclaude_indexer import engine_local, gpu_budget

    chamadas = []
    monkeypatch.setattr(
        gpu_budget, "measure_context_ceiling",
        lambda m, u, use_gpu=True: chamadas.append(use_gpu) or (32768, {"source": "gpu"}),
    )
    monkeypatch.setattr(gpu_budget, "plan", lambda m, u, c: (33, {"layers": 33}))
    motor = engine_local.LocalEngine(model="fake", url_base="http://127.0.0.1:9")
    motor.plan_gpu_use("x" * 300_000, page_count=16)   # ~100 mil tokens estimados
    motor.plan_gpu_use("x" * 300_000, page_count=16)
    assert motor.num_ctx == 32768 and chamadas == [True]
    assert motor.gpu_plan["context_ceiling"] == 32768
    assert not hasattr(engine_local, "_CONTEXT_CEILING_CANDIDATES")


def test_modo_cpu_manda_num_ctx_limitado_pela_ram(monkeypatch):
    from gclaude_indexer import engine_local, gpu_budget

    monkeypatch.setattr(
        gpu_budget, "measure_context_ceiling",
        lambda m, u, use_gpu=True: (0, {}) if use_gpu else (16384, {"source": "ram"}),
    )

    def nunca(*a):
        raise AssertionError("plan() não roda na CPU")

    monkeypatch.setattr(gpu_budget, "plan", nunca)
    motor = engine_local.LocalEngine(model="fake", url_base="http://127.0.0.1:9", num_gpu=0)
    assert motor.plan_gpu_use("x" * 90_000, page_count=16) is None
    assert motor.num_ctx == 16384 and motor.num_gpu == 0
    motor.plan_gpu_use("x" * 3_000, page_count=1)
    assert motor.num_ctx == 16384, "o contexto só cresce"


def test_evento_do_plano_diz_o_teto():
    from gclaude_indexer.i18n import translate

    for idioma in ("pt", "en", "es"):
        texto = translate(
            idioma, "log.local_engine.gpu_plan", model="m", layers=33, layers_total=33,
            free_vram=1, context=16384, ceiling=32768,
        )
        assert "32768" in texto


# --- Task 4: pedido sem corte ------------------------------------------------

import io  # noqa: E402
import json  # noqa: E402
import urllib.error  # noqa: E402

import pytest  # noqa: E402

from gclaude_indexer.engine_local import LocalEngine  # noqa: E402
from tests.test_phase21 import _OllamaSimulado, _Resposta, _linhas, _page, _plan_com_teto  # noqa: E402


class _OllamaQueRecusa(_OllamaSimulado):
    """Ollama 0.40 com `truncate: false`: prompt maior que `num_ctx` volta
    como erro HTTP 400, nunca cortado (comportamento verificado)."""

    def __call__(self, request, timeout=None):
        corpo = json.loads(request.data.decode("utf-8"))
        assert corpo["truncate"] is False
        contexto = corpo["options"]["num_ctx"]
        if self.prompt_tokens > contexto:
            self.contextos.append(contexto)
            raise urllib.error.HTTPError(
                request.full_url, 400, "Bad Request", {},
                io.BytesIO(json.dumps({"error": (
                    f"request ({self.prompt_tokens} tokens) exceeds the available context size "
                    f"({contexto} tokens), try increasing it"
                )}).encode()),
            )
        return super().__call__(request, timeout)


def _paginas_longas(n: int = 4, repeticoes: int = 2500) -> list:
    return [_page(f"f. {i}", "texto " * repeticoes) for i in range(1, n + 1)]


def test_recusa_do_ollama_sobe_o_contexto_e_repete_a_janela_inteira(monkeypatch):
    _plan_com_teto(monkeypatch, teto=32768)
    ollama = _OllamaQueRecusa(prompt_tokens=20000, paginas=4)
    monkeypatch.setattr("gclaude_indexer.engine_local.urllib.request.urlopen", ollama)
    motor = LocalEngine(model="fake", url_base="http://127.0.0.1:9")
    motor._chars_per_token = 6.0   # razão otimista: o primeiro num_ctx (~11k) fica abaixo dos 20000 reais

    itens = motor.classify_per_page(_paginas_longas())

    assert len(ollama.contextos) == 2 and ollama.contextos[-1] >= 20000 + 880
    assert ("log.local_engine.window_context_raised", {"context": ollama.contextos[-1]}) in motor.last_window_notes
    assert all(item.confidence != "low" for item in itens)
    assert not motor.last_window_warnings


def test_janela_acima_do_teto_e_dividida_antes_de_pedir(monkeypatch):
    _plan_com_teto(monkeypatch, teto=4096)
    ollama = _OllamaQueRecusa(prompt_tokens=1500, paginas=2)
    monkeypatch.setattr("gclaude_indexer.engine_local.urllib.request.urlopen", ollama)
    motor = LocalEngine(model="fake", url_base="http://127.0.0.1:9")
    # 3000 caracteres por página: a janela inteira pede 6144 tokens
    # (medido com `context_tokens_for`), acima do teto de 4096; cada metade
    # pede exatamente 4096 e cabe.
    itens = motor.classify_per_page(_paginas_longas(4, 500))

    assert len(ollama.contextos) == 2 and all(c <= 4096 for c in ollama.contextos), "só as duas metades foram pedidas"
    assert motor.last_window_notes[0][0] == "log.local_engine.window_split_for_size"
    assert motor.last_window_notes[0][1]["pages"] == 4 and motor.last_window_notes[0][1]["ceiling"] == 4096
    assert {f for item in itens for f in range(item.start_order, item.end_order + 1)} == {1, 2, 3, 4}


def test_assinatura_do_corte_e_falha_mesmo_com_o_numero_certo_de_linhas(monkeypatch):
    _plan_com_teto(monkeypatch, teto=32768)

    class _CortaMasResponde(_OllamaSimulado):
        """Servidor antigo, que ignora `truncate`: corta e ainda devolve as 4 linhas."""

        def __call__(self, request, timeout=None):
            contexto = json.loads(request.data.decode("utf-8"))["options"]["num_ctx"]
            if self.prompt_tokens > contexto:
                self.contextos.append(contexto)
                return _Resposta({"response": _linhas(self.paginas), "prompt_eval_count": contexto // 2 + 2, "eval_count": 400})
            return super().__call__(request, timeout)

    ollama = _CortaMasResponde(prompt_tokens=20000, paginas=4)
    monkeypatch.setattr("gclaude_indexer.engine_local.urllib.request.urlopen", ollama)
    motor = LocalEngine(model="fake", url_base="http://127.0.0.1:9")
    motor._chars_per_token = 6.0

    motor.classify_per_page(_paginas_longas())

    # 1ª: ctx ~11264, lido 5634, estimado ~10300 (≥ 1,35×) → falha apesar das 4 linhas; 2ª: 22528, cabe
    assert len(ollama.contextos) == 2 and ollama.contextos[-1] > ollama.contextos[0]


def test_prompt_honesto_perto_da_metade_nao_e_tomado_por_corte():
    from gclaude_indexer.engine_local import Generation, _looks_truncated

    g = Generation(text="", prompt_tokens=8200, context=16384)
    assert _looks_truncated(g)                                      # assinatura sozinha (compatibilidade)
    assert not _looks_truncated(g, estimated_prompt_tokens=9000)    # 9000 < 1,35 × 8200
    assert _looks_truncated(g, estimated_prompt_tokens=20000)


def test_erro_de_contexto_vira_prompt_too_long_e_outros_continuam_model_answer_error(monkeypatch):
    from gclaude_indexer.engine_local import ModelAnswerError, PromptTooLongError

    def falso(erro):
        def _(request, timeout=None):
            raise urllib.error.HTTPError(request.full_url, 400, "", {}, io.BytesIO(json.dumps({"error": erro}).encode()))
        return _

    motor = LocalEngine(model="fake", url_base="http://127.0.0.1:9")
    motor.num_ctx = 4096
    monkeypatch.setattr("gclaude_indexer.engine_local.urllib.request.urlopen",
                        falso("request (10289 tokens) exceeds the available context size (4096 tokens), try increasing it"))
    with pytest.raises(PromptTooLongError) as info:
        motor._generate("x")
    assert info.value.tokens == 10289
    monkeypatch.setattr("gclaude_indexer.engine_local.urllib.request.urlopen",
                        falso("input exceeds maximum context length and cannot be truncated further"))
    with pytest.raises(PromptTooLongError) as info:
        motor._generate("x")
    assert info.value.tokens == 0
    monkeypatch.setattr("gclaude_indexer.engine_local.urllib.request.urlopen", falso("prediction aborted, token repeat limit reached"))
    with pytest.raises(ModelAnswerError) as info:
        motor._generate("x")
    assert not isinstance(info.value, PromptTooLongError)


def test_janela_de_uma_pagina_acima_do_teto_faz_uma_tentativa_so(monkeypatch):
    _plan_com_teto(monkeypatch, teto=4096)
    ollama = _OllamaQueRecusa(prompt_tokens=90000, paginas=1)
    monkeypatch.setattr("gclaude_indexer.engine_local.urllib.request.urlopen", ollama)
    motor = LocalEngine(model="fake", url_base="http://127.0.0.1:9")

    itens = motor.classify_per_page([_page("f. 1", "texto " * 400)])

    assert [item.confidence for item in itens] == ["low"] and len(ollama.contextos) == 1
    assert motor.last_window_warnings


def test_contagem_exata_acima_do_teto_nao_sobe_o_contexto_a_toa(monkeypatch):
    """Revisão da fase 36: a recusa do Ollama diz quantos tokens o prompt
    tem; se esse número já passa do teto, subir `num_ctx` ao teto só custa
    uma recarga do modelo para receber outro 400 — e deixava no log uma
    nota "contexto ampliado" sem nada lido. Divide-se direto."""
    _plan_com_teto(monkeypatch, teto=32768)
    ollama = _OllamaQueRecusa(prompt_tokens=90000, paginas=4)
    monkeypatch.setattr("gclaude_indexer.engine_local.urllib.request.urlopen", ollama)
    motor = LocalEngine(model="fake", url_base="http://127.0.0.1:9")

    itens = motor.classify_per_page(_paginas_longas())

    chaves = [chave for chave, _ in motor.last_window_notes]
    assert "log.local_engine.window_context_raised" not in chaves
    assert len(ollama.contextos) == 7 and len(set(ollama.contextos)) == 1, "1 + 2 + 4 tentativas, nenhuma com contexto maior"
    nota = next(params for chave, params in motor.last_window_notes if chave == "log.local_engine.window_split_for_size")
    assert nota["pages"] == 4 and nota["ceiling"] == 32768 and nota["needed"] > 90000
    assert [item.confidence for item in itens] == ["low"] * 4


# --- Task 5: nota por janela e resumo da etapa --------------------------------


class _MotorComNotas:
    """Motor falso de `classify_pending`: a primeira janela subiu o contexto,
    a segunda foi dividida por tamanho; as demais, nada."""

    def __init__(self):
        from tests.test_phase29 import _MotorQueCai

        self._base = _MotorQueCai(0)
        self.url_base = "fake"
        self.gpu_plan = None
        self.last_window_warnings = []
        self.last_window_notes = []
        self.context_ceiling = 32768
        self.chamadas = 0

    def no_ar(self):
        return True

    def is_available(self):
        return True

    def classify(self, paginas):
        self.chamadas += 1
        self.last_window_notes = []
        if self.chamadas == 1:
            self.last_window_notes = [("log.local_engine.window_context_raised", {"context": 24576})]
        elif self.chamadas == 2:
            self.last_window_notes = [
                ("log.local_engine.window_split_for_size", {"pages": 8, "needed": 40960, "ceiling": 32768}),
            ]
        return self._base.classify(paginas)


def test_notas_da_janela_viram_eventos_e_entram_no_resumo(tmp_path, monkeypatch):
    from tests.test_phase29 import _classificacao_com_motor

    motor = _MotorComNotas()
    _, conn, resultado, _ = _classificacao_com_motor(tmp_path, monkeypatch, motor, True)
    eventos = conn.execute(
        "SELECT message_key, message_params FROM event WHERE message_key LIKE 'log.local_engine.%' ORDER BY id"
    ).fetchall()
    chaves = [e[0] for e in eventos]
    assert chaves.count("log.local_engine.window_note") == 2
    resumo = [json.loads(e[1]) for e in eventos if e[0] == "log.local_engine.context_summary"]
    assert resumo == [{"raised": 1, "split": 1, "ceiling": 32768}]
    assert chaves.index("log.local_engine.context_summary") < chaves.index("log.local_engine.summary")
    assert (resultado.windows_context_raised, resultado.windows_split_for_size) == (1, 1)
    conn.close()


def test_sem_notas_nao_ha_resumo_de_contexto(tmp_path, monkeypatch):
    from tests.test_phase29 import _MotorQueCai, _classificacao_com_motor

    _, conn, resultado, _ = _classificacao_com_motor(tmp_path, monkeypatch, _MotorQueCai(0), True)
    assert conn.execute("SELECT COUNT(*) FROM event WHERE message_key = 'log.local_engine.context_summary'").fetchone()[0] == 0
    assert (resultado.windows_context_raised, resultado.windows_split_for_size) == (0, 0)
    conn.close()


_CHAVES_DA_FASE = (
    ("log.local_engine.gpu_plan", {"model": "m", "layers": 1, "layers_total": 1, "free_vram": 1, "context": 1, "ceiling": 1}),
    ("log.local_engine.window_note", {"window": "w", "reason": "r"}),
    ("log.local_engine.window_context_raised", {"context": 1}),
    ("log.local_engine.window_split_for_size", {"pages": 1, "needed": 1, "ceiling": 1}),
    ("log.local_engine.context_summary", {"raised": 1, "split": 1, "ceiling": 1}),
)


def test_chaves_da_fase_36_nos_tres_idiomas():
    from gclaude_indexer.i18n import translate

    for idioma in ("pt", "en", "es"):
        for chave, params in _CHAVES_DA_FASE:
            texto = translate(idioma, chave, **params)
            assert texto and texto != chave, (idioma, chave)


# --- Task 6: diagnóstico do backend a partir do log do servidor -------------

_LOG_AMD = """time=2026-11-02T12:02:30.000-03:00 level=INFO source=types.go:32 msg="inference compute" id=GPU-1 library=CUDA compute=8.6 name=CUDA0 description="NVIDIA GeForce RTX 3060 Laptop GPU" total="6.0 GiB" available="5.1 GiB"
time=2026-11-02T12:02:36.912-03:00 level=WARN source=amd.go:485 msg="AMD driver is too old. Update your AMD driver to enable GPU inference."
time=2026-11-02T12:02:38.460-03:00 level=INFO source=types.go:32 msg="inference compute" id=0 filter_id=0 library=Vulkan compute=0.0 name=Vulkan0 description="AMD Radeon RX 6700 XT" libdirs=ollama,vulkan driver=0.0 pci_id="" type=discrete total="12.0 GiB" available="11.2 GiB"
[GIN] 2026/11/02 - 12:02:40 | 200 |       0s |       127.0.0.1 | GET      "/api/version"
time=2026-11-02T12:02:53.474-03:00 level=WARN source=sched.go:552 msg="model architecture does not currently support parallel requests" architecture=qwen35
"""

_LOG_CUDA = """time=2026-11-03T09:00:00.000-03:00 level=INFO source=types.go:32 msg="inference compute" id=GPU-1 library=CUDA compute=8.6 name=CUDA0 description="NVIDIA GeForce RTX 3060 Laptop GPU" total="6.0 GiB" available="5.1 GiB"
"""


def test_parse_do_log_pega_o_ultimo_bloco_de_descoberta():
    from gclaude_indexer.ollama_backend import parse_backend_log

    info = parse_backend_log(_LOG_AMD)
    assert info is not None
    assert (info.library, info.device, info.total) == ("Vulkan", "AMD Radeon RX 6700 XT", "12.0 GiB")
    assert info.seen_at == "2026-11-02T12:02:38.460-03:00"
    assert info.amd_driver_old is True
    assert info.parallel_pinned_family == "qwen35"

    cuda = parse_backend_log(_LOG_CUDA)
    assert (cuda.library, cuda.amd_driver_old, cuda.parallel_pinned_family) == ("CUDA", False, None)
    assert parse_backend_log("[GIN] nada de descoberta aqui\n") is None
    assert parse_backend_log("") is None


def test_read_backend_escolhe_o_log_mais_recente_e_ignora_o_que_nao_abre(tmp_path):
    from gclaude_indexer.ollama_backend import read_backend

    nosso = tmp_path / "ollama-serve.log"
    do_ollama = tmp_path / "Ollama" / "server.log"
    nosso.write_text(_LOG_AMD, encoding="utf-8")
    do_ollama.parent.mkdir()
    do_ollama.write_text(_LOG_CUDA, encoding="utf-8")   # subiu depois (03/11)
    assert read_backend([nosso, do_ollama]).library == "CUDA"
    assert read_backend([nosso, tmp_path / "nao-existe.log"]).library == "Vulkan"
    assert read_backend([tmp_path / "nao-existe.log"]) is None
    assert read_backend([]) is None
    # só a cauda é lida: um arquivo grande com a descoberta no fim continua legível
    grande = tmp_path / "grande.log"
    grande.write_text("x" * 2_000_000 + "\n" + _LOG_AMD, encoding="utf-8")
    assert read_backend([grande], tail_bytes=65536).library == "Vulkan"


def test_backend_log_paths_aponta_para_o_nosso_log_e_para_o_do_ollama(monkeypatch, tmp_path):
    from gclaude_indexer.ollama_backend import backend_log_paths

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("GCLAUDE_INDEXER_LOCAL_FOLDER", raising=False)
    caminhos = backend_log_paths()
    assert caminhos[0].name == "ollama-serve.log"
    assert caminhos[1] == tmp_path / "Ollama" / "server.log"


def _classificar_com_backend(tmp_path, monkeypatch, info):
    from gclaude_indexer import ollama_backend
    from tests.test_phase29 import _MotorQueCai, _classificacao_com_motor

    monkeypatch.setattr(ollama_backend, "read_backend", lambda *a, **k: info)
    _, conn, _, _ = _classificacao_com_motor(tmp_path, monkeypatch, _MotorQueCai(0), True)
    eventos = conn.execute(
        "SELECT level, message_key, message_params FROM event WHERE message_key LIKE 'log.local_engine.backend%' ORDER BY id"
    ).fetchall()
    conn.close()
    return eventos


def test_backend_amd_via_vulkan_sem_hip7_vira_dois_eventos_uma_vez_so(tmp_path, monkeypatch):
    from gclaude_indexer.ollama_backend import BackendInfo

    info = BackendInfo(library="Vulkan", device="AMD Radeon RX 6700 XT", total="12.0 GiB",
                       seen_at="t", amd_driver_old=True, parallel_pinned_family="qwen35")
    eventos = _classificar_com_backend(tmp_path, monkeypatch, info)
    chaves = [e[1] for e in eventos]
    assert chaves == ["log.local_engine.backend", "log.local_engine.backend_amd_no_hip7"]
    params = json.loads(eventos[0][2])
    assert (params["device"], params["library"]) == ("AMD Radeon RX 6700 XT", "Vulkan")
    assert params["note"]["$i18n_key"] == "log.local_engine.backend_parallel_pinned"
    assert params["note"]["$i18n_params"] == {"family": "qwen35"}
    assert eventos[1][0] == "warning"


def test_rx_7000_com_driver_antigo_recebe_o_aviso_de_atualizar_e_nao_o_do_hip7(tmp_path, monkeypatch):
    """Revisão da fase 36: a RX 7900 com driver antigo imprime a mesma
    linha "AMD driver is too old" e cai em Vulkan, mas para ela um
    Adrenalin com HIP 7 existe — dizer "nenhuma atualização muda isso"
    seria falso e contradiria o instalador."""
    from gclaude_indexer.ollama_backend import BackendInfo

    info = BackendInfo(library="Vulkan", device="AMD Radeon RX 7900 XTX", total="24.0 GiB",
                       seen_at="t", amd_driver_old=True)
    eventos = _classificar_com_backend(tmp_path, monkeypatch, info)
    assert [e[1] for e in eventos] == ["log.local_engine.backend", "log.local_engine.backend_amd_driver_old"]
    assert eventos[1][0] == "warning" and json.loads(eventos[1][2])["device"] == "AMD Radeon RX 7900 XTX"


def test_backend_nvidia_sem_avisos_e_so_o_evento_informativo(tmp_path, monkeypatch):
    from gclaude_indexer.ollama_backend import BackendInfo

    info = BackendInfo(library="CUDA", device="NVIDIA GeForce RTX 3060 Laptop GPU", total="6.0 GiB", seen_at="t")
    eventos = _classificar_com_backend(tmp_path, monkeypatch, info)
    assert [e[1] for e in eventos] == ["log.local_engine.backend"]
    assert json.loads(eventos[0][2])["note"]["$i18n_key"] == "log.local_engine.backend_no_note"


def test_sem_log_nenhum_o_backend_fica_como_nao_identificado(tmp_path, monkeypatch):
    eventos = _classificar_com_backend(tmp_path, monkeypatch, None)
    assert [e[1] for e in eventos] == ["log.local_engine.backend_unknown"]


_CHAVES_DA_FASE += (
    ("log.local_engine.backend", {"device": "d", "library": "l", "total": "t", "note": "n"}),
    ("log.local_engine.backend_parallel_pinned", {"family": "f"}),
    ("log.local_engine.backend_no_note", {}),
    ("log.local_engine.backend_amd_no_hip7", {"device": "d"}),
    ("log.local_engine.backend_amd_driver_old", {"device": "d"}),
    ("log.local_engine.backend_unknown", {}),
)


# --- Task 7: flash attention desligada em Vulkan sobre AMD RDNA1/RDNA2 ------


def test_vulkan_em_rdna2_desliga_a_flash_attention_e_usa_kv_f16():
    from gclaude_indexer import gpu_budget as gb
    from gclaude_indexer.ollama_backend import BackendInfo

    rx6700 = BackendInfo(library="Vulkan", device="AMD Radeon RX 6700 XT", total="12.0 GiB", seen_at="t")
    rx7900 = BackendInfo(library="Vulkan", device="AMD Radeon RX 7900 XTX", total="24 GiB", seen_at="t")
    cuda = BackendInfo(library="CUDA", device="NVIDIA GeForce RTX 3060 Laptop GPU", total="6 GiB", seen_at="t")
    assert gb.backend_overrides(rx6700) == {"OLLAMA_FLASH_ATTENTION": "0", "OLLAMA_KV_CACHE_TYPE": "f16"}
    assert gb.backend_overrides(rx7900) == {} and gb.backend_overrides(cuda) == {} and gb.backend_overrides(None) == {}
    # ambiente vazio: override entra
    amb = gb.server_environment({}, backend=rx6700)
    assert (amb["OLLAMA_FLASH_ATTENTION"], amb["OLLAMA_KV_CACHE_TYPE"]) == ("0", "f16")
    # valor do instalador presente: é do instalador, override entra
    amb = gb.server_environment({"OLLAMA_FLASH_ATTENTION": "1", "OLLAMA_KV_CACHE_TYPE": "q8_0"}, backend=rx6700)
    assert (amb["OLLAMA_FLASH_ATTENTION"], amb["OLLAMA_KV_CACHE_TYPE"]) == ("0", "f16")
    # valor do usuário (diferente do instalador): vence
    amb = gb.server_environment({"OLLAMA_KV_CACHE_TYPE": "q4_0"}, backend=rx6700)
    assert amb["OLLAMA_KV_CACHE_TYPE"] == "q4_0" and amb["OLLAMA_FLASH_ATTENTION"] == "0"
    # sem a regra, nada muda em relação à fase 35
    amb = gb.server_environment({"OLLAMA_NUM_PARALLEL": "3"}, backend=cuda)
    assert (amb["OLLAMA_NUM_PARALLEL"], amb["OLLAMA_FLASH_ATTENTION"], amb["OLLAMA_KV_CACHE_TYPE"]) == ("3", "1", "q8_0")


def test_regra_da_flash_attention_reconhece_nomes_de_placa_com_tm():
    """Revisão da fase 36: alguns drivers expõem "AMD Radeon(TM) RX 6600";
    o padrão exigia espaço depois de "Radeon" e a regra não disparava —
    2× de velocidade perdidos em silêncio."""
    from gclaude_indexer.ollama_backend import BackendInfo, prefers_flash_attention_off

    def vulkan(nome):
        return BackendInfo(library="Vulkan", device=nome, total="8 GiB", seen_at="t")

    assert prefers_flash_attention_off(vulkan("AMD Radeon(TM) RX 6600"))
    assert prefers_flash_attention_off(vulkan("AMD Radeon RX 5700 XT"))
    assert not prefers_flash_attention_off(vulkan("AMD Radeon RX 7900 XTX"))
    assert not prefers_flash_attention_off(vulkan("AMD Radeon(TM) Graphics"))
    assert not prefers_flash_attention_off(BackendInfo(library="ROCm", device="AMD Radeon RX 6700 XT", total="12 GiB", seen_at="t"))


def test_server_environment_le_o_backend_do_log_quando_nao_recebe_um(monkeypatch):
    from gclaude_indexer import gpu_budget as gb, ollama_backend
    from gclaude_indexer.ollama_backend import BackendInfo

    rx6700 = BackendInfo(library="Vulkan", device="AMD Radeon RX 6700 XT", total="12.0 GiB", seen_at="t")
    monkeypatch.setattr(ollama_backend, "read_backend", lambda *a, **k: rx6700)
    assert gb.server_environment({})["OLLAMA_FLASH_ATTENTION"] == "0"
    monkeypatch.setattr(ollama_backend, "read_backend", lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
    assert gb.server_environment({})["OLLAMA_FLASH_ATTENTION"] == "1", "falha na leitura do log não derruba nada"


def test_kv_quantizado_so_conta_com_a_flash_attention_ligada(monkeypatch):
    """Revisão da fase 36: o Ollama só quantiza o KV com flash attention
    ligada. Um usuário NVIDIA que desligou a FA à mão fica com o `q8_0`
    do instalador no ambiente e um KV real em f16 — o teto calculado com
    metade do custo transbordaria a placa pela corrida inteira."""
    from gclaude_indexer import gpu_budget as gb, ollama_backend
    from gclaude_indexer.ollama_backend import BackendInfo

    monkeypatch.setattr(ollama_backend, "read_backend", lambda *a, **k: None)
    monkeypatch.delenv("OLLAMA_KV_CACHE_TYPE", raising=False)
    monkeypatch.setenv("OLLAMA_FLASH_ATTENTION", "0")
    assert gb._effective_cache_type() == "f16"
    monkeypatch.setenv("OLLAMA_FLASH_ATTENTION", "false")
    assert gb._effective_cache_type() == "f16"
    monkeypatch.setenv("OLLAMA_FLASH_ATTENTION", "1")
    assert gb._effective_cache_type() == "q8_0"
    monkeypatch.setenv("OLLAMA_KV_CACHE_TYPE", "q4_0")
    assert gb._effective_cache_type() == "q4_0"
    # regra da RDNA2 com KV do usuário: a FA cai, o q4_0 fica no ambiente
    # (valor dele), mas o teto é calculado com o f16 que o servidor usa
    monkeypatch.delenv("OLLAMA_FLASH_ATTENTION", raising=False)
    rx6700 = BackendInfo(library="Vulkan", device="AMD Radeon RX 6700 XT", total="12.0 GiB", seen_at="t")
    monkeypatch.setattr(ollama_backend, "read_backend", lambda *a, **k: rx6700)
    assert gb.server_environment()["OLLAMA_KV_CACHE_TYPE"] == "q4_0"
    assert gb._effective_cache_type() == "f16"


def test_teto_acompanha_o_kv_f16_da_regra(monkeypatch):
    from gclaude_indexer import gpu_budget as gb, ollama_backend
    from gclaude_indexer.ollama_backend import BackendInfo

    monkeypatch.delenv("OLLAMA_KV_CACHE_TYPE", raising=False)
    monkeypatch.setattr(ollama_backend, "read_backend", lambda *a, **k: BackendInfo(
        library="Vulkan", device="AMD Radeon RX 6700 XT", total="12.0 GiB", seen_at="t"))
    monkeypatch.setattr(gb, "describe_model", lambda m, u: gb.ModelShape(**_QWEN))
    monkeypatch.setattr(gb, "free_vram_mb", lambda m=None, u="": 8192)
    _, detalhes = gb.measure_context_ceiling("qwen3.5:9b", "http://127.0.0.1:9")
    assert detalhes["cache_type"] == "f16" and detalhes["kv_per_token_bytes"] == 32768


def test_instalador_e_desinstalador_sabem_da_regra_da_flash_attention():
    instalador = (_RAIZ / "install.ps1").read_text(encoding="utf-8")
    assert 'RX\s*[56]\d{3}' in instalador
    assert '"OLLAMA_FLASH_ATTENTION"] = "0"' in instalador and '"OLLAMA_KV_CACHE_TYPE"] = "f16"' in instalador
    # Revisão: numa máquina que não é RDNA1/2 um "0"/"f16" definido à mão é do
    # usuário e fica; só o valor anterior do próprio instalador ("1"/"q8_0")
    # cede, e só quando a regra se aplica — o mesmo que `server_environment`.
    assert '"OLLAMA_FLASH_ATTENTION" = @("1")' in instalador and '"OLLAMA_KV_CACHE_TYPE"   = @("q8_0")' in instalador
    assert "$ours = $AmdRdna12 -and" in instalador
    assert "applies no GPU adjustment on any machine" not in instalador
    assert instalador.count("No adjustment applied: this GPU needs none.") == 2, "as duas linhas do ramo AMD passaram a depender de $AmdRdna12"
    desinstalador = (_RAIZ / "uninstall.ps1").read_text(encoding="utf-8")
    # remove a variável tanto com o valor padrão quanto com o da regra
    assert '"OLLAMA_FLASH_ATTENTION"   = @("1", "0")' in desinstalador
    assert '"OLLAMA_KV_CACHE_TYPE"     = @("q8_0", "f16")' in desinstalador


def test_evento_do_backend_diz_que_a_flash_attention_foi_desligada(tmp_path, monkeypatch):
    from gclaude_indexer.ollama_backend import BackendInfo

    info = BackendInfo(library="Vulkan", device="AMD Radeon RX 6700 XT", total="12.0 GiB", seen_at="t")
    (tmp_path / "amd").mkdir()
    eventos = _classificar_com_backend(tmp_path / "amd", monkeypatch, info)
    params = json.loads(eventos[0][2])
    assert params["tuning"]["$i18n_key"] == "log.local_engine.backend_flash_attention_off"
    cuda = BackendInfo(library="CUDA", device="NVIDIA GeForce RTX 3060 Laptop GPU", total="6 GiB", seen_at="t")
    (tmp_path / "nvidia").mkdir()
    eventos = _classificar_com_backend(tmp_path / "nvidia", monkeypatch, cuda)
    assert json.loads(eventos[0][2])["tuning"]["$i18n_key"] == "log.local_engine.backend_tuning_default"


_CHAVES_DA_FASE += (
    ("log.local_engine.backend", {"device": "d", "library": "l", "total": "t", "note": "n", "tuning": "u"}),
    ("log.local_engine.backend_flash_attention_off", {}),
    ("log.local_engine.backend_tuning_default", {}),
)


# --- Task 8: versão e documentos ---------------------------------------------


def test_versao_e_documentos_da_fase_36():
    import re

    app = (_RAIZ / "gclaude_indexer" / "web" / "app.py").read_text(encoding="utf-8")
    # A fase 36 subiu a versão para 1.7.4; as seguintes sobem mais. Pinar a
    # corrente aqui quebrava a cada fase (aconteceu na 37).
    versao = re.search(r'^SYSTEM_VERSION = "(\d+)\.(\d+)\.(\d+)"$', app, re.M)
    assert versao and tuple(int(n) for n in versao.groups()) >= (1, 7, 4)
    for registro in ("CHANGELOG.md", "docs/CHANGELOG.pt-BR.md", "docs/CHANGELOG.es.md"):
        texto = (_RAIZ / registro).read_text(encoding="utf-8")
        assert "## [1.7.4]" in texto and texto.index("## [1.7.4]") < texto.index("## [1.7.3]"), registro
    especificacao = (_RAIZ / "docs" / "SPECIFICATION.md").read_text(encoding="utf-8")
    assert "131072" in especificacao and "truncate" in especificacao
    assert "HSA_OVERRIDE_GFX_VERSION=10.3.0` — the one adjustment" not in especificacao
