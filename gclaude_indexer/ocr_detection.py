# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Que idioma o OCR deve ler em cada arquivo escaneado (2.0.0).

A passada roda antes da fila pesada de OCR (`conversion.convert`), arquivo
por arquivo, para PDFs e imagens:

1. PDF com páginas de texto nativo e páginas escaneadas: o texto nativo diz
   o idioma, sem OCR nenhum.
2. Sem texto nativo: o OSD do Tesseract (`osd.traineddata`, que já vinha
   sendo baixado e não era usado) olha até 3 páginas e diz a escrita
   (latina, cirílica, han…) e a rotação de cada uma.
3. Um OCR de amostra dessas páginas com o modelo da escrita
   (`script/Cyrillic`…) dá texto bastante para o detector de idioma
   (`language_detect`). Para a escrita latina vale o inglês que o Tesseract
   já traz: o `script/Latin` tem 89 MB e lê a amostra igual.
4. O OCR final usa os idiomas achados (até 3). Um PDF cujas páginas
   amostradas têm escritas diferentes passa pelo OSD em todas as páginas
   escaneadas e o `ocrmypdf` roda uma vez por grupo de páginas (`--pages`).

Este módulo faz só o trabalho pesado (abrir, OSD, amostra) e devolve textos;
o idioma é decidido no processo principal, onde o modelo do `py3langid` é
carregado uma vez (cada processo do conjunto pagaria ~100 MB por ele).

O plano de um arquivo é um texto (`file.ocr_lang`): `"deu+eng"` vale para o
arquivo todo; `"1-3,7:chi_sim+eng|4-6:deu"` dá os idiomas de cada grupo de
páginas.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import language_detect
from .file_types import category_of_extension

# Below this many characters of text a PDF page needs OCR (section 5,
# step 2). The conversion decides with it and the settings proposal
# predicts with it: the two must agree.
MIN_AVG_CHARS_PER_PAGE = 100

SAMPLE_PAGES = 3
SAMPLE_DPI = 200
# PDF com escritas diferentes nas páginas amostradas: o OSD passa por todas as
# escaneadas até este número; as demais herdam a escrita da página vizinha.
MAX_OSD_PAGES = 200
TESSERACT_TIMEOUT = 60
# Imagem grande demais é reduzida antes do OSD e da amostra: o OSD lê a
# orientação e a escrita, não precisa de 40 megapixels.
_MAX_SAMPLE_SIDE = 2400
# Texto nativo bastante para dizer o idioma sem OCR.
_NATIVE_SAMPLE_CHARS = 12000
# O modelo de uma língua já presente que lê a amostra quando o modelo da
# escrita não está aqui (e, na latina, no lugar dele: ver o passo 3 acima).
_SCRIPT_STAND_INS = {
    "latin": ("eng", "por", "spa", "fra", "deu", "ita"),
    "cyrillic": ("rus", "ukr", "bul", "srp"), "greek": ("ell",), "arabic": ("ara", "fas", "urd"),
    "hebrew": ("heb",), "kana": ("jpn",), "han": ("chi_sim", "chi_tra"), "hangul": ("kor",),
    "devanagari": ("hin", "mar", "nep"), "thai": ("tha",), "bengali": ("ben",), "tamil": ("tam",),
    "georgian": ("kat",), "armenian": ("hye",),
}


# --- plano ----------------------------------------------------------------------


def _pages_text(pages: list[int]) -> str:
    """`[1, 2, 3, 7]` → `"1-3,7"`."""
    parts: list[str] = []
    ordered = sorted(set(pages))
    start = previous = None
    for number in ordered:
        if start is None:
            start = previous = number
        elif number == previous + 1:
            previous = number
        else:
            parts.append(str(start) if start == previous else f"{start}-{previous}")
            start = previous = number
    if start is not None:
        parts.append(str(start) if start == previous else f"{start}-{previous}")
    return ",".join(parts)


def _parse_pages(text: str) -> list[int]:
    pages: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            first, _, last = part.partition("-")
            pages.extend(range(int(first), int(last) + 1))
        else:
            pages.append(int(part))
    return pages


def format_plan(groups: list[tuple[list[int] | None, list[str]]]) -> str:
    """O plano em texto. Um grupo só (ou sem páginas) vira só os idiomas."""
    if len(groups) == 1 or all(pages is None for pages, _ in groups):
        return "+".join(groups[0][1]) if groups else ""
    return "|".join(f"{_pages_text(pages or [])}:{'+'.join(models)}" for pages, models in groups)


def parse_plan(text: str | None) -> list[tuple[list[int] | None, list[str]]]:
    """`[(páginas ou None = todas, [modelos])]`. Texto inválido: `[]`."""
    groups: list[tuple[list[int] | None, list[str]]] = []
    for part in (text or "").split("|"):
        part = part.strip()
        if not part:
            continue
        pages: list[int] | None = None
        if ":" in part:
            pages_text, _, part = part.partition(":")
            try:
                pages = _parse_pages(pages_text)
            except ValueError:
                return []
        models = [model.strip() for model in part.split("+") if model.strip()]
        groups.append((pages, models))
    return groups


def plan_models(text: str | None) -> list[str]:
    """Todos os modelos de um plano, sem repetir."""
    models: list[str] = []
    for _pages, group in parse_plan(text):
        for model in group:
            if model not in models:
                models.append(model)
    return models


def restrict_plan(text: str | None, usable: set[str]) -> tuple[str, bool]:
    """O plano só com os modelos de `usable`, e se algum ficou de fora (o
    arquivo volta à fila quando o resto for baixado). Um grupo sem nenhum
    modelo fica no plano vazio: as páginas dele ficam sem OCR por ora."""
    groups = parse_plan(text)
    short = False
    kept: list[tuple[list[int] | None, list[str]]] = []
    for pages, models in groups:
        allowed = [model for model in models if model in usable]
        short = short or len(allowed) < len(models)
        kept.append((pages, allowed))
    if len(kept) == 1:
        return "+".join(kept[0][1]), short
    return "|".join(f"{_pages_text(pages or [])}:{'+'.join(models)}" for pages, models in kept), short


# --- Tesseract --------------------------------------------------------------------


_OSD_LINE = re.compile(r"^(Rotate|Script):\s*(\S+)", re.MULTILINE)


def osd_image(image) -> tuple[str | None, int] | None:
    """`(escrita, graus para endireitar)` pelo OSD, ou `None` quando ele não
    consegue (página em branco: "Too few characters"; Tesseract ausente)."""
    try:
        import pytesseract

        output = pytesseract.image_to_osd(image, config="--psm 0", timeout=TESSERACT_TIMEOUT)
    except Exception:
        return None
    found = dict(_OSD_LINE.findall(output or ""))
    try:
        rotate = int(found.get("Rotate", "0")) % 360
    except ValueError:
        rotate = 0
    return language_detect.script_from_osd(found.get("Script")), rotate


def ocr_sample(image, model: str) -> str:
    """O texto da amostra lido com `model`; `""` se o Tesseract falhar."""
    try:
        import pytesseract

        return pytesseract.image_to_string(image, lang=model, timeout=TESSERACT_TIMEOUT) or ""
    except Exception:
        return ""


def sample_model(script: str, present: frozenset[str]) -> str | None:
    """O modelo que lê a amostra de uma escrita, entre os presentes aqui: o
    da escrita (na latina, antes uma língua latina já presente), senão uma
    língua dela. `None`: é preciso baixar o modelo da escrita."""
    stand_ins = [model for model in _SCRIPT_STAND_INS.get(script, ()) if model in present]
    if script == "latin" and stand_ins:
        return stand_ins[0]
    model = language_detect.script_model(script)
    if model and model in present:
        return model
    return stand_ins[0] if stand_ins else None


def _prepared(image):
    """Tons de cinza e no máximo `_MAX_SAMPLE_SIDE` pixels de lado."""
    image = image.convert("L")
    largest = max(image.size)
    if largest > _MAX_SAMPLE_SIDE:
        scale = _MAX_SAMPLE_SIDE / largest
        image = image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))))
    return image


def _render(document, number: int):
    from PIL import Image

    page = document[number - 1]
    pixmap = page.get_pixmap(dpi=SAMPLE_DPI, colorspace="gray")
    return Image.frombytes("L", (pixmap.width, pixmap.height), pixmap.samples)


def _spread(pages: list[int], count: int) -> list[int]:
    """Até `count` páginas espalhadas: a primeira, a do meio, a última."""
    if len(pages) <= count:
        return list(pages)
    step = (len(pages) - 1) / (count - 1)
    return sorted({pages[round(index * step)] for index in range(count)})


def scan_pdf(path: Path) -> tuple[list[int], int, str]:
    """`(páginas que precisam de OCR, total, amostra do texto nativo)`. A
    regra das páginas é a de `conversion._pdf_pages_needing_ocr`."""
    import fitz

    document = fitz.open(path)
    try:
        pages: list[int] = []
        sample: list[str] = []
        size = 0
        for number, page in enumerate(document, start=1):
            text = page.get_text()
            stripped = text.strip()
            if len(stripped) < MIN_AVG_CHARS_PER_PAGE and (page.get_images() or page.get_drawings()):
                pages.append(number)
            elif size < _NATIVE_SAMPLE_CHARS and stripped:
                sample.append(stripped)
                size += len(stripped)
        return pages, document.page_count, "\n".join(sample)[:_NATIVE_SAMPLE_CHARS]
    finally:
        document.close()


def _probe_images(images: dict[int, object], present: frozenset[str]) -> dict:
    """OSD e amostra de páginas já abertas. Devolve `scripts` (página →
    escrita), `rotate` (página → graus), `samples` (escrita → texto) e
    `needs` (modelos de escrita a baixar)."""
    scripts: dict[int, str] = {}
    rotate: dict[int, int] = {}
    for number, image in images.items():
        found = osd_image(image)
        if found is None:
            continue
        script, degrees = found
        rotate[number] = degrees
        if script is not None:
            scripts[number] = script
    samples: dict[str, str] = {}
    needs: list[str] = []
    for script in sorted(set(scripts.values())):
        model = sample_model(script, present)
        if model is None:
            wanted = language_detect.script_model(script)
            if wanted and wanted not in needs:
                needs.append(wanted)
            continue
        texts = []
        for number, image in images.items():
            if scripts.get(number) != script:
                continue
            if rotate.get(number):
                # O OSD diz quantos graus girar no sentido horário; o PIL gira
                # no anti-horário.
                image = image.rotate(-rotate[number], expand=True, fillcolor=255)
            texts.append(ocr_sample(image, model))
        samples[script] = "\n".join(texts)
    return {"scripts": scripts, "rotate": rotate, "samples": samples, "needs": needs}


def probe_pdf(path: Path, ocr_pages: list[int], present: frozenset[str]) -> dict:
    """OSD e amostra das páginas escaneadas de um PDF. Com escritas diferentes
    nas páginas amostradas, o OSD passa por todas (até `MAX_OSD_PAGES`) e
    `scripts` cobre cada página escaneada."""
    import fitz

    document = fitz.open(path)
    try:
        chosen = _spread(ocr_pages, SAMPLE_PAGES)
        images = {number: _prepared(_render(document, number)) for number in chosen}
        result = _probe_images(images, present)
        if len(set(result["scripts"].values())) > 1:
            for number in ocr_pages[:MAX_OSD_PAGES]:
                if number in result["scripts"]:
                    continue
                found = osd_image(_prepared(_render(document, number)))
                if found is not None and found[0] is not None:
                    result["scripts"][number] = found[0]
        return result
    finally:
        document.close()


def probe_image(path: Path, present: frozenset[str]) -> dict:
    from PIL import Image

    try:
        from pillow_heif import register_heif_opener

        register_heif_opener()
    except ImportError:
        pass
    with Image.open(path) as image:
        image.load()
        prepared = _prepared(image)
    return _probe_images({1: prepared}, present)


def group_pages(ocr_pages: list[int], scripts: dict[int, str]) -> dict[str, list[int]]:
    """Cada página escaneada na escrita dela; a página que o OSD não leu fica
    com a escrita da vizinha mais próxima já conhecida."""
    if not scripts:
        return {}
    known = sorted(scripts)
    groups: dict[str, list[int]] = {}
    for number in ocr_pages:
        script = scripts.get(number)
        if script is None:
            nearest = min(known, key=lambda page: (abs(page - number), page))
            script = scripts[nearest]
        groups.setdefault(script, []).append(number)
    return groups


# Texto nativo a partir do qual o idioma sai dele, sem OCR de amostra.
_NATIVE_ENOUGH_LETTERS = 200
_NATIVE_ENOUGH_CJK = 60


def native_is_enough(text: str) -> bool:
    counts = language_detect.script_counts(text)
    cjk = counts["han"] + counts["kana"] + counts["hangul"]
    return sum(counts.values()) >= _NATIVE_ENOUGH_LETTERS or cjk >= _NATIVE_ENOUGH_CJK


def detect_file(row: dict, source_folder: str, present: frozenset[str], osd_ready: bool) -> dict:
    """O trabalho pesado da detecção de um PDF ou imagem, num processo do
    conjunto (só argumentos serializáveis; nunca toca o banco). Devolve
    textos e escritas; o idioma é decidido por quem chama.

    Chaves: `ocr_pages`/`page_count` (PDF), `native` (texto nativo),
    `scripts`, `rotate`, `samples` e `needs` (modelos de escrita a baixar)."""
    path = Path(source_folder) / row["relative_path"]
    category = category_of_extension("." + row["extension"])
    result: dict = {
        "id": row["id"], "category": category, "ocr_pages": None, "page_count": None, "native": "",
        "scripts": {}, "rotate": {}, "samples": {}, "needs": [],
    }
    stored = bool(row.get("ocr_lang"))
    if category == "pdf":
        if stored:
            return result  # o plano já existe; as páginas o `_process_file` conta
        ocr_pages, page_count, native = scan_pdf(path)
        result.update(ocr_pages=ocr_pages, page_count=page_count, native=native)
        if not ocr_pages or native_is_enough(native) or not osd_ready:
            return result
        result.update(probe_pdf(path, ocr_pages, present))
        return result
    if not osd_ready:
        return result
    # Imagem com plano guardado (refeita): só a rotação, sem amostra.
    result.update(probe_image(path, present if not stored else frozenset()))
    if stored:
        result["needs"] = []
        result["samples"] = {}
    return result
