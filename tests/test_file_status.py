# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""O ciclo de vida de `file.status` e `window.status` tem dono
(`gclaude_indexer/file_status.py`): nenhum outro módulo escreve o valor de
um status como literal, em SQL ou numa comparação. Senão um status novo (ou
um conjunto que muda de sentido) volta a ter de ser caçado em quinze
arquivos.

Status de etapa (`web/step_state.STATUSES`, operações, eventos) não entram:
`"done"`/`"pending"` em Python são deles; só o SQL é olhado para os de
janela.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from gclaude_indexer import file_status
from gclaude_indexer.file_status import ALL_FILE_STATUSES, WINDOW_DONE, WINDOW_PENDING

PACKAGE = Path(__file__).resolve().parent.parent / "gclaude_indexer"
FILE_VALUES = frozenset(ALL_FILE_STATUSES)
SQL_VALUES = FILE_VALUES | {WINDOW_PENDING, WINDOW_DONE}
_SQL_LITERAL = re.compile(r"'(" + "|".join(sorted(SQL_VALUES)) + r")'")
# Names whose value is a status: formatted into SQL they would be the pattern the
# user's SQL-injection scanner flags; they go in as `?` parameters.
STATUS_NAMES = frozenset({
    "DISCOVERED", "CONVERTED", "EXTRACTED", "FAILED", "DUPLICATE", "SKIPPED", "WINDOW_PENDING", "WINDOW_DONE",
})
_SQL_HINT = re.compile(r"\b(SELECT|UPDATE|INSERT|DELETE|WHERE|CASE|VALUES)\b|\bstatus\b")


def _docstrings(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                ids.add(id(body[0].value))
    return ids


def _is_status_expr(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return "status" in node.id
    if isinstance(node, ast.Attribute):
        return "status" in node.attr
    if isinstance(node, ast.Subscript):
        key = node.slice
        return isinstance(key, ast.Constant) and key.value == "status"
    return False


def _file_values(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Constant) and node.value in FILE_VALUES:
        return [node.value]
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return [e.value for e in node.elts if isinstance(e, ast.Constant) and e.value in FILE_VALUES]
    return []


def _call_name(node: ast.Call) -> str:
    func = node.func
    return func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")


def status_literals(source: str) -> list[tuple[int, str]]:
    """`(linha, valor)` de cada status escrito como literal fora do dono."""
    tree = ast.parse(source)
    docstrings = _docstrings(tree)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            if _SQL_HINT.search(node.value):
                found += [(node.lineno, m.group(1)) for m in _SQL_LITERAL.finditer(node.value)]
        elif isinstance(node, ast.Compare):
            operands = [node.left, *node.comparators]
            if any(_is_status_expr(o) for o in operands):
                for operand in operands:
                    found += [(node.lineno, v) for v in _file_values(operand)]
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == "status":
                    found += [(node.lineno, v) for v in _file_values(value)]
        elif isinstance(node, ast.Assign):
            if any(_is_status_expr(target) for target in node.targets):
                found += [(node.lineno, v) for v in _file_values(node.value)]
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and "status" in node.name:
            for inner in ast.walk(node):
                if isinstance(inner, ast.Return) and inner.value is not None:
                    found += [(inner.lineno, v) for v in _file_values(inner.value)]
        elif isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg == "status":
                    found += [(node.lineno, v) for v in _file_values(keyword.value)]
            func = node.func
            if (isinstance(func, ast.Attribute) and func.attr == "get" and _is_status_expr(func.value)) or (
                _call_name(node).endswith("_file")
            ):
                for arg in node.args:
                    found += [(node.lineno, v) for v in _file_values(arg)]
        elif isinstance(node, ast.FormattedValue):
            inner = node.value
            name = inner.attr if isinstance(inner, ast.Attribute) else getattr(inner, "id", "")
            if name in STATUS_NAMES:
                found.append((node.lineno, name))
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            values = _file_values(node)
            if len(values) >= 2:
                found += [(node.lineno, v) for v in values]
    return sorted(set(found))


def test_nenhum_status_literal_fora_de_file_status():
    owner = Path(file_status.__file__).resolve()
    problems = []
    for path in sorted(PACKAGE.rglob("*.py")):
        if path.resolve() == owner:
            continue
        for line, value in status_literals(path.read_text(encoding="utf-8")):
            problems.append(f"{path.relative_to(PACKAGE)}:{line}: '{value}'")
    assert not problems, "status literal fora de file_status.py:\n" + "\n".join(problems)


def test_a_varredura_acha_cada_forma_e_ignora_status_de_etapa():
    exemplo = '''
def f(conn, row, step, operation, by_status):
    conn.execute("SELECT * FROM file WHERE status = 'discovered'")
    conn.execute("UPDATE window SET status = 'done' WHERE id = ?")
    conn.execute("SELECT 1 FROM file WHERE status IN ('converted', 'extracted')")
    conn.execute("INSERT INTO window (status) VALUES ('pending')")
    if row["status"] == "failed":
        pass
    if row["status"] not in ("skipped", "duplicate"):
        pass
    item = {"status": "extracted"}
    status = "discovered"
    n = by_status.get("converted", 0)
    _insert_file(conn, "a", "skipped")
    for value in ("discovered", "converted"):
        pass
    conn.execute(f"SELECT 1 FROM file WHERE status = '{FAILED}' OR status = '{file_status.SKIPPED}'")
    # status de etapa e de operação, e a pasta converted/: não contam
    if step["status"] not in ("done", "running"):
        pass
    operation.status = "done"
    path = local_path(output_dir, "converted", "x")
    params = {"converted": 1, "failed": 2}
'''
    achados = {value for _line, value in status_literals(exemplo)}
    assert achados == {"discovered", "done", "converted", "extracted", "pending", "failed", "skipped", "duplicate",
                       "FAILED", "SKIPPED"}
    corte = next(i for i, texto in enumerate(exemplo.splitlines(), 1) if "não contam" in texto)
    assert max(line for line, _value in status_literals(exemplo)) < corte


def test_in_params_da_as_marcas_e_os_valores_na_mesma_ordem():
    assert file_status.in_params(file_status.CONVERSION_FINISHED) == (
        "?, ?, ?", ("converted", "extracted", "failed"),
    )


def test_espera_de_componente_igual_em_sql_e_em_python():
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE file (status TEXT, error TEXT)")
    linhas = [(s, e) for s in ALL_FILE_STATUSES for e in (None, "component_unavailable", "secret")]
    conn.executemany("INSERT INTO file VALUES (?, ?)", linhas)
    em_sql = set(conn.execute(
        "SELECT status, error FROM file WHERE " + file_status.WAITING_COMPONENT_SQL,
        file_status.WAITING_COMPONENT_PARAMS,
    ))
    em_python = {(s, e) for s, e in linhas if file_status.is_waiting_component(s, e)}
    assert em_sql == em_python == {("skipped", "component_unavailable")}
