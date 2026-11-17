# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Gera o manifesto dos idiomas e escritas do `tessdata_fast` (2.0.0).

O gerenciador de componentes (`gclaude_indexer/components.py`) só baixa o
que estiver no manifesto, com SHA-256 conferido. O GitHub não publica
SHA-256 dos arquivos, só o SHA-1 do git: este script lista a árvore do
commit fixado, baixa cada `.traineddata` (raiz e `script/`) e calcula o
SHA-256 enquanto o arquivo passa, sem gravar nada em disco além do
manifesto e do progresso. É o **único** lugar do projeto que acessa a rede
para isso; a suíte de testes nunca o executa.

Antes de aceitar um hash, confere o tamanho e o SHA-1 do blob do git contra
a árvore — uma resposta truncada não fixa um hash errado — e recusa o
resultado se `por`, `eng`, `spa` ou `osd` não baterem com os hashes de
sempre (`install.ps1`).

    python tools/gerar_manifesto_tessdata.py
    python tools/gerar_manifesto_tessdata.py --progresso C:\\Temp\\tessdata-progresso.json

O progresso é retomável: o que já foi conferido não é baixado de novo.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

COMMIT = "65727574dfcd264acbb0c3e07860e4e9e9b22185"
REPO = "tesseract-ocr/tessdata_fast"
URL_ARVORE = f"https://api.github.com/repos/{REPO}/git/trees/{COMMIT}?recursive=1"
URL_ARQUIVO = f"https://raw.githubusercontent.com/{REPO}/{COMMIT}/"
DESTINO = RAIZ / "gclaude_indexer" / "manifests" / "tessdata_fast.json"
# Os quatro de sempre (`install.ps1` e 1.10.x): mudar qualquer um seria
# trocar o arquivo que as instalações existentes já conferiram.
HASHES_DE_SEMPRE = {
    "por": "c4932b937207a9514b7514d518b931a99938c02a28a5a5a553f8599ed58b7deb",
    "eng": "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2",
    "spa": "6f2e04d02774a18f01bed44b1111f2cd7f3ba7ac9dc4373cd3f898a40ea6b464",
    "osd": "9cf5d576fcc47564f11265841e5ca839001e7e6f38ff7f7aacf46d15a96b00ff",
}
_TEMPO_LIMITE_S = 300
_AGENTE = {"User-Agent": "gclaude-indexer-manifest-generator"}


def _abrir(url: str):
    return urllib.request.urlopen(urllib.request.Request(url, headers=_AGENTE), timeout=_TEMPO_LIMITE_S)


def _arvore() -> list[dict]:
    with _abrir(URL_ARVORE) as resposta:
        dados = json.load(resposta)
    if dados.get("truncated"):
        raise SystemExit("a árvore veio truncada pela API do GitHub")
    return [
        item for item in dados["tree"]
        if item["type"] == "blob" and item["path"].endswith(".traineddata")
        and item["path"].count("/") <= 1
        and (item["path"].count("/") == 0 or item["path"].startswith("script/"))
    ]


def _licenca() -> str:
    with _abrir(URL_ARQUIVO + "LICENSE") as resposta:
        texto = resposta.read(4096).decode("utf-8", "replace")
    if "Apache License" in texto and "Version 2.0" in texto:
        return "Apache-2.0"
    raise SystemExit("licença do tessdata_fast não reconhecida; confira o LICENSE do repositório")


def _conferir(item: dict) -> str:
    """SHA-256 do arquivo, depois de conferir tamanho e SHA-1 do blob."""
    tamanho = int(item["size"])
    sha256 = hashlib.sha256()
    blob = hashlib.sha1(f"blob {tamanho}\0".encode("ascii"))
    lidos = 0
    with _abrir(URL_ARQUIVO + item["path"]) as resposta:
        for bloco in iter(lambda: resposta.read(1 << 20), b""):
            lidos += len(bloco)
            if lidos > tamanho:
                raise ValueError(f"{item['path']}: maior que o tamanho da árvore")
            sha256.update(bloco)
            blob.update(bloco)
    if lidos != tamanho:
        raise ValueError(f"{item['path']}: {lidos} bytes, a árvore diz {tamanho}")
    if blob.hexdigest() != item["sha"]:
        raise ValueError(f"{item['path']}: SHA-1 do blob não confere com a árvore")
    return sha256.hexdigest()


def _entrada(item: dict, sha256: str, licenca: str) -> dict:
    caminho = item["path"]
    idioma = caminho[: -len(".traineddata")]
    return {
        "name": f"tessdata/{idioma}",
        "url": URL_ARQUIVO + caminho,
        "sha256": sha256,
        "size": int(item["size"]),
        "license": licenca,
        "kind": "file",
        "target": f"tessdata/{caminho}",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--progresso", type=Path,
        default=Path(tempfile.gettempdir()) / "gclaude-tessdata-manifesto-progresso.json",
        help="arquivo de progresso (retomável); fica fora do repositório",
    )
    parser.add_argument("--paralelos", type=int, default=6)
    args = parser.parse_args(argv)

    itens = _arvore()
    licenca = _licenca()
    progresso: dict[str, str] = {}
    if args.progresso.is_file():
        progresso = json.loads(args.progresso.read_text(encoding="utf-8"))
    # Uma entrada antiga só vale para o mesmo blob.
    validos = {item["path"]: item for item in itens}
    progresso = {
        caminho: dados for caminho, dados in progresso.items()
        if caminho in validos and isinstance(dados, dict) and dados.get("sha") == validos[caminho]["sha"]
    }

    pendentes = [item for item in itens if item["path"] not in progresso]
    print(f"{len(itens)} arquivos, {len(pendentes)} a conferir", flush=True)
    falhas = []
    with ThreadPoolExecutor(max_workers=max(1, args.paralelos)) as pool:
        futuros = {pool.submit(_conferir, item): item for item in pendentes}
        for feito, futuro in enumerate(as_completed(futuros), start=1):
            item = futuros[futuro]
            try:
                progresso[item["path"]] = {"sha": item["sha"], "sha256": futuro.result()}
            except Exception as exc:  # noqa: BLE001 - reportado e repetível
                falhas.append(f"{item['path']}: {exc}")
                continue
            args.progresso.write_text(json.dumps(progresso, indent=0, sort_keys=True), encoding="utf-8")
            print(f"[{feito}/{len(pendentes)}] {item['path']}", flush=True)
    if falhas:
        print("\n".join(falhas), file=sys.stderr)
        print("rode de novo para completar (o progresso foi guardado)", file=sys.stderr)
        return 1

    entradas = sorted(
        (_entrada(item, progresso[item["path"]]["sha256"], licenca) for item in itens),
        key=lambda entrada: entrada["name"],
    )
    por_idioma = {entrada["name"].split("/", 1)[1]: entrada["sha256"] for entrada in entradas}
    for idioma, esperado in HASHES_DE_SEMPRE.items():
        if por_idioma.get(idioma) != esperado:
            raise SystemExit(f"{idioma}: o hash mudou ({por_idioma.get(idioma)}); manifesto não gravado")

    manifesto = {
        "format": 1,
        "source": f"https://github.com/{REPO}/tree/{COMMIT}",
        "generated_by": "tools/gerar_manifesto_tessdata.py",
        "components": entradas,
    }
    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    DESTINO.write_text(json.dumps(manifesto, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(entradas)} entradas em {DESTINO}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
