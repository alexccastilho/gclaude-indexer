"""As instruções geradas complementam as do usuário — nunca as substituem.

`project_instructions.md` e o `CLAUDE.md` da pasta de saída eram reescritos do
zero a cada geração: quem já tinha um `CLAUDE.md` naquela pasta, ou acrescentou
regras próprias ao arquivo gerado, perdia tudo na próxima atualização. Agora o
que o sistema escreve vive entre duas marcas, e o resto do arquivo é do usuário.
"""

from __future__ import annotations

from gclaude_indexer.artifacts import generate_project_instructions_md
from gclaude_indexer.config import load_config
from gclaude_indexer.db import connect, init_schema
from gclaude_indexer.managed_block import BEGIN_MARK, END_MARK, merge_managed
from gclaude_indexer.windows_prep import generate_claude_md


def _config(tmp_path, **extra):
    origem = tmp_path / "origem"
    origem.mkdir(exist_ok=True)
    saida = tmp_path / "saida"
    saida.mkdir(exist_ok=True)
    dados = {"name": "Acervo", "subject": "Tema do acervo",
             "source_folder": str(origem), "output_folder": str(saida)}
    dados.update(extra)
    return load_config(dados), saida


def _conn(saida):
    conn = connect(saida / "project.db")
    init_schema(conn)
    return conn


# --- a mesclagem em si ---------------------------------------------------------


def test_arquivo_novo_recebe_so_o_bloco():
    texto = merge_managed(None, "gerado")
    assert texto.startswith(BEGIN_MARK)
    assert "gerado" in texto
    assert texto.rstrip().endswith(END_MARK)


def test_texto_do_usuario_sem_marcas_fica_acima_do_bloco():
    texto = merge_managed("# Minhas regras\n\nResponda em tom formal.\n", "gerado")
    assert texto.index("Responda em tom formal.") < texto.index(BEGIN_MARK)
    assert "gerado" in texto


def test_regenerar_troca_so_o_que_esta_entre_as_marcas():
    primeira = merge_managed("antes do bloco\n", "versão 1")
    editada = primeira + "\ndepois do bloco\n"
    segunda = merge_managed(editada, "versão 2")
    assert "versão 1" not in segunda
    assert "versão 2" in segunda
    assert "antes do bloco" in segunda
    assert "depois do bloco" in segunda
    assert segunda.count(BEGIN_MARK) == 1 and segunda.count(END_MARK) == 1


def test_regenerar_e_idempotente():
    uma = merge_managed("minhas regras\n", "gerado")
    assert merge_managed(uma, "gerado") == uma


def test_arquivo_antigo_inteiramente_gerado_e_substituido():
    antigo = "# arquivo gerado por versão antiga\n"
    texto = merge_managed(antigo, "novo", is_legacy=lambda s: True)
    assert "versão antiga" not in texto
    assert "novo" in texto


def test_marca_de_fim_perdida_nao_duplica_o_bloco():
    quebrado = "minhas regras\n\n" + BEGIN_MARK + "\nlixo sem fim"
    texto = merge_managed(quebrado, "novo")
    assert texto.count(BEGIN_MARK) == 1
    assert "lixo sem fim" not in texto
    assert "minhas regras" in texto


def test_instrucoes_ja_usadas_entram_uma_vez_so():
    uma = merge_managed(None, "gerado", user_text="Regra que eu já usava.")
    duas = merge_managed(uma, "gerado", user_text="Regra que eu já usava.")
    assert duas.count("Regra que eu já usava.") == 1
    assert duas.index("Regra que eu já usava.") < duas.index(BEGIN_MARK)


# --- project_instructions.md ---------------------------------------------------


def test_project_instructions_preserva_regra_acrescentada_pelo_usuario(tmp_path):
    config, saida = _config(tmp_path)
    conn = _conn(saida)
    caminho = generate_project_instructions_md(conn, config, "pt")
    caminho.write_text(
        "Minha regra própria: cite sempre o volume.\n\n" + caminho.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    conteudo = generate_project_instructions_md(conn, config, "pt").read_text(encoding="utf-8")
    assert "Minha regra própria: cite sempre o volume." in conteudo
    assert "nunca do índice" in conteudo
    assert conteudo.count(BEGIN_MARK) == 1
    conn.close()


def test_project_instructions_inclui_instrucoes_que_o_usuario_ja_usa(tmp_path):
    config, saida = _config(tmp_path, existing_instructions="Sou advogado; responda com fundamento legal.")
    conn = _conn(saida)
    conteudo = generate_project_instructions_md(conn, config, "pt").read_text(encoding="utf-8")
    assert conteudo.index("responda com fundamento legal") < conteudo.index(BEGIN_MARK)
    conn.close()


def test_project_instructions_de_versao_antiga_e_atualizado_sem_duplicar(tmp_path):
    config, saida = _config(tmp_path)
    conn = _conn(saida)
    caminho = generate_project_instructions_md(conn, config, "pt")
    # Simula o arquivo de uma versão anterior: o mesmo conteúdo, sem marcas.
    corpo = caminho.read_text(encoding="utf-8")
    sem_marcas = corpo.replace(BEGIN_MARK + "\n", "").replace(END_MARK + "\n", "")
    caminho.write_text(sem_marcas, encoding="utf-8")

    conteudo = generate_project_instructions_md(conn, config, "pt").read_text(encoding="utf-8")
    assert conteudo.count("nunca do índice") == 1
    conn.close()


# --- CLAUDE.md -----------------------------------------------------------------


def test_claude_md_existente_do_usuario_nao_e_apagado(tmp_path):
    config, saida = _config(tmp_path)
    meu = "# Meu projeto\n\nUse sempre TypeScript estrito.\n"
    (saida / "CLAUDE.md").write_text(meu, encoding="utf-8")

    conteudo = generate_claude_md(config, "pt").read_text(encoding="utf-8")
    assert "Use sempre TypeScript estrito." in conteudo
    assert "processe as janelas" in conteudo
    # O original fica guardado antes da primeira mesclagem.
    assert (saida / "CLAUDE.md.bak").read_text(encoding="utf-8") == meu


def test_claude_md_regenerado_mantem_o_texto_do_usuario(tmp_path):
    config, saida = _config(tmp_path)
    (saida / "CLAUDE.md").write_text("Regra minha.\n", encoding="utf-8")
    generate_claude_md(config, "pt")
    conteudo = generate_claude_md(config, "en").read_text(encoding="utf-8")
    assert conteudo.count("Regra minha.") == 1
    assert "process the windows" in conteudo
    assert conteudo.count(BEGIN_MARK) == 1
