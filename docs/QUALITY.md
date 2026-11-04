**Read this in your language:** **[Português (Brasil)](QUALITY.pt-BR.md)** · **[Español](QUALITY.es.md)** · English (you are here)

# Index quality: accuracy measured against an answer key

This document publishes the accuracy of the index GClaude Indexer produces,
measured against a hand-checked answer key, and says what each number means
and does not mean. The program's "Quality" screen summarises the
**confidence** the engine declares; the number here is a different one:
**whether the piece is right**.

Updated by hand on every version that touches the classifier. Last
measurement: **2 November 2026, version 1.7.5** (classifier, prompt and
rules are the same as in 1.7.4; phase 37 only added the measurement).

## What was measured

- **Collection:** `demo/acervo`, entirely fictional: 72 pages, 41 pieces, 7
  files (two bound PDF volumes of an administrative process, a contract, a
  Word memo, a spreadsheet, a scanned letter as PNG and an e-mail). Thirteen
  types from the rules engine's vocabulary and seven pieces with no type.
- **Answer key:** `demo/gabarito.csv`: piece, type, date and author of every
  page.
- **Machine:** desktop with a Radeon RX 6700 XT (12 GB), Ollama 0.40.13 over
  Vulkan with flash attention off, Windows 11.
- **Command:** `tools/indexar_pasta.py` followed by `tools/medir_acerto.py`
  (the arithmetic is in `gclaude_indexer/answer_key.py`).

## Result

| Engine | Pages covered | Pieces (key / index) | Precision | Recall | F1 | Type | Date | Author | Time |
|---|---|---|---|---|---|---|---|---|---|
| Rules | 72/72 (100%) | 41 / 42 | 85.7% | 87.8% | 86.7% | 94.4% | 50.0% | 19.4% | 4 s |
| Local, `qwen3.5:9b` | 72/72 (100%) | 41 / 65 | 53.8% | 85.4% | 66.0% | 60.0% | 88.6% | 84.4% | 4 min 12 s |

**What each column means.** *Pages covered*: pages of the key that sit in
some piece of the index; no page was lost by either engine. *Piece found*:
the index has a piece in the same file sharing at least half of the pages
(Jaccard ≥ 0.5); a three-page piece returned as two plus one is a boundary
error, not an absence. *Precision*: found ÷ pieces in the index (drops when
the engine slices). *Recall*: found ÷ pieces in the key (drops when the
engine merges). *Type*, *date* and *author* are measured only among the
pieces found, so a boundary error is not charged twice; date and author only
where the key has them. Type is compared upper-cased, unaccented and exact;
author matches by surname or acronym.

## How to read it

- **The rules engine gets boundaries and types right** because the
  collection, like a real process, has most pieces with the type in the
  heading, and the rules vocabulary covers those headings. It gets **date**
  wrong (18 of 36 pieces found: it takes the first date in the text, often a
  date cited in the body rather than the piece's own) and barely finds the
  **author** (7 of 36: it only recognises a signature after markers such as
  "Atenciosamente"). Six "extra pieces" are pages where a vocabulary word
  opens a line in the middle of another piece ("PORTARIA nº 55/2026" inside
  the call for bids).
- **The local model gets date and author right** (31 of 35 and 27 of 32)
  and loses on boundaries: it mostly returns **one piece per page** (30
  extra pieces, hence 54% precision), and six long pieces (terms of
  reference, call for bids, minutes, appeal, two contracts) never reach half
  their pages in a single piece. The 60.0% **type** has three readings: 7 of
  the 14 mismatches are a more specific name of the right type ("PARECER
  JURÍDICO" for PARECER, "NFS-E" for NOTA FISCAL, "TERMO ADITIVO" for
  TERMO), which the exact comparison rejects; 4 are pieces the key leaves
  untyped and the model named ("PLANILHA", "EMAIL", "ATA DE REUNIÃO"); 3 are
  pieces with a clear type (TERMO) that the model returned without one.
- **Neither engine is "better"** in this table: each is right where the
  other is wrong. That is what the measurement is for, and where the next
  phases can start (dates in the rules engine and fragmentation in the
  model are the two largest gains in sight).

## What this does not say

- **Synthetic collection.** It was written with clean headings, legible
  digital text and a single good-quality scan. Real-world collections have stamps,
  skewed pages, poor OCR and types outside the vocabulary; accuracy there is
  lower, by an unknown amount.
- **One machine, one model, one run.** Another model, window size or GPU
  gives different numbers; the local model is not deterministic across runs.
  Measured: a second run on 2 November, after a one-word change in the
  texts, moved type from 45.7% to 60.0%, date from 91.4% to 88.6% and author
  from 78.1% to 84.4%, with the same boundaries (F1 66.0%). The table shows
  the run on the collection as versioned.
- **The type comparison is strict on purpose.** Accepting "PARECER
  JURÍDICO" as PARECER would lift the model's number to 80%, but hide
  that the index ships two names for one type.
- **The classifier was not tuned to the collection.** Phase 37's rule was to
  measure first, untouched; improving is another phase, and the measurement
  stays to say whether it improved.

## How to repeat

```
python tools/indexar_pasta.py demo/acervo <folder> --motor rules
python tools/medir_acerto.py <folder> demo/gabarito.csv --saida-md acerto.md

python tools/indexar_pasta.py demo/acervo <folder2> --motor local --modelo qwen3.5:9b
python tools/medir_acerto.py <folder2> demo/gabarito.csv --saida-md acerto2.md
```

CI performs the first run on every push and attaches `acerto.md` to the
workflow run; it enforces coverage (100%) only, not accuracy.
