"""Marca para reclassificação apenas as janelas que falharam numa corrida.

Por que isto existe: o sistema não tem essa operação. A única transição de
estado de janela no código é `pending -> done`, e a atualização
incremental (fase 17) só reage a mudanças nos *arquivos de origem* — com
os PDFs intactos, ela não invalida nada. Então, sem isto, as opções são
reindexar o acervo inteiro ou conviver com o resultado.

O que ele faz, nesta ordem:

  1. lê da tabela `event` quais janelas registraram falha;
  2. faz cópia de segurança do `project.db` e do `raw_items.jsonl`;
  3. apaga do `raw_items.jsonl` as peças vindas dessas janelas;
  4. devolve essas janelas para `status = 'pending'`.

Depois disso, rodar a etapa 6 na interface reclassifica só elas, e a etapa
7 (importação) reescreve a tabela de peças inteira a partir do JSONL
podado — `import_items._write_items` faz `DELETE FROM item` antes de
inserir, então não sobra duplicata nem peça órfã.

Uso:

    python reprocessar_janelas_com_falha.py "<pasta de saída do projeto>"
    python reprocessar_janelas_com_falha.py "<pasta>" --aplicar

Sem `--aplicar` ele não escreve nada: lista o que faria e para. A pasta de
saída é a que termina em `_indexado`, a mesma que contém `project.db`.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# As duas assinaturas de falha da etapa 6, como `events.record_event` as
# grava. Ambas guardam a chave da janela em `message_params` (JSON).
#
#   - `window_rejection` é o invólucro de vários avisos; o que interessa
#     aqui é o que traz `pages_missing_from_answer` dentro de `reason` —
#     "o modelo não respondeu sobre N de N página(s)". Os outros motivos
#     (referência não reconhecida, por exemplo) não são reclassificáveis
#     só por tentar de novo.
#   - `invalid_item` é a peça recusada na validação.
CONSULTA_JANELAS = """
    SELECT message_params, created_at, message_key
      FROM event
     WHERE step = 'classification'
       AND message_params IS NOT NULL
       AND (
             (message_key = 'log.local_engine.window_rejection'
              AND message_params LIKE '%pages_missing_from_answer%')
          OR message_key = 'log.local_engine.invalid_item'
           )
       AND created_at >= ?
     ORDER BY id
"""

ROTULOS = {
    "log.local_engine.window_rejection": "modelo não respondeu",
    "log.local_engine.invalid_item": "peça recusada na validação",
}


def janelas_com_falha(conn: sqlite3.Connection, desde: str) -> dict[str, set[str]]:
    """`{chave da janela: {motivos}}`, só para janelas que ainda existem.

    Uma janela citada num evento antigo pode ter sido descartada por uma
    atualização posterior; reabri-la seria ressuscitar uma posição que não
    existe mais.
    """
    existentes = {
        linha[0] for linha in conn.execute("SELECT key FROM window").fetchall()
    }

    encontradas: dict[str, set[str]] = {}
    for params_json, _criado_em, chave_msg in conn.execute(CONSULTA_JANELAS, (desde,)):
        try:
            params = json.loads(params_json)
        except (json.JSONDecodeError, TypeError):
            continue
        janela = params.get("window")
        if not isinstance(janela, str) or janela not in existentes:
            continue
        encontradas.setdefault(janela, set()).add(ROTULOS.get(chave_msg, chave_msg))

    return encontradas


def podar_jsonl(caminho: Path, janelas: set[str]) -> tuple[int, int]:
    """Remove as linhas cujas peças vieram de `janelas`.

    Devolve `(linhas removidas, linhas mantidas)`. Uma linha que não
    decodifica é mantida: a importação já reporta isso como erro, e apagar
    em silêncio o que não se consegue ler não é decisão deste script — a
    mesma regra que `invalidation._prune_raw_items` segue.
    """
    if not caminho.exists():
        return (0, 0)

    mantidas: list[str] = []
    removidas = 0
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        if not linha.strip():
            continue
        try:
            if json.loads(linha).get("window") in janelas:
                removidas += 1
                continue
        except json.JSONDecodeError:
            pass
        mantidas.append(linha)

    caminho.write_text("\n".join(mantidas) + ("\n" if mantidas else ""), encoding="utf-8")
    return (removidas, len(mantidas))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pasta_de_saida", help="a pasta do projeto que contém project.db")
    parser.add_argument(
        "--aplicar", action="store_true",
        help="escreve as mudanças; sem isto o script só lista o que faria",
    )
    parser.add_argument(
        "--desde", default="0000",
        help="só considera falhas registradas a partir desta data (AAAA-MM-DD)",
    )
    args = parser.parse_args(argv)

    saida = Path(args.pasta_de_saida).expanduser().resolve()
    banco = saida / "project.db"
    jsonl = saida / "raw_items.jsonl"

    if not banco.exists():
        print(f"ERRO: não achei {banco}", file=sys.stderr)
        print("A pasta de saída é a que termina em '_indexado'.", file=sys.stderr)
        return 1

    conn = sqlite3.connect(banco)
    try:
        janelas = janelas_com_falha(conn, args.desde)

        if not janelas:
            print("Nenhuma janela com falha registrada. Nada a fazer.")
            return 0

        print(f"{len(janelas)} janela(s) com falha:\n")
        for chave in sorted(janelas):
            print(f"  {chave}  ({', '.join(sorted(janelas[chave]))})")

        total = conn.execute("SELECT COUNT(*) FROM window").fetchone()[0]
        print(f"\n{len(janelas)} de {total} janelas ({len(janelas) / total:.0%} do acervo).")

        if not args.aplicar:
            print("\nEnsaio. Nada foi alterado — repita com --aplicar para valer.")
            return 0

        marca = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(banco, banco.with_suffix(f".db.bak-{marca}"))
        if jsonl.exists():
            shutil.copy2(jsonl, jsonl.with_suffix(f".jsonl.bak-{marca}"))
        print(f"\nCópia de segurança gravada com o sufixo .bak-{marca}")

        removidas, mantidas = podar_jsonl(jsonl, set(janelas))
        print(f"raw_items.jsonl: {removidas} peça(s) removida(s), {mantidas} mantida(s)")

        conn.executemany(
            "UPDATE window SET status = 'pending' WHERE key = ?",
            [(chave,) for chave in janelas],
        )
        conn.commit()
        print(f"{len(janelas)} janela(s) devolvida(s) para 'pending'.")

        print(
            "\nPronto. Agora, na interface do GClaude Indexer:\n"
            "  1. abra o projeto e vá para a tela de Execução;\n"
            "  2. rode as etapas — só as janelas acima serão classificadas;\n"
            "  3. deixe a importação e a geração de relatórios rodarem depois,\n"
            "     senão o índice continua mostrando o resultado antigo."
        )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
