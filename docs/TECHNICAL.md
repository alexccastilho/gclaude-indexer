**Read this in your language:** **[Português (Brasil)](TECHNICAL.pt-BR.md)** · **[Español](TECHNICAL.es.md)** · English (you are here)

# GClaude Indexer: technical details

This document is for whoever installs, maintains or wants to understand the program from the inside. The [README](../README.md) explains what it is for; the manual inside the program (the **Manual** menu) explains each screen. Here are the requirements, the installation without the installer, what runs in each step, what each output file contains and how to solve problems. Everything that was in the "Technical details" section of the old README is here, revised for 1.8.0.

Contents:

- [Requirements in detail](#requirements-in-detail)
- [Installing without the installer](#installing-without-the-installer)
- [Running day to day](#running-day-to-day)
- [The CPU sensors and the fans](#the-cpu-sensors-and-the-fans)
- [Uninstalling in detail](#uninstalling-in-detail)
- [The screens of the app](#the-screens-of-the-app)
- [Keeping a collection up to date](#keeping-a-collection-up-to-date)
- [Getting a good classification](#getting-a-good-classification)
- [What the index guarantees](#what-the-index-guarantees)
- [Windows, blocks and OCR](#windows-blocks-and-ocr)
- [Classification engines](#classification-engines)
- [Output files](#output-files)
- [Several collections in one Project: sets](#several-collections-in-one-project-sets)
- [Topic search and LexML](#topic-search-and-lexml)
- [OCR and document languages](#ocr-and-document-languages)
- [Running the test suite](#running-the-test-suite)
- [Troubleshooting](#troubleshooting)
- [Documentation](#documentation)

## Requirements in detail

- **Windows 10 or 11, required.** The program talks directly to Windows interfaces: PowerShell, WMI (hardware and resource detection), the registry (Tesseract data and display language) and Performance Counters (CPU and GPU charts). It does not run on Linux or macOS.
- **Python 3.12**, installed for you if it is missing. The project pins dependency versions that newer Pythons (3.13, 3.14) break. The installer looks for 3.12 and, if the machine does not have it, downloads and installs the official 3.12.10 for the current user: no administrator, no manual step. Any other Python already installed stays where it is.
- **OCR** (scanned documents without a text layer) needs Tesseract and Ghostscript. The installer installs both when it can.
- **The `local` engine** needs [Ollama](https://ollama.com), installed by the installer if you accept. The default model follows the graphics card: `qwen3.5:9b` (5.3 GB) on a card with 8 GB of VRAM or more, `qwen3.5:4b` (3.2 GB) on smaller ones. A graphics card is not required: Ollama puts on the GPU what fits and the rest goes to RAM, much slower. With little memory in both, the program switches to the `rules` engine on its own and says why on screen.
- **The `rules` engine** needs none of that: it runs on any Windows able to run Python, without GPU, download or extra software.
- A few gigabytes of free disk for the Python environment and, if you use it, the Ollama model. The intermediate files (OCR'd PDFs and text slices) live in the machine's local folder, `%LOCALAPPDATA%\GClaudeIndexer\work\`, not in the output folder: a large collection produces gigabytes there.
- The interface is in Brazilian Portuguese, English and Spanish, from a menu in the header. The default follows the Windows display language.
- The installer is a convenience for the first setup. The program is not compiled into a single `.exe`: it remains readable Python and PowerShell script, and a desktop shortcut opens it with a double click.

## Installing without the installer

This path also works on a machine where you cannot install programs. In short: run `Indexer.bat` and follow the instructions. Step by step:

**1. Put the source code on your machine.** If you downloaded the project as a `.zip`, right-click it, choose "Extract all..." and pick an ordinary folder (Documents, or a Google Drive folder mounted with a drive letter). If you cloned with Git, you already have a folder. Below it is called "the project folder".

**2. Open PowerShell in the project folder.** In File Explorer, open the folder, hold **Shift**, right-click an empty spot and choose "Open PowerShell window here" (or "Open in Terminal"). Or click the address bar, type `powershell` and press Enter.

**3. You do not need to install Python.** The installer in step 4 needs Python 3.12 and, if the machine does not have it, downloads the official 3.12 from python.org (exact version, checksum verified) into your user folder, without asking for administrator. It sits next to any other Python: if `python --version` shows 3.13 or 3.14 today, it keeps showing that. If you prefer to install it first, this is the same command the installer uses:

```powershell
winget install --id Python.Python.3.12 -e --scope user --silent --accept-package-agreements --accept-source-agreements
```

**4. Run the installer once.** It installs Python 3.12 if missing, creates a private Python environment for this program (outside the project folder, so it survives a folder move or a fresh Drive sync), installs the packages, checks Tesseract and Ghostscript (installing them if missing and you agree) and offers a desktop shortcut.

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1
```

Windows may show "Windows protected your PC" the first time you run a script downloaded from the internet. The `-ExecutionPolicy Bypass` option runs only this script, without changing any permanent setting. The installer shows progress and asks before installing anything (Tesseract, Ghostscript and, optionally, Ollama and the model, which is a large download). If a step fails, it shows the manual command. The first run takes several minutes, mostly downloading packages.

**5. Accept the desktop shortcut**, if you want it. A second, optional shortcut, "GClaude Indexer (CPU sensor)", asks for administrator every time it opens, only for the sensor reader (see the next section). You can change your mind later with `install.ps1 -CpuSensorShortcut`.

## Running day to day

Double-click the desktop shortcut. A console window appears only the first time, if the installer still needs to run; after that the program starts with no visible window and opens the browser at:

```
http://127.0.0.1:8000
```

The server listens only on `127.0.0.1`, your own machine. It is never reachable from the network or from another computer.

Without the shortcut, from the project folder:

```powershell
python launcher.py
```

That checks the environment and installs whatever is missing before starting the server, so it also works on a machine where you have not run the installer yet.

To close the program, close the terminal window it opened (or, if it is running hidden through the shortcut, end `pythonw.exe` in Task Manager).

**Updating the program.** Install the new version on top, without uninstalling: the installer closes the old version if it is running, and your projects stay where they are. If a server from another version is still up when you open the program, the new one replaces it and says so.

**What the installer writes for Ollama.** So that the graphics card is used in full, the installer writes user environment variables that Ollama reads when it starts. The program passes the same ones to the server it starts itself when none is running, and the two must agree:

| Variable | Value | Why |
|---|---|---|
| `OLLAMA_MAX_LOADED_MODELS` | `1` | one model at a time on the card |
| `OLLAMA_NUM_PARALLEL` | `1` | one request at a time; parallelism did not help in the measurements (02/11/2026) |
| `OLLAMA_FLASH_ATTENTION` | `1` (or `0` on Radeon RX 5000/6000) | on RDNA 1 and 2 through Vulkan, flash attention doubles the time to read the passage; measured on an RX 6700 XT |
| `OLLAMA_KV_CACHE_TYPE` | `q8_0` (or `f16` with flash attention off) | Ollama only compacts the cache when flash attention is on |
| `OLLAMA_GPU_OVERHEAD` | `0` | no artificial VRAM reserve |
| `OLLAMA_KEEP_ALIVE` | `30m` | the model stays loaded between one window and the next |
| `LLAMA_ARG_CACHE_RAM` | `0` | no prompt cache in RAM: the runner reserved 8 GB that were never reused here (each window is a new request) and looked like a model spilling over |

A value you changed yourself is respected and said on the console; the uninstaller removes only what the installer wrote. The log of the server the program starts is in `%LOCALAPPDATA%\GClaudeIndexer\ollama-serve.log`, and the run log says which card and which backend (CUDA, ROCm or Vulkan) Ollama is using.

## The CPU sensors and the fans

CPU temperature, power and fan speed can only be read with administrator privilege: the fan sits on the motherboard's SuperIO chip, which Windows exposes only to a kernel driver. There are two ways to ask, both optional. The **Read CPU sensors and fans** button, on the Run screen, asks on demand, as many times as you want, and explains in one line what Windows is going to ask. The "GClaude Indexer (CPU sensor)" shortcut asks by itself every time you open the program. What runs with privilege is not the program: it is a small helper process whose only job is to read the sensors and return the numbers. The server, the indexing and your documents run without privilege, and the helper closes with the program.

Answering **No** is safe and costs nothing: the program opens as through the ordinary shortcut, showing temperature, power, frequency, VRAM in use and the model loaded on the GPU, and "requires administrator, click Read sensors" for CPU temperature, power and fan. Nothing fails and the button stays available.

What the screen shows and why:

- **"stopped"** is a real reading of 0 RPM. Modern graphics cards stop the fan when they are cool.
- **"requires administrator, click Read sensors"** means the value exists but cannot be read without the helper.
- **"not measured"** means the machine has no sensor the library can read. On laptops the fans belong to the embedded controller and only the manufacturer exposes them; Dell laptops are read through Dell's own interface.
- **CPU temperature and power on recent processors** may need the PawnIO driver, which the installer offers as an optional item (Windows asks for administrator to install it).
- **VRAM in use** and **Model on the card** appear when there is a graphics card: that is how you see whether the model fit entirely on it.

The CPU fan is chosen by the sensor's name, when the board gives one, or by the chip's fixed CPU header; the program never shows "the first fan that spins" as if it were the CPU's. The elevated reader is relaunched when needed after the computer restarts.

## Uninstalling in detail

If you installed with the Windows installer, use Settings > Apps.

Otherwise, double-click `Desinstalar.bat` in the project folder (the same as `Indexer.bat`), or from the prompt:

```powershell
.\Desinstalar.bat
powershell -ExecutionPolicy Bypass -File uninstall.ps1
```

**Why not simply `.\uninstall.ps1`?** Google Drive marks every file it syncs as coming from the internet, and the default Windows execution policy (RemoteSigned) refuses to run such a `.ps1` without a digital signature. There is nothing wrong with the script: `Desinstalar.bat` passes `-ExecutionPolicy Bypass` for that run, like every launcher in this project. Running `install.ps1` also clears that mark from the scripts in the folder.

It asks item by item, and the default answer is always **no**. It separates what this installation owns (the virtual environment, the shortcuts, the sensor libraries, the local settings, the PATH entries and the environment variables it created) from the ordinary programs it merely installed for you: Tesseract, Ghostscript, Ollama, Python and the models downloaded by Ollama. Other programs may be using those, so each one is offered separately.

**It never deletes your projects.** The output folders, the databases and the generated reports are your documents. The script lists where they are, with the size of each, and leaves the decision to you.

Three options cover the non-interactive uses:

```powershell
powershell -ExecutionPolicy Bypass -File uninstall.ps1 -WhatIfOnly        # shows the plan, removes nothing
powershell -ExecutionPolicy Bypass -File uninstall.ps1 -KeepDependencies  # keeps Tesseract, Ghostscript, Ollama, Python
powershell -ExecutionPolicy Bypass -File uninstall.ps1 -RemoveAll         # says yes to everything (except your projects)
```

The project folder itself, if it is synced by Google Drive, is never touched: delete it there if you want it gone from every computer.

## The screens of the app

The interface has seven screens, plus **Manual** and **About**:

1. **Projects**: every project this computer knows, with creation date and status. It is where the program opens.
   - **Shared catalog**: point it at a folder inside Google Drive and every computer connected to that Drive sees, opens, edits and deletes the same projects. Without it, the list of projects stays on this machine only, even with the projects synced. Projects stored on another computer's local disk appear marked as out of reach.
   - **Open existing project** takes a folder you point at and reopens the project in it: after a reinstall, on a new machine, for a folder you moved or someone sent you. Nothing is recreated; the output folder already holds the whole project.
   - **Delete** offers two choices: only remove the project from the list, or also delete the generated files. In that case the program deletes only what it created itself (database, reports, `buscar.bat`, the local work folder). Your files in the output folder stay, and the folder only disappears if it ends up empty. In `project_instructions.md` and `CLAUDE.md` only the generated block goes. The source folder is never touched.
2. **New project**: source folder, output folder, which file types to include, how to group the documents and which engine to use. When you choose the source folder, the program proposes a configuration from what it finds there (file types, grouping, language). Every field has a default and a "?" hint.
3. **Run**: one line per step (scan, conversion, per-page extraction, window preparation, classification), each with a button to run it, a progress bar with a time estimate, and the **Pause** and **Resume** buttons. Pause answers right away ("stopping") and resuming continues from where it stopped. Below, a live log in plain language and the CPU, RAM and GPU charts, with the sensors. While the folder is being walked, a counter shows how many files have been seen. A separate button, **Import and generate reports**, turns the classified items into the output files. Every long operation shows up in an activity bar with a name and a stopwatch, which survives an F5; asking for another operation on a busy project leads to an "in progress" page, with nothing lost. If the source folder changed since the last run, a notice appears at the top shortly after the page loads.
4. **Update collection**: reached from that notice. It lists the new, edited and removed documents, names the ones that will be reprocessed and states the cost: how many files go through OCR again (including those whose OCR failed last time), how many windows are reclassified, how many keep their classification, and which documents will have their sheet numbering changed. Nothing changes until you confirm. If the source folder cannot be read (disk disconnected, folder moved), the screen says so and offers nothing: an unreachable folder is never mistaken for a collection whose documents were all deleted.
5. **Result**: the quality score, the pending items, a preview of each generated file, the package for Claude with the token budget and the list of what was left out for size, a button to open the output folder and **Free up space**, which deletes the intermediate files in the local work folder (OCR'd PDFs and text slices). The database, the reports and the logs are never touched by it.
6. **Search the collection**: full-text search over the project's pages, with the excerpt and the page of each result. An optional box also queries the Senate's LexML (see [Topic search and LexML](#topic-search-and-lexml)).
7. **Sets**: several collections in a single Claude Project (see [Several collections in one Project](#several-collections-in-one-project-sets)).

The header of every screen has a language selector, a theme selector (Light, Dark, Sepia, High contrast, Aurora, Toga, Graphite and Ocean) and a layout selector (Standard, Technical, Editorial and Compact). The choices are stored in your browser. Motion between screens is turned off when Windows asks for less motion.

## Keeping a collection up to date

A collection changes: documents arrive, a scan is replaced by a better one, something is withdrawn. None of that requires indexing everything again.

Open the project. A few seconds after the Run screen appears, if something changed in the source folder, a notice says how much ("14 new, 3 edited, 1 removed"). Follow it to **Update collection**, look at the plan and confirm. Then run the steps as usual: they find only the work the update left. Adding one document to a 500-page collection reclassifies one window instead of thirty-six: about one minute instead of eighteen and a half. A second scan does not reread unchanged files.

**One step is not part of "Run everything".** Turning the classified items into the Markdown files is its own button, **Import and generate reports**, on the Run screen. Classification finishing does not write them. If you skip that step, the reports keep describing the collection as it was before. The program reminds you: when nothing is left to process, a notice with the button appears, and the Result screen says when the files shown predate the project and what changed since. After updating, send the new files to your Claude Project.

**Why it is not the whole collection.** Documents are grouped, and the pages of a group are read as one long sequence, sliced into overlapping windows; the windows are what the classification engine reads. A change invalidates the group from the first page that shifted. Everything before it keeps its pages and its classification. A document added at the end of a group costs almost nothing; one inserted at the start shifts every page after it and costs more. The screen tells you which case you are in before you confirm.

**Removed documents.** The pages and items leave the index, the converted copy is deleted, and the name and moment of the removal are recorded in `review.md`. If the folder had an identical copy of the removed document, that copy is indexed in its place. If a whole group disappears, its `index-<group>.md` is deleted.

**Sheet numbering that changes.** In a case-file collection, the sheet numbering (f. 1, f. 2...) runs continuously through the group. Adding or removing a document in the middle changes the numbers of the following documents. The confirmation screen lists which ones and the log warns: old conversations with Claude that cited those sheets may be out of date.

Documents that only need renumbering do not go through OCR again: the converted files are still in the local work folder and are reread. Only a document whose content changed pays that cost. A file whose OCR failed is redone in the next conversion, and the step stays "pending" while there is one like that.

**If you cleared the intermediate files** with Free up space, the documents that would be reread need to be converted again. The update handles that correctly; it just takes longer.

**If the source folder cannot be reached** (the disk is disconnected, the folder was moved or renamed), nothing is offered and nothing is changed.

**One computer at a time.** While a project is open, it is locked to that computer. Another computer is told who is using it. Closing the browser releases the lock in about five minutes; a lock from a machine that crashed expires on its own in ten.

## Getting a good classification

Two things decide more about the result than anything else.

**Fill in the collection's Subject and Collection type in New project.** The `local` engine shows those fields to the model, and they are what tells it what kind of document it is reading. A collection described only with the defaults ends up classified against generic examples, and the model answers "don't know" for almost every type. One sentence about the collection (what it is, where it came from, what documents it has) is the most effective thing you can do for the result. **Role in the instructions** and **Extra rules** are also passed along, as context.

**Which model to use.** Measured in this project, over the same windows of one document, with every model running entirely on an 8 GB card:

| Model | Size | Type filled | s/window |
|---|---:|---:|---:|
| `qwen3.5:4b` | 3.0 GB | 100% | 30.8 |
| `gemma4:e4b` | 3.1 GB | 79.5% | 38.5 |
| `qwen3.5:9b` | 5.3 GB | 79.5% | 86.2 |
| `qwen3:8b` | 5.4 GB | 100% | 108.8 |
| `granite4.2:8b` | 5.7 GB | 100% | 116.9 |

In that measurement, `qwen3.5:4b` reached the quality of the best one in a quarter of the time and with half the VRAM. Measured later against an answer key, on the demo collection (72 pages, 41 items), `qwen3.5:9b` got the date (88.6%) and the author (84.4%) right more often and took 4 min 12 s, against 4 s for the rules engine; the full numbers and what they do not say are in [QUALITY.md](QUALITY.md). That is why the default since 1.5.14 is `qwen3.5:9b` on a card with 8 GB or more and `qwen3.5:4b` on smaller ones. Describing a page is reading and format discipline; size alone does not buy quality and costs time.

**Choose a model that fits on your graphics card.** What does not fit in VRAM, Ollama runs on the CPU, and the difference is large. On an 8 GB card, a 9.1 GB model ran with 17% of itself on the GPU; a 5 GB model ran entirely on the GPU. The Run screen shows the card's VRAM, the VRAM in use and the loaded model; the About screen lists the installed models; the log warns when the chosen model does not fit and says which card and which backend are in use. A model that fits and finishes is worth more than a bigger one that spends the whole run spilling over.

**Context from the hardware.** The size of the context sent to the model (`num_ctx`) has a ceiling computed from the card's VRAM and the RAM, so that the model and the cache stay entirely on the card. A large passage is never cut silently: the request goes with `truncate: false`, and a passage that does not fit is split into two requests. A response that comes back incomplete is requested again with a larger context or a smaller window.

If the quality score looks low, open the log: it reports how the GPU is being used. On the Result screen, the score is broken down into confidence, field completion and penalties. The score is based on what the engine itself declared; it is not a measure of real accuracy. To measure accuracy, use the demo collection and `tools/medir_acerto.py` ([QUALITY.md](QUALITY.md)), or check a sample of items from your own collection.

## What the index guarantees

Three properties hold no matter how well the model does its job, because the code enforces them.

**Every page reaches the index.** A page the model never mentioned still gets an entry, with its reference, the file and its own text as the summary, because the grouping walks the pages of the window, not the model's answer. An item that fails validation is discarded, but its pages come back as a low-confidence entry instead of disappearing with it. An index that silently omits a page is worse than no index: what is missing is invisible.

**A whole document is always its own item.** A file that is a single document (HTML, Word, e-mail, spreadsheet) starts a new item, even if the model joined it to the previous document. On a legislation page, the heading ("LEI Nº 8.078, DE 11 DE SETEMBRO DE 1990") becomes the item's type. The author of an act is read from the full text, and each author and each type have a single spelling across the whole index.

**Dates keep the precision the document actually has.** Documents dated by period ("competência 01/2020", "exercício 2019") are stored as `2020-01` and `2019`, not completed to a first day of the month the page never stated. ISO 8601 allows the reduced form, and it still sorts correctly in `timeline.md`. A date whose day does not exist (`2021-09-31`) falls back to the month; text that is not a date leaves the field empty, and the item keeps everything else.

## Windows, blocks and OCR

A **window** is a run of consecutive pages that the classifier reads at once to find where each item starts and ends.

**Pages per window** is what affects quality most: it is how many pages go in each request to the model, which answers with one line per page. The form default is 16. When the local engine was tuned, 8 gave the best results: with 16, the answer passed 3,500 tokens and was truncated, and with 4 you triple the number of requests with no gain. Since 1.3.2, the local engine notices when an answer comes back incomplete and tries again with a larger context or by splitting the window. If the score is low with the local model, try 8. Many short mixed documents do better with smaller windows; long, standardized documents tolerate larger ones.

**Pages per block** does not affect the index. It only cuts very large PDFs into auxiliary files inside the local work folder, which nothing else reads and which Free up space deletes. Leave it at 80; reduce it only if a very large PDF (500+ pages) makes the conversion run out of memory.

**OCR** applies only to pages without a text layer; the program checks page by page and leaves alone the ones that already have text. A PDF with native text and a few scanned sheets in the middle gets OCR only on those sheets (since 1.5.2), and a digitally signed PDF also gets OCR. A fully scanned PDF goes through a dedicated OCR configuration (the `configs/` folder), which improved the result on the demo collection's scans. Then what matters is that the **OCR language** matches your documents. The conversion runs in two queues (OCR and the rest) and has a per-file deadline: a file that hangs does not hold up the others, and an OCR that failed is redone in the next conversion.

**Files read as text.** HTML and other web pages are read as text (struck-through text becomes `~~like this~~`, so the classifier knows it was crossed out); the encoding of text files and e-mails is detected (UTF-8, Windows-1252 and others); Word hyperlinks are kept. `.ini` files are never indexed, and binary files without text appear among the pending items with the reason.

## Classification engines

Classification (deciding what each page is, who wrote it and when) is the only step where you choose how the work is done. All the others (scan, OCR, extraction, search, report generation) are identical whatever the engine, and always run locally.

| Engine | Cost | Leaves the machine? | Needs |
|---|---|---|---|
| `rules` | free | no | nothing: runs on any Windows machine |
| `local` | free | no | Ollama, installed automatically; faster with a GPU, works without one |
| `claude_code` | your existing Claude subscription | **yes** | Claude Code already installed on this machine |
| `automatic` | | | picks `local` if the hardware can take it, otherwise `rules`; never picks `claude_code` on its own |

**`claude_code` is entirely optional.** The program works from start to finish without it. Choose it only if you already use Claude Code and want it to do the classification. The program then writes a `CLAUDE.md` in the output folder and shows a sentence to say to Claude Code (`process the windows`); open Claude Code in the output folder, say the sentence and, when it finishes, click **Recheck if the windows are done**. That `CLAUDE.md` tells Claude Code to treat the documents' text as untrusted data, never as instructions.

`rules` is deterministic: it looks for known document-type markers, date patterns and signature blocks, with no machine-learning model, so the result is reproducible and needs no installation. `local` uses an open model served by [Ollama](https://ollama.com) on your own machine (`http://127.0.0.1:11434`, never a remote address, never through a proxy) and generally gives better results than `rules`, at the cost of the disk space, the download and (optionally) the GPU listed under Requirements. With a graphics card, the local engine waits for Ollama to come back instead of falling back to the rules; without one, it falls back and returns to the model when it answers.

**Planalto legislation.** `.htm`/`.html` pages saved from the Planalto site (laws, decrees, provisional measures, ordinances, resolutions, acts of the Empire) are read from the page's own structure, with no model: type, number, date, author and summary come from the heading and the header. No engine is consulted for them, and the result feeds `normas-citadas.md`.

**Review low confidence**, in New project, runs `rules` on everything and sends only the low-confidence items to a second engine of your choice: a middle ground between the zero cost of `rules` and the accuracy of a stronger engine on the pages that need it. The Result screen has a table to compare engines and models run over the same collection.

## Output files

Written to the output folder you chose, in the language the interface is in when you generate them:

- `index.md`: the summary. It lists the groups and says which index file to open for each; it counts the legislation pages and points to `normas-citadas.md`.
- `index-<group>.md`: one index per group. Each item with sheets or pages, type, date, author, file and page within the PDF, and a summary. A group index above 25 MB comes out in parts `index-<group>-1.md`, `-2.md`..., breaking only between source files. The lines are lean: the file name is not repeated in the Range column, and the Confidence column only appears when some line is in doubt.
- `normas-citadas.md`: one line per norm recognized in the collection (law, decree, provisional measure, ordinance...), with type, number, date, summary, which groups and pages it appears in and a link to the text on LexML. It replaces the old per-group legislation file (`legislacao-*.md`), which ceased to exist in 1.8.0 (an old project loses that file at the next generation). It only exists when there is at least one norm.
- `timeline.md`: the dated items in chronological order, without the Planalto acts. A group with more than 2,000 dated items gets its own `timeline-<group>.md`, which stays out of the Claude package (it repeats the group's index by date); the Result screen shows its size.
- `review.md`: a checking report: what was read, gaps, failures, what is still pending, and the documents removed from the source folder, with the moment each one left. The index and the timeline describe the collection as it is today; this is where you find out what used to be in it.
- `project_instructions.md`: instructions for a Claude Project, built from the fields you filled in New project, including how to use the index, how to find a norm in `normas-citadas.md` and the rule of always checking values in the original document.
- `buscar.bat`: the topic search for Claude Code, described in [Topic search and LexML](#topic-search-and-lexml).
- `project.db`: the project database. It holds everything, including the text of every page and the search index.
- `CLAUDE.md`: only when you use the `claude_code` engine or write a set to a folder.

The intermediate files (OCR'd PDFs in `converted/`, text slices in `blocks/`) live in `%LOCALAPPDATA%\GClaudeIndexer\work\<project>\`, outside the output folder, since 1.5.8: an output folder on Drive does not sync gigabytes that only this machine uses. An old project that still has those folders in the output is still read from there.

**Your text in these files is preserved.** In `project_instructions.md` and `CLAUDE.md`, the generated content sits between `<!-- GCLAUDE-INDEXER:BEGIN ... -->` and `<!-- GCLAUDE-INDEXER:END -->`. Generating the files again redoes only that block; what you wrote outside it stays, and is not repeated at each generation. If the output folder already had a `CLAUDE.md` of yours, it is kept and the block is appended, with a `.bak` copy of the original the first time. The text pasted into **Instructions you already use** goes to the top of `project_instructions.md`.

The Result screen also offers a `.zip` package with these files and a short guide. The guide says to paste the whole `project_instructions.md` into the Project's instructions and upload `index.md`, the `index-<group>.md` files, `normas-citadas.md`, `timeline.md` and `review.md` as project knowledge.

**The limits of a Claude Project, and how the program handles them.** A Project accepts 30 MB per knowledge file and only reads text (a `.zip` is not read). Everything you upload has to fit in the context window; above about 500 thousand tokens the Project switches to automatic search over the files, which works up to a few million tokens and degrades after that. That is why the Result screen shows, before the download button, each file that goes in the package with its size and estimated tokens, and warns at those two levels (the token ceiling is adjustable per project; the default is 2 million). A file above 30 MB never goes into the package, because the Project would refuse it: the screen lists what was left out. In most cases, generating the reports again is enough for the index to come out in parts below 30 MB; the exception is a single source file whose index, by itself, exceeds 30 MB, because the index is only split at the boundary between files. The program keeps the package small by leaving the norms' text out (Claude opens them through the link in `normas-citadas.md`), by not repeating the index in the timeline, by slicing indexes above 25 MB and by omitting what carries no information.

## Several collections in one Project: sets

The **Sets** screen builds a single package from two or more projects, for a Claude Project that answers about all of them. Each project in the set gets a short alias (proposed from the name: "Diretoria / Região Sul" becomes `diretoria-regiao-sul`), and in the combined package every file carries the alias as a prefix: `diretoria-regiao-sul__index.md`, `contratos__index-Processo.md`. The links inside the summaries and the timelines are rewritten to the prefixed names, so no name collides even when two projects have the same group. A single `project_instructions.md` comes out with the set's personal text at the top, a section "Which collection to look in" and one section per collection. The token budget is added up and the ceiling is the lowest among the projects.

A member whose folder is out of reach on this computer (another machine's Drive), whose database does not open or which never generated reports stays out of the package, with the reason on screen, and remains in the set. Sets are stored in `%LOCALAPPDATA%\GClaudeIndexer\sets.json`, on this machine.

**Write to the folder** writes the same files to a folder of your choice, plus a combined `CLAUDE.md` that tells Claude Code where each collection is and how to search each one. The folder cannot be a collection's source or output folder. Writing again updates only what changed, keeps what you wrote outside the marks and deletes the files of an alias that no longer exists.

## Topic search and LexML

At the end of extraction, the text of every page goes into a search index (SQLite FTS5) inside `project.db`; the step only finishes when the search is ready. The **Search the collection** screen queries that index and shows, for each result, the file, the page and the excerpt.

**For Claude Code**, the output folder gets a `buscar.bat`: `buscar.bat saneamento` lists the files and pages where the term appears, grouped by file, with the norm's link next to legislation excerpts. The `CLAUDE.md` explains the command. The `.bat` calls the program's own Python with this machine's paths and is rewritten at each generation. Options: `--grupo` restricts to one group, `--so-legislacao` shows only norms, `--limite` limits the count, `--lexml` also queries LexML.

**LexML.** [LexML](https://www.lexml.gov.br) is the Senate portal that catalogs Brazilian legislation. With the "Also search LexML" box checked on the search screen (in `buscar.bat`, with `--lexml` or when no act in the collection cites the term), the program asks the portal's search service (SRU) for the norms that deal with the term, sending nothing from your collection beyond the typed term. On 02/11/2026 the portal started answering searches from programs with a security verification page; in that case the program says so and shows the link to open the search in the browser. The program never tries to get around the verification. The links of each norm (`https://www.lexml.gov.br/urn/...`) still open normally.

## OCR and document languages

New projects use OCR in Portuguese (`por`) by default, since the project was born for collections in Brazilian Portuguese.

The Tesseract package for Windows ships only `eng` and `osd`, so `install.ps1` downloads the data for the language the project uses (`por`, by default), with the SHA-256 verified. When Tesseract's `tessdata` folder requires administrator (the common case), the data goes to this machine's folder (`%LOCALAPPDATA%\GClaudeIndexer\tessdata`), and the program points Tesseract at it only in its own process, without asking for administrator. The program also does that when it opens, so a missing language is fixed as soon as the machine is online.

If your collection is in another language, change the **OCR language** in New project to the Tesseract code (for example `eng` for English, `spa` for Spanish, or `por+eng` for both in the same collection) and install that language's data:

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1 -OcrLanguage spa
```

The installer only installs languages whose SHA-256 it has pinned: today `por`, `eng`, `spa` and `osd`. It never downloads a file it cannot verify; for any other language, it shows where to get the file and where to put it.

## Running the test suite

If you are contributing changes, or want to confirm everything works after installing, use the Python inside the environment the installer created (not the `python` your PATH finds):

```powershell
& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -B -m pytest -q
```

A correct run ends with a line like `1197 passed, ... warnings in ...s` and no failures. The number of tests grows over time; the warnings come from third-party libraries, and the count may vary between machines. The suite does not talk to the real Ollama or to the network, and never stops the machine's Ollama. See [CONTRIBUTING.md](../CONTRIBUTING.md) for the full setup of a development environment. The GitHub CI runs the suite and indexes the demo collection at every push, attaching the accuracy report to the run.

## Troubleshooting

- **A notice says the system was updated after the window opened.** The code on disk changed while the server was running, and Python loads modules once, at startup. Close the program and open it again from the shortcut.
- **The browser opens but the page never loads.** Wait a few seconds on the first run. If it keeps not loading, check whether another program is using port 8000.
- **"Request refused" appears.** Something other than the program's own screens (usually a website) tried to send a command and was blocked. Always open the program from the shortcut or at `http://127.0.0.1:8000`.
- **"database busy" or "operation in progress" appears.** Another operation is using the project (a conversion, a report generation). Nothing was lost: wait for the activity bar to finish and try again.
- **"python is not recognized..." in PowerShell.** Python is not on the PATH. Reinstall it with the `winget` command under *Installing without the installer*, or use the full path shown under *Running the test suite*.
- **OCR fails or produces no text.** Check that Tesseract and Ghostscript are installed (`install.ps1` checks) and that the language pack for your documents is installed (see *OCR and document languages*). A file whose OCR failed is redone in the next conversion.
- **The `local` engine falls back to `rules`.** It only happens on a machine without a graphics card: Ollama is not running, or the VRAM and RAM together are not enough for the model. It is not an error: the program degrades on purpose instead of failing, and returns to the model when Ollama answers. With a graphics card, it waits for Ollama instead of falling back. The About screen shows the installation diagnosis and `ollama-serve.log` what the server said.
- **The graphics card is almost empty and the RAM full during classification.** Check in the log which backend is in use and whether the model fit. On a Radeon RX 5000/6000, check that `OLLAMA_FLASH_ATTENTION` is `0` (the installer does that); on any card, `LLAMA_ARG_CACHE_RAM=0` avoids 8 GB of prompt cache in RAM.
- **Nothing works until I restart after installing.** Fixed: the installer records where it put each program and `Indexer.bat` reloads the PATH from the registry. On an old installation, run `install.ps1` once more.
- **I reinstalled (or formatted) and my projects vanished from the list.** They did not: they are in their output folders, and only the list was recreated empty. Use **Projects > Open existing project** and point at the output folder. Never point **New project** at a folder that already has a project: the program prevents it.
- **My projects do not show up on the other computer.** Projects sync through Drive, but the list stays on each machine until you set up a shared catalog. Open **Projects > Shared catalog**, choose a folder inside your Drive and save, on both computers, pointing at the same folder.
- **"Project in use on another machine".** Close the program on the other computer. If it crashed or was shut down, wait for the lock to expire or choose **Take over anyway**, only if you are sure the other one is not using it.
- **"Incomplete sync signal" when opening a project on a second machine right after the first.** Wait for Google Drive to finish before opening elsewhere. The program detects incomplete syncs and the other machine's lock, but it does not replace the wait.
- **Failed files among the pending items.** Usually password-protected, corrupted or binary files without text. Save an unprotected copy in the source folder and update the collection.
- **The LexML search says the Senate asked for verification.** The portal answers programs with a verification page; open the link shown and search in the browser. The program does not get around the verification.

## Documentation

- [README.md](../README.md): what the program is for and how to start.
- [QUALITY.md](QUALITY.md): the accuracy measured against an answer key on the demo collection, and what the numbers do not say.
- [CONTRIBUTING.md](../CONTRIBUTING.md): setting up the development environment, how to run a single test and the project's conventions.
- [SPECIFICATION.md](SPECIFICATION.md): the technical specification, in English: data model, each processing step, security rules and design decisions.
- [CHANGELOG.md](../CHANGELOG.md): what changed, version by version. It is the original; the Portuguese and Spanish versions follow it.
- [SECURITY.md](../SECURITY.md): how to report a vulnerability.
- [CODE_OF_CONDUCT.md](../CODE_OF_CONDUCT.md): the rules of conduct for contributors.
- `demo/README.md` and `tools/README.md`: the demo collection and the command-line tools.
