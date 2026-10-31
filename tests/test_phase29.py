# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""1.5.9: o que travou ou se repetiu à toa em produção (31/10/2026).

- a busca de texto completo varria a tabela inteira para cada arquivo;
- a tela de execução lia o texto de todas as páginas para contá-las;
- o log ao vivo colava a página "banco ocupado" na lista;
- a classificação gravava um commit por janela e por evento;
- a revisão reenviava ao modelo as janelas já revisadas.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from gclaude_indexer import fulltext
from gclaude_indexer.artifacts import _gaps_by_group
from gclaude_indexer.engine_rules import classify_pending as classify_rules
from gclaude_indexer.fulltext import coverage, index_pending, remove_file, search
from gclaude_indexer.i18n import translate
from gclaude_indexer.import_items import RAW_ITEMS_FILE_NAME
from gclaude_indexer.quality import _coverage
from gclaude_indexer.review import _low_confidence_windows
from gclaude_indexer.web.background_runs import StepTask, _fulltext_progress, _fulltext_progress_dict
from gclaude_indexer.web.step_state import step_status
from gclaude_indexer.windows_prep import group_page_counts, pages_for_group, prepare_windows

from .test_busca_texto_completo import _extrair, _projeto
from .test_phase28 import _projeto_com_paginas

# --- busca de texto completo ----------------------------------------------------


def _tres_notas(tmp_path):
    origem, config, conn = _projeto(tmp_path)
    for n, bicho in enumerate(("capivara", "tamandua", "jabuti")):
        (origem / f"n{n}.txt").write_text(f"nota {n} sobre {bicho}", encoding="utf-8")
    _extrair(conn, config)
    return origem, config, conn


def test_cada_arquivo_indexado_guarda_a_faixa_dos_seus_trechos(tmp_path):
    _, _, conn = _tres_notas(tmp_path)
    faixas = conn.execute(
        "SELECT file_id, first_rowid, last_rowid FROM fulltext_file ORDER BY first_rowid"
    ).fetchall()
    assert len(faixas) == 3
    for file_id, primeiro, ultimo in faixas:
        assert primeiro is not None and ultimo >= primeiro
        ids = {row[0] for row in conn.execute(
            "SELECT file_id FROM fulltext WHERE rowid BETWEEN ? AND ?", (primeiro, ultimo)
        )}
        assert ids == {file_id}
    conn.close()


def test_remover_pela_faixa_tira_so_aquele_arquivo(tmp_path):
    _, _, conn = _tres_notas(tmp_path)
    alvo = conn.execute("SELECT id FROM file WHERE name = 'n1.txt'").fetchone()[0]
    remove_file(conn, alvo)
    conn.commit()
    assert search(conn, "tamandua")[1] == 0
    assert search(conn, "capivara")[1] == 1
    assert search(conn, "jabuti")[1] == 1
    conn.close()


def test_remover_arquivo_indexado_antes_da_1_5_9_ainda_funciona(tmp_path):
    """Sem faixa (NULL), a remoção volta ao jeito antigo."""
    _, _, conn = _tres_notas(tmp_path)
    conn.execute("UPDATE fulltext_file SET first_rowid = NULL, last_rowid = NULL")
    alvo = conn.execute("SELECT id FROM file WHERE name = 'n0.txt'").fetchone()[0]
    remove_file(conn, alvo)
    conn.commit()
    assert search(conn, "capivara")[1] == 0
    assert search(conn, "jabuti")[1] == 1
    conn.close()


def test_arquivo_nunca_indexado_nao_toca_na_tabela_de_busca(tmp_path):
    _, _, conn = _tres_notas(tmp_path)
    comandos = []
    conn.set_trace_callback(comandos.append)
    remove_file(conn, 999_999)
    conn.set_trace_callback(None)
    assert not [c for c in comandos if "DELETE FROM fulltext " in c + " "]
    conn.close()


def test_arquivo_ilegivel_conta_como_tentado_e_a_etapa_termina(tmp_path, monkeypatch):
    origem, config, conn = _projeto(tmp_path)
    (origem / "a.txt").write_text("texto legível", encoding="utf-8")
    _extrair(conn, config)
    conn.execute("DELETE FROM fulltext")
    conn.execute("DELETE FROM fulltext_file")
    conn.commit()

    def _quebra(*_args, **_kwargs):
        raise OSError("sumiu")

    monkeypatch.setattr(fulltext, "_read_passages", _quebra)
    index_pending(conn, config)
    assert coverage(conn) == (1, 1)
    extracao = next(s for s in step_status(conn, lambda _k: False) if s["chave"] == "extraction")
    assert extracao["status"] == "done"
    conn.close()


def test_extracao_fica_pendente_enquanto_falta_indexar_a_busca(tmp_path):
    _, config, conn = _tres_notas(tmp_path)
    conn.execute("DELETE FROM fulltext")
    conn.execute("DELETE FROM fulltext_file")
    conn.commit()
    extracao = next(s for s in step_status(conn, lambda _k: False) if s["chave"] == "extraction")
    assert extracao["status"] == "pending"

    index_pending(conn, config)
    extracao = next(s for s in step_status(conn, lambda _k: False) if s["chave"] == "extraction")
    assert extracao["status"] == "done"
    conn.close()


def test_barra_mostra_a_fase_da_busca(tmp_path):
    _, _, conn = _tres_notas(tmp_path)
    conn.execute("DELETE FROM fulltext_file WHERE rowid = (SELECT MIN(rowid) FROM fulltext_file)")
    conn.commit()
    indexados, extraidos = _fulltext_progress(conn)
    assert (indexados, extraidos) == (2, 3)
    tarefa = StepTask(step="extraction", total=0, baseline=0)
    progresso = _fulltext_progress_dict(tarefa, indexados, extraidos)
    assert progresso["phase"] == "fulltext"
    assert (progresso["concluidos"], progresso["total"], progresso["percentual"]) == (2, 3, 66)
    conn.close()


def test_rotulo_da_fase_nos_tres_idiomas():
    for idioma in ("pt", "en", "es"):
        assert translate(idioma, "run.phase_fulltext") != "run.phase_fulltext"


# --- contagem de páginas e cobertura ---------------------------------------------


def test_contagem_de_paginas_igual_a_lista_sem_ler_o_texto(tmp_path):
    _, _, config, conn = _projeto_com_paginas(tmp_path)
    contagens = group_page_counts(conn)
    assert contagens
    for grupo, total in contagens.items():
        assert total == len(pages_for_group(conn, grupo))
        sem_texto = pages_for_group(conn, grupo, with_text=False)
        assert [p["reference"] for p in sem_texto] == [p["reference"] for p in pages_for_group(conn, grupo)]
        assert "text" not in sem_texto[0].keys()
    conn.close()


def _cobertura_ingenua(conn):
    faixas = {}
    for grupo, inicio, fim, confianca in conn.execute(
        "SELECT group_key, start_order, end_order, confidence FROM item"
    ):
        faixas.setdefault(grupo, []).append((inicio, fim, confianca))
    total = cobertas = classificadas = 0
    for grupo, n in group_page_counts(conn).items():
        for folha in range(1, n + 1):
            total += 1
            dentro = [c for i, f, c in faixas.get(grupo, []) if i <= folha <= f]
            if dentro:
                cobertas += 1
                if any(c != "low" for c in dentro):
                    classificadas += 1
    return total, cobertas, classificadas


def test_cobertura_por_diferencas_igual_a_comparacao_folha_a_folha(tmp_path):
    _, _, config, conn = _projeto_com_paginas(tmp_path)
    grupo, n = next(iter(group_page_counts(conn).items()))
    sorteio = random.Random(29)
    for numero in range(12):
        inicio = sorteio.randint(-1, n + 1)
        fim = sorteio.randint(inicio, n + 3)
        conn.execute(
            "INSERT INTO item (group_key, start_ref, end_ref, start_order, end_order,"
            " type, confidence, engine, files) VALUES (?, 'a', 'b', ?, ?, 'x', ?, 'rules', '[]')",
            (grupo, inicio, fim, sorteio.choice(["low", "medium", "high"])),
        )
    conn.commit()
    assert _coverage(conn) == _cobertura_ingenua(conn)
    assert set(_gaps_by_group(conn)) <= {grupo}
    conn.close()


# --- janelas -----------------------------------------------------------------------


def test_preparar_janelas_nao_apaga_arquivo_que_nao_existe(tmp_path, monkeypatch):
    _, saida, config, conn = _projeto_com_paginas(tmp_path)
    apagados = []
    monkeypatch.setattr(Path, "unlink", lambda self, *a, **k: apagados.append(self))
    prepare_windows(conn, config)
    assert apagados == []
    conn.close()


def test_preparar_janelas_apaga_sobra_que_existe(tmp_path):
    _, saida, config, conn = _projeto_com_paginas(tmp_path)
    pasta = saida / "windows"
    pasta.mkdir(parents=True, exist_ok=True)
    from gclaude_indexer.windows_prep import sanitize_group_name

    grupo = next(iter(group_page_counts(conn)))
    sobra = pasta / f"{sanitize_group_name(grupo)}_j0001-0003.txt"
    sobra.write_text("texto velho", encoding="utf-8")
    prepare_windows(conn, config)
    assert not sobra.exists()
    conn.close()


# --- classificação ----------------------------------------------------------------


def test_motor_de_regras_grava_em_lote_e_marca_todas_as_janelas(tmp_path):
    _, saida, config, conn = _projeto_com_paginas(tmp_path, motor="rules")
    prepare_windows(conn, config)
    commits = []
    conn.set_trace_callback(lambda sql: commits.append(sql) if sql.strip().upper() == "COMMIT" else None)
    resultado = classify_rules(conn, config)
    conn.set_trace_callback(None)
    janelas = conn.execute("SELECT COUNT(*) FROM window").fetchone()[0]
    assert resultado.windows_processed == janelas > 1
    assert conn.execute("SELECT COUNT(*) FROM window WHERE status = 'pending'").fetchone()[0] == 0
    assert len(commits) < janelas
    assert (saida / RAW_ITEMS_FILE_NAME).read_text(encoding="utf-8").strip()
    conn.close()


def test_revisao_nao_reenvia_janela_ja_revisada(tmp_path):
    jsonl = tmp_path / RAW_ITEMS_FILE_NAME
    linhas = [
        {"window": "g::000001-000003", "confidence": "low", "engine": "rules"},
        {"window": "g::000003-000005", "confidence": "low", "engine": "rules"},
        {"window": "g::000003-000005", "confidence": "high", "engine": "local"},
    ]
    jsonl.write_text("\n".join(json.dumps(l) for l in linhas), encoding="utf-8")
    assert _low_confidence_windows(jsonl) == {"g::000001-000003"}


# --- tela ---------------------------------------------------------------------------


def test_log_ao_vivo_so_acrescenta_resposta_200():
    modelo = Path(__file__).parent.parent / "gclaude_indexer" / "web" / "templates" / "run.html"
    texto = modelo.read_text(encoding="utf-8")
    assert '"HX-Request": "true"' in texto
    assert "response.status === 200" in texto


def test_resumo_de_qualidade_fica_em_cache_ate_algo_mudar(tmp_path, monkeypatch):
    from gclaude_indexer.web import app as app_mod

    _, _, config, conn = _projeto_com_paginas(tmp_path)
    chamadas = []
    original = app_mod.quality_summary
    monkeypatch.setattr(app_mod, "quality_summary", lambda c, cfg: chamadas.append(1) or original(c, cfg))
    app_mod._quality_cache.clear()
    app_mod._cached_quality_summary(1, conn, config)
    app_mod._cached_quality_summary(1, conn, config)
    assert len(chamadas) == 1
    prepare_windows(conn, config)
    conn.execute("UPDATE window SET status = 'done' WHERE id = (SELECT MIN(id) FROM window)")
    conn.commit()
    app_mod._cached_quality_summary(1, conn, config)
    assert len(chamadas) == 2
    conn.close()


def test_jsonl_com_u0085_no_texto_nao_vira_linha_corrompida(tmp_path):
    """Texto de HTML lido como latin-1 traz U+0085, que `json.dumps` não
    escapa e `splitlines()` tratava como fim de linha."""
    jsonl = tmp_path / RAW_ITEMS_FILE_NAME
    peca = {"window": "g::000001-000003", "confidence": "low", "engine": "rules", "summary": "a\x85b\u2028c"}
    jsonl.write_text(json.dumps(peca, ensure_ascii=False) + "\n", encoding="utf-8")
    assert _low_confidence_windows(jsonl) == {"g::000001-000003"}


def test_importacao_le_peca_com_u0085_inteira(tmp_path):
    from gclaude_indexer.import_items import import_and_consolidate

    _, saida, config, conn = _projeto_com_paginas(tmp_path, motor="rules")
    prepare_windows(conn, config)
    classify_rules(conn, config)
    jsonl = saida / RAW_ITEMS_FILE_NAME
    linhas = [json.loads(linha) for linha in jsonl.read_text(encoding="utf-8").split("\n") if linha.strip()]
    linhas[0]["summary"] = "antes\x85depois"
    jsonl.write_text("\n".join(json.dumps(l, ensure_ascii=False) for l in linhas) + "\n", encoding="utf-8")
    resultado = import_and_consolidate(conn, config, language="pt")
    assert resultado.invalid_lines == 0
    assert resultado.lines_read == len(linhas)
    conn.close()


def test_binario_de_extensao_desconhecida_nao_vira_texto(tmp_path):
    from gclaude_indexer.conversion import convert, converted_artifact_path
    from gclaude_indexer.scanning import scan

    from .test_phase4 import _preparar_projeto

    origem, saida, config, conn = _preparar_projeto(tmp_path, extra={"extensions": ["all"]})
    (origem / "fonte.ttf").write_bytes(b"\x00\x01\x00\x00\x00\x0fOS/2" + bytes(range(256)) * 4)
    (origem / "notas.cfg").write_text("chave = valor legível", encoding="utf-8")
    scan(conn, config)
    convert(conn, config)
    binario = converted_artifact_path(config.output_folder, "fonte.ttf", "ttf", False)
    texto = converted_artifact_path(config.output_folder, "notas.cfg", "cfg", False)
    assert binario.read_text(encoding="utf-8") == ""
    assert "valor legível" in texto.read_text(encoding="utf-8")
    conn.close()


# --- sensores: ventoinhas pela interface térmica da Dell -----------------------


def _firmware_g15(argumento):
    """Respostas medidas num Dell G15 5511 (31/10/2026)."""
    operacao, valor = argumento & 0xFF, (argumento >> 8) & 0xFF
    if operacao == 0x02:
        return 0x04000202  # 2 ventoinhas, 2 temperaturas
    if operacao == 0x03:
        return {0: 0x32, 1: 0x33, 2: 0x01, 3: 0x06}.get(valor, 0xFFFFFFFF)
    if operacao == 0x05:
        return {0x32: 2101, 0x33: 2387}.get(valor, 0xFFFFFFFF)
    if operacao == 0x04:
        return {0x01: 73, 0x06: 58}.get(valor, 0xFFFFFFFF)
    return 0xFFFFFFFF


def test_ventoinhas_e_temperaturas_do_dell_g15():
    from gclaude_indexer.dell_thermal import DellThermal

    leitura = DellThermal(invoke=_firmware_g15).read()
    assert leitura == {"cpu_fan_rpm": 2101, "gpu_fan_rpm": 2387, "cpu_temp_c": 73.0, "gpu_temp_c": 58.0}


def test_maquina_sem_a_interface_da_dell_nao_quebra_nem_insiste():
    from gclaude_indexer.dell_thermal import DellThermal

    chamadas = []

    def _ausente(argumento):
        chamadas.append(argumento)
        raise RuntimeError("Classe inválida")

    termica = DellThermal(invoke=_ausente)
    assert all(v is None for v in termica.read().values())
    assert all(v is None for v in termica.read().values())
    assert len(chamadas) == 1


def test_leitura_da_dell_so_preenche_o_que_a_biblioteca_deixou_vazio(monkeypatch):
    from gclaude_indexer import dell_thermal, sensors

    monkeypatch.setattr(sensors, "_is_admin", lambda: True)
    monkeypatch.setattr(dell_thermal, "read", lambda: {
        "cpu_fan_rpm": 2101, "gpu_fan_rpm": 2387, "cpu_temp_c": 73.0, "gpu_temp_c": 58.0,
    })
    biblioteca = {key: None for key in sensors.KEYS}
    biblioteca["gpu_temp_c"] = 61.0
    leitura = sensors._with_dell_thermal(biblioteca)
    assert leitura["gpu_temp_c"] == 61.0  # a biblioteca vence
    assert (leitura["cpu_temp_c"], leitura["cpu_fan_rpm"], leitura["gpu_fan_rpm"]) == (73.0, 2101, 2387)

    monkeypatch.setattr(sensors, "_is_admin", lambda: False)
    assert sensors._with_dell_thermal(biblioteca) == biblioteca


def test_instalador_oferece_o_pawnio_marcado():
    raiz = Path(__file__).parent.parent
    iss = (raiz / "installer" / "GClaudeIndexer.iss").read_text(encoding="utf-8-sig")
    assert "DepsChoicePage.Values[DEP_PAWNIO] := True;" in iss
    assert "' -SkipPawnIO'" in iss
    for idioma in ("brazilianportuguese", "english", "spanish"):
        assert f"{idioma}.DepPawnIO=" in iss
    script = (raiz / "install.ps1").read_text(encoding="utf-8-sig")
    assert "[switch]$SkipPawnIO" in script
    assert "winget install --id namazso.PawnIO -e --silent" in script
