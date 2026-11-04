# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""1.5.9: o que travou ou se repetiu à toa em produção.

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


def test_extracao_sem_nada_novo_ainda_indexa_a_busca(tmp_path):
    """1.5.12: com todos os arquivos já extraídos, a etapa se dava por
    pausada (o ponteiro de cada grupo nunca andava) e pulava a busca —
    em produção, dezenas de milhares de arquivos ficavam sem indexar e a
    etapa, pendente."""
    from gclaude_indexer.extraction import extract_pages

    _, config, conn = _tres_notas(tmp_path)
    conn.execute("DELETE FROM fulltext")
    conn.execute("DELETE FROM fulltext_file")
    conn.commit()
    extract_pages(conn, config)
    assert coverage(conn) == (3, 3)
    pausas = conn.execute(
        "SELECT COUNT(*) FROM event WHERE step = 'extraction' AND message LIKE '%pausad%'"
    ).fetchone()[0]
    assert pausas == 0
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


def _firmware_dell(argumento):
    """Respostas típicas de um notebook Dell da linha G."""
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


def test_ventoinhas_e_temperaturas_do_dell():
    from gclaude_indexer.dell_thermal import DellThermal

    leitura = DellThermal(invoke=_firmware_dell).read()
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


def test_interface_da_dell_que_ainda_nao_subiu_e_tentada_de_novo():
    """Logo depois de reiniciar, o leitor elevado sobe antes do serviço da
    Dell; a primeira falha não pode deixar as ventoinhas vazias a sessão
    inteira."""
    from gclaude_indexer import dell_thermal
    from gclaude_indexer.dell_thermal import DellThermal

    agora = [0.0]
    pronto = [False]

    def _firmware(argumento):
        if not pronto[0]:
            raise RuntimeError("provedor WMI ainda não respondeu")
        return _firmware_dell(argumento)

    termica = DellThermal(invoke=_firmware, clock=lambda: agora[0])
    assert termica.read()["cpu_fan_rpm"] is None
    pronto[0] = True
    assert termica.read()["cpu_fan_rpm"] is None  # ainda no intervalo
    agora[0] += dell_thermal._RETRY_SECONDS + 1
    assert termica.read()["cpu_fan_rpm"] == 2101


def test_maquina_sem_a_interface_desiste_depois_de_algumas_tentativas():
    from gclaude_indexer import dell_thermal
    from gclaude_indexer.dell_thermal import DellThermal

    agora = [0.0]
    chamadas = []

    def _ausente(argumento):
        chamadas.append(argumento)
        raise RuntimeError("Classe inválida")

    termica = DellThermal(invoke=_ausente, clock=lambda: agora[0])
    for _ in range(dell_thermal._MAX_FAILURES + 5):
        termica.read()
        agora[0] += dell_thermal._RETRY_SECONDS + 1
    assert len(chamadas) == dell_thermal._MAX_FAILURES


def test_classificacao_lenta_mostra_estimativa_depois_de_poucas_janelas():
    """1.5.12: 11 mil janelas a ~40 s cada; antes a estimativa só aparecia
    depois de 0,5% (55 janelas, 37 minutos)."""
    from gclaude_indexer.web.eta import ProgressEstimator

    def _simula(**kwargs):
        estimador = ProgressEstimator(started_at=0.0)
        resposta = None
        for passo in range(0, 101):  # leitura a cada 2 s, 200 s
            agora = passo * 2.0
            feitas = int(agora // 40)
            resposta = estimador.observe(float(feitas), 10962.0, now=agora, **kwargs)
        return resposta

    eta = _simula(counted_in_items=True)
    assert eta is not None and 300_000 < eta < 600_000  # ~5 dias
    assert _simula() is None  # em bytes, a fração mínima continua valendo


def test_servidor_do_ollama_religado_grava_a_saida_num_log(tmp_path):
    import sys

    from gclaude_indexer.subprocess_utils import start_in_background

    log = tmp_path / "sub" / "serve.log"
    processo = start_in_background([sys.executable, "-c", "print('subiu')"], log_path=log)
    processo.wait(timeout=30)
    assert "subiu" in log.read_text(encoding="utf-8", errors="replace")


def test_tempo_limite_da_geracao_cobre_janela_pesada_em_placa_quente():
    from gclaude_indexer import engine_local

    assert engine_local.GENERATION_TIMEOUT_S >= 300


# --- 1.5.12: com placa de vídeo, nunca o motor Regras ---------------------


def _classificacao_com_motor(tmp_path, monkeypatch, motor, com_placa):
    from gclaude_indexer import engine_local
    from gclaude_indexer.engine_local import classify_pending

    from .test_phase8 import TEXTO_LONGO_SEM_MARCADOR, _projeto_pronto_para_classificar

    config, conn = _projeto_pronto_para_classificar(
        tmp_path, [TEXTO_LONGO_SEM_MARCADOR] * 40, pages_per_window=8, overlap=0
    )
    monkeypatch.setattr(engine_local, "_has_dedicated_gpu", lambda: com_placa)
    monkeypatch.setattr(engine_local, "MODEL_RETRY_SECONDS", 0.0)
    monkeypatch.setattr(engine_local, "_try_restart_ollama", lambda *a, **k: motor.no_ar())
    resultado = classify_pending(conn, config, local_engine=motor)
    linhas = [
        json.loads(l)
        for l in (Path(config.output_folder) / RAW_ITEMS_FILE_NAME).read_text(encoding="utf-8").split("\n")
        if l.strip()
    ]
    return config, conn, resultado, linhas


class _MotorQueCai:
    """Responde, cai em `quedas` chamadas a partir da segunda janela e volta."""

    def __init__(self, quedas):
        self.quedas = quedas
        self.chamadas = 0
        self.fora = False
        self.url_base = "fake"
        self.gpu_plan = None
        self.last_window_warnings = []
        self.last_rejections = []

    def no_ar(self):
        # Cada consulta durante a queda gasta uma; quando acabam, voltou.
        if self.fora and self.quedas > 0:
            self.quedas -= 1
            return False
        self.fora = False
        return True

    def is_available(self):
        return self.no_ar()

    def classify(self, paginas):
        from gclaude_indexer.classification import ClassifiedItem
        from gclaude_indexer.engine_local import OllamaConnectionError

        self.chamadas += 1
        if self.chamadas >= 2 and self.quedas > 0:
            self.quedas -= 1
            self.fora = True
            raise OllamaConnectionError("caiu")
        primeira, ultima = paginas[0], paginas[-1]
        return [ClassifiedItem(
            start_ref=primeira.reference, end_ref=ultima.reference, start_order=primeira.order, end_order=ultima.order,
            type="OFÍCIO", date=None, author=None, summary="pelo modelo", has_table=False, has_image=False,
            engine="local", confidence="high", files=sorted({p.file_name for p in paginas}),
        )]


def test_com_placa_de_video_espera_o_modelo_e_nunca_usa_regras(tmp_path, monkeypatch):
    _, conn, resultado, linhas = _classificacao_com_motor(tmp_path, monkeypatch, _MotorQueCai(4), True)
    assert resultado.windows_via_rules_fallback == 0
    assert linhas and {l["engine"] for l in linhas} == {"local"}
    assert conn.execute("SELECT COUNT(*) FROM window WHERE status = 'pending'").fetchone()[0] == 0
    conn.close()


def test_sem_placa_cai_em_regras_marcado_e_volta_ao_modelo_depois(tmp_path, monkeypatch):
    from gclaude_indexer.engine_local import classify_pending

    config, conn, resultado, linhas = _classificacao_com_motor(tmp_path, monkeypatch, _MotorQueCai(50), False)
    assert resultado.windows_via_rules_fallback > 0
    assert all(l.get("fallback") for l in linhas if l["engine"] == "rules")

    segunda = classify_pending(conn, config, local_engine=_MotorQueCai(0))
    assert segunda.windows_via_rules_fallback == 0
    linhas = [
        json.loads(l)
        for l in (Path(config.output_folder) / RAW_ITEMS_FILE_NAME).read_text(encoding="utf-8").split("\n")
        if l.strip()
    ]
    assert {l["engine"] for l in linhas} == {"local"}
    conn.close()


def test_copia_do_leitor_elevado_leva_todo_modulo_que_ele_importa():
    """1.5.13: `dell_thermal.py` ficou fora da cópia e as ventoinhas nunca
    apareceram na máquina instalada (nos testes o pacote inteiro existe)."""
    import re

    from gclaude_indexer import sensor_service

    pacote = Path(sensor_service.__file__).resolve().parent
    precisa = set()
    for modulo in ("sensors.py", "sensor_service.py", "paths.py", "dell_thermal.py"):
        texto = (pacote / modulo).read_text(encoding="utf-8")
        precisa |= {m + ".py" for m in re.findall(r"from \. import (\w+)", texto)}
        precisa |= {m + ".py" for m in re.findall(r"from \.(\w+) import", texto)}
    assert precisa <= set(sensor_service.HELPER_MODULES)


# --- 1.5.14: legislação do Planalto lida pela estrutura -------------------

_DECRETO_REVOGADO = """Presidência da República
Casa Civil
Subchefia para Assuntos Jurídicos
DECRETO Nº 93.618, DE 24 DE NOVEMBRO DE 1986.
Revogado pelo Decreto de 15.2.1991
Texto para impressão |
~~Autoriza o aumento de capital da LIGHT - Serviços de Eletricidade S. A.~~
~~O PRESIDENTE DA REPÚBLICA , no uso da atribuição que lhe confere o artigo 81, item III, da Constituição,~~
~~DECRETA:~~
~~Art. 1º. Fica a LIGHT autorizada a promover a elevação de seu capital social.~~
~~Brasília, 24 de novembro de 1986; 165º da Independência e 98º da República.~~
~~JOSÉ SARNEY~~
~~Aureliano Chaves~~
~~Este texto não substitui o publicado no DOU de 26.11.1986~~"""

_DECRETO_ANTIGO = """###DEC-074403-0-000-13-08-1974@@@
DECRETO Nº 74.403 - DE 13 DE AGOSTO DE 1974.
Concede à Ferro de Belo Horizonte S.A. - FERROBEL o direito de lavrar minério de ferro.
O PRESIDENTE DA REPÚBLICA, usando da atribuição que lhe confere o artigo 81, item III, da Constituição,
DECRETA:
Art. 1º Fica concedido o direito de lavrar.
Brasília, 13 de agosto de 1974; 153º da Independência e 86º da República.
ERNESTO GEISEL
Shigeaki Ueki"""

_MP_REEDITADA = """Presidência da República
Casa Civil
MEDIDA PROVISÓRIA Nº 1.478-18, DE 22 DE NOVEMBRO DE 1996.
Reeditada pela MPv nº 1.478-19 de 1996
Dá nova redação aos arts. 9º da Lei nº 8.036, de 11 de maio de 1990.
O PRESIDENTE DA REPÚBLICA, no uso da atribuição que lhe confere o art. 62 da Constituição,
adota a seguinte Medida Provisória, com força de lei:
Art. 1º Texto."""

_CITACAO_SOLTA = """Ata da reunião de diretoria
LEI Nº 8.666, DE 21 DE JUNHO DE 1993.
Foi discutida a aplicação da lei citada acima nas compras do conselho."""


def test_leitor_do_planalto_extrai_tipo_numero_data_autor_e_ementa():
    from gclaude_indexer import planalto

    ato = planalto.parse(_DECRETO_REVOGADO)
    assert ato["type"] == "DECRETO" and ato["number"] == "93.618" and ato["date"] == "1986-11-24"
    assert ato["author"] == "José Sarney"  # 1.5.17: uma grafia só
    assert ato["summary"].startswith("DECRETO Nº 93.618: Autoriza o aumento de capital da LIGHT")
    assert "Revogado pelo Decreto de 15.2.1991" in ato["summary"]

    antigo = planalto.parse(_DECRETO_ANTIGO)
    assert antigo["number"] == "74.403" and antigo["date"] == "1974-08-13"
    assert antigo["author"] == "Ernesto Geisel"

    mp = planalto.parse(_MP_REEDITADA)
    assert mp["type"] == "MEDIDA PROVISÓRIA" and mp["number"] == "1.478-18"
    assert "Reeditada" not in mp["summary"] and "Dá nova redação" in mp["summary"]


def test_titulo_citado_em_outro_documento_nao_vira_ato():
    from gclaude_indexer import planalto

    assert planalto.parse(_CITACAO_SOLTA) is None


def test_janela_mista_manda_ao_modelo_so_o_que_nao_e_do_planalto():
    from gclaude_indexer import planalto
    from gclaude_indexer.classification import WindowPage

    paginas = [
        WindowPage("p. 1", "d93618.htm", _DECRETO_REVOGADO, False, 0, order=1),
        WindowPage("p. 2", "ata.pdf", _CITACAO_SOLTA, False, 0, order=2),
        WindowPage("p. 3", "d74403.htm", _DECRETO_ANTIGO, False, 0, order=3),
    ]
    itens, resto = planalto.split(paginas)
    assert [i.files for i in itens] == [["d93618.htm"], ["d74403.htm"]]
    assert all(i.engine == "structured" for i in itens)
    assert [p.file_name for p in resto] == ["ata.pdf"]


def test_janela_so_de_legislacao_nao_espera_o_modelo(tmp_path, monkeypatch):
    """Com o Ollama fora do ar e placa de vídeo, uma janela só de atos do
    Planalto termina mesmo assim, sem chamar o modelo."""
    from gclaude_indexer import engine_local
    from gclaude_indexer.engine_local import classify_pending

    from .test_phase8 import _projeto_pronto_para_classificar

    origem = tmp_path / "origem"
    config, conn = _projeto_pronto_para_classificar(tmp_path, ["Página de teste com texto suficiente para não acionar OCR aqui."])
    conn.execute("UPDATE page SET text = ?", (_DECRETO_ANTIGO,))
    conn.execute("UPDATE file SET name = 'd74403.htm', relative_path = 'volume_1/d74403.htm'")
    conn.commit()

    class _MotorQueNuncaResponde(_MotorQueCai):
        def is_available(self):
            return False

        def classify(self, paginas):
            raise AssertionError("o modelo não devia ser chamado")

    monkeypatch.setattr(engine_local, "_has_dedicated_gpu", lambda: True)
    monkeypatch.setattr(engine_local, "_try_restart_ollama", lambda *a, **k: False)
    resultado = classify_pending(conn, config, local_engine=_MotorQueNuncaResponde(0))
    assert resultado.windows_processed == 1 and resultado.windows_via_rules_fallback == 0
    linhas = [json.loads(l) for l in (Path(config.output_folder) / RAW_ITEMS_FILE_NAME).read_text(encoding="utf-8").split("\n") if l.strip()]
    assert {l["engine"] for l in linhas} == {"structured"}
    conn.close()


def test_modelo_automatico_segue_a_vram(monkeypatch):
    """1.5.14: placa de 8 GB ou mais usa qwen3.5:9b; 6 GB ou menos, qwen3.5:4b."""
    from gclaude_indexer import engine_local

    assert engine_local.recommended_local_model(6144) == "qwen3.5:4b"
    assert engine_local.recommended_local_model(0) == "qwen3.5:4b"
    assert engine_local.recommended_local_model(8188) == "qwen3.5:9b"
    assert engine_local.recommended_local_model(12288) == "qwen3.5:9b"
    from gclaude_indexer.config import ProjectConfig

    monkeypatch.setattr(engine_local, "gpu_vram_mb", lambda: 8192)
    import gclaude_indexer.web.ollama_models as om

    monkeypatch.setattr(om, "model_downloaded_on_disk", lambda name: True)
    assert engine_local.model_to_use(None, ProjectConfig(name="x", source_folder=".", output_folder=".")) == "qwen3.5:9b"
    # máquina atualizada que ainda não baixou o 9B: fica no 4B que já tem
    monkeypatch.setattr(om, "model_downloaded_on_disk", lambda name: name == "qwen3.5:4b")
    assert engine_local.model_to_use(None, ProjectConfig(name="x", source_folder=".", output_folder=".")) == "qwen3.5:4b"
    monkeypatch.setattr(engine_local, "gpu_vram_mb", lambda: 6144)
    assert engine_local.model_to_use(None, ProjectConfig(name="x", source_folder=".", output_folder=".")) == "qwen3.5:4b"


def test_pagina_binaria_antiga_vira_pagina_vazia():
    """1.5.15: bytes de .zip gravados como texto antes da 1.5.9 não chegam ao modelo."""
    from gclaude_indexer.classification import readable_text

    assert readable_text("PK\x03\x04\x14\x00\x08") == ""
    assert readable_text("texto normal") == "texto normal"
    assert readable_text(None) == ""


def test_resposta_recusada_divide_a_janela(monkeypatch):
    """1.5.15: "token repeat limit reached" isola a página ruim em vez de
    deixar o trecho pendente para sempre."""
    from gclaude_indexer import engine_local
    from gclaude_indexer.classification import ClassifiedItem, WindowPage

    pages = [WindowPage(reference=f"f. {i}", file_name="a.pdf", text="ruim" if i == 3 else "ok",
                        has_table=False, image_count=0, order=i) for i in range(1, 7)]

    class Motor:
        def classify(self, ps):
            if any(p.text == "ruim" for p in ps):
                raise engine_local.ModelAnswerError("prediction aborted, token repeat limit reached")
            return [ClassifiedItem(start_ref=p.reference, end_ref=p.reference, start_order=p.order,
                                   end_order=p.order, type="Ofício", date=None, author=None,
                                   summary="x", has_table=False, has_image=False, engine="local", confidence="high", files=[p.file_name])
                    for p in ps]

    items = engine_local._classify_in_parts(Motor(), pages)
    assert sorted(i.start_order for i in items) == [1, 2, 4, 5, 6]


def test_erro_500_com_corpo_do_ollama_e_recusa_nao_queda(monkeypatch):
    import io
    import urllib.error
    from gclaude_indexer import engine_local

    def falha(*a, **k):
        raise urllib.error.HTTPError("http://x", 500, "Internal", {},
                                     io.BytesIO(b'{"error":"prediction aborted, token repeat limit reached"}'))

    monkeypatch.setattr(engine_local.urllib.request, "urlopen", falha)
    e = engine_local.LocalEngine(model="qwen3.5:4b")
    import pytest

    with pytest.raises(engine_local.ModelAnswerError):
        e._generate("x")


def test_planalto_formatos_da_1_5_16():
    """Portarias, datas sem "de" entre dia e mês, "(*)" antes do título e
    atos do Império confirmados pelo cabeçalho do site."""
    from gclaude_indexer import planalto

    portaria = planalto.parse(
        "MINISTÉRIO DA SAÚDE\nGABINETE DO MINISTRO\nPORTARIA Nº 561, DE 26 DE MARÇO DE 2020\n"
        "Autoriza a utilização de leitos.\n"
        "O MINISTRO DE ESTADO DA SAÚDE, no uso das atribuições que lhe conferem o art. 87, resolve:\nArt. 1º …"
    )
    assert portaria["type"] == "PORTARIA" and portaria["number"] == "561" and portaria["date"] == "2020-03-26"
    assert portaria["summary"] == "PORTARIA Nº 561: Autoriza a utilização de leitos."

    antigo = planalto.parse(
        "###DEC-024388-0-000-23-01-1948@@@\nDECRETO Nº 24.388, De 23 janeiro DE 1948.\n"
        "Autoriza o cidadão a comprar pedras preciosas.\nO PRESIDENTE DA REPÚBLICA, usando da atribuição,\ndecreta:"
    )
    assert antigo["date"] == "1948-01-23"

    nota = planalto.parse(
        "###DEC-054213-0-000-26-08-1964@@@\n(*) DECRETO Nº 54.213, DE 26 DE AGÔSTO DE 1964.\n"
        "Classifica os cargos.\nO PRESIDENTE DA REPÚBLICA, usando das atribuições,"
    )
    assert nota["number"] == "54.213" and nota["date"] == "1964-08-26"

    imperio = planalto.parse(
        "Presidência da República\nCasa Civil\nSubchefia para Assuntos Jurídicos\n"
        "ALVARÁ de 04 de MAIO de 1808\nCrêa nesta cidade o logar de Juiz Conservador.\nNão remover\n- Down\n"
        "Eu o Principe Regente faço saber aos que este alvará virem…"
    )
    assert imperio["type"] == "ALVARÁ" and imperio["date"] == "1808-05-04"
    assert imperio["summary"] == "ALVARÁ: Crêa nesta cidade o logar de Juiz Conservador."

    # Sem cabeçalho, sem promulgação e sem fecho: uma citação, não o ato.
    assert planalto.parse("Conforme a\nPORTARIA Nº 5, DE 1º DE ABRIL DE 2020\nque trata do assunto.") is None
