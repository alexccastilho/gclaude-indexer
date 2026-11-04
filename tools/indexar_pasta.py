# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Indexa uma pasta sem a interface, do início ao fim (fase 37).

As mesmas cinco etapas que a interface roda, na mesma ordem
(`background_runs.STEP_ORDER`), depois a importação das peças e os
artefatos (`index.md`, um `index-<grupo>.md` por grupo). Existe para duas
coisas que a interface não faz: rodar numa máquina sem ninguém na frente
(o CI indexa o acervo de demonstração a cada push) e deixar ao lado do
`project.db` um `run_info.json` com motor, modelo, versão e duração, que
`medir_acerto.py` põe no cabeçalho do relatório.

    python tools/indexar_pasta.py demo/acervo <pasta de saída> --motor rules
    python tools/indexar_pasta.py demo/acervo <pasta de saída> --motor local --modelo qwen3.5:9b

Não toca em `projects.json`: o projeto não aparece na interface. Tudo o
mais é o que as etapas já fazem (a conversão escreve em
`machine_local_folder()/work`, como sempre).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import platform
import re
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

# As categorias que o acervo de demonstração usa. O padrão de `ProjectConfig`
# é ["pdf", "docx", "imagens"]: deixaria a planilha e o e-mail de fora, e a
# cobertura do gabarito cairia sem que nada estivesse errado.
EXTENSOES = ["pdf", "docx", "xlsx", "imagens", "email"]


def _versao() -> str:
    """`SYSTEM_VERSION` lida do arquivo: importar `web.app` traz o FastAPI
    inteiro só para um texto."""
    try:
        texto = (RAIZ / "gclaude_indexer" / "web" / "app.py").read_text(encoding="utf-8")
        encontrado = re.search(r'^SYSTEM_VERSION\s*=\s*"([^"]+)"', texto, re.M)
        return encontrado.group(1) if encontrado else "?"
    except OSError:
        return "?"


def run(source: Path, output: Path, engine: str = "rules", model: str = "automatic", language: str = "pt") -> dict:
    from gclaude_indexer.config import load_config
    from gclaude_indexer.conversion import convert
    from gclaude_indexer.db import connect, init_schema
    from gclaude_indexer.extraction import extract_pages
    from gclaude_indexer.import_items import import_and_consolidate
    from gclaude_indexer.artifacts import generate_all_artifacts
    from gclaude_indexer.orchestrator import run_classification
    from gclaude_indexer.scanning import scan
    from gclaude_indexer.web.background_runs import STEP_ORDER
    from gclaude_indexer.windows_prep import prepare_windows

    source, output = Path(source).resolve(), Path(output).resolve()
    if not source.is_dir():
        raise SystemExit(f"Pasta de origem não encontrada: {source}")
    output.mkdir(parents=True, exist_ok=True)

    config = load_config({
        "name": source.name,
        "source_folder": str(source),
        "output_folder": str(output),
        "extensions": EXTENSOES,
        "classification_engine": engine,
        "local_model": model,
    })

    # Mesmos nomes, mesma ordem que a interface; se `STEP_ORDER` ganhar uma
    # etapa, este dicionário deixa de cobri-lo e o erro aparece aqui.
    etapas = {
        "scan": scan, "conversion": convert, "extraction": extract_pages,
        "windows": prepare_windows, "classification": run_classification,
    }
    faltam = set(STEP_ORDER) - set(etapas)
    if faltam:
        raise SystemExit(f"Etapa(s) sem correspondente neste script: {sorted(faltam)}")

    inicio = time.monotonic()
    iniciado_em = dt.datetime.now().isoformat(timespec="seconds")
    conn = connect(output / "project.db")
    try:
        init_schema(conn)
        motor_usado = engine
        for nome in STEP_ORDER:
            t0 = time.monotonic()
            resultado = etapas[nome](conn, config, should_stop=None, language=language)
            if nome == "classification":
                motor_usado = resultado[0]
            print(f"  {nome:<15} {time.monotonic() - t0:6.1f} s")
        t0 = time.monotonic()
        import_and_consolidate(conn, config, language=language)
        generate_all_artifacts(conn, config, language)
        print(f"  {'import+index':<15} {time.monotonic() - t0:6.1f} s")
        janelas = conn.execute("SELECT COUNT(*) FROM window").fetchone()[0]
        itens = conn.execute("SELECT COUNT(*) FROM item").fetchone()[0]
    finally:
        conn.close()

    info = {
        "engine": motor_usado,
        "model": model if engine == "local" else "",
        "version": _versao(),
        "machine": platform.node(),
        "started_at": iniciado_em,
        "duration_s": round(time.monotonic() - inicio, 1),
        "windows": janelas,
        "items": itens,
        "source": str(source),
    }
    (output / "run_info.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    return info


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Indexa uma pasta sem a interface, do início ao fim.")
    parser.add_argument("origem", type=Path, help="pasta com os documentos (ex.: demo/acervo)")
    parser.add_argument("saida", type=Path, help="pasta de saída do projeto (project.db, index.md, run_info.json)")
    parser.add_argument("--motor", choices=["rules", "local"], default="rules",
                        help="rules: só regras, roda em qualquer máquina; local: modelo via Ollama")
    parser.add_argument("--modelo", default="automatic", help="modelo do Ollama para --motor local (padrão: automático)")
    parser.add_argument("--idioma", default="pt", help="idioma dos textos do índice e do log (pt, en, es)")
    args = parser.parse_args(argv)

    print(f"Indexando {args.origem} com o motor '{args.motor}'...")
    info = run(args.origem, args.saida, engine=args.motor, model=args.modelo, language=args.idioma)
    print(f"Concluído em {info['duration_s']} s: {info['windows']} trecho(s), {info['items']} peça(s). "
          f"Saída em {args.saida.resolve()}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
