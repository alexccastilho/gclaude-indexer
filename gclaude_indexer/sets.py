# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Conjuntos: dois ou mais projetos num único Project do Claude (fase 38).

Um conjunto é uma seleção nomeada de projetos do catálogo, cada um com um
apelido, mais o texto que a pessoa já usa como instruções do Project. O
`combined_package.py` lê o conjunto e monta o pacote com os nomes
prefixados pelo apelido (`atas__index.md`), para dois acervos não
colidirem no mesmo Project.

O conjunto vive em `sets.json` na pasta local da máquina, não dentro de
nenhum projeto e não no catálogo compartilhado: um acervo pode pertencer a
vários conjuntos, e quem compartilha a pasta de um projeto não herda os
conjuntos de um colega. Noutro computador o conjunto é criado de novo em
dois cliques (spec da fase 38, seção 3.1).
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path

from .paths import machine_local_folder

SETS_FILE_NAME = "sets.json"

# Apelido de quem não deixou nada aproveitável no nome ("***", "???").
DEFAULT_ALIAS = "acervo"


@dataclass
class SetMember:
    project_id: int
    alias: str


@dataclass
class SetEntry:
    id: int
    name: str
    members: list[SetMember] = field(default_factory=list)
    personal_instructions: str = ""
    created_at: str = ""


def sets_path() -> Path:
    return machine_local_folder() / SETS_FILE_NAME


def propose_alias(name: str, taken: set[str]) -> str:
    """Apelido seguro para nome de arquivo, único entre `taken`.

    Minúsculas, sem acento, qualquer sequência que não seja letra ou
    dígito vira um hífen (`Diretoria / Região Sul` → `diretoria-regiao-
    sul`): o apelido vira prefixo de nome de arquivo no ZIP e na pasta
    combinada, e precisa valer no Windows, no Drive e no Project. Colisão
    ganha `-2`, `-3`...
    """
    sem_acento = unicodedata.normalize("NFKD", name)
    base = "".join(ch for ch in sem_acento if not unicodedata.combining(ch)).lower()
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-") or DEFAULT_ALIAS
    candidato = base
    n = 2
    while candidato in taken:
        candidato = f"{base}-{n}"
        n += 1
    return candidato


def unique_aliases(members: list[SetMember]) -> list[SetMember]:
    """Os mesmos membros com apelidos normalizados e sem repetição, na ordem
    dada. Vale para o que vem do formulário e para o que vem do arquivo:
    dois `atas` no mesmo conjunto dariam dois `atas__index.md` no ZIP."""
    usados: set[str] = set()
    resultado = []
    for member in members:
        alias = propose_alias(member.alias, usados)
        usados.add(alias)
        resultado.append(SetMember(project_id=int(member.project_id), alias=alias))
    return resultado


def _read() -> list[SetEntry]:
    """Os conjuntos gravados, tolerando o que não for o que escrevemos
    (mesmo critério do catálogo)."""
    path = sets_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []

    known = {item.name for item in fields(SetEntry)} - {"members"}
    entries: list[SetEntry] = []
    for item in data:
        if not isinstance(item, dict) or "id" not in item or "name" not in item:
            continue
        raw_members = item.get("members") or []
        try:
            members = [
                SetMember(project_id=int(m["project_id"]), alias=str(m.get("alias", "")))
                for m in raw_members if isinstance(m, dict) and "project_id" in m
            ]
            entry = SetEntry(**{k: v for k, v in item.items() if k in known}, members=unique_aliases(members))
        except (TypeError, ValueError):
            continue
        entries.append(entry)
    return entries


def _write(entries: list[SetEntry]) -> None:
    path = sets_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(e) for e in entries], ensure_ascii=False, indent=2), encoding="utf-8")


def list_sets() -> list[SetEntry]:
    return _read()


def find_set(set_id: int) -> SetEntry | None:
    for entry in _read():
        if entry.id == set_id:
            return entry
    return None


def save_set(entry: SetEntry) -> SetEntry:
    """Grava o conjunto e o devolve com id (novo quando 0), data de criação
    e apelidos únicos. Um id já existente é substituído."""
    entries = _read()
    entry.members = unique_aliases(entry.members)
    if entry.id <= 0:
        entry.id = max((e.id for e in entries), default=0) + 1
    if not entry.created_at:
        entry.created_at = datetime.now().isoformat(timespec="seconds")
    restantes = [e for e in entries if e.id != entry.id]
    restantes.append(entry)
    restantes.sort(key=lambda e: e.id)
    _write(restantes)
    return entry


def remove_set(set_id: int) -> None:
    _write([e for e in _read() if e.id != set_id])
