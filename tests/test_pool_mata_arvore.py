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


# --- 2.1.6: o último arquivo preso não derruba a etapa a cada execução -------

import threading  # noqa: E402
from concurrent.futures import ThreadPoolExecutor  # noqa: E402

from gclaude_indexer.worker_pool import OK, TIMED_OUT, PoolStalledError  # noqa: E402,F401


def test_ultimo_arquivo_preso_vira_tempo_esgotado_em_vez_de_travar_a_etapa():
    """O arquivo preso estoura o prazo uma vez com os outros terminando (o
    sistema está são) e volta para o fim da fila. Os outros acabam, e ele
    passa a rodar sozinho: antes, cada novo estouro contava como "disco
    travado" e a etapa caía com `PoolStalledError` em toda execução."""
    solta = threading.Event()

    def trabalho(item):
        if item == "preso":
            solta.wait()
            return "nunca"
        time.sleep(0.02)
        return item

    try:
        with ResilientPool(
            lambda: ThreadPoolExecutor(max_workers=2), 2,
            deadline_for=lambda item: 0.3, poll_seconds=0.02,
        ) as pool:
            resultados = {o.item: o.kind for o in pool.run(["preso", "a", "b", "c"], lambda ex, i: ex.submit(trabalho, i))}
    finally:
        solta.set()
    assert resultados == {"preso": TIMED_OUT, "a": OK, "b": OK, "c": OK}


def test_arquivo_sozinho_desde_o_inicio_continua_sem_ser_condenado():
    """Sem nenhuma prova de que o sistema está são (nada terminou nunca), o
    pool segue desistindo sem condenar ninguém: pode ser o disco."""
    solta = threading.Event()
    try:
        with __import__("pytest").raises(PoolStalledError):
            with ResilientPool(
                lambda: ThreadPoolExecutor(max_workers=1), 1,
                deadline_for=lambda item: 0.1, poll_seconds=0.02,
            ) as pool:
                list(pool.run(["preso"], lambda ex, i: ex.submit(solta.wait)))
    finally:
        solta.set()
