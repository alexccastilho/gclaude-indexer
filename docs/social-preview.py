# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Gera a imagem de prévia social do repositório a partir de `logo.png`.

Rode com o venv do projeto, da raiz do repositório:

    .\\venv\\Scripts\\python.exe docs\\social-preview.py

São 1280x640, o formato que o GitHub pede em Settings > General > Social
preview. A imagem precisa funcionar em dois tamanhos muito diferentes:
grande numa aba do navegador e minúscula num cartão de link do WhatsApp.
Daí o título em peso Black, o espaçamento manual nas maiúsculas — que
colam e viram borrão quando a imagem é reduzida — e a regra de não
escrever nada que só se leia na versão grande.

Duas versões, porque os canais são dois. A do repositório está em inglês,
acompanhando o README principal e a descrição. A em português é para o
downivo, o TabNews e o r/brdev, onde a imagem entra no corpo do post.

Existe aqui, versionado, para que a próxima versão não dependa de alguém
lembrar as medidas.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

RAIZ = Path(__file__).resolve().parent.parent
DOCS = RAIZ / "docs"
FONTES = Path("C:/Windows/Fonts")

LARGURA, ALTURA = 1280, 640

# A paleta sai da própria logo: turquesa, dourado e roxo sobre o mesmo
# fundo escuro que o tema escuro do sistema usa.
FUNDO = (22, 20, 27)
TURQUESA = (95, 213, 192)
DOURADO = (224, 180, 79)
ROXO = (150, 90, 220)
TITULO_COR = (245, 243, 248)
CORPO_COR = (163, 155, 178)
FRACO = (108, 101, 121)

# Coluna do texto, à direita da logo.
X_TEXTO = 508
ENDERECO_PROJETO = "github.com/alexccastilho/gclaude-indexer"


def _fonte(arquivo: str, tamanho: int) -> ImageFont.FreeTypeFont:
    caminho = FONTES / arquivo
    if not caminho.is_file():
        raise SystemExit(f"fonte não encontrada: {caminho}")
    return ImageFont.truetype(str(caminho), tamanho)


def compor(primeira_linha: str, segunda_linha: str, selos: tuple[str, ...],
           saida: str) -> Path:
    titulo = _fonte("seguibl.ttf", 78)
    linha = _fonte("segoeuisl.ttf", 33)
    rodape = _fonte("seguisb.ttf", 20)
    endereco = _fonte("segoeui.ttf", 19)

    imagem = Image.new("RGB", (LARGURA, ALTURA), FUNDO)

    # Uma mancha de luz atrás da marca, não um degradê de ponta a ponta:
    # dá profundidade sem competir com o texto.
    brilho = Image.new("RGB", (LARGURA, ALTURA), FUNDO)
    pincel = ImageDraw.Draw(brilho)
    pincel.ellipse([40, 60, 560, 580], fill=(40, 58, 62))
    pincel.ellipse([160, 220, 620, 680], fill=(48, 36, 62))
    imagem = Image.blend(imagem, brilho.filter(ImageFilter.GaussianBlur(110)), 0.85)

    logo = Image.open(RAIZ / "logo.png").convert("RGBA")
    logo = logo.resize((330, 330), Image.LANCZOS)
    imagem.paste(logo, (104, (ALTURA - 330) // 2), logo)

    desenho = ImageDraw.Draw(imagem)
    desenho.text((X_TEXTO, 208), "GClaude Indexer", font=titulo, fill=TITULO_COR)
    desenho.text((X_TEXTO, 312), primeira_linha, font=linha, fill=CORPO_COR)
    desenho.text((X_TEXTO, 356), segunda_linha, font=linha, fill=CORPO_COR)

    def espacado(x: float, y: int, texto: str, fonte, cor, espaco: int = 3) -> float:
        """Maiúsculas coladas viram um borrão quando a imagem é reduzida."""
        for caractere in texto:
            desenho.text((x, y), caractere, font=fonte, fill=cor)
            x += desenho.textlength(caractere, font=fonte) + espaco
        return x

    fim = X_TEXTO
    for indice, selo in enumerate(selos):
        if indice:
            fim = espacado(fim + 10, 428, "·", rodape, CORPO_COR) + 10
        fim = espacado(fim, 428, selo, rodape, TURQUESA)

    # O endereço, discreto e no canto: a imagem costuma chegar acompanhada
    # do link, mas quando é reaproveitada num post ela vai sozinha.
    largura_endereco = desenho.textlength(ENDERECO_PROJETO, font=endereco)
    desenho.text((LARGURA - 104 - largura_endereco, 556), ENDERECO_PROJETO,
                 font=endereco, fill=FRACO)

    # Faixa da marca na base, nas cores da logo lidas da esquerda para a
    # direita.
    faixa = 7
    for x in range(LARGURA):
        posicao = x / (LARGURA - 1)
        if posicao < 0.5:
            proporcao, origem, destino = posicao / 0.5, TURQUESA, DOURADO
        else:
            proporcao, origem, destino = (posicao - 0.5) / 0.5, DOURADO, ROXO
        cor = tuple(
            round(origem[canal] + (destino[canal] - origem[canal]) * proporcao)
            for canal in range(3)
        )
        desenho.line([(x, ALTURA - faixa), (x, ALTURA)], fill=cor)

    destino_arquivo = DOCS / saida
    imagem.save(destino_arquivo, format="PNG", optimize=True)
    return destino_arquivo


def main() -> int:
    SELOS = ("WINDOWS", "100% OFFLINE", "GPL-3.0")

    gerados = [
        compor(
            "A folder of documents becomes an index,",
            "a timeline and Claude-ready instructions.",
            SELOS,
            "social-preview.png",
        ),
        compor(
            "Uma pasta de documentos vira índice,",
            "cronologia e instruções para o Claude.",
            SELOS,
            "social-preview-pt-BR.png",
        ),
    ]

    for caminho in gerados:
        # O GitHub recusa acima de 1 MB.
        print(f"{caminho.name}: {caminho.stat().st_size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
