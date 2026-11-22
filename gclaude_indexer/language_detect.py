# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Escrita e idioma de um texto, em qualquer idioma (2.0.0).

Até a 1.10 o projeto tinha um idioma só (`config.ocr_language`), adivinhado
por palavras frequentes de português, espanhol e inglês. Um acervo com um
contrato em alemão ou uma certidão em russo passava pelo OCR em português, e
o classificador resumia tudo em português.

Aqui ficam as duas perguntas, sem rede e sem Tesseract:

- **escrita** (latina, cirílica, árabe, han, kana, hangul…), pelos blocos
  Unicode das letras — exata e de graça;
- **idioma**, pelo `py3langid` (BSD-3-Clause, modelo de ~4,5 MB que já vem
  no pacote; carregado uma vez, na primeira pergunta). As escritas do Leste
  Asiático decidem sozinhas: havendo kana é japonês; han sem kana é chinês;
  hangul é coreano.

E a tradução para o Tesseract: o código ISO (o que se mostra e se grava em
`file.language`) vira o modelo do Tesseract (`deu`, `rus`, `chi_sim`…) por uma
tabela só (`TESSERACT_CODES`). Idioma sem modelo no Tesseract cai no modelo
da escrita (`script/Cyrillic`, `script/Latin`…), que lê qualquer idioma dela.
"""

from __future__ import annotations

import bisect
import re
import threading
from collections import Counter

# --- escritas -------------------------------------------------------------------

# (início, fim, escrita), em ordem. Só letras contam (`str.isalpha`): dígitos e
# pontuação são de todas as escritas.
_RANGES: list[tuple[int, int, str]] = sorted([
    (0x0041, 0x024F, "latin"), (0x0250, 0x02AF, "latin"), (0x1E00, 0x1EFF, "latin"),
    (0x2C60, 0x2C7F, "latin"), (0xA720, 0xA7FF, "latin"), (0xFF21, 0xFF5A, "latin"),
    (0x0370, 0x03FF, "greek"), (0x1F00, 0x1FFF, "greek"),
    (0x0400, 0x052F, "cyrillic"), (0x1C80, 0x1C8F, "cyrillic"), (0x2DE0, 0x2DFF, "cyrillic"),
    (0xA640, 0xA69F, "cyrillic"),
    (0x0530, 0x058F, "armenian"),
    (0x0590, 0x05FF, "hebrew"), (0xFB1D, 0xFB4F, "hebrew"),
    (0x0600, 0x06FF, "arabic"), (0x0750, 0x077F, "arabic"), (0x08A0, 0x08FF, "arabic"),
    (0xFB50, 0xFDFF, "arabic"), (0xFE70, 0xFEFF, "arabic"),
    (0x0700, 0x074F, "syriac"),
    (0x0780, 0x07BF, "thaana"),
    (0x0900, 0x097F, "devanagari"),
    (0x0980, 0x09FF, "bengali"),
    (0x0A00, 0x0A7F, "gurmukhi"),
    (0x0A80, 0x0AFF, "gujarati"),
    (0x0B00, 0x0B7F, "oriya"),
    (0x0B80, 0x0BFF, "tamil"),
    (0x0C00, 0x0C7F, "telugu"),
    (0x0C80, 0x0CFF, "kannada"),
    (0x0D00, 0x0D7F, "malayalam"),
    (0x0D80, 0x0DFF, "sinhala"),
    (0x0E00, 0x0E7F, "thai"),
    (0x0E80, 0x0EFF, "lao"),
    (0x0F00, 0x0FFF, "tibetan"),
    (0x1000, 0x109F, "myanmar"),
    (0x10A0, 0x10FF, "georgian"),
    (0x1100, 0x11FF, "hangul"), (0x3130, 0x318F, "hangul"), (0xA960, 0xA97F, "hangul"),
    (0xAC00, 0xD7AF, "hangul"), (0xFFA0, 0xFFDC, "hangul"),
    (0x1200, 0x139F, "ethiopic"),
    (0x13A0, 0x13FF, "cherokee"),
    (0x1400, 0x167F, "canadian_aboriginal"),
    (0x1780, 0x17FF, "khmer"),
    (0x3040, 0x309F, "kana"), (0x30A0, 0x30FF, "kana"), (0x31F0, 0x31FF, "kana"),
    (0xFF66, 0xFF9F, "kana"),
    (0x2E80, 0x2FDF, "han"), (0x3005, 0x3007, "han"), (0x3400, 0x4DBF, "han"),
    (0x4E00, 0x9FFF, "han"), (0xF900, 0xFAFF, "han"), (0x20000, 0x323AF, "han"),
])
_STARTS = [start for start, _end, _script in _RANGES]

# Escritas sem espaço entre as palavras: a busca por palavras (FTS5
# `unicode61`) não as acha, e vão também para a tabela `trigram`
# (`fulltext.py`).
UNSPACED_SCRIPTS = frozenset({"han", "kana", "hangul", "thai", "lao", "khmer", "myanmar", "tibetan"})
# Escritas em que um caractere carrega o que uma palavra carrega numa escrita
# alfabética: o limite de caracteres por página é menor (`auto_settings`).
CJK_SCRIPTS = frozenset({"han", "kana", "hangul"})


def _unspaced_ranges() -> list[tuple[int, int]]:
    """As faixas de `_RANGES` das escritas sem espaço, contíguas unidas."""
    merged: list[tuple[int, int]] = []
    for start, end, script in _RANGES:
        if script not in UNSPACED_SCRIPTS:
            continue
        if merged and merged[-1][1] + 1 >= start:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


# Classe de caracteres das escritas sem espaço (`[...]` de expressão regular
# e do `GLOB` do SQLite, que entendem `a-b` do mesmo jeito).
_UNSPACED_CLASS = "".join(f"{chr(start)}-{chr(end)}" for start, end in _unspaced_ranges())
_UNSPACED_CHAR = re.compile(f"[{_UNSPACED_CLASS}]")
# Algum caractere dessas escritas, no `GLOB` do SQLite (`fulltext.backfill_trigram`).
UNSPACED_GLOB = f"*[{_UNSPACED_CLASS}]*"
_SPACE_BETWEEN_UNSPACED = re.compile(f"(?<=[{_UNSPACED_CLASS}])[ \\t\u3000]+(?=[{_UNSPACED_CLASS}])")


def script_of(char: str) -> str | None:
    """A escrita de uma letra, ou `None` (dígito, pontuação, símbolo)."""
    if not char.isalpha():
        return None
    code = ord(char)
    index = bisect.bisect_right(_STARTS, code) - 1
    if index >= 0:
        start, end, script = _RANGES[index]
        if start <= code <= end:
            return script
    return None


def script_counts(text: str) -> Counter:
    """Quantas letras de cada escrita há no texto."""
    counts: Counter = Counter()
    for char in text:
        script = script_of(char)
        if script is not None:
            counts[script] += 1
    return counts


def dominant_script(text: str) -> str | None:
    """A escrita com mais letras, ou `None` sem letra nenhuma. Kana e han
    juntos contam como japonês (`kana`): um texto japonês tem mais kanji que
    kana com frequência, e mesmo assim é japonês."""
    counts = script_counts(text)
    if not counts:
        return None
    if counts["kana"] and counts["kana"] * 20 >= counts["kana"] + counts["han"]:
        counts["kana"] += counts.pop("han", 0)
    return counts.most_common(1)[0][0]


def cjk_count(counts: Counter) -> int:
    """Quantas letras de `script_counts` são de `CJK_SCRIPTS`."""
    return sum(counts[script] for script in CJK_SCRIPTS)


def is_unspaced(text: str) -> bool:
    """Se o texto é, na maior parte, de uma escrita sem espaço entre palavras."""
    return dominant_script(text) in UNSPACED_SCRIPTS


def has_unspaced(text: str) -> bool:
    return _UNSPACED_CHAR.search(text or "") is not None


def collapse_unspaced_spaces(text: str) -> str:
    """Tira o espaço entre dois caracteres de escrita sem espaço. O OCR
    (e a extração de alguns PDFs) põe espaço entre ideogramas — "东京 都" —
    e a busca por "东京都" não acharia o trecho."""
    return _SPACE_BETWEEN_UNSPACED.sub("", text)


# --- idioma ---------------------------------------------------------------------

# Abaixo disto o palpite do modelo é ruído: uma assinatura, um carimbo.
MIN_LETTERS = 40
MIN_CJK_CHARS = 12
# Um idioma só entra na lista com pelo menos esta fatia do texto.
_MIN_SHARE = 0.15
# 2.1.3: palpite de um trecho abaixo desta probabilidade é ruído. Uma folha
# de ponto escaneada (só horários e riscos) saía iorubá, lígure ou lingala
# com 0,02; num acervo inteiro, todo trecho com 0,5 ou mais era o idioma
# certo e os códigos exóticos ficavam todos abaixo de 0,3.
MIN_PROBABILITY = 0.5
_CHUNK_CHARS = 400
MAX_LANGUAGES = 3

_identifier = None
_identifier_lock = threading.Lock()
_identifier_failed = False


def _model():
    """O identificador do `py3langid`, carregado uma vez por processo (~0,6 s).
    Sem a biblioteca (instalação incompleta), `None`: as escritas do Leste
    Asiático ainda decidem, o resto fica sem idioma e o projeto decide."""
    global _identifier, _identifier_failed
    if _identifier is not None or _identifier_failed:
        return _identifier
    with _identifier_lock:
        if _identifier is None and not _identifier_failed:
            try:
                from py3langid.langid import MODEL_FILE, LanguageIdentifier

                # Uma instância própria, não a do módulo: `set_languages` dele é
                # estado global, e a extração lê páginas em várias linhas.
                _identifier = LanguageIdentifier.from_model_file(MODEL_FILE, norm_probs=True)
            except Exception:
                _identifier_failed = True
    return _identifier


# Escrita de cada idioma que o modelo conhece fora da latina: um palpite que
# não bate com a escrita do trecho é descartado (o modelo às vezes chama de
# "mongol" um parágrafo latino cheio de siglas).
_LANGUAGE_SCRIPT = {
    "ru": "cyrillic", "uk": "cyrillic", "bg": "cyrillic", "be": "cyrillic", "mk": "cyrillic",
    "sr": "cyrillic", "kk": "cyrillic", "ky": "cyrillic", "mn": "cyrillic", "tg": "cyrillic",
    "tt": "cyrillic", "ba": "cyrillic", "el": "greek", "grc": "greek", "ar": "arabic", "ary": "arabic",
    "arz": "arabic", "fa": "arabic", "ur": "arabic", "ps": "arabic", "ug": "arabic", "sd": "arabic",
    "he": "hebrew", "hbo": "hebrew", "yi": "hebrew", "hy": "armenian", "ka": "georgian",
    "hi": "devanagari", "mr": "devanagari", "ne": "devanagari", "sa": "devanagari", "gom": "devanagari",
    "bn": "bengali", "as": "bengali", "pa": "gurmukhi", "gu": "gujarati", "or": "oriya", "ta": "tamil",
    "te": "telugu", "kn": "kannada", "ml": "malayalam", "si": "sinhala", "th": "thai", "lo": "lao",
    "km": "khmer", "my": "myanmar", "bo": "tibetan", "dz": "tibetan", "am": "ethiopic",
    "ja": "kana", "zh": "han", "yue": "han", "wuu": "han", "ko": "hangul",
}


def _chunks(text: str) -> list[str]:
    """Pedaços de ~400 caracteres, cortados em fim de linha: um documento com
    um parágrafo em inglês e o resto em alemão tem os dois idiomas."""
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in text.splitlines():
        current.append(line)
        size += len(line) + 1
        if size >= _CHUNK_CHARS:
            chunks.append("\n".join(current))
            current, size = [], 0
    if current:
        chunks.append("\n".join(current))
    return chunks


def _east_asian(counts: Counter) -> str | None:
    """Kana decide japonês; han sem kana, chinês; hangul, coreano."""
    if counts["kana"] >= 3 or (counts["kana"] and counts["kana"] * 20 >= counts["han"]):
        return "ja"
    if counts["hangul"] and counts["hangul"] >= counts["han"]:
        return "ko"
    if counts["han"]:
        return "zh"
    if counts["hangul"]:
        return "ko"
    return None


def east_asian_language(text: str) -> str | None:
    """"ja", "ko" ou "zh" pela escrita, sem o modelo do `py3langid` (que um
    processo do conjunto não carrega)."""
    return _east_asian(script_counts(text))


def _chunk_language(chunk: str, counts: Counter) -> str | None:
    script = counts.most_common(1)[0][0]
    if script in CJK_SCRIPTS:
        return _east_asian(counts)
    identifier = _model()
    if identifier is None:
        return None
    try:
        ranked = identifier.rank(chunk)
    except Exception:
        return None
    for code, score in ranked[:5]:
        expected = _LANGUAGE_SCRIPT.get(code, "latin")
        if expected == script:
            if score < MIN_PROBABILITY:
                return None
            return None if code == "zxx" else code
    return None


def detect_languages(text: str, max_languages: int = MAX_LANGUAGES) -> list[str]:
    """Os idiomas do texto (códigos ISO do `py3langid`: "pt", "de", "ja"…),
    do mais presente ao menos, até `max_languages`. `[]` com texto curto
    demais para dizer."""
    text = text or ""
    total = script_counts(text)
    cjk = cjk_count(total)
    letters = sum(total.values())
    if letters < MIN_LETTERS and cjk < MIN_CJK_CHARS:
        return []
    weights: Counter = Counter()
    for chunk in _chunks(text):
        counts = script_counts(chunk)
        size = sum(counts.values())
        if size < 15:
            continue
        code = _chunk_language(chunk, counts)
        if code:
            weights[code] += size
    if not weights:
        # Pedaços curtos demais um a um (uma lista de nomes): o texto inteiro.
        code = _chunk_language(text, total) if total else None
        return [code] if code else []
    whole = sum(weights.values())
    return [code for code, weight in weights.most_common() if weight / whole >= _MIN_SHARE][:max_languages]


def majority_language(texts: list[str]) -> tuple[list[str], str | None]:
    """`(idiomas, majoritário)` de vários textos (as páginas de uma janela),
    pesados pelo tamanho de cada um. O majoritário é o que o classificador usa
    para escrever o tipo e o resumo."""
    weights: Counter = Counter()
    for text in texts:
        found = detect_languages(text, max_languages=1)
        if found:
            weights[found[0]] += max(1, sum(script_counts(text).values()))
    if not weights:
        return [], None
    ranked = [code for code, _ in weights.most_common()]
    return ranked, ranked[0]


# --- Tesseract ------------------------------------------------------------------

# Código ISO (do `py3langid` e do whisper) → modelo do `tessdata_fast`. Todo
# valor daqui está no manifesto (`tests/test_idiomas.py` confere).
TESSERACT_CODES = {
    "af": "afr", "am": "amh", "ar": "ara", "ary": "ara", "arz": "ara", "as": "asm", "az": "aze",
    "be": "bel", "bg": "bul", "bn": "ben", "bo": "bod", "br": "bre", "bs": "bos", "ca": "cat",
    "ceb": "ceb", "chr": "chr", "co": "cos", "cs": "ces", "cy": "cym", "da": "dan", "de": "deu",
    "dv": "div", "dz": "dzo", "el": "ell", "en": "eng", "eo": "epo", "es": "spa", "et": "est",
    "eu": "eus", "fa": "fas", "fi": "fin", "fil": "fil", "fo": "fao", "fr": "fra", "fy": "fry",
    "ga": "gle", "gd": "gla", "gl": "glg", "grc": "grc", "gu": "guj", "hbo": "heb", "he": "heb",
    "hi": "hin", "hr": "hrv", "ht": "hat", "hu": "hun", "hy": "hye", "id": "ind", "is": "isl",
    "it": "ita", "iu": "iku", "ja": "jpn", "jv": "jav", "jw": "jav", "ka": "kat", "kk": "kaz",
    "km": "khm", "kn": "kan", "ko": "kor", "ku": "kmr", "ky": "kir", "la": "lat", "lb": "ltz",
    "lo": "lao", "lt": "lit", "lv": "lav", "mi": "mri", "mk": "mkd", "ml": "mal", "mn": "mon",
    "mr": "mar", "ms": "msa", "mt": "mlt", "my": "mya", "ne": "nep", "nl": "nld", "nn": "nor",
    "no": "nor", "oc": "oci", "or": "ori", "pa": "pan", "pl": "pol", "ps": "pus", "pt": "por",
    "qu": "que", "ro": "ron", "ru": "rus", "sa": "san", "sd": "snd", "si": "sin", "sk": "slk",
    "sl": "slv", "sq": "sqi", "sr": "srp", "su": "sun", "sv": "swe", "sw": "swa", "syr": "syr",
    "ta": "tam", "te": "tel", "tg": "tgk", "th": "tha", "ti": "tir", "tl": "fil", "to": "ton",
    "tr": "tur", "tt": "tat", "ug": "uig", "uk": "ukr", "ur": "urd", "uz": "uzb", "vi": "vie",
    "wuu": "chi_sim", "yi": "yid", "yo": "yor", "yue": "chi_tra", "zh": "chi_sim",
}

# Escrita → modelo de escrita do `tessdata_fast` (`script/<Nome>`). Han vai
# para o chinês simplificado; o japonês tem modelo próprio (com kana).
SCRIPT_MODELS = {
    "latin": "Latin", "greek": "Greek", "cyrillic": "Cyrillic", "armenian": "Armenian",
    "hebrew": "Hebrew", "arabic": "Arabic", "syriac": "Syriac", "thaana": "Thaana",
    "devanagari": "Devanagari", "bengali": "Bengali", "gurmukhi": "Gurmukhi", "gujarati": "Gujarati",
    "oriya": "Oriya", "tamil": "Tamil", "telugu": "Telugu", "kannada": "Kannada",
    "malayalam": "Malayalam", "sinhala": "Sinhala", "thai": "Thai", "lao": "Lao", "tibetan": "Tibetan",
    "myanmar": "Myanmar", "georgian": "Georgian", "hangul": "Hangul", "ethiopic": "Ethiopic",
    "cherokee": "Cherokee", "canadian_aboriginal": "Canadian_Aboriginal", "khmer": "Khmer",
    "kana": "Japanese", "han": "HanS",
}

# Idiomas de cada escrita cujo modelo, já presente, pode ler uma amostra dela
# no lugar do modelo da escrita (`ocr_detection.sample_model`), do preferido
# ao último. Cada código é de um idioma daquela escrita (`_LANGUAGE_SCRIPT`;
# `tests/test_idiomas.py` confere) e o modelo sai de `TESSERACT_CODES`.
_STAND_IN_LANGUAGES = {
    "latin": ("en", "pt", "es", "fr", "de", "it"),
    "cyrillic": ("ru", "uk", "bg", "sr"), "greek": ("el",), "arabic": ("ar", "fa", "ur"),
    "hebrew": ("he",), "kana": ("ja",), "han": ("zh", "yue"), "hangul": ("ko",),
    "devanagari": ("hi", "mr", "ne"), "thai": ("th",), "bengali": ("bn",), "tamil": ("ta",),
    "georgian": ("ka",), "armenian": ("hy",),
}


def stand_in_models(script: str) -> tuple[str, ...]:
    """Os modelos de idioma que leem uma amostra da escrita, do preferido ao
    último (`_STAND_IN_LANGUAGES`)."""
    return tuple(dict.fromkeys(TESSERACT_CODES[code] for code in _STAND_IN_LANGUAGES.get(script, ())))


# Nome que o OSD do Tesseract dá à escrita ("Script: Han") → a nossa.
_OSD_ALIASES = {
    "japanese": "kana", "katakana": "kana", "hiragana": "kana", "korean": "hangul", "han": "han",
    "fraktur": "latin", "canadian_aboriginal": "canadian_aboriginal",
}


def script_from_osd(name: str | None) -> str | None:
    if not name:
        return None
    key = name.strip().lower()
    key = _OSD_ALIASES.get(key, key)
    return key if key in SCRIPT_MODELS else None


def script_model(script: str | None) -> str | None:
    """O modelo de escrita (`script/Latin`), ou `None` para escrita sem modelo."""
    name = SCRIPT_MODELS.get(script or "")
    return f"script/{name}" if name else None


# Caracteres frequentes que só existem numa das duas formas do chinês.
_SIMPLIFIED_ONLY = frozenset("这们国说时会为来个对学发经进过后实现关开门问长东书车见产业电动无应当头体机点样从么还没种话认让给号")
_TRADITIONAL_ONLY = frozenset("這們國說時會為來個對學發經進過後實現關開門問長東書車見產業電動無應當頭體機點樣從麼還沒種話認讓給號")


def chinese_models(text: str) -> list[str]:
    """`chi_sim`, `chi_tra`, ou os dois quando o texto não decide."""
    simplified = sum(1 for char in text if char in _SIMPLIFIED_ONLY)
    traditional = sum(1 for char in text if char in _TRADITIONAL_ONLY)
    if simplified >= 3 and simplified >= 2 * traditional:
        return ["chi_sim"]
    if traditional >= 3 and traditional >= 2 * simplified:
        return ["chi_tra"]
    return ["chi_sim", "chi_tra"]


def tesseract_languages(codes: list[str], text: str = "", limit: int = MAX_LANGUAGES) -> list[str]:
    """Os modelos do Tesseract para os idiomas `codes` (ISO), sem repetir, até
    `limit`. Um idioma sem modelo vira o modelo da escrita dele (ou a do
    texto); chinês vira `chi_sim`, `chi_tra` ou os dois (`chinese_models`)."""
    models: list[str] = []
    for code in codes:
        if code == "zh":
            found = chinese_models(text)
        elif code in TESSERACT_CODES:
            found = [TESSERACT_CODES[code]]
        else:
            fallback = script_model(_LANGUAGE_SCRIPT.get(code) or dominant_script(text) or "latin")
            found = [fallback] if fallback else []
        for model in found:
            if model not in models:
                models.append(model)
    return models[:limit]


def model_script(model: str) -> str:
    """A escrita que um modelo do Tesseract lê ("rus" → cirílica,
    "script/HanS" → han). O que não se sabe conta como latina."""
    if model.startswith("script/"):
        name = model.split("/", 1)[1]
        for script, value in SCRIPT_MODELS.items():
            if value == name or name.startswith(value):
                return script
        return "han" if name.startswith("Han") else "latin"
    if model.startswith("chi_"):
        return "han"
    code = iso_from_tesseract(model)
    return _LANGUAGE_SCRIPT.get(code or "", "latin")


def iso_from_tesseract(model: str) -> str | None:
    """O inverso da tabela, para o idioma de um projeto antigo (`por` → `pt`)."""
    for code, value in TESSERACT_CODES.items():
        if value == model and code not in ("ary", "arz", "hbo", "jw", "nn", "tl", "wuu", "yue"):
            return code
    return None


# --- nomes, para o classificador -------------------------------------------------

# O prompt do motor local é em português de propósito (`engine_local._PAGE_PROMPT`);
# o nome do idioma também. Fora desta lista vai o código ISO, que o modelo
# entende do mesmo jeito.
_NAMES_PT = {
    "pt": "português", "en": "inglês", "es": "espanhol", "fr": "francês", "de": "alemão",
    "it": "italiano", "nl": "neerlandês", "ru": "russo", "uk": "ucraniano", "pl": "polonês",
    "cs": "tcheco", "sk": "eslovaco", "hu": "húngaro", "ro": "romeno", "bg": "búlgaro",
    "el": "grego", "tr": "turco", "ar": "árabe", "he": "hebraico", "fa": "persa", "ur": "urdu",
    "hi": "híndi", "bn": "bengali", "ja": "japonês", "zh": "chinês", "ko": "coreano", "th": "tailandês",
    "vi": "vietnamita", "id": "indonésio", "ms": "malaio", "sv": "sueco", "da": "dinamarquês",
    "no": "norueguês", "nn": "norueguês", "fi": "finlandês", "et": "estoniano", "lv": "letão",
    "lt": "lituano", "sr": "sérvio", "hr": "croata", "bs": "bósnio", "sl": "esloveno", "ca": "catalão",
    "gl": "galego", "eu": "basco", "la": "latim", "eo": "esperanto", "ga": "irlandês", "cy": "galês",
    "is": "islandês", "sq": "albanês", "mk": "macedônio", "be": "bielorrusso", "ka": "georgiano",
    "hy": "armênio", "az": "azerbaijano", "kk": "cazaque", "uz": "uzbeque", "sw": "suaíli",
    "af": "africâner", "ta": "tâmil", "te": "telugo", "mr": "marati", "ne": "nepalês", "km": "khmer",
    "my": "birmanês", "lo": "laosiano", "tl": "filipino", "am": "amárico",
}


def language_name(code: str) -> str:
    """"alemão (de)" — o nome em português e o código."""
    name = _NAMES_PT.get(code)
    return f"{name} ({code})" if name else code
