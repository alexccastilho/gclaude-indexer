"""Etapa P: sem nenhuma linha de queda, o reenfileiramento não analisa o
`raw_items.jsonl` linha a linha (num acervo grande, gigabytes a cada
classificação). Uma busca de bytes pela chave decide; havendo a chave, o
caminho de antes roda inteiro."""

from __future__ import annotations

import json

from gclaude_indexer import engine_local, raw_items


def _linha(janela, **extra):
    return json.dumps({"window": janela, "order_start": 1, "order_end": 1, "summary": "x", **extra},
                      ensure_ascii=False) + "\n"


def test_arquivo_sem_queda_nao_e_analisado(tmp_path, monkeypatch):
    caminho = tmp_path / "raw_items.jsonl"
    caminho.write_text(_linha("a") + _linha("b", summary='cita "fallback" no texto'), encoding="utf-8")

    def nao_analisa(_texto):
        raise AssertionError("o arquivo sem queda foi analisado linha a linha")

    monkeypatch.setattr(raw_items, "parse", nao_analisa)
    assert engine_local._fallback_only_windows(caminho) == set()


def test_chave_na_divisa_dos_blocos_e_achada(tmp_path):
    caminho = tmp_path / "raw_items.jsonl"
    linha_de_queda = _linha("caiu", fallback=True)
    inicio = linha_de_queda.index('"fallback"')
    # A chave começa 4 bytes antes do fim do primeiro bloco de 1 MiB.
    enchimento = (1 << 20) - 4 - inicio
    with open(caminho, "w", encoding="utf-8", newline="\n") as arquivo:
        arquivo.write(" " * (enchimento - 1) + "\n")
        arquivo.write(linha_de_queda)
        arquivo.write(_linha("ok"))
    assert engine_local._mentions_fallback(caminho)
    assert engine_local._fallback_only_windows(caminho) == {"caiu"}
