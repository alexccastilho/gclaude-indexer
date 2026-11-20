# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Áudio e vídeo (`midia`) da 2.0.0, com o ffmpeg e o whisper.cpp simulados:
`media._popen` é trocado por um processo falso que grava um WAV (o "ffmpeg") e
um JSON no formato real do `whisper-cli` (o "whisper"). Nada vai à rede nem
roda um binário de verdade; o resto (cortes em pausas, páginas com tempos,
retomada, conversão, extração, busca) é o de verdade."""

from __future__ import annotations

import json
import math
import struct
import subprocess
import wave
from dataclasses import replace
from pathlib import Path

import pytest

from gclaude_indexer import components, fulltext, media, ocr_languages, workdir
from gclaude_indexer.config import load_config
from gclaude_indexer.conversion import convert, requeue_ocr_failures
from gclaude_indexer.db import connect, init_schema
from gclaude_indexer.light_formats import MBOX_PAGE_SEPARATOR
from gclaude_indexer.extraction import extract_pages
from gclaude_indexer.file_types import MESSAGE_PAGE_CATEGORIES, category_of_extension
from gclaude_indexer.i18n import translate
from gclaude_indexer.scanning import scan

SR = media.SAMPLE_RATE


def _wav(path: Path, seconds: float, silences=()) -> None:
    """Um WAV mono de 16 kHz: um tom, com silêncio nos intervalos dados."""
    frames = bytearray()
    for index in range(int(seconds * SR)):
        second = index / SR
        quiet = any(start <= second < end for start, end in silences)
        value = 0 if quiet else int(8000 * math.sin(2 * math.pi * 220 * second))
        frames += struct.pack("<h", value)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SR)
        out.writeframes(bytes(frames))


class Simulador:
    """O que o ffmpeg e o whisper.cpp falsos fazem, e o que foi pedido a eles."""

    def __init__(self, seconds=25.0, silences=((9.5, 10.5), (19.5, 20.5)), language="pt"):
        self.seconds = seconds
        self.silences = silences
        self.language = language
        self.ffmpeg_calls: list[list[str]] = []
        self.probe_calls: list[list[str]] = []
        self.probe_format = "mp3"
        self.probe_exit = 0
        self.whisper_calls: list[float] = []  # duração (s) de cada trecho recebido
        self.ffmpeg_exit = 0
        self.ffmpeg_log = ""
        self.whisper_exit = 0
        self.after_whisper = lambda: None
        self.empty_chunks: set[int] = set()
        self.hang = ""  # "ffmpeg" ou "whisper": o processo não termina

    class Processo:
        pid = 1

        def __init__(self, code, hang=False):
            self.code, self.hang = code, hang

        def wait(self, timeout=None):
            if self.hang:
                import time
                time.sleep(min(timeout or 0.05, 0.05))
                raise subprocess.TimeoutExpired("x", timeout)
            return self.code

        def kill(self):
            pass

    def popen(self, command, stderr, stdout=None):
        name = Path(command[0]).name
        if name.startswith("ffprobe"):
            self.probe_calls.append(command)
            if self.probe_exit == 0 and stdout is not None:
                stdout.write((self.probe_format + "\n").encode())
            elif self.probe_exit != 0:
                stderr.write(b"Invalid data found when processing input")
            return self.Processo(self.probe_exit)
        if name.startswith("ffmpeg"):
            self.ffmpeg_calls.append(command)
            if self.hang == "ffmpeg":
                return self.Processo(0, hang=True)
            if self.ffmpeg_exit == 0:
                _wav(Path(command[-1]), self.seconds, self.silences)
            else:
                stderr.write(self.ffmpeg_log.encode())
            return self.Processo(self.ffmpeg_exit)
        assert name.startswith("whisper")
        chunk = Path(command[command.index("-f") + 1])
        base = Path(command[command.index("-of") + 1])
        with wave.open(str(chunk), "rb") as reader:
            seconds = reader.getnframes() / SR
        self.whisper_calls.append(seconds)
        if self.hang == "whisper":
            return self.Processo(0, hang=True)
        if self.whisper_exit == 0:
            number = len(self.whisper_calls)
            items = [] if number in self.empty_chunks else [
                {"offsets": {"from": 0, "to": 2000}, "text": f" Fala do trecho {number}."},
                {"offsets": {"from": 2000, "to": int(seconds * 1000)}, "text": " [BLANK_AUDIO]"},
                {"offsets": {"from": 3000, "to": 4000}, "text": " Segunda frase."},
            ]
            base.with_name(base.name + ".json").write_text(
                json.dumps({"result": {"language": self.language}, "transcription": items}), encoding="utf-8"
            )
        self.after_whisper()
        return self.Processo(self.whisper_exit)


@pytest.fixture
def sim(monkeypatch):
    simulador = Simulador()
    monkeypatch.setattr(media, "_popen", simulador.popen)
    # Trechos de 10 s e busca de pausa de ±2 s: o mesmo comportamento, em segundos.
    monkeypatch.setattr(media, "CHUNK_SECONDS", 10)
    monkeypatch.setattr(media, "PAUSE_SEARCH_SECONDS", 2)
    return simulador


@pytest.fixture(autouse=True)
def _sem_rede_nem_idioma(monkeypatch):
    monkeypatch.setattr(ocr_languages, "ensure", lambda _lang, _exe, download=True: [])


def _tools(tmp_path, vulkan=False, model="small") -> media.Toolset:
    return media.Toolset(
        tmp_path / "ffmpeg.exe", tmp_path / "whisper-cli.exe", tmp_path / "ggml.bin", model, vulkan
    )


def _origem(tmp_path, nome="aula.mp3") -> Path:
    origem = tmp_path / "origem"
    origem.mkdir(exist_ok=True)
    arquivo = origem / nome
    arquivo.write_bytes(b"ID3\x00\x00dados")
    return arquivo


def _transcrever(tmp_path, ferramentas=None, **kwargs):
    arquivo = _origem(tmp_path)
    destino = tmp_path / "saida" / "aula.mp3.txt"
    destino.parent.mkdir(exist_ok=True)
    trabalho = tmp_path / "trabalho"
    resultado = media.transcribe(arquivo, destino, trabalho, ferramentas or _tools(tmp_path), **kwargs)
    return arquivo, destino, trabalho, resultado


# --- páginas com tempos ------------------------------------------------------------


def test_trechos_cortados_em_pausas_viram_paginas_com_intervalo_no_cabecalho(tmp_path, sim):
    _arquivo, destino, trabalho, resultado = _transcrever(tmp_path)

    paginas = destino.read_text(encoding="utf-8").split(MBOX_PAGE_SEPARATOR)
    assert [p.splitlines()[0] for p in paginas] == [
        "[00:00:00–00:00:10]", "[00:00:10–00:00:20]", "[00:00:20–00:00:25]",
    ]
    assert paginas[0].splitlines()[1:] == ["Fala do trecho 1.", "Segunda frase."]
    assert "BLANK_AUDIO" not in destino.read_text(encoding="utf-8")
    assert resultado.pages == 3 and resultado.language == "pt" and not resultado.no_audio
    assert resultado.duration == pytest.approx(25.0)
    # O corte caiu na pausa (perto de 10 s e de 20 s), não em 10,00 exato por acaso.
    assert sim.whisper_calls[0] == pytest.approx(10.05, abs=0.1)
    # Um processo do ffmpeg só, com o contêiner preso a arquivos locais.
    assert len(sim.ffmpeg_calls) == 1
    comando = sim.ffmpeg_calls[0]
    assert comando[comando.index("-protocol_whitelist") + 1] == "file"
    assert "-nostdin" in comando and "0:a:0?" in comando and "-vn" in comando
    assert comando[comando.index("-ar") + 1] == "16000" and comando[comando.index("-ac") + 1] == "1"
    # Nada sobra no disco. Tarefa 12: o idioma vai para `file.language` (pela
    # conversão), não mais para um `.idioma` ao lado do intermediário.
    assert not trabalho.exists()
    assert not list(destino.parent.glob("*.partial")) and not list(destino.parent.glob("*.progress"))
    assert not (destino.parent / "aula.mp3.txt.idioma").exists()


def test_trecho_sem_fala_nao_gera_pagina_mas_o_horario_do_proximo_continua(tmp_path, sim):
    sim.empty_chunks = {2}
    _arquivo, destino, _trabalho, resultado = _transcrever(tmp_path)
    paginas = destino.read_text(encoding="utf-8").split(MBOX_PAGE_SEPARATOR)
    assert [p.splitlines()[0] for p in paginas] == ["[00:00:00–00:00:10]", "[00:00:20–00:00:25]"]
    assert resultado.pages == 2


def test_o_idioma_e_o_que_mais_tempo_de_fala_teve(tmp_path, sim, monkeypatch):
    idiomas = iter(["en", "pt", "pt"])
    original = sim.popen

    def alterna(comando, stderr, stdout=None):
        processo = original(comando, stderr, stdout)
        if Path(comando[0]).name.startswith("whisper"):
            saida = Path(comando[comando.index("-of") + 1] + ".json")
            dados = json.loads(saida.read_text(encoding="utf-8"))
            dados["result"]["language"] = next(idiomas)
            saida.write_text(json.dumps(dados), encoding="utf-8")
        return processo

    monkeypatch.setattr(media, "_popen", alterna)
    assert _transcrever(tmp_path)[3].language == "pt"


def test_sem_nenhuma_fala_e_uma_pagina_vazia(tmp_path, sim):
    sim.empty_chunks = {1, 2, 3}
    _arquivo, destino, _trabalho, resultado = _transcrever(tmp_path)
    assert destino.read_text(encoding="utf-8") == "" and resultado.pages == 1 and resultado.language == ""


def test_sem_faixa_de_audio_e_um_texto_vazio_e_nao_uma_falha(tmp_path, sim):
    sim.ffmpeg_exit = 1
    sim.ffmpeg_log = "[out#0/wav @ 000] Output file does not contain any stream\nError opening output files"
    _arquivo, destino, trabalho, resultado = _transcrever(tmp_path)
    assert resultado.no_audio and resultado.pages == 1
    assert destino.read_text(encoding="utf-8") == "" and not trabalho.exists()
    assert sim.whisper_calls == []


def test_arquivo_ilegivel_falha_e_nao_deixa_nada(tmp_path, sim):
    sim.ffmpeg_exit = 1
    sim.ffmpeg_log = "Error opening input files: Invalid data found when processing input"
    with pytest.raises(media.MediaError, match="Invalid data"):
        _transcrever(tmp_path)
    assert not (tmp_path / "trabalho").exists()
    assert not list((tmp_path / "saida").glob("*"))


def test_playlist_ou_roteiro_disfarcado_de_midia_e_recusado_sem_transcrever(tmp_path, sim):
    for formato in ("hls", "concat", "ffconcat", "mov,mp4,m4a,hls", "applehttp", "image2", "tty", "foo,bar"):
        sim.probe_format = formato
        with pytest.raises(media.MediaRefused):
            _transcrever(tmp_path)
    assert sim.ffmpeg_calls == [] and sim.whisper_calls == []
    assert not (tmp_path / "trabalho").exists()
    # A sondagem também só lê arquivos locais.
    comando = sim.probe_calls[0]
    assert comando[comando.index("-protocol_whitelist") + 1] == "file"
    # Mídia de verdade passa.
    sim.probe_format = "mov,mp4,m4a,3gp,3g2,mj2"
    assert _transcrever(tmp_path)[3].pages == 3
    # O ffmpeg recebe o demuxer conferido e só aceita os permitidos.
    comando = sim.ffmpeg_calls[-1]
    assert comando[comando.index("-f") + 1] == "mov"  # o `-f` de entrada, antes do `-i`
    assert comando.index("-f") < comando.index("-i")
    lista = comando[comando.index("-format_whitelist") + 1].split(",")
    assert set(lista) == media.ALLOWED_FORMATS and comando[comando.index("-protocol_whitelist") + 1] == "file"
    assert "-format_whitelist" in sim.probe_calls[-1]


@pytest.mark.parametrize(
    ("extensao", "formato"),
    [
        (".mp3", "mp3"), (".wav", "wav"), (".m4a", "mov,mp4,m4a,3gp,3g2,mj2"), (".mp4", "mov,mp4,m4a,3gp,3g2,mj2"),
        (".mov", "mov,mp4,m4a,3gp,3g2,mj2"), (".m4v", "mov,mp4,m4a,3gp,3g2,mj2"), (".3gp", "mov,mp4,m4a,3gp,3g2,mj2"),
        (".aac", "aac"), (".ogg", "ogg"), (".opus", "ogg"), (".flac", "flac"), (".wma", "asf"), (".wmv", "asf"),
        (".mkv", "matroska,webm"), (".webm", "matroska,webm"), (".avi", "avi"),
    ],
)
def test_toda_extensao_de_midia_tem_demuxer_permitido(extensao, formato):
    from gclaude_indexer.file_types import EXTENSION_CATEGORIES

    assert extensao in EXTENSION_CATEGORIES["midia"]
    assert any(nome in media.ALLOWED_FORMATS for nome in formato.split(","))


def test_toda_extensao_de_midia_esta_coberta_pelo_teste_acima():
    from gclaude_indexer.file_types import EXTENSION_CATEGORIES

    assert len(EXTENSION_CATEGORIES["midia"]) == 16


def test_sondagem_que_falha_e_arquivo_ilegivel(tmp_path, sim):
    sim.probe_exit = 1
    with pytest.raises(media.MediaError, match="ffprobe"):
        _transcrever(tmp_path)
    assert sim.ffmpeg_calls == []


def test_falha_do_whisper_apaga_o_progresso(tmp_path, sim):
    sim.whisper_exit = 1
    with pytest.raises(media.MediaError, match="whisper"):
        _transcrever(tmp_path)
    assert not (tmp_path / "trabalho").exists() and not list((tmp_path / "saida").glob("*"))


def test_tempo_limite_mata_o_processo_e_falha(tmp_path, sim, monkeypatch):
    mortos: list = []
    monkeypatch.setattr(media, "kill_tree", lambda processo: mortos.append(processo))
    monkeypatch.setattr(media, "FILE_TIMEOUT_MIN_S", 0.0)
    monkeypatch.setattr(media, "PROCESS_TIMEOUT_MIN_S", 0.0)
    monkeypatch.setattr(media, "PROCESS_TIMEOUT_FACTOR", 0)
    sim.hang = "whisper"
    with pytest.raises(media.MediaError, match="tempo limite"):
        _transcrever(tmp_path)
    assert mortos  # e o que já havia fica no disco (ver o teste dos trechos prontos)


# --- Parar e retomar ---------------------------------------------------------------


def test_parar_depois_do_primeiro_trecho_e_retomar_sem_refazer_o_que_ja_foi(tmp_path, sim):
    parar = {"valor": False}
    sim.after_whisper = lambda: parar.update(valor=True)
    arquivo = _origem(tmp_path)
    destino = tmp_path / "saida" / "aula.mp3.txt"
    destino.parent.mkdir()
    trabalho = tmp_path / "trabalho"
    ferramentas = _tools(tmp_path)

    with pytest.raises(media.Interrupted):
        media.transcribe(arquivo, destino, trabalho, ferramentas, should_stop=lambda: parar["valor"])
    assert not destino.exists()
    assert len(sim.whisper_calls) == 1
    assert (destino.parent / "aula.mp3.txt.progress").exists() and (trabalho / media.WORK_WAV).exists()

    sim.after_whisper = lambda: None
    resultado = media.transcribe(arquivo, destino, trabalho, ferramentas)
    # O áudio não foi extraído de novo e só os trechos 2 e 3 foram transcritos.
    assert len(sim.ffmpeg_calls) == 1 and len(sim.whisper_calls) == 3
    paginas = destino.read_text(encoding="utf-8").split(MBOX_PAGE_SEPARATOR)
    assert [p.splitlines()[0][:10] for p in paginas] == ["[00:00:00–", "[00:00:10–", "[00:00:20–"]
    assert resultado.pages == 3
    # Idêntico a uma execução sem parada.
    outro = tmp_path / "outro"
    sim.whisper_calls.clear()
    destino2 = outro / "aula.mp3.txt"
    outro.mkdir()
    media.transcribe(arquivo, destino2, outro / "w", ferramentas)
    assert [p.splitlines()[0] for p in destino2.read_text(encoding="utf-8").split(MBOX_PAGE_SEPARATOR)] == [
        p.splitlines()[0] for p in paginas
    ]


def _relogio(monkeypatch, sim, saltos):
    """Um relógio falso: cada trecho transcrito avança `saltos[n]` segundos."""
    agora = {"t": 0.0}
    monkeypatch.setattr(media.time, "monotonic", lambda: agora["t"])
    chamadas = iter(saltos)
    sim.after_whisper = lambda: agora.update(t=agora["t"] + next(chamadas, 0.0))
    return agora


def test_estouro_do_orcamento_guarda_o_progresso_e_a_proxima_execucao_retoma(tmp_path, sim, monkeypatch):
    monkeypatch.setattr(media, "FILE_TIMEOUT_MIN_S", 0.0)
    # Trecho 1: 10 s (a velocidade medida projeta ~25 s, orçamento ~75 s);
    # trecho 2: 1000 s (a máquina engasgou). Antes do trecho 3 o orçamento estoura.
    _relogio(monkeypatch, sim, [10.0, 1000.0])
    arquivo = _origem(tmp_path)
    destino = tmp_path / "saida" / "aula.mp3.txt"
    destino.parent.mkdir()
    trabalho = tmp_path / "trabalho"
    ferramentas = _tools(tmp_path)

    with pytest.raises(media.Postponed):
        media.transcribe(arquivo, destino, trabalho, ferramentas)
    assert len(sim.whisper_calls) == 2 and not destino.exists()
    parcial = destino.parent / "aula.mp3.txt.partial"
    assert parcial.read_text(encoding="utf-8").count("Fala do trecho") == 2
    assert (destino.parent / "aula.mp3.txt.progress").exists() and (trabalho / media.WORK_WAV).exists()

    # Próxima execução (relógio normal): só o trecho 3, sem extrair de novo.
    monkeypatch.undo()
    monkeypatch.setattr(media, "_popen", sim.popen)
    monkeypatch.setattr(media, "CHUNK_SECONDS", 10)
    monkeypatch.setattr(media, "PAUSE_SEARCH_SECONDS", 2)
    sim.after_whisper = lambda: None
    resultado = media.transcribe(arquivo, destino, trabalho, ferramentas)
    assert len(sim.ffmpeg_calls) == 1 and len(sim.whisper_calls) == 3 and resultado.pages == 3
    assert destino.read_text(encoding="utf-8").count("Fala do trecho") == 3


def test_tempo_limite_de_um_processo_nao_joga_fora_os_trechos_prontos(tmp_path, sim, monkeypatch):
    monkeypatch.setattr(media, "kill_tree", lambda processo: None)
    arquivo = _origem(tmp_path)
    destino = tmp_path / "saida" / "aula.mp3.txt"
    destino.parent.mkdir()
    trabalho = tmp_path / "trabalho"
    original = sim.popen
    contagem = {"n": 0}

    def trava_no_segundo(comando, stderr, stdout=None):
        if Path(comando[0]).name.startswith("whisper"):
            contagem["n"] += 1
            if contagem["n"] == 2:
                sim.whisper_calls.append(0)
                return sim.Processo(0, hang=True)
        return original(comando, stderr, stdout)

    monkeypatch.setattr(media, "_popen", trava_no_segundo)
    monkeypatch.setattr(media, "PROCESS_TIMEOUT_MIN_S", 0.0)
    monkeypatch.setattr(media, "PROCESS_TIMEOUT_FACTOR", 0)
    with pytest.raises(media.MediaTimeout):
        media.transcribe(arquivo, destino, trabalho, _tools(tmp_path))
    assert (destino.parent / "aula.mp3.txt.partial").exists() and (destino.parent / "aula.mp3.txt.progress").exists()


def test_erro_no_aviso_de_estimativa_nao_derruba_o_arquivo(tmp_path, sim):
    def quebra(_info):
        raise RuntimeError("banco ocupado")

    assert _transcrever(tmp_path, on_estimate=quebra)[3].pages == 3


def test_sobra_do_idioma_ao_lado_do_intermediario_e_apagada(tmp_path, sim):
    """Tarefa 12: o `.idioma` da versão anterior (antes da coluna
    `file.language`) some na transcrição seguinte, com ou sem fala."""
    _arquivo, destino, _trabalho, _r = _transcrever(tmp_path)
    sidecar = destino.parent / "aula.mp3.txt.idioma"
    sidecar.write_text("pt", encoding="utf-8")
    sim.empty_chunks = {4, 5, 6}  # a segunda transcrição: nenhuma fala
    _transcrever(tmp_path)
    assert not sidecar.exists()
    # E o caminho sem faixa de áudio.
    sidecar.write_text("pt", encoding="utf-8")
    sim.ffmpeg_exit = 1
    sim.ffmpeg_log = "Output file does not contain any stream"
    assert _transcrever(tmp_path)[3].no_audio and not sidecar.exists()


def test_arquivo_trocado_ou_outro_modelo_descarta_o_progresso(tmp_path, sim):
    parar = {"valor": False}
    sim.after_whisper = lambda: parar.update(valor=True)
    arquivo = _origem(tmp_path)
    destino = tmp_path / "saida" / "aula.mp3.txt"
    destino.parent.mkdir()
    trabalho = tmp_path / "trabalho"
    with pytest.raises(media.Interrupted):
        media.transcribe(arquivo, destino, trabalho, _tools(tmp_path), should_stop=lambda: parar["valor"])

    sim.after_whisper = lambda: None
    arquivo.write_bytes(b"ID3\x00\x00dados novos e maiores")  # outro tamanho e outra data
    media.transcribe(arquivo, destino, trabalho, _tools(tmp_path))
    assert len(sim.ffmpeg_calls) == 2 and len(sim.whisper_calls) == 1 + 3

    # O mesmo vale quando o modelo mudou entre as execuções.
    sim.whisper_calls.clear()
    sim.ffmpeg_calls.clear()
    parar["valor"] = False
    sim.after_whisper = lambda: parar.update(valor=True)
    with pytest.raises(media.Interrupted):
        media.transcribe(arquivo, destino, trabalho, _tools(tmp_path, model="small"), should_stop=lambda: parar["valor"])
    sim.after_whisper = lambda: None
    media.transcribe(arquivo, destino, trabalho, _tools(tmp_path, model="base"))
    assert len(sim.ffmpeg_calls) == 2 and len(sim.whisper_calls) == 1 + 3


def test_parar_durante_um_processo_mata_a_arvore(tmp_path, sim, monkeypatch):
    mortos: list = []
    monkeypatch.setattr(media, "kill_tree", lambda processo: mortos.append(processo))
    sim.hang = "ffmpeg"
    with pytest.raises(media.Interrupted):
        _transcrever(tmp_path, should_stop=lambda: True)
    assert mortos


def test_estimativa_e_dada_antes_de_transcrever(tmp_path, sim):
    vistos: list = []
    _transcrever(tmp_path, on_estimate=lambda info: vistos.append((dict(info), len(sim.whisper_calls))))
    info, trechos_ja_feitos = vistos[0]
    assert trechos_ja_feitos == 0 and len(vistos) == 1
    assert info["duration"] == pytest.approx(25.0)
    assert info["estimate"] == pytest.approx(25.0 * media.REALTIME_FACTOR[False]["small"])
    assert info["model"] == "small" and info["vulkan"] is False


# --- modelo, tempos e componentes --------------------------------------------------


@pytest.mark.parametrize(
    ("ram", "vram", "vulkan", "esperado"),
    [
        (4096, 0, False, "base"),       # sem placa usável e pouca RAM
        (16384, 0, False, "small"),     # padrão
        (None, None, False, "small"),   # sem medição
        (4096, 12288, False, "base"),   # placa grande, mas o binário não a usa (build de CPU)
        (16384, 12288, False, "small"),
        (16384, 12288, True, "medium"),  # Vulkan e VRAM de sobra
        (16384, 6144, True, "medium"),
        (16384, 4096, True, "small"),
        (4096, 4096, True, "small"),    # com placa usável, pouca RAM não rebaixa
        (4096, 1024, True, "base"),     # placa pequena demais para contar
    ],
)
def test_modelo_pelo_computador(ram, vram, vulkan, esperado):
    assert media.choose_model(ram, vram, vulkan) == esperado


def test_estimativa_de_gpu_e_menor_que_a_de_cpu():
    for modelo in media.MODEL_COMPONENTS:
        assert media.estimate_seconds(600, modelo, True) < media.estimate_seconds(600, modelo, False)
    assert media.estimate_seconds(-5, "small", False) == 0


def test_vulkan_e_reconhecido_pelo_backend_ao_lado_do_binario(tmp_path):
    exe = tmp_path / "whisper-cli.exe"
    exe.write_bytes(b"x")
    assert not media.has_vulkan(exe)
    (tmp_path / "ggml-vulkan.dll").write_bytes(b"x")
    assert media.has_vulkan(exe)


def test_prepare_baixa_so_o_modelo_escolhido(tmp_path, monkeypatch):
    pedidos: list = []
    raiz = tmp_path / "componentes"
    monkeypatch.setattr(components, "private_root", lambda: raiz)

    def ensure(nomes, download=True, **_k):
        pedidos.append(list(nomes))
        for nome in nomes:
            componente = components.get(nome)
            alvo = components.target_path(componente)
            if componente.kind == "zip":
                (alvo / Path(componente.check).parent).mkdir(parents=True, exist_ok=True)
                (alvo / componente.check).write_bytes(b"x")
                (alvo / components.ZIP_MARKER_NAME).write_text("{}", encoding="utf-8")
            else:
                alvo.parent.mkdir(parents=True, exist_ok=True)
                alvo.write_bytes(b"x")
        return {}

    monkeypatch.setattr(components, "ensure", ensure)
    monkeypatch.setattr(media, "_measure_hardware", lambda: (4096, 0))
    ferramentas, faltando = media.prepare()
    assert faltando == [] and ferramentas.model_name == "base" and ferramentas.vulkan is False
    assert pedidos == [["ffmpeg", "whisper-cpp"], ["whisper-model-base"]]
    assert ferramentas.ffmpeg.name == "ffmpeg.exe" and ferramentas.whisper.name == "whisper-cli.exe"


def test_prepare_sem_rede_diz_o_que_faltou_e_aproveita_modelo_ja_instalado(tmp_path, monkeypatch):
    monkeypatch.setattr(components, "private_root", lambda: tmp_path / "vazio")
    monkeypatch.setattr(media, "_measure_hardware", lambda: (16384, 0))
    ferramentas, faltando = media.prepare()  # a rede é a fechada pelo conftest
    assert ferramentas is None
    assert faltando == ["ffmpeg", "whisper.cpp", "Whisper small"]

    # Com ffmpeg e whisper.cpp presentes, o modelo `base` já instalado serve no lugar do `small`.
    raiz = tmp_path / "parcial"
    monkeypatch.setattr(components, "private_root", lambda: raiz)
    for nome in ("ffmpeg", "whisper-cpp"):
        componente = components.get(nome)
        alvo = components.target_path(componente)
        (alvo / Path(componente.check).parent).mkdir(parents=True)
        (alvo / componente.check).write_bytes(b"x")
        (alvo / components.ZIP_MARKER_NAME).write_text("{}", encoding="utf-8")
    base = components.target_path(components.get("whisper-model-base"))
    base.parent.mkdir(parents=True)
    base.write_bytes(b"x")
    ferramentas, faltando = media.prepare()
    assert faltando == [] and ferramentas.model_name == "base"


# --- no fluxo do projeto -----------------------------------------------------------


def _projeto(tmp_path, extensoes=("all", "midia")):
    origem = tmp_path / "origem"
    origem.mkdir()
    saida = tmp_path / "saida"
    config = load_config({
        "name": "Mídia", "source_folder": str(origem), "output_folder": str(saida), "extensions": list(extensoes),
    })
    config = replace(config, parallelism="economy")
    conn = connect(saida / "project.db")
    init_schema(conn)
    return origem, saida, config, conn


def _arquivo(conn, nome):
    return conn.execute("SELECT * FROM file WHERE name = ?", (nome,)).fetchone()


def test_midia_so_e_transcrita_com_a_categoria_e_sem_ela_nada_e_baixado(tmp_path, monkeypatch):
    origem, _saida, config, conn = _projeto(tmp_path, ("all",))
    (origem / "aula.mp3").write_bytes(b"ID3\x00\x00dados")
    (origem / "nota.txt").write_text("texto comum", encoding="utf-8")

    def proibido(*_a, **_k):
        raise AssertionError("nenhum componente de mídia pode ser pedido sem a categoria")

    monkeypatch.setattr(media, "prepare", proibido)
    monkeypatch.setattr(components, "ensure", proibido)
    scan(conn, config)
    assert (_arquivo(conn, "aula.mp3")["status"], _arquivo(conn, "aula.mp3")["error"]) == ("skipped", "media_not_selected")
    assert convert(conn, config).failed == 0
    conn.close()


def test_midia_entra_no_modelo_de_paginas_das_mensagens():
    assert "midia" in MESSAGE_PAGE_CATEGORIES
    assert category_of_extension(".mp4") == "midia"


def test_conversao_extracao_e_busca_de_um_audio(tmp_path, sim, monkeypatch):
    origem, saida, config, conn = _projeto(tmp_path)
    (origem / "reunião.mp3").write_bytes(b"ID3\x00\x00dados")
    monkeypatch.setattr(media, "prepare", lambda download=True, **_k: (_tools(tmp_path), []))
    scan(conn, config)

    resultado = convert(conn, config, language="pt-BR")
    extract_pages(conn, config)

    assert resultado.failed == 0
    linha = _arquivo(conn, "reunião.mp3")
    assert linha["page_count"] == 3 and linha["status"] in ("converted", "extracted")
    paginas = [r["text"] for r in conn.execute("SELECT text FROM page ORDER BY number")]
    assert len(paginas) == 3 and paginas[1].startswith("[00:00:10–00:00:20]")
    avisos = [r["message"] for r in conn.execute("SELECT message FROM event")]
    assert any("transcrição local com o modelo small (CPU)" in a and "00:00:25 de áudio" in a for a in avisos), avisos
    assert any("idioma detectado na fala: pt" in a for a in avisos)
    # Tarefa 12: o idioma da fala fica na coluna do arquivo, como o de um texto.
    assert _arquivo(conn, "reunião.mp3")["language"] == "pt"
    # A busca devolve o trecho com o horário.
    achados = fulltext.passages_for_file(conn, config, _arquivo(conn, "reunião.mp3"))
    assert any("Segunda frase" in p.text and "[00:00:10" in p.text for p in achados)
    assert not list((workdir.work_folder(saida) / "converted").rglob("midia"))
    conn.close()


def test_sem_componentes_fica_pendente_com_um_aviso_e_volta_a_fila(tmp_path, sim, monkeypatch):
    origem, _saida, config, conn = _projeto(tmp_path)
    (origem / "a.mp3").write_bytes(b"ID3\x00\x00a")
    (origem / "b.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42")
    (origem / "nota.txt").write_text("texto comum", encoding="utf-8")
    monkeypatch.setattr(media, "prepare", lambda download=True, **_k: (None, ["ffmpeg", "Whisper small"]))
    scan(conn, config)

    resultado = convert(conn, config, language="pt-BR")
    assert resultado.failed == 0
    for nome in ("a.mp3", "b.mp4"):
        linha = _arquivo(conn, nome)
        assert (linha["status"], linha["error"], linha["ocr_failed"]) == ("skipped", "component_unavailable", 1)
    assert _arquivo(conn, "nota.txt")["status"] == "converted"
    avisos = [r["message"] for r in conn.execute("SELECT message FROM event WHERE level = 'warning'")]
    assert sum("ffmpeg, Whisper small" in a and "2 arquivo(s) de áudio/vídeo" in a for a in avisos) == 1, avisos
    assert sim.ffmpeg_calls == []

    # Na conversão seguinte voltam à fila e, com os componentes, são transcritos.
    monkeypatch.setattr(media, "prepare", lambda download=True, **_k: (_tools(tmp_path), []))
    assert requeue_ocr_failures(conn) == 2
    assert convert(conn, config).failed == 0
    for nome in ("a.mp3", "b.mp4"):
        linha = _arquivo(conn, nome)
        assert (linha["status"], linha["error"], linha["ocr_failed"], linha["page_count"]) == ("converted", None, 0, 3)
    conn.close()


def test_parar_deixa_o_arquivo_na_fila_e_a_conversao_seguinte_retoma(tmp_path, sim, monkeypatch):
    origem, saida, config, conn = _projeto(tmp_path)
    (origem / "aula.mp3").write_bytes(b"ID3\x00\x00dados")
    monkeypatch.setattr(media, "prepare", lambda download=True, **_k: (_tools(tmp_path), []))
    scan(conn, config)
    parar = {"valor": False}
    sim.after_whisper = lambda: parar.update(valor=True)

    convert(conn, config, should_stop=lambda: parar["valor"])
    assert _arquivo(conn, "aula.mp3")["status"] == "discovered"
    assert len(sim.whisper_calls) == 1

    sim.after_whisper = lambda: None
    convert(conn, config)
    assert _arquivo(conn, "aula.mp3")["status"] == "converted"
    assert len(sim.ffmpeg_calls) == 1 and len(sim.whisper_calls) == 3
    conn.close()


def test_lista_de_reproducao_vira_ignorada_e_estouro_deixa_na_fila_com_aviso(tmp_path, sim, monkeypatch):
    origem, _saida, config, conn = _projeto(tmp_path)
    (origem / "lista.mp4").write_bytes(b"#EXTM3U\nhttp://x/y.ts\n")
    monkeypatch.setattr(media, "prepare", lambda download=True, **_k: (_tools(tmp_path), []))
    sim.probe_format = "hls"
    scan(conn, config)
    assert convert(conn, config).failed == 0
    linha = _arquivo(conn, "lista.mp4")
    assert (linha["status"], linha["error"]) == ("skipped", "unsupported")
    assert sim.ffmpeg_calls == [] and sim.whisper_calls == []

    # Estouro do orçamento: continua `discovered`, com um aviso traduzido.
    sim.probe_format = "mp3"
    (origem / "lista.mp4").unlink()
    (origem / "aula.mp3").write_bytes(b"ID3\x00\x00dados")
    monkeypatch.setattr(media, "FILE_TIMEOUT_MIN_S", 0.0)
    _relogio(monkeypatch, sim, [10.0, 1000.0])
    scan(conn, config)
    assert convert(conn, config, language="pt-BR").failed == 0
    assert _arquivo(conn, "aula.mp3")["status"] == "discovered"
    avisos = [r["message"] for r in conn.execute("SELECT message FROM event WHERE level = 'warning'")]
    assert any("passou do tempo previsto" in a and "aula.mp3" in a for a in avisos), avisos
    conn.close()


def test_arquivo_de_midia_ilegivel_falha_sem_derrubar_os_demais(tmp_path, sim, monkeypatch):
    origem, _saida, config, conn = _projeto(tmp_path)
    (origem / "quebrado.mp3").write_bytes(b"lixo")
    (origem / "nota.txt").write_text("texto comum", encoding="utf-8")
    monkeypatch.setattr(media, "prepare", lambda download=True, **_k: (_tools(tmp_path), []))
    sim.ffmpeg_exit = 1
    sim.ffmpeg_log = "Error opening input files: Invalid data found when processing input"
    scan(conn, config)
    resultado = convert(conn, config)
    assert resultado.failed == 1 and resultado.converted == 1
    assert _arquivo(conn, "quebrado.mp3")["status"] == "failed"
    assert _arquivo(conn, "nota.txt")["status"] == "converted"
    conn.close()


def test_rotulos_nos_tres_idiomas():
    for idioma in ("pt-BR", "en", "es"):
        assert translate(idioma, "ignored.reason.component_unavailable") != "ignored.reason.component_unavailable"
        for chave, parametros in (
            ("log.conversion.media_component_unavailable", {"component": "ffmpeg", "count": 2}),
            ("log.conversion.media_estimate", {"name": "a.mp3", "model": "small", "device": "CPU", "duration": "00:01:00", "minutes": 3}),
            ("log.conversion.media_language", {"name": "a.mp3", "lang": "pt"}),
            ("log.conversion.media_no_audio", {"name": "a.mp3"}),
            ("log.conversion.media_postponed", {"name": "a.mp3"}),
            ("log.conversion.media_truncated", {"name": "a.mp3", "hours": 24, "limit_mb": 256}),
        ):
            texto = translate(idioma, chave, **parametros)
            assert texto != chave and "{" not in texto


def test_manifesto_traz_os_cinco_componentes_de_midia_com_licenca_e_modelos_fixados():
    manifesto = components.manifest()
    for nome in ("ffmpeg", "whisper-cpp", "whisper-model-base", "whisper-model-small", "whisper-model-medium"):
        assert nome in manifesto
        assert manifesto[nome].url.startswith("https://") and len(manifesto[nome].sha256) == 64
    assert manifesto["ffmpeg"].license.startswith("LGPL") and manifesto["whisper-cpp"].license == "MIT"
    # Modelos pelo commit do repositório, nunca por `main`.
    for modelo in media.MODEL_COMPONENTS.values():
        assert "/resolve/main/" not in manifesto[modelo].url and manifesto[modelo].license == "MIT"
    assert manifesto["ffmpeg"].check and manifesto["whisper-cpp"].check


def test_estimativa_usa_o_nome_do_modelo_e_nao_o_caminho(tmp_path, sim):
    """Revisão final: `estimate_seconds` recebia `tools.model` (o caminho do
    `.bin`), nunca achava o modelo na tabela e caía sempre no `small`."""
    vistos: list = []
    ferramentas = _tools(tmp_path, vulkan=True, model="medium")
    _transcrever(tmp_path, ferramentas, on_estimate=vistos.append)
    assert media.REALTIME_FACTOR[True]["medium"] != media.REALTIME_FACTOR[True]["small"]
    assert vistos[0]["estimate"] == pytest.approx(25.0 * media.REALTIME_FACTOR[True]["medium"])
