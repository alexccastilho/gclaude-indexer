*Read this in other languages: [Português (Brasil)](docs/README.pt-BR.md) · [Español](docs/README.es.md)*

# GClaude Indexer

A local, offline tool that turns a folder full of documents into a searchable
index, a chronological timeline, and ready-to-use instructions for a Claude
Project.

## What it does

Point GClaude Indexer at a folder of documents — scanned PDFs, Word,
Excel, PowerPoint files, images, emails, plain text, almost anything — and it
scans the folder, runs OCR on scanned pages that have no text layer, slices
oversized PDFs into readable chunks, and reads every page. It then classifies
the content into discrete items (each with a type, a date when one can be
found, an author, and a short summary) and writes back four Markdown files:
an **index** of every item, a **timeline** ordered by date, a **review**
report listing gaps and failures, and a set of **project instructions** ready
to paste into a new Claude Project. The original documents are never
modified — everything the tool produces is new files written next to your
originals, in a separate output folder you choose.

Classification — the step that decides what each page is, who wrote it and
when — can be done four different ways, described below. Three of those four
never leave your machine. Every other step (scanning, OCR, page extraction,
slicing, writing the four reports) always runs entirely locally, regardless
of which classification engine you pick.

## Highlights

- **Offline by design.** Except for the optional `claude_code` engine (see
  below), GClaude Indexer never sends a document, a page of text, or even a
  filename over the network. This matters most if you work with sensitive
  or confidential collections — nothing leaves the machine unless you
  explicitly choose the one engine that does.
- **Windows only.** The application talks directly to Windows-specific
  interfaces — PowerShell, WMI (for hardware detection and resource
  monitoring), the Windows registry (for the Tesseract data location and
  locale detection) and the Performance Counters subsystem (for live
  CPU/GPU graphs). It does not run on Linux or macOS.
- **Interface in three languages** — English, Brazilian Portuguese and
  Spanish, selectable at any time from a dropdown in the page header. The
  default is detected automatically from your Windows display language.
- **No installer required to use it day to day.** After the one-time setup
  below, a desktop shortcut opens the app with a double-click. Nothing is
  compiled into a single `.exe`; it stays as plain, readable Python and
  PowerShell scripts.
- **GNU GPL-3.0 licensed.** See [License](#license) below for what that
  means if you plan to modify or redistribute this software.

![image alt](https://github.com/alexccastilho/gclaude-indexer/blob/d1502243fb331fd6ada0f415704289a0dd670a94/image.png)

## Requirements

- **Windows 10 or 11.** Required — see [Highlights](#highlights) above for
  why.
- **Python 3.12**, specifically. Newer versions (3.13, 3.14) are known to
  break this project's pinned dependency versions — if your machine's
  default `python` is newer, follow the note in
  [Installing](#installing-first-time-on-a-machine) below to select 3.12
  explicitly.
- For **OCR** (scanned documents with no text layer): Tesseract and
  Ghostscript. The installer below installs both automatically when
  possible.
- For the **`local` classification engine** (the recommended default):
  [Ollama](https://ollama.com), installed automatically by the installer
  below when you accept. A GPU with a few gigabytes of free VRAM speeds this
  engine up considerably, but is not required — Ollama uses as much GPU
  memory as fits and spills the rest into system RAM automatically. As a
  rough guide, the default local model is close to 9.6 GB to download, and
  needs somewhat more than that in combined VRAM + RAM to run; a machine
  with too little of both falls back automatically to the `rules` engine
  (see [Classification engines](#classification-engines) below), with an
  explanation shown on screen.
- The **`rules` engine** needs none of the above — it runs on any Windows
  machine that can run Python, with no GPU, no download and no extra
  software.
- Roughly a few gigabytes of free disk space for the Python environment and,
  if you use it, the local Ollama model.

## Installing (first time on a machine)

You do not need Git, a GitHub account, or any programming experience for
this. You do need to be able to open a folder in File Explorer and run one
command in a terminal — both are explained step by step below.

**1. Get the source code onto your machine.** If you downloaded this project
as a `.zip` file, right-click it and choose "Extract All…", then pick a
regular folder (for example, one inside your Documents or a folder synced
by Google Drive/OneDrive). If you cloned it with Git instead, you already
have a folder — either way, remember where it is; the rest of these
instructions call it "the project folder".

**2. Open PowerShell in the project folder.** In File Explorer, open the
project folder, then either:
- hold **Shift**, right-click an empty spot inside the folder, and choose
  "Open PowerShell window here" (or "Open in Terminal"), or
- click the address bar, type `powershell`, and press Enter.

A blue or dark window opens — this is PowerShell, and it is already "in"
the project folder.

**3. You do not have to install Python yourself.** The installer in step 4
does it: this project needs Python 3.12 specifically (the package versions
it pins do not build on newer releases), and if your machine does not have
it, the installer downloads the official 3.12 from python.org — exact
version, checksum verified — and installs it into your own user folder.
Nothing needs administrator rights for that step.

It is installed *beside* any other Python you have, not over it. If typing
`python --version` today prints 3.13 or 3.14, it will still print the same
thing afterwards: your `python` command, your file associations and your
Start Menu are left exactly as they are.

If you would rather install it yourself first, this is the same thing the
installer does:

```powershell
winget install --id Python.Python.3.12 -e --scope user --silent --accept-package-agreements --accept-source-agreements
```

**4. Run the installer once.** This installs Python 3.12 if it is missing,
creates a private Python environment for this app (kept outside the project
folder, so it survives being moved or re-synced by Google Drive/OneDrive),
installs the required Python packages, checks for Tesseract and Ghostscript
(installing them if missing and you agree), and offers to create a desktop
shortcut.

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

Windows may show a security prompt the first time you run any PowerShell
script downloaded from the internet ("Windows protected your PC") — this is
normal; the `-ExecutionPolicy Bypass` flag above already tells PowerShell to
run this one script anyway, without changing any permanent setting on your
machine.

While it runs, the installer prints its progress and asks for confirmation
before installing anything (Tesseract, Ghostscript, and optionally Ollama
and its default model, which is a large download). If a step fails, it
prints the manual command you can run yourself as a fallback. This first
run can take several minutes, mostly spent downloading packages.

**5. Accept the desktop shortcut offer at the end**, if you want one — it is
the easiest way to open the app afterwards.

The installer then offers a *second*, optional shortcut, "GClaude Indexer
(CPU sensor)". Say yes only if you want CPU temperature and power draw on
the Run screen: those two readings need administrator rights, so that
shortcut makes Windows ask for administrator every time you open the app.
Everything else — including GPU temperature, power and clock — works
without it. Saying no is a perfectly good answer, and you can change your
mind later by running `install.ps1 -CpuSensorShortcut`.

## Running day to day

Once installed, double-click the desktop shortcut. It opens a Command
Prompt-like console the first time only (if the installer still needs to
run); after that, it starts the app with no visible window and opens your
default browser at:

```
http://127.0.0.1:8000
```

The server only listens on `127.0.0.1` — your own machine — and is never
reachable from the network or from any other computer.

If you prefer not to use the shortcut, from the project folder:

```powershell
python launcher.py
```

This does the same thing the installer does — checks the environment,
installs anything missing — before starting the server, so it also works as
a "just make it work" command on a machine where you have not run the
installer yet.

To close the app, close the terminal window it opened (or, if it is running
hidden via the shortcut, find `pythonw.exe` in Task Manager and end it).

### The optional CPU sensor

If you took the "GClaude Indexer (CPU sensor)" shortcut, opening it raises
a Windows administrator prompt. What is being elevated is *not* the app: it
is one small helper process that does nothing but read the sensors and hand
the numbers back. The server, the indexing and your documents keep running
without any privileges, and the helper closes together with the app.

Answering **No** to that prompt is safe and costs you nothing else: the
system opens exactly as it does from the ordinary shortcut, showing GPU
temperature, power and clock, and "not measured" for the two CPU sensors.
Nothing fails, and no error is shown.

## Uninstalling

Double-click `Desinstalar.bat` in the project folder — the same folder as
`Indexer.bat`. From a prompt, either of these:

```powershell
.\Desinstalar.bat
powershell -ExecutionPolicy Bypass -File uninstall.ps1
```

**Why not just `.\uninstall.ps1`?** Google Drive marks every file it syncs
as having come from the internet, and Windows' default execution policy
(RemoteSigned) refuses to run a `.ps1` from that zone without a digital
signature — "the file is not digitally signed". Nothing is wrong with the
script: `Desinstalar.bat` simply passes `-ExecutionPolicy Bypass` for that
one run, which is what every other launcher in this project already does.
Running `install.ps1` also clears the mark from this folder's scripts, so
the direct command works after that too.

It asks about each item separately, defaulting to **no** every time. It
distinguishes what this installation owns — the virtual environment, the
shortcuts, the sensor libraries, local settings, the PATH entries and
environment variables it added — from the ordinary programs it merely
installed for you: Tesseract, Ghostscript, Ollama, Python and the
downloaded Ollama models. Other software on your machine may be using
those, so each is offered on its own, with that said plainly.

**It never deletes your projects.** The output folders, their databases,
the OCR'd PDFs and the generated reports are your documents, not
installation leftovers. The script lists where they are, with their sizes,
and leaves the decision to you.

Three switches cover the non-interactive cases:

```powershell
powershell -ExecutionPolicy Bypass -File uninstall.ps1 -WhatIfOnly        # show the plan, remove nothing
powershell -ExecutionPolicy Bypass -File uninstall.ps1 -KeepDependencies  # keep Tesseract, Ghostscript, Ollama, Python
powershell -ExecutionPolicy Bypass -File uninstall.ps1 -RemoveAll         # say yes to everything (still not your projects)
```

The project folder itself is synced by Google Drive and is never touched:
delete it there if you want it gone from every computer.

## Using the app

The interface has four screens, plus an "About" page:

1. **Projects** — lists every project you have opened, with its creation
   date and current status. This is where you land when you open the app.
   At the bottom is **Shared catalog**: point it at a folder inside your
   Google Drive and every computer signed into that Drive sees, opens,
   edits and deletes the same projects. Without it, the project *list*
   stays on this machine even though the projects themselves sync — which
   is why a second computer would otherwise show an empty screen. Projects
   stored on another computer's local disk are listed and marked as out of
   reach. **Open existing project**, next to "New project", takes a folder
   you point at and reopens the project inside it — for a reinstall, a new
   machine, a folder you moved, or one someone sent you. Nothing is
   recreated: the output folder already holds the whole project, and it is
   used exactly as found.
2. **New project** — a form where you pick a source folder (the documents),
   an output folder (where the results go), which file types to include,
   how documents should be grouped, and which classification engine to use.
   Every field has a sensible default already filled in and a "?" hint next
   to its label.
3. **Execution** — one row per processing step (scan, conversion, page
   extraction, window preparation, classification), each with a "run this
   step" button, a progress bar with a time estimate, and a pause button.
   A live log and a CPU/RAM/GPU usage graph are shown below. A separate
   button, "Import and generate reports", runs the last two steps (turning
   classified items into the four output files) once classification is
   done.
4. **Result** — a preview of the four generated files, a button to open the
   output folder directly in File Explorer, a report of anything still
   pending, and a button to free up disk space by deleting intermediate
   files (the OCR'd PDFs and text slices) once you are happy with the
   result — the database, the four reports and the logs are never touched
   by this.

A language selector and a theme selector (four color themes) sit in the
header of every screen; both choices are remembered in your browser between
visits.

## Getting a good classification

Two settings decide more about the result than anything else, and both are
easy to get wrong because nothing forces you to think about them.

**Fill in Subject and Collection type on the New project form.** They are
not decoration: the `local` engine puts them in front of the model, and
they are what tells it *what kind of document it is looking at*. A
collection of course material described only by the defaults gets classified
against generic examples, and the model correctly answers "I don't know" for
almost every type. Writing one sentence about the collection — what it is,
where it came from, what the documents are — is the single most effective
thing you can do for the result. "Role instructions" and "Extra rules" are
passed along too, as context about the collection.

**Which model to use.** Benchmarked on this project, over the same
windows of a 31-page document, with every model running fully on an 8 GB
card:

| Model | Size | Type filled | s/window |
|---|---:|---:|---:|
| **`qwen3.5:4b`** | **3.0 GB** | **100%** | **30.8** |
| `gemma4:e4b` | 3.1 GB | 79.5% | 38.5 |
| `qwen3.5:9b` | 5.3 GB | 79.5% | 86.2 |
| `qwen3:8b` | 5.4 GB | 100% | 108.8 |
| `granite4.2:8b` | 5.7 GB | 100% | 116.9 |

`qwen3.5:4b` reaches the same quality as the best of them in a quarter of
the time and half the VRAM, and fits a 6 GB card as comfortably as an 8 GB
one — one setting for every machine. Note that the larger model of the same
family lost to the smaller: describing a page is reading and format
discipline, not deep reasoning, so size buys nothing here and costs time.

**Pick a model that fits your graphics card.** Ollama runs whatever does not
fit in VRAM on the CPU instead, and the difference is not subtle. On the
machine this was measured on — an 8 GB card — a 9.1 GB model ran with 17% of
itself on the GPU; a 5 GB model ran entirely on the GPU. The Run screen
shows your card's VRAM, the "About" screen lists the installed models, and
the log warns you when the chosen model cannot fit. Smaller is usually the
right trade: a model that fits and finishes beats a larger one that spends
the run swapping.

If the quality score looks low, open the log: it now reports how the GPU is
being used and, on the Result screen, the score is broken down into
confidence, field completion and penalties, so you can see which of the
three is costing you.

### Windows, blocks and OCR

**Pages per window** is the setting that decides quality: it is how many
pages go into each request to the model, and the model answers with one
line per page. **8 is the recommended value.** With 16 the answer alone
runs past 3,500 tokens and starts being truncated — which was the cause of
every poor result measured while tuning this. With 4 you triple the number
of requests for nothing.

**Pages per block** does *not* affect the index. It only cuts very large
PDFs into smaller auxiliary files under `output/blocks/`, which nothing
else reads and which the "free up space" button deletes. Leave it at 80;
lower it only if a very large PDF (500+ pages) makes conversion run out of
memory.

**OCR** applies only to PDFs with no text layer — the system detects this
per file and skips it when the text is already there. What matters then is
`ocr_language` matching your documents.

## Classification engines

Classification — deciding what each page is, who wrote it, and when — is
the one step in the whole pipeline where you choose *how* the work gets
done. Everything else in the pipeline (scanning, OCR, extraction, writing
the reports) is identical no matter which engine you pick here.

| Engine | Cost | Leaves the machine? | Needs |
|---|---|---|---|
| `rules` | free | no | nothing — runs on any Windows machine |
| `local` | free | no | Ollama, installed automatically; faster with a GPU, works without one |
| `claude_code` | your existing Claude Code subscription | **yes** | Claude Code already installed on this machine |
| `automatic` | — | — | picks `local` if the hardware can run it, otherwise falls back to `rules`; never picks `claude_code` on its own |

**`claude_code` is entirely optional.** GClaude Indexer works from start to
finish without it, using `rules` or `local` — neither needs anything beyond
what the installer already sets up. Choose `claude_code` only if you
already use Claude Code and specifically want classification done through
it; in that case, the app prepares the files and shows you a command to
paste into Claude Code, then imports the result once Claude Code is done.

`rules` is a deterministic engine — it looks for known document-type
markers, date patterns and signature blocks, with no machine-learning model
involved, so its output is fully reproducible and needs no installation at
all. `local` uses an open model served by [Ollama](https://ollama.com) on
your own machine (`http://127.0.0.1:11434`, never a remote address) and
generally produces better results than `rules`, at the cost of the disk
space, download and (optionally) GPU listed under
[Requirements](#requirements).

A "review low-confidence items" option is also available in the New Project
form: it runs `rules` over everything, then reruns only the low-confidence
items through a second engine of your choice — a middle ground between
`rules`'s zero cost and a more expensive engine's better accuracy on the
handful of pages that actually need it.

## Output files

Written to the output folder you chose, always in the language the
interface is set to at the time you generate them:

- `index.md` — a catalog of every classified item, with its origin, type,
  date, author and summary.
- `timeline.md` — the dated items in chronological order.
- `review.md` — a coverage report: gaps, failures, anything still pending.
- `project_instructions.md` — ready-to-paste instructions for a new Claude
  Project, built from a template with the fields you filled in on the New
  Project form.

The Result screen also offers a `.zip` package containing these four files
plus a short guide, sized for pasting directly into a brand-new Claude
Project.

## OCR and document languages

Tesseract's OCR defaults to Portuguese (`por`) for new projects, since this
project originated for Brazilian Portuguese document collections.

Tesseract's own Windows package ships only `eng` and `osd`, so `install.ps1`
downloads and installs the language data the project is configured for
(`por` by default) into Tesseract's `tessdata` folder. It asks Windows for
administrator rights just for that one file copy, and verifies the file's
SHA-256 before installing it.

If your collection is in another language, change the "OCR language" field
in the New Project form to the matching Tesseract language code (for example
`eng` for English or `spa` for Spanish), and install that language's data
pack by running the installer with the code you need:

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1 -OcrLanguage spa
```

The installer only installs languages whose SHA-256 it has pinned — `por`,
`eng`, `spa` and `osd` today. It never downloads a file it cannot verify;
for any other language it prints where to get the file and where to put it,
and carries on.

## Running the test suite

If you are contributing changes or just want to confirm everything works
after installing, using the Python interpreter inside the environment the
installer created (not whatever `python` your PATH resolves to — see
[Requirements](#requirements)):

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -B -m pytest -q
```

A correct run ends with a line like:

```
317 passed, 6 warnings in 147.01s (0:02:27)
```

(The warning count may vary slightly by machine; they come from third-party
libraries, not from this project's own code.) See
[CONTRIBUTING.md](CONTRIBUTING.md) for a full development setup.

## Troubleshooting

- **A banner says the system was updated after the window opened.** The
  code on disk changed while this server was running, and Python loads its
  modules once, at startup — what is running is still the older version.
  Close the system and open it again from the shortcut. A run started
  before doing that would use the old code.
- **The browser opens but the page never loads.** Give it a few seconds —
  the server can take a moment to start on the first run. If it still does
  not load, check whether another program is already using port 8000.
- **"python is not recognized…" in PowerShell.** Python is not on your
  system's PATH. Reinstall it with the `winget` command in
  [Installing](#installing-first-time-on-a-machine) and try again, or use
  the full path to the interpreter as shown in
  [Running the test suite](#running-the-test-suite).
- **OCR fails or produces no text.** Confirm Tesseract and Ghostscript are
  installed (`install.ps1` checks this automatically) and
  that the language pack matching your documents is installed — see
  [OCR and document languages](#ocr-and-document-languages).
- **The `local` engine falls back to `rules` with a memory warning.** Your
  combined GPU VRAM and system RAM is below what the local model needs —
  see [Requirements](#requirements). This is not an error: the app degrades
  on purpose instead of failing outright.
- **Nothing works until I reboot after installing.** This was fixed: the
  installer now records where it put each program and `Indexer.bat`
  reloads PATH from the registry, so neither depends on Windows Explorer
  noticing the change. If you hit it on an older install, run
  `install.ps1` once more — signing out is no longer necessary.
- **I reinstalled (or reformatted) and my projects are gone from the
  list.** They are not gone — the projects live in their output folders,
  it is the list that was rebuilt empty. Use **Projects → Open existing
  project** and point at a project's output folder; it reopens with its
  configuration and everything already processed. Never point "New
  project" at a folder that already holds one: the app now stops you, but
  the intent there is to *open*, not to create.
- **I reinstalled (or reformatted) and my projects are gone from the
  list.** They are not gone — the projects live in their output folders,
  it is the list that was rebuilt empty. Use **Projects → Open existing
  project** and point at a project's output folder; it reopens with its
  configuration and everything already processed. Never point "New
  project" at a folder that already holds one: the app now stops you, but
  the intent there is to *open*, not to create.
- **My projects do not show up on the other computer.** The projects sync
  through Drive, but the list of them is per-machine until you set a
  shared catalog. Open **Projects → Shared catalog**, choose a folder
  inside your Drive, and save — on both computers, pointing at the same
  folder. Your existing projects are copied into it automatically.
- **Opening the same project from a second machine right after the first.**
  Wait for Google Drive (or whichever sync tool holds your output folder)
  to finish syncing before opening it elsewhere — the app detects and warns
  about incomplete syncs and about another machine's active lock, but
  cannot substitute for waiting.

## Documentation

- [CONTRIBUTING.md](CONTRIBUTING.md) — development setup, running a single
  test, and the project's conventions.
- [docs/SPECIFICATION.md](docs/SPECIFICATION.md) — the full technical
  specification: data model, every processing step, security rules and
  design decisions, in more detail than this file.
- [CHANGELOG.md](CHANGELOG.md) — what changed, release by release.
- [SECURITY.md](SECURITY.md) — how to report a vulnerability.
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) — community standards for
  contributors.

## License

GClaude Indexer is licensed under the **GNU General Public License v3.0**
(GPL-3.0) — see [LICENSE](LICENSE) for the full text. In short: you are
free to use, study, modify and redistribute this software, including
commercially, but any modified version you distribute must also be licensed
under GPL-3.0 and its source made available. There is no warranty of any
kind.
