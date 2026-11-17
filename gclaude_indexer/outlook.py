# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Arquivos do Outlook (`.pst`, `.ost`) (2.0.0).

Cada mensagem vira uma página do arquivo (como na caixa `.mbox`), com
cabeçalho (De, Para, Data, Assunto, Pasta) e o corpo. Cada anexo que tem
texto vira uma página logo depois da mensagem dele, com uma linha de
cabeçalho que diz de qual anexo se trata: o modelo atual (um arquivo, várias
páginas) já comporta isso, sem tabela nova.

O leitor (`libpff-python`, LGPL-3.0-ou-posterior) fica atrás de uma interface
mínima (`PstReader`), trocada nos testes por um leitor simulado. Sem a
biblioteca, `open_reader` levanta `ReaderUnavailable` e o arquivo fica
ignorado com o motivo `unsupported`.

Arquivos enormes (dezenas de gigabytes) são lidos em fluxo: uma mensagem por
vez, a página escrita assim que pronta. O progresso (quantas mensagens já
estão no arquivo parcial e quantos bytes ele tinha) é gravado ao lado; ao
retomar depois de Parar (ou de uma queda), o arquivo parcial é cortado nesse
ponto e as mensagens já escritas são puladas, sem refazer a leitura dos
anexos (o trabalho caro).
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator, Protocol

from .light_formats import MBOX_PAGE_SEPARATOR

# Tetos (um arquivo de terceiros não pode esgotar disco nem memória).
MAX_MESSAGES = 200_000
MAX_ATTACHMENT_BYTES = 64 * 1024 * 1024
MAX_EXTRACTED_BYTES = 2 * 1024 * 1024 * 1024
# Teto do texto que vai para o intermediário (um anexo pequeno pode virar muito texto).
MAX_OUTPUT_BYTES = 2 * 1024 * 1024 * 1024
MAX_ATTACHMENTS_PER_MESSAGE = 200
MAX_PAGE_CHARS = 2_000_000
MAX_FOLDER_DEPTH = 64
# O progresso vai a disco a cada tantas mensagens (e sempre ao parar).
PROGRESS_EVERY = 25

PROGRESS_SUFFIX = ".progress"
PARTIAL_SUFFIX = ".partial"


class OutlookError(Exception):
    """O arquivo não pôde ser lido (corrompido, protegido, formato errado)."""


class ReaderUnavailable(OutlookError):
    """A biblioteca que lê `.pst`/`.ost` não está neste computador."""


class Interrupted(Exception):
    """Parar foi pedido; o progresso já está gravado."""


class PstAttachment(Protocol):
    name: str
    size: int

    def read(self, limit: int) -> bytes: ...


@dataclass
class PstMessage:
    """Uma mensagem. Os campos de texto podem ser calculados só quando lidos
    (o leitor real faz assim): pular uma mensagem já escrita não custa nada."""

    folder: str = ""
    sender: str = ""
    recipients: str = ""
    date: str = ""
    subject: str = ""
    plain: str = ""
    html: str = ""
    rtf: str = ""
    attachments: list = field(default_factory=list)


class PstReader(Protocol):
    def messages(self) -> Iterator[PstMessage]: ...

    def close(self) -> None: ...


# --- leitor real (libpff) ---------------------------------------------------------


def _text(value) -> str:
    """Texto de um valor do pypff: `str`, `bytes` (decodificados com a mesma
    detecção do resto do programa) ou nada."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    from .text_decoding import decode_bytes

    return decode_bytes(bytes(value))[0]


def _safe(call, default=""):
    try:
        return call()
    except Exception:
        return default


class _PypffAttachment:
    def __init__(self, attachment, index: int) -> None:
        self._attachment = attachment
        self.name = _safe(lambda: _text(attachment.long_filename)) or f"anexo-{index}"
        self.size = _safe(lambda: int(attachment.size or 0), 0)

    def read(self, limit: int) -> bytes:
        return self._attachment.read_buffer(min(self.size, limit)) or b""


class _PypffMessage:
    """Os campos são lidos quando pedidos, nunca ao listar."""

    def __init__(self, message, folder: str) -> None:
        self._message = message
        self.folder = folder

    sender = property(lambda self: _safe(lambda: _text(self._message.sender_name)))
    subject = property(lambda self: _safe(lambda: _text(self._message.subject)))
    plain = property(lambda self: _safe(lambda: _text(self._message.plain_text_body)))
    html = property(lambda self: _safe(lambda: _text(self._message.html_body)))

    @property
    def rtf(self) -> str:
        raw = _safe(lambda: self._message.rtf_body, None)
        return raw.decode("latin-1") if isinstance(raw, (bytes, bytearray)) else (raw or "")

    @property
    def date(self) -> str:
        for name in ("delivery_time", "client_submit_time", "creation_time"):
            value = _safe(lambda: getattr(self._message, name), None)
            if value:
                return str(value)
        return ""

    @property
    def recipients(self) -> str:
        names: list[str] = []
        try:
            recipients = self._message.recipients
            for index in range(recipients.get_number_of_recipients()):
                entries = {}
                for record_set in recipients.get_recipient(index).record_sets:
                    for entry in record_set.entries:
                        # 0x3001: nome de exibição; 0x39FE: endereço SMTP.
                        if entry.entry_type in (0x3001, 0x39FE):
                            entries[entry.entry_type] = _safe(lambda: _text(entry.data_as_string))
                name, address = entries.get(0x3001, ""), entries.get(0x39FE, "")
                names.append(f"{name} <{address}>" if name and address else name or address)
        except Exception:
            pass
        names = [name for name in names if name]
        if names:
            return "; ".join(names)
        # Sem a tabela de destinatários, os cabeçalhos de transporte (quando
        # a mensagem os guarda) ainda dizem para quem foi.
        headers = _safe(lambda: _text(self._message.transport_headers))
        found = re.findall(r"^(?:To|Cc):[ \t]*(.+(?:\r?\n[ \t]+.+)*)", headers, re.IGNORECASE | re.MULTILINE)
        return "; ".join(" ".join(item.split()) for item in found)

    @property
    def attachments(self) -> list:
        count = _safe(lambda: int(self._message.number_of_attachments), 0)
        found = []
        for index in range(min(count, MAX_ATTACHMENTS_PER_MESSAGE)):
            try:
                found.append(_PypffAttachment(self._message.get_attachment(index), index + 1))
            except Exception:
                continue
        return found


class _PypffReader:
    def __init__(self, path: Path) -> None:
        import pypff

        self._file = pypff.file()
        try:
            self._file.open(str(path))
        except Exception as exc:
            raise OutlookError(f"arquivo do Outlook ilegível ou protegido: {exc}") from exc

    def messages(self) -> Iterator[PstMessage]:
        # Pilha explícita (sem recursão): pastas aninhadas fundo demais não
        # estouram a pilha; a ordem é a do arquivo, estável entre execuções.
        root = self._file.get_root_folder()
        stack: list[tuple[object, str, int]] = [(root, "", 0)]
        while stack:
            folder, path, depth = stack.pop()
            for index in range(_safe(lambda: int(folder.number_of_sub_messages), 0)):
                try:
                    yield _PypffMessage(folder.get_sub_message(index), path)
                except Exception:
                    continue
            if depth >= MAX_FOLDER_DEPTH:
                continue
            children = []
            for index in range(_safe(lambda: int(folder.number_of_sub_folders), 0)):
                try:
                    child = folder.get_sub_folder(index)
                except Exception:
                    continue
                name = _safe(lambda: _text(child.name)) or f"pasta-{index + 1}"
                children.append((child, f"{path}/{name}" if path else name, depth + 1))
            stack.extend(reversed(children))

    def close(self) -> None:
        try:
            self._file.close()
        except Exception:
            pass


def open_reader(path: Path) -> PstReader:
    """O leitor de um `.pst`/`.ost`. Os testes trocam esta função."""
    try:
        import pypff  # noqa: F401
    except ImportError as exc:
        raise ReaderUnavailable("leitor de Outlook indisponível neste computador") from exc
    return _PypffReader(path)


# --- nomes de anexo ---------------------------------------------------------------

_RESERVED_NAMES = frozenset(
    {"con", "prn", "aux", "nul", *(f"com{n}" for n in range(1, 10)), *(f"lpt{n}" for n in range(1, 10))}
)
_BAD_CONTROL = re.compile(r"[\x00-\x1f]")
_BAD_CHARS = re.compile(r'[\x00-\x1f<>:"/\\|?*]')


def sanitize_attachment_name(name: str, fallback: str = "anexo") -> str:
    """Um nome de arquivo seguro: sem separadores de caminho, sem caracteres
    que o Windows recusa, sem nome reservado (`CON`, `NUL`…), sem ponto ou
    espaço no fim e de tamanho razoável (a extensão é preservada)."""
    # Só o último componente: o nome nunca leva caminho (`..\..\x.exe`, `a/b.txt`).
    base = re.split(r"[\\/]", str(name or ""))[-1]
    base = _BAD_CHARS.sub("_", base).strip().rstrip(". ")
    if not base or set(base) <= {"_", "."}:
        base = fallback
    stem, dot, extension = base.rpartition(".")
    if not dot:
        stem, extension = base, ""
    if stem.lower() in _RESERVED_NAMES:
        stem = f"_{stem}"
    extension = extension[:16]
    stem = stem[: 120 - len(extension)].rstrip(". ") or fallback
    return f"{stem}.{extension}" if extension else stem


# --- conversão em fluxo -----------------------------------------------------------


def _header(message: PstMessage) -> str:
    lines = [
        f"De: {message.sender}",
        f"Para: {message.recipients}",
        f"Data: {message.date}",
        f"Assunto: {message.subject}",
        f"Pasta: {message.folder}",
    ]
    return "\n".join(lines)


def message_body(message: PstMessage) -> str:
    """O corpo em texto: o simples quando existe; senão o HTML (pelo mesmo
    leitor do resto do programa) e, por último, o RTF."""
    if message.plain and message.plain.strip():
        return message.plain
    if message.html and message.html.strip():
        from .html_text import html_to_text

        return html_to_text(message.html)
    if message.rtf and message.rtf.strip():
        from striprtf.striprtf import rtf_to_text

        return rtf_to_text(message.rtf, encoding="cp1252", errors="ignore")
    return ""


def _clean(text: str) -> str:
    # O avanço de página separa as páginas no intermediário: nunca no texto.
    return text.replace("\x0c", " ")[:MAX_PAGE_CHARS]


def _read_progress(progress: Path, partial: Path, source: Path) -> dict | None:
    """O progresso gravado (mensagens já escritas, bytes e páginas do parcial,
    bytes de anexos já extraídos) se vale para este arquivo de origem (mesmo
    tamanho e data) e o parcial tem aqueles bytes; senão `None`."""
    try:
        data = json.loads(progress.read_text(encoding="utf-8"))
        stat = source.stat()
        if (
            data["size"] == stat.st_size and data["mtime_ns"] == stat.st_mtime_ns
            and partial.stat().st_size >= data["bytes"]
        ):
            return {
                "messages": int(data["messages"]), "bytes": int(data["bytes"]),
                "pages": int(data.get("pages", data["messages"])), "extracted": int(data.get("extracted", 0)),
            }
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def _write_progress(progress: Path, source: Path, messages: int, size: int, pages: int, extracted: int) -> None:
    stat = source.stat()
    temporary = progress.with_name(progress.name + ".tmp")
    temporary.write_text(
        json.dumps({
            "size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "messages": messages, "bytes": size,
            "pages": pages, "extracted": extracted,
        }),
        encoding="utf-8",
    )
    os.replace(temporary, progress)


@dataclass
class PstResult:
    pages: int
    messages: int
    # Por que a leitura parou antes do fim: "messages", "output" ou `None`.
    truncated: str | None = None


# `attachment_text(path, original_name)` devolve o texto de um anexo já
# gravado em disco, pelo extrator do tipo real dele, ou `None` quando o tipo
# não é lido (compactado, binário, chave, imagem sem OCR…). `original_name`
# é o nome como veio no arquivo (sem caminho), antes do saneamento: é o que
# as mesmas regras da varredura (`.env`, `id_rsa`…) precisam ver.
AttachmentText = Callable[[Path, str], "str | None"]


def convert_pst(
    source: Path,
    destination: Path,
    attachments_root: Path,
    attachment_text: AttachmentText,
    should_stop: Callable[[], bool] | None = None,
    reader_factory: Callable[[Path], PstReader] | None = None,
    on_note: Callable[[str, dict], None] | None = None,
) -> PstResult:
    """Escreve em `destination` o texto do arquivo, uma página por mensagem (e
    uma por anexo com texto), separadas por `MBOX_PAGE_SEPARATOR`.

    Levanta `Interrupted` quando Parar é pedido (o que já foi escrito fica
    para a retomada), `ReaderUnavailable` sem a biblioteca e `OutlookError`
    para um arquivo ilegível. Os anexos são gravados em
    `attachments_root/<n>/<nome>`, lidos e apagados em seguida."""
    reader_factory = reader_factory or open_reader
    partial = destination.with_name(destination.name + PARTIAL_SUFFIX)
    progress = destination.with_name(destination.name + PROGRESS_SUFFIX)

    saved = _read_progress(progress, partial, source) or {"messages": 0, "bytes": 0, "pages": 0, "extracted": 0}
    skip, size, pages = saved["messages"], saved["bytes"], saved["pages"]
    # O teto de anexos é do arquivo, não da execução: vale também na retomada.
    extracted = saved["extracted"]
    reader = reader_factory(source)
    truncated = None
    written = skip
    try:
        with open(partial, "ab") as handle:
            handle.truncate(size)
            handle.seek(size)

            def emit(text: str) -> None:
                nonlocal size, pages
                chunk = ((MBOX_PAGE_SEPARATOR if pages else "") + _clean(text)).encode("utf-8")
                handle.write(chunk)
                size += len(chunk)
                pages += 1

            def save() -> None:
                handle.flush()
                _write_progress(progress, source, written, size, pages, extracted)

            for index, message in enumerate(reader.messages()):
                if index >= MAX_MESSAGES:
                    truncated = "messages"
                    break
                if index < skip:
                    continue
                if size >= MAX_OUTPUT_BYTES:
                    truncated = "output"
                    break
                if should_stop is not None and should_stop():
                    save()
                    raise Interrupted()
                emit(f"{_header(message)}\n\n{message_body(message)}")
                extracted += _attachments(
                    message, attachments_root / str(index + 1), attachment_text, emit,
                    MAX_EXTRACTED_BYTES - extracted, on_note, lambda: size >= MAX_OUTPUT_BYTES,
                )
                written = index + 1
                if written % PROGRESS_EVERY == 0:
                    save()
            handle.flush()
    finally:
        reader.close()
        shutil.rmtree(attachments_root, ignore_errors=True)

    if pages == 0:
        # Caixa sem mensagens: uma página vazia, como um arquivo vazio.
        partial.write_text("", encoding="utf-8")
        pages = 1
    os.replace(partial, destination)
    try:
        progress.unlink()
    except OSError:
        pass
    return PstResult(pages=pages, messages=written, truncated=truncated)


def _attachments(
    message: PstMessage,
    folder: Path,
    attachment_text: AttachmentText,
    emit: Callable[[str], None],
    budget: int,
    on_note: Callable[[str, dict], None] | None,
    output_full: Callable[[], bool] = lambda: False,
) -> int:
    """Grava cada anexo na pasta da mensagem, lê pelo extrator do tipo real e
    acrescenta uma página com o texto; devolve os bytes gravados."""
    used = 0
    taken: set[str] = set()
    try:
        attachments = list(message.attachments)[:MAX_ATTACHMENTS_PER_MESSAGE]
    except Exception:
        return 0
    for number, attachment in enumerate(attachments, start=1):
        if output_full():
            break
        raw_name = re.split(r"[\\/]", str(getattr(attachment, "name", "") or ""))[-1]
        # O mesmo tratamento do nome gravado em disco (sem controles, sem
        # espaço nem ponto no fim): `.env `, `id_rsa.` e `chave.pem. ` não
        # podem enganar a regra de segredos por diferença de leitura.
        raw_name = _BAD_CONTROL.sub("", raw_name).strip().rstrip(". ")
        label = sanitize_attachment_name(raw_name, f"anexo-{number}")
        if label.lower() in taken:
            label = f"{number}-{label}"
        taken.add(label.lower())
        size = int(getattr(attachment, "size", 0) or 0)
        if size > MAX_ATTACHMENT_BYTES or used + size > budget:
            if on_note is not None:
                on_note("attachment_too_large", {"name": label})
            continue
        try:
            data = attachment.read(MAX_ATTACHMENT_BYTES)
        except Exception:
            continue
        if not data or used + len(data) > budget:
            continue
        folder.mkdir(parents=True, exist_ok=True)
        target = (folder / label).resolve()
        if not target.is_relative_to(folder.resolve()):
            continue
        target.write_bytes(data)
        used += len(data)
        try:
            text = attachment_text(target, raw_name)
        except Exception:
            text = None
        finally:
            # O extrator pode ter renomeado o arquivo (tipo real diferente da
            # extensão): a pasta da mensagem inteira vai embora, não só o alvo.
            shutil.rmtree(folder, ignore_errors=True)
        if text and text.strip():
            # O texto também tem teto: um anexo pequeno pode virar muito texto.
            emit(f"Anexo: {label} (mensagem: {message.subject})\n\n{text[:MAX_PAGE_CHARS]}")
    shutil.rmtree(folder, ignore_errors=True)
    return used
