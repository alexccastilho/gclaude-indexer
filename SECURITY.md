# Security Policy

## Supported versions

GClaude Indexer does not yet use semantic versioning across releases — see
[CHANGELOG.md](CHANGELOG.md). Until a versioning scheme is adopted, only
the current state of the default branch is supported with security fixes.

## Reporting a vulnerability

**Please do not open a public issue for a security vulnerability.**

Use GitHub's private vulnerability reporting instead: on this repository's
GitHub page, go to the **Security** tab, then **Report a vulnerability**
(GitHub's own "private security advisory" mechanism). This opens a private
conversation with the maintainer that is not visible to the public until
it is resolved, and is GitHub's recommended channel for this — no email
address is published for this purpose.

If your GitHub account cannot access that tab for this repository (for
example, because the feature isn't enabled on it yet), open a regular
issue asking for a private reporting channel to be enabled, without
including any vulnerability details in that issue itself.

## What's in scope

GClaude Indexer is a local, single-user, offline-by-default Windows
application: the web interface only listens on `127.0.0.1` and has no
authentication, by design (see `docs/SPECIFICATION.md`, section 7). Reports
about things like:

- path traversal or writes outside the configured source/output folders,
- SQL injection,
- unsafe deserialization (`pickle`, `eval`, `exec` over untrusted data),
- a way for the server to become reachable from outside `127.0.0.1`,
- or a way for the `local`/`rules` engines to send data off the machine,

are all very welcome. A report that "the interface has no login" is not a
vulnerability on its own — that is intentional for this application's
threat model (a single user on their own machine) — but a way to reach the
server from a different machine or process without that user's action
would be.

## What happens next

The maintainer will acknowledge the report, investigate, and work with you
on a fix and a disclosure timeline before any public details are shared.
