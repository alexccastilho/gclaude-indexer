# GClaude Indexer — document collection indexer
# Copyright (C) 2026  Alex Camacho Castilho
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version. See the LICENSE file for details.

"""Áudio e vídeo transcritos no próprio computador (2.0.0).

Só entram no índice quando o usuário marca a categoria `midia` (opt-in). Três
componentes baixados sob demanda (`components`), só se houver mídia a
transcrever: o `ffmpeg` (build LGPL), o `whisper.cpp` (`whisper-cli`) e um
modelo multilíngue (`base`, `small` ou `medium`, escolhido pelo computador).

Como cada arquivo é transcrito:
- o `ffmpeg` extrai a primeira faixa de áudio para um WAV mono de 16 kHz na
  pasta de trabalho local (nunca na pasta de saída, que o Drive sincroniza);
  o contêiner de um terceiro nunca busca URL nem lê outro arquivo
  (`-protocol_whitelist file`);
- o WAV é cortado em trechos de cerca de 5 minutos, no ponto mais quieto
  perto do corte (uma pausa, não o meio de uma frase); cada trecho é
  transcrito pelo `whisper-cli` com detecção automática de idioma e vira uma
  página, que começa por uma linha `[hh:mm:ss–hh:mm:ss]` (o intervalo do
  trecho no arquivo original). Trecho sem fala não gera página;
- o processo externo recebe lista de argumentos (sem shell), roda sem
  janela, com as saídas em arquivo, uma vez por vez e com tempo limite
  proporcional à duração (a árvore inteira é morta ao estourar ou ao Parar);
- o progresso (trecho já transcrito, bytes e páginas do arquivo parcial) vai a
  disco a cada trecho, preso ao tamanho e à data do arquivo de origem e ao
  modelo usado. Ao retomar depois de Parar (ou de uma queda) o parcial é
  cortado nesse ponto e os trechos feitos não são refeitos.

O idioma detectado (o que mais tempo de fala teve) vai para o log e para um
arquivo ao lado do intermediário (`<intermediário>.idioma`).
"""

from __future__ import annotations

import array
import json
import math
import os
import shutil
import signal
import subprocess
import sys
import time
import wave
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import components
from .light_formats import MBOX_PAGE_SEPARATOR

COMPONENT_FFMPEG = "ffmpeg"
COMPONENT_WHISPER = "whisper-cpp"
MODEL_COMPONENTS = {
    "base": "whisper-model-base",
    "small": "whisper-model-small",
    "medium": "whisper-model-medium",
}
# Nomes para o aviso ao usuário (o que faltou).
DISPLAY_NAMES = {
    COMPONENT_FFMPEG: "ffmpeg",
    COMPONENT_WHISPER: "whisper.cpp",
    **{component: f"Whisper {model}" for model, component in MODEL_COMPONENTS.items()},
}

SAMPLE_RATE = 16_000
BYTES_PER_SECOND = SAMPLE_RATE * 2  # mono, 16 bits
# Alvo de cada trecho/página e quanto o corte pode andar para achar uma pausa.
CHUNK_SECONDS = 300
PAUSE_SEARCH_SECONDS = 20
PAUSE_FRAME_SECONDS = 0.1
# Um resto menor que isto não vale um processo (e o whisper recusa áudio < 1 s).
MIN_TAIL_SECONDS = 0.5
# Teto do áudio transcrito de um arquivo (24 h de WAV mono 16 kHz = 2,7 GB).
MAX_AUDIO_SECONDS = 24 * 3600
# Teto do texto que vai para o intermediário.
MAX_OUTPUT_BYTES = 256 * 1024 * 1024
MAX_PAGE_CHARS = 2_000_000

# Tempo limite: o arquivo todo vale 3x a estimativa (mínimo 10 min); cada
# processo, no máximo 6x a estimativa do trecho (mínimo 5 min). A extração do
# áudio tem o mínimo de 10 min mais o tempo de ler o arquivo a 2 MB/s (um
# filme no Google Drive).
FILE_TIMEOUT_FACTOR = 3
FILE_TIMEOUT_MIN_S = 600
PROCESS_TIMEOUT_FACTOR = 6
PROCESS_TIMEOUT_MIN_S = 300
EXTRACT_TIMEOUT_MIN_S = 600
EXTRACT_READ_BYTES_PER_S = 2 * 1024 * 1024

# Quanto tempo de processamento cada segundo de áudio custa (ESTIMATIVA, não
# garantia: `whisper-cli` em um processador de uso geral de 8 núcleos, ou na
# placa via Vulkan; varia com o computador). Só serve para avisar o usuário e
# para calcular o tempo limite.
REALTIME_FACTOR = {
    False: {"base": 0.08, "small": 0.25, "medium": 0.8},  # CPU
    True: {"base": 0.03, "small": 0.08, "medium": 0.2},  # Vulkan
}

# Escolha do modelo (ver `choose_model`).
MIN_GPU_VRAM_MB = 2048
MEDIUM_VRAM_MB = 6144
LOW_RAM_MB = 8192

PROGRESS_SUFFIX = ".progress"
PARTIAL_SUFFIX = ".partial"
LANGUAGE_SUFFIX = ".idioma"
WORK_WAV = "audio.wav"


class MediaError(Exception):
    """Falha ao transcrever. A mensagem não leva conteúdo do arquivo."""


class MediaTimeout(MediaError):
    """Um processo passou do tempo limite e foi morto. O que já estava
    transcrito fica no disco (um tempo limite nunca joga trechos prontos fora)."""


class MediaRefused(MediaError):
    """O contêiner é uma lista de reprodução ou roteiro (HLS, `concat`…), que
    pode apontar para outros arquivos: não é mídia de verdade e não é lido."""


class Interrupted(Exception):
    """Parar foi pedido; o progresso já está gravado."""


class Postponed(Exception):
    """A execução passou do tempo previsto para o arquivo; o progresso está
    gravado e o arquivo continua na fila para a próxima conversão."""


# Formatos que o ffprobe reconhece por conteúdo e que mandam o ffmpeg buscar
# outros arquivos ou endereços (listas de reprodução, roteiros, descrições).
REFUSED_FORMATS = frozenset({"hls", "applehttp", "concat", "ffconcat", "dash", "sdp", "rtsp", "rtp"})


@dataclass(frozen=True)
class Toolset:
    ffmpeg: Path
    whisper: Path
    model: Path
    model_name: str
    # O `whisper-cli` instalado sabe usar a placa (traz o backend Vulkan).
    vulkan: bool


@dataclass
class MediaResult:
    pages: int
    language: str = ""
    duration: float = 0.0
    # `True` quando não havia faixa de áudio.
    no_audio: bool = False
    # Por que parou antes do fim: "duration", "output" ou `None`.
    truncated: str | None = None


# --- componentes e escolha do modelo -----------------------------------------


def has_vulkan(whisper_exe: Path) -> bool:
    """O `whisper-cli` carrega os backends de DLLs ao lado dele: com o do
    Vulkan ali, usa a placa; sem ele (a build publicada hoje) roda no
    processador."""
    return any(whisper_exe.parent.glob("ggml-vulkan*.dll"))


def choose_model(ram_mb: int | None, vram_mb: int | None, vulkan: bool) -> str:
    """O modelo pelo computador: `medium` só com placa usável pelo Vulkan e
    VRAM de sobra; `base` sem placa usável e com pouca RAM; `small` no resto.
    Sem medição (`None`/0) vale o padrão `small`."""
    vram = vram_mb or 0
    usable_gpu = vulkan and vram >= MIN_GPU_VRAM_MB
    if usable_gpu and vram >= MEDIUM_VRAM_MB:
        return "medium"
    if not usable_gpu and ram_mb and ram_mb < LOW_RAM_MB:
        return "base"
    return "small"


def _measure_hardware() -> tuple[int, int]:
    """`(RAM total, VRAM livre)` em MB, 0 quando não dá para medir: as
    mesmas medições que escolhem o modelo do Ollama."""
    try:
        from .hardware import _total_memory_mb

        ram = int(_total_memory_mb())
    except Exception:
        ram = 0
    try:
        from .gpu_budget import free_vram_mb

        vram = int(free_vram_mb() or 0)
    except Exception:
        vram = 0
    return ram, vram


def _executable(name: str) -> Path | None:
    folder = components.path_of(name)
    component = components.get(name)
    if folder is None or component is None or not component.check:
        return None
    candidate = folder / component.check
    return candidate if candidate.is_file() else None


def prepare(download: bool = True) -> tuple[Toolset | None, list[str]]:
    """Os três componentes (baixando o que falta): `(ferramentas, [])` ou
    `(None, nomes do que faltou)`. Nunca levanta; só o modelo escolhido é
    baixado (um modelo já instalado serve quando o escolhido não vem)."""
    components.ensure([COMPONENT_FFMPEG, COMPONENT_WHISPER], download=download)
    ffmpeg = _executable(COMPONENT_FFMPEG)
    whisper = _executable(COMPONENT_WHISPER)
    missing = [DISPLAY_NAMES[name] for name, found in ((COMPONENT_FFMPEG, ffmpeg), (COMPONENT_WHISPER, whisper)) if found is None]
    if whisper is None:
        # Sem o binário não há como saber se a placa serve; o modelo
        # escolhido (o padrão) entra na lista do que faltou.
        return None, missing + [DISPLAY_NAMES[MODEL_COMPONENTS["small"]]]
    vulkan = has_vulkan(whisper)
    ram, vram = _measure_hardware()
    chosen = choose_model(ram, vram, vulkan)
    order = [chosen] + [model for model in MODEL_COMPONENTS if model != chosen]
    model_path = None
    model_name = chosen
    for model in order:
        component = MODEL_COMPONENTS[model]
        if model == chosen:
            components.ensure([component], download=download)
        path = components.path_of(component)
        if path is not None and path.is_file():
            model_path, model_name = path, model
            break
    if model_path is None:
        missing.append(DISPLAY_NAMES[MODEL_COMPONENTS[chosen]])
    if missing or ffmpeg is None:
        return None, missing
    return Toolset(ffmpeg, whisper, model_path, model_name, vulkan), []


def estimate_seconds(audio_seconds: float, model: str, vulkan: bool) -> float:
    return max(0.0, audio_seconds) * REALTIME_FACTOR[bool(vulkan)].get(model, REALTIME_FACTOR[bool(vulkan)]["small"])


def format_clock(seconds: float) -> str:
    total = max(0, int(seconds))
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


# --- processo ----------------------------------------------------------------


def _popen(command: list[str], stderr, stdout=subprocess.DEVNULL) -> subprocess.Popen:
    """O único ponto que cria o processo (a suíte o troca por um simulador).
    Sem shell, sem janela, sem entrada; a saída padrão é descartada (o
    `whisper-cli` a usaria para imprimir o texto transcrito) e os avisos vão
    para o arquivo `stderr`."""
    kwargs: dict = {"stdin": subprocess.DEVNULL, "stdout": stdout, "stderr": stderr}
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        kwargs["startupinfo"] = startupinfo
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(command, shell=False, **kwargs)


def _kill_tree(process: subprocess.Popen) -> None:
    """Mata o processo e os filhos dele."""
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(process.pid)],
                shell=False, capture_output=True, timeout=30,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
    try:
        process.kill()
    except OSError:
        pass
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        pass


class _Process:
    """Um processo por vez (CPU e memória de um `whisper-cli` já bastam)."""

    def __init__(self, should_stop: Callable[[], bool] | None) -> None:
        self.should_stop = should_stop

    def run(self, command: list[str], timeout: float, log: Path, stdout_to: Path | None = None) -> tuple[int, str]:
        """`(código, fim do log)`. Levanta `Interrupted` quando
        Parar é pedido e `MediaError` ao estourar o tempo."""
        with open(log, "wb") as stream, open(stdout_to or os.devnull, "wb") as out:
            try:
                process = _popen(command, stream, out)
            except OSError as exc:
                raise MediaError(f"não foi possível iniciar {Path(command[0]).name}: {exc.strerror or 'erro'}") from exc
            deadline = time.monotonic() + max(1.0, timeout)
            try:
                while True:
                    try:
                        code = process.wait(timeout=0.5)
                        break
                    except subprocess.TimeoutExpired:
                        pass
                    if self.should_stop is not None and self.should_stop():
                        _kill_tree(process)
                        raise Interrupted()
                    if time.monotonic() > deadline:
                        _kill_tree(process)
                        raise MediaTimeout(
                            f"{Path(command[0]).name} passou do tempo limite ({int(timeout)} s) e foi encerrado"
                        )
            except BaseException:
                _kill_tree(process)
                raise
        return code, _log_tail(log)


def _log_tail(log: Path) -> str:
    try:
        return log.read_bytes()[-4096:].decode("utf-8", errors="replace")
    except OSError:
        return ""


def _last_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1][:200] if lines else ""


# --- áudio -------------------------------------------------------------------


def ffmpeg_command(ffmpeg: Path, source: Path, target: Path) -> list[str]:
    return [
        str(ffmpeg), "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
        # O contêiner (uma lista de reprodução, um `concat`) nunca busca URL
        # nem lê outro arquivo.
        "-protocol_whitelist", "file",
        "-i", str(source.resolve()),
        # Só a primeira faixa de áudio (se existir): sem vídeo, legenda ou dados.
        "-map", "0:a:0?", "-vn", "-sn", "-dn",
        "-ac", "1", "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le",
        "-t", str(MAX_AUDIO_SECONDS), "-f", "wav", str(target),
    ]


def probe_command(tools: Toolset, source: Path) -> list[str]:
    ffprobe = tools.ffmpeg.with_name("ffprobe" + tools.ffmpeg.suffix)
    return [
        str(ffprobe), "-v", "error", "-protocol_whitelist", "file",
        "-show_entries", "format=format_name", "-of", "default=noprint_wrappers=1:nokey=1", str(source.resolve()),
    ]


def check_container(tools: Toolset, source: Path, process: _Process, work: Path) -> None:
    """Recusa listas de reprodução e roteiros disfarçados de mídia (o
    `-protocol_whitelist file` ainda deixaria um `concat` ou HLS ler outros
    arquivos do disco). Levanta `MediaRefused` ou `MediaError`."""
    result = work / "formato.txt"
    code, log = process.run(
        probe_command(tools, source), PROCESS_TIMEOUT_MIN_S, work / "ffprobe.log", stdout_to=result
    )
    try:
        names = {item.strip().lower() for item in result.read_text(encoding="utf-8", errors="replace").split(",")}
    except OSError:
        names = set()
    result.unlink(missing_ok=True)
    names.discard("")
    if names & REFUSED_FORMATS:
        raise MediaRefused("o arquivo é uma lista de reprodução ou roteiro, não mídia")
    if code != 0 or not names:
        raise MediaError(f"o ffprobe não conseguiu ler o arquivo ({_last_line(log) or 'arquivo corrompido ou protegido'})")


def extract_audio(
    tools: Toolset, source: Path, wav: Path, process: _Process, size: int | None = None
) -> bool:
    """Grava o WAV de `source`; `False` quando o arquivo não tem faixa de
    áudio. Levanta `MediaError` para um arquivo ilegível."""
    partial = wav.with_name(wav.name + ".part")
    partial.unlink(missing_ok=True)
    size = source.stat().st_size if size is None else size
    timeout = EXTRACT_TIMEOUT_MIN_S + size / EXTRACT_READ_BYTES_PER_S
    code, log = process.run(ffmpeg_command(tools.ffmpeg, source, partial), timeout, wav.with_name("ffmpeg.log"))
    if code != 0 and "does not contain any stream" in log.lower():
        # `-map 0:a:0?` deixa a saída sem nenhuma faixa: o arquivo não tem áudio.
        partial.unlink(missing_ok=True)
        return False
    if code != 0 or not partial.is_file():
        partial.unlink(missing_ok=True)
        raise MediaError(f"o ffmpeg não conseguiu ler o arquivo ({_last_line(log) or 'arquivo corrompido ou protegido'})")
    os.replace(partial, wav)
    return True


def _frames_rms(samples: array.array, frame: int) -> list[float]:
    return [
        math.sqrt(sum(value * value for value in samples[start : start + frame]) / frame)
        for start in range(0, len(samples) - frame + 1, frame)
    ]


def find_cut(reader: wave.Wave_read, target: int, total: int) -> int:
    """O ponto de corte (em amostras) mais quieto perto de `target`: uma
    pausa da fala, não o meio de uma frase. Determinístico (a retomada refaz
    a mesma conta). Sem folga para procurar (fim do áudio), é o próprio
    `target`."""
    span = int(PAUSE_SEARCH_SECONDS * SAMPLE_RATE)
    frame = max(1, int(PAUSE_FRAME_SECONDS * SAMPLE_RATE))
    low, high = max(0, target - span), min(total, target + span)
    if high - low < 2 * frame:
        return min(target, total)
    reader.setpos(low)
    samples = array.array("h")
    samples.frombytes(reader.readframes(high - low))
    if sys.byteorder == "big":
        samples.byteswap()
    levels = _frames_rms(samples, frame)
    if not levels:
        return min(target, total)
    # O mais quieto; no empate, o mais perto do alvo.
    best = min(range(len(levels)), key=lambda index: (round(levels[index], 3), abs(low + index * frame - target)))
    return low + best * frame + frame // 2


def write_chunk(reader: wave.Wave_read, start: int, end: int, target: Path) -> None:
    reader.setpos(start)
    with wave.open(str(target), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SAMPLE_RATE)
        remaining = end - start
        while remaining > 0:
            piece = reader.readframes(min(remaining, SAMPLE_RATE * 30))
            if not piece:
                break
            out.writeframes(piece)
            remaining -= len(piece) // 2


# --- whisper -----------------------------------------------------------------


def whisper_command(tools: Toolset, wav: Path, output_base: Path, threads: int) -> list[str]:
    return [
        str(tools.whisper), "-m", str(tools.model), "-f", str(wav), "-l", "auto",
        "-oj", "-of", str(output_base), "-t", str(threads),
    ]


def parse_whisper_json(path: Path) -> tuple[list[tuple[float, float, str]], str]:
    """`([(início, fim, texto)], idioma)` do JSON do `whisper-cli`; tempos em
    segundos, relativos ao trecho."""
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        items = data["transcription"]
        language = str(((data.get("result") or {}).get("language")) or "")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise MediaError("o whisper.cpp não produziu uma transcrição legível") from exc
    segments: list[tuple[float, float, str]] = []
    for item in items:
        try:
            text = " ".join(str(item["text"]).split())
            offsets = item["offsets"]
            begin, end = float(offsets["from"]) / 1000.0, float(offsets["to"]) / 1000.0
        except (KeyError, TypeError, ValueError):
            continue
        if text and text.upper() != "[BLANK_AUDIO]":
            segments.append((begin, end, text))
    return segments, language


def format_page(start: float, end: float, segments: list[tuple[float, float, str]]) -> str:
    """A página de um trecho: a linha `[hh:mm:ss–hh:mm:ss]` e um segmento por
    linha."""
    header = f"[{format_clock(start)}–{format_clock(end)}]"
    return header + "\n" + "\n".join(text for _begin, _end, text in segments)


# --- progresso ---------------------------------------------------------------


def _read_progress(progress: Path, partial: Path, source: Path, model: str) -> dict | None:
    """O progresso gravado se vale para esta origem (mesmo tamanho e data),
    para este modelo e para este parcial (que tem aqueles bytes); senão
    `None`."""
    try:
        data = json.loads(progress.read_text(encoding="utf-8"))
        stat = source.stat()
        if (
            data["size"] == stat.st_size and data["mtime_ns"] == stat.st_mtime_ns and data["model"] == model
            and partial.stat().st_size >= data["bytes"]
        ):
            return {
                "offset": int(data["offset"]), "bytes": int(data["bytes"]), "pages": int(data["pages"]),
                "languages": {str(key): float(value) for key, value in dict(data["languages"]).items()},
            }
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def _write_progress(progress: Path, source: Path, model: str, state: dict) -> None:
    stat = source.stat()
    temporary = progress.with_name(progress.name + ".tmp")
    temporary.write_text(
        json.dumps({"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "model": model, **state}),
        encoding="utf-8",
    )
    os.replace(temporary, progress)


def _threads() -> int:
    try:
        from .parallelism import _physical_cores

        return max(1, min(8, int(_physical_cores())))
    except Exception:
        return max(1, min(8, (os.cpu_count() or 2) // 2))


# --- conversão ---------------------------------------------------------------

# `on_estimate(info)`: chamado uma vez, com o áudio já extraído e antes de
# transcrever, com `duration` e `remaining` (segundos de áudio), `estimate`
# (segundos de trabalho) e `model`/`vulkan`: a estimativa que o log mostra.
EstimateCallback = Callable[[dict], None]


def transcribe(
    source: Path,
    destination: Path,
    work: Path,
    tools: Toolset,
    should_stop: Callable[[], bool] | None = None,
    on_estimate: EstimateCallback | None = None,
) -> MediaResult:
    """Escreve em `destination` a transcrição, uma página por trecho de cerca
    de 5 minutos, separadas por `MBOX_PAGE_SEPARATOR`.

    Levanta `Interrupted` quando Parar é pedido (o que já foi escrito fica
    para a retomada) e `MediaError` para um arquivo ilegível ou que passou do
    tempo limite (nesse caso o progresso é apagado). `work` é a pasta local
    deste arquivo (o WAV e os arquivos de cada trecho); é apagada no fim, mas
    não ao Parar."""
    partial = destination.with_name(destination.name + PARTIAL_SUFFIX)
    progress = destination.with_name(destination.name + PROGRESS_SUFFIX)
    wav = work / WORK_WAV
    saved = _read_progress(progress, partial, source, tools.model_name)
    if saved is None:
        # Origem trocada, outro modelo ou progresso ilegível: recomeça.
        shutil.rmtree(work, ignore_errors=True)
        partial.unlink(missing_ok=True)
        progress.unlink(missing_ok=True)
        saved = {"offset": 0, "bytes": 0, "pages": 0, "languages": {}}
    work.mkdir(parents=True, exist_ok=True)
    runner = _Process(should_stop)
    try:
        if not wav.is_file():
            check_container(tools, source, runner, work)
            if not extract_audio(tools, source, wav, runner):
                return _finish_empty(destination, partial, progress, work, no_audio=True)
        return _transcribe_wav(source, destination, partial, progress, work, wav, tools, runner, saved, on_estimate)
    except (Interrupted, Postponed, MediaTimeout):
        # Nada do que já foi transcrito é jogado fora.
        raise
    except BaseException:
        # Falha (ou qualquer erro inesperado): nada fica para trás.
        shutil.rmtree(work, ignore_errors=True)
        partial.unlink(missing_ok=True)
        progress.unlink(missing_ok=True)
        raise


def _finish_empty(destination: Path, partial: Path, progress: Path, work: Path, no_audio: bool) -> MediaResult:
    shutil.rmtree(work, ignore_errors=True)
    partial.unlink(missing_ok=True)
    progress.unlink(missing_ok=True)
    destination.write_text("", encoding="utf-8")
    destination.with_name(destination.name + LANGUAGE_SUFFIX).unlink(missing_ok=True)
    return MediaResult(pages=1, no_audio=no_audio)


def _transcribe_wav(
    source: Path, destination: Path, partial: Path, progress: Path, work: Path, wav: Path,
    tools: Toolset, runner: _Process, saved: dict, on_estimate: EstimateCallback | None,
) -> MediaResult:
    try:
        reader = wave.open(str(wav), "rb")
    except (wave.Error, EOFError, OSError) as exc:
        raise MediaError("o áudio extraído é ilegível") from exc
    languages: Counter = Counter(saved["languages"])
    offset, size, pages = saved["offset"], saved["bytes"], saved["pages"]
    truncated = None
    with reader:
        total = reader.getnframes()
        duration = total / SAMPLE_RATE
        remaining = max(0.0, (total - offset) / SAMPLE_RATE)
        estimate = estimate_seconds(remaining, tools.model, tools.vulkan)
        if on_estimate is not None:
            try:
                on_estimate({
                    "duration": duration, "remaining": remaining, "estimate": estimate,
                    "model": tools.model_name, "vulkan": tools.vulkan,
                })
            except Exception:
                # O aviso é só informação: um erro ao gravá-lo (banco ocupado)
                # não pode jogar fora o progresso do arquivo.
                pass
        if duration >= MAX_AUDIO_SECONDS - 1:
            truncated = "duration"
        # Orçamento desta execução: 3x a estimativa até o primeiro trecho ser
        # medido; dali em diante, 3x o que a velocidade real do primeiro trecho
        # projeta para o áudio restante (uma máquina mais lenta que a tabela
        # não estoura sozinha). Estourar não perde nada: o progresso fica e o
        # arquivo volta na próxima conversão.
        run_start = time.monotonic()
        projected = estimate
        measured = False
        chunk_timeout = max(
            PROCESS_TIMEOUT_MIN_S, PROCESS_TIMEOUT_FACTOR * estimate_seconds(CHUNK_SECONDS, tools.model, tools.vulkan)
        )
        threads = _threads()
        chunk_wav, out_base = work / "trecho.wav", work / "trecho"
        with open(partial, "ab") as handle:
            handle.truncate(size)
            handle.seek(size)
            while offset < total:
                if total - offset < MIN_TAIL_SECONDS * SAMPLE_RATE:
                    break
                if size >= MAX_OUTPUT_BYTES:
                    truncated = "output"
                    break
                if runner.should_stop is not None and runner.should_stop():
                    handle.flush()
                    raise Interrupted()
                target = offset + CHUNK_SECONDS * SAMPLE_RATE
                end = total if total - target < MIN_TAIL_SECONDS * SAMPLE_RATE else find_cut(reader, target, total)
                if end <= offset:
                    end = min(total, target)
                if total - end < MIN_TAIL_SECONDS * SAMPLE_RATE:
                    end = total
                write_chunk(reader, offset, end, chunk_wav)
                if time.monotonic() - run_start > max(FILE_TIMEOUT_MIN_S, FILE_TIMEOUT_FACTOR * projected):
                    handle.flush()
                    raise Postponed()
                chunk_started = time.monotonic()
                result_json = out_base.with_name(out_base.name + ".json")
                result_json.unlink(missing_ok=True)
                code, _detail = runner.run(
                    whisper_command(tools, chunk_wav, out_base, threads), chunk_timeout, work / "whisper.log"
                )
                if code != 0 or not result_json.is_file():
                    raise MediaError(f"o whisper.cpp falhou ao transcrever o trecho em {format_clock(offset / SAMPLE_RATE)}")
                segments, language = parse_whisper_json(result_json)
                if segments:
                    page = format_page(offset / SAMPLE_RATE, end / SAMPLE_RATE, segments)[:MAX_PAGE_CHARS]
                    chunk = ((MBOX_PAGE_SEPARATOR if pages else "") + page.replace("\x0c", " ")).encode("utf-8")
                    handle.write(chunk)
                    size += len(chunk)
                    pages += 1
                    if language:
                        languages[language] += (end - offset) / SAMPLE_RATE
                handle.flush()
                if not measured and end > offset:
                    measured = True
                    projected = (time.monotonic() - chunk_started) / ((end - offset) / SAMPLE_RATE) * remaining
                offset = end
                _write_progress(progress, source, tools.model_name, {
                    "offset": offset, "bytes": size, "pages": pages, "languages": dict(languages),
                })

    language = languages.most_common(1)[0][0] if languages else ""
    if pages == 0:
        # Nenhuma fala (ou só silêncio): uma página vazia, como um arquivo vazio.
        partial.write_text("", encoding="utf-8")
        pages = 1
    os.replace(partial, destination)
    sidecar = destination.with_name(destination.name + LANGUAGE_SUFFIX)
    if language:
        sidecar.write_text(language, encoding="utf-8")
    else:
        # Sem idioma (nenhuma fala): nada de um `.idioma` de transcrição anterior.
        sidecar.unlink(missing_ok=True)
    progress.unlink(missing_ok=True)
    shutil.rmtree(work, ignore_errors=True)
    return MediaResult(pages=pages, language=language, duration=duration, truncated=truncated)
