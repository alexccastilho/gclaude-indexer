# Changelog

All notable changes to this project are documented in this file. The
format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

The oldest entries are grouped by development phase rather than by
semantic version: the reported application version (`SYSTEM_VERSION` in
`web/app.py`) stayed `1.0.0` from phase 1 through phase 16. `1.0.1` is the
first bump, and it releases everything the phase 16 block below had been
carrying as unreleased.

## [1.10.3] - 2026-11-13

### Fixed

- Reading the pages stopped with `UNIQUE constraint failed: page.file_id,
  page.number` when a document changed in the source folder and the steps
  were run from the Execution screen without "Update" first. The scan sent
  the document back to the queue but kept its old pages, search passages
  and windows. The scan step now applies the same invalidation as the
  "Update" button to new and changed documents. Removed documents still
  leave the index only after you confirm it on the update screen.
- A project already left in that state is repaired by itself on the next
  "Run everything up to classification" or "Resume": the affected documents are read again
  with their new content. Nothing has to be done by hand.

## [1.10.2] - 2026-11-04

### Changed

- Documentation, comments and tests revised: every example now uses
  fictitious names and data. No change in behaviour.

## [1.10.1] - 2026-11-04

### Changed

- Authors: the same name written with and without accents ("ANTONIO
  PEREIRA" and "ANTÔNIO PEREIRA") now gets one spelling in the whole index,
  for every engine, not only for the Planalto acts. Mixed case still wins
  over capitals, and an accented spelling wins when it appears at least
  half as often as the unaccented one. Takes effect on the next "Import
  and generate reports"; nothing is classified again.
- Social preview image of the repository redone with the Studio dark
  colors, the bundled fonts and a screenshot of the Workspace layout.

### Security

- Code scanning with CodeQL (advanced setup): Python, JavaScript and the
  GitHub Actions workflows, with the `security-and-quality` query suite,
  on every push, every pull request and once a week.
- Dependency review on pull requests: a new dependency with a known
  vulnerability or an incompatible licence blocks the change.
- Every workflow now runs with a read-only token by default.

### Removed

- Internal planning notes of past phases (`docs/superpowers/`), unused
  functions and imports, and version and phase markers left in code
  comments. No behaviour changes.

## [1.10.0] - 2026-11-03

A new look, chosen among three proposals: the Workspace layout, with its
own palette, the Studio theme.

### Added

- Workspace layout, now the default: a side bar with the main screens and
  every project (with a status dot), a top bar showing where you are, and
  tabs for the five screens of a project (Execution, Result, Search, Update
  collection, Instructions).
- Command palette: Ctrl+K (or "Search or run" in the side bar) finds any
  screen, any project's screens and the theme, layout and language
  preferences by typing part of a word, accents optional. It only navigates
  and changes preferences; it never starts work. Keyboard and screen reader
  friendly (dialog, listbox, arrows, Enter, Esc).
- Studio and Studio dark themes: warm neutral grays and a single teal
  accent. Studio is the default for whoever never chose a theme.
- Inter and JetBrains Mono fonts shipped with the program (SIL Open Font
  License, files in `web/static/fonts`), so it still works offline.
- On the Execution screen, the step that is running is highlighted.

### Changed

- The layout preference has a new cookie: whoever used another layout sees
  the Workspace once after updating, and can go back under Preferences. The
  chosen theme is kept. The previous layouts (Default, Technical,
  Editorial, Compact) and the eight previous themes are all still there.
- The side bar never opens a project database: its status dots come from
  what the Projects screen already computed.
- README screenshots and walk-through GIFs redone with the new look, in the
  three languages.

## [1.9.2] - 2026-11-03

People who had instructions before the automatic block existed often copied
its sections into their own part by hand. The block was then appended below
and Claude got everything twice, with the copy's counts frozen ("120000
pages") while the block's were updated.

### Added

- Generation recognizes a copy of the block in the user's part of
  `project_instructions.md`: sections whose text is mostly the block's
  (compared word by word, ignoring accents, case, dashes, colons, numbering
  and numbers), in any of the three languages, plus lines with counts that
  change on every indexing. The user's text is never changed there: a
  notice goes at the top of the block and in the log, and the Execution and
  Result screens link to the review.
- On the Project instructions screen: the repeated sections, the lines with
  counts, the "section 4" style references that would point to the block,
  and the passages of the user's own that talk about the collection.
  "Remove the repetitions" takes the copies out (previous version in a
  stamped `.bak`), points those references at the block and moves the
  ticked passages to the project's extra rules, which appear inside the
  block. "Keep as it is" only records the choice. Both are logged.

### Fixed

- A file with no marks whose user part carried a hand copy of the
  non-negotiable rule was taken for a file written whole by an old version
  and replaced (kept only in the `.bak`). Now every section of the file has
  to be one the program writes.

The first generation after updating adds the notice to the block of a
project that has a copy, so the file changes once and needs to be pasted
into the Claude Project again.

## [1.9.1] - 2026-11-03

What was left for later in 1.9.0, done now: faster navigation on projects
stored on Google Drive, and the author defects found in a large collection.

### Changed

- The screens that only read (Execution, its periodic refreshes, Result)
  keep one read-only connection per open project (`web/readers.py`), so
  SQLite's page cache survives between requests. It is reopened whenever
  `project.db` changes on disk (for example, Google Drive bringing the
  other computer's copy), closed after two minutes without use, and closed
  when the project is closed, deleted or taken over. Steps, imports and
  updates keep their own writing connections.
- The Projects screen no longer opens every project's database on each
  visit: the summary of each project is kept while `project.db` is the
  same file (size and modification time).
- Checking for changes in the collection reads the `file` table once
  instead of twice, and a new file is only read whole (to look for a
  duplicate) when another file has exactly the same size.
- The log estimates `qwen3.5:9b` at its own size (about 6.3 GB) on a
  first run, before the model is downloaded, instead of the 4b's 3232 MB.

### Fixed

- An author, date, type or summary that only said "null", "N/A", "-" or
  similar was printed as text in the index; it is now empty.
- The same author written in different case by the local model ("LUIZ
  INÁCIO LULA DA SILVA" and "Luiz Inácio Lula da Silva") now has one
  spelling, the most frequent one in mixed case. Names only ever written
  in capitals are left as they are.
- A norm cited as the author ("Lei nº 9.394/1996", "Decreto 7.892 de
  2013") is no longer shown as the author.
- An item that ran into the first page of the next one (a "PÁGINA EM
  BRANCO" f. 14-15 followed by an item starting at f. 15) now ends on the
  page before it. An item wholly inside another is left as it is.

These fixes apply the next time "Import and generate reports" runs;
nothing is classified again.

## [1.9.0] - 2026-11-03

A user confirmed a collection update without pasting the instructions and could
not stop it: the browser's Stop only dropped the answer, the server kept
working, and the next click said "busy with: Update". At the end, the screen
did not go back to Execution on its own. They also reported that opening a
large project or generating reports left the screen frozen with no notice,
that the progress bar was unreadable in dark themes, that switching the theme
in the middle erased it, that navigation was slow, and that About did not show
the graphics driver version.

### Fixed

- **Stop any long operation.** "Update" and "Import and generate reports" run
  in the background, and a panel in the middle of the screen shows what is
  running, the elapsed time and a Stop button. Stopping writes nothing halfway:
  the update goes back to the state before the click, and in a report
  generation each file is either the old or the new one, with the log saying
  which changed. The "project busy" page has the Stop button too.
- **Goes to the next screen on its own.** When the operation ends, the screen
  moves to Execution (after an update) or Result (after a generation), even if
  you reloaded the page or switched tabs in the middle.
- **A readable "please wait" notice in every theme.** The yellow bar at the top
  used a background colour no theme defined, with the theme's white text on
  it. The new panel uses the theme's own surface and text colours.
- **Switching the theme or the layout no longer reloads the page** and no longer
  erases the panel. Switching the language reloads, and the panel comes back
  with the right time, because the server says what is running.
- **Slow screens say so.** Opening a large project, or any screen that takes a
  while, shows "Loading, please wait" with a clock instead of a frozen screen.
- **About** shows the installed graphics driver with its release date, for
  example "driver 621.01 (32.0.16.2101), released 2026-10-18". NVIDIA cards
  also show the number NVIDIA advertises.
- **No em dashes on screens or in the manual.** The texts were rewritten with a
  comma, a colon, a period or parentheses. Index and timeline files do not
  change because of this.

### Added

- **"Project instructions" screen**, linked from Execution and Result: shows
  your part of `project_instructions.md` so you can fix it or paste the current
  version from the Claude Project at any time, without updating the
  collection. The part the program generates is shown below it, read only, and
  each save keeps the previous one in a dated `.bak` copy.
- Visual polish: Windows 11's own fonts, headings with more presence, section
  titles without capitals, fields and buttons that respond to focus and click,
  shadows in the theme's colour, the current screen marked in the menu, and a
  "Skip to content" link. Each screen's entrance is shorter, so it does not
  feel like a delay.

### Performance

Measured on a large project stored on Google Drive:

- **Result**: took tens of seconds on every visit. Now only the first visit after
  a change does the counting, and the next ones are almost immediate. Quality, pending items and the run comparison are only recomputed when
  items, windows or pages change, and the pending items are computed once. The
  size of the intermediate files comes from the folder listing itself.
- **An idle Execution screen no longer reads the database every 2 s.** With
  nothing running, the steps table and the progress box are reused for up to
  30 s; anything that starts or ends refreshes both at once. While something
  runs, nothing changes. The five file counts became one.
- **Source folder check**: computing the relative path, most of the time of the
  walk, became a text slice with the same result. A confirmed update no longer
  walks the folder a third time.
- **About** keeps the installation check for 5 minutes.
- Refreshing the usage lock, a write to Drive every minute, no longer holds the
  other screens while it writes.

### Not changed

- `project_instructions.md` changes once on the first generation in 1.9.0 (the
  generated section's title and the block mark lost their em dash): paste it
  into the Claude Project again. Indexes and timelines do not change.
- The "Run everything" steps keep their own progress box and Pause button.

## [1.8.1] — 2026-11-03

A user added documents to a large collection, opened the project and saw no
sign that the program had noticed them. It had the means: the update screen
("Update collection") has listed new, changed and removed documents since
phase 17. The check behind its notice took minutes on a collection of that
size on Google Drive while the Execution screen showed nothing.
The same request asked that the user's Project instructions be updated, not
replaced, and that only the new indexing change the output files.

### Fixed

- **The "the source folder changed" check takes seconds, not minutes**
  (`scanning.walk_source_stats`, `update_plan.detect_changes`). The folder
  listing on Windows already carries each file's size and modification
  time; the check discarded them and asked the drive again, one file at a
  time. On a large collection: seconds instead of minutes, with the listed
  times identical to the stored ones on every unchanged file, so
  nothing is hashed again. The scan step uses the same values and is faster
  for the same reason.
- **The Execution screen says it is checking.** While the check runs, the
  notice area reads "Checking the source folder for new, changed and removed
  documents…" instead of staying blank.
- **The generated instructions no longer contradict the user's.** When
  `project_instructions.md` holds the user's own instructions, the generated
  part is now one section of their document ("Collection indexed by GClaude
  Indexer"), one heading level down, with the collection's numbers, files,
  columns and rules, and without a second title or the generic "Role". A
  project could have hundreds of lines of its own instructions followed by
  "you are a research assistant". Without instructions of the user's, the file is as
  before.

### Added

- **The update screen asks for the current Project instructions.** A field
  comes filled with the user's part of `project_instructions.md`; if the
  instructions were changed in the Claude Project, the user pastes the
  current version there. It replaces only the user's part, kept exactly as
  pasted, with all customizations; the generated section stays and is
  refreshed on the next generation. A pasted text that includes the
  generated section keeps only what is outside it. The previous file is kept
  as `project_instructions.md.<date-time>.bak`. An empty or unchanged field
  changes nothing.
- **Only the output files that changed are rewritten.** Each generation
  compares what it would write with what is on disk, ignoring the generation
  date, and leaves identical files untouched. The log then names the files
  that changed — the ones to send to the Claude Project again — or says that
  none did. Adding a document to one group rewrites that group's index, the
  summary and the timeline, not the other groups' indexes. The index of a
  group that left the collection is deleted, and the log names it as well,
  so it can be removed from the Claude Project.

### Not changed

- Detection of removed documents, removed folders and new folders already
  existed and is unchanged; 1.8.1 adds tests for a whole new folder and a
  whole removed folder, compared with indexing the same collection from
  scratch.

## [1.8.0] — 2026-11-02

Phase 38. Two requests from the user, plus two findings of the same day.
The requests: several collections inside one Claude Project without name
collisions, and documentation a person outside IT can read. The findings:
the package of a large project carried `legislacao-<group>.md` files of
tens of megabytes (millions of tokens) that no Project accepts, while the
budget "only informed, never blocked"; and a question such as "which acts
deal with sanitation" needs full-text search, not a list of links. The classifier,
the prompt, the rules and the pipeline are unchanged.

### Added

- **Sets** (screen `/sets`, `gclaude_indexer/sets.py`,
  `gclaude_indexer/combined_package.py`): a named selection of two or more
  projects plus the user's own Project instructions, kept in the machine's
  local catalog. The combined package prefixes every file with the
  project's alias (`<alias>__index.md`, `<alias>__index-<group>.md`,
  `<alias>__timeline.md`, `<alias>__review.md`), rewrites the links between
  summaries and group indexes to the prefixed names, including labels
  inside backticks and indexes split in parts, and writes a single
  `project_instructions.md`: the personal text at the top, outside the
  managed marks; inside them, the role once, one section per collection and
  a "which collection to search" rule. "Write to the folder" produces the
  same files plus a combined `CLAUDE.md` for Claude Code, refuses a
  project's own source or output folder, and removes prefixed files of
  projects that left the set. The output folders of individual projects do
  not change, so existing Projects and `CLAUDE.md` files keep working.
- **`normas-citadas.md`** in the output folder and in the package: one line
  per federal act recognised in the collection (kind, number, year, short
  ementa when found, link to the text on LexML, group and pages where it
  appears). A few KB even on a collection with a full Planalto mirror. The
  generated instructions now say that legislation is not in the Project's
  knowledge: read this file to know what exists, follow the link to read
  the text, ask the user for a topic search.
- **Topic search for Claude Code**: `tools/buscar.py`, and a `buscar.bat`
  written in the output folder, query the project's database with the same
  FTS5 engine as the "Search the collection" screen and print, in Markdown,
  the acts and pages that cite a term, with excerpt, source file and
  LexML link; options `--grupo`, `--so-legislacao`, `--limite`,
  `--lexml`. The output folder's `CLAUDE.md` tells Claude Code to use it
  for thematic questions.
- **LexML** (`gclaude_indexer/lexml.py`): when a term appears in no act of
  the collection, or on request, the search queries the public SRU service
  of LexML and lists the acts found as "outside the collection". It is the
  one call that leaves the machine, it sends only the typed term, and it
  never runs during indexing. As checked: the service answers
  programs with the Senate's "security check" page; the client recognises
  that page (an HTML document, or the mark inside `<title>`, never an
  ementa that happens to contain the words), says so and gives the link to
  open in the browser. Getting around the check is not an option. The
  "Search the collection" screen has the same "Also search LexML" box.
- **A budget that protects** (`gclaude_indexer/claude_package.py`):
  `MAX_FILE_BYTES` (30 MB, the Project's per-file limit at the time of
  this release) and `RAG_THRESHOLD_TOKENS`. A file above the per-file limit
  never enters the package, simple or combined; the screen shows it in red
  with its size and what to do. Above the total, the screen lists what fits
  and what is left out, and the download button warns before generating. A
  group index has come out in parts of up to 25 MB since 1.6.0
  (`INDEX_PART_BYTES`); what changes is that a single source file whose
  index alone exceeds 30 MB stays out of the package, and the screen says
  which.
- **Media retaken on 1.8.0**: `docs/media/demo-{pt,en,es}.gif` and 21
  screenshots over `demo/acervo` with the rules engine, window 1366 px,
  light theme, the CPU temperature, fan and power read by the elevated
  helper visible on the Run screen; new `search-*.png` and `sets-*.png`.
- **A language test** (`tests/test_phase38_docs.py`) over README ×3,
  manual ×3, `demo/README.md`, `tools/README.md` and `docs/TECHNICAL` ×3:
  no em or en dash as an aside, straight quotes, no ellipsis character, no
  word from the inflated-vocabulary lists (pt, en, es).

### Changed

- **README ×3 rewritten for people outside IT**: one sentence on what the
  program is, three people who use it, what you receive (with the
  screens), what you need, ten minutes to try it, how much it gets right
  (the numbers of `docs/QUALITY.md`, one sentence each), privacy, several
  collections, legislation and search, teamwork. Each README is shorter
  than before. Every technical detail moved to the new
  **`docs/TECHNICAL.md`**, **`docs/TECHNICAL.pt-BR.md`** and
  **`docs/TECHNICAL.es.md`**, which keep the sixteen topics of the old
  "Technical details" section and add sets and search.
- **Manual ×3 rewritten** under the same rules, 22 sections, with new
  sections on the demo collection, what to expect in accuracy, sets, cited
  acts and search, the sensors and the administrator request, pause and
  resume, and updating the program. The New-project field list matches the
  screen (the package token ceiling is not a field).
- **CONTRIBUTING ×3** (one commit per task, CI indexes the demo collection,
  the documentation rule, how the Windows installer is packaged),
  **SECURITY**, **CODE_OF_CONDUCT**, **QUALITY ×3**, **SPECIFICATION**
  (`normas-citadas.md`, `buscar.bat`, sets, the seven screens), the GitHub
  issue and pull request templates, the repository description and topics,
  and the social preview (`docs/media/social-preview*.png`, generated by
  `docs/social-preview.py`).

### Removed

- **`legislacao-<group>.md` and the "Planalto legislation in the package"
  option** (`planalto_in_package`, phases 31 to 37). The file copied the
  text of every act recognised; on a collection with a Planalto mirror it
  reached tens of megabytes that no Project accepts, and the same text is
  one link away. Projects that still have the file in the output folder
  lose it at the next generation, as with any orphan. The key stays
  written in the `config_json` of every project created up to 1.7.5 and is
  ignored on load, so those projects keep opening. The recognition of
  federal acts (`planalto.py`) and the indexing of `.htm` pages as pages of
  the collection are unchanged.

### Fixed

A step's background task was marked as finished before the `run` row got its
`finished_at` and `ok`: whoever read the database at that instant (the
"Compare engines and models" table on the Result screen, the phase-13 test)
saw the run still open and the comparison came out empty. Seen once on the
GitHub runner (1 failure in 1204, suite at 9 min) and once locally
under load. The flag now flips only after the commit.

Six corrections from the independent review of part A: the link rewriting
in the combined package reaches labels inside backticks and the index in
parts; saving a set keeps a member that is temporarily unavailable instead
of dropping it in silence; writing a set into a project's own folder is
refused with a message; regenerating a set into a folder removes the
prefixed files that left the set; the LexML client no longer mistakes an
ementa that contains the challenge words for the verification page; the
summary of a revoked act without an ementa falls back to its parts instead
of an empty line.

## [1.7.5] — 2026-11-02

Phase 37. After an honest assessment of the project, the user asked for
three proofs anyone opening the repository can check: "CI, a quality
measure and a demo collection". Nothing in the classifier, the prompt or
the rules changed in this phase; it measures what exists.

### Added

- **Demo collection** (`demo/acervo`, 72 pages, 41 pieces, 7 files):
  two bound PDF volumes of a fictional administrative process, a contract,
  a Word memo, an Excel sheet, a scanned PNG and an e-mail, generated by
  `demo/gerar_acervo.py` from a single list of pieces and versioned with its
  answer key, `demo/gabarito.csv` (piece, type, date and author of every
  page). Everything is invented: the town, the people, the company, the
  CNPJ and the process number (both invalid on purpose). `demo/README.md`
  and a "Try it in ten minutes" section in the three READMEs.
- **Accuracy against an answer key** (`gclaude_indexer/answer_key.py`,
  `tools/medir_acerto.py`): page coverage, pieces found by Jaccard ≥ 0.5
  on page sets (precision, recall, F1), and type, date and author among the
  pieces found, per group and in total, with the list of mismatches as a
  Markdown report. The "Quality" screen measured declared confidence; this
  measures correctness.
- **`docs/QUALITY.md` ×3** with the numbers of this machine (RX 6700 XT,
  Ollama 0.40.13). Rules engine: coverage 100%, boundaries F1 86.7%, type
  94.4%, date 50.0%, author 19.4%, 4 s. `qwen3.5:9b`: coverage 100%,
  F1 66.0% (it mostly returns one piece per page), type 60.0% under exact
  comparison (80% accepting more specific names such as "PARECER
  JURÍDICO"), date 88.6%, author 84.4%, 4 min 12 s. The document says what
  each number means and does not mean.
- **CI proves the product**: `tools/indexar_pasta.py` runs the five steps,
  the import and the artifacts with no interface; the GitHub run indexes the
  demo collection with the rules engine on every push, fails if any page of
  the key is left out of the index, and attaches the accuracy report and the
  index to the run. Tests badge at the top of the three READMEs.

### Fixed

- **The test suite no longer reaches the developer's real Ollama.** It
  used to send hundreds of 404s with fake models to `127.0.0.1:11434`, the
  About screen's `ollama --version` asked the real server for its version,
  and — once the port was closed — the restart path launched a real
  `ollama serve` that stayed orphaned, serving the fake models. The suite
  now points the engine, the CLI (`OLLAMA_HOST`) and the launcher at a
  closed port, for the whole process; proven with the server up: 339 tests,
  zero new lines in `ollama-serve.log`, no extra process.
- **The test suite stopped the machine's real Ollama.** A phase-19 test
  proved that the uninstaller's `Stop-OllamaProcesses` survives an absent
  Ollama by calling the real function — which stops every process named
  `ollama` on the machine. The model server died twice
  in the middle of a classification and once more while the suite ran; a canary that
  checked for the process after every test found the culprit in one run.
  The test now hides the processes from the function, and a guard test
  keeps a look-alike `ollama.exe` alive through it.

## [1.7.4] — 2026-11-02

Phase 36. The user asked for the program to use everything the machine
has, automatically, on any hardware — "the fastest result that still
guarantees the best information in the index". Measured on the same
hardware as 1.7.3 (RX 6700 XT 12 GB, Ollama 0.40.13, qwen3.5:9b).

### Fixed

- **Windows larger than the context are no longer cut in silence.** Some
  requests in the run were windows of over 20 thousand tokens that Ollama
  cut to 8194 before the model saw them; the `rows < pages` guard
  then split the window, so the index lost nothing, but each one had
  paid a ~70 s attempt that could not succeed. The request now carries
  `truncate: false` (Ollama 0.40 answers HTTP 400 with the exact token
  count instead of cutting), a refusal or the old cut signature counts
  as a failed attempt — never as an answer — the context grows to what
  the window needs and the whole window is sent again; only when even
  the ceiling is not enough is it split, and a window whose estimate
  already exceeds the ceiling is split before any request is made.
- **"cpu" mode and machines without a card now send `num_ctx`.** That
  path returned before sizing the context, so Ollama's 4096 default cut
  every full window.

### Added

- **Context ceiling computed from the hardware.** Instead of a fixed
  list that stopped at 16384, the ceiling is the largest multiple of
  4096 whose KV cache fits on the card next to the whole model, the
  safety margin and the runner's compute buffers (measured ~400 MiB),
  capped at 131072 and the model's own limit; on the CPU, the same
  calculation over free RAM, capped at 32768. The KV cost counts only
  the layers that keep a cache (qwen3.5: 8 of 32 — the old all-layers
  count was 4× too high: 1 GiB computed against 272 MiB allocated).
  Here it goes from 16384 to 131072, and the 26k-token windows fit whole
  (`size_vram == size` measured up to 49152). A model whose metadata
  does not give the KV cost keeps the old 16384 on the card. The cache
  type the ceiling is sized for is the one the server really uses: with
  flash attention off, f16, whatever the variable says.
- **The log says which backend is in use and why not a better one**:
  "Graphics card in use: AMD Radeon RX 6700 XT (12.0 GiB), via Vulkan",
  that Ollama serves this model family one request at a time, and — on
  AMD RX 5000/6000 — that ROCm is out of reach because the driver ships
  no `amdhip64_7.dll` (any other AMD card with an old driver is told to
  update it, which does bring ROCm there). Read from the server logs
  only; nothing is forced.
- **Flash attention off on Vulkan over AMD RX 5000/6000.** Measured on
  the same two windows: prompt reading 735 against 373 tokens/s (2×),
  generation −5%, a window 23–28% shorter; with flash attention on and
  an f16 cache the speed did not move, so the cause is flash attention
  itself on this card. The server this program starts, and the
  installer on these cards, set `OLLAMA_FLASH_ATTENTION=0` and
  `OLLAMA_KV_CACHE_TYPE=f16` (Ollama only quantises the cache with flash
  attention on). A value the user set by hand still wins; a value the
  installer itself wrote gives way; the uninstaller removes either. Two
  limits of that rule: a value typed by hand that happens to equal the
  installer's is indistinguishable from it; and a quantised cache type
  the user pinned stays in the environment but, with flash attention
  off, the server runs f16 — the ceiling is sized for f16. On any other
  card an `OLLAMA_FLASH_ATTENTION=0` set by hand is left alone.
- **Per-window log entries** when a window needed more context than the
  run started with or was split by size, and a one-line summary of the
  step with the ceiling.

### Measured and left out

- Parallel windows: 0.81× with two, 1.00× with three — Ollama pins the
  `qwen35` family to one request. Deferred to a later phase with its own
  measurement; the design is in `docs/superpowers/specs/`.
- `num_batch` 2048 against 1024: −2%.
- ROCm on the RX 6700 XT: impossible on the current AMD driver.

## [1.7.3] — 2026-11-02

Two findings from the first run of 1.7.2 on a large collection, both
about memory that looked wrong and was not.

### Fixed

- **Ollama's runner no longer keeps an 8 GB prompt cache in RAM.** The
  model was entirely on the card (33 of 33 layers, 52 tokens/s), yet
  `llama-server` held 16 GB of system memory, which read as the model
  spilling out of the card. Eight of those were the prompt cache
  llama.cpp keeps in RAM by default (8192 MiB), meant to pick an earlier
  conversation back up — and never used here: every window is a new
  prompt, and every window started with nothing reused (the rest is
  the model file mapped in memory, which Windows reclaims when needed).
  The server this program starts, and the user variables the installer
  writes, now disable it (`LLAMA_ARG_CACHE_RAM=0` — a user-wide
  variable, so a llama.cpp server run by hand skips that cache too; the
  uninstaller removes it). When the installer changes these settings
  it also stops Ollama's own `llama-server`, which can outlive a stopped
  server and keep holding the card.

### Added

- **"Model on the card" among the GPU sensors.** The VRAM figure is the
  whole desktop's (2.4 GB of the 9.2 GB measured were the browser, the
  compositor and other programs); the new line comes from Ollama itself
  and says what matters: "qwen3.5:9b: 100% (5638 / 5638 MB)".

## [1.7.2] — 2026-11-02

Everything below came out of one run of a collection on 1.7.1, and every fix was checked against the rule that the program has to
work on any computer — any graphics card, or none.

### Fixed

- **OCR of scanned PDF pages works again.** The private Tesseract data
  folder (`%LOCALAPPDATA%\GClaudeIndexer\tessdata`, since 1.5.19) held
  the languages but not the `configs/` folder, and ocrmypdf asks
  Tesseract for its `hocr` and `txt` outputs by those config names:
  every scanned page failed with exit code 15 (some PDFs not prepared and
  others left partial; images were fine because pytesseract asks for no
  config). The folder now also receives `configs/` and
  `tessconfigs/` — copied from Tesseract's own folder, or the four
  essential ones written when no source has them — and an existing
  folder is repaired on the first conversion after updating. A data
  folder without them is never taken as ready. The affected pages are
  already marked for a new OCR attempt; the next conversion picks them
  up.
- **"Update" redoes the files whose OCR failed.** Once a project has
  classification windows, the conversion's own retry holds those files
  back (redoing them alone would leave the windows with the old blank
  pages) and points to the project update — which only looked at changed
  bytes. The update now treats a file with a failed OCR as changed: its
  group's windows are discarded and it goes through OCR again.
- **Image OCR no longer depends on how the program was started.** The
  conversion itself puts the Tesseract folder on this process's `PATH`;
  before, only the server did it at start-up, and a conversion run any
  other way failed every image with "tesseract is not installed".
- **Pause answers at once, and there is a Continue.** Clicking Pause
  during the model load left the screen unchanged for over a minute (the
  request is only read between windows) and, once stopped, the button
  simply disappeared. The progress box now says "stopping" the moment
  you click, and shows a **Continue** button when the step has stopped —
  it resumes exactly where it left off. A pause that lands in the
  instant between two steps of "run everything" now reaches the chain
  too, instead of being ignored.
- **The total VRAM is the card that is installed.** Windows keeps the
  driver key of a card that was removed; summing every key reported
  20448 MB for a 12 GB card, and the classification's "free VRAM" was
  inflated by the same amount. The total now follows the video
  controllers actually present, so swapping cards, or having none, is
  read correctly on every start. On a machine with an integrated and a
  dedicated GPU the diagnostic names the one with the most memory, and
  the VRAM it counts on is that card's alone — the model runs on one
  card, and summing both used to recommend a model the dedicated card
  could not hold.
- **CPU clock on a Windows in any language.** The frequency counter was
  looked up by its localized set name, which matched only English and
  Portuguese; a Spanish Windows never showed it. It now comes from a WMI
  class whose name is never translated.

### Added

- **VRAM in use among the graphics card's sensors** on the Execution
  screen (user request), read from the card itself — the same number as
  the line under the GPU chart.

## [1.7.1] — 2026-11-02

### Fixed

- **The activity bar survives a reload in every long operation.** Update,
  delete, index the search and clear intermediates now hold the project's
  slot like "import and generate" does, under the same name as the button
  that started them — a page reloaded in the middle resumes the bar with
  the real elapsed time. Any of these four, started while the project is
  busy, gets a page naming the operation in progress (HTTP 409) instead of
  running alongside it — "import and generate" and the package option keep
  sending to the result screen, as since 1.6.0. In practice they are
  always sequential; "delete project" during a generation would remove
  files being written.
- **The slot never gets stuck.** Released on every exit of the operation
  (return, exception, interruption) and empty when the server starts —
  the slot lives in memory, so this guards against a reloaded module or a
  future on-disk record, not against a failure seen in use.
- **Elapsed time uses the monotonic clock.** Setting the Windows clock
  back in the middle of a generation no longer distorts the bar.
- A malformed token on the "Read CPU sensors and fans" request answers 403
  instead of an internal error with a traceback in the log.
- Only the motherboard's SuperIO chip decides the CPU fan; another
  sub-hardware with a header named "CPU…" at 0 RPM no longer shows as
  "stopped".

## [1.7.0] — 2026-11-02

### Added

- **Fan speeds on any machine the library can read.** The CPU fan is not
  a CPU sensor: it is a header of the motherboard's SuperIO chip, which
  the sensor reader never opened. On a Nuvoton NCT6798D, for example, the CPU fan is `Fan #2`,
  invisible before. The elevated helper now reads the SuperIO and
  picks the CPU fan by the sensor's name or, when the board gives none,
  by the chip's fixed CPU header; a guessed header reading 0 stays "not
  measured" rather than showing a wrong number. A GPU fan at 0 RPM is
  shown as **"stopped"** (zero-RPM mode when the card is cool), and a
  CPU value that is missing only for lack of privilege says so instead
  of a dash.
- **"Read CPU sensors and fans" button on the Run screen.** Asks for the
  elevated sensor helper on demand, with one line explaining what Windows
  will ask and why; the desktop shortcut stays for whoever wants it
  automatic. The route behind the button accepts the request only with
  four independent guards — a token minted on each server start and
  embedded only in that page, `Sec-Fetch-Site: same-origin`, a custom
  request header, and a `Host` equal to the server's own — and every page
  now refuses to be embedded in another site's frame (`X-Frame-Options:
  DENY`), so no other website open in the browser can make the prompt
  appear, by request or by a hijacked click. A second click while Windows
  is still asking does not open a second prompt.
- **Activity bar for every long operation.** Shows the name of what is
  running and a clock, not a spinner: import and generate reports, save
  and regenerate, package download, clear intermediates, search index,
  update, delete. The server records which operation holds a project and
  since when, and every page of the project asks on load — reloading in
  the middle of a generation resumes the bar with the real elapsed time,
  under the same name it had at the click. Screen readers hear the start,
  each full minute and the end, not the clock every second.

### Fixed

- The sensor helper's status file from a previous session (`started`,
  with no helper alive) made a fresh server say "the reader did not
  answer" before anyone had asked for a reader. It is cleared at startup.

## [1.6.1] — 2026-11-01

### Fixed

- **The instructions you already use were copied again on every
  regeneration.** The text pasted into "Instructions you already use"
  arrives from the form with Windows line endings, while
  `project_instructions.md` reads back with plain ones, so the check "is
  it already in the file?" compared two spellings of the same text and
  appended it once more on every "Save and generate again" and every
  "Import and generate reports", until the file held several copies.
  `merge_managed` now normalizes line endings and inserts the
  pasted text only when the file has nothing outside the managed block;
  whatever is already outside the block is kept as it is. Generating three
  times in a row now produces an identical file (test added).

## [1.6.0] — 2026-11-01

### Changed

- **The package fits a Claude Project.** A Project on claude.ai accepts
  30 MB per knowledge file, and its answers degrade once the files add up
  to more than a few million tokens (above roughly 500 thousand it already
  switches to automatic search over the files). On a large collection
  with a full Planalto mirror, `index-<group>.md` of the main group
  reached tens of megabytes and over a hundred thousand lines, almost all
  of them federal acts recognised by the Planalto reader, and
  `timeline.md` was nearly as large: the same index reordered by date. No file slicing fixes that; the Project's capacity is
  the limit. Four things change in the generated files, which is why this
  is 1.6.0:
  - **Planalto legislation goes to `legislacao-<group>.md`**, with the
    same columns as the index, generated always but **outside the package
    by default**. Legislation means the acts the Planalto reader
    recognised and also any `.htm`/`.html` page from the same folder as
    those acts that the reader did not read (corrections, presidential
    messages, decrees in an unusual layout; on a large collection they
    alone nearly doubled the packaged index): Claude consults laws, decrees and provisional measures
    better directly at planalto.gov.br, and `project_instructions.md` now
    tells it so, with the instruction to always cite the act's number and
    date. The summary in `index.md` counts collection documents and
    Planalto acts separately. The option **Planalto legislation in the
    package** (New project form and Result screen, which regenerates the
    reports) puts them back in.
  - **The timeline no longer repeats the index.** Planalto acts stay out
    of it (unless the option above is on), and a group with more than
    2,000 dated items (`timeline_split_items`) gets its own
    `timeline-<group>.md`, with `timeline.md` pointing to it. That file
    stays outside the package (on a large collection it reaches hundreds
    of thousands of tokens, the group's index reordered by date); the Result screen lists it as
    generated but not packaged. The Source column is gone: file and page
    now go in the Reference.
  - **A group index above 25 MB comes out in parts** `index-<group>-1.md`,
    `-2.md`…, split only between source files — the items of one PDF stay
    together. The summary lists the parts with the sheet range of each.
    The same applies to `legislacao-<group>.md`.
  - **Leaner lines.** The Range column shows only `(p. N)` when the file is
    the one already in the Source column, and the Confidence column
    appears only when the project reviews low confidence or some item is
    below `high` (it was `high` in almost every line). A new
    section of `project_instructions.md`, "Columns of the files",
    describes the columns as they are.

### Added

- **Token budget before download.** The Result screen lists every file
  that goes in the `.zip` with its size and estimated tokens (3 characters
  per token, a conservative estimate for Claude on tabular Markdown in
  Portuguese), the total, and a warning at two levels: above 500 thousand
  tokens the Project depends on automatic search; above
  `package_token_limit` (default 2,000,000) it stops answering well. A
  file above 30 MB is flagged with the two remedies. Nothing is ever
  blocked — the download button stays active.
- `HOW_TO_USE.md` in the package and the three READMEs explain the
  Project's limits and how the program handles them.
- Still to come, noted in the phase plan: a local MCP server over the
  full-text index (`fulltext.py`), so Claude Desktop can search the whole
  collection on demand without uploading any file — the definitive answer
  for collections above a few million tokens.

## [1.5.19] — 2026-11-01

### Fixed

- **The OCR language is installed without administrator rights.** Tesseract
  comes with English only, and its data folder (`C:\Program
  Files\Tesseract-OCR\tessdata`) needs administrator rights; the
  installer asked Windows for elevation to copy `por.traineddata` there,
  and when that approval did not happen the language was missing and the
  "About" screen sent the user to download it by hand. The language data
  now goes to this machine's own folder (`%LOCALAPPDATA%\GClaudeIndexer\tessdata`)
  with the languages Tesseract already has, downloaded from the pinned
  `tessdata_fast` commit with its SHA-256 checked, and GClaude Indexer
  points Tesseract at that folder in its own process only — nothing
  machine-wide changes. The installer does this, and so does the program
  itself on start, before OCR and when the "About" screen is opened, so a
  machine whose installation could not do it fixes itself as soon as it
  is online. A Tesseract that already has the language is used as it is.

## [1.5.18] — 2026-11-01

### Fixed

- **Closing the browser frees the project for another computer.** The
  server has no window and keeps running after the last tab is closed, and
  it refreshed the project's lock every minute for as long as it lived:
  the other computer was told "in use, last activity 1 minute ago" and
  could never open the project. The lock is now refreshed only while the
  project is in use — a screen of it open in the browser (each one tells
  the server every minute), a request being answered, or a step running
  in the background, so a classification left running overnight with the
  browser closed keeps its lock. About 5 minutes after the last tab is
  closed, with nothing running, the lock is removed; opening a screen
  again takes it back after the usual check. The message shown on the
  other computer now says this.

## [1.5.17] — 2026-11-01

### Changed

- **Planalto acts get their author from the whole text.** The page the
  classifier sees stops at the project's page size (4,000 characters by
  default), and a long law is signed past that point, so many acts of a
  large collection had no author. "Importar e gerar
  relatórios" now reads the signature from the full-text search, which
  keeps the whole text; acts of the Congress, which close with "Congresso
  Nacional, em …" instead of the President's line, are read too, and
  constitutional amendments (signed by both Mesas) get the Mesas as
  author. Almost all of the missing authors are now found in about a
  minute, with nothing classified again; the few that remain are almost
  all corrections (retificações), which carry no signature.
- **One spelling per signature.** "ERNESTO GEISEL", "Ernesto Geisel" and
  "ernesto geisel", or "Getulio Vargas" and "Getúlio Vargas", became one
  author each in the index.
- **One spelling per document type.** Types that differ only in accents
  ("INDICE"/"ÍNDICE", "SESSAO"/"SESSÃO") become the accented one when it
  is common enough, and an item with no type whose summary says the page
  is blank gets "PÁGINA EM BRANCO". Different names are never merged:
  "LEI FEDERAL" stays apart from "LEI".
- **The hardware summary is no longer repeated in the log.** Every step of
  "Rodar tudo até a classificação" diagnosed the machine again and wrote
  the same two lines four to eight times per run; a repeat within 15
  minutes is now left out. Warnings are always written.

## [1.5.16] — 2026-11-01

### Changed

- **The Planalto reader recognizes more acts.** Ministerial ordinances,
  resolutions and normative instructions (the Covid-19 collection), the
  Congress's declaratory acts, alvarás and acts of the Empire (confirmed
  by the site's own header, since they have no enacting clause), dates
  written without "de" between day and month ("De 23 janeiro DE 1948") and
  titles preceded by "(*)". On a large collection the share of Planalto
  pages read this way rose by a few points, and the windows that still
  send pages to the model fell by about a third. Without an enacting clause, the
  summary is the single line under the title, and the site's navigation
  links ("Não remover", "Down", "Up") no longer get into it.

## [1.5.15] — 2026-10-31

### Fixed

- **A window the model refuses is split, not left pending forever.** When
  Ollama answers with an error about the prompt itself ("prediction
  aborted, token repeat limit reached"), the window is classified in
  halves until the unreadable page is alone; that page is indexed by file
  name. Before, it counted as Ollama being down: restart attempts, three
  identical retries and the window pending again on every run.
- **Pages holding the raw bytes of a binary file are read as empty.** Zip,
  font, audio and CAD files converted before 1.5.9 kept a page of control
  characters, which made the model loop.
- The "model stopped responding" message no longer says the run will
  switch to the Rules engine; with a video card it never does.

## [1.5.14] — 2026-10-31

### Added

- **Federal legislation from the Planalto website is read from its own
  structure, not by the model.** Every act carries the same parts: title
  with kind, number and date, the official ementa, the enacting clause,
  the closing date line and the signatures. Type, number, date, signer
  and summary (the official ementa, plus the revocation note when there
  is one) come out of them word for word. On a large collection, the vast
  majority of the Planalto pages are read this way in seconds, and the
  model's queue goes from many thousands of windows (days on a 6 GB laptop
  card) to a few hundred. Pages that do not match the format
  exactly still go to the model. Search is not affected: the full text of
  every page is indexed whatever classifies it. Applies to the local
  model and to the Rules engine; a window made only of acts no longer
  waits for Ollama.

### Changed

- **The installer brings Ollama to its newest version** every time,
  stopping the running server first (an open `ollama.exe` made the
  upgrade fail). New model formats are refused by an older Ollama.
- **The automatic local model follows the video card.** The installer
  and the program read the card's VRAM: 8 GB or more takes `qwen3.5:9b`,
  6 GB or less keeps `qwen3.5:4b`. A machine upgraded from an older
  version without the 9B model downloaded keeps using the 4B one.
- On 6 GB cards the model stays `qwen3.5:4b`. Compared on the same set of
  windows, its `-mtp` variant gave the same answers and was not faster
  (162 s against 145 s for four windows); `bonsai-2:9b` and
  `ornith-1.5:9b` were slower (2x and 9x) and each failed one window; `qwen3-vl:8b` does not fit a 6 GB card and
  timed out loading.

## [1.5.13] — 2026-10-31

### Fixed

- **The fan speeds never showed on the installed program.** The elevated
  sensor reader runs from a local copy of a few modules, and Dell's
  thermal reader was not among them: its import failed there without a
  word. A test now checks that the copy carries every module the reader
  imports.

## [1.5.12] — 2026-10-31

### Fixed

- **With a graphics card, classification never falls back to the Rules
  engine.** One slow window timed out, was retried while Ollama was still
  busy with it, and the run then handed the thousands of remaining windows
  to the Rules engine in minutes, without a word in the log (the summary
  still said "local model"). Now, with a graphics card, a model that stops
  responding is restarted and waited for, and the run carries on from the
  same window. A window that fails three times while the model answers
  the others stays pending for the next run. Without a graphics card the
  Rules engine still stands in, but its windows are marked and go back to
  the model on the next run.
- **Windows the Rules engine classified only because the model was down
  go back to the model** at the start of the next classification; the
  ones the model already did are kept.
- **Time limit for one answer of the model raised from 120 s to 300 s.**
  A 16-page window answers ~1,800 tokens; on a hot 6 GB laptop card that
  averaged 40 s and passed 120 s on the heavy ones. A server that still
  answers is no longer restarted after a timeout: the same window is sent
  again.
- **What an Ollama server started by the program prints is kept** in
  `%LOCALAPPDATA%\GClaudeIndexer\ollama-serve.log`, so a crash can be
  explained afterwards.
- **"Page extraction" stayed pending with nothing left to extract.** With
  every file already extracted, the step counted itself paused and skipped
  the full-text search index, so no file of the project was ever indexed
  for search.
- **The classification shows its estimated time after five windows**,
  instead of after 0.5% of them (over half an hour on a large run).
- Includes 1.5.11 (fan speeds after restarting Windows), which had no
  installer of its own.

## [1.5.11] — 2026-10-31

### Fixed

- **The fan speeds stayed empty after restarting Windows.** The elevated
  sensor reader starts before Dell's thermal service is ready, and its
  first failed read switched the fans off for the whole session. It now
  tries again every 30 seconds, and only gives up after ten failures in a
  row (a machine without Dell's interface).

## [1.5.10] — 2026-10-31

### Fan speeds on Dell laptops; PawnIO driver for the CPU sensors

#### Added

- **Fan speeds of the CPU and the GPU on Dell gaming laptops** (G series,
  Alienware), read from Dell's own thermal interface (the one Alienware
  Command Center uses). On a laptop the fans belong to the embedded
  controller: neither the sensor library nor the graphics driver sees
  them (`nvidia-smi` reports `N/A`). The same interface gives the CPU
  temperature, so it shows even without the PawnIO driver. Only read
  operations are used; fan control is never touched. Needs the CPU sensor
  shortcut (the elevated sensor reader); on other machines nothing
  changes.
- **The installer offers the PawnIO driver, ticked by default.** The
  sensor library reads the CPU temperature and power through it; without
  it they stayed empty even with the CPU sensor shortcut. It is a kernel
  driver from a third party (https://pawnio.eu/), installed through
  winget, and Windows asks for an administrator to install it. It can be
  unticked; everything else works without it.

## [1.5.9] — 2026-10-31

### The full-text search no longer stalls the extraction; a responsive Execution screen

The times below were measured on a local copy of a large project's database
(well over a hundred thousand pages). With the database in Google Drive
they are slower, though not by orders of magnitude.

#### Fixed

- **Adding files to the full-text search slowed down with every file.**
  Before storing a file, its old passages were deleted through a column
  the search table does not index, so each file read the whole table —
  new files included, which had nothing to delete. On a large collection
  the extraction reached 100% and then sat "running" for what would have
  been more than 100 hours. Each file's passages now get a recorded range
  and are removed by it, and the texts are read in parallel: ~0.35
  files/s before, ~800–1,000 HTML files/s now.
- **The extraction step was "done" while the search was still being
  built.** A pause during that phase left the search unfinished and "Run
  next step" moved on. The step is now done only when every file is in
  the search, and the progress bar shows that phase on its own instead of
  sitting at 100%.
- **The Execution screen took about 90 seconds to open** during a large
  run, and the steps table as long to refresh. The quality summary read
  the text of every page just to count them, every two seconds. It now
  counts without reading the text, computes coverage in one pass, and is
  recalculated only when something changes: 5.6 s → 0.2 s locally.
- **The live log filled with "The project's database is busy" and
  stopped updating.** That notice is meant for a whole page, and the log
  pasted it into the list whenever the database was busy. The log now
  skips that cycle and tries again, like the rest of the screen.
- **Classified items were lost when a summary contained the character
  U+0085.** Common in HTML read as Latin-1, it split the item's line in
  `raw_items.jsonl` in two, and the import discarded both halves as
  corrupt.
- **A review resumed after a pause sent every low-confidence window back
  to the model**, including those it had already reviewed. They are now
  skipped.

#### Changed

- **Classification writes in batches** (rules and local engines): one
  commit every two seconds instead of one per window plus one per
  logged event. On a database in Google Drive each commit costs seconds
  and blocks the screen. The windows step reads the pages without their
  text when it does not write window files, checks existing windows with
  one query per group, and lists the windows folder once. Locally, on
  the same database: the windows step takes seconds and the rules
  classification about a minute.
- **The steps write less often**: every two seconds or 500 operations
  (were one second or 200), so the screens find the database free more
  often.
- **OCR conversion starts with the largest file.** In path order a PDF
  of hundreds of pages could start last and run alone for minutes after
  every other file was done.
- **Binary files are no longer read as text.** With "all extensions"
  selected, a file with no extractor whose first bytes contain a NUL
  (zip, audio, font, CAD drawing) is kept in the index by name with no
  text, instead of a page of control characters that went into the search
  and into summaries. This applies to files converted from now on; the
  ones already converted change when reprocessed (project update).
- **A file whose text cannot be read for the search** is logged and
  recorded with no passages, so the step can finish, instead of being
  retried on every run. Reprocessing the file (project update) brings it
  back.
- **The installer ticks the classification model download and the CPU
  sensor shortcut by default.** Both can still be unticked; an update
  finds the model already downloaded and skips it.

## [1.5.8] — 2026-10-31

### Much faster processing on Google Drive; updating stops the old version

#### Changed

- **Intermediate files are kept on the local disk.** The OCR'd PDFs, each
  file's extracted text and the PDF slices (`converted/`, `blocks/`) now go
  to `%LOCALAPPDATA%\GClaudeIndexer\work\`, not to the output folder. In
  Google Drive each new small file took ~800 ms to create, against 0.3 ms
  locally, and the conversion of a large collection was waiting on Drive
  with the CPU idle. Nothing a project is used for needs these files
  afterwards: the pages and the full-text search are in `project.db`, the
  indexes and the windows stay in the output folder. Projects converted
  before keep reading the copies they already have there. On another
  computer, a file whose copy is missing goes back to conversion instead of
  failing.
- **Conversion runs two queues.** Files that need no OCR (HTML, text, DOCX,
  e-mail) spend their time waiting on the disk, so they get a much larger
  pool of processes (up to 4 per physical core in "maximum" mode). OCR keeps
  its per-core pool. Measured on HTML files from Drive: a few files per
  second before, hundreds per second now.
- **Windows step:** the window `.txt` files are written only for the Claude
  Code engine, the only one that reads them, in parallel, and any missing
  ones are written when that engine is chosen later. One commit per group
  instead of one per window.
- **Full-text search indexing** commits in batches instead of once per file.

#### Fixed

- **Classification reread the whole group for every window.** On a group
  of over a hundred thousand pages that meant hundreds of megabytes read
  per window, for thousands of windows. Each window now loads only its own pages,
  and the group column is indexed. This affects the rules, local and review
  engines alike.
- **Installing an update left the old version running.** Opening the
  program again found the old server still on the port and showed the old
  version. The installer (and the uninstaller) now stops the program's
  processes first, including the server that the virtual environment's
  launcher starts as a child. Opening the program also replaces a server
  of another version still running, and the shortcut waits for the server
  to answer before opening the browser.

## [1.5.7] — 2026-10-31

### OCR no longer fails on PDFs with unusual colors, and failed OCR is retried

#### Fixed

- **OCR failed on PDFs with an unusual color space** (common in print-shop
  PDFs), with `ColorConversionNeededError`. Text recognition itself worked;
  what failed was converting the result to PDF/A, the archival format, and
  the whole file's OCR was thrown away with it. The OCR'd copy is only read
  for its text, so it is now a plain PDF (`--output-type pdf`). This is also
  a little faster.
- **A file whose OCR failed stayed that way for good.** A PDF with native
  text kept its scanned pages blank, and a fully scanned PDF stayed failed;
  running the steps again did not revisit either. Now a file on which OCR
  failed is marked and goes back to the queue at the start of the next
  conversion, until OCR succeeds. Only OCR failures: a corrupt or
  password-protected file is not retried. The Execution screen shows the
  conversion as pending while such files wait.
- **Files that failed before this version are recovered.** The first time
  1.5.7 opens a project it marks the files whose OCR failed earlier, found
  from the error stored for the file and from the log's warnings, and the
  next conversion redoes them. A file already inside the classification
  windows is not sent back, since its windows would go out of date; the log
  names it.

## [1.5.6] — 2026-10-31

### Economy mode and the scan cannot freeze either; security updates

#### Fixed

- **Economy mode (parallelism 1) could still freeze on a Google Drive
  file.** One file at a time ran on the step's own thread, which nothing
  could unfreeze. It now runs under the same guard as the parallel path,
  on a thread the step abandons when the file goes past its time limit.
  OCR still runs in the program's own process, as before.
- **The scan could freeze on a file or a folder that Drive never
  answers.** Reading each file's size and computing its hash now have a
  time limit. A file past it is left out of this scan, with a warning in
  the log, and checked again on the next one. Three in a row stop the
  scan with a clear message. A folder whose listing never answers stops
  the scan instead of being skipped, because a skipped folder would look
  like its files had been removed.
- **The update check never reads a frozen folder as "files removed".**
  It reports the source folder as unavailable, the same as a disconnected
  drive, and offers nothing to delete.

#### Security

- **Pillow 13.0.0** (was 12.3.0), fixing the 41 Dependabot alerts against
  12.x, among them heap overflows when decoding JPEG, TIFF and FlashPix
  images and argument injection into the Ghostscript call. The program
  opens third-party images for OCR, so these were reachable.
- **Starlette 1.3.1** (was 0.52.1), fixing NTLM credential theft through
  UNC paths in `StaticFiles` on Windows, form limits that were silently
  ignored, and Host header validation. It needed **FastAPI 0.162.0** (was
  0.128.8), the first series that accepts Starlette 1.x.

## [1.5.5] — 2026-10-31

### Processing no longer freezes, whatever the size of the collection

#### Fixed

- **A conversion could freeze for good, and the Execution screen then
  showed "Internal Server Error" every two seconds.** On a very large
  Google Drive folder, Drive stopped answering a few file opens. The
  helper processes waited on them forever, and the step, which waited for
  its helpers before leaving, waited with them while keeping the database
  locked. Every file now has a time limit that grows with its size (10
  minutes plus 2 per MB). A helper that goes past it is stopped and
  restarted, and the work carries on. A file that freezes twice while the
  others keep moving is marked as failed with "timed out". When nothing
  moves at all (Drive or the disk has frozen, not one file), the step
  stops with a clear message and leaves every file for the next run.
- **A busy database broke the step instead of waiting.** A moment of
  `database is locked` ended the step with its transaction still open.
  The step now writes in batches, and on a locked database it undoes the
  batch and applies it again a moment later, for up to ten minutes.
- **A busy database showed "Internal Server Error" on screen.** The
  Execution screen keeps what it already shows and asks again on the next
  tick. A full page explains that the database is busy and nothing was
  lost.
- **A helper process that died (out of memory) ended the step.** The pool
  of helpers is now rebuilt and the work carries on. Files caught in two
  crashes are kept for the next run, as before.

#### Changed

- **Conversion and extraction are much faster on a Google Drive folder.**
  The database journal mode is now `TRUNCATE` instead of `DELETE`: a
  commit on a Drive folder went from about 0.3 s to under 0.01 s, because
  Drive no longer has to create and delete the journal file each time.
  It is still a rollback journal with the same safety, never WAL. The
  steps also commit in batches (at least once a second) instead of once
  per file.
- **The screen's polls wait at most 5 seconds for a busy database**,
  instead of 30.

## [1.5.4] — 2026-10-31

### A second scan no longer rereads every file, and its bar moves

#### Fixed

- **"Run everything up to classification" spent hours rescanning a folder
  that had already been scanned.** The button always starts with the
  scan, and the scan computed the hash of every file again just to learn
  that nothing had changed — on a very large Google Drive folder, that
  meant reopening each file one by one. A file whose size and
  modification time match the inventory is now taken as unchanged
  without reading its bytes, the same rule the update check already
  followed. Anything that moved is still confirmed by its hash.
- **The progress bar of a second scan stayed at "0 / N" until the end.**
  It counted new rows in the inventory, and a scan of an unchanged folder
  adds none. The bar now follows the files the scan has gone through.
- **A wrong size stored for a file made it be reread on every scan.**
  Google Drive can report 16,384 bytes right after a file is written;
  when the content turns out to be the same, the real size is now saved.

## [1.5.3] — 2026-10-30

### The run buttons answer at once on large folders, with a live counter

#### Fixed

- **"Run next step" and "Run everything up to classification" looked
  dead on a large source folder.** Before registering the scan, the
  request walked the whole source folder twice to size the progress bar —
  minutes on a very large Google Drive folder. Meanwhile the first
  button hung and the screen said "No step running". The task is now
  registered at once and measures its work in the background.
- **Each extra click started another scan of the same database.** The
  "already running" check could not see a task that was still being
  measured. The check and the registration now happen under one lock: a
  second click returns the task already running.
- **The progress bar of the scan could stop short of 100%.** Its total
  counted `desktop.ini` and other system files that the scan never
  records; the count now uses the scan's own criteria.

#### Changed

- **While the source folder is walked, the Execution screen shows a live
  counter** ("Counting the files in the source folder: N file(s) found"),
  the elapsed time, a moving bar and the pause button, so a long walk never
  looks frozen.
- **The source folder is walked once per scan, not three times.** The
  count hands its list to the scan, and the walk uses `os.scandir`, which
  on Windows reads each file's size from the folder listing instead of
  asking for it file by file.
- **`.ini` files are never indexed**, even with "all extensions": Windows
  and Google Drive write one into every folder, and none is a document.

## [1.5.2] — 2026-10-30

### OCR page by page: scanned sheets inside native PDFs are no longer lost

#### Fixed

- **Scanned pages inside a native-text PDF reached the index blank.** OCR
  was decided by the file's average — under 100 characters per page — so a
  native PDF with a few scanned sheets in the middle (a signed minute, an
  annex) passed the average and those sheets stayed without text. The
  decision is now made per page: pages under 100 characters that carry an
  image or a vector drawing go to `ocrmypdf --force-ocr --pages …`, and the
  others pass through untouched. `--force-ocr` instead of `--skip-text`
  because a scanned sheet with a stamp or a "fl. 2" as text was skipped.
  On a collection of a few hundred PDFs, dozens turned out to be mixed;
  their scanned sheets went from a few dozen characters to thousands each,
  and native pages came out identical.
- **Digitally signed PDFs are OCR'd** (`--invalidate-digital-signatures`).
  Only the internal copy in the output folder loses the signature; the
  original is never touched.

#### Changed

- A low-text page with nothing drawn on it (a blank verso, a chapter
  divider) does not send a native book to OCR.
- If OCR fails on a PDF that also has native text, the file goes on with
  that text and a warning names how many pages stayed blank; a fully
  scanned PDF still fails, as before. The log says how many pages of how
  many received OCR.
- Already indexed projects keep their conversion: a mixed PDF is read again
  only when it changes or is reprocessed.

## [1.5.1] — 2026-10-28

### Mixed collections: one item per document, settings proposed from the folder, every word searchable

#### Fixed

- **The rules engine merged whole laws into one item.** In a collection of
  one law per HTML file, every page starts with "Presidência da
  República", no type marker matched "LEI Nº", and changing file was not a
  signal — so consecutive laws became a single item. Now a whole-document
  file (HTML, DOCX, XLSX, PPTX, TXT, MD, e-mail… everything except PDF and
  images) always starts its own item, in the rules, local and
  `claude_code` engines alike. PDF pages and runs of scanned images can
  still form one item, as before.
- **Legislative epigraphs are recognised as types** (`heading_types` in
  `classification_rules.json`): EMENDA CONSTITUCIONAL, LEI, LEI
  COMPLEMENTAR, DECRETO-LEI, DECRETO, MEDIDA PROVISÓRIA, PORTARIA,
  RESOLUÇÃO, INSTRUÇÃO NORMATIVA, SÚMULA, ACÓRDÃO and others — only at the
  start of a line within the first 600 characters, so a law cited in the
  middle of a text is not taken as the document's type. Dates written as
  "1º DE JANEIRO DE 2023" are read. Measured on 354 Planalto laws: 354
  items, 97% typed, all dated.
- **"biblioteca" collections with several files in a group merged their
  items.** There each file's references restart at "p. 1", and the
  position of a page in the group was taken from that number — so every
  item of every file had position 1 and consolidation fused them. The
  position is now the page's place in the group (`group_page_positions`),
  used by import, the index's physical-page map, the gap report and the
  quality coverage. Windows for `claude_code` show it as `[#N]` in each
  page header, and `CLAUDE.md` says to use it for `order_start` /
  `order_end`. "processo" collections were not affected.
- **A 1962 decree was read as Baltic (cp1257).** When statistical
  detection finds Windows-1252 as plausible as its best guess, Windows-1252
  wins — the encoding of almost all older Brazilian text.

#### Added

- **Settings proposed from the source folder.** On choosing the source
  folder of a new project, the program surveys it — up to 6 seconds, a
  sample of PDFs and text files — and proposes pages per block, pages per
  window, overlap, characters per page and OCR language, each with the
  reason, plus the folder's composition. "Apply" fills the form; nothing
  changes without it. OCR languages are only proposed if Tesseract has
  them installed.
- **Full-text search** ("Search the collection", on the run and result
  screens). Classification reads only the first "characters per page" of
  each page; the search keeps the whole text of every file, untruncated,
  in an SQLite FTS5 table inside the project. Results say where the text
  is — the PDF page (`f. 12` / `p. 5`), or in a whole document the article
  or heading and the line ("p. 1 · Art. 40") — highlight the words found,
  mark what was struck through in the original, and open the original
  file. Accents and capitals do not matter; "quotes" for a phrase, `*`
  for a prefix. Indexing runs at the end of extraction and resumes where
  it stopped; files extracted by an earlier version are added with
  "Add the missing files".

#### Notes

- A "biblioteca" project with several files per group that was already
  classified by 1.5.0 or earlier has merged items: create it again.
- The search covers files extracted from now on; for an existing project,
  open "Search the collection" and use "Add the missing files".

## [1.5.0] — 2026-10-28

### Web pages read as text, with what was struck through kept; every encoding read right

#### Added

- **HTML is read, not dumped.** `.htm`/`.html` went into the index as raw
  markup: `<head>`, CSS and JavaScript filled the characters allowed per
  page before the first article. They now become clean text
  (`html_text.py`): no tags, one block per line, headings as `#`, list
  items as `- `, table cells joined by ` | `, `N<sup>o</sup>` as `Nº`.
  Unclosed and misnested 1990s markup is tolerated; if the parser still
  fails, the text is recovered by stripping tags — never by failing the
  file. Measured on the Planalto collection: 0.4 s for the 1.7 MB Code of
  Civil Procedure, ~22 ms per law on average.
- **Strikethrough kept as `~~text~~`.** On the Planalto site a struck
  article, paragraph or item is a revoked, suppressed or replaced one,
  left on the page next to the text in force. Recognised forms:
  `<strike>`, `<s>`, `<del>`, inline `text-decoration: line-through` and
  CSS classes declared with it — and struck runs in DOCX, PPTX and XLSX.
  The rules engine ignores struck text when looking for type, date, author
  and summary; the local engine's prompt (only when a window has the
  mark), the `claude_code` engine's `CLAUDE.md` and
  `project_instructions.md` (only when the collection has the mark)
  explain it, in the three languages.
- **More web formats:** `.xhtml`, `.xht`, `.shtml` and `.mht`/`.mhtml`
  (a page saved by the browser as a single file). An `.xml` whose root is
  `<html>` goes through the HTML reader; other XML and JSON stay literal.

#### Fixed

- **Encoding is worked out, never assumed.** Every text-like file was read
  as UTF-8 with `errors="replace"`, so a Windows-1252 file — the whole of
  the Planalto legislation, most older Brazilian documents — came out as
  "Presid�ncia da Rep�blica". `text_decoding.py` now tries, in order: the
  byte-order mark, the declared encoding (HTML `<meta>`, XML declaration,
  MIME `charset`) if the bytes agree, UTF-8, statistical detection
  (`charset-normalizer`, now pinned), then Windows-1252/Latin-1. Labels
  `iso-8859-1` and `ascii` are read as Windows-1252, as browsers do. It
  never raises. Applies to `.txt`, `.md`, `.log`, `.csv`, `.xml`, `.json`,
  web pages, e-mail bodies and the `all` category.
- **E-mail with an unknown charset label no longer fails the file**, and
  an HTML-only e-mail body is converted to text instead of kept as markup.
  `.msg` without a plain-text body falls back to its HTML body.
- **DOCX no longer drops the text of hyperlinks** (cross-references to
  other laws, for one).

#### Notes

- Each HTML file is still one page, truncated at "Characters per page" for
  classification; the full clean text is in `converted/`. A law's first
  3000 characters carry its epigraph, summary and first articles.
- Files converted by an earlier version keep their old text: to re-read a
  collection, create the project again (or delete it with "everything" and
  recreate it).
- Strikethrough in PDFs is not detected — it is a drawn line, not a text
  attribute.

## [1.4.0] — 2026-10-16

### Your instructions kept, removals without loss, a real manual, safer by default

#### Added

- **Instructions complement yours instead of replacing them.**
  `project_instructions.md` and the output folder's `CLAUDE.md` were
  rewritten from scratch on every run, so a `CLAUDE.md` you already had in
  that folder, or a rule you added to the generated file, was gone on the
  next update. What the system writes now lives between
  `<!-- GCLAUDE-INDEXER:BEGIN … -->` and `<!-- GCLAUDE-INDEXER:END -->`;
  everything outside the marks is yours and is carried over untouched. The
  first time a file without marks is touched, the original is saved as
  `<name>.bak`. New field **"Instructions you already use"** on the New
  project form puts your Claude Project's current instructions at the top
  of the file. The Claude package guide now says to paste the whole file.
- **Full manual inside the app** (menu **Manual**, `/help`), in Portuguese,
  English and Spanish: quick start, every field, an engine comparison
  (speed, quality, requirements), the steps, output files, using it with
  Claude, updates, team use, tips and troubleshooting. Each screen's Help
  dialog links to its own section.
- **Four new themes** — Aurora, Toga, Graphite and Ocean — and a motion
  layer for every theme (`motion.css`): smooth page transitions, staggered
  entrance, lifting cards, pressable buttons, animated dialogs, a shimmer
  on running progress bars. Only `transform`/`opacity` animate, and
  everything turns off when Windows asks for reduced motion.

#### Changed

- **The live log speaks plainly.** 57 messages rewritten in the three
  languages to say what happened and what to do; technical details only in
  parentheses at the end. The step column shows "Update" instead of the raw
  `update`.
- **Removing a document from the collection** now: re-indexes an identical
  copy still in the folder (it used to silently drop the content), records
  a removal once and forgets it when the file comes back, deletes the
  removed file's OCR copy in `converted/`, deletes per-group indexes of
  groups that no longer exist (they were shipped to Claude), keeps groups
  whose safe names collide in separate files, and warns — on the plan
  screen and in the log — which documents' sheet numbers (`f. N`) shift.
- **Deleting a project "with files"** deletes only what the app created
  (database, converted copies, windows, log, reports), keeps your own files
  in the output folder, strips only the generated block from instruction
  files, and removes the folder only if it ends up empty. Without a
  `project.db` in the folder, nothing is deleted.
- **A brand-new project** no longer shows "the source folder changed: N
  new" before its first run.
- **Result screen** shows the engine's translated name, and the model only
  when the local engine used one; very large reports are previewed, not
  embedded whole.
- **FastAPI 0.128.8 with Starlette 0.52.1 pinned**, leaving the range
  affected by CVE-2024-47874 and CVE-2025-62727.

#### Fixed

- The confidence bars on the Result screen had no colour since phase 14:
  the template used a class name the stylesheet never defined.

#### Security

- **Only the app's own screens can command it.** The server checks `Host`
  (DNS rebinding), refuses requests the browser marks as coming from
  another site (except a plain link with no parameters) and refuses POSTs
  with a foreign `Origin` (CSRF). This also closes the NTLM-hash leak a
  site could trigger by making the app look at a `\\attacker\share` path.
  UNC paths typed in the app's own forms still work.
- The `claude_code` engine's `CLAUDE.md` tells Claude Code that window text
  is untrusted data and that it may only append to `raw_items.jsonl`.
- Calls to the local Ollama never go through a system proxy, so document
  text does not leave the machine on a corporate network.
- No open redirect through the `Referer`; the package file name is sent in
  RFC 5987 form.

#### Performance

- The "code changed since start" check uses `stat` instead of re-reading
  and hashing the package on every screen (several times every two seconds
  on the Execution screen).
- The live log reads only new rows, in SQL.
- Blocking routes (folder picker, update, delete, create) no longer freeze
  the server.
- Indexes on `window(status)` and `event(level)`.

## [1.3.4] — 2026-09-17

### Maintenance — a tools directory, and four pins moved forward

No behaviour of the application changes in this release. What changes is
what the repository carries alongside it, and which versions a fresh
install pulls.

#### Added

- **`tools/`, for operations the product does not offer.** Maintenance
  scripts run by hand against an indexed project's output folder; the
  installer does not ship them and the interface does not call them. The
  first one, `reprocessar_janelas_com_falha.py`, returns only the windows
  that failed in a step-6 run to `pending`, so a new classification retries
  just those instead of reindexing the whole acquis — the pipeline's only
  window transition is `pending -> done`, and the incremental update
  (phase 17) reacts to changes in the *source files*, so with the PDFs
  untouched it invalidates nothing. It refuses to reopen a window the
  acquis no longer has, and refuses failures that retrying cannot fix.
  Covered by `tests/test_tools_reprocessamento.py`.

#### Changed

- **Four pinned versions moved forward**, each merged with the full suite
  green: `pillow` 10.4.0 → 12.3.0, `jinja2` 3.1.4 → 3.1.6,
  `python-multipart` 0.0.12 → 0.0.31 and `pytest` 8.3.3 → 9.0.3. The CI
  actions moved too: `actions/checkout` 5 → 7 and `actions/setup-python`
  6 → 7.

  This matters more than a routine bump because the installer ships
  `requirements.txt` and `install.ps1` runs `pip install -r` from it on the
  user's machine: until this release, a fresh install pulled the versions
  pinned back in 1.3.0. The `jinja2` advisories are for its sandboxed
  environment, which this project does not use — it renders its own
  templates through `Jinja2Templates` — so the bump is hygiene, not an
  exposure being closed. `pillow` is the one that earned a check beyond the
  suite: it is a two-major jump, and it is reached from
  `_extract_text_image`, the OCR path for loose image files.

## [1.3.3] — 2026-09-17

### Phase 22 — "import and generate reports" on a network drive

Phase 21 fixed classification. The step *after* it was the one left
standing: on an acquis of thousands of pages whose output folder lives on
Google Drive, classification finished after hours and then **"Import and
generate reports" took over half an hour on its own**, with no progress bar
and no way to tell whether it was working or hung. The work was never at
risk — the pieces were all valid — but the screen gave no sign of it, so
the button got clicked again. And again.

#### Fixed

- **The range check stops re-reading the same pages once per piece.**
  `_validate_range_within_group` asks the database for every page of a
  piece's group, to check that the piece's range exists. It asked once per
  piece: **thousands of queries where one per group would do**, because
  the acquis has only a few groups, and one of them holds almost all the
  pieces. The range depends only on the group, so it is now read once per
  group and cached for the run. On that acquis: **from tens of seconds to
  under a tenth of a second** on a local disk, and **from most of an hour
  to under a second** with the database on the Drive, where each of those
  queries cost tens of times more than locally. Import plus every report
  now takes under a second where it took most of an hour.

- **A second click no longer starts a second import.** Unlike the pipeline
  steps, this route does its work inside the HTTP request, so it has no
  `task_manager` entry and nothing was checking whether it was already
  running. A stack dump of the live server showed **several concurrent
  `import_and_generate` threads**, each holding the GIL in turn and each
  about to run `DELETE FROM item` followed by thousands of inserts on the
  same SQLite file. They all finished, and all wrote the same result — but
  each took most of an hour to do it. A click that lands on a run already
  under way now goes straight to the Result screen instead.

640 tests passing, against 638.


## [1.3.2] — 2026-09-16

### Phase 21 — calibrated context and an honest score

Phase 20 fixed the mechanism and kept the wrong number feeding it. On a
long indexing run on 1.3.1, **about one window in ten entered the index
with no classification at all**: hundreds of pieces with empty type, date
and author, and raw OCR in place of the summary. The log closed on
`baixa=0` and the score still looked high.

#### Fixed

- **The characters-per-token ratio stops being a guess.**
  `_CHARS_PER_TOKEN` was 3.0, measured on Portuguese prose. The acquis
  held accounting tables, and an accounting table tokenizes at **1.45** — phase 20's per-window recalculation ran
  and came up short every time. The ratio is now learned during the run
  from the `prompt_eval_count` Ollama already returns and the code was
  discarding, keeping the lowest value observed, with a floor of 1.2.
  On that acquis the ratio converges to 1.45, and windows
  that returned 0 of 4 pages now return 4 of 4, all at high confidence.

- **Retry ladder.** The trigger is "rows returned < pages in the window",
  which does not depend on Ollama's internal behaviour. Telemetry only
  picks the next context: a truncated prompt doubles it; an intact prompt
  with a starved answer uses `prompt_eval + pages × 220`. Above the card's
  ceiling, measured per run, the window is subdivided instead of spilling
  into RAM.

- **The answer with no budget.** A failure mode nobody had seen: at
  `num_ctx` 5120 a 5091-token prompt fits whole and leaves 29 tokens to
  answer with. The JSON comes out cut off and the log says the same thing
  it says for truncation, from the opposite cause. Detection now looks at
  both sides.

- **Coverage was measuring nothing.** The query compared `page.number`,
  which is the page within the file, against `item.start_order`, which is
  the sheet within the group, with no join on the group. Direct proof:
  removing hundreds of pieces from the index, a hole of hundreds of
  sheets, left it still reporting 100.0%.

- **The score stops paying itself.** The 40 coverage points were
  tautological: grouping emits one piece per page of the window, so the
  page is always inside some piece. They now measure *classified*
  coverage — pages the model actually described. The same run now scores
  **lower**, and it is against that honest score that the fix shows its
  gain.

- **A blind piece stops passing for a medium one.** A page the model said
  nothing about still enters the index through grouping — that guarantee
  is what prevents loss — but now at `baixa` confidence. That is what
  gives step 6's `baixa=` count its meaning back.

### Added

- **An index row leads to the physical page of the PDF.** `f. 417` can be
  page 145 of `Vol 2.pdf` in a group of many volumes; the index named the
  file and stopped there.

- **Per-group index, with a table of contents.** `index.md` came out at
  thousands of rows and more than a megabyte in a single file, too much for a Claude Project to
  consult reliably. It becomes a few-KB summary pointing at the group and
  the file; each group's table goes to `index-<group>.md`, and the Project
  package carries them all.

638 tests passing, against 618.


## [1.3.1] — 2026-09-15

Phase 20. Three things an indexing run was losing in silence.

Found by reading the log of a long indexing run (`qwen3.5:4b` on a laptop GPU). Nothing had crashed — the
run reported `0 falhou(aram)` at every step — and that was the problem:
all three defects reported themselves as warnings, or as nothing at all.

### Fixed

- **A piece is no longer thrown away because of the precision of its
  date.** Accounting and administrative documents are dated by period —
  "competência 01/2020", "exercício 2019" — and the model returns
  `2020-01` because that is what the page says. Validation demanded a
  strict `AAAA-MM-DD` and dropped the *entire* piece — type, author,
  summary and all — over one optional field. That was every rejected
  piece of the run.

  Reduced precision is now kept as it came. It is legitimate ISO 8601 and,
  what settles it here, it sorts correctly under the lexicographic sort
  the timeline in `artifacts.py` already uses (`2019-12` < `2020-01` <
  `2020-01-05`) — so there is nothing to gain by inventing a first-of-the-
  month the document never stated. A date whose finer precision does not
  hold drops one step instead of vanishing: `2021-09-31`, a day that does
  not exist, becomes `2021-09`, because the month is still good. Text that
  is not a date at all — a range, a Brazilian-format date — clears the
  field and the piece is written without it.

- **A rejected piece no longer takes its pages out of the index with it.**
  The coverage guarantee ran *before* validation, so pages covered only by
  a piece that validation then refused ended up in no piece at all —
  silently, since the coverage warning had already decided nothing was
  missing. In the observed run that left whole stretches of pages absent from
  an index whose whole purpose is to say which page a thing is on.
  Coverage is now computed from the pieces that actually survived
  validation.

- **The Ollama context is measured per window, not once per run.** It was
  sized from the first window's prompt and frozen there. A denser window
  further in overflowed it, the answer came back truncated, the JSON never
  closed and the parser got zero rows — the window reached the index with
  no classification at all, only a warning saying the model had not
  answered about any of its pages. That was about one window in seven,
  which is most of what the run reported as medium confidence. The
  context is now remeasured whenever a window needs more than the widest
  one so far, and only ever grows — an oscillating `num_ctx` would make
  Ollama reload the model between windows, which is what the single
  measurement was avoiding in the first place.

## [1.3.0] — 2026-09-13

Phase 19. An installer for people who do not open a terminal.

### Added

- **A Windows installer.** `GClaude-Indexer-Setup-1.3.0.exe`, built with
  Inno Setup from `installer/GClaudeIndexer.iss`. It asks where to install
  (per-user or for the whole machine), shows the GPL-3.0 text — the licence
  being granted, not terms being imposed — and puts every dependency on one
  page with a checkbox each: Tesseract and Ghostscript ticked and locked
  because without OCR the program cannot do the job it exists for, and
  Ollama, the classification model, the sensor libraries and the CPU-sensor
  shortcut left to the person installing. Everything is downloaded and
  installed with a progress bar and without a terminal window appearing at
  any point.

  It is not code-signed. A certificate costs money this project does not
  have, so SmartScreen warns before it runs; each release publishes the
  SHA-256 of the file.

- **An uninstaller that asks what should go.** Removing the program from
  Settings > Apps opens a dialog with one checkbox per shared dependency —
  Tesseract, Ghostscript, Ollama, the downloaded models, Python 3.12 — and
  removes what is ticked and nothing else. Someone who wants Ollama gone
  may well still be using Ghostscript. The project list is never touched:
  it lives behind a switch nothing in the installer passes.

- **A log for both.** `%LOCALAPPDATA%\\GClaudeIndexer\\install-log.txt` and
  `uninstall-log.txt`, in UTF-8. The first version of this ran hidden and
  silent, and when a user reported that nothing had been installed there
  was no way to tell whether the script had failed, run partially, or
  worked while they looked too early.

- **The project page on the About screen.** The only outbound link in the
  system, and it does not weaken the offline promise: nothing is fetched
  and nothing is sent — the page opens only if the person clicks it.

### Fixed

- **The installer ran nothing at all in the default folder.** It built one
  `cmd /c ""powershell.exe" -File ""<path>"" ..."` command line, and the
  doubled quotes cmd's own parsing needs did not survive PowerShell's: in
  `C:\\Program Files\\GClaude Indexer` the path was cut at the space,
  PowerShell refused `-File 'C:\\Program'` and fell through to its
  interactive prompt — a black window in front of an installation where not
  one dependency had been installed. The sentinel hid it: `& echo
  %ERRORLEVEL%` ran whether or not PowerShell had ever started, so the
  wizard read a code and went to its final page. The uninstaller used the
  same command line and failed the same way, without even leaving a log,
  because the redirection was part of the line that never ran. There is no
  `cmd.exe` in the project any more: the installer writes a `.ps1` with the
  paths already embedded and runs that.

- **The Ollama model was never downloaded.** `ollama list` and `ollama
  pull` are both clients of a server on 127.0.0.1:11434, and having the
  binary on disk is not having the server up — after a fresh winget install
  it usually is not. That produced two wrong answers in one run: the script
  concluded the model was missing, then the download was refused with "the
  target machine actively refused it". The installer now starts `ollama
  serve` before asking anything and waits up to forty seconds for the port.

- **Removing a user-scope package needs an unelevated winget.** The
  uninstaller removed Tesseract, which installs machine-wide, and left
  Ollama and Python, which install into the user's own profile. Removal is
  now attempted as the user first and elevated afterwards only for what is
  still installed.

- **`--silent` stopped the removal instead of quieting it.** It asks winget
  to run the package's own silent uninstall command, and a package whose
  manifest has none refuses the whole request — three runs reported "Ollama:
  still installed" while the same command without the flag removed it on
  the first try. Both variants are attempted now, and the verdict comes
  from asking the machine rather than from winget's exit code, which
  reported success for an uninstall that changed nothing.

- **The CPU-sensor shortcut was never created.** Its whole block in
  `install.ps1` sits behind `if (-not $NoShortcut)`, and `-NoShortcut` is
  what the installer always passes so that uninstalling removes the
  shortcuts. Ticking the box passed `-CpuSensorShortcut` into a script that
  had already decided to create none, while the application told the user
  to open the shortcut that was not there. The `[Icons]` section owns it
  now.

- **The CPU-sensor shortcut did nothing when the system was already open** —
  which is exactly when someone clicks it. Each click started a second
  server that asked for the elevated helper, lost port 8000 to the server
  already running and died; the helper's lifetime is tied to the process
  that asked for it, so it died too, and the server drawing the screens was
  never told. The helper is now attached to the server that is already
  running.

- **A downloaded model was reported as missing.** The list of models comes
  from the Ollama server, and a stopped server returns an empty list that
  is indistinguishable from an empty machine — so the About screen offered
  to re-download 3.2 GB that were already on disk. The store on disk is
  consulted when the server does not answer.

- **The About screen showed a connection warning in the Version column.**
  `ollama --version` with the server down prints two lines and both begin
  with "Warning:"; the first is about the connection and the second carries
  the version.

- **`PSModulePath` from PowerShell 7 killed the installation at step 3.**
  Installing PowerShell 7 prepends its module directories machine-wide, and
  Windows PowerShell 5.1 — which runs the installer — then loaded the wrong
  `Microsoft.PowerShell.Utility` and lost `Get-FileHash`. Reproduced on the
  pre-phase-19 script: a latent defect, not a regression.

- **The uninstaller deleted the project list.** `projects.json` is the list
  of collections the user has opened; losing it deletes no document but
  makes every collection have to be found by hand again. It is now user
  data, which only `-RemoveUserData` removes — not even the "remove the
  dependencies too" option touches it.

- **`review.md` did not count duplicate files.** The coverage loop skipped
  the `duplicate` state, so a collection with repeated documents reported
  fewer files than it had.

### Changed

- **New logotype, with real transparency.** The previous one was a JPEG, a
  format with no alpha channel — the transparency was not being lost in
  conversion, it could never exist. The icon carries ten sizes from 16 to
  256, each resampled here rather than by the Windows shell at display
  time.

## [1.2.0] — 2026-09-13

Phase 18. The reports say when they have fallen behind.

### Added

- **A notice when the four generated files no longer describe the
  project.** This came out of an actual update: a few documents were
  added, the pipeline scanned, converted, extracted their pages, built the
  windows and classified every one of them — and `index.md`, `timeline.md`,
  `review.md` and `project_instructions.md` went on reporting the previous
  file and window counts, because generating them is a separate step,
  behind its own button, that had not been run. The Result screen showed
  those files with nothing to say they were out of date. The owner found
  out by reading the numbers by hand.

  `generate_all_artifacts` now records, in a one-row table, the three
  counts the files describe: documents, classified windows, and items.
  When they stop matching the database, two screens say so, each with the
  regenerate button beside it — the Result screen whenever they differ,
  naming what changed since the files were written; the Execution screen
  only once there is nothing left to process.

  The two screens use different conditions on purpose. With windows still
  waiting for the model, telling someone to generate the reports would
  produce reports that are incomplete the moment they are written, so the
  Execution screen stays quiet and the honest advice — keep running the
  steps — is what the screen already shows. On the Result screen the files
  on display genuinely do predate the project whatever else is happening,
  so the notice is unconditional.

  Counts, not file timestamps: the output folder is synced by Google
  Drive, and the client rewrites the modification time of files whose
  bytes never changed. Comparing dates here would repeat the mistake the
  update's own detection is built to avoid.

  A project from any earlier version carries no recorded state and is
  never reported stale — there is nothing to compare against, and a
  warning with no ground under it is worse than none. The first generation
  on this version records the state; every one after it is checked.

### Fixed

- **`review.md` counted five of the six file statuses.** The coverage list
  ran through `discovered`, `converted`, `extracted`, `failed` and
  `skipped`, but not `duplicate` — so a file that entered as a copy of one
  already indexed disappeared from the report, and the coverage simply
  failed to add up to the collection with nothing to explain the
  difference. A test now walks every status `scanning.py` writes, so the
  same gap cannot reopen through a status added later.

## [1.1.0] — 2026-09-13

Phase 17. A collection stops having to be reindexed from scratch every
time it changes.

### Added

- **Incremental update.** Point the app at a project whose source folder
  has changed and it now detects what is new, what was edited and what was
  removed, invalidates only what the change actually affects, and
  reprocesses that. Adding one document to a 500-page collection
  reclassifies **one window instead of thirty-six** — roughly a minute
  against eighteen and a half.

  The reason it can be that cheap is the shape of the invalidation.
  Documents are grouped, a group's pages are concatenated, and the
  concatenation is sliced into fixed-size overlapping windows. A change
  does not invalidate a file; it invalidates the group *from the first
  page that moved onward*, because outside library mode a page's reference
  (`f. N`) is counted running through the whole group, so a file that
  gains or loses pages shifts the numbering of every file after it.
  Everything before that point keeps its pages, its references and its
  classification.

  Files after the divergence that did not themselves change are returned
  to `converted`, not `discovered`: extraction re-reads them from the
  already-converted artifact and **they do not pay OCR again**.

- **A confirmation screen, and a notice on the Execution screen.** Opening
  a project whose folder has changed shows how many documents are new,
  edited and removed. The confirmation names the files that will be
  reprocessed and states the cost: how many go through OCR again, how many
  windows are reclassified, how many keep their classification. Two of
  those numbers are exact; the windows a *new* document will add depend on
  its page count, which nothing knows before extraction, so the screen
  says so rather than estimating.

  The notice is fetched after the page renders rather than before it. On a
  large Drive-synced collection the folder walk takes seconds, and paying
  them before the first pixel would trade one problem for another.

- **Removed documents are reported.** A document taken out of the source
  folder leaves `index.md` and `timeline.md`, which describe the
  collection as it is today, and appears in `review.md` — already the
  report of gaps and failures — with the moment it went. A new
  `removed_file` table holds that as state rather than as a log entry,
  which would vanish if the log were cleared.

### Changed

- **Detection reads size and modification time before it reads bytes.**
  The diagnosis runs every time the Execution screen opens, and hashing an
  entire Drive-synced collection each time would force the client to
  download files nobody asked for. The hash still has the last word,
  because Drive rewrites modification times on files whose content never
  changed — without that tie-break the app would report "changed"
  constantly, which is the worst defect a warning can have. A new
  `file.mtime` column stores the comparison value.

- **A group's pages are ordered deterministically** by natural path and
  page number instead of by insertion order. The two coincided in a
  project built in one pass; after an update they would not, and a
  corrected document would have jumped to the end of its group.

### Fixed

Four paths to a wrong index with no error and no warning, three of them
reachable in ordinary use and all found before release:

- **Page geometry was derived from two different sources.** One module
  summed `file.page_count`, another counted rows in the `page` table. A
  file that converts successfully and then fails extraction keeps a
  nonzero count with no pages — one unreadable PDF in a collection — and
  the two disagreed, leaving a window classified over pages that had moved
  beneath it.

- **Classified items outlived their windows.** The invalidation deleted
  window rows, their text files and their pages, but never pruned
  `raw_items.jsonl`, which the classification engine appends to and the
  import step re-reads whole. Items from discarded windows survived with
  stale references, passed validation because the range still fit the
  group, and were merged into live items — so an updated `index.md` could
  attribute pages to a document no longer in the collection.

- **A renamed document was treated as a duplicate of itself.** Its content
  matched the row the update was about to delete, so it was dropped from
  the plan; the following scan then saw a brand-new file and inserted
  pages the plan had never accounted for.

- **The state a successful update leaves behind was misread as a corrupt
  layout**, because the check compared window counts rather than window
  keys. The screen then invited a second update that would have discarded
  everything the first one preserved.

Three further defects, one of them a regression this phase would have
introduced:

- **Clearing intermediate files no longer breaks the next update.** The
  Result screen's "free up disk space" button deletes the `converted/`
  folder, and the renumbering path assumed it was still there: every
  unchanged document after the divergence would have been marked `failed`
  and disappeared from the index permanently, unrecoverable because
  conversion only picks up `discovered` files and a rescan skips them. The
  update now checks the artifact exists and pays OCR again when it does
  not.

- **An unsupported file no longer invalidates a whole collection.**
  Dropping a `readme.txt` into a PDF-only project, or a duplicate copy of
  a document already indexed, made the plan invalidate the entire group
  for a file the pipeline would never index.

- **A recreated window writes its new text.** The text file's name derives
  from window positions, so a document corrected without changing its page
  count produced the same name, and the old text survived beside the new
  classification.

### Migration

Nothing to do. A project created by 1.0.1 opens on 1.1.0 with no manual
step: `removed_file` is created by `CREATE TABLE IF NOT EXISTS` and
`file.mtime` by an `ALTER TABLE` guarded by `PRAGMA table_info`, both
re-executed every time a project is opened. The column starts empty, so
the first update of an existing project hashes the collection once to fill
it in; from the second onward the fast path applies.

### Tests

537 passing, up from 456. The phase adds 81, of which the one that matters
most is an equivalence test: an incremental update must produce artifacts
indistinguishable from a full reindex over the same final folder. Every
other test in the phase exists to explain *why* that one failed when it
fails. It is what caught the `raw_items.jsonl` defect above.

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
  the worst way: a server left running through the night kept old code for
  hours after the fix was saved, spending those hours producing an index with a
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
  information nobody can find again. Benchmarked on a 31-page document,
  five models across three families — `gemma4:e4b`, `qwen3:8b`,
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
  * The model marked `continues: true` on eight consecutive sections of
    the same report that it had itself named correctly — it read
    "continues the same *report*" where the prompt meant "the same
    *subject*". Grouping is now decided in code by comparing subjects;
    `continues` only breaks ties when the wording of one subject changes
    without the document changing (two parts of one section with slightly
    different headings).

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
  No engine showed them to the model. The cost showed on a collection of
  teaching material: classified by a prompt whose only worked examples
  were "OFÍCIO, MEMORANDO, PARECER", almost every item came back with no
  type at all. The model was not failing; it was answering the question it
  had been asked. The `local` engine now builds a context block from those
  fields, framed as *what this collection is* rather than as the task — an
  `extra_rules` entry can be an instruction for the later research use of
  the index, not something a classifier should try to carry out.
- **The prompt asked for documents and accepted pages.** The same run
  produced almost one item per page, sliced a page or two at a time
  straight through documents that ran for dozens. The
  prompt now states the rule explicitly, with the failure it is meant to
  prevent.
- **`ÍNDICE` and `Índice` were two different document types.** Types are
  normalised (upper-cased, whitespace collapsed) on the way in, and the
  words a model returns instead of leaving the field empty (`null`, `N/A`,
  `desconhecido`) are treated as empty rather than stored as types of their
  own.
- **A `desktop.ini` was item number one of an index**,
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
  finding out that one empty field accounted for most of the missing
  points had required querying the database by hand.
- **The VRAM planner made things worse when the model did not fit.**
  Measured on the same machine: with less free VRAM than the model needed,
  it asked for fewer than half of the layers, and Ollama ended up placing
  less of the model on the card than its own split did — the estimate
  replaced the scheduler's split with a worse one and slowed the run down. The per-layer cost here is the file
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
  machine that prompted this work: an 8 GB RX 5700 XT running a 9.1 GB
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
