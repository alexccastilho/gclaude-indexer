# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""The OCR language data, installed without administrator rights.

`winget install UB-Mannheim.TesseractOCR` brings English only, and its data
folder (`C:\\Program Files\\Tesseract-OCR\\tessdata`) needs administrator
rights to write. Up to 1.5.18 the installer asked Windows for elevation to
copy `por.traineddata` there; when that approval did not happen (refused,
hidden behind the setup window, timed out) the language was simply missing,
and the "About" screen sent the user to download it by hand — for
something the program cannot work without.

Now the language data lives in this machine's own folder
(`%LOCALAPPDATA%\\GClaudeIndexer\\tessdata`), which never needs elevation:
the languages Tesseract already has are copied there, the missing ones are
downloaded from the pinned `tessdata_fast` commit with their SHA-256
checked, and **this process only** points Tesseract at that folder through
`TESSDATA_PREFIX`. Nothing machine-wide changes: other programs that use
Tesseract keep its own folder.

Tesseract's own folder is used as it is whenever it already has every
language needed — then nothing is copied, downloaded or redirected.

Fase 34: a data folder is only usable with its `configs/` too —
`tesseract … hocr txt` reads those names as config files — so the private
folder also receives `configs/` and `tessconfigs/` (copied, or the
essential ones written), and a folder without them is never "ready".
"""

from __future__ import annotations

import hashlib
import os
import shutil
import threading
import urllib.request
from pathlib import Path

from .paths import machine_local_folder

# Same commit and hashes as `install.ps1` (tag 4.1.0, the build UB-Mannheim
# ships). Only a pinned language is ever downloaded: the hash decides.
TESSDATA_COMMIT = "65727574dfcd264acbb0c3e07860e4e9e9b22185"
TESSDATA_URL = f"https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/{TESSDATA_COMMIT}/"
PINNED_SHA256 = {
    "por": "c4932b937207a9514b7514d518b931a99938c02a28a5a5a553f8599ed58b7deb",
    "eng": "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2",
    "spa": "6f2e04d02774a18f01bed44b1111f2cd7f3ba7ac9dc4373cd3f898a40ea6b464",
    "osd": "9cf5d576fcc47564f11265841e5ca839001e7e6f38ff7f7aacf46d15a96b00ff",
}
_DOWNLOAD_TIMEOUT_S = 120
_lock = threading.Lock()


def private_folder() -> Path:
    return machine_local_folder() / "tessdata"


def wanted(ocr_language: str | None) -> list[str]:
    """Tesseract's own syntax: "por+eng" means both."""
    return [part.strip() for part in (ocr_language or "por").split("+") if part.strip()]


def _has(folder: Path | None, language: str) -> bool:
    return folder is not None and (folder / f"{language}.traineddata").is_file()


# Fase 34: a pasta de dados não é só os `.traineddata`. O
# Tesseract lê o formato de saída como um *arquivo de configuração*:
# `tesseract img out hocr txt` (o que o ocrmypdf executa) abre
# `TESSDATA_PREFIX/configs/hocr` e `.../configs/txt`. A pasta privada da
# 1.5.19 só copiava os idiomas; o Tesseract avisava ("read_params_file:
# Can't open hocr"), gerava só o `.txt`, e o ocrmypdf quebrava em
# `render_hocr_page` (código 15) em **toda** página escaneada de PDF — num
# acervo grande, vários arquivos ficaram sem preparar e outros parciais, enquanto as imagens
# JPG passavam porque o pytesseract não pede config nenhum. Com `configs/`
# na pasta, o mesmo arquivo saiu com código 0.
_CONFIG_FOLDERS = ("configs", "tessconfigs")
# Conteúdo oficial (tessdata/configs do próprio Tesseract), para uma
# distribuição portátil que não traga a pasta: o suficiente para hOCR,
# texto, PDF e TSV — os formatos que ocrmypdf e pytesseract podem pedir.
_MINIMAL_CONFIGS = {
    "hocr": "tessedit_create_hocr 1\n",
    "txt": "tessedit_create_txt 1\n",
    "pdf": "tessedit_create_pdf 1\n",
    "tsv": "tessedit_create_tsv 1\n",
}


def _has_configs(folder: Path | None) -> bool:
    return folder is not None and all((folder / "configs" / name).is_file() for name in ("hocr", "txt"))


def _ready(folder: Path | None, languages: list[str]) -> bool:
    """A folder Tesseract can be pointed at as it is: every language *and*
    the output configs ocrmypdf asks for."""
    return all(_has(folder, lang) for lang in languages) and _has_configs(folder)


def _complete_configs(private: Path, sources: tuple[Path | None, ...]) -> None:
    """Brings `configs/` and `tessconfigs/` into the private folder: copied
    from the first source that has them (Tesseract's own folder keeps ~25
    configs; all come, a user may ask for `tsv` or `pdf` elsewhere), and the
    four essential ones written when no source had them. Runs on every
    `ensure`, so a folder created by 1.5.19 without them is repaired on the
    first conversion after the update — nothing is overwritten."""
    for source in sources:
        if source is None or not source.is_dir() or source == private:
            continue
        for name in _CONFIG_FOLDERS:
            origin = source / name
            if not origin.is_dir():
                continue
            target_folder = private / name
            try:
                target_folder.mkdir(exist_ok=True)
            except OSError:
                continue
            for item in origin.iterdir():
                target = target_folder / item.name
                if item.is_file() and not target.exists():
                    try:
                        shutil.copy2(item, target)
                    except OSError:
                        pass
    configs = private / "configs"
    try:
        configs.mkdir(exist_ok=True)
    except OSError:
        return
    for name, content in _MINIMAL_CONFIGS.items():
        target = configs / name
        if not target.exists():
            try:
                target.write_text(content, encoding="ascii")
            except OSError:
                pass


def tesseract_folder(tesseract_path: str | None) -> Path | None:
    """Tesseract's own data folder, next to the executable."""
    if not tesseract_path:
        return None
    folder = Path(tesseract_path).resolve().parent / "tessdata"
    return folder if folder.is_dir() else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _download(language: str, target: Path) -> bool:
    expected = PINNED_SHA256.get(language)
    if expected is None:
        return False
    partial = target.with_suffix(".part")
    try:
        with urllib.request.urlopen(f"{TESSDATA_URL}{language}.traineddata", timeout=_DOWNLOAD_TIMEOUT_S) as answer:
            with partial.open("wb") as handle:
                shutil.copyfileobj(answer, handle)
        if _sha256(partial) != expected:
            partial.unlink(missing_ok=True)
            return False
        partial.replace(target)
        return True
    except OSError:
        partial.unlink(missing_ok=True)
        return False


def ensure(ocr_language: str | None, tesseract_path: str | None, download: bool = True) -> list[str]:
    """Makes every language of `ocr_language` readable by Tesseract in this
    process, and returns the ones still missing (empty: all set).

    In order: a `TESSDATA_PREFIX` the user set that is ready (languages and
    `configs/`) is left alone; Tesseract's own folder that is ready is used
    as it is; otherwise the private folder is completed (languages copied
    from Tesseract's own folder, downloaded when `download`; `configs/`
    copied or written — fase 34) and this process points at it."""
    languages = wanted(ocr_language)
    with _lock:
        private = private_folder()
        current = os.environ.get("TESSDATA_PREFIX", "").strip()
        current_folder = Path(current) if current else None
        # The private folder itself is never "left alone": it is the one
        # this module owns, and the one that may still lack `configs/`.
        if current_folder is not None and current_folder != private and _ready(current_folder, languages):
            return []
        own = tesseract_folder(tesseract_path)
        if current_folder is None and own is not None and _ready(own, languages):
            return []

        try:
            private.mkdir(parents=True, exist_ok=True)
        except OSError:
            return [lang for lang in languages if not _has(own, lang)]
        # Everything Tesseract already knows comes along: pointing it at
        # this folder must not make it forget English or the orientation
        # model, nor a language the user added to its own folder.
        for source in (own, current_folder):
            if source is None or not source.is_dir() or source == private:
                continue
            for data in source.glob("*.traineddata"):
                target = private / data.name
                if not target.exists():
                    try:
                        shutil.copy2(data, target)
                    except OSError:
                        pass
        for lang in languages + ["osd"]:
            if not _has(private, lang) and download:
                _download(lang, private / f"{lang}.traineddata")
        _complete_configs(private, (own, current_folder))

        missing = [lang for lang in languages if not _has(private, lang)]
        if not missing and _has_configs(private):
            os.environ["TESSDATA_PREFIX"] = str(private)
        return missing


def ensure_in_background(ocr_language: str | None, tesseract_path: str | None) -> threading.Thread:
    """`ensure` without holding up the server's start (a download is ~2 MB
    per language, on a slow network that is seconds)."""
    thread = threading.Thread(
        target=lambda: ensure(ocr_language, tesseract_path), name="ocr-languages", daemon=True
    )
    thread.start()
    return thread
