# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Fase 19: o instalador do Windows e os scripts que ele chama.

Estes testes exercitam PowerShell, não Python: o instalador é uma casca
em volta do `install.ps1`, e o que pode quebrar em silêncio mora do lado
de lá — um cmdlet que some do ambiente por causa de outra versão do
PowerShell instalada, ou um catálogo de projetos tratado como cache.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
POWERSHELL = "powershell"


def _rodar_ps(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True, text=True, timeout=180,
    )


# --- o catálogo de projetos não é lixo de instalação ------------------------


def _confirm_step(argumentos: str, extra: str = "") -> str:
    """Chama `Confirm-Step` isoladamente, sem executar o desinstalador.

    `uninstall.ps1` roda ao ser carregado, então o teste precisa de uma
    porta explícita para só definir as funções e voltar.
    """
    script = (
        f". '{RAIZ / 'uninstall.ps1'}' -DryRunContract {extra}; "
        f"if (Confirm-Step -Title 'x' {argumentos}) {{ 'REMOVE' }} else {{ 'MANTEM' }}"
    )
    # `Confirm-Step` also prints the title and the reason for its answer,
    # which is the point of it — the verdict is the last line.
    linhas = [l for l in _rodar_ps(script).stdout.splitlines() if l.strip()]
    return linhas[-1].strip() if linhas else ""


def test_o_catalogo_de_projetos_sobrevive_a_desinstalacao_padrao():
    """O `projects.json` é a lista dos acervos do usuário. Perdê-lo não
    apaga acervo nenhum, mas obriga a pessoa a lembrar onde cada um estava
    e reapontar um por um. Foi o que aconteceu numa desinstalação real."""
    assert _confirm_step("-IsUserData", "-KeepDependencies") == "MANTEM"


def test_nem_o_remove_all_apaga_dados_do_usuario():
    """`-RemoveAll` é o que a caixa 'remover também as dependências' do
    desinstalador do Windows aciona, e essa caixa fala de Tesseract,
    Ghostscript, Ollama e Python — não da lista de projetos."""
    assert _confirm_step("-IsUserData", "-RemoveAll") == "MANTEM"


def test_dados_do_usuario_saem_so_quando_pedidos_explicitamente():
    assert _confirm_step("-IsUserData", "-RemoveUserData") == "REMOVE"


def test_estado_de_instalacao_continua_saindo_com_keep_dependencies():
    """A correção não pode transformar o desinstalador em algo que não
    desinstala: o que pertence a esta instalação continua saindo."""
    assert _confirm_step("", "-KeepDependencies") == "REMOVE"


def test_dependencia_compartilhada_continua_preservada():
    assert _confirm_step("-IsSharedDependency", "-KeepDependencies") == "MANTEM"


def test_o_catalogo_nao_esta_na_lista_de_estado_descartavel():
    """Guarda estrutural: mesmo que a decisão acima mude, o arquivo não
    pode voltar a ser tratado como cache."""
    texto = (RAIZ / "uninstall.ps1").read_text(encoding="utf-8")
    inicio = texto.find("Installation state")
    assert inicio != -1, "bloco de estado de instalação não encontrado"
    bloco = texto[inicio:inicio + 900]

    assert "projects.json" not in bloco
    assert "settings.json" not in bloco
    assert "tools.json" in bloco
