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

## What's in scope

GClaude Indexer is a local, single-user, offline-by-default Windows
application: the web interface only listens on `127.0.0.1` and has no
authentication, by design (see `docs/SPECIFICATION.md`, section 7). Reports
about things like:

- path traversal or writes outside the configured source/output folders,
- SQL injection,
- unsafe deserialization (`pickle`, `eval`, `exec` over untrusted data),
- a way for the server to become reachable from outside `127.0.0.1`,
- or a way for the program to send data off the machine. The only outbound
  call is the LexML search (on the screen, only with its box checked; in
  `buscar.bat`, also when no act in the collection cites the term), which
  sends the typed term and nothing else; anything beyond that is in scope,

are all very welcome. A report that "the interface has no login" is not a
vulnerability on its own: that is intentional for this application's
threat model (a single user on their own machine). A way to reach the
server from a different machine or process without that user's action
would be.

## What happens next

The maintainer will acknowledge the report, investigate, and work with you
on a fix and a disclosure timeline before any public details are shared.
