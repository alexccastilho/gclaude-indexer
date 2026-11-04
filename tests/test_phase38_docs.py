# GClaude Indexer — indexador local de acervos documentais para o Claude
# Copyright (C) 2026 Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""Fase 38, parte B: documentação para quem não é de TI.

"""
from __future__ import annotations

import re
from pathlib import Path

_RAIZ = Path(__file__).resolve().parents[1]

_READMES = {
    "pt": ("docs/README.pt-BR.md", "docs/TECHNICAL.pt-BR.md", 964, "Conjuntos"),
    "en": ("README.md", "docs/TECHNICAL.md", 929, "Sets"),
    "es": ("docs/README.es.md", "docs/TECHNICAL.es.md", 990, "Conjuntos"),
}

# Os tópicos recolhíveis da seção "Detalhes técnicos" dos READMEs anteriores à
# 1.8.0, copiados antes da reescrita. Critério 5 da spec (4.6): nenhum deles
# deixa de existir no TECHNICAL do idioma.
_TITULOS_ANTIGOS = {
    "pt": (
        "Requisitos em detalhe", "Instalando sem o instalador", "Rodando no dia a dia",
        "Os sensores da CPU e as ventoinhas", "Desinstalando em detalhe", "As telas do programa",
        "Mantendo um acervo atualizado", "Conseguindo uma boa classificação", "O que o índice garante",
        "Janelas, blocos e OCR", "Motores de classificação", "Arquivos de saída",
        "OCR e idioma dos documentos", "Rodando a suíte de testes", "Solução de problemas", "Documentação",
    ),
    "en": (
        "Requirements in detail", "Installing without the installer", "Running day to day",
        "The CPU sensors and the fans", "Uninstalling in detail", "The screens of the app",
        "Keeping a collection up to date", "Getting a good classification", "What the index guarantees",
        "Windows, blocks and OCR", "Classification engines", "Output files",
        "OCR and document languages", "Running the test suite", "Troubleshooting", "Documentation",
    ),
    "es": (
        "Requisitos en detalle", "Instalación sin el instalador", "Uso diario",
        "Los sensores de la CPU y los ventiladores", "Desinstalación en detalle", "Las pantallas del programa",
        "Mantener un acervo actualizado", "Lograr una buena clasificación", "Lo que garantiza el índice",
        "Ventanas, bloques y OCR", "Motores de clasificación", "Archivos de salida",
        "OCR e idioma de los documentos", "Ejecutar la suite de pruebas", "Solución de problemas", "Documentación",
    ),
}


def _texto(rel: str) -> str:
    return (_RAIZ / rel).read_text(encoding="utf-8")


def test_readmes_sao_menores_e_apontam_para_o_tecnico():
    for idioma, (leiame, tecnico, linhas_antes, conjuntos) in _READMES.items():
        texto = _texto(leiame)
        assert len(texto.splitlines()) < linhas_antes, (idioma, len(texto.splitlines()))
        assert Path(tecnico).name in texto, (idioma, "link para o TECHNICAL")
        assert "<details>" not in texto, (idioma, "os detalhes técnicos saíram do README")
        for trecho in ("demo/", "QUALITY", conjuntos, "actions/workflows/tests.yml/badge.svg"):
            assert trecho in texto, (idioma, trecho)


def test_tecnico_preserva_os_titulos_do_antigo_detalhes_tecnicos():
    for idioma, (_leiame, tecnico, _linhas, _conjuntos) in _READMES.items():
        texto = _texto(tecnico)
        titulos = set(re.findall(r"^## (.+)$", texto, re.M))
        for titulo in _TITULOS_ANTIGOS[idioma]:
            assert titulo in titulos, (idioma, titulo)
        assert "legislacao-<" not in texto, idioma
        for trecho in ("normas-citadas.md", "buscar.bat", "LLAMA_ARG_CACHE_RAM", "OLLAMA_FLASH_ATTENTION"):
            assert trecho in texto, (idioma, trecho)


_MANUAL = _RAIZ / "gclaude_indexer" / "web" / "templates" / "manual"
_SECOES_NOVAS = ("demonstracao", "acerto", "conjuntos", "normas-e-busca", "sensores", "pausa", "atualizar-programa")
_FRASES_RETIRADAS = (
    "legislacao-<", "legislacao-&lt;",
    "Planalto no pacote", "legislation in the package", "Planalto en el paquete",
)


def test_manual_cobre_as_secoes_da_1_8():
    """Spec 4.2: acervo de demonstração; o que esperar de acerto; conjuntos;
    normas citadas e busca; sensores e elevação; pausa e retomada;
    atualização do programa. E nada do que saiu na 1.8.0."""
    for idioma in ("pt", "en", "es"):
        texto = (_MANUAL / f"{idioma}.html").read_text(encoding="utf-8")
        for secao in _SECOES_NOVAS:
            assert f'id="{secao}"' in texto, (idioma, secao)
            assert f'href="#{secao}"' in texto, (idioma, secao, "sumário")
        for frase in _FRASES_RETIRADAS:
            assert frase not in texto, (idioma, frase)
        assert "normas-citadas.md" in texto and "buscar.bat" in texto, idioma


# --- Task 13: guarda contra regressão de linguagem (spec 4.5) ----------------

# Vocabulário inflado por idioma, da skill humanizer-token-optimizer-pt-br
# (pt) e das listas equivalentes em inglês e espanhol acertadas no plano.
_VOCABULARIO_INFLADO = {
    "pt": (
        "robusto", "crucial", "fundamental", "essencial", "abrangente", "inovador", "revolucionário",
        "impactante", "estratégico", "holístico", "disruptivo", "escalável", "transformador",
        "alavancar", "potencializar", "impulsionar", "otimizar", "maximizar", "jornada", "ecossistema",
        "pilar", "sinergia",
    ),
    "en": (
        "robust", "crucial", "seamless", "leverage", "empower", "cutting-edge", "game-changer",
        "holistic", "synergy", "journey", "ecosystem", "unlock", "delve",
    ),
    "es": (
        "robusto", "crucial", "fundamental", "innovador", "revolucionario", "impactante", "holístico",
        "disruptivo", "escalable", "transformador", "potenciar", "impulsar", "optimizar", "sinergia",
        "ecosistema",
    ),
}

# Os documentos sob a regra, por idioma. CHANGELOG, specs e planos ficam
# fora: são históricos (spec 4.5).
_DOCUMENTOS_SOB_A_REGRA = {
    "pt": ("docs/README.pt-BR.md", "docs/TECHNICAL.pt-BR.md", "demo/README.md", "tools/README.md",
           "gclaude_indexer/web/templates/manual/pt.html"),
    "en": ("README.md", "docs/TECHNICAL.md", "gclaude_indexer/web/templates/manual/en.html"),
    "es": ("docs/README.es.md", "docs/TECHNICAL.es.md", "gclaude_indexer/web/templates/manual/es.html"),
}

_BLOCO_DE_CODIGO = re.compile(r"```.*?```", re.S)
_CODIGO_EM_LINHA = re.compile(r"`[^`\n]*`")
# No manual (HTML), código é o conteúdo de <code>, <pre> e <kbd>, não só a tag.
_CODIGO_HTML = re.compile(r"<(code|pre|kbd)\b[^>]*>.*?</\1>", re.S)
_TAG_HTML = re.compile(r"<[^>]+>")
# Travessão ou meia-risca com espaço dos dois lados (aparte), e o hífen
# espaçado que o substitui ("palavra - palavra"); o hífen antes de número
# ou maiúscula fica de fora, porque aparece em intervalos e listas.
_APARTE = re.compile(r"\s[—–]\s|\s-\s(?=[a-záéíóúàâêôãõçñ])")
_ASPAS_CURVAS = re.compile(r"[“”‘’]")


def _prosa(texto: str) -> str:
    """O que sobra de um documento depois de tirar código, tabelas e tags:
    a parte em que a regra de linguagem vale."""
    texto = _BLOCO_DE_CODIGO.sub(" ", texto)
    texto = _CODIGO_EM_LINHA.sub(" ", texto)
    texto = _CODIGO_HTML.sub(" ", texto)
    texto = _TAG_HTML.sub(" ", texto)
    linhas = [linha for linha in texto.splitlines() if not linha.lstrip().startswith("|")]
    return "\n".join(linhas)


def _marcas_de_ia(texto: str, idioma: str) -> list[str]:
    """As violações da regra de linguagem num texto, como mensagens curtas.
    Lista vazia quer dizer texto limpo."""
    prosa = _prosa(texto)
    achados: list[str] = []
    for numero, linha in enumerate(prosa.splitlines(), start=1):
        if _APARTE.search(linha):
            achados.append(f"linha {numero}: travessão, meia-risca ou hífen como aparte: {linha.strip()[:80]}")
        if _ASPAS_CURVAS.search(linha):
            achados.append(f"linha {numero}: aspas curvas: {linha.strip()[:80]}")
        if "…" in linha:
            achados.append(f"linha {numero}: reticências em caractere único: {linha.strip()[:80]}")
        minusculas = linha.lower()
        for palavra in _VOCABULARIO_INFLADO[idioma]:
            if re.search(_flexoes(palavra), minusculas):
                achados.append(f"linha {numero}: vocabulário inflado '{palavra}': {linha.strip()[:80]}")
    return achados


def _flexoes(palavra: str) -> str:
    """Expressão que pega a palavra e as flexões de gênero e número:
    "robusto" pega robusta e robustos; "journey" pega journeys."""
    raiz = re.escape(palavra[:-1] if palavra.endswith("o") else palavra)
    return rf"(?<![\w-]){raiz}(?:[oa]s?|e?s)?(?![\w-])"


def test_detector_de_marcas_acha_aparte_aspas_reticencias_e_vocabulario():
    assert _marcas_de_ia("O prazo era curto — o time entregou.", "pt")
    assert _marcas_de_ia("O prazo era curto – o time entregou.", "pt")
    assert _marcas_de_ia("O prazo era curto - o time entregou.", "pt")
    assert _marcas_de_ia("Ele disse “sim” e saiu.", "pt")
    assert _marcas_de_ia("E depois… nada.", "pt")
    assert _marcas_de_ia("Uma solução robusta e escalável.", "pt")
    assert _marcas_de_ia("A seamless journey for the user.", "en")
    assert _marcas_de_ia("Una herramienta innovadora.", "es")
    # O que a regra deixa passar: intervalos, código, tabelas e tags.
    assert not _marcas_de_ia("Páginas 2 - 3 do volume; veja `a — b`.", "pt")
    assert not _marcas_de_ia("```\nx — y\n```\n| a — b |", "pt")
    assert not _marcas_de_ia('<p class="x">texto</p>', "pt")
    assert not _marcas_de_ia("O prazo era curto. O time entregou.", "pt")


def test_documentos_sem_marcas_de_ia():
    """Spec 4.5: README ×3, manual ×3, demo/README.md, tools/README.md e
    docs/TECHNICAL ×3 sem travessão ou meia-risca como aparte, sem aspas
    curvas, sem reticências em caractere único e sem vocabulário inflado."""
    problemas: list[str] = []
    for idioma, documentos in _DOCUMENTOS_SOB_A_REGRA.items():
        for documento in documentos:
            for achado in _marcas_de_ia(_texto(documento), idioma):
                problemas.append(f"{documento}: {achado}")
    assert not problemas, "\n".join(problemas)


# --- Task 13: versão 1.8.0 e documentos --------------------------------------


def test_versao_e_documentos_da_fase_38():
    app = _texto("gclaude_indexer/web/app.py")
    versao = re.search(r'^SYSTEM_VERSION = "(\d+)\.(\d+)\.(\d+)"$', app, re.M)
    assert versao, "SYSTEM_VERSION"
    numero = tuple(int(parte) for parte in versao.groups())
    assert numero >= (1, 8, 0), numero
    instalador = "GClaude-Indexer-Setup-{}.{}.{}.exe".format(*numero)
    for leiame in ("README.md", "docs/README.pt-BR.md", "docs/README.es.md"):
        assert instalador in _texto(leiame), (leiame, instalador)
    for registro in ("CHANGELOG.md", "docs/CHANGELOG.pt-BR.md", "docs/CHANGELOG.es.md"):
        texto = _texto(registro)
        assert "## [1.8.0]" in texto and texto.index("## [1.8.0]") < texto.index("## [1.7.5]"), registro
        for trecho in ("normas-citadas.md", "buscar.bat", "LexML", "TECHNICAL"):
            assert trecho in texto[: texto.index("## [1.7.5]")], (registro, trecho)
    especificacao = _texto("docs/SPECIFICATION.md")
    assert "test_phase38_docs.py" in especificacao, "critério de linguagem na SPECIFICATION"


def test_revisao_da_parte_b_corrigiu_as_afirmacoes_falsas():
    """Revisão independente da parte B: seis afirmações que os
    documentos faziam e o código não sustentava. Cada bloco abaixo é um achado;
    o teste guarda a forma corrigida para a frase não voltar numa retradução."""
    leiames = ("README.md", "docs/README.pt-BR.md", "docs/README.es.md")
    # Achado 6 (técnico) e 1 (leigo): "o índice sempre leva o Claude à página
    # certa" promete mais do que o QUALITY mede (só nenhuma página se perde).
    for leiame in leiames:
        texto = _texto(leiame)
        for promessa in ("sempre leva o Claude", "always takes Claude", "siempre lleva a Claude"):
            assert promessa not in texto, (leiame, promessa)
    # Achado 1 (técnico): o buscar.bat consulta o LexML sozinho quando nenhuma
    # norma do acervo cita o termo (spec 3.3); "opcional" sem essa condição
    # mente para o leitor da seção de privacidade.
    for leiame, condicao in zip(leiames, ("no act in the collection cites", "nenhuma norma do acervo cita",
                                           "ninguna norma del acervo cita")):
        texto = _texto(leiame)
        assert condicao in texto, (leiame, "condição do LexML na seção de privacidade")
        for frase in ("é opcional e envia", "is optional and sends", "es opcional y envía"):
            assert frase not in texto, (leiame, frase)
    for manual in ("pt", "en", "es"):
        texto = _texto(f"gclaude_indexer/web/templates/manual/{manual}.html")
        for frase in ("é opcional e envia", "is optional and sends", "es opcional y envía"):
            assert frase not in texto, (manual, frase)
    assert "no act in the collection cites" in _texto("SECURITY.md")
    assert "no act in the collection cites" in _texto("CONTRIBUTING.md")
    # Achados 2 e 3 (técnico): o CHANGELOG 1.8.0 falava em "link canônico do
    # Planalto" (é a URN do LexML) e anunciava como novo o índice em partes,
    # que existe desde a 1.6.0.
    for registro in ("CHANGELOG.md", "docs/CHANGELOG.pt-BR.md", "docs/CHANGELOG.es.md"):
        texto = _texto(registro)
        novo = texto[: texto.index("## [1.7.5]")]
        for frase in ("link canônico do Planalto", "link do Planalto", "canonical Planalto link",
                      "Planalto link;", "enlace canónico del Planalto", "enlace del Planalto"):
            assert frase not in novo, (registro, frase)
        assert "1.6.0" in novo[novo.index("INDEX_PART_BYTES") - 400: novo.index("INDEX_PART_BYTES") + 50], registro
    # Achado 4 (técnico): a frase-gatilho do Claude Code é traduzida
    # (`engine_claude_code.USER_COMMANDS`); o TECHNICAL en/es citava a portuguesa.
    assert "`process the windows`" in _texto("docs/TECHNICAL.md")
    assert "`procese las ventanas`" in _texto("docs/TECHNICAL.es.md")
    # Achados leigos 3, 4, 5 e 12: o instalador, o que é um Project e um token,
    # e como baixar o ZIP do acervo de demonstração.
    for leiame, trechos in {
        "docs/README.pt-BR.md": ("Dependências", "127.0.0.1:8000", "Download ZIP", "Token é", "Extensões incluídas"),
        "README.md": ("Dependencies", "127.0.0.1:8000", "Download ZIP", "token is", "Included extensions"),
        "docs/README.es.md": ("Dependencias", "127.0.0.1:8000", "Download ZIP", "token es", "Extensiones incluidas"),
    }.items():
        texto = _texto(leiame)
        for trecho in trechos:
            assert trecho in texto, (leiame, trecho)
