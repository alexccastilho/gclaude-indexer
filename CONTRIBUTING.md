*Read this in other languages: [Português (Brasil)](docs/CONTRIBUTING.pt-BR.md) · [Español](docs/CONTRIBUTING.es.md)*

# Contributing to GClaude Indexer

Thank you for considering a contribution. This document covers how to set
up a development environment, run the test suite, and the conventions the
codebase relies on.

## Windows only

GClaude Indexer runs on **Windows only**. It is not a portability gap to be
fixed incidentally — the codebase talks to Windows-specific surfaces on
purpose: PowerShell (installer and launcher scripts), WMI (hardware and
resource sensors), and the Windows registry (locale/language detection).
Contributions that add cross-platform abstraction layers without a concrete
need are out of scope; contributions that fix a genuine Windows bug, or
extend Windows-specific functionality, are very welcome.

## You do not need Claude Code

The project name mentions Claude, but **Claude Code is optional**, both to
use the software and to contribute to it. Classification of collection
items is done by one of three interchangeable engines (plus an `automatic`
mode that picks between the first two based on the machine's hardware):

- `rules` — deterministic, no external tool required.
- `local` — uses a local Ollama model.
- `claude_code` — delegates classification to Claude Code, for users who
  already have it installed.

The `rules` and `local` engines are enough to run the full pipeline
end-to-end and to work on almost anything in this repository. You only need
Claude Code if you are specifically working on `gclaude_indexer/engine_claude_code.py`
or `gclaude_indexer/claude_package.py`, and even then the test suite mocks the
subprocess call — you do not need Claude Code installed to run the tests.

## Setting up the environment

1. Install Python 3.12. The environment must **not** live inside a folder
   synced by Google Drive/OneDrive/etc — file locking during sync breaks
   SQLite and virtualenvs. The convention used by this project is a venv in
   `%LOCALAPPDATA%\GClaudeIndexer\venv`.

   ```powershell
   py -3.12 -m venv "$env:LOCALAPPDATA\GClaudeIndexer\venv"
   ```

2. Install the dependencies:

   ```powershell
   & "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pip install -r requirements.txt
   ```

3. Alternatively, run the installer script, which does the above plus
   checks for Tesseract/Ghostscript and offers to create a desktop shortcut:

   ```powershell
   powershell -ExecutionPolicy Bypass -File install.ps1
   ```

## Running the tests

Always use the venv interpreter, not whatever `python` resolves to on
`PATH` (a newer, unpinned Python breaks the pinned dependency versions):

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -B -m pytest -q
```

The suite must pass in full before and after your change. If you are
working on a single test file during development:

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -B -m pytest tests/test_something.py -v
```

The project does not use a git repository at present; where a normal
workflow would ask for a commit at each step, run the full suite instead.

## Conventions

### All interface text goes through i18n, in three languages

Every string a user sees in the web interface must be a translation key
resolved through `gclaude_indexer/web/i18n.py`, with an entry in **all
three** language tables: `pt`, `en`, `es`. A key present in only one
language falls back silently and reintroduces a language leak — this has
been a recurring class of bug in this project. When you add a new
user-facing string, add it to all three dictionaries in the same change.

### Logic returns stable ASCII keys; the template translates

Business logic (routes, background tasks, status calculations) must never
return language text or accented identifiers. It returns a stable, ASCII,
lowercase key (e.g. `"done"`, `"scan"`, `"failed"`) that has exactly one
job: identifying a state. That key is then used, unmodified, as:

- the lookup into `i18n.py` for the text shown on screen, and
- the CSS class name, when relevant.

Do not let a single value serve as display text, CSS class, and comparison
value at the same time — that overload is what caused several interface
defects fixed in phase 12 (an accented status string doubling as a CSS
class and as the value compared to decide which step runs next). If you
add a new state, add its ASCII key first, then the three translations.

### Renames and translations are mechanical

The codebase (identifiers, comments, docstrings, database schema) is now
fully in English — that migration is complete. If you still find a
leftover Portuguese identifier, translating it is welcome; keep the change
mechanical: same behavior, same tests
(adjusted only where they assert on renamed identifiers/text). Do not fold
in a logic improvement at the same time — mixing refactors with mass
renames is how regressions hide in an otherwise-reviewable diff.

### The project is offline

No runtime network calls, except to `http://127.0.0.1:11434` (the local
Ollama instance, always loopback, never configurable to a remote host).
Do not add a dependency that requires network access to function.

## Packaging a Windows installer (future work)

Today, setup on a new machine is `install.ps1`: it finds a base Python,
creates the venv, installs `requirements.txt`, and offers to install
Tesseract/Ghostscript/Ollama one at a time via `winget`, asking before each
download. That script is the reference for what a real installer package
(an MSI, or an Inno Setup `.exe`) would need to do unattended, in one step.
This section documents what such a package would need to **embed** versus
what it should still fetch on demand — nobody has built this package yet;
building it is separate work from this document.

**Embed in the package** (so the app runs with no further downloads):

- **Python 3.12** — an embeddable or full 3.12 runtime. The pinned
  versions in `requirements.txt` do not install on newer interpreters (a
  `python`/`py` that resolves to 3.13+ builds a broken environment today —
  see "Setting up the environment" above, which pins `py -3.12`
  explicitly), so the package must supply its own 3.12 rather than trust
  whatever `python` is already on the target machine's `PATH`. The package
  would create the venv at `%LOCALAPPDATA%\GClaudeIndexer\venv` and install
  `requirements.txt` from bundled wheels, so the target machine never needs
  its own Python or an internet connection for this step.
- **Tesseract OCR** and **Ghostscript** — `install.ps1` downloads both
  from their official release URLs (UB-Mannheim's Tesseract build,
  ArtifexSoftware's Ghostscript build), with the version pinned and the
  hash verified; the same files can be embedded and used from disk
  instead. Note that Ghostscript's own installer cannot run unattended
  (`requireAdministrator`, and `/S` stopped silencing it in 10.01.0), so
  `install.ps1` unpacks its payload rather than running it — a package
  embedding Ghostscript would need to do the same, or ship the unpacked
  tree directly.
- **The hardware-sensor DLLs** — `LibreHardwareMonitorLib.dll` and
  `HidSharp.dll` (from LibreHardwareMonitor's GitHub releases), plus the
  five .NET BCL shim DLLs `System.Memory`, `System.Buffers`,
  `System.Runtime.CompilerServices.Unsafe`, `System.Numerics.Vectors`, and
  `System.Threading.AccessControl` (from nuget.org — see the exact package
  layout in `gclaude_indexer/install_diagnostics.py`), copied to
  `%LOCALAPPDATA%\GClaudeIndexer\lib\`. Nothing in the current codebase
  automates this download — `install.ps1` does not fetch these DLLs either,
  it only reports them missing on the "About" screen — so a packaged
  installer is the first place this would actually be automated.
- The desktop shortcut to `Indexer.vbs` (an MSI/Inno Setup installer
  creates this natively; `install.ps1`'s `New-DesktopShortcut` function is
  the reference for target, working directory, and icon).

**Leave as an optional, separate download** (do not embed):

- **Ollama** and, especially, **its default local model** — the model
  alone is several gigabytes. `install.ps1` already asks about these
  separately from Tesseract/Ghostscript for the same reason: a user
  should be able to decline a multi-gigabyte download without declining
  the rest of the setup. A packaged installer should preserve that
  separate opt-in rather than bundling the model file.

## Code style

- Python 3.12, no external formatter enforced yet; match the style of the
  surrounding file.
- `from __future__ import annotations` at the top of modules that use it
  already (after the license header and module docstring).
- Every `.py` file under `gclaude_indexer/` carries a short GPL header at
  the top (see any existing file for the exact text). Add it to new files
  too.

## License

By contributing, you agree that your contribution is licensed under the
GNU General Public License v3.0, the same license as the rest of the
project (see `LICENSE`).
