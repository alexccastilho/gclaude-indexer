"""Which model the `local` engine runs: the two profiles, the model a new
project starts with, and the model a project resolves to.

Kept out of `engine_local` on purpose: the screen, the installation
diagnostics, the quality report and the orchestrator only need these
answers, and they change for product and measurement reasons, while the
engine changes with the protocol spoken to Ollama. Nothing here imports
`engine_local`.
"""

from __future__ import annotations

from . import hardware, ollama_models
from .config import ProjectConfig
from .ollama_models import DEFAULT_LOCAL_MODEL

# A card with 8 GB or more of VRAM holds the 9B model whole, and the
# bigger model reads names, signatures and dates better. Cards of 6 GB or
# less keep `qwen3.5:4b`: measured on a 6 GB laptop card, every larger
# model tried (bonsai-2:9b, ornith-1.5:9b, qwen3-vl:8b) spilled into system
# RAM and ran 2x to 9x slower, some failing windows. 8 GB cards report a
# little under 8192 MB, hence the margin.
LARGE_MODEL_MIN_VRAM_MB = 7680

# 2.1.0: two profiles the project chooses between, instead of a model name.
# Measured on the demo collection and on a real 83-page case file,
# with an answer key for each: `ornith-1.5:9b` (a Qwen 3.5 9B fine-tune)
# finds the documents' limits best and slices them least, at about twice
# the time of `qwen3.5:4b`, which is the fastest and finds the start of
# as many documents. `qwen3.5:9b` lost to both on the real file (it found
# fewer document starts and merged more), so it is no longer a default.
# A model name still works as a value, for whoever wants to compare.
QUALITY_LOCAL_MODEL = "ornith-1.5:9b"
PROFILE_FAST = "fast"
PROFILE_QUALITY = "quality"
LOCAL_MODEL_PROFILES: dict[str, str] = {PROFILE_FAST: DEFAULT_LOCAL_MODEL, PROFILE_QUALITY: QUALITY_LOCAL_MODEL}

@hardware.measured_once
def gpu_vram_mb() -> int:
    """Total VRAM of the dedicated graphics card, in MB (0 without one).
    Measured once per process."""
    try:
        gpu = hardware.detect_gpu()
        return int(gpu.vram_mb) if gpu else 0
    except Exception:
        return 0


def default_local_profile(vram_mb: int | None = None) -> str:
    """The profile a new project starts with: best quality on a card with
    8 GB of VRAM or more (the 9B model fits whole), fastest otherwise (a
    larger model spills into system RAM there and runs several times
    slower)."""
    if vram_mb is None:
        vram_mb = gpu_vram_mb()
    return PROFILE_QUALITY if vram_mb >= LARGE_MODEL_MIN_VRAM_MB else PROFILE_FAST


def recommended_local_model(vram_mb: int | None = None) -> str:
    """The model of the default profile: `ornith-1.5:9b` for a card with
    8 GB of VRAM or more, `qwen3.5:4b` otherwise."""
    return LOCAL_MODEL_PROFILES[default_local_profile(vram_mb)]


def model_to_use(config: ProjectConfig) -> str:
    """Model the 'local' engine will use.

    The user's choice in the form wins; `DEFAULT_LOCAL_MODEL` is just the
    default. This function used to ignore `config.local_model` and always
    return the default — the selector on the screen was decorative. It
    started to matter when the user asked to compare the quality of
    different models, which is impossible if every run uses the same one.
    """
    chosen = (config.local_model or "").strip()
    if chosen in LOCAL_MODEL_PROFILES:
        recommended = LOCAL_MODEL_PROFILES[chosen]
    elif chosen and chosen != "automatic":
        return chosen
    else:
        recommended = recommended_local_model()
    if recommended != DEFAULT_LOCAL_MODEL:
        # A machine upgraded from an older version may not have the 9B model
        # yet; the 4B one it already has beats waiting for a download.
        try:
            downloaded = ollama_models.model_downloaded_on_disk
            if not downloaded(recommended) and downloaded(DEFAULT_LOCAL_MODEL):
                return DEFAULT_LOCAL_MODEL
        except Exception:
            pass
    return recommended
