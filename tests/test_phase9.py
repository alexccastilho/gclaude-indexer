"""Phase 9 tests: web interface (FastAPI + Jinja2 + HTMX), spec section 6."""

from __future__ import annotations

import time

import fitz
import pytest
from fastapi.testclient import TestClient

import gclaude_indexer.catalog as catalogo_mod
import gclaude_indexer.hardware as hardware_mod
from gclaude_indexer.web.app import _validate_host, app
from gclaude_indexer.web.background_runs import task_manager


def _esperar_etapa_terminar(projeto_id: int, etapa: str, timeout: float = 30):
    """As rotas de execução agora só disparam a etapa em segundo plano e
    retornam na hora (barra de progresso + pausa dependem disso) — os
    testes precisam esperar a tarefa terminar antes de checar o resultado."""
    fim = time.monotonic() + timeout
    while time.monotonic() < fim:
        tarefa = task_manager.get(projeto_id, etapa)
        if tarefa is not None and not tarefa.running:
            return tarefa
        time.sleep(0.05)
    raise AssertionError(f"etapa '{etapa}' do projeto {projeto_id} não terminou em {timeout}s")


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    """Isola o catálogo local de projetos num diretório de teste — nunca
    toca no %LOCALAPPDATA% de verdade durante os testes."""
    pasta_local = tmp_path / "local_maquina"
    monkeypatch.setattr(catalogo_mod, "machine_local_folder", lambda: pasta_local)
    monkeypatch.setattr(hardware_mod, "machine_local_folder", lambda: pasta_local)
    return TestClient(app)


def _pdf(caminho, texto):
    documento = fitz.open()
    pagina = documento.new_page()
    pagina.insert_textbox((50, 50, 550, 750), texto, fontsize=12)
    documento.save(caminho)
    documento.close()


def _criar_projeto(cliente, tmp_path, nome="Projeto de teste", **campos_extra):
    origem = tmp_path / "origem" / nome.replace(" ", "_")
    (origem / "volume_1").mkdir(parents=True)
    saida = tmp_path / f"{nome.replace(' ', '_')}_indexado"
    _pdf(
        origem / "volume_1" / "peca.pdf",
        "OFÍCIO No 1\nAssunto: teste da interface web, com texto suficiente para não acionar OCR.\n10/01/2024",
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
    projeto_id = int(resposta.headers["location"].split("/")[2])
    return projeto_id


# --- segurança: só 127.0.0.1 -----------------------------------------------


def test_validar_host_aceita_127_0_0_1():
    _validate_host("127.0.0.1")  # não levanta


def test_validar_host_recusa_qualquer_outro_endereco():
    with pytest.raises(ValueError):
        _validate_host("0.0.0.0")
    with pytest.raises(ValueError):
        _validate_host("192.168.0.10")


# --- tela: Projetos ----------------------------------------------------


def test_tela_projetos_vazia(cliente):
    resposta = cliente.get("/projects")
    assert resposta.status_code == 200
    assert "Nenhum projeto ainda" in resposta.text


def test_projeto_criado_aparece_na_lista(cliente, tmp_path):
    _criar_projeto(cliente, tmp_path, nome="Projeto Alfa")
    resposta = cliente.get("/projects")
    assert "Projeto Alfa" in resposta.text


# --- tela: Novo projeto — todos os campos, com os padrões da seção 6 ------


def test_formulario_novo_projeto_tem_todos_os_campos_da_tabela(cliente, monkeypatch):
    import gclaude_indexer.web.app as app_mod

    # Determinístico independente do Ollama estar de pé nesta máquina
    # (Tarefa 8, fase 12): o formulário lista os modelos instalados num
    # <select>, mas o teste não pode depender do serviço real.
    monkeypatch.setattr(app_mod, "list_installed_models", lambda: ["qwen3.5:4b", "qwen3:8b"])

    resposta = cliente.get("/projects/new")
    assert resposta.status_code == 200
    corpo = resposta.text

    campos_esperados = [
        'name="name"', 'name="subject"', 'name="source_folder"', 'name="output_folder"',
        'name="collection_type"', 'name="group_mode"', 'name="group_pattern"',
        'name="extensions"', 'name="classification_engine"', 'name="role_instructions"',
    ]
    # Saíram do formulário de criação (2.0.0): sem repassagem de confiança
    # baixa e com as regras extras editadas na tela Instruções.
    assert 'name="review_low_confidence"' not in corpo
    assert 'name="extra_rules"' not in corpo
    # Fatiamento, janelas e OCR saíram do formulário (2.0.0): são resolvidos
    # sozinhos depois da varredura.
    for campo_automatico in ("pages_per_block", "pages_per_window", "overlap", "chars_per_page", "ocr_language"):
        assert f'name="{campo_automatico}"' not in corpo
    for campo in campos_esperados:
        assert campo in corpo, f"campo ausente do formulário: {campo}"

    # modelo_local (Tarefa 8, fase 12): com modelos instalados, o campo é um
    # <select> preenchido a partir do Ollama local, não mais um <input
    # disabled> travado no modelo padrão. `id="local_model"` (Tarefa 18, fase
    # 14): o id foi trocado de "modelo_local" para bater com o name= já
    # traduzido — ver defeito 5 do relatorio da tarefa.
    assert 'id="local_model"' in corpo
    assert '<select id="local_model" name="local_model">' in corpo
    assert '<option value="qwen3:8b"' in corpo
    # 2.1.0: o padrão é um perfil, que depende da placa desta máquina.
    assert '<option value="fast" selected' in corpo or '<option value="quality" selected' in corpo


def _checkbox_marcado(corpo: str, valor: str) -> bool:
    trecho = corpo.split(f'value="{valor}"', 1)[1][:60]
    return "checked" in trecho.split(">")[0]


def test_formulario_novo_projeto_tem_os_padroes_da_secao_6(cliente):
    corpo = cliente.get("/projects/new").text
    assert '<option value="processo" selected' in corpo
    assert '<option value="subfolder" selected' in corpo
    assert '<option value="automatic" selected' in corpo

    # 2.0.0: o padrão é "TODOS" e cada categoria específica também aparece marcada
    # (TODOS fica abaixo da dobra); áudio e vídeo (opt-in) vêm desmarcados.
    assert _checkbox_marcado(corpo, "all"), "TODOS deveria vir marcado por padrão"
    for categoria in ("pdf", "docx", "imagens", "xlsx", "pptx", "text", "email"):
        assert _checkbox_marcado(corpo, categoria), f"{categoria} deveria vir marcado por padrão"
    assert not _checkbox_marcado(corpo, "midia"), "áudio/vídeo é opt-in e vem desmarcado"


def test_criar_projeto_com_dados_invalidos_reexibe_formulario_com_erros(cliente):
    resposta = cliente.post("/projects/new", data={"name": "Sem pasta"})
    assert resposta.status_code == 400
    assert "Corrija antes de continuar" in resposta.text
    assert "Sem pasta" in resposta.text  # reexibe o que já foi digitado


def test_criar_projeto_valido_redireciona_para_execucao(cliente, tmp_path):
    projeto_id = _criar_projeto(cliente, tmp_path)
    resposta = cliente.get(f"/projects/{projeto_id}/run")
    assert resposta.status_code == 200
    assert "1. Varredura" in resposta.text


# --- tela: Execução ----------------------------------------------------


def _situacao_da_etapa(html: str, titulo: str) -> str:
    trecho = html.split(titulo, 1)[1]
    return trecho.split('status-')[1].split('"')[0]


def test_executar_proxima_roda_uma_etapa_de_cada_vez(cliente, tmp_path):
    projeto_id = _criar_projeto(cliente, tmp_path)

    cliente.post(f"/projects/{projeto_id}/run-next")
    _esperar_etapa_terminar(projeto_id, "scan")
    html1 = cliente.get(f"/projects/{projeto_id}/run").text
    assert _situacao_da_etapa(html1, "1. Varredura") == "done"
    # só a varredura rodou — a conversão ainda não
    assert _situacao_da_etapa(html1, "2–3. Conversão") != "done"

    cliente.post(f"/projects/{projeto_id}/run-next")
    _esperar_etapa_terminar(projeto_id, "conversion")
    html2 = cliente.get(f"/projects/{projeto_id}/run").text
    assert _situacao_da_etapa(html2, "2–3. Conversão") == "done"
    assert _situacao_da_etapa(html2, "4. Extração") != "done"


def test_executar_tudo_ate_classificacao(cliente, tmp_path):
    projeto_id = _criar_projeto(cliente, tmp_path)
    cliente.post(f"/projects/{projeto_id}/run-all")
    _esperar_etapa_terminar(projeto_id, "classification")

    resposta = cliente.get(f"/projects/{projeto_id}/run")
    assert resposta.status_code == 200
    for titulo in ("1. Varredura", "2–3. Conversão", "4. Extração", "5. Preparação de janelas", "6. Classificação"):
        trecho = resposta.text.split(titulo)[1][:200]
        assert "done" in trecho, f"{titulo} não ficou concluída: {trecho}"


def test_log_atualiza_lendo_a_tabela_evento(cliente, tmp_path):
    # Tarefa 12 (Fase 14): a mensagem do evento agora é traduzida na leitura
    # (`list_events(conn, language=...)`), não mais texto fixo em português —
    # fixa o cookie para não depender do idioma padrão detectado na máquina
    # que roda o teste.
    cliente.cookies.set("language", "pt")
    projeto_id = _criar_projeto(cliente, tmp_path)

    vazio = cliente.get(f"/projects/{projeto_id}/run/log")
    assert "Nenhum evento ainda" in vazio.text

    cliente.post(f"/projects/{projeto_id}/run-next")
    _esperar_etapa_terminar(projeto_id, "scan")

    com_eventos = cliente.get(f"/projects/{projeto_id}/run/log")
    assert "Nenhum evento ainda" not in com_eventos.text
    assert "varredura" in com_eventos.text  # texto traduzido em `log.scan.summary` (chave `pt`)


def _gravar_motor_antigo(projeto_id: int, motor: str) -> None:
    """Deixa o projeto salvo com `motor` em `config_json`, como um da 1.x."""
    import json
    import sqlite3
    from pathlib import Path

    from gclaude_indexer.catalog import find_project

    banco = Path(find_project(projeto_id).output_folder) / "project.db"
    conn = sqlite3.connect(banco)
    dados = json.loads(conn.execute("SELECT config_json FROM project").fetchone()[0])
    dados["classification_engine"] = motor
    conn.execute("UPDATE project SET config_json = ?", (json.dumps(dados),))
    conn.commit()
    conn.close()


def test_projeto_salvo_com_claude_code_abre_e_vira_automatico(cliente, tmp_path):
    from gclaude_indexer.catalog import find_project
    from gclaude_indexer.project import load_project

    projeto_id = _criar_projeto(cliente, tmp_path, nome="Projeto Antigo", classification_engine="rules")
    _gravar_motor_antigo(projeto_id, "claude_code")

    tela = cliente.get(f"/projects/{projeto_id}/run")

    assert tela.status_code == 200
    assert "processe as janelas" not in tela.text
    assert "Reverificar" not in tela.text
    config, conn = load_project(find_project(projeto_id).output_folder)
    assert config.classification_engine == "automatic"
    avisos = conn.execute(
        "SELECT COUNT(*) FROM event WHERE message_key = 'log.project.classification_engine_converted'"
    ).fetchone()[0]
    conn.close()
    assert avisos == 1  # aviso único, mesmo com várias aberturas
    # Gravado: a próxima abertura já encontra "automatic" no banco.
    cliente.get(f"/projects/{projeto_id}/run")
    config, conn = load_project(find_project(projeto_id).output_folder)
    assert conn.execute(
        "SELECT COUNT(*) FROM event WHERE message_key = 'log.project.classification_engine_converted'"
    ).fetchone()[0] == 1
    conn.close()


def test_janelas_ja_respondidas_no_claude_code_nao_sao_refeitas(cliente, tmp_path):
    import json
    from pathlib import Path

    from gclaude_indexer.catalog import find_project
    from gclaude_indexer.project import load_project

    projeto_id = _criar_projeto(cliente, tmp_path, nome="Projeto CC Sync", classification_engine="rules")
    for etapa in ("scan", "conversion", "extraction", "windows"):
        cliente.post(f"/projects/{projeto_id}/run-next")
        _esperar_etapa_terminar(projeto_id, etapa)

    entry = find_project(projeto_id)
    config, conn = load_project(entry.output_folder)
    chave = conn.execute("SELECT key FROM window").fetchone()["key"]
    agrupador = conn.execute("SELECT group_key FROM window").fetchone()["group_key"]
    conn.close()
    peca = {
        "window": chave, "group": agrupador, "ref_start": "f. 1", "ref_end": "f. 1",
        "order_start": 1, "order_end": 1, "type": "OFÍCIO", "date": "2024-01-10", "author": None,
        "summary": "resumo", "has_table": False, "has_image": False, "engine": "claude_code",
        "confidence": "high", "files": "peca.pdf",
    }
    (Path(entry.output_folder) / "raw_items.jsonl").write_text(json.dumps(peca) + "\n", encoding="utf-8")
    _gravar_motor_antigo(projeto_id, "claude_code")

    config, conn = load_project(entry.output_folder)
    status = conn.execute("SELECT status FROM window WHERE key = ?", (chave,)).fetchone()["status"]
    conn.close()
    assert config.classification_engine == "automatic"
    assert status == "done"


def test_rota_de_reverificar_do_claude_code_nao_existe_mais(cliente, tmp_path):
    projeto_id = _criar_projeto(cliente, tmp_path, nome="Projeto Rota", classification_engine="rules")
    assert cliente.post(f"/projects/{projeto_id}/claude-code/recheck").status_code in (404, 405)


# --- tela: Resultado -----------------------------------------------------


def test_resultado_mostra_os_quatro_artefatos_e_pendencias(cliente, tmp_path):
    projeto_id = _criar_projeto(cliente, tmp_path)
    cliente.post(f"/projects/{projeto_id}/run-all")
    _esperar_etapa_terminar(projeto_id, "classification")
    cliente.post(f"/projects/{projeto_id}/import-and-generate", follow_redirects=False)

    resposta = cliente.get(f"/projects/{projeto_id}/result")
    assert resposta.status_code == 200
    for titulo in ("Índice", "Cronologia", "Conferência", "Instruções do projeto"):
        assert titulo in resposta.text
    # Tarefa 11 (Fase 14): nome de arquivo fixo em inglês, qualquer que seja
    # o idioma da prévia — é o que o próprio sistema lê de volta e o que o
    # usuário abre no Explorer.
    for nome_arquivo in ("index.md", "timeline.md", "review.md", "project_instructions.md"):
        assert nome_arquivo in resposta.text


def test_resultado_pre_visualiza_artefatos_traduzidos_no_idioma_do_cookie(cliente, tmp_path):
    """A prévia (Tarefa 11, Fase 14) segue o cookie `language`: título e
    conteúdo do artefato aparecem no idioma escolhido, com os mesmos quatro
    nomes de arquivo fixos em inglês."""
    projeto_id = _criar_projeto(cliente, tmp_path)
    cliente.post(f"/projects/{projeto_id}/run-all")
    _esperar_etapa_terminar(projeto_id, "classification")
    cliente.cookies.set("language", "en")
    cliente.post(f"/projects/{projeto_id}/import-and-generate", follow_redirects=False)

    resposta = cliente.get(f"/projects/{projeto_id}/result")
    assert resposta.status_code == 200
    for titulo in ("Index", "Timeline", "Review", "Project instructions"):
        assert titulo in resposta.text
    for nome_arquivo in ("index.md", "timeline.md", "review.md", "project_instructions.md"):
        assert nome_arquivo in resposta.text
    assert "Índice" not in resposta.text
    assert "Cronologia" not in resposta.text


def test_resultado_antes_de_qualquer_execucao_avisa_artefato_ausente(cliente, tmp_path):
    projeto_id = _criar_projeto(cliente, tmp_path)
    resposta = cliente.get(f"/projects/{projeto_id}/result")
    assert "Ainda não gerado" in resposta.text


# --- 2.0.0: sobras do motor Claude Code ------------------------------------


def test_formulario_recusa_o_motor_claude_code(cliente, tmp_path):
    origem = tmp_path / "origem_cc"
    origem.mkdir()
    resposta = cliente.post(
        "/projects/new",
        data={
            "name": "CC", "subject": "x", "source_folder": str(origem),
            "output_folder": str(tmp_path / "saida_cc"), "collection_type": "processo",
            "group_mode": "subfolder", "group_pattern": "", "extensions": ["pdf"],
            "classification_engine": "claude_code",
        },
        follow_redirects=False,
    )
    assert resposta.status_code == 400


def test_limpeza_das_janelas_so_toca_nomes_no_padrao(tmp_path):
    from gclaude_indexer.windows_prep import cleanup_legacy_window_files

    janelas = tmp_path / "windows"
    janelas.mkdir()
    antigos = ["volume_1_j0001-0016.txt", "volume_1_j0015-0030.txt", "grupo_x_j00001-00016.txt"]
    ficam = ["notas.txt", "volume_1_j1-16.txt", "volume_1_j0001-0016.txt.bak", "leia.md"]
    for nome in antigos + ficam:
        (janelas / nome).write_text("x", encoding="utf-8")
    (janelas / "pasta_j0001-0002.txt").mkdir()  # diretório com nome no padrão não é arquivo

    assert cleanup_legacy_window_files(tmp_path) == len(antigos)

    assert sorted(p.name for p in janelas.iterdir()) == sorted(ficam + ["pasta_j0001-0002.txt"])


def test_limpeza_das_janelas_remove_a_pasta_so_quando_fica_vazia(tmp_path):
    from gclaude_indexer.windows_prep import cleanup_legacy_window_files

    janelas = tmp_path / "windows"
    janelas.mkdir()
    (janelas / "a_j0001-0016.txt").write_text("x", encoding="utf-8")
    assert cleanup_legacy_window_files(tmp_path) == 1
    assert not janelas.exists()
    assert cleanup_legacy_window_files(tmp_path) == 0  # sem pasta, nada a fazer

    janelas.mkdir()
    (janelas / "a_j0001-0016.txt").write_text("x", encoding="utf-8")
    (janelas / "meu.docx").write_text("do usuário", encoding="utf-8")
    assert cleanup_legacy_window_files(tmp_path) == 1
    assert (janelas / "meu.docx").read_text(encoding="utf-8") == "do usuário"


def test_limpeza_das_janelas_respeita_o_parar(tmp_path):
    from gclaude_indexer.windows_prep import cleanup_legacy_window_files

    janelas = tmp_path / "windows"
    janelas.mkdir()
    (janelas / "a_j0001-0016.txt").write_text("x", encoding="utf-8")

    assert cleanup_legacy_window_files(tmp_path, should_stop=lambda: True) == 0
    assert (janelas / "a_j0001-0016.txt").exists()


def test_importar_e_gerar_limpa_as_janelas_antigas_e_escreve_o_claude_md(cliente, tmp_path):
    from pathlib import Path

    from gclaude_indexer.catalog import find_project

    projeto_id = _criar_projeto(cliente, tmp_path, nome="Projeto Limpeza")
    saida = Path(find_project(projeto_id).output_folder)
    janelas = saida / "windows"
    janelas.mkdir()
    (janelas / "volume_1_j0001-0016.txt").write_text("velho", encoding="utf-8")
    (saida / "CLAUDE.md").write_text(
        "# GClaude Indexer — classificação das janelas (X)" + chr(10) + "motor `claude_code`" + chr(10),
        encoding="utf-8",
    )
    for etapa in ("scan", "conversion", "extraction", "windows", "classification"):
        cliente.post(f"/projects/{projeto_id}/run-next")
        _esperar_etapa_terminar(projeto_id, etapa)

    cliente.post(f"/projects/{projeto_id}/import-and-generate", follow_redirects=False)
    fim = time.monotonic() + 30
    while time.monotonic() < fim and (janelas.exists() or "buscar.bat" not in (saida / "CLAUDE.md").read_text(encoding="utf-8")):
        time.sleep(0.1)

    assert not janelas.exists()
    texto = (saida / "CLAUDE.md").read_text(encoding="utf-8")
    assert "buscar.bat" in texto and "claude_code" not in texto
