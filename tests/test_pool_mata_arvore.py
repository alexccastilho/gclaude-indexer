"""2.1.6: descartar o pool mata também os filhos do trabalhador.

Um trabalhador da conversão roda o Tesseract, o Ghostscript ou o LibreOffice
como subprocessos. Matar só o trabalhador Python deixava esses filhos vivos,
segurando o PDF de destino e a memória."""

from __future__ import annotations

import subprocess
import sys
import time

import psutil

from gclaude_indexer.worker_pool import ResilientPool

_PAI = (
    "import subprocess, sys, time\n"
    "filho = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
    "print(filho.pid, flush=True)\n"
    "time.sleep(120)\n"
)


class _ExecutorComProcesso:
    """Imita o `ProcessPoolExecutor`: o pool só olha `_processes` e `shutdown`."""

    def __init__(self, processo):
        self._processes = {processo.pid: processo}

    def shutdown(self, wait=True, cancel_futures=False):
        pass


def test_descartar_o_pool_mata_os_filhos_do_trabalhador():
    pai = subprocess.Popen([sys.executable, "-c", _PAI], stdout=subprocess.PIPE, text=True)
    try:
        pid_filho = int(pai.stdout.readline())
        assert psutil.pid_exists(pid_filho)

        pool = ResilientPool(lambda: None, 1, deadline_for=lambda item: 5)
        pool._executor = _ExecutorComProcesso(pai)
        pool._discard_executor()

        limite = time.monotonic() + 15
        while time.monotonic() < limite:
            try:
                vivo = psutil.Process(pid_filho).is_running() and psutil.Process(pid_filho).status() != psutil.STATUS_ZOMBIE
            except psutil.NoSuchProcess:
                vivo = False
            if not vivo:
                break
            time.sleep(0.1)
        assert not vivo, "o filho do trabalhador ficou vivo"
    finally:
        for processo in (pai,):
            try:
                processo.kill()
            except OSError:
                pass
        try:
            psutil.Process(pid_filho).kill()
        except Exception:
            pass
