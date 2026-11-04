## What does this change?

A short description of what this pull request does and why.

## Related issue

Closes #

## How was this tested?

- [ ] The full test suite passes (about five minutes; it never talks to a real Ollama or to the network):
      `& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest -q`
- [ ] I ran the app itself and checked the affected screens by hand (automated tests do not cover visual layout or theme changes; see [CONTRIBUTING.md](../CONTRIBUTING.md))
- [ ] If I added a user-facing string, I added it to the three language tables (`pt`, `en`, `es`) in `gclaude_indexer/i18n.py`
- [ ] If I changed the classifier prompt, the rules vocabulary or the Planalto reader, I re-measured against `demo/gabarito.csv` and updated `docs/QUALITY.md`

## Checklist

- [ ] My change follows the conventions in [CONTRIBUTING.md](../CONTRIBUTING.md): stable ASCII status keys, i18n for all user-facing text, no network calls other than the local Ollama and the opt-in LexML search
- [ ] I did not mix a refactor or rename with a behavior change in the same commit
- [ ] New or changed `.py` files under `gclaude_indexer/` carry the GPL license header
- [ ] Comments that explain a decision say what was measured, where and when
- [ ] Documentation I touched (README, manual, TECHNICAL) keeps the language rules: no em dash as an aside, straight quotes, no inflated vocabulary
