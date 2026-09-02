"""Phase 14 tests: default language from Windows (Task 10), output files and CLAUDE.md in the system language (Task 11)."""

from __future__ import annotations

from gclaude_indexer.artifacts import (
    INDEX_FILENAME,
    PROJECT_INSTRUCTIONS_FILENAME,
    REVIEW_FILENAME,
    TIMELINE_FILENAME,
    generate_all_artifacts,
    generate_index_md,
)
from gclaude_indexer.config import load_config
from gclaude_indexer.db import connect, init_schema
from gclaude_indexer.engine_claude_code import USER_COMMANDS, command_for_language
from gclaude_indexer.system_locale import (
    FALLBACK_LANGUAGE,
    _detect_windows_locale,
    _locale_family,
    detect_ui_language,
)
from gclaude_indexer.windows_prep import generate_claude_md


# --- Tarefa 10: mapeamento de locale do Windows para família de idioma ------


def test_locale_conhecido_mapeia_para_a_familia_certa():
    assert _locale_family("pt_BR") == "pt"
    assert _locale_family("en_US") == "en"
    assert _locale_family("es_MX") == "es"
    assert _locale_family("es_ES") == "es"


def test_pt_pt_mapeia_para_pt():
    """A interface só tem textos em português do Brasil (`web/i18n.py`) —
    `pt_PT` (Portugal) cai na mesma família, não em inglês."""
    assert _locale_family("pt_PT") == "pt"


def test_locale_desconhecido_cai_em_ingles():
    assert _locale_family("ja_JP") == "en"
    assert _locale_family("de_DE") == "en"
    assert _locale_family(None) == "en"
    assert _locale_family("") == "en"


def test_fallback_e_ingles_nao_portugues():
    """Requisito do usuário: o último recurso, para um sistema cujo idioma
    não temos, é inglês — não português."""
    assert FALLBACK_LANGUAGE == "en"


def test_deteccao_publica_cai_em_ingles_quando_a_fonte_nao_responde(monkeypatch):
    """Simula um Windows que não responde nada utilizável: a função pública
    tem que cair em `en`, nunca subir uma exceção — ela roda na
    inicialização do servidor web (`web/i18n.py::DEFAULT_LANGUAGE`)."""
    import gclaude_indexer.system_locale as system_locale_mod

    # `conftest.py` pins the whole suite to `pt` through this variable, so
    # the override has to come off before the fallback can be observed at
    # all — otherwise this test would only ever prove the override works.
    monkeypatch.delenv(system_locale_mod.LANGUAGE_ENV_VAR, raising=False)
    monkeypatch.setattr(system_locale_mod, "_detect_windows_locale", lambda: None)
    assert system_locale_mod.detect_ui_language() == "en"


def test_variavel_de_ambiente_vence_a_deteccao_do_windows(monkeypatch):
    """A variável de ambiente existe para dois usos: alguém cujo Windows
    está num idioma diferente do que quer ver na interface, e a própria
    suíte, que precisa de asserções independentes do idioma da máquina que
    a roda. Valor não suportado é ignorado, não obedecido — assim um erro
    de digitação degrada para a detecção em vez de quebrar a interface."""
    import gclaude_indexer.system_locale as system_locale_mod

    monkeypatch.setattr(system_locale_mod, "_detect_windows_locale", lambda: "pt_BR")

    monkeypatch.setenv(system_locale_mod.LANGUAGE_ENV_VAR, "es")
    assert system_locale_mod.detect_ui_language() == "es"

    monkeypatch.setenv(system_locale_mod.LANGUAGE_ENV_VAR, "xx")
    assert system_locale_mod.detect_ui_language() == "pt"


def test_deteccao_interna_ignora_ctypes_indisponivel(monkeypatch):
    """Em qualquer máquina que não seja Windows (ex. rodando a suíte fora
    do Windows), `ctypes.windll` nem existe — `AttributeError`, capturada
    especificamente, não pode subir."""
    import ctypes

    import gclaude_indexer.system_locale as system_locale_mod

    if hasattr(ctypes, "windll"):
        monkeypatch.delattr(ctypes, "windll", raising=False)

    # Não deve levantar, mesmo que a segunda fonte (`getdefaultlocale`)
    # também não devolva nada usável no ambiente de teste.
    resultado = system_locale_mod._detect_windows_locale()
    assert resultado is None or isinstance(resultado, str)


def test_deteccao_real_nesta_maquina_devolve_string():
    """Não mocka nada: roda a detecção de verdade nesta máquina. Serve só
    para garantir que a função pública nunca lança e sempre devolve um dos
    três idiomas da interface."""
    resultado = detect_ui_language()
    assert resultado in ("pt", "en", "es")


# --- Tarefa 11: artefatos e CLAUDE.md no idioma do sistema ------------------


def _config_e_conn_vazios(tmp_path):
    """Só o necessário para gerar os artefatos sobre um acervo vazio — não
    precisa de varredura/conversão/extração real: os quatro geradores lidam
    com "nenhuma peça" sozinhos, e é exatamente esse texto (traduzido) que
    estes testes conferem."""
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    config = load_config(
        {"name": "Verificação i18n", "source_folder": str(origem), "output_folder": str(saida)}
    )
    conn = connect(saida / "project.db")
    init_schema(conn)
    return config, conn


def test_indice_em_ingles_nao_tem_texto_em_portugues(tmp_path):
    config, conn = _config_e_conn_vazios(tmp_path)

    conteudo = generate_index_md(conn, config, "en").read_text(encoding="utf-8")

    assert "# Index —" in conteudo
    assert "No item classified yet." in conteudo
    assert "Índice" not in conteudo
    assert "Nenhuma peça" not in conteudo

    conn.close()


def test_indice_em_espanhol_traduz_titulo_e_texto_vazio(tmp_path):
    config, conn = _config_e_conn_vazios(tmp_path)

    conteudo = generate_index_md(conn, config, "es").read_text(encoding="utf-8")

    assert "# Índice —" in conteudo  # "Índice" também é a palavra em espanhol
    assert "Ninguna pieza clasificada hasta el momento." in conteudo

    conn.close()


def test_generate_all_artifacts_mantem_nomes_de_arquivo_fixos_em_ingles(tmp_path):
    """Requisito do brief: nome de arquivo não muda com o idioma — só o
    conteúdo. Gera nos três idiomas e confere que é sempre o mesmo conjunto
    de quatro nomes em inglês."""
    config, conn = _config_e_conn_vazios(tmp_path)

    for language in ("pt", "en", "es"):
        caminhos = generate_all_artifacts(conn, config, language)
        assert {p.name for p in caminhos.values()} == {
            INDEX_FILENAME, TIMELINE_FILENAME, REVIEW_FILENAME, PROJECT_INSTRUCTIONS_FILENAME,
        }

    conn.close()


def _config_simples(tmp_path):
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    saida.mkdir()
    return load_config(
        {"name": "Verificação CLAUDE.md", "subject": "Acervo de teste", "source_folder": str(origem),
         "output_folder": str(saida)}
    )


def test_claude_md_documenta_as_tres_frases_gatilho_em_qualquer_idioma(tmp_path):
    """A armadilha real apontada pelo brief: se `CLAUDE.md` só documentasse
    a frase no idioma corrente, um usuário que gerou o arquivo num idioma e
    trocou a interface depois (ou só lembra a frase antiga) deixaria de ser
    reconhecido pelo motor `claude_code` externo — sem erro, sem teste
    falhando. A decisão tomada foi documentar as três frases como gatilhos
    válidos em qualquer idioma do arquivo."""
    config = _config_simples(tmp_path)

    for language in ("pt", "en", "es"):
        conteudo = generate_claude_md(config, language).read_text(encoding="utf-8")
        for frase in USER_COMMANDS.values():
            assert frase in conteudo, f"frase {frase!r} ausente do CLAUDE.md em {language!r}"


def test_claude_md_mantem_vocabulario_de_tipos_e_chaves_json_em_qualquer_idioma(tmp_path):
    """As chaves JSON do contrato (Tarefa 9e) e o vocabulário de tipos de
    documento (termos reais do acervo em português) não são prosa — ficam
    fixos em todo idioma; só a prosa ao redor muda."""
    config = _config_simples(tmp_path)

    for language in ("pt", "en", "es"):
        conteudo = generate_claude_md(config, language).read_text(encoding="utf-8")
        assert '"engine": "claude_code"' in conteudo
        assert '"confidence"' in conteudo
        assert "order_start" in conteudo and "order_end" in conteudo
        assert "OFÍCIO" in conteudo and "MEMORANDO" in conteudo


def test_command_for_language_cai_para_referencia_em_idioma_desconhecido():
    """Mesmo raciocínio de `translate()`/`_REFERENCE_LANGUAGE`: um idioma
    não reconhecido não pode quebrar o botão de copiar comando."""
    assert command_for_language("xx") == USER_COMMANDS["pt"]
    assert command_for_language("en") == "process the windows"


def test_web_i18n_reexporta_a_mesma_tabela_do_nucleo():
    """Confere a estrutura movida pela Tarefa 11: `web/i18n.py` não tem
    tabela própria — reexporta exatamente o objeto de `gclaude_indexer/i18n.py`,
    para que `artifacts.py` (núcleo) e a camada web sempre leiam a mesma
    fonte."""
    import gclaude_indexer.i18n as nucleo
    import gclaude_indexer.web.i18n as web

    assert web._TRANSLATIONS is nucleo._TRANSLATIONS
    assert web.translate is nucleo.translate
    assert web.valid_language is nucleo.valid_language


# --- defeito de produção encontrado na Tarefa 11 ----------------------------


def test_tela_de_execucao_escreve_o_claude_md_do_motor_claude_code(tmp_path, monkeypatch):
    """Regressão de um defeito que a suíte não pegava: `start_all()` pula a
    etapa de classificação quando o motor é `claude_code`, e nada mais na
    aplicação chamava `prepare()` — só os testes. Resultado: o `CLAUDE.md`
    nunca chegava ao disco, e a tela mandava o usuário digitar o comando
    num Claude Code que não tinha instrução nenhuma para ler. O motor era
    inutilizável de ponta a ponta com todos os seus próprios testes verdes.

    Aqui a tela de execução é aberta de verdade, e o que se cobra é o
    arquivo existir depois disso."""
    import gclaude_indexer.catalog as catalogo_mod
    import gclaude_indexer.hardware as hardware_mod
    from fastapi.testclient import TestClient
    from gclaude_indexer.catalog import find_project
    from gclaude_indexer.web.app import app
    from gclaude_indexer.windows_prep import CLAUDE_MD_FILENAME
    from pathlib import Path

    monkeypatch.setattr(catalogo_mod, "machine_local_folder", lambda: tmp_path / "local")
    monkeypatch.setattr(hardware_mod, "machine_local_folder", lambda: tmp_path / "local")
    cliente = TestClient(app)

    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    resposta = cliente.post(
        "/projects/new",
        data={
            "name": "Projeto CLAUDE.md", "subject": "Acervo de teste",
            "source_folder": str(origem), "output_folder": str(saida),
            "collection_type": "processo", "group_mode": "subfolder", "group_pattern": "",
            "extensions": ["pdf"], "pages_per_block": "80", "pages_per_window": "16",
            "overlap": "2", "chars_per_page": "2000", "ocr_language": "por",
            "classification_engine": "claude_code", "local_model": "automatic",
            "role_instructions": "", "extra_rules": "",
        },
        follow_redirects=False,
    )
    assert resposta.status_code == 303, resposta.text
    projeto_id = int(resposta.headers["location"].split("/")[2])

    claude_md = Path(find_project(projeto_id).output_folder) / CLAUDE_MD_FILENAME
    assert not claude_md.exists(), "pré-condição: o arquivo ainda não deve existir"

    assert cliente.get(f"/projects/{projeto_id}/run").status_code == 200

    assert claude_md.exists(), (
        "a tela de execução do motor `claude_code` não escreveu o CLAUDE.md — "
        "o usuário veria o comando para digitar sem o arquivo que o instrui"
    )


def test_arquivos_nao_python_nao_citam_modulos_inexistentes():
    """Regressão de um defeito que nenhuma auditoria desta fase pegou: o
    instalador PowerShell embute uma linha `python -c "from gclaude_indexer
    ... import ..."`. As renomeações de módulo desta fase varreram `.py`,
    `.html` e `.css` — nunca `.ps1` —, então a referência ficou apontando
    para `gclaude_indexer.motor_local.MODELO_LOCAL_PADRAO`, que deixou de
    existir. O instalador quebrava com código 1 em qualquer máquina com
    Ollama, e a suíte inteira continuava verde.

    Este teste importa de verdade tudo que os arquivos não-Python dizem
    importar, para que a próxima renomeação não possa repetir isso em
    silêncio."""
    import importlib
    import re
    from pathlib import Path

    raiz = Path(__file__).resolve().parent.parent
    padrao = re.compile(r"from\s+(gclaude_indexer[\w.]*)\s+import\s+([\w, ]+)")

    verificados = 0
    for arquivo in list(raiz.glob("*.ps1")) + list(raiz.glob("*.bat")) + list(raiz.glob("*.vbs")):
        for modulo, nomes in padrao.findall(arquivo.read_text(encoding="utf-8", errors="replace")):
            importado = importlib.import_module(modulo)
            for nome in (n.strip() for n in nomes.split(",") if n.strip()):
                assert hasattr(importado, nome), (
                    f"{arquivo.name} importa {nome!r} de {modulo!r}, que não existe mais"
                )
                verificados += 1

    assert verificados > 0, (
        "nenhuma referência encontrada — se o instalador deixou de embutir Python, "
        "remova este teste; se o padrão de busca deixou de casar, corrija-o"
    )
