# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Mudança da pasta de saída de um projeto existente para `<origem>-AI`
(2.0.0, decisão 10 do usuário).

Até a 1.10 a saída podia ficar dentro da origem. A varredura do próprio
projeto já pula a pasta (ela tem `project.db`), mas o que foi gerado continua
exposto a quem lê a origem: outro projeto ou outra ferramenta que indexe a
mesma pasta, e qualquer pessoa com acesso a ela. Este módulo leva a saída
para a pasta irmã sugerida por `paths.suggest_output_folder`.

**Diário antes de tocar em arquivo.** `relocation.json`, na pasta local da
máquina (nunca na pasta sincronizada), descreve a mudança inteira antes do
primeiro `rename`: de onde, para onde, quais itens e como. Uma queda no meio
(energia, processo encerrado) deixa o diário, e a próxima abertura do
projeto o lê (`recover`):

- antes do ponto de confirmação (`phase = "moving"`), desfaz na ordem
  inversa — o que estava no destino volta para a origem;
- depois dele (`phase = "committed"`), conclui: apaga as cópias de origem já
  verificadas e regrava caminhos, catálogos e a pasta de trabalho.

O sentido é decidido pelo disco, não só pela fase gravada: um `rename` que
terminou sem dar tempo de anotar `committed` é reconhecido (o `project.db`
já está no destino e a origem já não o tem) e segue adiante.

**Nunca sobrescreve.** Destino ocupado, item que já existe do outro lado ou
cópia que não confere em tamanho e SHA-256 param a mudança e desfazem o que
foi feito. Links simbólicos e junções nunca são seguidos: um item que seja
ponto de nova análise (reparse point) recusa a mudança antes de começar.

**Volumes diferentes** (raro: a pasta irmã normalmente está no mesmo disco)
viram cópia com verificação, depois de conferir o espaço livre, e a origem
só é apagada depois que todas as cópias conferem.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import shutil
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import paths, sync, workdir
from .catalog import relocate_project as relocate_catalog_entry
from .deletion import GENERATED_FILES, SHARED_FILES
from .managed_block import BACKUP_SUFFIX, without_managed_block
from .windows_prep import LEGACY_WINDOW_FILE

JOURNAL_FILE_NAME = "relocation.json"
POSTPONED_FILE_NAME = "relocation-postponed.json"
JOURNAL_VERSION = 1

# O que é levado para a pasta nova. `converted/` é levado, não apagado, ao
# contrário do que a tarefa previa: projetos convertidos antes da 1.5.8 têm
# nele os PDFs com OCR e os textos extraídos (`workdir.legacy_path`), que a
# atualização relê para renumerar folhas sem refazer OCR
# (`invalidation._renumber_status`) e que a extração exige para arquivos
# ainda em `'converted'`. Perdê-lo obrigaria a refazer OCR — ou deixaria
# esses arquivos como falha. Fica no mesmo lugar relativo, e
# `workdir.intermediate_path` continua a achá-lo.
CARRIED_FOLDERS = ("converted", "logs")
CARRIED_FILES = tuple(GENERATED_FILES) + (paths.OUTPUT_MARKER_NAME,)
# Arquivos de instruções: têm o bloco gerado e, às vezes, texto do usuário
# (`managed_block.py`). Com a pasta toda nossa, vão junto; numa pasta com
# arquivos do usuário, só se forem inteiramente nossos. Se tiverem texto do
# usuário, são copiados para a pasta nova e, no original, sai só o bloco
# gerado — como na exclusão do projeto.
INSTRUCTION_FILES = tuple(SHARED_FILES)
# Sobras de versões antigas, que não são levadas: `windows/` (janelas do
# motor manual, removido na 2.0.0) e `blocks/` (fatias de PDFs grandes; o
# fatiamento acabou e nada mais lê a pasta). Saem só os nomes que nós
# gravamos; qualquer outra coisa nelas fica onde está.
OBSOLETE_FOLDERS = ("windows", "blocks")

_DB_SIDECARS = ("project.db-wal", "project.db-shm", "project.db-journal")
_COPY_CHUNK = 1024 * 1024
# Folga além do tamanho a copiar: o sistema de arquivos arredonda por
# cluster e o Drive guarda metadados à parte.
_SPACE_MARGIN_BYTES = 64 * 1024 * 1024


class RelocationError(Exception):
    """A mudança não pôde ser feita (ou foi desfeita). Carrega a chave de
    tradução e os parâmetros, não o texto: quem mostra é a tela."""

    def __init__(self, key: str, **params):
        super().__init__(key)
        self.key = key
        self.params = params


class RelocationCancelled(Exception):
    """O usuário pediu Parar antes do ponto de confirmação: tudo foi desfeito."""


# --- detecção -----------------------------------------------------------------


def output_inside_source(source_folder: str, output_folder: str) -> bool:
    """A saída está dentro da origem (ou é ela). Qualquer erro de disco é
    "não": a abertura de um projeto nunca pode falhar por causa disto."""
    try:
        if not source_folder or not output_folder:
            return False
        source = Path(source_folder).resolve()
        output = Path(output_folder).resolve()
        return paths.is_inside_folder(output, source)
    except (OSError, ValueError, RuntimeError):
        return False


def _key(folder) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(str(folder))))


# --- adiamento (por máquina) -------------------------------------------------


def _postponed_path() -> Path:
    return paths.machine_local_folder() / POSTPONED_FILE_NAME


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return default


def _write_json_atomic(path: Path, data) -> None:
    """Grava num temporário ao lado e troca com `os.replace`: uma queda no
    meio deixa o arquivo antigo inteiro, nunca um pela metade."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with open(temporary, "w", encoding="utf-8") as file:
        file.write(json.dumps(data, ensure_ascii=False, indent=2))
        file.flush()
        os.fsync(file.fileno())
    os.replace(temporary, path)


def is_postponed(output_folder) -> bool:
    data = _read_json(_postponed_path(), {})
    return isinstance(data, dict) and _key(output_folder) in data


def postpone(output_folder) -> None:
    """O usuário escolheu "Adiar": sem prazo (decisão do usuário). Fica
    nesta máquina, não na pasta compartilhada — outra máquina pergunta de
    novo, e a tela de Execução segue mostrando o aviso."""
    data = _read_json(_postponed_path(), {})
    if not isinstance(data, dict):
        data = {}
    data[_key(output_folder)] = datetime.now().isoformat(timespec="seconds")
    _write_json_atomic(_postponed_path(), data)


def _forget_postponement(*folders) -> None:
    data = _read_json(_postponed_path(), {})
    if not isinstance(data, dict):
        return
    changed = False
    for folder in folders:
        if data.pop(_key(folder), None) is not None:
            changed = True
    if changed:
        try:
            _write_json_atomic(_postponed_path(), data)
        except OSError:
            pass


# --- plano --------------------------------------------------------------------


@dataclass
class RelocationPlan:
    source: str
    old: str
    new: str
    # "rename": a pasta inteira é só nossa e muda de nome de uma vez.
    # "items": há arquivos do usuário; só os itens gerados vão.
    mode: str
    same_volume: bool
    # Em ordem de execução; `project.db` por último.
    carried: list[str] = field(default_factory=list)
    # Instruções com texto do usuário: copiadas, e o original perde só o bloco.
    copied_instructions: list[str] = field(default_factory=list)
    # Sobras que não são levadas (apagadas depois da confirmação).
    dropped: list[str] = field(default_factory=list)
    # Quantos itens do usuário ficam onde estão.
    kept: int = 0
    total_bytes: int = 0


def _is_link(path: Path) -> bool:
    """Link simbólico ou junção (ponto de nova análise no Windows): nunca
    é seguido nem levado. Na dúvida (erro ao ler), é tratado como link."""
    try:
        if path.is_symlink():
            return True
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
        return bool(attributes & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT
    except OSError:
        return True


def _matches(name: str, patterns) -> bool:
    folded = os.path.normcase(name)
    return any(fnmatch.fnmatchcase(folded, os.path.normcase(pattern)) for pattern in patterns)


def _is_backup_of_instructions(name: str) -> bool:
    folded = os.path.normcase(name)
    for base in INSTRUCTION_FILES:
        base_folded = os.path.normcase(base)
        if folded == base_folded + BACKUP_SUFFIX:
            return True
        if folded.startswith(base_folded + ".") and folded.endswith(BACKUP_SUFFIX):
            return True
    return False


def _classify(entry: os.DirEntry) -> str:
    """`carry`, `instructions`, `obsolete` ou `user` para um item do primeiro
    nível da pasta de saída."""
    name = entry.name
    try:
        is_dir = entry.is_dir(follow_symlinks=False)
    except OSError:
        return "user"
    if is_dir:
        if _matches(name, CARRIED_FOLDERS):
            return "carry"
        if _matches(name, OBSOLETE_FOLDERS):
            return "obsolete"
        return "user"
    if _matches(name, INSTRUCTION_FILES):
        return "instructions"
    if _matches(name, CARRIED_FILES) or _is_backup_of_instructions(name):
        return "carry"
    return "user"


def _instruction_is_ours(path: Path) -> bool:
    """Um arquivo de instruções sem nada fora do bloco gerado."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return not without_managed_block(text).strip()


def _tree_size_without_links(path: Path) -> int:
    """Tamanho de um arquivo ou pasta. Levanta `RelocationError` se achar
    um link ou junção em qualquer nível."""
    if _is_link(path):
        raise RelocationError("relocation.error.link", path=str(path))
    if path.is_file():
        return path.stat().st_size
    total = 0
    pending = [path]
    while pending:
        current = pending.pop()
        with os.scandir(current) as entries:
            for entry in entries:
                child = Path(entry.path)
                if _is_link(child):
                    raise RelocationError("relocation.error.link", path=str(child))
                if entry.is_dir(follow_symlinks=False):
                    pending.append(child)
                else:
                    total += entry.stat(follow_symlinks=False).st_size
    return total


def _same_volume(a: Path, b: Path) -> bool:
    """Ponto de troca nos testes, que não têm dois volumes à mão."""
    return os.stat(a).st_dev == os.stat(b).st_dev


def _is_free(path: Path) -> bool:
    if not path.exists():
        return True
    if _is_link(path) or not path.is_dir():
        return False
    try:
        return not any(path.iterdir())
    except OSError:
        return False


def build_plan(source_folder: str, output_folder: str, destination: str | None = None) -> RelocationPlan:
    """O que a mudança faria, sem tocar em nada. Levanta `RelocationError`
    quando ela não pode ser feita (destino ocupado, link, origem na raiz)."""
    source = Path(source_folder).resolve()
    old = Path(output_folder).resolve()
    if destination is None:
        destination = paths.suggest_output_folder(str(source))
    if destination is None:
        raise RelocationError("relocation.error.no_destination", source=str(source))
    new = Path(destination)

    if _is_link(old):
        raise RelocationError("relocation.error.link", path=str(old))
    if not (old / paths.PROJECT_DB_NAME).is_file():
        raise RelocationError("relocation.error.no_project", path=str(old))
    if not _is_free(new):
        raise RelocationError("relocation.error.destination_taken", path=str(new))
    if paths.is_inside_folder(new, source) or paths.is_inside_folder(new, old):
        raise RelocationError("relocation.error.destination_inside", path=str(new))

    carried: list[str] = []
    instructions_ours: list[str] = []
    instructions_mixed: list[str] = []
    dropped: list[str] = []
    kept = 0
    with os.scandir(old) as entries:
        listed = sorted(entries, key=lambda e: e.name.lower())
    for entry in listed:
        kind = _classify(entry)
        if kind == "user":
            kept += 1
        elif kind == "carry":
            carried.append(entry.name)
        elif kind == "obsolete":
            dropped.append(entry.name)
        elif _instruction_is_ours(Path(entry.path)):
            instructions_ours.append(entry.name)
        else:
            instructions_mixed.append(entry.name)

    # A origem nunca muda de nome inteira: se a saída é a própria origem,
    # os documentos do usuário estão nela.
    same_as_source = _key(old) == _key(source)
    mode = "rename" if kept == 0 and not same_as_source else "items"
    if mode == "rename":
        carried = carried + instructions_ours + instructions_mixed
        instructions_mixed = []
    else:
        carried = carried + instructions_ours

    def db_order(name: str) -> tuple[int, str]:
        folded = name.lower()
        if folded == paths.PROJECT_DB_NAME:
            return (2, folded)
        if folded in _DB_SIDECARS:
            return (1, folded)
        return (0, folded)

    carried.sort(key=db_order)

    total = 0
    for name in carried + instructions_mixed:
        total += _tree_size_without_links(old / name)

    parent = new.parent
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    same_volume = _same_volume(old, parent)

    return RelocationPlan(
        source=str(source), old=str(old), new=str(new), mode=mode, same_volume=same_volume,
        carried=carried, copied_instructions=instructions_mixed, dropped=dropped,
        kept=kept, total_bytes=total,
    )


# --- diário -------------------------------------------------------------------

_journal_lock = threading.RLock()
# Pastas com mudança em andamento neste processo, e a thread que a faz. A
# mesma thread pode entrar de novo (a rota marca a pasta antes de fechar as
# conexões, e `execute` marca outra vez); outra thread recebe "ocupado".
_in_flight: dict[str, int] = {}
_in_flight_lock = threading.Lock()


def _journal_path() -> Path:
    return paths.machine_local_folder() / JOURNAL_FILE_NAME


def _read_journals() -> dict[str, dict]:
    data = _read_json(_journal_path(), {})
    if not isinstance(data, dict) or not isinstance(data.get("moves"), dict):
        return {}
    return {k: v for k, v in data["moves"].items() if isinstance(v, dict)}


def _write_journal(journal: dict) -> None:
    with _journal_lock:
        moves = _read_journals()
        moves[_key(journal["old"])] = journal
        _write_json_atomic(_journal_path(), {"version": JOURNAL_VERSION, "moves": moves})


def _drop_journal(journal: dict) -> None:
    with _journal_lock:
        moves = _read_journals()
        if moves.pop(_key(journal["old"]), None) is None:
            return
        if moves:
            _write_json_atomic(_journal_path(), {"version": JOURNAL_VERSION, "moves": moves})
        else:
            _journal_path().unlink(missing_ok=True)


def pending_for(output_folder) -> dict | None:
    """O diário de uma mudança interrompida que envolve esta pasta (como
    origem ou como destino), ou `None`."""
    key = _key(output_folder)
    for journal in _read_journals().values():
        if key in (_key(journal.get("old", "")), _key(journal.get("new", ""))):
            return journal
    return None


def in_flight(output_folder) -> bool:
    """Uma mudança desta pasta está em andamento neste processo agora."""
    with _in_flight_lock:
        return _key(output_folder) in _in_flight


@contextmanager
def flying(*folders):
    """Marca as pastas como em mudança enquanto o bloco roda. Os pedidos que
    chegarem nesse meio tempo (a tela de Execução pergunta a cada 2 s)
    respondem "ocupado" em vez de abrir o banco no meio da troca."""
    keys = {_key(folder) for folder in folders}
    me = threading.get_ident()
    with _in_flight_lock:
        if any(_in_flight.get(key, me) != me for key in keys):
            raise RelocationError("relocation.error.busy")
        added = {key for key in keys if key not in _in_flight}
        for key in added:
            _in_flight[key] = me
    try:
        yield
    finally:
        with _in_flight_lock:
            for key in added:
                _in_flight.pop(key, None)


# --- cópia verificada ---------------------------------------------------------


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(_COPY_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_file_verified(source: Path, target: Path) -> None:
    """Copia byte a byte para um arquivo novo (`xb`: nunca sobrescreve) e
    confere tamanho e SHA-256 lendo a cópia de volta do disco."""
    digest = hashlib.sha256()
    with open(source, "rb") as reader, open(target, "xb") as writer:
        for chunk in iter(lambda: reader.read(_COPY_CHUNK), b""):
            digest.update(chunk)
            writer.write(chunk)
        writer.flush()
        os.fsync(writer.fileno())
    try:
        shutil.copystat(source, target, follow_symlinks=False)
    except OSError:
        pass
    if target.stat().st_size != source.stat().st_size or _sha256(target) != digest.hexdigest():
        raise RelocationError("relocation.error.copy_mismatch", path=str(source))


def _copy_tree_verified(source: Path, target: Path) -> None:
    if _is_link(source):
        raise RelocationError("relocation.error.link", path=str(source))
    if source.is_file():
        _copy_file_verified(source, target)
        return
    target.mkdir(exist_ok=False)
    with os.scandir(source) as entries:
        children = list(entries)
    for entry in children:
        _copy_tree_verified(Path(entry.path), target / entry.name)


def _remove_tree(path: Path) -> None:
    """Apaga um arquivo ou pasta que já foi copiado e conferido. Links não
    são seguidos (e não existem aqui: o plano os recusou)."""
    if _is_link(path):
        # Só o link sai, nunca o que ele aponta: junção é pasta para o
        # Windows (`rmdir`), link de arquivo é arquivo (`unlink`).
        try:
            os.rmdir(path)
        except OSError:
            path.unlink(missing_ok=True)
        return
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


# --- execução -----------------------------------------------------------------


def _new_journal(plan: RelocationPlan, created_new: bool) -> dict:
    action = "move" if plan.same_volume else "copy"
    ops = [{"name": name, "action": action} for name in plan.carried]
    ops += [{"name": name, "action": "copy"} for name in plan.copied_instructions]
    return {
        "version": JOURNAL_VERSION,
        "source": plan.source,
        "old": plan.old,
        "new": plan.new,
        "mode": plan.mode,
        "same_volume": plan.same_volume,
        "ops": ops,
        "strip": list(plan.copied_instructions),
        "dropped": list(plan.dropped),
        "created_new": created_new,
        "phase": "moving",
        "started_at": datetime.now().isoformat(timespec="seconds"),
    }


def _check_space(plan: RelocationPlan) -> None:
    if plan.same_volume:
        return
    parent = Path(plan.new).parent
    while not parent.exists() and parent != parent.parent:
        parent = parent.parent
    free = shutil.disk_usage(parent).free
    needed = plan.total_bytes + _SPACE_MARGIN_BYTES
    if free < needed:
        raise RelocationError(
            "relocation.error.space", needed=megabytes(needed), free=megabytes(free), path=str(parent),
        )


def megabytes(value: int) -> str:
    return f"{value / (1024 * 1024):,.0f}".replace(",", ".")


def execute(plan: RelocationPlan, should_stop=None, on_finalize=None) -> str:
    """Faz a mudança descrita em `plan` e devolve a pasta nova.

    Em qualquer erro antes do ponto de confirmação, desfaz o que fez e
    levanta `RelocationError` (ou `RelocationCancelled` se pediram Parar).
    Depois dele, uma falha deixa o diário para a próxima abertura concluir.
    `on_finalize(old, new)`: o que a interface precisa fazer ao fim
    (esvaziar caches)."""
    old, new = Path(plan.old), Path(plan.new)
    with flying(old, new):
        if pending_for(old) is not None or pending_for(new) is not None:
            raise RelocationError("relocation.error.pending")
        _check_space(plan)
        journal_file = old / "project.db-journal"
        try:
            if journal_file.is_file() and journal_file.stat().st_size > 0:
                raise RelocationError("relocation.error.db_busy")
        except OSError:
            raise RelocationError("relocation.error.db_busy")

        created_new = False
        if plan.mode == "items" or not plan.same_volume:
            try:
                created_new = paths.ensure_writable_folder(str(new))
            except OSError as exc:
                raise RelocationError("relocation.error.not_writable", path=str(new), error=str(exc))
        else:
            # `os.rename` da pasta inteira exige o destino inexistente; uma
            # pasta vazia no lugar (o plano conferiu) sai antes. A prova de
            # gravação é a própria troca de nome: se falhar, nada mudou.
            if new.exists():
                try:
                    new.rmdir()
                except OSError as exc:
                    raise RelocationError("relocation.error.not_writable", path=str(new), error=str(exc))

        journal = _new_journal(plan, created_new)
        try:
            _write_journal(journal)
        except OSError as exc:
            if created_new:
                _remove_if_empty(new)
            raise RelocationError("relocation.error.journal", error=str(exc))

        try:
            _move_all(journal, should_stop)
        except BaseException as exc:
            _undo(journal)
            if isinstance(exc, RelocationCancelled):
                raise
            if isinstance(exc, RelocationError):
                raise
            if isinstance(exc, OSError):
                raise RelocationError("relocation.error.failed", error=f"{type(exc).__name__}: {exc}")
            raise

        journal["phase"] = "committed"
        _write_journal(journal)
        _finish(journal, on_finalize)
        return str(new)


def _remove_if_empty(path: Path) -> None:
    try:
        path.rmdir()
    except OSError:
        pass


def _move_all(journal: dict, should_stop) -> None:
    old, new = Path(journal["old"]), Path(journal["new"])
    if journal["mode"] == "rename" and journal["same_volume"]:
        if should_stop is not None and should_stop():
            raise RelocationCancelled()
        if new.exists():
            raise RelocationError("relocation.error.destination_taken", path=str(new))
        os.rename(old, new)
        return
    for op in journal["ops"]:
        if should_stop is not None and should_stop():
            raise RelocationCancelled()
        source, target = old / op["name"], new / op["name"]
        if target.exists() or target.is_symlink():
            raise RelocationError("relocation.error.collision", path=str(target))
        if _is_link(source):
            raise RelocationError("relocation.error.link", path=str(source))
        if op["action"] == "move":
            os.rename(source, target)
        else:
            _copy_tree_verified(source, target)


def _undo(journal: dict) -> None:
    """Desfaz, na ordem inversa, o que `_move_all` chegou a fazer. Decide
    item a item pelo disco: o que está no destino e falta na origem volta;
    uma cópia cujo original segue no lugar é apagada (o destino estava
    vazio no começo, então o que há nele da lista é nosso). Nunca
    sobrescreve: se os dois lados existem num `move`, nada é tocado."""
    old, new = Path(journal["old"]), Path(journal["new"])
    if journal["mode"] == "rename" and journal["same_volume"]:
        if new.exists() and not old.exists():
            os.rename(new, old)
        _drop_journal(journal)
        return
    for op in reversed(journal["ops"]):
        source, target = old / op["name"], new / op["name"]
        if not (target.exists() or target.is_symlink()):
            continue
        if op["action"] == "move":
            if not source.exists():
                os.rename(target, source)
        elif source.exists():
            _remove_tree(target)
        else:
            os.rename(target, source)
    if journal.get("created_new") or journal["mode"] == "rename":
        _remove_if_empty(new)
    _drop_journal(journal)


def _all_moved(journal: dict) -> bool:
    """Todos os `rename` terminaram (o que uma queda logo antes de anotar
    `committed` deixa). Cópias não contam: só a fase gravada diz que foram
    conferidas."""
    old, new = Path(journal["old"]), Path(journal["new"])
    if journal["mode"] == "rename" and journal["same_volume"]:
        return not old.exists() and (new / paths.PROJECT_DB_NAME).is_file()
    if any(op["action"] != "move" for op in journal["ops"]):
        return False
    return all(
        not (old / op["name"]).exists() and (new / op["name"]).exists() for op in journal["ops"]
    )


def _finish(journal: dict, on_finalize) -> None:
    """Depois do ponto de confirmação. Cada passo é idempotente: uma queda
    no meio repete o que faltou na próxima abertura."""
    old, new = Path(journal["old"]), Path(journal["new"])

    # Originais das cópias, só agora que todas conferiram.
    for op in journal["ops"]:
        if op["action"] != "copy":
            continue
        source = old / op["name"]
        if op["name"] in journal.get("strip", []):
            _strip_generated_block(source)
        elif source.exists() or source.is_symlink():
            _remove_tree(source)

    # As sobras ficam onde estão: na pasta nova se ela mudou de nome
    # inteira, na antiga em qualquer outro caso (nada as copiou).
    remaining = new if journal["mode"] == "rename" and journal["same_volume"] else old
    for name in journal.get("dropped", []):
        _drop_obsolete(remaining / name)
    # A trava que uma batida do coração atrasada possa ter regravado no
    # lugar antigo: é desta máquina e já não descreve nada.
    _remove_own_stray_lock(old)
    if journal["mode"] == "rename" and not journal["same_volume"]:
        _remove_if_empty(old)
    elif journal["mode"] == "items" and old.exists():
        # A pasta antiga só sai se ficou vazia; os arquivos do usuário ficam.
        _remove_if_empty(old)

    _rewrite_project_paths(new)
    relocate_catalog_entry(str(old), str(new))
    sync.rename_key(old, new)
    _rename_work_folder(old, new)
    _forget_postponement(old)
    _record_done(new, old)
    if on_finalize is not None:
        on_finalize(str(old), str(new))
    _drop_journal(journal)


def _strip_generated_block(path: Path) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    remaining = without_managed_block(text)
    if remaining != text:
        try:
            path.write_text(remaining, encoding="utf-8")
        except OSError:
            pass


def _drop_obsolete(folder: Path) -> None:
    """`windows/`: só os arquivos de janela no nome exato que gravávamos.
    `blocks/`: só PDFs (as fatias). A pasta sai se ficar vazia."""
    if _is_link(folder) or not folder.is_dir():
        return
    is_windows = os.path.normcase(folder.name) == os.path.normcase("windows")
    for current, folders, files in os.walk(folder, topdown=False):
        current_path = Path(current)
        for name in files:
            path = current_path / name
            if _is_link(path):
                continue
            ours = LEGACY_WINDOW_FILE.fullmatch(name) if is_windows else name.lower().endswith(".pdf")
            if ours and (not is_windows or current_path == folder):
                try:
                    path.unlink()
                except OSError:
                    pass
        for name in folders:
            child = current_path / name
            if not _is_link(child):
                _remove_if_empty(child)
    _remove_if_empty(folder)


def _remove_own_stray_lock(folder: Path) -> None:
    from .lock import LOCK_FILE_NAME, machine_identity, read_lock

    if not (folder / LOCK_FILE_NAME).is_file():
        return
    lock = read_lock(folder)
    if lock is not None and lock.machine == machine_identity()[0]:
        try:
            (folder / LOCK_FILE_NAME).unlink()
        except OSError:
            pass


def _rewrite_project_paths(new: Path) -> None:
    """`project.output_folder` e o `config_json` passam a dizer a pasta nova.
    `load_project` já faz isso ao abrir uma pasta que não é a gravada;
    chamá-lo aqui grava agora, sem esperar a próxima abertura. Uma falha
    (banco travado) não impede o resto: a abertura seguinte regrava."""
    from .project import load_project

    try:
        _config, conn = load_project(new)
    except (sqlite3.Error, ValueError, OSError):
        return
    except Exception:  # noqa: BLE001 - configuração inválida: a abertura mostra o erro
        return
    conn.close()


def _rename_work_folder(old: Path, new: Path) -> None:
    """A pasta de trabalho local é chaveada pelo caminho da saída
    (`workdir.work_folder`); sem renomeá-la, o projeto na pasta nova não
    acharia os intermediários e refaria o OCR. Se a pasta do caminho novo
    já existir, nada é sobrescrito."""
    source = workdir.work_folder(old)
    target = workdir.work_folder(new)
    if _key(source) == _key(target):
        return
    if source.exists() and not _is_link(source) and not target.exists():
        os.rename(source, target)
    if target.is_dir() and not _is_link(target):
        try:
            (target / workdir.ORIGIN_FILE_NAME).write_text(str(new) + "\n", encoding="utf-8")
        except OSError:
            pass


def _record_done(new: Path, old: Path) -> None:
    from .db import connect
    from .events import record_event

    db_path = new / paths.PROJECT_DB_NAME
    if not db_path.is_file():
        return
    try:
        conn = connect(db_path)
    except sqlite3.Error:
        return
    try:
        record_event(conn, "relocation", "info", "log.relocation.done", {"old": str(old), "new": str(new)})
    except sqlite3.Error:
        pass
    finally:
        conn.close()


# --- retomada -----------------------------------------------------------------


def recover(output_folder, on_finalize=None) -> bool:
    """Conclui ou desfaz a mudança interrompida que envolve esta pasta.
    Devolve `True` se não sobrou diário dela. Erros de disco (a unidade do
    destino não está montada, por exemplo) deixam o diário para a próxima
    vez e devolvem `False`."""
    journal = pending_for(output_folder)
    if journal is None:
        return True
    old, new = Path(journal["old"]), Path(journal["new"])
    try:
        with flying(old, new):
            journal = pending_for(output_folder)  # pode ter sido concluída por outro pedido
            if journal is None:
                return True
            # Unidade fora do ar: decidir pelo disco agora apagaria o diário
            # sem ter devolvido nada. Fica para quando as pastas voltarem.
            if not old.exists() and not new.exists():
                return False
            if journal.get("mode") == "items" and not old.exists():
                return False
            if journal.get("phase") == "moving" and _all_moved(journal):
                journal["phase"] = "committed"
                _write_journal(journal)
            if journal.get("phase") == "committed":
                if not (new / paths.PROJECT_DB_NAME).is_file():
                    return False
                _finish(journal, on_finalize)
            else:
                _undo(journal)
    except RelocationError:
        return False
    except OSError:
        return False
    return pending_for(output_folder) is None
