"""Root pytest configuration, loaded before any test module is imported.

Two things have to happen this early:

1. No bytecode cache inside the project folder — it is synced by Google
   Drive, and spec section 11.1 requires every cache to stay local to each
   machine. `pytest.ini` handles `.pytest_cache`; this handles
   `__pycache__`.

2. The interface language is pinned for the whole suite. Since Task 10
   (Phase 14) the default language comes from the Windows UI language, and
   dozens of tests across nine files assert Portuguese text without ever
   setting the `language` cookie. Without this pin those assertions would
   pass only on a Portuguese Windows and fail for any contributor running
   an English or Spanish one — a project about to be published cannot have
   a suite that depends on the machine's own language. It must be set
   before anything imports `gclaude_indexer.web.i18n`, where
   `DEFAULT_LANGUAGE` is computed once at import time.

   `setdefault`, not assignment: whoever exports the variable on purpose
   (to run the suite against another language) still wins.
"""

import os
import sys

sys.dont_write_bytecode = True
# The environment variable as well as the flag: `sys.dont_write_bytecode`
# belongs to *this* interpreter and does not reach the ones the conversion
# tests spawn. Windows uses `spawn` for `ProcessPoolExecutor`, so each
# worker is a fresh interpreter that re-imports `gclaude_indexer` — and,
# without this, writes a `__pycache__` into the Drive-synced project folder
# that section 11.1 forbids. The variable is inherited; the flag is not.
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

os.environ.setdefault("GCLAUDE_INDEXER_LANGUAGE", "pt")
