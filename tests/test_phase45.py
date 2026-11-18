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
"""2.0.0: versão, documentação e texto de interface sobre o funcionamento offline.

A 2.0.0 é uma versão maior entregue de uma vez. Estes testes guardam o que o
Task 16 fecha: o número da versão e o nome do instalador nos READMEs, a entrada
do CHANGELOG nos três idiomas, as seções novas do manual, o SECURITY.md sobre
os downloads sob demanda e a retirada da promessa de "funciona offline" que o
texto da interface fazia sem as ressalvas dos componentes opcionais.
"""
from __future__ import annotations

import re
from pathlib import Path

from gclaude_indexer import i18n

_RAIZ = Path(__file__).resolve().parents[1]
_MANUAL = _RAIZ / "gclaude_indexer" / "web" / "templates" / "manual"


def _texto(rel: str) -> str:
    return (_RAIZ / rel).read_text(encoding="utf-8")


def test_versao_do_sistema_e_nome_do_instalador():
    from gclaude_indexer.web.app import SYSTEM_VERSION

    assert SYSTEM_VERSION == "2.1.0"
    instalador = f"GClaude-Indexer-Setup-{SYSTEM_VERSION}.exe"
    for leiame in ("README.md", "docs/README.pt-BR.md", "docs/README.es.md"):
        assert instalador in _texto(leiame), leiame
        assert "Setup-1.10" not in _texto(leiame), leiame


def test_changelog_tem_a_entrada_2_0_0_com_quebras_e_migracoes():
    # Cada registro: a entrada vem antes da 1.10.4 e cita o que quebra e a migração.
    esperado = {
        "CHANGELOG.md": ("-AI", "Folder move", "Claude Code (manual)", "Review low confidence", "15%", "components.py"),
        "docs/CHANGELOG.pt-BR.md": ("-AI", "Mudança de pasta", "Claude Code (manual)", "Revisar confiança baixa", "15%", "components.py"),
        "docs/CHANGELOG.es.md": ("-AI", "Cambio de carpeta", "Claude Code (manual)", "Revisar confianza baja", "15%", "components.py"),
    }
    for registro, trechos in esperado.items():
        texto = _texto(registro)
        assert "## [2.0.0]" in texto and texto.index("## [2.0.0]") < texto.index("## [1.10.4]"), registro
        entrada = texto[texto.index("## [2.0.0]"): texto.index("## [1.10.4]")]
        for trecho in trechos:
            assert trecho in entrada, (registro, trecho)


def test_manual_tem_as_secoes_da_2_0_0_nos_tres_idiomas():
    for idioma in ("pt", "en", "es"):
        texto = (_MANUAL / f"{idioma}.html").read_text(encoding="utf-8")
        for secao in ("formatos", "idiomas", "mudanca-de-pasta"):
            assert f'id="{secao}"' in texto and f'href="#{secao}"' in texto, (idioma, secao)
        # Nada do que saiu na 2.0.0 pode voltar a ser ensinado como opção.
        for frase in ("processe as janelas", "process the windows", "procese las ventanas"):
            assert frase not in texto, (idioma, frase)
        # A numeração dos títulos é sequencial (o sumário é gerado na mesma ordem).
        numeros = [int(n) for n in re.findall(r"<h2>(\d+)\. ", texto)]
        assert numeros == list(range(1, len(numeros) + 1)), (idioma, numeros)


def test_security_descreve_os_downloads_sob_demanda_sem_exagero():
    texto = _texto("SECURITY.md")
    for trecho in ("LibreOffice 26.2.7", "SHA-256", "HTTPS", "FFmpeg", "whisper.cpp b5454", "HEVC", "LGPL", "py3langid", "BSD-3-Clause", "macros"):
        assert trecho in texto, trecho
    # A garantia do hash tem limite declarado, e não se promete "nunca sai nada".
    assert "not that the upstream project is free of flaws" in texto
    assert "offline-by-default" not in texto


def test_texto_da_interface_nao_promete_funcionar_offline_sem_ressalva():
    for idioma, ressalva in (("pt", "download único"), ("en", "one-time download"), ("es", "descarga única")):
        texto = i18n.translate(idioma, "about.description")
        assert "offline" not in texto.lower(), idioma
        assert ressalva in texto, idioma


def test_ajuda_do_todos_diz_o_que_acontece_ao_desmarcar():
    for idioma, trecho in (("pt", "desmarcar uma só categoria"), ("en", "unchecking a single category"),
                           ("es", "desmarcar una sola categoría")):
        assert trecho in i18n.translate(idioma, "new_project.extensions_help_all"), idioma
