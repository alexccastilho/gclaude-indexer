# Security Policy

## Supported versions

Releases are numbered MAJOR.MINOR.PATCH (see [CHANGELOG.md](CHANGELOG.md)).
Only the latest release receives security fixes; there are no maintenance
branches for older versions.

## Reporting a vulnerability

**Please do not open a public issue for a security vulnerability.**

Use GitHub's private vulnerability reporting instead: on this repository's
GitHub page, go to the **Security** tab, then **Report a vulnerability**
(GitHub's own "private security advisory" mechanism). This opens a private
conversation with the maintainer that is not visible to the public until
it is resolved, and is GitHub's recommended channel for this. No email
address is published for this purpose.

If your GitHub account cannot access that tab for this repository (for
example, because the feature isn't enabled on it yet), open a regular
issue asking for a private reporting channel to be enabled, without
including any vulnerability details in that issue itself.

## Automated checks

Every push and pull request is scanned by CodeQL (Python, JavaScript and
the GitHub Actions workflows, `security-and-quality` queries, plus a weekly
run), pull requests go through GitHub's dependency review, and Dependabot
alerts, security updates and secret scanning with push protection are on.
The alerts are in the repository's **Security** tab.

## Components downloaded on demand

Most of the program is installed by the installer. A few components are not,
because they are large or only some collections need them. The program
downloads each of them once, the first time a document needs it, into its own
private folder under `%LOCALAPPDATA%\GClaudeIndexer`, never into the source or
output folders:

- **LibreOffice 26.2.7**, to read old formats (`.doc`, `.ppt`, `.wpd`,
  `.wps`, `.pub`, `.vsd` and others). It comes as the official MSI from The
  Document Foundation and is unpacked by an administrative extraction
  (`msiexec /a`), without elevation and without installing anything in
  Windows. It runs headless, with a pre-seeded profile that turns off macros,
  links and the updater. A LibreOffice 7.6 or newer already installed on the
  machine is also accepted; it is not covered by the SHA-256 pin.
- **FFmpeg 8.1** (LGPL, shared build) and **whisper.cpp b5454**, with the
  whisper ggml models (`base`, `small`, `medium`), to transcribe audio and
  video locally.
- **OCR language data** (`tessdata_fast`), for languages beyond the ones the
  installer brings.
- **libpff-python** (`.pst` and `.ost` from Outlook) is not downloaded at
  run time: it is a pinned dependency installed with the others.

How the downloads are limited:

- Every download comes from a manifest pinned in the repository
  (`gclaude_indexer/manifests/`) that lists the URL, the size and the SHA-256
  of each file. A file whose SHA-256 does not match is refused and deleted.
- Redirects are followed only over HTTPS. The request carries the component's
  name and nothing from your documents.
- ZIP and MSI contents are unpacked with ceilings on the extracted size and the
  number of members, and a member that would leave the target folder is
  refused.
- No shell is involved and external processes run with a time limit.

What this does not mean: the SHA-256 proves that the file is the one the
manifest lists, not that the upstream project is free of flaws. The manifest
pins versions that were chosen on the day of the release; a newer security fix
in LibreOffice or FFmpeg reaches users only in a new release of this program.

Without internet, or when a download is refused, the program keeps working:
documents that need a missing component are skipped with a clear reason, are
not marked as failed, and go back to the queue the next time the step runs.

## Licences and patents

- **LGPL and MPL components.** FFmpeg (LGPL-2.1 or later), `libpff-python`
  (LGPL-3.0 or later) and LibreOffice (MPL-2.0, with parts under other free
  licences) are used as separate programs or libraries that the program calls,
  not modified. whisper.cpp and its models are MIT. `py3langid` (language
  detection) is BSD-3-Clause. The whole project is GPL-3.0, which is compatible
  with these licences; see `requirements.txt` for each package.
- **HEIC and HEVC.** Reading HEIC photos goes through `pillow-heif`, whose
  Windows builds bundle libheif and libde265 (LGPL-3.0) and x265 (GPL-2.0 or
  later). The HEVC format is covered by patents in some countries, and the
  licences of these libraries do not grant patent rights. The program only
  decodes HEIC and never encodes it, but the user, or whoever distributes
  the program, is responsible for checking whether a patent licence is needed
  where they are. If that is a concern, leave the Images category unchecked in New project (it also turns off the other image formats).

## What's in scope

GClaude Indexer is a local, single-user Windows application: it reads and
classifies everything on the machine, and its only network traffic is the one
described in this file. The web interface only listens on `127.0.0.1` and has no
authentication, by design (see `docs/SPECIFICATION.md`, section 7). Reports
about things like:

- path traversal or writes outside the configured source/output folders,
- SQL injection,
- unsafe deserialization (`pickle`, `eval`, `exec` over untrusted data),
- a way for the server to become reachable from outside `127.0.0.1`,
- or a way for the program to send data off the machine. The only outbound
  call is the LexML search (on the screen, only with its box checked; in
  `buscar.bat`, also when no act in the collection cites the term), which
  sends the typed term and nothing else; the other outbound requests are
  the on-demand component downloads described above (OCR language and
  script models, LibreOffice, FFmpeg, whisper.cpp and its models), fetched
  only from the pinned manifests in `gclaude_indexer/manifests/` and refused
  unless the SHA-256 matches, carrying the component's name and no document
  content; anything beyond that is in scope,
- a way for a document to make LibreOffice, FFmpeg or the Outlook reader do
  something on the machine (run a macro, follow a link, read a path outside
  the document) despite the limits described above,

are all very welcome. A report that "the interface has no login" is not a
vulnerability on its own: that is intentional for this application's
threat model (a single user on their own machine). A way to reach the
server from a different machine or process without that user's action
would be.

## What happens next

The maintainer will acknowledge the report, investigate, and work with you
on a fix and a disclosure timeline before any public details are shared.
