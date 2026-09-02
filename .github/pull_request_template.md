## What does this change?

A short description of what this pull request does and why.

## Related issue

Closes #

## How was this tested?

- [ ] The full test suite passes:
      `& "$env:LOCALAPPDATA\GClaudeIndexer\venv\Scripts\python.exe" -m pytest -q`
- [ ] I ran the app itself and checked the affected screen(s) by hand
      (automated tests do not cover visual layout/theme changes — see
      [CONTRIBUTING.md](../CONTRIBUTING.md))
- [ ] If I added a user-facing string, I added it to all three language
      tables (`pt`, `en`, `es`) in `gclaude_indexer/i18n.py`

## Checklist

- [ ] My change follows the conventions described in
      [CONTRIBUTING.md](../CONTRIBUTING.md) (stable ASCII status keys,
      i18n for all user-facing text, no network calls other than to the
      local Ollama instance)
- [ ] I did not mix a refactor/rename with a behavior change in the same
      commit
- [ ] New/changed `.py` files under `gclaude_indexer/` carry the GPL
      license header
