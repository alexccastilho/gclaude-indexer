# Changelog

All notable changes to this project are documented in this file. The
format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

Entries are grouped by development phase, following the project's own
planning documents in `docs/superpowers/plans/`, rather than by semantic
version — the reported application version (`SYSTEM_VERSION` in
`web/app.py`) stayed `1.0.0` from phase 1 through phase 16. `1.0.1` is the
first bump, and it releases everything the phase 16 block below had been
carrying as unreleased.

## [1.0.1] — 2026-09-03

The release that goes out with the project's first public announcement.

### Changed

- **The default local model is now `qwen3.5:4b`, replacing `gemma4:e4b`.**
  This is the project's own measurement finally reaching the default: over
  the same windows of a 31-page document, every model fully resident on an
  8 GB card, `qwen3.5:4b` filled the type field on 100% of the pieces at
  30.8 s/window against `gemma4:e4b`'s 79.5% at 38.5 s/window — better and
  faster at the same time, which is not the usual shape of that trade. The
  README had recommended it since phase 15; `DEFAULT_LOCAL_MODEL` had not
  followed. `gemma4:e4b` stays selectable in the New Project form for
  anyone who wants to compare, but it is no longer what the installer
  downloads.

  The practical effect is on first use, not on quality: `gemma4:e4b` pulls
  ~9.6 GB from Ollama even though only ~3.1 GB of it is resident, so a
  first run now downloads roughly a third of what it used to, and fits a
  6 GB card as comfortably as an 8 GB one. `install.ps1` reads
  `DEFAULT_LOCAL_MODEL` from Python rather than hardcoding a name, so it
  followed the change on its own.

### Fixed

- **The hardware check told every machine it needed ~9.6 GB it did not
  need.** `ESTIMATED_MODEL_SIZE_MB` was calibrated for `gemma4:e4b` and is
  the number `choose_model` falls back to before Ollama can report a real
  size — that is, on exactly the first run, when nothing has been
  downloaded yet. Left at 9_600 next to a 3.2 GB default, it would have
  pushed borderline machines to the `rules` engine over memory they never
  had to have. Now 3_232, the size this machine's Ollama reports for
  `qwen3.5:4b`.

### Documentation

- **A demo GIF (`demo.gif`) at the top of all three READMEs**, walking
  through the four screens in order — projects, new project, execution,
  result.
- **The Python 3.12 requirement no longer reads like a manual step.** The
  installer has downloaded and installed Python 3.12.10 for the current
  user since phase 15 task 4, and the "Installing" section said so, but
  the "Requirements" bullet above it still told the reader to go select
  3.12 themselves — the first thing a newcomer reads, describing a barrier
  that no longer exists.
- **The language links now lead each README**, with the other two
  languages named in their own language rather than folded into one line
  of small print.
- The `new.png` screenshot was retaken: it showed `gemma4:e4b` selected in
  the model dropdown, which is no longer what a fresh install shows.

## Phase 16: Second-Machine Report — released in 1.0.1

Everything in this phase comes from one source: the maintainer installed
the system on a second computer and wrote down the eight things that were
wrong with it. Each entry below names the defect as it was experienced,
not as it was implemented.

### Fixed

- **Console windows flashed over the desktop all through the OCR and
  Ghostscript conversion.** `subprocess_utils.run_hidden` already hid
  every command this code runs; it could not hide the ones the libraries
  run. `pytesseract` starts `tesseract.exe` through its own `Popen`, and
  `ocrmypdf` starts Tesseract, Ghostscript, `pngquant` and `jbig2` from
  inside its pipeline — none of them with `CREATE_NO_WINDOW`, and none of
  them ours to change. The server being windowless is exactly what made
  each of those visible: a process with no console that starts a console
  child makes Windows allocate a new console **and show it**. Suppression
  is now a property of the process rather than of individual call sites
  (`no_window.install()` wraps `subprocess.Popen.__init__`), applied in
  the server, in every conversion pool worker (`initializer`), in the new
  `_ocr_runner` that fronts ocrmypdf's command line, and — through a
  `sitecustomize.py` on the OCR subprocess's `PYTHONPATH` — in ocrmypdf's
  own `--jobs` pool workers, which are the direct parents of Tesseract.
- **The CPU sensors stayed empty even when the elevated shortcut was
  used.** The project folder is a Google Drive virtual drive, mounted
  under the logged-on user's session token. An elevated process runs under
  the administrator half of the same split token, and Windows does not
  carry drive mappings across that boundary — `H:\...` does not exist for
  the elevated child, so `python -m gclaude_indexer.sensor_service` failed
  with "No module named" before executing a line of ours, silently,
  because the helper runs under `pythonw.exe` with `SW_HIDE`. The four
  modules the helper needs are now mirrored into `%LOCALAPPDATA%` and it
  runs from there. The server's own local folder is also passed on the
  command line, so elevating with a *different* administrator account
  cannot publish the reading into a profile the server never reads. A new
  `helper_sem_resposta` state distinguishes "the helper started and did
  not answer" from "you never asked for it" — the two used to look
  identical on screen, so the advice shown was to do what the user had
  already done.
- **The GPU's VRAM was never filled before work spilled into RAM.**
  `options.num_gpu = -1` reads as "use as much GPU as possible" and does
  not do it: it hands the decision to Ollama's scheduler, which sizes the
  KV cache for `OLLAMA_NUM_PARALLEL` concurrent requests (four by default,
  where this classifier sends one), keeps its own margin on top, and
  rounds down. Two independent changes: the settings that decide what fits
  are now written as user environment variables by the installer and
  passed to any Ollama server this program starts itself (one loaded
  model, one parallel slot, flash attention, a quantised KV cache); and
  `gpu_budget.py` measures the free VRAM, reads the model's real shape and
  asks for a **specific** layer count instead of "as many as fit".
  `num_ctx` is now sent explicitly too — Ollama's 4096-token default is
  smaller than a full window at this project's defaults, and a longer
  prompt was being truncated in silence.
- **A reboot was needed before the system worked on a new machine.** The
  install was complete; the `PATH` change had not reached the processes
  that were already running. `install.ps1` writes it to the registry and
  broadcasts `WM_SETTINGCHANGE`, which Explorer frequently ignores, so
  every process Explorer starts — the shortcut, `Indexer.vbs`,
  `Indexer.bat`, the server, everything the server spawns — kept the
  environment from before the install, and only logging out (which
  restarts Explorer) fixed it. Two independent fixes, either one
  sufficient: the installer records the absolute path of everything it
  installed into `tools.json` at the moment it installs it, and `tools.py`
  consults that before `PATH`; and `Indexer.bat` rebuilds `PATH` from the
  registry before starting anything.
- **The live log could not be scrolled, read, selected or copied.** Three
  separate causes, all of them real. `.log` and `.log-box` both had
  `overflow-y: auto`, so the inner list was what actually scrolled while
  the script drove the outer box. The lines were rendered newest-first
  while the "follow" behaviour scrolled to the *bottom*, so following a
  run dragged the reader to the oldest visible line every two seconds. And
  HTMX replaced the panel's entire content on every poll, which wiped out
  any text the user had selected. The log is now chronological, the outer
  box is the only scrolling container (and can be dragged taller), and new
  lines are **appended** through `/run/log?since=<id>` instead of the
  panel being rebuilt. Refreshing pauses while a selection is active, and
  there are "go to the end" and "copy" buttons.
- **The estimated time to finish each step was wrong.** It divided items
  finished by seconds elapsed. That counted the wrong thing (a 900-page
  scanned PDF and a 3 KB note are both "one file"), averaged over the
  wrong window (including one-off startup costs, and unable to react when
  the real pace changed), and jumped on every poll. `web/eta.py` now
  weights progress by bytes for the steps that process files, averages the
  rate exponentially so recent pace dominates, smooths what reaches the
  screen, and drops the estimate entirely — rather than counting down
  towards a moment that will not arrive — when a step stalls.
- **Projects saved on one computer did not appear on another.** The
  projects themselves sync through Drive; the *list* of them lived in
  `%LOCALAPPDATA%`, so a second computer opened on an empty Projects
  screen with every project sitting right there on disk. The catalog can
  now live in a Drive folder chosen on the Projects screen. Paths are
  stored relative to that folder as well as absolutely, and the relative
  one wins on read, because the drive letter differs between machines
  (`H:` here, `G:` there — section 11.5). Setting the folder also copies
  the machine's existing projects into it. Projects that live on another
  computer's local disk are listed and marked as out of reach rather than
  hidden.

- **Pointing "New project" at a folder that already held one destroyed
  that project's configuration, silently.** That was the only gesture
  available for reopening, and it was accepted without a word:
  `create_project` INSERTed a *second* row into the project's own `project`
  table, and `load_project` read `ORDER BY id DESC` — the newest — so the
  form's values became the project's. Every scanned file, page and item
  survived, which is what made it invisible: it looked like it had worked.
  The saved subject was gone and structural settings went with it, so a
  project whose windows had been built at 8 pages each carried on at 16.
  Measured, not inferred. The form now detects the existing project, stops
  with a 409 and offers to open it; and `load_project` reads the *first*
  row, restoring the original configuration on every database this already
  happened to. The extra rows are deliberately not deleted — they are the
  only remaining record of the second attempt, and a repair that destroys
  evidence to tidy up is not a repair — and a warning is logged once per
  database saying which configuration is in force.

- **`uninstall.ps1` would not run at all from a PowerShell prompt.** Not a
  defect in the script: Google Drive marks every file it syncs with
  `Zone.Identifier`/`ZoneId=3` — "came from the internet" — and Windows'
  default execution policy, RemoteSigned, refuses to run a `.ps1` from that
  zone without a digital signature. The message ("the file is not digitally
  signed") reads as though the script were broken. It applied to
  `install.ps1` just as much, and only never showed because that one is
  always started through `Indexer.bat`, which passes `-ExecutionPolicy
  Bypass`; the uninstaller was the one script with no launcher of its own.
  Added `Desinstalar.bat` — the desktop shortcut now points at it, and it
  forwards `-WhatIfOnly`/`-KeepDependencies`/`-RemoveAll` — and
  `install.ps1` now runs `Unblock-File` over this folder's scripts so the
  direct command works too. The execution policy itself is left alone: that
  is a machine-wide security setting, and not an installer's to change.
- **A server can run code older than the files on disk, and nothing said
  so.** Python loads a module into memory once, at startup; editing the file
  afterwards changes nothing for a process already running. Observed here in
  the worst way: a server started at 02:09 was still running at 08:03 with
  code corrected at 05:40, spending those hours producing an index with a
  defect that had already been fixed. The only clue was a log line the user
  happened to read and find odd. Every screen now carries a banner when the
  source on disk differs from what the process loaded.

  Compared by **content hash, not modification time**: the project folder is
  synced by Google Drive, and a sync client rewrites timestamps on files
  whose bytes never changed. A date comparison would cry wolf often enough
  to be ignored, which is the worst thing a warning can be. Hashing every
  `.py` in the package costs a few milliseconds and never reports a change
  that is not real.

- **The uninstaller no longer gets a desktop shortcut** (explicit user
  decision). The desktop is for what you open every day, and an uninstaller
  is the opposite of that — a button nobody means to press, sitting beside
  the one they press daily, wearing the same icon. It stays two clicks away
  in `Desinstalar.bat`, in the project folder next to `Indexer.bat`.
  `uninstall.ps1` still removes the shortcut from machines that already have
  one.

- **A measured model recommendation, and the settings that go with it.**
  Five models benchmarked over identical windows of a 31-page document, all
  running fully on an 8 GB card: `qwen3.5:4b` (3.0 GB) reaches 100% of items
  typed and dated in 30.8 s per window, against 116.9 s for `granite4.2:8b`
  at the same quality, and it fits a 6 GB card just as comfortably — one
  setting for every machine. The larger model of the same family lost to the
  smaller one (`qwen3.5:9b`: 79.5% in 86.2 s), which follows from what the
  task now is: describing a page is reading and format discipline, not deep
  reasoning. `pages_per_window` of 8 is documented as the value to use, and
  `pages_per_block` is documented for what it is — a setting that produces
  auxiliary files and does **not** affect the index at all.

- **Nothing in the collection may be missing from the index — and it was.**
  The purpose of this system, stated by its owner: the index is read to find
  *which PDF, on which page* holds an answer, without loading the PDFs
  themselves into a Claude project. A page absent from the index is
  information nobody can find again. Benchmarked on a 31-page laboratory
  report, five models across three families — `gemma4:e4b`, `qwen3:8b`,
  `qwen3.5:9b`, `qwen3.5:4b`, `granite4.2:8b` — covered between 0% and 9,7%
  of the pages, every one of them reporting "high" confidence. Adding an
  explicit "cover every page" rule to the prompt moved two models to 22,6%
  — *the same figure for both*, which is what settled the diagnosis: when
  independent models fail identically, the task is wrong, not the model.

  The task was asking for arithmetic. "Return the items, each from ref_start
  to ref_end" makes the model enumerate ranges that must sum to exactly the
  window, with no gap and no overlap. A small model reads one page well and
  closes that accounting badly.

  So the question was inverted: **one line per page**. The model says what
  is on each page and nothing else; the grouping into items became the
  code's job, which can count. Coverage is now a property rather than a
  hope — `_group_pages_into_items` walks the window's pages, not the
  model's answer, so a page it never mentioned still reaches the index with
  its own text.

  Two further defects were found and fixed while measuring this:

  * Asking the model to echo the page's citable reference back ("copied
    exactly as it appears") made `qwen3.5:4b` copy the ENTIRE page text into
    the `ref` field; the JSON ran past its limit before closing and the
    parser got zero rows. Pages are now numbered 1..N and the model returns
    the number — an integer cannot be mistaken for the content, and the code
    already knows which reference each position holds.
  * The model marked `continues: true` on eight consecutive laboratory tests
    it had itself named correctly (Hemograma, Ferritina, Metabolismo do
    Ferro, Vitamina B-12, Protrombina, Ureia, Creatinina) — it read
    "continues the same *report*" where the prompt meant "the same
    *subject*". Grouping is now decided in code by comparing subjects;
    `continues` only breaks ties when the wording of one subject changes
    without the document changing ("Hemograma — série vermelha" / "— série
    branca").

- **Coverage now carries the most weight in the quality score (40 of 100).**
  It was not measured at all, and that was the gap the benchmark exposed:
  the 9,7%-coverage result above scored close to 100, because the handful of
  items that did exist had perfect confidence and perfect field completion.
  Coverage is the one failure with no remedy downstream — an empty type can
  be reclassified, a page missing from the index is simply never found.
  Confidence dropped to 35 and field completion to 25 to make room.

- **A summary length cap (600 characters per item).** The whole index has to
  fit inside a Claude project's context; it is the sum of these summaries
  that fills it. Without a cap the index would grow into a second copy of
  the collection, which is precisely what it exists to avoid.

- **The project form's own fields never reached the model.** `subject`,
  `collection_type`, `role_instructions` and `extra_rules` were collected,
  validated and stored, and then used only to write
  `instrucoes-do-projeto.md` — an artifact produced *after* classification.
  No engine showed them to the model. The cost was measured on a real
  collection: postgraduate course material classified by a prompt whose
  only worked examples were "OFÍCIO, MEMORANDO, PARECER" came back with
  1432 of 1445 items carrying no type at all. The model was not failing; it
  was answering the question it had been asked. The `local` engine now
  builds a context block from those fields, framed as *what this collection
  is* rather than as the task — `extra_rules` on that collection said "all
  current legislation must be observed", an instruction for the later
  research use of the index and not something a classifier should try to
  carry out.
- **The prompt asked for documents and accepted pages.** The same run
  produced 1445 items for 1844 pages — 1.28 pages per item, sliced two
  pages at a time straight through documents that ran for dozens. The
  prompt now states the rule explicitly, with the failure it is meant to
  prevent.
- **`ÍNDICE` and `Índice` were two different document types.** Types are
  normalised (upper-cased, whitespace collapsed) on the way in, and the
  words a model returns instead of leaving the field empty (`null`, `N/A`,
  `desconhecido`) are treated as empty rather than stored as types of their
  own.
- **A `desktop.ini` was item number one of an index of course material**,
  summarised as "operating system configuration file". Files the operating
  system and sync clients leave behind are skipped, by an explicit list
  rather than by a rule like "hidden files" — a collection can legitimately
  contain a document whose name starts with a dot.
- **The quality score punished the engine for being right.** The fill rate
  charged for an empty `date` on every item, and lecture notes are not
  dated documents: 15 of the 30 fill-rate points were lost for the correct
  answer, and 100 was unreachable no matter how good the classification
  got. `date` now counts only for collections that actually have dates (5%
  threshold, so one invented date cannot switch a whole collection into
  being graded on a field it does not have). `type` always counts. The
  summary also returns the score broken into confidence, fill and penalty —
  finding out that one empty field accounted for 30 of the 40 missing
  points had required querying the database by hand.
- **The VRAM planner made things worse when the model did not fit.**
  Measured on the same machine: with 4712 MB available it asked for 18 of
  43 layers, and Ollama went from placing 3108 MB of the model on the card
  to placing 1849 MB — the estimate replaced the scheduler's split with a
  worse one and slowed the run down. The per-layer cost here is the file
  size divided by the layer count, a rough figure, while Ollama knows each
  tensor's real size. The rule is now asymmetric: the plan overrides `-1`
  only when it can say with certainty that *everything* fits, and a split
  is left to the scheduler. Separately, VRAM already held by the model
  being sized now counts as available to it — without that, each run
  budgeted from a number that excluded the very model it was loading, asked
  for fewer layers, and ratcheted itself off the GPU.

### Added

- A warning when the chosen model cannot fit the card at all — the case
  where no setting helps and the answer is a smaller model. Found on the
  collection that prompted this work: an 8 GB RX 5700 XT running a 9.1 GB
  model with 17% of it on the GPU.


- **"Open existing project"** — there was no way to reopen a project whose
  folder this machine's catalog did not list, which is every case the
  shared catalog does not cover: a reinstall, a reformat, a different
  account, a folder that moved, a folder received from someone else. The
  output folder already *is* the project — its `project.db` holds the
  configuration, every file scanned, every page and every classified item —
  so the new screen reads that folder (with the database opened
  `mode=ro`, so inspecting a folder can never be what creates something in
  it), shows what it found, and adopts it unchanged.

- **`uninstall.ps1`** — the system had no uninstaller at all. It asks
  about each item separately and draws one distinction throughout: what
  this installation *owns* (the virtual environment, shortcuts, sensor
  DLLs, the unpacked Ghostscript, local settings, the `PATH` entries and
  environment variables it added) is removed on request; what it merely
  *installed* (Tesseract, Ghostscript, Ollama, Python, the downloaded
  model store) is a shared program that other software may depend on, and
  is offered one at a time with that said plainly. `-RemoveAll`,
  `-KeepDependencies` and `-WhatIfOnly` cover the non-interactive cases.
  It never deletes a project's output folder under any flag — it lists
  them, with sizes, and leaves the decision to the user. `install.ps1`
  creates a desktop shortcut for it.
- A "Shared catalog" section on the Projects screen, with the native
  folder picker, for pointing the project list at a Drive folder.
- A log event reporting how the GPU is being used for a classification run
  (`N of M layers on the GPU, X MB of free VRAM measured`) — the number
  behind the VRAM gauge, which Ollama does not report and the screen could
  not explain.
- 49 tests covering the eight items, the reopen path and the launcher (`tests/test_phase16.py`), including a
  regression for a defect found while validating this work against a real
  Ollama: a multimodal model publishes `gemma4.audio.block_count = 12`
  alongside `gemma4.block_count = 42`, and the audio one comes first —
  matching by suffix alone read the layer count of the audio tower and
  made every per-layer figure wrong by more than threefold.

## [Unreleased] — Phase 15: Hardware-Aware Installer and Optional Elevation

Goal of this phase: make the installer analyse the machine and install
what that machine actually needs, and give the CPU sensor a way to run
with the privilege it requires — without demanding it.

The phase began with the maintainer wiping the machine (Python 3.12, the
virtual environment, Tesseract, Ghostscript, Ollama, the GPU environment
variable and the desktop shortcut) so the installer could be tested from
zero for the first time. That test found more than it was meant to.

### Added

- The installer downloads the seven sensor libraries
  (`LibreHardwareMonitorLib` 0.9.6, `HidSharp` 2.6.4 and five .NET BCL
  shims) from nuget.org into `%LOCALAPPDATA%\GClaudeIndexer\lib`, with
  pinned versions and **SHA-256 verified before installing**. Nothing had
  ever installed these: they had been placed by hand, so anyone cloning
  the repository got no temperature, power or clock readings and no way
  to obtain them.
- **The installer installs Python 3.12 itself**, and continues in the same
  run. It was detecting the missing interpreter and printing a `winget`
  command for the user to run by hand — which is not installing. It now
  tries winget in *user* scope (no administrator, and the machine PATH is
  left alone so an existing `python` keeps winning), then the pinned
  python.org installer with its SHA-256 checked, then an elevated
  all-users install, and only then falls back to the printed guidance.
  Seeing the freshly installed interpreter in the same process needed its
  own work: `PATH` and the `py` launcher's registry are read when a
  process starts, so the installer reloads the PATH from the registry,
  reads PEP 514's `Software\Python\PythonCore\3.12\InstallPath` and checks
  the known install folders — running each candidate and asking its own
  version rather than trusting a key or a folder name. This machine had a
  stale registry key pointing at a `Python312` folder with no
  `python.exe`, which would have answered "found" for an interpreter that
  does not exist.
- Portuguese OCR language data. The project defaults to
  `ocr_language="por"`, but the Tesseract package ships only `eng` and
  `osd` — `ocrmypdf` failed with "does not have language data for: por".
  The installer now installs the configured language (pinned commit,
  hash-verified) into Tesseract's own `tessdata`. `-OcrLanguage` accepts
  others.
- Ghostscript, which nothing had been installing at all: the winget
  package (`ArtifexSoftware.GhostScript`) **no longer exists**. The
  version is pinned and the SHA-512 cross-checked against the
  `SHA512SUMS` file Artifex publishes with the release. How it is put in
  place changed later in this same phase — see "Ghostscript is unpacked,
  not installed" below.
- A post-install GPU check: the installer loads a model and reports what
  `ollama ps` says. When the GPU is not being used, it prints guidance
  for older AMD cards — links only, never an automatic third-party
  download.
- Optional elevation for the CPU sensor: a second shortcut,
  `GClaude Indexer (CPU sensor)`, passing `--cpu-sensor` to the existing
  launchers. Only `gclaude_indexer.sensor_service` runs elevated; the
  server does not. The installer offers this shortcut by asking, stating
  both what it gains (CPU temperature and power) and what it costs (a UAC
  prompt on every launch). `-AutoInstall` alone does not create it.

### Removed

- `gclaude_indexer/installer.py` and the ten tests that covered it. It was
  a second implementation of dependency installation, in Python, reached
  only from `launcher.py` — so the same job existed twice, and the copy
  nobody looked at was the one still running Ghostscript's installer with
  `/S` and a 900-second wait. `install.ps1` is now the single path:
  `Indexer.bat` already runs it when the environment is missing.
  `launcher.py` lost `_garantir_dependencias_externas()` along with it,
  and `log.installer.*` (27 keys across the three languages) went with the
  code that used them.

  Trade-off accepted: the app no longer silently reinstalls a dependency
  that disappears after setup. The About screen still reports it missing,
  and re-running the installer fixes it.

### Changed

- **Ghostscript is unpacked, not installed.** It now lands in
  `%LOCALAPPDATA%\GClaudeIndexer\gs` — beside the virtual environment and
  the catalogue — and its `bin` folder is added to the *user* PATH. The
  vendor's installer could not run unattended: it is manifested
  `requireAdministrator` (so every destination, `%LOCALAPPDATA%`
  included, raises a UAC prompt), `/S` no longer silences this build, and
  what it leaves on screen is a "Finish" page waiting for a click.
  Unpacking it instead needs no administrator, no window and no click:
  measured at 2.1 s for 649 files, with `gswin64c --version` answering
  0.2 s later, against ~93 s plus a prompt plus a click. The extractor is
  7-Zip's own MSI, unpacked with `msiexec /a` (an administrative install,
  which installs nothing) and pinned and SHA-256 checked like every other
  download here. Running the vendor's installer survives as the fallback,
  and there the wait is for the binary to answer `--version` — not for a
  process that never ends — after which the leftover window is closed by
  killing it. Bounded by a timeout that degrades with a warning.
- Hardware analysis now walks every display adapter instead of the first
  one, and reports what it did for NVIDIA and Intel instead of inventing
  an adjustment: neither needs one beyond what Ollama already does.
- The installer no longer writes `HSA_OVERRIDE_GFX_VERSION`, and removes
  it if present. Measured on an RX 5700 XT with Ollama 0.33.2: the model
  runs at **100% GPU, 66.9 tokens/s, through the Vulkan backend**, with
  ROCm never attempted. The unofficial ROCm library replacement that
  circulates for this card addresses an older Ollama that had only CUDA
  and ROCm; applying it now would overwrite Ollama's files with
  third-party binaries to replace a path that already works.

### Fixed

- `$ErrorActionPreference = "Stop"` turned any native command's stderr
  into a terminating error. This broke the installer in two places: the
  Python version check died before printing the guidance written for
  exactly that case, and `ollama list` — run seconds after installing
  Ollama, while its service was still starting — killed the script after
  installing everything and before the hardware analysis, the sensor
  libraries and the shortcut. **A from-zero install could not finish.**
  Both fixed through `Invoke-NativeCommand`.
- `installer.py` passed Inno Setup flags (`/VERYSILENT /NORESTART
  /SUPPRESSMSGBOXES`) to Ghostscript's NSIS installer, which ignores what
  it does not recognise and would have opened a window waiting for a
  human in the middle of an unattended install. Changed to `/S` — which
  was later measured not to silence this build either, so `install.ps1`
  stopped running that installer at all (see "Ghostscript is unpacked,
  not installed"). `installer.py` still carries the old approach; it is
  listed under "Known limitations" below.
- `Install-IfMissing` returned winget's output alongside its boolean, so
  `$GhostscriptOk` was always true and its warnings never appeared.
- Every "the installer returned code N" warning in `install.ps1` was dead
  code: `Start-Process -PassThru` hands back a `Process` object whose
  `ExitCode` stays `$null` for ever unless its handle is kept open.
  Reading `.Handle` once, right after launching, makes the exit code
  readable — measured before and after.
- The installer wrote `__pycache__` into the project folder, which is
  Google Drive-synced, against the spec's own rule. Fixed with `-B`; the
  root `conftest.py` turned out not to cover its own compilation either,
  so `PYTHONDONTWRITEBYTECODE` is now set in CI and `-B` documented in
  the contributing guides.
- The About screen would have offered to restore the very environment
  variable the installer had just removed.

### Known limitations

- **UAC refusal has never been exercised.** Elevation is proven, refusing
  it is not, and neither is the standard-account case where Windows asks
  for credentials. (The earlier note here said this machine has
  `ConsentPromptBehaviorAdmin = 0` and never shows a dialog; measured
  again in Task 5, it is **5** — the machine does prompt.)
- Not verified in practice: NVIDIA and Intel GPUs, AMD cards other than
  RDNA1, machines with no GPU, network failure during the downloads, and
  Ghostscript via winget (the package is gone).
- The Ghostscript fallback — the vendor's installer, run elevated — was
  tested against a stand-in that behaves like it (writes the tree, then
  hangs), not against the installer itself: exercising it for real needs
  somebody at the keyboard to approve a UAC prompt.
- `expected_sha256` for the Tesseract and Ollama downloads is still
  unpinned in `install.ps1` — no hash was written that had not been
  measured first.

## [Phase 14] - 2026-08-30 — Internationalization and Open-Source Preparation

Goal of this phase (from the plan): translate the whole project to
English — identifiers, docstrings, database schema, translation keys and
tests — remove development leftovers, and prepare the repository for open
publication under GPL-3.0 and for a distributable Windows installer.

### Added

- `LICENSE` with the full, verbatim text of the GNU General Public
  License v3.0.
- GPL license header at the top of every module in `gclaude_indexer/`.
- `CONTRIBUTING.md`, with Brazilian Portuguese and Spanish translations
  under `docs/`, and this `CHANGELOG.md` — English only, single version,
  following the Keep a Changelog convention.
- `README.md` rewritten as the repository's English entry point (with
  `docs/README.pt-BR.md` and `docs/README.es.md`), replacing the
  Portuguese-only `README.md` this phase started with — corrected against
  the current code wherever it had drifted (see "Fixed" below).
- `docs/SPECIFICATION.md`, the technical reference translated to English
  from the former `ESPECIFICACAO.md` and corrected against the current
  code (kept as a single, English-only document — an internal reference,
  not user-facing).
- `.gitignore` (the project has not used version control until this
  phase).

### Removed

- Development leftovers: an accidental empty `INSERT_PATH` file, the
  empty `_tmp_task7_check/` folder, and all `__pycache__/` directories.

### Changed

- The entire `gclaude_indexer/` codebase — identifiers, comments,
  docstrings — and the SQLite schema (`project`, `file`, `page`, `window`,
  `item`, `event`, `run`) translated to English, including every HTTP
  route, template context variable, CSS class/variable, and the
  classification engines' JSON wire format (`raw_items.jsonl`). The
  three-language (`pt`/`en`/`es`) interface via `i18n.py` is unaffected —
  only the *keys* moved to English; each language's own text is unchanged.
- The interface's default language is now detected from the Windows
  display language, overridable with the `GCLAUDE_INDEXER_LANGUAGE`
  environment variable.
- The four output artifacts (`index.md`, `timeline.md`, `review.md`,
  `project_instructions.md`) and the execution log's own messages are now
  generated in the interface's current language, re-translatable on read
  as well as on write.
- The test suite renamed `test_fase1.py`…`test_fase13.py` to
  `test_phase1.py`…`test_phase13.py`, plus a new `test_phase14.py` for
  this phase's own coverage.
- The installer, translated and renamed from `instalar.ps1` to
  `install.ps1` (messages, comments, and function/variable names included;
  the `-AutoInstalar` parameter is now `-AutoInstall`), together with
  `Indexador.bat`/`Indexador.vbs` renamed to `Indexer.bat`/`Indexer.vbs`
  and `iniciador.py`/`executar_servidor.py` renamed to
  `launcher.py`/`run_server.py`. Installer logic (Python/venv detection,
  the `requirements.txt` hash check, winget calls, GPU detection,
  idempotency) is unchanged — only names and user-facing text moved to
  English.

### Fixed (documentation)

- `README.md` and `ESPECIFICACAO.md` had drifted from the code before this
  phase renamed anything further: they still named `pecas_brutas.jsonl`
  (now `raw_items.jsonl`), `indice.md` (now `index.md`), `janelas/` (now
  `windows/`), `estilo.css` (now `style.css`), `projetos.json` (now
  `projects.json`), and several module/route names from before the
  translation work in this phase. Corrected throughout, along with the
  Python version requirement (`3.11+` was documented; the pinned
  dependencies actually require **3.12** specifically — newer interpreters
  break them).

### Security

- SQL column allowlist (`_NULLABLE_COLUMNS`) in both `_count_nulls`
  helpers in `quality.py`. There was no injection — the arguments are
  code literals — but a column name cannot be a SQL parameter, so the
  interpolation is unavoidable and the validation is what keeps user
  input from ever reaching it.
- `pip-audit` review of `requirements.txt`: **46 known vulnerabilities
  across 6 packages**, reported without changing any pin. Four are
  straightforward bumps (jinja2 3.1.4 to 3.1.6, python-multipart 0.0.12
  to 0.0.31, pillow 10.4.0 to 12.3.0, pytest 8.3.3 to 9.0.3); starlette
  0.38.6 has no fix compatible with `fastapi==0.115.0`, so it needs a
  FastAPI upgrade rather than a pin change. Left as a decision for the
  maintainer, since upgrading untested is how a working system breaks.
- `SECURITY.md` and `CODE_OF_CONDUCT.md`, plus GitHub issue and pull
  request templates.

### Continuous integration

- `.github/workflows/tests.yml`: the suite on `windows-latest` with
  Python 3.12, with a comment explaining why there is no Linux job (the
  project uses PowerShell, WMI and the registry). Installs Tesseract and
  Ghostscript via Chocolatey and downloads `por.traineddata` separately —
  neither package ships it, and the three real-OCR tests need it.
  **Nothing in the suite is excluded from CI.** The workflow itself has
  not been run on an actual runner: the project had no git repository
  when it was written.

### Fixed (final verification)

The end-to-end verification ran the whole system rather than the suite,
and found five defects that 319 passing tests did not:

- `projeto.lock` persisted Portuguese JSON keys (`maquina`, `usuario`,
  `criado_em`, `atualizado_em`) into every project's output folder — the
  one piece of persisted state the translation mandate had missed. Now
  `project.lock` with English keys.
- The `importacao` step tag was never added to `STEPS` or to the
  translation table, so it leaked raw into the live log on every real
  run, in all three languages. The same was true of `diagnostico`, found
  while looking for siblings. Both now render translated, through a
  `LOG_KNOWN_STEPS` display list kept separate from `STEPS`.
- Configuration validation errors were built as fixed Portuguese strings
  and shown regardless of interface language. `ConfigError` now carries
  `ConfigErrorMessage(key, params)`, rendered by the display layer.
- The About screen's GPU and sensor diagnostics were hardcoded Portuguese
  sentences, and `sensors.unavailable_reason()`'s raw code leaked
  untranslated into the page.
- The lock and sync screens showed messages built in Portuguese in
  `lock.py` and `sync.py`. Both results now carry `message_key` and
  `message_params`.
- 45 of 64 template `id=` attributes, most inline JavaScript identifiers,
  and the Jinja block and macro names were still Portuguese — invisible
  because the visible text was already correctly translated.

### Verified

- Full pipeline over a 6-PDF collection (one image-only, requiring OCR):
  7 stages, 7 items classified at high confidence, 4 artifacts generated
  with real content.
- All 16 theme x layout combinations plus the three languages, with no
  raw translation keys, empty titles, overflowing tables or console
  errors.
- The suite ran twice with no flakiness.

### Known limitations

- Projects created before this phase will not open: their stored
  `processing_mode` and `group_mode` hold Portuguese values, and
  validation rejects unknown values rather than falling back to the
  default, so the screen returns HTTP 500. No compatibility shim was
  written — the maintainer had confirmed the existing collections were
  disposable test data.
- The `_PROMPT` sent to the local model and the generated `CLAUDE.md`
  remain in Portuguese on purpose. The JSON keys they ask for were fixed
  to English and validated against a real model, so the wire format no
  longer varies with the interface language; the prose has not been
  translated, which still ties the `local` engine's quality to
  Portuguese-language collections.

## [Phase 13] - 2026-08-29 — GPU, Quality and Layouts

Goal (from the plan): make the system install itself on any machine using
whatever hardware it finds; monitor the whole machine regardless of GPU
vendor; and allow comparing engines and models by time and quality, with
four genuinely distinct interface layouts.

### Added

- GPU and VRAM usage detection for any vendor (not only NVIDIA).
- CPU, memory and GPU clock monitoring.
- Temperature and power sensors via LibreHardwareMonitor.
- A quality report generated at the end of a run.
- Four selectable, genuinely distinct visual layouts, with the
  infrastructure to support them.
- An installer that sets up a new machine unattended, adapting to the
  hardware it detects.
- Parallelism in conversion/OCR and extraction — the largest single
  performance improvement of this phase.
- A benchmark comparing engines and models side by side by time and
  quality.

### Changed

- The resources panel now surfaces all collected machine metrics (CPU,
  RAM, GPU, temperature, power, clocks) in one place.
- The live log view no longer auto-scrolls while the user has scrolled up
  to read earlier entries.
- The model selector (for the `local` engine) now actually takes effect.
- The scan progress bar reaches 100% correctly even when duplicate files
  are present.

### Fixed

- The "All" file-extensions option is now mutually exclusive with
  specific extension categories in the New Project form (previously both
  could be selected at once, with "All" silently taking over).

### Removed

- The `openrouter` classification engine, removed entirely.

## [Phase 12] - 2026-08-28 — Interface Fixes

Goal (from the plan): fix the 12 interface defects found during the first
real use of GClaude Indexer v1.0 — status internationalization, progress
bar behavior, form and theme readability, and cleanup of intermediate
files.

### Added

- A discovery step for installed Ollama models, feeding the model
  selector.
- Four selectable visual themes.
- Cleanup of intermediate files left behind in the output folder.

### Changed

- Step/run status is now represented by stable, ASCII, language-neutral
  keys (`estado_etapas.py`) instead of accented Portuguese text used
  simultaneously as display text, CSS class and comparison value — the
  root cause of several of the 12 defects, including a bug where
  translating the status text broke the "run next step" button.
- The progress bar keeps showing the last known state ("done", "paused",
  "error") instead of disappearing the instant a step finishes.
- The scan step's progress total now respects the file extensions
  selected for the project, instead of counting every file in the source
  folder.
- The progress bar shows the translated step title instead of the raw
  internal step key.
- The live log view shows up to 200 lines (up from 50), adds a filter by
  level (info/warning/error), and keeps the view pinned to the latest
  line while "follow the tail" is checked.
- File extensions in the New Project form are grouped by family (documents,
  images, text/data, messages), showing which extensions each category
  covers, instead of a single alphabetically sorted row.
- Classification engine descriptions in the New Project form made
  readable.

### Removed

- The dispensable "machine switch" banner.

### Fixed

- Remaining language leaks in the interface (untranslated strings still
  reaching the screen in non-Portuguese languages).
