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
- **Machine:** desktop with a Radeon RX 6000 (12 GB), Ollama 0.40.13 over
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

## Profiles, structured output and grouping (2.1.0, 18 November 2026)

Version 2.1.0 offers two profiles for the local model, constrains the
model's answer with a JSON Schema (Ollama structured outputs), keeps in one
piece the pages of the same type that the model marks as continuing (same
file, not when the type names a section), and sends the model no project
block. Same machine (Ollama 0.40.16), measured on the
demo collection and on a **real case file** (83 pages, 15 PDFs, 16
documents, hand-made answer key). The real case file is private and is not
in the repository; its numbers cannot be repeated by others, which is why
the demo is still the published reference.

| Profile, GPU | Demo: F1 / pieces (41) / time | Real: F1 / pieces (16) / starts found / exact documents / merges / time |
|---|---|---|
| Fastest (`qwen3.5:4b`) | 87.5% / 39 / 2 min 23 s | 46.2% / 36 / 14 of 16 / 9 / 2 / 3 min 26 s |
| Best quality (`ornith-1.5:9b`) | 100% / 41 / 5 min 38 s | 73.7% / 22 / 15 of 16 / 11 / 1 / 7 min 38 s |

Before the grouping rule, with structured output already on: demo F1 57.6%
(Fastest) and 96.5% (Best quality); in the real case file, 71 and 57 pieces
for 16 documents, with 15 of 16 starts and one merge for both. The rule cost
Fastest one document start and one merge in the real case file, and cost
Best quality nothing. `qwen3.5:9b`, the previous default for cards with 8 GB
or more, found 12 of 16 document starts in the real case file and merged two
documents.

The project context in the prompt, measured with Best quality (F1, real /
demo): none 73.7% / 100%; collection type only 68.8% / 93.0%; collection
profile only 50.0% / 84.0%; both 60.6% / 94.1%. The two automatic lines
were removed. With the Subject filled in (one sentence describing
each collection): 50.0% / 96.5%,
15 → 11 of 16 starts and 1 → 3 merges in the real file, although the type
went from 73% to 91% there. The per-page prompt therefore sends no project
block; the Subject goes into the instructions written for Claude.

Without a graphics card (CPU and RAM only, 9-page sample of the demo, the
Contracts group): same pieces and same fields as on the GPU, in 136 s
against 40 s (Fastest) and 590 s against 66 s (Best quality). About 15 s of
each run are the steps before classification, so classification itself is
about 5 times (Fastest) and 11 times (Best quality) slower on the CPU. A
full run of Best quality on the CPU over the 83-page case file did not
finish one 16-page window in 30 minutes.

## Low confidence and window (2.0.0, 17 November 2026)

Version 2.0.0 removed the "review low confidence" step (a whole second
pass) and improves within the single pass instead: a page with no text and
no image becomes "PÁGINA EM BRANCO" (blank page) with high confidence
without going to the model; a page with an image and OCR under 100
characters is read again, once, with the model for its script; with no Theme
set, a profile of the collection goes into the context; a page with no
answer (plus its neighbours) and a page answered without a type (with its
whole text, from the index) get a second attempt, at most one per page and
15% extra requests per run; in the rules engine, keeping the continuation of a
piece opened by a marker at `medium` was measured but **not adopted**. The report
(`medir_acerto.py`) now also splits pieces and accuracy **by confidence
level**. Same machine, same collection, same commands (`--janela` and
`--sobreposicao` are new options of `indexar_pasta.py`).

| Run | Pieces (index) | F1 | Type | High / medium / low confidence (pieces; type right) |
|---|---|---|---|---|
| Rules, baseline (1.10.4) | 42 | 86.7% | 94.4% | 23 (100.0%; 17/17) / 2 (100.0%; 2/2) / 17 (88.2%; 15/17) |
| Rules, 2.0.0 (same as baseline: the change was not adopted) | 42 | 86.7% | 94.4% | 23 (100.0%; 17/17) / 2 (100.0%; 2/2) / 17 (88.2%; 15/17) |
| Rules, continuation at `medium` (measured, not adopted) | 42 | 86.7% | 94.4% | 23 (100.0%; 17/17) / 19 (89.5%; 17/19) / 0 |
| Local `qwen3.5:9b`, baseline (1.10.4, window 16, overlap 2) | 71 | 62.5% | 57.1% | 53 (60.0%; 18/30) / 18 (40.0%; 2/5) / 0 |
| Local `qwen3.5:9b`, 2.0.0, window 16, overlap 2 | 71 | 62.5% | 57.1% | 53 (60.0%; 18/30) / 18 (40.0%; 2/5) / 0 |
| Local `qwen3.5:9b`, 2.0.0, window 8, overlap 2 (new default) | 64 | 68.6% | 44.4% | 59 (44.4%; 16/36) / 5 (no piece found) / 0 |

Commands: `python tools/indexar_pasta.py demo/acervo <folder> --motor rules`
and `... --motor local --modelo qwen3.5:9b [--janela 8 --sobreposicao 2]`,
then `python tools/medir_acerto.py <folder> demo/gabarito.csv`. The baseline
was indexed with the code of commit `a9a17e8` (before any 2.0.0 change) and
measured with the new tool, which only reads `project.db`.

**Window × overlap matrix (local engine, 3 runs per cell).** The three runs
of each cell came out **identical** (temperature 0): the variation described
in the section below comes from changing the text, not from repeating the
run.

| Window / overlap | Windows | Pieces | F1 | Type | Date | Author | Time |
|---|---|---|---|---|---|---|---|
| 8 / 1 | 11 | 67 | 64.8% | 45.7% | 94.3% | 87.5% | 4 min 0 s |
| **8 / 2** | 13 | 64 | **68.6%** | 44.4% | 86.1% | 81.8% | 4 min 32 s |
| 12 / 1 | 7 | 64 | **68.6%** | 33.3% | 83.3% | 78.8% | 3 min 42 s |
| 12 / 2 | 8 | 71 | 62.5% | 34.3% | 85.7% | 78.1% | 4 min 12 s |
| 16 / 1 | 6 | 71 | 62.5% | 45.7% | 80.0% | 87.5% | 3 min 50 s |
| 16 / 2 | 6 | 71 | 62.5% | 57.1% | 91.4% | 84.4% | 4 min 2 s |

The rule was to stay at 8 pages unless window 12 ended within 1 percentage
point of the best F1 **and** got the type right with fewer requests. 12 ties
for the best F1 (12/1) but gets the type right less often (33.3% against
44.4%), so the local engine's window stays **8** (`auto_settings.
WINDOW_LOCAL`), with the overlap of 2 that 2.0.0 already used for PDF
collections. Window 16 (the 1.x one) has the worst F1. Type is the number
that moves most with the window (33% to 57%): it is the model's weak point
on this collection, not the window's.

**By confidence level.** In the rules engine we tested keeping the
continuation of a piece opened by a marker at `medium`, instead of dropping the
whole piece to `low`. Before the change the 2 `medium` pieces got the type
right 100% of the time and the 17 `low` 88.2%; with the change the 19 `medium`
sat at 89.5% and `low` became empty. **The change was not adopted**: with 2
`medium` pieces against 17 `low`, and a collection with no piece lacking an
opening marker, the sample is too small to say that `medium` is more accurate
than `low`, and the rule was to change only if the measurement supported it
(`engine_rules.CONTINUATION_KEEPS_MEDIUM` stays `False`). In the local engine confidence separates nothing: 75% to 92% of the
pieces come out `high`, and the type right among them (44% to 60%) is close
to that of `medium`.

**The second attempt did not show up in this collection.** With 6 to 13
windows, the 15% cap on extra requests only frees the first extra request
after the seventh regular one, and no run had a page with no answer (every
page had text, none was blank) nor a piece with no type whose whole text was
longer than the window's. That is why the 1.10.4 and 2.0.0 (16/2) rows came
out equal. What the measurement shows here is the effect of the window and of
the by-confidence report; the effect of the second attempt only appears in
larger collections, with long or scanned pages.

## What this does not say

- **Synthetic collection.** It was written with clean headings, legible
  digital text and a single good-quality scan. Real-world collections have stamps,
  skewed pages, poor OCR and types outside the vocabulary; accuracy there is
  lower, by an unknown amount.
- **One machine, one model, one run.** Another model, window size or GPU
  gives different numbers; the local model can vary with the Ollama or model version (on the same machine and
  with the same input, the 2.0.0 runs came out identical, at temperature 0).
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
