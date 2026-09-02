"""Phase 11 tests: the install.ps1 installer, the launchers and the shortcut."""

from __future__ import annotations

from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CAMINHO_INSTALAR_PS1 = RAIZ / "install.ps1"
CAMINHO_INDEXADOR_BAT = RAIZ / "Indexer.bat"
CAMINHO_INDEXADOR_VBS = RAIZ / "Indexer.vbs"
CAMINHO_LOGO_ICO = RAIZ / "logo.ico"


def _texto_ps1() -> str:
    return CAMINHO_INSTALAR_PS1.read_text(encoding="utf-8-sig")


def _texto_bat() -> str:
    return CAMINHO_INDEXADOR_BAT.read_text(encoding="utf-8-sig")


def _texto_vbs() -> str:
    return CAMINHO_INDEXADOR_VBS.read_text(encoding="utf-8-sig")


# --- instalar.ps1 ------------------------------------------------------


def test_instalar_ps1_existe_com_bom_utf8():
    assert CAMINHO_INSTALAR_PS1.exists()
    bruto = CAMINHO_INSTALAR_PS1.read_bytes()
    assert bruto[:3] == b"\xef\xbb\xbf", "Windows PowerShell 5.1 exige BOM para acentos"


def test_instalar_ps1_cria_ambiente_virtual():
    texto = _texto_ps1()
    assert "python -m venv" in texto or "-m venv" in texto
    assert "GClaudeIndexer" in texto
    assert "venv" in texto


def test_instalar_ps1_instala_dependencias_so_quando_hash_muda():
    texto = _texto_ps1()
    assert "requirements.txt" in texto
    assert "Get-FileHash" in texto
    assert "pip install -r" in texto
    assert "requirements.sha256" in texto


def test_instalar_ps1_verifica_tesseract_e_ghostscript():
    texto = _texto_ps1()
    assert "tesseract" in texto.lower()
    assert "gswin64c" in texto or "ghostscript" in texto.lower()


def test_instalar_ps1_avisa_comando_winget_quando_faltam():
    texto = _texto_ps1()
    assert "winget install --id UB-Mannheim.TesseractOCR" in texto
    assert "winget install --id ArtifexSoftware.GhostScript" in texto


def test_instalar_ps1_tem_funcao_de_criar_atalho():
    texto = _texto_ps1()
    assert "function New-DesktopShortcut" in texto
    assert "WScript.Shell" in texto
    assert "CreateShortcut" in texto
    assert "Indexer.bat" in texto


def test_instalar_ps1_atalho_aponta_para_vbs_com_icone():
    """Pedido explícito do usuário (versão 1.0): o atalho não abre uma janela
    de console visível, e usa o logo do sistema como ícone."""
    texto = _texto_ps1()
    assert "Indexer.vbs" in texto
    assert "logo.ico" in texto
    assert "-IconPath $ShortcutIconPath" in texto or "-IconPath" in texto


# --- Indexador.vbs (janela do servidor suprimida, pedido do usuário) -----


def test_indexador_vbs_existe():
    assert CAMINHO_INDEXADOR_VBS.exists()


def test_indexador_vbs_roda_o_bat_oculto():
    texto = _texto_vbs()
    assert "Indexer.bat" in texto
    assert "WScript.Shell" in texto
    # 0 = janela oculta (WScript.Shell.Run), é o modo padrão quando o
    # ambiente já está pronto.
    #
    # Fase 15, Tarefa 3: a linha deixou de montar o comando dentro da
    # própria chamada (`""" & BatPath & """, 0, False`) porque agora ela
    # pode levar o `--cpu-sensor` do segundo atalho junto. O que este teste
    # existe para provar não mudou: o modo 0 continua sendo o do caminho
    # normal.
    assert "objShell.Run CommandLine, 0, False" in texto


def test_logo_ico_existe():
    assert CAMINHO_LOGO_ICO.exists()


def test_instalar_ps1_nao_invoca_pyinstaller():
    # a palavra pode aparecer em comentário explicando que NÃO é usado
    # (seção 11.2/11) — o que não pode existir é uma invocação de verdade.
    texto = _texto_ps1().lower()
    assert "pip install pyinstaller" not in texto
    assert "-m pyinstaller" not in texto
    assert "pyinstaller " not in texto.replace("# sem pyinstaller", "").replace(
        "sem pyinstaller", ""
    ).replace("no pyinstaller", "")


# --- Indexador.bat -------------------------------------------------------


def test_indexador_bat_existe():
    assert CAMINHO_INDEXADOR_BAT.exists()


def test_indexador_bat_ativa_o_ambiente():
    texto = _texto_bat()
    assert "activate.bat" in texto
    assert "GClaudeIndexer\\venv" in texto or "GClaudeIndexer\\\\venv" in texto


def test_indexador_bat_sobe_o_servidor():
    texto = _texto_bat()
    assert "run_server.py" in texto


def test_indexador_bat_sobe_servidor_sem_janela_de_console():
    """Versão 1.0 (pedido explícito do usuário): a janela do servidor web
    fica suprimida — pythonw.exe nunca abre console, ao contrário de
    python.exe."""
    texto = _texto_bat()
    assert "pythonw.exe" in texto


def test_indexador_bat_abre_o_navegador_na_url():
    texto = _texto_bat()
    assert "http://127.0.0.1:8000" in texto
    assert "start \"\"" in texto or 'start ""' in texto


# --- executar_servidor.py (bug real: pythonw.exe sem console) -------------


def test_executar_servidor_sobrevive_sem_console(monkeypatch, tmp_path):
    """Bug real encontrado testando o atalho de verdade: lançado sem
    console (pythonw.exe via Indexer.vbs), sys.stdout/stderr ficam
    `None` — o primeiro print/log do uvicorn batia em `None.write(...)` e
    derrubava o processo na hora, sem deixar nenhum rastro (o servidor
    "sumia" ao abrir pelo atalho). `run_server.py` precisa
    redirecionar os dois para um arquivo antes de importar o resto."""
    import sys

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    sys.modules.pop("run_server", None)

    import run_server  # noqa: F401  (a importação não deve lançar)

    assert sys.stdout is not None, "sys.stdout continua None: uvicorn derrubaria o processo"
    assert sys.stderr is not None
    sys.stdout.write("teste\n")  # não pode lançar AttributeError

    caminho_log = tmp_path / "GClaudeIndexer" / "servidor.log"
    assert caminho_log.exists()

    sys.stdout.close()
    sys.modules.pop("run_server", None)


def test_indexador_bat_recorre_ao_instalador_se_ambiente_ausente():
    texto = _texto_bat()
    assert "install.ps1" in texto


def test_indexador_bat_nao_usa_pyinstaller():
    assert "pyinstaller" not in _texto_bat().lower()


def test_caminhos_com_espaco_estao_entre_aspas():
    """Seção 11.5: 'todo caminho com espaço... precisa de aspas nos comandos
    gerados' — as variáveis de caminho (%RAIZ%, %VENV%) sempre aparecem
    entre aspas nas linhas que as usam como comando/argumento."""
    texto = _texto_bat()
    for linha in texto.splitlines():
        if "%RAIZ%" in linha and ("start " in linha or "python" in linha or "-File" in linha):
            assert '"%RAIZ%' in linha, f"caminho sem aspas: {linha!r}"
