"""Hardware probe and per-machine model choice for the two LLM tiers.

live tier  LocalLLM via Ollama: a small model that fits in VRAM and answers in seconds. Unchanged.
deep tier  DeepLLM via AirLLM (optional): a bigger model run layer by layer from disk. Only one layer
           sits in VRAM, so a 14B-72B model runs on a 4 GB GPU, but EVERY layer is re-read from disk
           for EVERY generated token. On a laptop NVMe (roughly 2-4 GB/s) a 4-bit 14B model (~8 GB of
           layers) costs a few seconds per token and a 4-bit 72B model (~41 GB) tens of seconds. That
           is far too slow for interactive use, and R1-style reasoning models that write thousands of
           "thinking" tokens are impractical. So the deep tier runs only as a background job on a few
           top results, with a hard cap on new tokens and a short JSON answer, and it is advisory:
           deterministic code decides every number and verdict (docs/07-trend-forensics.md §4-5).

All speeds here are estimates (layer bytes / disk speed), not measurements.
`python scripts/airllm_setup.py --download` measures the real figure on a machine.
"""
from __future__ import annotations

import ctypes
import importlib.util
import math
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

GiB = 1024 ** 3
PACKAGES = ("torch", "airllm", "bitsandbytes")
TORCH_CUDA = "pip install torch --index-url https://download.pytorch.org/whl/cu126"

# Live tier (Ollama). (min VRAM GiB, tag, q4_K_M weights GB from ollama.com/library/qwen3.5, why)
LIVE = [
    (24, "qwen3.5:27b", 17.0, "17 GB of 4-bit weights fit in VRAM with room for context"),
    (10, "qwen3.5:9b", 6.6, "6.6 GB of 4-bit weights fit in VRAM"),
    (4, "qwen3.5:4b", 3.3, "3.3 GB of 4-bit weights fit in 4 GB VRAM (tight: if `ollama ps` shows CPU "
                           "offload, use qwen3.5:2b)"),
    (0, "qwen3.5:2b", 2.7, "small enough for CPU or a very small GPU"),
]

# Deep tier (AirLLM). Qwen2 architecture: supported by AirLLM's generic base model.
# size: (HF repo, 4-bit layer GB read per token, peak disk GB = bf16 download + 4-bit split + margin,
#        max new tokens so that (1 + n) passes stay inside the default 30 min timeout)
DEEP = {
    "14b": ("Qwen/Qwen2.5-14B-Instruct", 8.0, 42, 64),
    "32b": ("Qwen/Qwen2.5-32B-Instruct", 18.0, 92, 64),
    "72b": ("Qwen/Qwen2.5-72B-Instruct", 41.0, 205, 48),
}


def packages() -> dict[str, bool]:
    """Importable without importing (torch is never imported here)."""
    return {p: importlib.util.find_spec(p) is not None for p in PACKAGES}


def _gpu() -> dict:
    none = {"gpu_name": None, "vram_total_gb": 0.0, "vram_free_gb": 0.0}
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,memory.free",
                            "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=15)
    except FileNotFoundError:
        return {**none, "gpu_note": "nvidia-smi not found (no NVIDIA GPU or driver)"}
    except (OSError, subprocess.SubprocessError) as exc:
        return {**none, "gpu_note": f"nvidia-smi failed: {type(exc).__name__}"}
    rows = []
    for line in (r.stdout or "").splitlines():
        parts = [p.strip() for p in line.split(",")]
        try:
            rows.append((parts[0], float(parts[1]), float(parts[2])))
        except (IndexError, ValueError):
            continue
    if r.returncode != 0 or not rows:
        return {**none, "gpu_note": "no NVIDIA GPU found: " + ((r.stdout or "") + (r.stderr or "")).strip()[:160]}
    name, total, free = max(rows, key=lambda row: row[1])           # MiB; biggest GPU wins
    return {"gpu_name": name, "vram_total_gb": round(total / 1024, 1), "vram_free_gb": round(free / 1024, 1),
            "gpu_note": None}


def _ram() -> tuple[float, float]:
    """(total, available) GiB: psutil, else Windows GlobalMemoryStatusEx, else /proc/meminfo."""
    try:
        import psutil
        vm = psutil.virtual_memory()
        return vm.total / GiB, vm.available / GiB
    except ImportError:
        pass
    if sys.platform == "win32":
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong)] + [
                (f, ctypes.c_ulonglong) for f in ("ullTotalPhys", "ullAvailPhys", "ullTotalPageFile",
                                                  "ullAvailPageFile", "ullTotalVirtual", "ullAvailVirtual",
                                                  "ullAvailExtendedVirtual")]
        m = MEMORYSTATUSEX()
        m.dwLength = ctypes.sizeof(m)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            return m.ullTotalPhys / GiB, m.ullAvailPhys / GiB
        return 0.0, 0.0
    try:
        info = dict(line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines() if ":" in line)
        return (float(info["MemTotal"].split()[0]) / 1024 ** 2, float(info["MemAvailable"].split()[0]) / 1024 ** 2)
    except (OSError, KeyError, ValueError):
        return 0.0, 0.0


def default_disk_path() -> Path:
    """Where AirLLM's download and split layers land unless DEEP_LLM_LAYER_DIR says otherwise."""
    return Path(os.environ.get("HF_HOME") or Path.home() / ".cache" / "huggingface")


def probe(disk_path: str | Path | None = None) -> dict:
    p = Path(disk_path or default_disk_path()).expanduser().resolve()
    while not p.exists() and p != p.parent:                         # not created yet: use its drive
        p = p.parent
    ram_total, ram_avail = _ram()
    return {"os": platform.platform(), **_gpu(),
            "ram_total_gb": round(ram_total, 1), "ram_available_gb": round(ram_avail, 1),
            "disk_path": str(p), "disk_free_gb": round(shutil.disk_usage(p).free / GiB, 1),
            "packages": packages()}


def recommend(profile: dict, size: str = "14b") -> dict:
    """Live + deep model for a probe() profile. size="32b"/"72b" is the explicit opt-in to bigger models."""
    vram = profile.get("vram_total_gb") or 0.0
    _, tag, weights, why = next(row for row in LIVE if vram >= row[0])
    live = {"provider": "ollama", "model": tag, "weights_gb": weights, "why": f"{why}; run: ollama pull {tag}"}
    out = {"live": live, "deep": None, "notes": []}
    notes = out["notes"]
    if vram >= 24:
        notes.append(f"{vram:g} GB VRAM holds a large model directly: run it in Ollama or vLLM. AirLLM "
                     f"(layer-by-layer from disk) would only be slower, so the deep tier is off.")
        return out
    if vram < 4:
        notes.append("AirLLM needs an NVIDIA GPU with at least 4 GB VRAM; on CPU it is slower still. Deep tier off.")
        return out

    repo, layers_gb, disk_gb, n_new = DEEP[size]
    # best case: whole 4-bit model read at 4 GB/s; worst: 2 GB/s plus ~50% for dequantising and PCIe copies
    lo, hi = round(layers_gb / 4, 1), round(layers_gb / 2 * 1.5, 1)
    free = profile.get("disk_free_gb") or 0.0
    if free < disk_gb:
        notes.append(f"{repo} needs about {disk_gb} GB free at {profile.get('disk_path')} (bf16 download + 4-bit "
                     f"split layers); only {free:g} GB is free. Free space, or point HF_HOME and "
                     f"DEEP_LLM_LAYER_DIR at a bigger drive.")
    missing = [p for p in PACKAGES if not (profile.get("packages") or {}).get(p)]
    if missing:
        notes.append(f"Missing packages: {', '.join(missing)}. Install a CUDA build of PyTorch first "
                     f"({TORCH_CUDA}), then: pip install -r requirements-airllm.txt. The deep tier would use {repo}.")
    if notes:
        return out

    minutes = (int(lo * (n_new + 1) / 60), math.ceil(hi * (n_new + 1) / 60))   # prompt pass + n tokens
    out["deep"] = {"provider": "airllm", "model": repo, "compression": "4bit", "max_new_tokens": n_new,
                   "approx_seconds_per_token": [lo, hi], "disk_needed_gb": disk_gb,
                   "why": f"{size.upper()} instruct model at 4-bit: AirLLM streams one layer at a time through "
                          f"{vram:g} GB VRAM, re-reading ~{layers_gb:g} GB per token, so an estimated {lo}-{hi} s "
                          f"per token and ~{minutes[0]}-{minutes[1]} min for a {n_new}-token answer. "
                          f"Background jobs only; advisory."}
    notes.append("Speeds are estimates from layer size / disk speed (2-4 GB/s NVMe), not measurements; "
                 "`python scripts/airllm_setup.py --download` measures this machine. A 16 GB RAM file cache "
                 "can make a 14B model faster after the first token.")
    notes.append("R1-style reasoning models (DeepSeek-R1-Distill-Qwen/Llama) load in AirLLM too, but they write "
                 "hundreds to thousands of thinking tokens before answering: hours per answer here. Not recommended.")
    if size != "14b":
        notes.append(f"Opt-in {size.upper()}: estimated {lo}-{hi} s per token, ~{minutes[0]}-{minutes[1]} min per "
                     f"answer. Use it only for a handful of top results.")
    return out
