"""Publish the last git commit to a Hugging Face Docker Space.

Usage (from the repo root, with your HF write token in the environment, never in a file):
    set HF_TOKEN=hf_...            (PowerShell: $env:HF_TOKEN="hf_...")
    .venv\\Scripts\\python deploy\\hf\\publish_space.py <hf-username>/<space-name>
    add --dry-run to only build and list the upload folder

What it does: creates the Space if missing (Docker SDK), stores EARTHDATA_TOKEN from .env as a Space
secret (encrypted on HF, never in the files), and uploads the committed code with deploy/hf/Dockerfile
at the root. The Space then builds itself (about 10-20 minutes the first time).
"""
from __future__ import annotations

import argparse
import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HF = ROOT / "deploy" / "hf"
CARD = """---
title: Earth System Trend Detective
emoji: 🌍
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
short_description: Is this Earth trend real? NASA data, tested and explained.
---

NASA Space Apps 2026: Earth System Trend Detective. Source: https://github.com/chandrakiran-05/NASA
"""


def stage(dst: Path) -> None:
    tar = subprocess.run(["git", "archive", "--format=tar", "HEAD"], cwd=ROOT, check=True, capture_output=True).stdout
    with tarfile.open(fileobj=io.BytesIO(tar)) as t:
        t.extractall(dst, filter="data")
    shutil.copytree(HF, dst / "deploy" / "hf", dirs_exist_ok=True)     # latest deploy files even if uncommitted
    shutil.copy(HF / "Dockerfile", dst / "Dockerfile")
    (dst / "README.md").write_text(CARD, encoding="utf-8")
    (dst / ".dockerignore").write_text(".git\nfrontend/node_modules\nfrontend/dist\n.venv\ndata/cache\n", encoding="utf-8")


def env_value(key: str) -> str | None:
    env = ROOT / ".env"
    if not env.exists():
        return None
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip() or None
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("space", help="<hf-username>/<space-name>")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if "/" not in a.space:
        sys.exit("space must look like <hf-username>/<space-name>")
    dirty = subprocess.run(["git", "status", "--porcelain", "--", "backend", "frontend", "requirements.txt"],
                           cwd=ROOT, capture_output=True, text=True).stdout.strip()
    if dirty:
        print("warning: uncommitted changes in backend/frontend are NOT uploaded (only the last commit is)")

    with tempfile.TemporaryDirectory() as tmp:
        dst = Path(tmp)
        stage(dst)
        files = [p for p in dst.rglob("*") if p.is_file()]
        print(f"staged {len(files)} files, {sum(p.stat().st_size for p in files) / 1e6:.1f} MB")
        assert (dst / "Dockerfile").exists() and not (dst / ".env").exists()
        if a.dry_run:
            print("dry run: nothing uploaded")
            return

        from huggingface_hub import HfApi
        if not os.environ.get("HF_TOKEN"):
            sys.exit("set HF_TOKEN to a Hugging Face token with write access first")
        api = HfApi()
        api.create_repo(a.space, repo_type="space", space_sdk="docker", exist_ok=True)
        token = env_value("EARTHDATA_TOKEN")
        if token:
            api.add_space_secret(a.space, "EARTHDATA_TOKEN", token)
            print("EARTHDATA_TOKEN stored as a Space secret")
        else:
            print("no EARTHDATA_TOKEN in .env: the Space uses the keyless NOAA sources only")
        api.upload_folder(repo_id=a.space, repo_type="space", folder_path=dst, delete_patterns="*",
                          commit_message="Deploy from GitHub main")
    print(f"Uploaded. Build log: https://huggingface.co/spaces/{a.space}  Site: "
          f"https://{a.space.replace('/', '-').replace('_', '-').lower()}.hf.space")


if __name__ == "__main__":
    main()
