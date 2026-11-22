"""O seletor de pasta precisa de COM em STA, venha de qual thread vier.

Numa thread com COM em MTA (por exemplo, uma thread do pool do servidor que
já rodou código .NET via pythonnet), o Tk cai no seletor antigo do Windows,
que fica invisível: o Procurar não abre nada e o pedido fica pendurado.
"""

import ctypes
import sys
import threading
import types

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="COM só existe no Windows")

APTTYPE_STA = 0
APTTYPE_MAINSTA = 3
COINIT_MULTITHREADED = 0


def _apartment() -> int | None:
    kind, qualifier = ctypes.c_int(), ctypes.c_int()
    if ctypes.windll.ole32.CoGetApartmentType(ctypes.byref(kind), ctypes.byref(qualifier)) != 0:
        return None  # COM não inicializado nesta thread
    return kind.value


def _fake_tkinter(seen: dict):
    class Tk:
        def withdraw(self): pass
        def attributes(self, *a): pass
        def destroy(self): pass

    def askdirectory(**kw):
        seen["apartment"] = _apartment()
        seen["title"] = kw.get("title")
        return "C:/escolhida"

    tk = types.ModuleType("tkinter")
    tk.Tk = Tk
    fd = types.ModuleType("tkinter.filedialog")
    fd.askdirectory = askdirectory
    tk.filedialog = fd
    return tk, fd


def test_dialogo_abre_em_sta_mesmo_chamado_de_thread_mta(monkeypatch):
    from gclaude_indexer.web import folder_picker

    seen: dict = {}
    tk, fd = _fake_tkinter(seen)
    monkeypatch.setitem(sys.modules, "tkinter", tk)
    monkeypatch.setitem(sys.modules, "tkinter.filedialog", fd)

    result: dict = {}

    def caller():
        ctypes.windll.ole32.CoInitializeEx(None, COINIT_MULTITHREADED)
        try:
            result["folder"] = folder_picker.choose_folder(title="Selecione a pasta")
        finally:
            ctypes.windll.ole32.CoUninitialize()

    t = threading.Thread(target=caller)
    t.start()
    t.join(10)

    assert result["folder"] == "C:/escolhida"
    assert seen["title"] == "Selecione a pasta"
    assert seen["apartment"] in (APTTYPE_STA, APTTYPE_MAINSTA)
