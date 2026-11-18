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
from pathlib import Path

sys.dont_write_bytecode = True
# The environment variable as well as the flag: `sys.dont_write_bytecode`
# belongs to *this* interpreter and does not reach the ones the conversion
# tests spawn. Windows uses `spawn` for `ProcessPoolExecutor`, so each
# worker is a fresh interpreter that re-imports `gclaude_indexer` — and,
# without this, writes a `__pycache__` into the Drive-synced project folder
# that section 11.1 forbids. The variable is inherited; the flag is not.
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

os.environ.setdefault("GCLAUDE_INDEXER_LANGUAGE", "pt")


import pytest


@pytest.fixture(autouse=True)
def _test_client_host():
    """`TestClient` talks to the app as `http://testserver`. The app accepts
    only loopback hosts (see `_request_is_trusted` in `web/app.py`), so the
    suite adds that one name — for its own run, never in the shipped code."""
    import gclaude_indexer.web.app as app_module
    added = "testserver" not in app_module.ALLOWED_HOSTS
    app_module.ALLOWED_HOSTS.add("testserver")
    yield
    if added:
        app_module.ALLOWED_HOSTS.discard("testserver")


# What the suite may still read from the real per-machine folder: the tools
# and components this machine downloaded (Python packages in `lib`, OCR
# models, Ghostscript), which several conversion tests need. Everything
# else there is the user's own data — catalog, sets, sync state.
_SHARED_LOCAL_FOLDERS = ("lib", "tessdata", "gs", "helper")
_SHARED_LOCAL_FILES = ("tools.json",)


def _real_local_folder() -> Path:
    from gclaude_indexer import paths

    override = os.environ.get(paths.LOCAL_FOLDER_ENV, "").strip()
    if override:
        return Path(override)
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "GClaudeIndexer"


def _prepare_local_folder(folder: Path, real: Path) -> None:
    """Components through junctions (read where they are, never copied),
    `tools.json` copied, none of the user's files."""
    import shutil

    for name in _SHARED_LOCAL_FILES:
        if (real / name).is_file():
            shutil.copy2(real / name, folder / name)
    if sys.platform == "win32":
        import _winapi

        for name in _SHARED_LOCAL_FOLDERS:
            if (real / name).is_dir():
                _winapi.CreateJunction(str(real / name), str(folder / name))


def _remove_junctions(folder: Path) -> None:
    """Junctions out before pytest cleans its temporary folders, so that
    cleanup never walks into the real components. `os.rmdir` removes a
    junction itself and refuses a folder that is not empty."""
    for name in _SHARED_LOCAL_FOLDERS:
        if os.path.lexists(folder / name):
            os.rmdir(folder / name)


@pytest.fixture(scope="session", autouse=True)
def _session_local_folder(tmp_path_factory):
    r"""The per-machine folder for the whole process, holding no user data.

    `paths.machine_local_folder` holds the project catalog, the sets and the
    sync state next to the downloaded components. Isolating it was opt-in
    per test, and one test that forgot (`POST /projects/new`) wrote a "Norm"
    project into the real `%LOCALAPPDATA%\GClaudeIndexer\projects.json` on
    every run: 48 of them showed up in the app.

    Set in the process environment, not through `monkeypatch`: a background
    operation a test started may finish after that test's teardown, and must
    still land here rather than in the real folder."""
    from gclaude_indexer import paths

    real = _real_local_folder()
    folder = tmp_path_factory.mktemp("local-session")
    _prepare_local_folder(folder, real)
    previous = os.environ.get(paths.LOCAL_FOLDER_ENV)
    os.environ[paths.LOCAL_FOLDER_ENV] = str(folder)
    yield real
    if previous is None:
        os.environ.pop(paths.LOCAL_FOLDER_ENV, None)
    else:
        os.environ[paths.LOCAL_FOLDER_ENV] = previous
    _remove_junctions(folder)


@pytest.fixture(autouse=True)
def _machine_local_folder(_session_local_folder, tmp_path_factory, monkeypatch):
    """Each test on top of that gets a folder of its own, so no test reads
    what another one left there (a sensor snapshot, a catalog entry). A
    test that sets the variable itself still wins: its own
    `monkeypatch.setenv` runs after this one."""
    from gclaude_indexer import paths

    folder = tmp_path_factory.mktemp("local")
    _prepare_local_folder(folder, _session_local_folder)
    monkeypatch.setenv(paths.LOCAL_FOLDER_ENV, str(folder))
    yield
    _remove_junctions(folder)


@pytest.fixture(autouse=True)
def _local_work_folder(tmp_path_factory, monkeypatch):
    r"""Since 1.5.8 conversion writes its intermediates under the per-machine
    folder (`workdir.py`). Each test gets its own, so the suite never fills
    the real `%LOCALAPPDATA%\GClaudeIndexer\work` nor sees another test's
    files. Its own variable, not the per-machine folder's, which other tests
    set to check where that folder resolves."""
    monkeypatch.setenv("GCLAUDE_INDEXER_WORK_FOLDER", str(tmp_path_factory.mktemp("work")))
