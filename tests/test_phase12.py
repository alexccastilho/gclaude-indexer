"""Phase 12 tests: interface fixes (spec section 6)."""

from __future__ import annotations

import time
from pathlib import Path

import fitz
import pytest
from fastapi.testclient import TestClient

import gclaude_indexer.catalog as catalogo_mod
import gclaude_indexer.hardware as hardware_mod
from gclaude_indexer.web.app import app, _format_time
from gclaude_indexer.web.background_runs import task_manager


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    pasta_local = tmp_path / "local_maquina"
    monkeypatch.setattr(catalogo_mod, "machine_local_folder", lambda: pasta_local)
    monkeypatch.setattr(hardware_mod, "machine_local_folder", lambda: pasta_local)
    return TestClient(app)


@pytest.fixture(autouse=True)
def limpar_gerenciador():
    """Limpa as tarefas do gerenciador antes e depois de cada teste, para não
    depender da ordem de coleta do pytest (limpar só depois deixaria o
    primeiro teste de uma sessão exposto a lixo de uma execução anterior)."""
    task_manager._tasks.clear()
    yield
    task_manager._tasks.clear()


def _pdf(caminho, texto):
    documento = fitz.open()
    pagina = documento.new_page()
    pagina.insert_textbox((50, 50, 550, 750), texto, fontsize=12)
    documento.save(caminho)
    documento.close()


def _criar_projeto(cliente, tmp_path, nome="Projeto fase 12", **campos_extra):
    origem = tmp_path / "origem" / nome.replace(" ", "_")
    (origem / "volume_1").mkdir(parents=True)
    saida = tmp_path / f"{nome.replace(' ', '_')}_indexado"
    _pdf(
        origem / "volume_1" / "peca.pdf",
        "OFÍCIO No 1\nAssunto: teste da fase 12, com texto suficiente para não acionar OCR.\n10/01/2024",
    )
    dados = {
        "name": nome, "subject": "Acervo de teste", "source_folder": str(origem), "output_folder": str(saida),
        "collection_type": "processo", "group_mode": "subfolder", "group_pattern": "",
        "extensions": ["pdf", "docx", "imagens"], "pages_per_block": "80", "pages_per_window": "16",
        "overlap": "2", "chars_per_page": "2000", "ocr_language": "por",
        "classification_engine": "rules", "local_model": "automatic", "role_instructions": "", "extra_rules": "",
    }
    dados.update(campos_extra)
    resposta = cliente.post("/projects/new", data=dados, follow_redirects=False)
    assert resposta.status_code == 303, resposta.text
    return int(resposta.headers["location"].split("/")[2])


def _esperar_etapa_terminar(projeto_id: int, etapa: str, timeout: float = 30):
    fim = time.monotonic() + timeout
    while time.monotonic() < fim:
        tarefa = task_manager.get(projeto_id, etapa)
        if tarefa is not None and not tarefa.running:
            return tarefa
        time.sleep(0.05)
    raise AssertionError(f"etapa '{etapa}' não terminou em {timeout}s")


# --- Tarefa 1: chaves estáveis de situação ---------------------------------


def test_status_etapas_devolve_chaves_ascii_e_nao_texto_de_tela(cliente, tmp_path):
    from gclaude_indexer.project import load_project
    from gclaude_indexer.web.step_state import STEPS, STATUSES, step_status

    projeto_id = _criar_projeto(cliente, tmp_path)
    cliente.post(f"/projects/{projeto_id}/run-next")
    _esperar_etapa_terminar(projeto_id, "scan")

    from gclaude_indexer.catalog import find_project
    _config, conn = load_project(find_project(projeto_id).output_folder)
    try:
        etapas = step_status(conn, lambda _chave: False)
    finally:
        conn.close()

    assert [e["chave"] for e in etapas] == list(STEPS)
    for item in etapas:
        assert item["status"] in STATUSES, item
        assert item["status"].isascii(), "a situação vira classe CSS: precisa ser ASCII"
    assert etapas[0]["status"] == "done"
    assert etapas[0]["vars"] == {"total": 1}


def test_proxima_etapa_pendente_usa_chave_e_nao_texto_traduzido():
    from gclaude_indexer.web.step_state import next_pending_step

    etapas = [
        {"chave": "scan", "status": "done", "vars": {}},
        {"chave": "conversion", "status": "running", "vars": {}},
        {"chave": "extraction", "status": "not_started", "vars": {}},
    ]
    assert next_pending_step(etapas) == "extraction"


def test_tela_de_execucao_traduz_o_status_para_ingles(cliente, tmp_path):
    projeto_id = _criar_projeto(cliente, tmp_path)
    cliente.post(f"/projects/{projeto_id}/run-next")
    _esperar_etapa_terminar(projeto_id, "scan")

    cliente.cookies.set("language", "en")
    corpo = cliente.get(f"/projects/{projeto_id}/run").text

    # A tabela de etapas é o escopo desta tarefa; o log de eventos (mais
    # abaixo na mesma página) é texto de domínio e continua em português por
    # design documentado em i18n.py — não é o defeito que este teste cobre.
    inicio_tabela = corpo.index('id="steps"')
    fim_tabela = corpo.index("</table>", inicio_tabela)
    tabela_etapas = corpo[inicio_tabela:fim_tabela]

    assert "1. Scan" in tabela_etapas
    # ">done<" e não "done" solto: "{feitas} done, {pendentes} pending" (a
    # contagem da etapa de classificação, em inglês) também contém "done"
    # como substring — o texto do badge de situação é o que precisa provar.
    assert ">done<" in tabela_etapas
    assert "concluída" not in tabela_etapas
    assert "1. Varredura" not in tabela_etapas
    assert 'status-done' in tabela_etapas  # classe CSS estável, sem acento


# --- Tarefa 2: o progresso não some ao terminar ----------------------------


def test_progresso_mostra_concluida_depois_que_a_etapa_termina(cliente, tmp_path):
    projeto_id = _criar_projeto(cliente, tmp_path)
    cliente.post(f"/projects/{projeto_id}/run-next")
    _esperar_etapa_terminar(projeto_id, "scan")

    corpo = cliente.get(f"/projects/{projeto_id}/run/progress").text

    assert "progress-bar-done" in corpo
    assert "100%" in corpo
    assert "Nenhuma etapa rodando" not in corpo


def test_progresso_vazio_quando_o_projeto_nunca_rodou(cliente, tmp_path):
    projeto_id = _criar_projeto(cliente, tmp_path)
    corpo = cliente.get(f"/projects/{projeto_id}/run/progress").text
    assert "Nenhuma etapa rodando" in corpo


def test_tempo_decorrido_congela_quando_a_etapa_termina(cliente, tmp_path):
    projeto_id = _criar_projeto(cliente, tmp_path)
    cliente.post(f"/projects/{projeto_id}/run-next")
    tarefa = _esperar_etapa_terminar(projeto_id, "scan")

    assert tarefa.finished_at is not None, "terminado_em tem que ser gravado ao acabar"
    congelado = tarefa.finished_at - tarefa.started_at

    primeira = cliente.get(f"/projects/{projeto_id}/run/progress").text
    time.sleep(1.2)
    segunda = cliente.get(f"/projects/{projeto_id}/run/progress").text

    # a mesma duração formatada nas duas leituras, mesmo com 1.2s entre elas
    assert _format_time(congelado) in primeira
    assert _format_time(congelado) in segunda


# --- Tarefa 4: nome legível da etapa na barra ------------------------------


def test_barra_de_progresso_mostra_o_titulo_da_etapa_e_nao_a_chave(cliente, tmp_path):
    projeto_id = _criar_projeto(cliente, tmp_path)
    cliente.post(f"/projects/{projeto_id}/run-next")
    _esperar_etapa_terminar(projeto_id, "scan")

    corpo = cliente.get(f"/projects/{projeto_id}/run/progress").text
    assert "1. Varredura" in corpo
    assert ">varredura<" not in corpo


def test_barra_de_progresso_traduz_o_titulo_da_etapa(cliente, tmp_path):
    projeto_id = _criar_projeto(cliente, tmp_path)
    cliente.post(f"/projects/{projeto_id}/run-next")
    _esperar_etapa_terminar(projeto_id, "scan")

    cliente.cookies.set("language", "es")
    corpo = cliente.get(f"/projects/{projeto_id}/run/progress").text
    assert "1. Barrido" in corpo


# --- Tarefa 5: log ao vivo -------------------------------------------------


def test_log_mostra_ate_200_linhas(cliente, tmp_path):
    from gclaude_indexer.catalog import find_project
    from gclaude_indexer.events import record_event
    from gclaude_indexer.project import load_project

    projeto_id = _criar_projeto(cliente, tmp_path)
    _config, conn = load_project(find_project(projeto_id).output_folder)
    try:
        for i in range(220):
            record_event(conn, "scan", "info", f"message numero {i}")
        conn.commit()
    finally:
        conn.close()

    corpo = cliente.get(f"/projects/{projeto_id}/run/log").text

    # Não asserte um número de message específico na borda da janela: criar o
    # projeto já registra eventos próprios, então o corte de 200 cai num ponto
    # que depende de quantos foram. O que precisa valer é o teto e a cauda.
    assert "message numero 219" in corpo, "a message mais recente tem que aparecer"
    assert "message numero 0" not in corpo, "as mais antigas têm que ficar de fora"
    assert corpo.count("<li") <= 200, "o painel não pode passar de 200 linhas"
    assert corpo.count("<li") >= 190, "e precisa estar de fato usando a janela nova"


def test_barra_de_filtro_do_log_existe_mesmo_sem_eventos(cliente, tmp_path):
    """A barra de filtro é parte da tela, não das linhas: aparece mesmo com
    o log vazio, senão o usuário não teria como prepará-la antes de rodar."""
    projeto_id = _criar_projeto(cliente, tmp_path)
    corpo = cliente.get(f"/projects/{projeto_id}/run").text

    assert 'id="log-filter"' in corpo
    assert 'id="follow-log"' in corpo
    assert 'value="error"' in corpo
    assert 'class="log-box"' in corpo
    # sem eventos ainda: nenhuma linha marcada, só o aviso de log vazio
    assert "data-log-level" not in corpo


def test_linhas_do_log_carregam_o_nivel_para_o_filtro(cliente, tmp_path):
    projeto_id = _criar_projeto(cliente, tmp_path)
    cliente.post(f"/projects/{projeto_id}/run-next")
    _esperar_etapa_terminar(projeto_id, "scan")

    corpo = cliente.get(f"/projects/{projeto_id}/run").text

    assert 'data-log-level="info"' in corpo
    assert 'id="log-filter"' in corpo


# --- Tarefa 18: etapa de importação não vaza chave crua no log ------------


def test_log_traduz_a_etapa_de_importacao_e_nao_mostra_chave_crua(cliente, tmp_path):
    """Defect 2 (Task 18): `import_items.py` used to record events under the
    step `"importacao"`, absent from both `step_state.STEPS` and any
    `step.*.title` i18n key — `_log.html` fell back to the raw key, in any
    language. `import` is deliberately not in `STEPS` (see
    `import_items.py`'s module docstring) but must still resolve to a
    translated label via `app.LOG_KNOWN_STEPS`."""
    from gclaude_indexer.catalog import find_project
    from gclaude_indexer.events import record_event
    from gclaude_indexer.project import load_project

    projeto_id = _criar_projeto(cliente, tmp_path)
    _config, conn = load_project(find_project(projeto_id).output_folder)
    try:
        record_event(conn, "import", "warning", "log.import.file_not_found")
        conn.commit()
    finally:
        conn.close()

    corpo_pt = cliente.get(f"/projects/{projeto_id}/run/log").text
    assert "Importação" in corpo_pt
    assert ">import<" not in corpo_pt

    cliente.cookies.set("language", "en")
    corpo_en = cliente.get(f"/projects/{projeto_id}/run/log").text
    assert "Import" in corpo_en
    assert ">import<" not in corpo_en

    cliente.cookies.set("language", "es")
    corpo_es = cliente.get(f"/projects/{projeto_id}/run/log").text
    assert "Importación" in corpo_es
    assert ">import<" not in corpo_es


# --- Tarefa 6: extensões agrupadas por família -----------------------------


def test_categorias_por_familia_cobre_todas_as_categorias_menos_todos():
    from gclaude_indexer.file_types import CATEGORY_ALL, EXTENSION_CATEGORIES, categories_by_family

    agrupadas = categories_by_family()
    vistas = {item["categoria"] for _familia, itens in agrupadas for item in itens}
    assert vistas == set(EXTENSION_CATEGORIES)
    assert CATEGORY_ALL not in vistas
    assert [familia for familia, _itens in agrupadas][0] == "documentos"


def test_categorias_por_familia_traz_as_extensoes_de_cada_categoria():
    from gclaude_indexer.file_types import categories_by_family

    por_categoria = {
        item["categoria"]: item["extensoes"]
        for _familia, itens in categories_by_family() for item in itens
    }
    assert por_categoria["pdf"] == [".pdf"]
    assert ".jpg" in por_categoria["imagens"]
    assert por_categoria["imagens"] == sorted(por_categoria["imagens"])


def test_formulario_agrupa_as_extensoes_e_mostra_o_que_cada_uma_cobre(cliente):
    corpo = cliente.get("/projects/new").text
    assert 'class="extension-family"' in corpo
    assert ".pdf" in corpo
    assert ".jpeg" in corpo
    for categoria in ("pdf", "docx", "xlsx", "pptx", "imagens", "text", "web_dados", "email", "all"):
        assert f'value="{categoria}"' in corpo, categoria


def test_formulario_reexibido_apos_erro_tambem_agrupa_as_extensoes(cliente):
    """O ramo de `criar_novo_projeto` que reexibe o formulário após erro de
    validação passa pelo mesmo contexto de template que `tela_novo_projeto` —
    um GET sozinho não pega regressão nesse segundo ponto."""
    resposta = cliente.post("/projects/new", data={"name": "Sem pasta"})
    assert resposta.status_code == 400
    assert 'class="extension-family"' in resposta.text
    for categoria in ("pdf", "docx", "xlsx", "pptx", "imagens", "text", "web_dados", "email", "all"):
        assert f'value="{categoria}"' in resposta.text, categoria


# --- Tarefa 7: descrições dos motores --------------------------------------


def test_motores_ordenados_cobre_exatamente_os_motores_validos():
    from gclaude_indexer.config import CLASSIFICATION_ENGINES
    from gclaude_indexer.web.app import CLASSIFICATION_ENGINES_ORDER

    assert set(CLASSIFICATION_ENGINES_ORDER) == CLASSIFICATION_ENGINES
    assert CLASSIFICATION_ENGINES_ORDER[0] == "automatic"


def test_formulario_mostra_nome_e_descricao_de_cada_motor(cliente):
    corpo = cliente.get("/projects/new").text
    assert "Automático" in corpo
    assert "Ollama" in corpo  # descrição do motor local diz do que ele depende
    assert '<option value="claude_code"' in corpo
    assert ">claude_code<" not in corpo  # o identificador cru não aparece mais
    assert 'class="engine-descriptions"' in corpo


def test_formulario_reexibido_apos_erro_tambem_mostra_os_motores(cliente):
    """Mesmo ponto de atenção da Tarefa 6: o ramo de erro de `criar_novo_projeto`
    passa por um contexto próprio, então um teste que só faz GET não pega
    regressão nesse segundo ponto."""
    resposta = cliente.post("/projects/new", data={"name": "Sem pasta"})
    assert resposta.status_code == 400
    assert 'class="engine-descriptions"' in resposta.text
    assert '<option value="claude_code"' in resposta.text
    assert ">claude_code<" not in resposta.text


def test_descricoes_dos_motores_nao_afirmam_o_que_o_codigo_nao_faz(cliente):
    """Trava um erro factual que já entrou uma vez: o motor automático decide
    por hardware (não por Ollama respondendo). O openrouter, que tinha a
    outra afirmação travada aqui ("ainda não implementado"), foi removido na
    Tarefa 6 da Fase 13 — a opção nunca teve implementação e saiu do
    formulário por completo."""
    corpo = cliente.get("/projects/new").text

    assert "hardware" in corpo
    assert "Ollama estiver respondendo" not in corpo
    assert "envia o texto do acervo para fora" not in corpo


# --- Tarefa 8: descoberta de modelos do Ollama -----------------------------


def test_listar_modelos_devolve_nomes_ordenados(monkeypatch):
    import json
    import io
    from gclaude_indexer.web import ollama_models

    resposta = json.dumps({"models": [
        {"name": "qwen3:8b"}, {"name": "gemma4:e4b"}, {"name": "gemma4:26b"},
    ]}).encode("utf-8")

    class _Resposta(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    monkeypatch.setattr(ollama_models.urllib.request, "urlopen", lambda *a, **k: _Resposta(resposta))
    assert ollama_models.list_installed_models() == ["gemma4:26b", "gemma4:e4b", "qwen3:8b"]


def test_listar_modelos_devolve_lista_vazia_quando_ollama_esta_fora(monkeypatch):
    import urllib.error
    from gclaude_indexer.web import ollama_models

    def _explode(*_args, **_kwargs):
        raise urllib.error.URLError("conexão recusada")

    monkeypatch.setattr(ollama_models.urllib.request, "urlopen", _explode)
    assert ollama_models.list_installed_models() == []


def test_formulario_oferece_os_modelos_instalados(cliente, monkeypatch):
    import gclaude_indexer.web.app as app_mod

    monkeypatch.setattr(app_mod, "list_installed_models", lambda: ["qwen3.5:4b", "qwen3:8b"])
    corpo = cliente.get("/projects/new").text

    assert '<select id="local_model" name="local_model">' in corpo
    assert '<option value="qwen3:8b"' in corpo
    assert '<option value="qwen3.5:4b" selected' in corpo
    assert "(fixo)" not in corpo


def test_formulario_avisa_quando_nao_ha_modelo_instalado(cliente, monkeypatch):
    import gclaude_indexer.web.app as app_mod

    monkeypatch.setattr(app_mod, "list_installed_models", lambda: [])
    corpo = cliente.get("/projects/new").text

    assert 'name="local_model"' in corpo
    # "Ollama" sozinho aparece de qualquer forma (ex. "motor.local.nome"); o
    # que prova que este é o aviso de "sem modelo instalado" é o endereço.
    assert "127.0.0.1:11434" in corpo


def test_formulario_reexibido_apos_erro_tambem_oferece_os_modelos(cliente, monkeypatch):
    """Mesmo ponto de atenção das Tarefas 6 e 7: o ramo de erro de
    `criar_novo_projeto` passa por um contexto próprio, então um teste que só
    faz GET não pega regressão nesse segundo ponto."""
    import gclaude_indexer.web.app as app_mod

    monkeypatch.setattr(app_mod, "list_installed_models", lambda: ["qwen3.5:4b", "qwen3:8b"])
    resposta = cliente.post("/projects/new", data={"name": "Sem pasta"})

    assert resposta.status_code == 400
    assert '<select id="local_model" name="local_model">' in resposta.text
    assert '<option value="qwen3:8b"' in resposta.text
    assert '<option value="qwen3.5:4b" selected' in resposta.text


# --- Tarefa 8 (correção pós-revisão): robustez e textos de ajuda -----------


def test_listar_modelos_engole_resposta_http_malformada(monkeypatch):
    import http.client
    from gclaude_indexer.web import ollama_models

    def _trunca(*_args, **_kwargs):
        raise http.client.IncompleteRead(b"parcial")

    monkeypatch.setattr(ollama_models.urllib.request, "urlopen", _trunca)
    assert ollama_models.list_installed_models() == []


def test_ajuda_do_modelo_local_diz_a_verdade_sobre_o_modelo_usado(cliente, monkeypatch):
    """Trava as frases falsas que já entraram: nem 'o campo é só
    compatibilidade' (a lista é real e vem do Ollama), nem 'a escolha não
    muda o modelo usado' (desde a Tarefa 8 da Fase 13, `modelo_para_usar`
    respeita `config.local_model`; só "automático"/vazio cai no padrão)."""
    import gclaude_indexer.web.app as app_mod

    monkeypatch.setattr(app_mod, "list_installed_models", lambda: ["qwen3.5:4b", "qwen3:8b"])
    corpo = cliente.get("/projects/new").text

    assert "Único modelo permitido" not in corpo
    assert "só por compatibilidade" not in corpo
    assert "ainda não troca o modelo usado" not in corpo
    assert "Modelos instalados no Ollama" in corpo
    assert "usada de verdade na classificação" in corpo


# --- Tarefa 9: quatro temas ------------------------------------------------


def test_tema_valido_aceita_os_quatro_e_recusa_desconhecido():
    from gclaude_indexer.web.theme import AVAILABLE_THEMES, DEFAULT_THEME, valid_theme

    assert AVAILABLE_THEMES == ("light", "dark", "sepia", "high_contrast")
    for tema in AVAILABLE_THEMES:
        assert valid_theme(tema) == tema
    assert valid_theme("roxo") == DEFAULT_THEME
    assert valid_theme(None) == DEFAULT_THEME


def test_cabecalho_traz_um_seletor_com_os_quatro_temas(cliente):
    corpo = cliente.get("/projects").text
    assert 'name="theme"' in corpo
    for tema in ("light", "dark", "sepia", "high_contrast"):
        assert f'<option value="{tema}"' in corpo, tema


def test_escolher_tema_grava_o_cookie_e_aplica_no_html(cliente):
    resposta = cliente.post("/preferences/theme", data={"theme": "sepia"}, follow_redirects=False)
    assert resposta.status_code in (302, 303)
    corpo = cliente.get("/projects").text
    assert 'data-theme="sepia"' in corpo


def test_tema_desconhecido_cai_no_padrao(cliente):
    cliente.post("/preferences/theme", data={"theme": "roxo"}, follow_redirects=False)
    corpo = cliente.get("/projects").text
    assert 'data-theme="light"' in corpo


def test_css_define_os_tokens_dos_temas_novos():
    from pathlib import Path

    import gclaude_indexer.web.app as app_mod

    import re

    css = (Path(app_mod.WEB_ROOT) / "static" / "style.css").read_text(encoding="utf-8")

    def tokens(bloco: str) -> set[str]:
        return set(re.findall(r"(--color-[a-z0-9-]+)\s*:", bloco))

    def bloco_do_tema(nome: str) -> str:
        return css.split(f'html[data-theme="{nome}"] {{', 1)[1].split("}", 1)[0]

    for tema in ("sepia", "high_contrast"):
        assert f'html[data-theme="{tema}"]' in css, tema

    # The floor is what the `dark` theme defines, not the whole `:root`: dark
    # intentionally leaves out 7 inherited tokens (--color-log-* and --color-header-*),
    # because the log and header are already dark in the light theme. Requiring
    # parity with `:root` would fail this code, which is correct.
    minimo = tokens(bloco_do_tema("dark"))
    assert len(minimo) >= 24
    for tema in ("sepia", "high_contrast"):
        faltando = minimo - tokens(bloco_do_tema(tema))
        assert not faltando, f"tema {tema} não redefine: {sorted(faltando)}"


# --- Tarefa 10: aviso dispensável ------------------------------------------


def test_aviso_de_troca_de_maquina_tem_botao_de_dispensar(cliente):
    corpo = cliente.get("/projects").text
    # ids/localStorage key traduzidos na Tarefa 18 (fase 14, defeito 5).
    assert 'id="machine-switch-notice"' in corpo
    assert 'id="close-machine-switch-notice"' in corpo
    assert "gclaude.machine_switch_notice_dismissed" in corpo


# --- Tarefa 18: defeito 5 — acoplamento id=/for=/hx-target/ícone não descasa --


def test_hx_target_sempre_aponta_para_um_id_existente_nos_templates():
    """Static, render-independent version of the coupling check: some
    `hx-target=` fragments only render under a specific runtime condition
    (`_progress.html`'s pause button needs a step actually running,
    `_steps.html`'s claude_code recheck needs that engine selected) — a
    request-based test can miss them depending on fixture state. This reads
    every template's source directly and proves each `hx-target="#x"` has a
    matching `id="x"` *somewhere* in the template set (ids and their
    consumers can live in different files — `run.html` defines `id="steps"`,
    `_progress.html`/`_steps.html` target it — that is exactly the pairing
    Task 18 found broken: `_progress.html`/`_steps.html` still said
    `hx-target="#etapas"` after `run.html`'s `id="etapas"` became `"steps"`,
    caught only by reading the file, not by any test or by clicking through
    the common paths."""
    import re
    from pathlib import Path

    templates_dir = Path(__file__).resolve().parent.parent / "gclaude_indexer" / "web" / "templates"
    all_source = "\n".join(p.read_text(encoding="utf-8") for p in templates_dir.glob("*.html"))

    ids = set(re.findall(r'\bid="([^"{]+)"', all_source))  # static ids only (skip {{ ... }} ones)
    targets = set(re.findall(r'hx-target="#([^"{]+)"', all_source))
    missing = {t for t in targets if t not in ids}
    assert not missing, f"hx-target aponta para id= inexistente em qualquer template: {missing}"


def test_todo_label_for_tem_id_correspondente_na_pagina(cliente, tmp_path):
    """Defect 5 (Task 18): every renamed `id=` had up to three consumers
    (`<label for=>`, `hx-target=`, `getElementById`) that had to move
    together — a mismatch on any one breaks silently, no failing test, just
    a label that stops focusing its field or a button that stops updating
    the right fragment. This audits every page that ships a `<label for=>`
    or an `hx-target=` and proves the id it points at still exists."""
    import re

    projeto_id = _criar_projeto(cliente, tmp_path)
    paginas = {
        "/projects/new": cliente.get("/projects/new").text,
        f"/projects/{projeto_id}/run": cliente.get(f"/projects/{projeto_id}/run").text,
        f"/projects/{projeto_id}/result": cliente.get(f"/projects/{projeto_id}/result").text,
        "/about": cliente.get("/about").text,
    }
    for url, corpo in paginas.items():
        ids = set(re.findall(r'\bid="([^"]+)"', corpo))
        for alvo in re.findall(r'\bfor="([^"]+)"', corpo):
            assert alvo in ids, f"{url}: label for=\"{alvo}\" sem id= correspondente"
        for alvo in re.findall(r'hx-target="#([^"]+)"', corpo):
            assert alvo in ids, f"{url}: hx-target=\"#{alvo}\" sem id= correspondente"


def test_todo_icone_usado_tem_simbolo_correspondente(cliente):
    """Every `m.icon('x')` call builds `href="#icon-x"` (see `_macros.html`)
    — this proves every such reference resolves to a `<symbol id="icon-x">`
    actually defined in `_icons.html` (included once, in `base.html`).
    Catches the exact kind of drift Task 18 found pre-existing: `icon('help')`
    pointed at a symbol that used to be named `icone-ajuda`, not `icone-help`
    — silently rendering an empty icon, no error anywhere."""
    import re

    corpo = cliente.get("/projects").text
    symbol_ids = set(re.findall(r'<symbol id="(icon-[^"]+)"', corpo))
    assert symbol_ids, "nenhum símbolo de ícone encontrado — _icons.html não foi incluído?"
    used = set(re.findall(r'href="#(icon-[^"]+)"', corpo))
    assert used, "nenhum ícone referenciado na tela de projetos"
    assert used <= symbol_ids, f"ícone(s) referenciado(s) sem símbolo definido: {used - symbol_ids}"


# --- Tarefa 11: limpeza de intermediários ----------------------------------


def test_limpar_intermediarios_apaga_so_convertidos_e_blocos(tmp_path):
    from gclaude_indexer.cleanup import clear_intermediates, intermediates_size

    saida = tmp_path / "saida"
    (saida / "converted" / "volume_1").mkdir(parents=True)
    (saida / "blocks" / "volume_1").mkdir(parents=True)
    (saida / "logs").mkdir()
    (saida / "converted" / "volume_1" / "peca.pdf").write_bytes(b"x" * 1000)
    (saida / "blocks" / "volume_1" / "bloco_1.txt").write_bytes(b"y" * 500)
    (saida / "logs" / "execucao.log").write_text("registro", encoding="utf-8")
    (saida / "project.db").write_bytes(b"banco")
    (saida / "indice.md").write_text("# Índice", encoding="utf-8")
    (saida / "raw_items.jsonl").write_text("{}", encoding="utf-8")

    assert intermediates_size(str(saida)) == 1500
    assert clear_intermediates(str(saida)) == 1500

    assert not (saida / "converted").exists()
    assert not (saida / "blocks").exists()
    assert (saida / "project.db").exists()
    assert (saida / "indice.md").exists()
    assert (saida / "raw_items.jsonl").exists()
    assert (saida / "logs" / "execucao.log").exists()
    assert intermediates_size(str(saida)) == 0


def test_limpar_intermediarios_e_idempotente_em_pasta_sem_intermediarios(tmp_path):
    from gclaude_indexer.cleanup import clear_intermediates, intermediates_size

    saida = tmp_path / "saida_limpa"
    saida.mkdir()
    (saida / "project.db").write_bytes(b"banco")

    assert intermediates_size(str(saida)) == 0
    assert clear_intermediates(str(saida)) == 0
    assert (saida / "project.db").exists()


def test_tela_de_resultado_oferece_a_limpeza(cliente, tmp_path):
    projeto_id = _criar_projeto(cliente, tmp_path)
    corpo = cliente.get(f"/projects/{projeto_id}/result").text
    assert f"/projects/{projeto_id}/clear-intermediates" in corpo


def test_rota_de_limpeza_libera_espaco_e_volta_para_o_resultado(cliente, tmp_path):
    from gclaude_indexer.catalog import find_project

    projeto_id = _criar_projeto(cliente, tmp_path)
    saida = Path(find_project(projeto_id).output_folder)
    (saida / "converted").mkdir(parents=True, exist_ok=True)
    (saida / "converted" / "peca.pdf").write_bytes(b"z" * 2048)

    resposta = cliente.post(f"/projects/{projeto_id}/clear-intermediates", follow_redirects=False)
    assert resposta.status_code in (302, 303)
    assert not (saida / "converted").exists()
    assert (saida / "project.db").exists()


def test_limpeza_pausa_etapas_em_andamento_antes_de_apagar(cliente, tmp_path, monkeypatch):
    """A tela de Resultado é alcançável com a conversão rodando; apagar sob
    uma etapa ativa falharia em silêncio no Windows. Só provar que `pausar`
    foi chamada não basta — precisa ser chamada ANTES do `rmtree`, senão a
    chamada pode ter acontecido tarde demais para evitar a corrida."""
    import gclaude_indexer.web.app as app_mod
    from gclaude_indexer.web.background_runs import task_manager

    projeto_id = _criar_projeto(cliente, tmp_path)
    ordem = []
    original_pausar = task_manager.pause
    original_limpar = app_mod.clear_intermediates
    monkeypatch.setattr(
        task_manager, "pause",
        lambda pid, step=None: (ordem.append("pausar"), original_pausar(pid, step))[1],
    )
    monkeypatch.setattr(
        app_mod, "clear_intermediates",
        lambda pasta: (ordem.append("limpar"), original_limpar(pasta))[1],
    )

    cliente.post(f"/projects/{projeto_id}/clear-intermediates", follow_redirects=False)

    assert ordem == ["pausar", "limpar"], "pausar tem que rodar antes do rmtree, não só ser chamada em algum momento"


# --- Tarefa 12: paridade entre os três idiomas -----------------------------


def test_os_tres_idiomas_tem_exatamente_as_mesmas_chaves():
    from gclaude_indexer.web.i18n import AVAILABLE_LANGUAGES, _TRANSLATIONS

    assert set(_TRANSLATIONS) == set(AVAILABLE_LANGUAGES)
    referencia = set(_TRANSLATIONS["pt"])
    for idioma, tabela in _TRANSLATIONS.items():
        faltando = sorted(referencia - set(tabela))
        sobrando = sorted(set(tabela) - referencia)
        assert not faltando, f"{idioma} não traduz: {faltando}"
        assert not sobrando, f"{idioma} tem chave que 'pt' não tem: {sobrando}"


def test_toda_chave_com_variavel_usa_o_mesmo_conjunto_nos_tres_idiomas():
    import re
    from gclaude_indexer.web.i18n import _TRANSLATIONS

    def variaveis(texto: str) -> set[str]:
        return set(re.findall(r"\{(\w+)\}", texto))

    for chave, texto_pt in _TRANSLATIONS["pt"].items():
        esperado = variaveis(texto_pt)
        for idioma, tabela in _TRANSLATIONS.items():
            assert variaveis(tabela[chave]) == esperado, f"{idioma}/{chave}: variáveis não batem"


def test_tela_de_resultado_traduz_as_pendencias(cliente, tmp_path):
    """Com pendências de verdade no banco — sem elas o bloco nem renderiza e
    o teste passaria mesmo com o template sem tradução."""
    from gclaude_indexer.catalog import find_project
    from gclaude_indexer.project import load_project

    projeto_id = _criar_projeto(cliente, tmp_path)
    cliente.post(f"/projects/{projeto_id}/run-next")
    _esperar_etapa_terminar(projeto_id, "scan")

    _config, conn = load_project(find_project(projeto_id).output_folder)
    try:
        # uma falha e uma janela pendente: os dois ramos do bloco de pendências
        conn.execute(
            "UPDATE file SET status = 'failed', error = 'erro de teste' "
            "WHERE id = (SELECT id FROM file LIMIT 1)"
        )
        conn.execute(
            "INSERT INTO window (key, group_key, start_ref, end_ref, status) "
            "VALUES ('teste-pendente', 'volume_1', 'f. 1', 'f. 2', 'pending')"
        )
        conn.commit()
    finally:
        conn.close()

    corpo_pt = cliente.get(f"/projects/{projeto_id}/result").text
    assert "ainda não classificada" in corpo_pt, "o bloco de pendências precisa renderizar"

    cliente.cookies.set("language", "en")
    corpo_en = cliente.get(f"/projects/{projeto_id}/result").text

    assert "not classified yet" in corpo_en
    assert "ainda não classificada" not in corpo_en
    assert "Lacuna em" not in corpo_en
    assert "Falhou:" not in corpo_en


# --- Correções da revisão final ---------------------------------------------


def test_css_esconde_a_faixa_quando_marcada_com_hidden():
    """`display:flex` na regra base vence o [hidden] do navegador; sem uma
    regra explícita o botão de dispensar fica inerte e o teste de HTML não pega."""
    from pathlib import Path
    import gclaude_indexer.web.app as app_mod

    css = (Path(app_mod.WEB_ROOT) / "static" / "style.css").read_text(encoding="utf-8")
    assert ".notice-bar[hidden]" in css
    bloco = css.split(".notice-bar[hidden]", 1)[1].split("}", 1)[0]
    assert "display: none" in bloco


def test_faixa_de_aviso_continua_visivel_sem_javascript(cliente):
    corpo = cliente.get("/projects").text
    assert "<noscript>" in corpo
    assert ".notice-bar[hidden]" in corpo.split("<noscript>", 1)[1].split("</noscript>", 1)[0]


def test_texto_da_limpeza_nao_promete_regeneracao(cliente, tmp_path):
    projeto_id = _criar_projeto(cliente, tmp_path)
    corpo = cliente.get(f"/projects/{projeto_id}/result").text
    assert "rodar a conversão outra vez" not in corpo
    assert "definitiva" in corpo


def test_botao_de_limpeza_desabilitado_com_etapa_em_andamento(cliente, tmp_path):
    """Com uma etapa rodando, `pausar` só sinaliza — não espera a thread — e
    a limpeza correria contra quem está escrevendo. O botão precisa ficar
    desabilitado nesse caso, não só quando não há nada para apagar."""
    from gclaude_indexer.catalog import find_project
    from gclaude_indexer.web.background_runs import StepTask, task_manager

    projeto_id = _criar_projeto(cliente, tmp_path)
    saida = Path(find_project(projeto_id).output_folder)
    (saida / "converted").mkdir(parents=True, exist_ok=True)
    (saida / "converted" / "peca.pdf").write_bytes(b"z" * 2048)

    corpo_livre = cliente.get(f"/projects/{projeto_id}/result").text
    inicio = corpo_livre.index('class="cleanup-box"')
    fim = corpo_livre.index("</form>", inicio)
    assert "disabled" not in corpo_livre[inicio:fim], "com espaço a liberar e nada rodando, o botão fica ativo"

    task_manager._tasks[(projeto_id, "conversion")] = StepTask(step="conversion", total=1, baseline=0)

    corpo_ocupado = cliente.get(f"/projects/{projeto_id}/result").text
    inicio2 = corpo_ocupado.index('class="cleanup-box"')
    fim2 = corpo_ocupado.index("</form>", inicio2)
    trecho = corpo_ocupado[inicio2:fim2]
    assert "disabled" in trecho, "com uma etapa em andamento, o botão de limpeza precisa ficar desabilitado"
    assert "espere terminar" in trecho or "wait for it" in trecho or "espere a que termine" in trecho


def test_limpar_intermediarios_recalcula_liberado_apos_falha_no_rmtree(tmp_path, monkeypatch):
    """`liberado` calculado antes do `rmtree` (que roda com `ignore_errors=True`)
    mentiria se o `rmtree` não apagasse nada de verdade."""
    from gclaude_indexer import cleanup as limpeza_mod

    saida = tmp_path / "saida_falha"
    (saida / "converted").mkdir(parents=True)
    (saida / "converted" / "peca.pdf").write_bytes(b"x" * 500)

    monkeypatch.setattr(limpeza_mod.shutil, "rmtree", lambda *a, **k: None)

    liberado = limpeza_mod.clear_intermediates(str(saida))

    assert liberado == 0, "se o rmtree não apagou nada de verdade, 0 bytes foram liberados"
    assert (saida / "converted" / "peca.pdf").exists()


def test_tamanho_intermediarios_ignora_arquivo_que_sumiu_durante_a_leitura(tmp_path, monkeypatch):
    """Entre o `is_file()` e o `stat()` o arquivo pode sumir — a tela de
    Resultado é alcançável com a conversão ainda escrevendo nessas pastas."""
    from pathlib import Path as PathlibPath

    from gclaude_indexer import cleanup as limpeza_mod

    saida = tmp_path / "saida_corrida"
    (saida / "converted").mkdir(parents=True)
    (saida / "converted" / "a.pdf").write_bytes(b"x" * 100)
    (saida / "converted" / "b.pdf").write_bytes(b"y" * 200)

    stat_original = PathlibPath.stat
    chamadas = {"a.pdf": 0}

    def _stat_instavel(self, *args, **kwargs):
        if self.name == "a.pdf":
            # Deixa a primeira chamada (usada por `is_file()`) passar, e só
            # falha na segunda (a chamada explícita de `tamanho_intermediarios`)
            # — reproduz exatamente a janela de corrida entre as duas.
            chamadas["a.pdf"] += 1
            if chamadas["a.pdf"] >= 2:
                raise OSError("arquivo sumiu durante a leitura")
        return stat_original(self, *args, **kwargs)

    monkeypatch.setattr(PathlibPath, "stat", _stat_instavel)

    assert limpeza_mod.intermediates_size(str(saida)) == 200


def test_gerenciador_tarefas_nao_tem_mais_etapa_rodando():
    """Código morto: zero chamadores de `TaskManager.etapa_rodando`
    (confirmado por grep) — `ultima_do_projeto` cobre o mesmo caso de uso."""
    from gclaude_indexer.web.background_runs import TaskManager

    assert not hasattr(TaskManager, "etapa_rodando")


def test_etapas_e_etapas_ordem_nao_divergem():
    from gclaude_indexer.web.step_state import STEPS
    from gclaude_indexer.web.background_runs import STEP_ORDER

    assert tuple(STEPS) == tuple(STEP_ORDER)


def test_textos_criticos_dizem_a_verdade_nos_tres_idiomas():
    from gclaude_indexer.web.i18n import _TRANSLATIONS

    proibidas = {
        "pt": ["Ollama estiver respondendo", "envia o texto do acervo para fora",
               "Único modelo permitido", "só por compatibilidade", "rodar a conversão outra vez"],
        "en": ["if Ollama is responding", "sends the collection's text off",
               "The only model allowed", "kept only for compatibility"],
        "es": ["si Ollama está respondiendo", "envía el texto del acervo fuera",
               "Único modelo permitido", "mantenido solo por compatibilidad"],
    }
    for idioma, frases in proibidas.items():
        junto = " ".join(_TRANSLATIONS[idioma].values())
        for frase in frases:
            assert frase not in junto, f"{idioma}: texto falso reintroduzido — {frase!r}"
