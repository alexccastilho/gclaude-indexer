"""Every translation key the code uses exists in the three languages, and
every `log.*` key in the table is still recorded somewhere or is listed as
retired.

A `log.*` key is a recorded contract: `events.record_event` stores it in
`event.message_key`, and when the key is missing from the table it stores the
raw key as the message instead, silently, forever. A step missing from
`pipeline.LOG_STEPS` shows its raw id in the live log. Nothing else catches
either mistake, so this test reads the package source (AST and template
text) instead of relying on lists copied by hand.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from gclaude_indexer.events import LEVELS
from gclaude_indexer.i18n import _TRANSLATIONS, AVAILABLE_LANGUAGES, RETIRED_EVENT_KEYS
from gclaude_indexer.pipeline import LOG_STEPS

PACKAGE = Path(__file__).resolve().parent.parent / "gclaude_indexer"
LANGUAGES = tuple(AVAILABLE_LANGUAGES)
KEY_SHAPE = re.compile(r"^[a-z_]+(\.[a-z0-9_]+)+$")
# `t('area.key')` or `t('area.key', var=...)` in a template; keys built by
# concatenation (`t('step.' + ...)`) do not match and are covered elsewhere.
TEMPLATE_KEY = re.compile(r"""\bt\(\s*'([^']+)'\s*[,)]""")


def _python_sources() -> list[tuple[Path, ast.AST]]:
    return [
        (path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        for path in sorted(PACKAGE.rglob("*.py"))
        if path.name != "i18n.py"  # the table itself
    ]


SOURCES = _python_sources()


def _log_keys_in_code() -> set[str]:
    """Every string literal shaped like a `log.*` key: covers keys passed to
    `record_event`, to `nested`, kept in event tuples and chosen by an `if`
    before the call."""
    return {
        node.value
        for _path, tree in SOURCES
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        and node.value.startswith("log.") and KEY_SHAPE.match(node.value)
    }


def _recorded_steps() -> dict[str, str]:
    """`step` of every event written with literals: `(step, level, key)` as
    three consecutive arguments (`record_event(conn, step, level, key)`,
    `_record_event_op(...)`) or tuple items (the conversion's deferred
    events)."""
    steps: dict[str, str] = {}
    for path, tree in SOURCES:
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                values = node.args
            elif isinstance(node, ast.Tuple):
                values = node.elts
            else:
                continue
            for step, level, key in zip(values, values[1:], values[2:]):
                if (
                    isinstance(level, ast.Constant) and level.value in LEVELS
                    and isinstance(key, ast.Constant) and isinstance(key.value, str)
                    and key.value.startswith("log.")
                ):
                    where = f"{path.relative_to(PACKAGE)}:{node.lineno}"
                    if isinstance(step, ast.Constant):
                        steps.setdefault(step.value, where)
    return steps


def _translate_calls() -> dict[str, str]:
    """Literal keys passed to `translate(language, "key")`, to a local
    `t("key")` alias of it, or to `nested("key")`."""
    keys: dict[str, str] = {}
    for path, tree in SOURCES:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            position = {"translate": 1, "t": 0, "nested": 0}.get(name)
            if position is None or len(node.args) <= position:
                continue
            arg = node.args[position]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and KEY_SHAPE.match(arg.value):
                keys.setdefault(arg.value, f"{path.relative_to(PACKAGE)}:{node.lineno}")
    return keys


def _template_keys() -> dict[str, str]:
    keys: dict[str, str] = {}
    for path in sorted((PACKAGE / "web" / "templates").rglob("*.html")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            for key in TEMPLATE_KEY.findall(line):
                keys.setdefault(key, f"{path.relative_to(PACKAGE)}:{number}")
    return keys


def _missing(keys) -> list[str]:
    return sorted(
        f"{key} ({language})" for key in keys for language in LANGUAGES if key not in _TRANSLATIONS[language]
    )


def test_a_varredura_acha_as_chamadas():
    """Guards the scan itself: an empty result would make the other tests
    pass for the wrong reason."""
    assert len(_log_keys_in_code()) > 100
    assert {"scan", "conversion", "classification", "instructions"} <= set(_recorded_steps())
    assert len(_template_keys()) > 300


def test_toda_chave_de_evento_usada_existe_nos_tres_idiomas():
    assert _missing(_log_keys_in_code()) == []


def test_toda_chave_de_evento_da_tabela_e_gravada_ou_aposentada():
    in_table = {key for key in _TRANSLATIONS["pt"] if key.startswith("log.")}
    leftover = in_table - _log_keys_in_code() - RETIRED_EVENT_KEYS
    assert sorted(leftover) == []


@pytest.mark.parametrize("key", sorted(RETIRED_EVENT_KEYS))
def test_chave_aposentada_continua_traduzivel_e_ninguem_grava(key):
    assert _missing([key]) == []
    assert key not in _log_keys_in_code(), "still recorded: remove it from RETIRED_EVENT_KEYS"


def test_toda_etapa_gravada_esta_na_lista_do_log():
    steps = _recorded_steps()
    assert {step: where for step, where in steps.items() if step not in LOG_STEPS} == {}


def test_toda_etapa_do_log_tem_rotulo_nos_tres_idiomas():
    assert _missing(f"step.{step}.title" for step in LOG_STEPS) == []


def test_toda_chave_literal_do_codigo_existe_nos_tres_idiomas():
    keys = _translate_calls()
    assert [f"{item} em {keys[item.split(' ')[0]]}" for item in _missing(keys)] == []


def test_toda_chave_literal_dos_templates_existe_nos_tres_idiomas():
    keys = _template_keys()
    assert [f"{item} em {keys[item.split(' ')[0]]}" for item in _missing(keys)] == []
