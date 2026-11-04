*Read this in other languages: [Português (Brasil)](docs/CONTRIBUTING.pt-BR.md) · [Español](docs/CONTRIBUTING.es.md)*

# Contributing to GClaude Indexer

Thank you for considering a contribution. This document covers how to set up a development environment, run the test suite, and the conventions the codebase relies on. The user-facing documentation is the [README](README.md); the technical reference is [docs/TECHNICAL.md](docs/TECHNICAL.md).

## Windows only

GClaude Indexer runs on **Windows only**. It is not a portability gap to be fixed incidentally: the codebase talks to Windows-specific surfaces on purpose. PowerShell (installer and launcher scripts), WMI (hardware and resource sensors), the Windows registry (locale and language detection) and Performance Counters (the live CPU and GPU graphs). Contributions that add cross-platform abstraction layers without a concrete need are out of scope; contributions that fix a genuine Windows bug, or extend Windows-specific functionality, are very welcome.

## You do not need Claude Code

The project name mentions Claude, but **Claude Code is optional**, both to use the software and to contribute to it. Classification of collection items is done by one of three interchangeable engines (plus an `automatic` mode that picks between the first two based on the machine's hardware):

- `rules`: deterministic, no external tool required.
- `local`: uses a local Ollama model.
- `claude_code`: delegates classification to Claude Code, for users who already have it installed.

The `rules` and `local` engines are enough to run the full pipeline end to end and to work on almost anything in this repository. You only need Claude Code if you are working on `gclaude_indexer/engine_claude_code.py` or `gclaude_indexer/claude_package.py`, and even then the test suite mocks the subprocess call. You do not need Claude Code installed to run the tests.

## Setting up the environment

1. Install Python 3.12. The environment must **not** live inside a folder synced by Google Drive, OneDrive or similar: file locking during sync breaks SQLite and virtualenvs. The convention used by this project is a venv in `%LOCALAPPDATA%\GClaudeIndexer\venv`.

   ```powershell
   py -3.12 -m venv "$env:LOCALAPPDATA\GClaudeIndexer\venv"
   ```

2. Install the dependencies:

   ```powershell
   & "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pip install -r requirements.txt
   ```

3. Alternatively, run the installer script, which does the above plus checks for Tesseract and Ghostscript, fetches the hardware-sensor libraries and offers to create a desktop shortcut:

   ```powershell
   powershell -ExecutionPolicy Bypass -File install.ps1
   ```

## Running the tests

Always use the venv interpreter, not whatever `python` resolves to on `PATH` (a newer, unpinned Python breaks the pinned dependency versions):

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -B -m pytest -q
```

The suite must pass in full before and after your change; it takes about five minutes and never talks to a real Ollama or to the network. If you are working on a single test file during development:

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -B -m pytest tests/test_something.py -v
```

The suite writes the OCR language data it needs into the real `%LOCALAPPDATA%\GClaudeIndexer\tessdata` folder of the machine; nothing else outside the temporary folders is touched.

Work is committed per task, one commit per self-contained change, on `main`. GitHub Actions runs the suite and indexes the demonstration collection (`demo/acervo`) on every push, attaching the accuracy report to the run.

## Conventions

### All interface text goes through i18n, in three languages

Every string a user sees in the web interface must be a translation key resolved through `gclaude_indexer/i18n.py`, with an entry in **all three** language tables: `pt`, `en`, `es`. A key present in only one language falls back silently and reintroduces a language leak, which has been a recurring class of bug in this project. When you add a new user-facing string, add it to all three dictionaries in the same change. A test checks that the three tables have the same keys and the same placeholders.

### Logic returns stable ASCII keys; the template translates

Business logic (routes, background tasks, status calculations) must never return language text or accented identifiers. It returns a stable, ASCII, lowercase key (for example `"done"`, `"scan"`, `"failed"`) that has exactly one job: identifying a state. That key is then used, unmodified, as the lookup into `i18n.py` for the text shown on screen, and as the CSS class name when relevant.

Do not let a single value serve as display text, CSS class and comparison value at the same time. That overload is what caused several interface defects fixed in phase 12 (an accented status string doubling as a CSS class and as the value compared to decide which step runs next). If you add a new state, add its ASCII key first, then the three translations.

### Renames and translations are mechanical

The codebase (identifiers, comments, docstrings, database schema) is in English; that migration is complete. If you still find a leftover Portuguese identifier, translating it is welcome; keep the change mechanical: same behavior, same tests (adjusted only where they assert on renamed identifiers or text). Do not fold in a logic improvement at the same time. Mixing refactors with mass renames is how regressions hide in an otherwise reviewable diff.

### Comments say why, with numbers and dates

A comment that explains a non-obvious decision states what was measured, where and when ("flash attention doubled prompt reading time on the RX 6700 XT via Vulkan, 02/11/2026"). A reader two versions later can then re-measure instead of guessing whether the reason still holds.

### The project is offline

No runtime network calls, except to `http://127.0.0.1:11434` (the local Ollama instance, always loopback, never configurable to a remote host) and the LexML search service (opt-in on the screen; in `buscar.bat`, also when no act in the collection cites the term), which sends only the term the user typed and never anything from the collection. Do not add a dependency that requires network access to function. The classifier prompt, the rules vocabulary and the Planalto reader are behavior knobs: changes to them need a new measurement against `demo/gabarito.csv` and an update to `docs/QUALITY.md`.

### The documentation reads like a person wrote it

README, manual and technical documents follow the same rule in the three languages: no em dash or en dash as an aside, straight quotes, three dots instead of the ellipsis character, no inflated vocabulary, no "it is not X, it is Y". A test in `tests/test_phase38_docs.py` fails on the first violation.

## Packaging the Windows installer

The installer is an Inno Setup script, `installer/GClaudeIndexer.iss`, built by `installer/build.ps1` with Inno Setup 6 (`ISCC.exe`, found in `Program Files` or in `%LOCALAPPDATA%\Programs`). It reads the version from `SYSTEM_VERSION` in `gclaude_indexer/web/app.py` and writes `dist/GClaude-Indexer-Setup-<version>.exe`. The package carries the code, the documentation and `install.ps1`; at install time it runs `install.ps1` with the components the person ticked. What the installer embeds and what it fetches on demand:

- **Python 3.12.** The pinned versions in `requirements.txt` do not install on newer interpreters, so `install.ps1` looks for 3.12 and, when the machine has none, downloads the official 3.12.10 for the current user (exact version, checksum verified), without administrator rights and without touching any other Python.
- **Tesseract OCR and Ghostscript.** Downloaded from their official release URLs, version pinned and hash verified. Ghostscript's own installer cannot run unattended (`requireAdministrator`, and `/S` stopped silencing it in 10.01.0), so `install.ps1` unpacks its payload instead of running it. The OCR language data (`por`, `eng`, `spa`, `osd`, each with a pinned SHA-256) goes to `%LOCALAPPDATA%\GClaudeIndexer\tessdata` when the Tesseract folder needs administrator rights.
- **The hardware-sensor libraries.** `LibreHardwareMonitorLib.dll`, `HidSharp.dll` and the five .NET shim DLLs they need (see `gclaude_indexer/install_diagnostics.py` for the exact package layout), copied to `%LOCALAPPDATA%\GClaudeIndexer\lib\`. The optional PawnIO driver, for CPU temperature and power on recent processors, is a separate component that asks for administrator rights.
- **Ollama and its model** stay an opt-in, separate download: the model alone is several gigabytes, and a person must be able to decline it without declining the rest. The installer also writes the user environment variables the Ollama server needs (`OLLAMA_*` and `LLAMA_ARG_CACHE_RAM`; see `docs/TECHNICAL.md`, "Running day to day") and respects a value the person set by hand.
- **Shortcuts.** The desktop shortcut runs `Indexer.vbs` (no console window); the optional "CPU sensor" shortcut asks for administrator rights at launch, for the sensor helper only.

Installing a new version over an old one stops the running server first; the uninstaller asks, item by item, which shared programs to remove and never touches the person's projects.

## Code style

- Python 3.12, no external formatter enforced; match the style of the surrounding file.
- `from __future__ import annotations` at the top of modules that use it already (after the license header and module docstring).
- Every `.py` file under `gclaude_indexer/` carries a short GPL header at the top (see any existing file for the exact text). Add it to new files too.

## License

By contributing, you agree that your contribution is licensed under the GNU General Public License v3.0, the same license as the rest of the project (see `LICENSE`).
