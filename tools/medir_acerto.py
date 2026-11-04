# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Mede o acerto de um índice contra um gabarito (fase 37).

Lê o `project.db` de uma pasta de saída já indexada e o CSV do gabarito
(`demo/gabarito.csv` tem o formato), e escreve um relatório em Markdown
com cobertura de páginas, peças encontradas (precisão, revocação, F1) e,
entre as encontradas, acerto de tipo, data e autor. A conta está em
`gclaude_indexer/answer_key.py`.

    python tools/medir_acerto.py <pasta de saída> demo/gabarito.csv --saida-md acerto.md
    python tools/medir_acerto.py <pasta de saída> demo/gabarito.csv --exigir-cobertura 1.0

`--exigir-cobertura` faz o script sair com código 1 quando a cobertura fica
abaixo do valor: é o que o CI cobra do acervo de demonstração (toda página
em alguma peça). Nenhum limiar de acerto do tipo é cobrado: esse número é
publicado, não exigido.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))


def _pct(valor: float | None) -> str:
    return "—" if valor is None else f"{valor * 100:.1f}%".replace(".", ",")


def run(output: Path, key_csv: Path, report_md: Path | None = None, machine: str | None = None):
    from gclaude_indexer.answer_key import compare_with_answer_key, load_answer_key, render_report
    from gclaude_indexer.db import connect

    output = Path(output)
    banco = output / "project.db"
    if not banco.is_file():
        raise SystemExit(f"Não achei {banco}; a pasta de saída é a que tem o project.db.")

    key = load_answer_key(Path(key_csv))
    conn = connect(banco)
    try:
        report = compare_with_answer_key(conn, key)
    finally:
        conn.close()

    info: dict = {}
    run_info = output / "run_info.json"
    if run_info.is_file():
        try:
            info = json.loads(run_info.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            info = {}
    context = {
        "engine": info.get("engine", ""),
        "model": info.get("model", ""),
        "version": info.get("version", ""),
        "machine": machine or info.get("machine", ""),
        "date": str(info.get("started_at", ""))[:10],
        "duration_s": info.get("duration_s"),
    }
    texto = render_report(report, context)
    if report_md is not None:
        Path(report_md).parent.mkdir(parents=True, exist_ok=True)
        Path(report_md).write_text(texto, encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mede o acerto de um índice contra um gabarito.")
    parser.add_argument("saida", type=Path, help="pasta de saída do projeto (com project.db)")
    parser.add_argument("gabarito", type=Path, help="CSV do gabarito (formato de demo/gabarito.csv)")
    parser.add_argument("--saida-md", type=Path, default=None, help="onde escrever o relatório em Markdown")
    parser.add_argument("--maquina", default=None, help="texto da coluna Máquina do relatório (ex.: a placa de vídeo)")
    parser.add_argument("--exigir-cobertura", type=float, default=None, metavar="FRACAO",
                        help="sai com código 1 se a cobertura de páginas ficar abaixo (ex.: 1.0)")
    args = parser.parse_args(argv)

    report = run(args.saida, args.gabarito, args.saida_md, machine=args.maquina)
    print(
        f"Cobertura {report.pages_covered}/{report.pages_total} ({_pct(report.coverage)}); "
        f"peças {report.matched} encontradas de {report.key_pieces} do gabarito e {report.index_pieces} do índice "
        f"(precisão {_pct(report.precision)}, revocação {_pct(report.recall)}, F1 {_pct(report.f1)}); "
        f"tipo {_pct(report.type_score.rate)}, data {_pct(report.date_score.rate)}, autor {_pct(report.author_score.rate)}."
    )
    if report.missing_files:
        print(f"Arquivos do gabarito ausentes no índice: {', '.join(report.missing_files)}")
    if report.unknown_files:
        print(f"Arquivos do índice fora do gabarito: {', '.join(report.unknown_files)}")
    if args.saida_md is not None:
        print(f"Relatório em {args.saida_md}")
    if args.exigir_cobertura is not None and (report.coverage or 0.0) < args.exigir_cobertura:
        print(f"Cobertura abaixo de {_pct(args.exigir_cobertura)}: falha.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
