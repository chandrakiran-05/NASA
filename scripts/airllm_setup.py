#!/usr/bin/env python3
"""Pick and prepare the deep-review model (AirLLM) for THIS machine.

    python scripts/airllm_setup.py               # hardware, recommendation and the exact commands
    python scripts/airllm_setup.py --size 32b    # explicit opt-in to a bigger, much slower model
    python scripts/airllm_setup.py --download    # download + split the model now (tens of GB)

AirLLM re-reads every layer from disk for every generated token, so expect seconds (14B) to tens of
seconds (72B) per token. The deep tier is for background jobs on a few results, never live use.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.core import hardware  # noqa: E402
from backend.core.config import get_settings  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--size", choices=list(hardware.DEEP), default="14b", help="deep model size (default 14b)")
    ap.add_argument("--download", action="store_true", help="download and split the deep model now")
    a = ap.parse_args()

    s = get_settings()
    prof = hardware.probe(s.deep_llm_layer_dir)
    rec = hardware.recommend(prof, a.size)
    pk = ", ".join(f"{k} {'yes' if v else 'NO'}" for k, v in prof["packages"].items())
    print(f"Machine   {prof['os']}")
    print(f"GPU       {prof['gpu_name'] or '-'}  {prof['vram_total_gb']:g} GB VRAM ({prof['vram_free_gb']:g} GB free)"
          + (f"  [{prof['gpu_note']}]" if prof["gpu_note"] else ""))
    print(f"RAM       {prof['ram_total_gb']:g} GB ({prof['ram_available_gb']:g} GB available)")
    print(f"Disk      {prof['disk_free_gb']:g} GB free at {prof['disk_path']}")
    print(f"Packages  {pk}\n")

    live = rec["live"]
    print(f"LIVE tier  {live['model']} via Ollama: {live['why']}")
    print(f"           .env: LLM_PROVIDER=ollama  LLM_MODEL={live['model']}\n")
    deep = rec["deep"]
    if deep:
        lo, hi = deep["approx_seconds_per_token"]
        print(f"DEEP tier  {deep['model']} via AirLLM, {deep['compression']}, max {deep['max_new_tokens']} new tokens")
        print(f"           estimated {lo}-{hi} s per token; needs ~{deep['disk_needed_gb']} GB disk")
        print(f"           {deep['why']}\n")
    else:
        print("DEEP tier  off for now (see notes)\n")
    for n in rec["notes"]:
        print(f"note: {n}")

    repo = s.deep_llm_model or (deep or {}).get("model") or hardware.DEEP[a.size][0]
    size = "" if a.size == "14b" else f" --size {a.size}"
    print("\nCommands (run in the project venv):")
    print(f"  1. {hardware.TORCH_CUDA}")
    print("  2. pip install -r requirements-airllm.txt")
    print(f"  3. python scripts/airllm_setup.py --download{size}    # downloads and splits {repo}")
    print(f"  4. .env: DEEP_LLM_PROVIDER=airllm  DEEP_LLM_MODEL={repo}  "
          f"DEEP_LLM_MAX_NEW_TOKENS={(deep or {}).get('max_new_tokens', 64)}")

    if not a.download:
        return 0
    if deep is None:
        print("\nNot downloading: fix the notes above first.")
        return 1
    from backend.ai.deep_llm import load_airllm
    print(f"\nDownloading and splitting {repo} (tens of GB; can take an hour) ...")
    t0 = time.perf_counter()
    generate = load_airllm(repo, s)
    print(f"ready in {(time.perf_counter() - t0) / 60:.1f} min. Measuring speed with a 4-token answer ...")
    t0 = time.perf_counter()
    out = generate([{"role": "user", "content": "Reply with the single word OK."}], 4)
    print(f"answer {out!r}: about {(time.perf_counter() - t0) / 5:.1f} s per token on this machine "
          f"(prompt pass + 4 tokens, first CUDA call included)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
