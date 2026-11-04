# GClaude Indexer - document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""1.9.0: long operations in the background with Stop, the waiting panel,
the instructions screen, the graphics driver in About.

What the user reported: an update confirmed without the
instructions could not be stopped (the browser's Stop only dropped the
answer; the server went on, and the next click said "busy with: Update"),
the end of it never took them back to the Execution screen, the activity
bar was unreadable in the dark themes, a theme change in the middle lost
it, and About said "a recent driver is enough" instead of the driver.
"""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path

import pytest

from gclaude_indexer import db
from gclaude_indexer.i18n import translate
from gclaude_indexer.run_control import OperationCancelled
from gclaude_indexer.web import app as modulo_app


def _parar_sempre():
    return True


# --- Stop leaves the project as it was --------------------------------------

def test_parar_a_atualizacao_nao_muda_nada(tmp_path):
    from tests.test_phase17 import _pdf_de_paginas
    from tests.test_phase39 import _config_por_pasta, _pipeline

    from gclaude_indexer.invalidation import apply_update_plan
    from gclaude_indexer.update_plan import build_update_plan

    origem = tmp_path / "origem"
    (origem / "Atas").mkdir(parents=True)
    _pdf_de_paginas(origem / "Atas" / "ata.pdf", "ATA", 4)
    saida = tmp_path / "saida"
    saida.mkdir()
    config = _config_por_pasta(origem, saida)
    conn = db.connect(saida / "project.db")
    db.init_schema(conn)
    _pipeline(conn, config)
    (origem / "Atas" / "ata.pdf").unlink()
    _pdf_de_paginas(origem / "Atas" / "nova.pdf", "NOVA", 2)
    plano = build_update_plan(conn, config)
    antes = conn.execute("SELECT relative_path, status FROM file ORDER BY id").fetchall()

    with pytest.raises(OperationCancelled):
        apply_update_plan(conn, config, plano, should_stop=_parar_sempre)

    depois = conn.execute("SELECT relative_path, status FROM file ORDER BY id").fetchall()
    assert [tuple(r) for r in antes] == [tuple(r) for r in depois]
    conn.close()


def test_parar_no_meio_da_caminhada_nao_vira_remocao(tmp_path):
    """A walk cut short by Stop is a partial folder: never "the rest was removed"."""
    from tests.test_phase39 import _acervo, _config

    from gclaude_indexer.update_plan import detect_changes

    origem, saida, conn = _acervo(tmp_path)
    with pytest.raises(OperationCancelled):
        detect_changes(conn, _config(origem, saida), should_stop=_parar_sempre)


def test_parar_a_importacao_nao_apaga_as_pecas(tmp_path):
    from tests.test_phase39 import _acervo_de_uma_ata, _config_por_pasta, _pipeline

    from gclaude_indexer.import_items import import_and_consolidate

    origem, saida, conn = _acervo_de_uma_ata(tmp_path)
    config = _config_por_pasta(origem, saida)
    _pipeline(conn, config)
    antes = conn.execute("SELECT COUNT(*) FROM item").fetchone()[0]
    assert antes > 0

    with pytest.raises(OperationCancelled):
        import_and_consolidate(conn, config, should_stop=_parar_sempre)

    assert conn.execute("SELECT COUNT(*) FROM item").fetchone()[0] == antes
    conn.close()


def test_parar_a_geracao_entre_arquivos_avisa_e_nao_grava_o_estado(tmp_path):
    from tests.test_phase39 import _acervo_de_uma_ata, _config_por_pasta, _pipeline

    from gclaude_indexer.artifacts import generate_all_artifacts

    origem, saida, conn = _acervo_de_uma_ata(tmp_path)
    config = _config_por_pasta(origem, saida)
    _pipeline(conn, config)
    estados = conn.execute("SELECT COUNT(*) FROM artifact_state").fetchone()[0] if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name = 'artifact_state'").fetchone() else None
    chamadas = iter([False, True])

    with pytest.raises(OperationCancelled):
        generate_all_artifacts(conn, config, "pt", should_stop=lambda: next(chamadas, True))

    if estados is not None:
        assert conn.execute("SELECT COUNT(*) FROM artifact_state").fetchone()[0] == estados
    conn.close()


# --- the background runner --------------------------------------------------

def test_operacao_em_segundo_plano_aparece_e_para_pelo_botao(tmp_path, monkeypatch):
    from tests.test_phase32 import _app_com_projeto

    cliente, pid, _conn, _config = _app_com_projeto(tmp_path, monkeypatch)
    monkeypatch.setattr(modulo_app, "OPERATION_INLINE_WAIT_SECONDS", 0.0)
    comecou = threading.Event()

    def trabalho(should_stop):
        comecou.set()
        while not should_stop():
            time.sleep(0.01)
        raise OperationCancelled()

    operacao = modulo_app._start_operation(pid, "update.confirm", trabalho, f"/projects/{pid}/run")
    assert operacao is not None and comecou.wait(5)
    # A second operation of the same project is refused while it runs.
    assert modulo_app._start_operation(pid, "run.import_and_generate", trabalho, "/") is None

    vistas = cliente.get("/activity").json()["operations"]
    assert [v["status"] for v in vistas if v["project_id"] == pid] == ["running"]
    assert vistas[0]["operation"] == translate("pt", "update.confirm")

    assert cliente.post(f"/projects/{pid}/operation/stop").json() == {"stopping": True}
    for _ in range(500):
        if operacao.status != "running":
            break
        time.sleep(0.01)
    assert operacao.status == "stopped"
    assert pid not in modulo_app._IMPORTS_IN_PROGRESS, "o projeto fica livre de novo"
    vista = [v for v in cliente.get("/activity").json()["operations"] if v["project_id"] == pid][0]
    assert vista["message"] == translate("pt", "activity.stopped")


def test_o_pedido_que_comeca_manda_para_a_tela_com_o_numero_da_operacao(tmp_path, monkeypatch):
    from tests.test_phase32 import _app_com_projeto

    cliente, pid, _conn, _config = _app_com_projeto(tmp_path, monkeypatch)
    monkeypatch.setattr(modulo_app, "OPERATION_INLINE_WAIT_SECONDS", 0.0)
    liberar = threading.Event()

    def demorado(conn, config, language=None, should_stop=None):
        liberar.wait(5)

    monkeypatch.setattr(modulo_app, "import_and_consolidate", demorado)
    monkeypatch.setattr(modulo_app, "generate_all_artifacts", lambda *a, **k: {})
    resposta = cliente.post(
        f"/projects/{pid}/import-and-generate", follow_redirects=False,
        headers={"referer": f"http://127.0.0.1:8000/projects/{pid}/result"},
    )
    liberar.set()

    assert resposta.status_code == 303
    assert re.fullmatch(rf"/projects/{pid}/result\?op=\d+", resposta.headers["location"])


def test_quem_termina_rapido_vai_direto_ao_resultado(tmp_path, monkeypatch):
    from tests.test_phase32 import _app_com_projeto

    cliente, pid, _conn, _config = _app_com_projeto(tmp_path, monkeypatch)
    monkeypatch.setattr(modulo_app, "import_and_consolidate", lambda *a, **k: None)
    monkeypatch.setattr(modulo_app, "generate_all_artifacts", lambda *a, **k: {})

    resposta = cliente.post(f"/projects/{pid}/import-and-generate", follow_redirects=False)

    assert resposta.status_code == 303
    assert resposta.headers["location"] == f"/projects/{pid}/result"


def test_o_aviso_de_atualizacao_fica_quieto_enquanto_uma_operacao_roda(tmp_path, monkeypatch):
    from tests.test_phase32 import _app_com_projeto

    cliente, pid, _conn, _config = _app_com_projeto(tmp_path, monkeypatch)
    with modulo_app._generation_slot(pid, "update.confirm"):
        assert cliente.get(f"/projects/{pid}/update/banner").text == ""


def test_painel_de_espera_e_legivel_em_todos_os_temas():
    """The old bar used `--color-accent-bg`, which no theme defines, so it
    fell back to the warning yellow while the text took the accent's white.
    The panel uses only the theme's own surface and text pair."""
    css = (Path(modulo_app.__file__).parent / "static" / "style.css").read_text(encoding="utf-8")
    painel = css[css.index(".wait-card {"):]
    painel = painel[:painel.index("}")]
    assert "var(--color-surface)" in painel and "var(--color-text)" in painel
    assert "--color-accent-bg" not in css


def test_tema_muda_sem_recarregar_a_pagina(tmp_path, monkeypatch):
    from tests.test_phase32 import _app_com_projeto

    cliente, _pid, _conn, _config = _app_com_projeto(tmp_path, monkeypatch)
    resposta = cliente.post(
        "/preferences/theme", data={"theme": "dark"}, headers={"x-preference-fetch": "1"},
        follow_redirects=False,
    )
    assert resposta.status_code == 204
    assert "theme=dark" in resposta.headers["set-cookie"]


# --- instructions screen ----------------------------------------------------

def test_tela_de_instrucoes_mostra_edita_e_guarda_a_anterior(tmp_path, monkeypatch):
    from tests.test_phase32 import _app_com_projeto
    from tests.test_phase39 import _arquivo_com_bloco

    from gclaude_indexer.managed_block import user_part

    cliente, pid, _conn, config = _app_com_projeto(tmp_path, monkeypatch)
    saida = Path(config.output_folder)
    _arquivo_com_bloco(saida)

    tela = cliente.get(f"/projects/{pid}/instructions")
    assert tela.status_code == 200
    assert "Antigas" in tela.text
    assert translate("pt", "instructions.generated_title") in tela.text

    resposta = cliente.post(f"/projects/{pid}/instructions", data={"user_instructions": "# Minhas regras\n\nNovas."})
    assert resposta.status_code == 200
    assert user_part(saida / "project_instructions.md") == "# Minhas regras\n\nNovas."
    assert len(list(saida.glob("project_instructions.md.*.bak"))) == 1

    igual = cliente.post(f"/projects/{pid}/instructions", data={"user_instructions": "# Minhas regras\n\nNovas."})
    assert translate("pt", "instructions.unchanged") in igual.text
    assert len(list(saida.glob("project_instructions.md.*.bak"))) == 1


def test_execucao_e_resultado_levam_as_instrucoes(tmp_path, monkeypatch):
    from tests.test_phase32 import _app_com_projeto

    cliente, pid, _conn, _config = _app_com_projeto(tmp_path, monkeypatch)
    for tela in ("run", "result"):
        assert f'href="/projects/{pid}/instructions"' in cliente.get(f"/projects/{pid}/{tela}").text, tela


# --- driver in About --------------------------------------------------------

def test_numero_da_nvidia_a_partir_do_numero_do_windows():
    from gclaude_indexer.hardware import nvidia_version_from_wddm

    assert nvidia_version_from_wddm("32.0.15.6094") == "560.94"
    assert nvidia_version_from_wddm("32.0.16.2101") == "621.01"
    assert nvidia_version_from_wddm("abc") == ""


def test_sobre_mostra_versao_e_data_do_driver(monkeypatch):
    from gclaude_indexer import install_diagnostics
    from gclaude_indexer.hardware import GpuDriver, GpuInfo

    monkeypatch.setattr(install_diagnostics, "_detect_gpu_for_diagnostics", lambda: GpuInfo("RTX X", "NVIDIA", 6144))
    monkeypatch.setattr(install_diagnostics, "gpu_driver", lambda name: GpuDriver("32.0.16.2101", "2026-10-18", "621.01"))

    pt = install_diagnostics._diagnose_gpu_runtime("pt")["version"]
    en = install_diagnostics._diagnose_gpu_runtime("en")["version"]
    assert pt == "RTX X: driver 621.01 (32.0.16.2101), publicado em 18/10/2026"
    assert "2026-10-18" in en and "621.01" in en


def test_sem_leitura_do_driver_volta_ao_texto_generico(monkeypatch):
    from gclaude_indexer import install_diagnostics
    from gclaude_indexer.hardware import GpuInfo

    monkeypatch.setattr(install_diagnostics, "_detect_gpu_for_diagnostics", lambda: GpuInfo("RX Y", "AMD", 12288))
    monkeypatch.setattr(install_diagnostics, "gpu_driver", lambda name: None)
    assert install_diagnostics._diagnose_gpu_runtime("pt")["version"] == translate(
        "pt", "diagnostics.gpu_runtime.driver_sufficient", name="RX Y"
    )


# --- texts ------------------------------------------------------------------

def test_chaves_novas_nos_tres_idiomas():
    from gclaude_indexer.i18n import _TRANSLATIONS

    chaves = [
        "activity.stop", "activity.open", "activity.ok", "activity.loading", "activity.loading_hint",
        "activity.hint", "activity.stopping", "activity.done_title", "activity.stopped_title",
        "activity.failed_title", "activity.stopped", "activity.failed",
        "instructions.title", "instructions.intro", "instructions.help", "instructions.label",
        "instructions.save", "instructions.saved", "instructions.unchanged",
        "instructions.generated_title", "instructions.no_file", "instructions.button",
        "diagnostics.gpu_runtime.driver_installed", "diagnostics.gpu_runtime.driver_installed_no_date",
    ]
    for idioma in ("pt", "en", "es"):
        for chave in chaves:
            assert chave in _TRANSLATIONS[idioma], (idioma, chave)


_TEMPLATES = Path(modulo_app.__file__).parent / "templates"
_COMENTARIOS = re.compile(r"(?ms)\{#.*?#\}|<!--.*?-->|/\*.*?\*/|^[ \t]*//[^\n]*$")


def test_nenhuma_tela_mostra_travessao():
    """The person asked for no em dash on screen (at most a hyphen)."""
    for caminho in _TEMPLATES.rglob("*.html"):
        visivel = _COMENTARIOS.sub("", caminho.read_text(encoding="utf-8"))
        assert "—" not in visivel, caminho.name


def test_nenhum_texto_da_interface_tem_travessao():
    from gclaude_indexer.i18n import _TRANSLATIONS

    for idioma, textos in _TRANSLATIONS.items():
        for chave, texto in textos.items():
            if chave.startswith(("artifact.index.", "artifact.timeline.")):
                continue  # data tables of the generated files, not screens
            assert "—" not in texto, (idioma, chave)


# --- performance (strategy chosen for projects with many files) -------------

def test_caminho_relativo_rapido_e_igual_ao_do_pathlib(tmp_path):
    from gclaude_indexer.scanning import relative_text

    raiz = tmp_path / "Acervo Ação"
    for rel in ("a.pdf", "Sub/b.PDF", "Sub/Mais Fundo/c d.docx", "ç/é.txt"):
        alvo = raiz / rel
        alvo.parent.mkdir(parents=True, exist_ok=True)
        alvo.write_text("x", encoding="utf-8")
    for caminho in raiz.rglob("*"):
        assert relative_text(caminho, raiz) == str(caminho.relative_to(raiz))
    assert relative_text(Path("C:/a/b"), Path("C:/")) == str(Path("C:/a/b").relative_to(Path("C:/")))


def test_tela_parada_reaproveita_a_resposta_e_renova_quando_algo_comeca(tmp_path, monkeypatch):
    from tests.test_phase32 import _app_com_projeto

    cliente, pid, _conn, _config = _app_com_projeto(tmp_path, monkeypatch)
    monkeypatch.setattr(modulo_app, "IDLE_FRAGMENT_SECONDS", 30.0)
    chamadas = []
    original = modulo_app._steps_context

    def contando(*args, **kwargs):
        chamadas.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(modulo_app, "_steps_context", contando)
    for _ in range(3):
        assert cliente.get(f"/projects/{pid}/run/steps").status_code == 200
    assert len(chamadas) == 1, "parado, o banco não é lido de novo a cada 2 s"

    with modulo_app._generation_slot(pid, "update.confirm"):
        cliente.get(f"/projects/{pid}/run/steps")
        cliente.get(f"/projects/{pid}/run/steps")
    assert len(chamadas) == 3, "com algo rodando, cada pergunta lê o banco"


def test_resultado_nao_recalcula_a_qualidade_sem_mudanca(tmp_path, monkeypatch):
    from tests.test_phase32 import _app_com_projeto

    cliente, pid, _conn, _config = _app_com_projeto(tmp_path, monkeypatch)
    chamadas = []
    original = modulo_app.quality_summary

    def contando(*args, **kwargs):
        chamadas.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(modulo_app, "quality_summary", contando)
    assert cliente.get(f"/projects/{pid}/result").status_code == 200
    assert cliente.get(f"/projects/{pid}/result").status_code == 200
    assert len(chamadas) == 1


def test_tamanho_dos_intermediarios_com_a_listagem(tmp_path, monkeypatch):
    from gclaude_indexer import cleanup

    pasta = tmp_path / "converted"
    (pasta / "sub").mkdir(parents=True)
    (pasta / "a.pdf").write_bytes(b"x" * 10)
    (pasta / "sub" / "b.pdf").write_bytes(b"y" * 5)
    monkeypatch.setattr(cleanup, "_target_folders", lambda _saida: [pasta, tmp_path / "nao-existe"])
    assert cleanup.intermediates_size(str(tmp_path)) == 15


def test_arquivo_com_a_marca_antiga_continua_com_um_bloco_so(tmp_path):
    """1.9.0 trocou o travessão da marca do bloco por um ponto. Os arquivos
    já gravados têm a marca antiga: a geração nova substitui o bloco, nunca
    acrescenta um segundo embaixo das instruções do usuário."""
    from gclaude_indexer.managed_block import END_MARK, user_part, write_managed

    marca_antiga = (
        "<!-- GCLAUDE-INDEXER:BEGIN \u00b7 gerado automaticamente / auto-generated / "
        "generado autom\u00e1ticamente \u2014 edite fora deste bloco / edit outside this block / "
        "edite fuera de este bloque -->"
    )
    arquivo = tmp_path / "project_instructions.md"
    arquivo.write_text(f"# Minhas regras\n\nCite a folha.\n\n{marca_antiga}\nvelho\n{END_MARK}\n", encoding="utf-8")

    write_managed(arquivo, "novo")

    texto = arquivo.read_text(encoding="utf-8")
    assert texto.count("GCLAUDE-INDEXER:BEGIN") == 1
    assert "velho" not in texto and "novo" in texto
    assert user_part(arquivo) == "# Minhas regras\n\nCite a folha."
