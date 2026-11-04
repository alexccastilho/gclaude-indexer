# GClaude Indexer: document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Gera a imagem de prévia social do repositório.

Rode com o venv do projeto, da raiz do repositório:

    .\\venv\\Scripts\\python.exe docs\\social-preview.py

São 1280x640, o formato que o GitHub pede em Settings > General > Social
preview, gravadas em `docs/media/`. As cores são as do tema Estúdio
escuro e as fontes são as que vão junto com o programa (Inter e
JetBrains Mono), então a imagem acompanha a interface. À direita entra a
captura da tela Execução (`docs/media/run-*.png`): refaça as capturas
antes, quando o visual mudar.

A imagem precisa funcionar grande numa aba do navegador e minúscula num
cartão de link: título pesado, selos espaçados e nada que só se leia na
versão grande.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

RAIZ = Path(__file__).resolve().parent.parent
DOCS = RAIZ / "docs" / "media"
FONTES = RAIZ / "gclaude_indexer" / "web" / "static" / "fonts"
VERSAO = "1.10"

LARGURA, ALTURA = 1280, 640

# Tema Estúdio escuro (style.css).
FUNDO = (20, 20, 19)
SUPERFICIE = (34, 34, 32)
BORDA = (47, 47, 43)
TEXTO = (236, 235, 230)
TEXTO_FRACO = (163, 162, 154)
DESTAQUE = (45, 212, 191)
DESTAQUE_FRACO = (19, 58, 53)

X_TEXTO = 72
ENDERECO_PROJETO = "github.com/alexccastilho/gclaude-indexer"


def _fonte(arquivo: str, tamanho: int, peso: int) -> ImageFont.FreeTypeFont:
    fonte = ImageFont.truetype(str(FONTES / arquivo), tamanho)
    fonte.set_variation_by_axes([peso])
    return fonte


def _inter(tamanho: int, peso: int) -> ImageFont.FreeTypeFont:
    return _fonte("inter-latin-wght-normal.woff2", tamanho, peso)


def _mono(tamanho: int, peso: int) -> ImageFont.FreeTypeFont:
    return _fonte("jetbrains-mono-latin-wght-normal.woff2", tamanho, peso)


def _cantos(imagem: Image.Image, raio: int) -> Image.Image:
    mascara = Image.new("L", imagem.size, 0)
    ImageDraw.Draw(mascara).rounded_rectangle([0, 0, *imagem.size], raio, fill=255)
    imagem.putalpha(mascara)
    return imagem


def compor(linhas: tuple[str, str], captura: str, saida: str) -> Path:
    imagem = Image.new("RGB", (LARGURA, ALTURA), FUNDO)

    # Um brilho turquesa fraco atrás da captura dá profundidade sem
    # competir com o texto.
    brilho = Image.new("RGB", (LARGURA, ALTURA), FUNDO)
    ImageDraw.Draw(brilho).ellipse([700, 40, 1400, 700], fill=DESTAQUE_FRACO)
    imagem = Image.blend(imagem, brilho.filter(ImageFilter.GaussianBlur(140)), 0.9)

    # A captura da interface, numa janela que sai pela borda direita.
    tela = Image.open(DOCS / captura).convert("RGB")
    largura_tela = 780
    tela = tela.resize((largura_tela, round(tela.height * largura_tela / tela.width)), Image.LANCZOS)
    x_tela, y_tela = 640, 118
    sombra = Image.new("L", (LARGURA, ALTURA), 0)
    ImageDraw.Draw(sombra).rounded_rectangle(
        [x_tela, y_tela + 18, x_tela + tela.width, y_tela + tela.height + 18], 16, fill=170
    )
    imagem.paste((0, 0, 0), (0, 0), sombra.filter(ImageFilter.GaussianBlur(26)))
    moldura = Image.new("RGB", (tela.width + 2, tela.height + 2), BORDA)
    imagem.paste(_cantos(moldura, 15), (x_tela - 1, y_tela - 1), moldura)
    tela = _cantos(tela.convert("RGB"), 14)
    imagem.paste(tela, (x_tela, y_tela), tela)

    desenho = ImageDraw.Draw(imagem)

    logo = Image.open(RAIZ / "logo.png").convert("RGBA").resize((76, 76), Image.LANCZOS)
    imagem.paste(logo, (X_TEXTO, 150), logo)

    desenho.text((X_TEXTO, 252), "GClaude", font=_inter(70, 760), fill=TEXTO)
    desenho.text((X_TEXTO, 328), "Indexer", font=_inter(70, 760), fill=TEXTO)
    corpo = _inter(25, 420)
    desenho.text((X_TEXTO, 428), linhas[0], font=corpo, fill=TEXTO_FRACO)
    desenho.text((X_TEXTO, 462), linhas[1], font=corpo, fill=TEXTO_FRACO)

    # Selos em fonte mono, numa pílula discreta cada.
    selo = _mono(16, 600)
    x = X_TEXTO
    for texto in ("WINDOWS", "OFFLINE", "GPL-3.0", VERSAO):
        largura = desenho.textlength(texto, font=selo) + 22
        desenho.rounded_rectangle([x, 520, x + largura, 550], 7, fill=SUPERFICIE, outline=BORDA)
        desenho.text((x + 11, 525), texto, font=selo, fill=DESTAQUE)
        x += largura + 10

    endereco = _inter(16, 450)
    desenho.text((X_TEXTO, 588), ENDERECO_PROJETO, font=endereco, fill=TEXTO_FRACO)

    # Faixa fina no topo, na cor de destaque.
    desenho.rectangle([0, 0, LARGURA, 4], fill=DESTAQUE)

    destino = DOCS / saida
    imagem.save(destino, format="PNG", optimize=True)
    return destino


def main() -> int:
    gerados = [
        compor(("A folder of documents becomes an index", "Claude can read, offline on your PC."),
               "run-en.png", "social-preview.png"),
        compor(("Uma pasta de documentos vira um índice", "que o Claude lê, sem sair do seu PC."),
               "run-pt.png", "social-preview-pt-BR.png"),
    ]
    for caminho in gerados:
        # O GitHub recusa acima de 1 MB.
        print(f"{caminho.name}: {caminho.stat().st_size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
