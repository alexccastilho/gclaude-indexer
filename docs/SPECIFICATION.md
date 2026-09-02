# Specification: GClaude Indexer

A local tool that turns a folder of documents into three artifacts that
feed a Claude Project: an index, a timeline, and instructions.

This file is the implementation's source of truth. This is an internal
technical reference, kept in English only — the user-facing documentation
(README, CONTRIBUTING) ships in English, Brazilian Portuguese and Spanish;
see [README.md](../README.md).

---

## 1. Objective

The user points at a folder — commonly, but not necessarily, one synced by
Google Drive — containing documents of any type and quantity. The system
scans it, converts what needs converting, applies OCR where necessary,
slices oversized PDFs, indexes the content, and produces:

- `index.md` — a catalog of items with origin, type, date, author and
  summary
- `timeline.md` — the dated items in chronological order
- `project_instructions.md` — instructions ready to paste into a Claude
  Project
- `review.md` — a coverage and failure report
- Sliced PDFs, in readable chunks, written back into the output folder

The original documents are never altered. The extracted text exists to
locate content; reading the material of record still happens in the
original file.

## 2. Constraints

- Application name: **GClaude Indexer**.
- Runs on Windows, offline, except for the classification step when the
  optional `claude_code` engine is chosen (see section 5.6).
- The source code can live in a folder synced by a cloud drive and be used
  from more than one machine, one at a time. See section 11.
- The `claude_code` engine drives classification through a Claude Code
  session already installed on the machine, under the user's own
  subscription. **Never** call the Anthropic API over HTTP and never use
  `ANTHROPIC_API_KEY` — this application has no code path that does either,
  in any engine.
- Browser interface, served on `127.0.0.1`, no authentication (single-user,
  local machine only — see section 7).
- No writes outside the folders the user configured.
- Every step is resumable: interrupting and reopening continues where it
  left off.

## 3. Technical stack

| Layer | Choice | Reason |
|---|---|---|
| Language | Python 3.12 | mature document libraries; newer interpreters (3.13/3.14) are known to break this project's pinned dependency versions |
| Interface | FastAPI + Jinja2 + HTMX | forms and progress updates with no separate front-end build |
| Database | SQLite via the standard library's `sqlite3` | one file per project, zero installation |
| PDF | PyMuPDF | reading, page counting, slicing, image detection |
| OCR | ocrmypdf + Tesseract | text layer without altering the original image |
| DOCX | python-docx | text and tables |
| XLSX | openpyxl | cells as tabulated text |
| PPTX | python-pptx | slide and notes text |
| Images | Pillow + pytesseract | direct OCR |
| Email | standard library `email` module | `.eml`, and `.msg` via `extract-msg` |

Versions are pinned in `requirements.txt`. No dependency that requires a
compiler.

## 4. Data model

One `project.db` file per project, in the output folder. Opened with
`PRAGMA journal_mode=DELETE` and `PRAGMA synchronous=FULL` — never WAL (see
section 11.3).

```sql
CREATE TABLE project (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    subject       TEXT,
    source_folder TEXT NOT NULL,
    output_folder TEXT NOT NULL,
    config_json   TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE file (
    id            INTEGER PRIMARY KEY,
    relative_path TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL,
    extension     TEXT NOT NULL,
    size          INTEGER NOT NULL,
    sha256_hash   TEXT NOT NULL,
    group_key     TEXT,             -- volume, subfolder or subject, per config.group_mode
    page_count    INTEGER,
    needs_ocr     INTEGER NOT NULL DEFAULT 0,
    status        TEXT NOT NULL,    -- discovered|converted|extracted|failed|duplicate|skipped
    error         TEXT
);

CREATE TABLE page (
    id            INTEGER PRIMARY KEY,
    file_id       INTEGER NOT NULL REFERENCES file(id),
    number        INTEGER NOT NULL, -- position within the file
    reference     TEXT NOT NULL,    -- citable label, e.g. "f. 178" or "p. 12"
    char_count    INTEGER NOT NULL,
    image_count   INTEGER NOT NULL,
    has_table     INTEGER NOT NULL,
    text          TEXT NOT NULL,
    UNIQUE (file_id, number)
);

CREATE TABLE window (
    id            INTEGER PRIMARY KEY,
    key           TEXT NOT NULL UNIQUE,
    group_key     TEXT NOT NULL,
    start_ref     TEXT NOT NULL,
    end_ref       TEXT NOT NULL,
    status        TEXT NOT NULL     -- pending|done
);

CREATE TABLE item (
    id            INTEGER PRIMARY KEY,
    group_key     TEXT NOT NULL,
    start_ref     TEXT NOT NULL,
    end_ref       TEXT NOT NULL,
    start_order   INTEGER NOT NULL, -- for ordering and gap detection
    end_order     INTEGER NOT NULL,
    type          TEXT,
    date          TEXT,             -- ISO or NULL
    author        TEXT,
    summary       TEXT,
    has_table     INTEGER NOT NULL DEFAULT 0,
    has_image     INTEGER NOT NULL DEFAULT 0,
    engine        TEXT NOT NULL,    -- rules|local|claude_code
    confidence    TEXT NOT NULL,    -- high|medium|low
    files         TEXT NOT NULL     -- names of the PDFs that contain the range
);

CREATE TABLE event (
    id            INTEGER PRIMARY KEY,
    step          TEXT NOT NULL,
    level         TEXT NOT NULL,    -- info|warning|error
    message       TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

-- Duration and outcome of each step run, to compare engines/models by time
-- as well as by quality (section 6, "Result" screen). `parallelism` is
-- recorded because two times measured under different parallelism modes
-- (e.g. "economy" vs. "maximum") are not comparable even on the same
-- collection and machine.
CREATE TABLE run (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    step          TEXT NOT NULL,
    engine        TEXT,
    model         TEXT,
    parallelism   TEXT,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    items         INTEGER NOT NULL DEFAULT 0,
    ok            INTEGER NOT NULL DEFAULT 0
);
```

Indexes on `file(status)`, `page(file_id)`, `item(group_key, start_order)`.

The output folder **is** the project's identity: this database holds
everything needed to reopen it, so a machine that has never seen the project
recovers it by being pointed at the folder ("Open existing project"), with no
identifier to create and nothing to recreate. Exactly one row of `project` is
in force — the first, `ORDER BY id`; more than one row means the database
went through the defect where "New project" was pointed at an occupied
folder, and the later rows are kept but unused.

A separate `projects.json` (not in this database) is the catalog of "which
output folders have been opened" — see section 11.1. It is per-machine by
default, and can be moved into a folder on the Drive chosen by the user, at
which point every computer signed into that Drive shares one list. Entries
in a shared catalog also carry the output folder **relative to the catalog
folder**, and that relative path wins on read: the drive letter differs
between machines (section 11.5), so the absolute path written by one
computer is meaningless on the next.

## 5. Processing steps

Each step is an independent function that reads from and writes to the
database, can be run on its own, and is safe to repeat.

**1. Scan.** Walks the source folder recursively. Hashes every file (SHA-256).
A file whose hash is already recorded is skipped as a duplicate (recorded
with `status = 'duplicate'`, not silently dropped, so scan-progress counts
stay consistent). Derives `group_key` per the project's `group_mode`:
subfolder name, a regular expression over the file name, or everything in
one group.

**2. Conversion and OCR.** By type:
- PDF with a text layer already: nothing to do.
- PDF with no text layer, or averaging under 100 characters per page:
  `ocrmypdf --skip-text --language <ocr_language> --deskew`, writing a copy
  into the output folder. The original stays untouched. Note: the
  specification originally also called for `--clean`, but that flag depends
  on the `unpaper` binary, which has no official Windows distribution — the
  code omits it on this platform (see the comment in `conversion.py`).
- Image: direct OCR, text stored as a single page.
- DOCX, XLSX, PPTX, TXT, MD, CSV, HTML, XML, JSON, EML/MSG: text extraction,
  no OCR.
- Under the special `all` extension category, any extension with no
  dedicated extractor falls back to reading the file as plain text
  (`errors="replace"`), never failing the step.
- Extensions on the fixed executable/binary blocklist are always excluded,
  even under `all`.

> **Parallelism (conversion/OCR and extraction):** the project's
> "Parallelism" field (`economy`/`automatic`/`maximum`, `parallelism.py`)
> controls how many workers `ProcessPoolExecutor` uses in these two steps —
> always physical cores, never logical ones, because OCR and PDF rendering
> saturate the execution unit and counting hyperthreads produces contention
> instead of gain. `economy` = 1, `maximum` = all physical cores,
> `automatic` (default) = physical cores minus one, so the interface stays
> responsive during processing. Measured gain on the development machine (8
> physical cores): 61.5s → 12.0s (5.14×) on 12 three-page PDFs with forced
> OCR. The GPU does not accelerate either of these two steps — the
> Tesseract binary `ocrmypdf` calls is CPU-only.

**3. Slicing.** A PDF with more pages than the configured limit (default 80)
is cut into chunks, written into the output folder, with the original page
numbering preserved.

**4. Page extraction.** For every page: text truncated at the configured
character limit, character count, embedded-image count, a best-effort table
detection. Written to `page`.

**5. Window preparation.** Groups pages into overlapping windows. Writes one
`.txt` file per window into `<output>/windows/`, with a header identifying
the group and the page range, and each page labeled with its own
`reference`.

**6. Classification.** An isolated step behind a single interface, with
three interchangeable engines selectable in the form (plus an `automatic`
mode that resolves to one of the first two, described below). All of them
receive a window's text and return the same item structure, so the
following steps never need to know which engine ran.

| Engine | Cost | Billed to | Leaves the machine | Expected quality |
|---|---|---|---|---|
| `rules` | zero | nobody | no | good on a well-structured collection; lower on irregular ones |
| `local` | zero | nobody | no | close to `claude_code` |
| `claude_code` | the user's own subscription | Claude | yes | best |

**`rules` engine, the zero-dependency default.** Purely deterministic:
- Date by regular expression, covering `15/05/2024`, `15.05.2024` and
  `15 de maio de 2024` (and their English/Spanish equivalents), with
  calendar validation.
- Type by a dictionary of markers at the start of the page (document-type
  words such as memorandum, opinion, order, minutes, certificate, term,
  notice, invoice, appeal, decision, ordinance, resolution). The dictionary
  lives in an editable file (`config/classification_rules.json`), not in
  code.
- Item start detected by a type marker, a preceding blank page, a protocol
  stamp, or a change in a repeated header.
- Item end on the page before the next detected start.
- Author by footer and signature-block patterns.
- Summary by extraction: a line starting with "Subject:"/"Re:" or, failing
  that, the first sentence longer than 40 characters.
- A page with no marker at all joins the previous item and is marked
  `confidence = "low"`.

**`local` engine.** An open model served by Ollama on
`http://127.0.0.1:11434`. No account, no key, no external network traffic
after the model is downloaded once. The default model is
`gemma4:e4b` (`engine_local.py:DEFAULT_LOCAL_MODEL`), used regardless of
hardware unless the project's "Local model" field names a different,
already-installed Ollama model — that field is fed by `GET /api/tags`
against the local Ollama instance, with a free-text fallback when Ollama
does not respond. A connection failure falls back to the `rules` engine,
with a warning event. Hardware too small to hold the chosen model
(combined VRAM + RAM, with a 20% margin) is checked before running it —
see section 10.2.

**`claude_code` engine.** What already exists on disk (`CLAUDE.md` and the
window files) is enough for an external Claude Code session, launched by
the user in that folder, to do the classification: the user types a
trigger phrase (in the interface's current language — English "process the
windows", Portuguese "processe as janelas", or Spanish "procese las
ventanas"; `CLAUDE.md` documents all three as valid regardless of which one
generated it), Claude Code writes `raw_items.jsonl`, and this application
re-reads that file to track progress and imports the result once done.
Nothing in this codebase compares the trigger phrase as a string — that
matching happens inside the external Claude Code session, reading
`CLAUDE.md`'s own natural-language instructions.

**Review mode.** A form option: run the `rules` engine over everything, and
submit only the low-confidence items to a second engine of the user's
choice. Cuts the expensive engine's usage by roughly 90% while keeping
most of the quality gain.

**Automatic engine selection.** When `classification_engine == "automatic"`,
`orchestrator.py:resolve_effective_engine` picks `local` if the hardware
diagnostic says the chosen model fits, otherwise `rules`. It never resolves
to `claude_code` — that engine is only ever used when explicitly selected.

Every item records which engine classified it, for auditing, and every
step run is recorded in the `run` table (engine, model, parallelism mode,
item count, timing) to support the quality/benchmark comparison on the
Result screen (section 6).

**7. Import and consolidation.** Reads `raw_items.jsonl` (the wire format
every engine writes to, including `claude_code`'s external session), validates
each line, discards duplicates from window overlap, stitches an item split
across windows back together, and writes to `item`. An invalid line becomes
an error event, without stopping the process.

**8. Artifact generation.** Produces `index.md`, `timeline.md`, `review.md`
and `project_instructions.md`, in the interface's current language. The
instructions file is assembled from a template filled with the fields the
user entered in the New Project form.

## 6. Interface

Four screens plus an "About" page, served on `http://127.0.0.1:8000`.

| Screen | Route |
|---|---|
| Projects | `GET /projects` |
| New project | `GET /projects/new`, `POST /projects/new` |
| Execution | `GET /projects/{project_id}/run` |
| Result | `GET /projects/{project_id}/result` |
| About | `GET /about` |

**Projects.** Lists existing projects with creation date and status. Button
to create a new one.

**New project.** A form with the fields below. Fields have a sensible
default already filled in; the user only touches what needs changing. Field
names match `ProjectConfig`'s own attribute names (`config.py`) — they are
also the HTTP form field names, so the two never drift apart.

| Field | Type | Default | What it's for |
|---|---|---|---|
| `name` | text | — | identifies the project in the list |
| `subject` | long text | — | **shown to the classifying model** as context, and goes into the generated instructions |
| `source_folder` | folder picker | — | where the documents are |
| `output_folder` | folder picker | `<source>\_indexed` | where everything is written |
| `collection_type` | choice | `processo` (case file) | `processo` numbers by sheet; `biblioteca` (library) numbers by page |
| `group_mode` | choice | `subfolder` | subfolder, name pattern, or everything together |
| `group_pattern` | regex | empty | used when grouping is by name pattern |
| `extensions` | multiple, grouped by family (Documents, Images, Text and data, Messages) | `pdf`, `docx`, `imagens` | what enters the scan — the family grouping is presentation only, see `categories_by_family()` in `file_types.py` |
| `pages_per_block` | number | 80 | slicing limit for the auxiliary `blocks/` files; **does not affect the index** — extraction reads the whole PDF, not the slices |
| `pages_per_window` | number | 16 | pages per request to the model, and the setting that decides classification quality: the reply carries one line per page, and a window too wide truncates it (8 is the measured recommendation) |
| `overlap` | number | 2 | pages repeated between windows |
| `chars_per_page` | number | 2000 | how much text goes into classification |
| `ocr_language` | choice | `por` | Tesseract language code |
| `classification_engine` | choice, with a name and description per engine | `automatic` | see section 5.6 |
| `local_model` | selector fed by `GET /api/tags` against local Ollama, with a free-text fallback when Ollama doesn't respond | `automatic` (resolves to `gemma4:e4b`) | the choice is saved and does take effect (`engine_local.py:model_to_use`) |
| `processing_mode` | choice | `automatic` | `automatic`/`gpu` use `num_gpu=-1` in Ollama (as much GPU as fits, rest in RAM); `cpu` forces `num_gpu=0` — only affects the `local` engine |
| `parallelism` | choice | `automatic` | `economy` (1 worker), `automatic` (physical cores minus one), `maximum` (all physical cores) — see section 5.2 |
| `review_low_confidence` | checkbox | off | reprocess only low-confidence items with another engine |
| `role_instructions` | long text | a default template | **shown to the classifying model** as context; who Claude is, in the generated instructions |
| `extra_rules` | long text | empty | **shown to the classifying model** as context; appended to the generated instructions |

**Execution.** One row per step (scan, conversion, extraction, windows,
classification — `step_state.STEPS`), with status and count. A button runs
the next step, and a separate "Import and generate reports" action runs
import + artifact generation once classification is done; both trigger a
background task and return immediately. Below: a progress bar with
percentage and an ETA for the running step, and a pause/interrupt button
(cooperative — every step is resumable by design, so "pause" is just "run
again later"). A live CPU/RAM/GPU usage graph (plain `<canvas>`, no
library). A live log panel reading the `event` table, up to 200 of the most
recent lines, with a level filter (all/info/warning/error, in pure CSS) and
a "follow the tail" checkbox that keeps the scroll pinned to the latest
line. When the engine is `claude_code`, shows the copyable command and a
button to recheck whether the windows are done.

**Result.** A preview of the four generated files, a button to open the
output folder in Explorer, a report of what's still pending, and a button
to delete the intermediate files (`converted/` and `blocks/`), preserving
the database, the four reports, `raw_items.jsonl` and `logs/` — permanent
for the project, since the conversion step only processes files with
`status = 'discovered'` (`cleanup.py`). Also shows a quality summary for the
current run and, when more than one classification run has been recorded,
a side-by-side comparison by engine/model (`quality.py`), with three
limitations shown on screen, not hidden: (1) time is only comparable within
the same collection and the same machine; (2) the score measures the
engine's own declared confidence and how many fields it filled in, **not
actual correctness**, which would require a hand-checked answer key; (3)
the quality score can only be attributed to the (engine, model) group of
the **last** import, because `import_and_consolidate` recreates the whole
`item` table on every import — any other group from the history gets a
`None` score, never a number computed over items that no longer belong to
that engine/model.

A language selector and a theme selector (four color themes: light, dark,
sepia, high-contrast) sit in the header of every screen, in a `<select>`
each, persisted in a cookie. A separate layout selector (four layouts:
standard, technical, editorial, compact — `web/layout.py` +
`static/layouts.css`) is orthogonal to the theme: 4 layouts × 4 palettes,
same Jinja2 templates for all of them, varying only via `data-layout` and
CSS rules. All fonts used across every layout (Segoe UI, Cascadia Mono,
Constantia, Corbel and equivalents) ship with Windows itself — never Google
Fonts nor any font loaded from outside the machine, keeping the interface
consistent with the project's offline design.

Step status (`step_state.py`) is always a stable ASCII key
(`"done"`, `"scan"`, ...), never screen text — the template translates the
key into the current language. Do not let a status value double as display
text, CSS class and comparison value at the same time; see
[CONTRIBUTING.md](../CONTRIBUTING.md) for why that specific coupling has
caused real defects in this project before.

## 7. Security

- The server listens only on `127.0.0.1`. Never `0.0.0.0`.
- Every path input is resolved with `Path.resolve()` and validated against
  the project's folders (`paths.py:resolve_within`). Any path outside them
  is refused, including via `..`.
- `subprocess` always runs with an argument list and `shell=False`
  (`subprocess_utils.run_hidden`).
- No SQL query built by string concatenation. Bound parameters only.
- No `eval`, `exec` or `pickle` over data coming from a file.
- The JSON the classification engines return is validated field by field
  before being written: type, range within the group, plausible ISO date
  format.
- Logs never contain document content, only file names and counts.

## 8. Acceptance criteria

1. Running twice in a row on the same folder reprocesses nothing and
   creates no duplicates.
2. Adding a new file to the folder and running again processes only that
   file.
3. Interrupting mid-step and reopening resumes with no loss.
4. `review.md` reports zero gaps when classification is complete.
5. A corrupted file is recorded as an error, marked `failed`, and does not
   bring down the run.
6. No file is written outside the output folder.
7. A 3,000-page collection completes the local steps in under two hours.

## 9. Implementation phases

Each phase ends running, with tests, before the next one starts. (This
list reflects the original build order; see [CHANGELOG.md](../CHANGELOG.md)
for what was added, changed or fixed phase by phase, including work after
phase 11.)

1. Structure, database, configuration and logging.
2. Scan and inventory.
3. Conversion, OCR and slicing.
4. Page extraction and windows.
5. `rules` engine and the common classification interface.
6. Import, consolidation and artifact generation.
7. Hardware diagnostics and silent dependency installation.
8. `local` and `claude_code` engines, and review mode.
9. Web interface.
10. Cross-machine portability and database locking.
11. Packaging and desktop shortcut.
12. GPU/sensor telemetry for any vendor, parallelism, quality/benchmark
    reporting, and four interface layouts.
13. Internationalization (English source code and database schema; a
    three-language interface, output artifacts and log messages;
    documentation in three languages) and open-source preparation.

## 10. Automatic dependency installation

No manual installation by the user. The installer resolves everything and
reports progress in the interface (or its own console output), never in a
silent background window.

### 10.1 Machine diagnostics

Before installing anything, gather and record as an event:

- GPU and VRAM: `nvidia-smi --query-gpu=name,memory.total --format=csv,noheader`
  when present. Without it, AMD and Intel GPUs are detected through
  `Win32_VideoController` over WMI, and — for VRAM specifically — through
  the registry (`HardwareInformation.qwMemorySize`, 64-bit), because
  `Win32_VideoController.AdapterRAM` is 32-bit and saturates at 4095 MB on
  cards with more than that. On any GPU, live utilization and VRAM usage
  come from Windows's own Performance Counters
  (`\GPU Engine(*)\Utilization Percentage`,
  `\GPU Adapter Memory(*)\Dedicated Usage`) when `nvidia-smi` is
  unavailable — `nvidia-smi` stays preferred when present, for more precise
  total-VRAM reporting.
- System memory and free disk space at the destination.
- Presence of Tesseract, Ghostscript and Ollama.

### 10.2 Local model choice

The `local` engine's model is fixed to `gemma4:e4b`
(`engine_local.py:DEFAULT_LOCAL_MODEL`) by default, on any hardware, unless
the project's "Local model" field names a different, already-installed
model (see section 6) — in which case that model is what actually runs,
and what the hardware check below evaluates. Ollama is always asked to use
`num_gpu: -1` (as much GPU as fits, the rest spilling into RAM
automatically), regardless of which model runs.

`hardware.py:choose_model` decides whether the machine can run the model
that will actually be used:

- The model's size comes from Ollama's own `/api/tags` when the model is
  already downloaded; otherwise the check falls back to a calibrated
  estimate for the default model (`gemma4:e4b`, roughly 9.6 GB).
- Required combined memory (VRAM + RAM) is the model size plus a 20%
  margin.
- Below that, classification falls back to the `rules` engine, with the
  reason recorded as an event — never a silent failure.
- Required free disk space is at least twice the model's size before
  downloading it; below that, the download is skipped and the `rules`
  engine is used instead.

An earlier design (superseded, kept here only as history) picked among
several `qwen2.5` model sizes by VRAM tier. That table no longer reflects
the running code; do not use it as a reference.

### 10.3 Silent installation

Order of attempts for each dependency, stopping at the first that works:

1. `winget install --id <package> -e --silent --accept-package-agreements --accept-source-agreements`
2. The vendor's official installer, downloaded to a temporary folder and
   run with its packager's silent flag (e.g. `/VERYSILENT /NORESTART` for
   Inno Setup, `/S` for NSIS).
3. Both failing: record an error, continue with the `rules` engine, and
   show the manual command in the interface as a last resort.

Packages: `Ollama.Ollama`, `UB-Mannheim.TesseractOCR`. There is no
Ghostscript package any more: `ArtifexSoftware.GhostScript` was removed
from the winget repository, so that route cannot be relied on.

Ghostscript also cannot be installed unattended by its own installer. It
is manifested `requireAdministrator`, so every destination raises a UAC
prompt, and since 10.01.0 the vendor stopped honouring the NSIS `/S`
flag — the installer leaves a "Finish" page waiting for a click. What
`install.ps1` does instead is **unpack** the installer's payload into
`%LOCALAPPDATA%\GClaudeIndexer\gs` and add its `bin` to the user PATH:
no administrator, no window, no click. Ghostscript resolves its own
resources relative to the executable, so it runs correctly from there.

Verify the downloaded file's hash when the vendor publishes one. Download
only from an official domain, over HTTPS, without following a redirect to
a different domain.

After installing, confirm it actually works before declaring success:
`tesseract --version`, `ollama --version`, and a real test call to the
model.

### 10.4 Model download

`ollama pull <model>`, with its output read in real time and turned into a
progress bar in the interface. An interrupted download resumes on the next
run — Ollama's own native behavior.

### 10.5 Performance

- Ollama detects CUDA and ROCm on its own; nothing here configures the GPU
  manually. The one documented exception is AMD RDNA1 cards (e.g. RX 5700
  XT), where the installer sets the user environment variable
  `HSA_OVERRIDE_GFX_VERSION=10.3.0` — the one adjustment that architecture's
  ROCm path needs. RDNA2 onward, and earlier AMD generations, need nothing.
  The installer never installs ROCm itself.
- `OLLAMA_KEEP_ALIVE=30m`, so the model doesn't leave memory between
  windows.
- With a GPU: `OLLAMA_NUM_PARALLEL=3` and three simultaneous windows.
  Without one: one at a time, to avoid locking up the machine.
- `num_ctx` is computed from the real window size, with a 20% margin.
- The first few windows' time is measured and shown as a completion
  estimate before the rest proceeds.

### 10.6 Uninstallation

A button removes the downloaded model and reports how much space that
frees. Ollama, Tesseract and Ghostscript themselves are never removed —
other programs on the machine may depend on them.

### 10.7 Installation diagnostics

`install_diagnostics.py:check_installation()` checks the presence and
version of Tesseract, Ghostscript, Ollama, the local model, and the
hardware-sensor DLLs, without ever raising — it feeds both the installer
script (decides what to offer) and the "About" screen (shows the user what
is missing and how to fix it, with no terminal required). `-AutoInstall`
runs every install unattended, without confirmation, including Ollama and
its default model — use with care, since those are large downloads.

## 11. Cross-machine portability

The source code can live in a cloud-synced folder (this project's own
development setup uses Google Drive) and be used from more than one
machine, one at a time.

### 11.1 What syncs and what stays local

| Goes to the synced folder | Stays local, per machine |
|---|---|
| source code, text templates, dictionaries | the Python virtual environment |
| `requirements.txt` and its installed-hash marker | `__pycache__` and temporary files |
| each project's configuration (inside `project.db`'s `config_json` column, in its output folder) | the project catalog, `projects.json` — per machine unless the user points it at a Drive folder (see section 4) |
| the shared project catalog, when configured (a Drive folder of the user's choosing) | `settings.json`, which names that folder — it is the pointer *into* the synced world and so cannot itself be synced |
| — | `tools.json`: the absolute path of each installed program, recorded by `install.ps1` so a fresh install does not depend on `PATH` having reached the running processes |
| generated artifacts: index, timeline, review, instructions | downloaded Ollama models |
| sliced PDFs | — |
| execution logs (`<output_folder>/logs/execution.log`, written alongside the `event` table) | — |

Default local path: `%LOCALAPPDATA%\GClaudeIndexer`. Never create a virtual
environment, cache, or temporary folder inside the synced folder.

### 11.2 Environment per machine

The launcher (`launcher.py`) checks, on every run:

1. Does `%LOCALAPPDATA%\GClaudeIndexer\venv` exist? If not, create it.
2. Has `requirements.txt`'s hash changed since the last install? If so,
   run `pip install -r requirements.txt` and record the new hash.
3. Are the external dependencies present on this machine? If not, trigger
   the silent installation from section 10.

So the first run on a new machine resolves itself with no manual step.

### 11.3 Database

- `project.db` lives in the project's output folder, which may be inside
  the synced folder.
- Always opened with `PRAGMA journal_mode=DELETE` and
  `PRAGMA synchronous=FULL`. **Never WAL** — its auxiliary files do not
  survive cloud-sync round trips.
- On opening a project, creates `project.lock` with the machine name, the
  user, and a timestamp, refreshed every minute while the app is open.
- Finding another machine's lock less than 10 minutes old refuses to open
  and explains which machine is using it (HTTP 423). An older lock is
  considered abandoned and can be taken over, with user confirmation
  (HTTP 409).
- The lock is removed when the server closes.

### 11.4 Switching machines

The interface shows a persistent notice with the rule: close the app, wait
for the sync tool to finish, and only then open it on the other machine.
The notice can be dismissed with a "×" button, remembered per browser in
`localStorage` (not a cookie, since it is a local display preference, not
something the server needs to know).

On startup, the project's file modification times are compared against the
last known record. Any sign of incomplete sync triggers a warning before
letting the user continue.

### 11.5 Paths

- No absolute path is ever written into code or into the database. Paths
  are always stored relative to the project, resolved at runtime.
- The drive letter can change between machines. The application root is
  located from the running file's own position, never a fixed letter.
- Any path containing spaces, including the application's own folder,
  needs quoting in generated commands.

## 12. Implementation status

The system is complete through phase 13 (see section 9) and phase 14
(internationalization and open-source preparation), with the full test
suite passing (317 tests as of this document). Phase-by-phase detail,
including every user-requested deviation from this specification and why,
lives in [CHANGELOG.md](../CHANGELOG.md) — this section intentionally does
not duplicate that history.

Known, deliberate departures from earlier drafts of this specification,
still true as of phase 14:

- **Local model choice.** Section 10.2's original VRAM-tiered `qwen2.5`
  table was replaced by a single fixed default (`gemma4:e4b`) with an
  optional user override that takes effect — see section 10.2 for the
  current rule.
- **Execution logs sync with the rest of the output folder**
  (`<output_folder>/logs/execution.log`), which section 11.1's original
  draft listed as machine-local; the table in this document already
  reflects the corrected behavior.
- **Intermediate file cleanup** (`converted/`/`blocks/`, deletable from the
  Result screen) was not in the original design; see section 6.
- **The GPU/sensor telemetry, parallelism, and quality/benchmark
  reporting** described in sections 5, 6 and 10.1 were added in phase 13,
  after the phases originally scoped in section 9.
