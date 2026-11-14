import asyncio
import subprocess
import time

import pytest

from backend.ai.deep_llm import DeepLLM, first_json
from backend.core import hardware
from backend.core.config import Settings

ALL = {"torch": True, "airllm": True, "bitsandbytes": True}
LAPTOP = {"gpu_name": "NVIDIA GeForce RTX 3050 Laptop GPU", "vram_total_gb": 4.0, "vram_free_gb": 3.6,
          "ram_total_gb": 16.0, "ram_available_gb": 9.0, "disk_path": "C:\\", "disk_free_gb": 200.0, "packages": ALL}
MSGS = [{"role": "system", "content": "You review trends."}, {"role": "user", "content": "FACTS: {}"}]


def test_recommend_rtx3050_laptop():
    r = hardware.recommend(LAPTOP)
    d = r["deep"]
    assert d["provider"] == "airllm" and d["model"] == "Qwen/Qwen2.5-14B-Instruct" and d["compression"] == "4bit"
    lo, hi = d["approx_seconds_per_token"]
    assert 0 < lo < hi and d["max_new_tokens"] <= 96 and d["disk_needed_gb"] < 200
    assert r["live"]["provider"] == "ollama" and r["live"]["weights_gb"] < 4.0
    assert any("estimate" in n for n in r["notes"])


def test_recommend_big_model_needs_opt_in_and_states_time():
    r = hardware.recommend({**LAPTOP, "disk_free_gb": 250.0}, "72b")       # 72B needs ~205 GB while splitting
    assert "72B" in r["deep"]["model"] and r["deep"]["approx_seconds_per_token"][0] >= 10
    assert any(n.startswith("Opt-in 72B") and "s per token" in n for n in r["notes"])


def test_recommend_24gb_gpu_skips_airllm():
    r = hardware.recommend({**LAPTOP, "vram_total_gb": 24.0})
    assert r["deep"] is None and r["live"]["model"] == "qwen3.5:27b"
    assert any("Ollama or vLLM" in n for n in r["notes"])


@pytest.mark.parametrize("change, hint", [({"disk_free_gb": 20.0}, "GB free"),
                                          ({"packages": {**ALL, "torch": False, "airllm": False}},
                                           "requirements-airllm.txt"),
                                          ({"vram_total_gb": 0.0, "gpu_name": None}, "4 GB VRAM")])
def test_recommend_off_with_notes(change, hint):
    r = hardware.recommend({**LAPTOP, **change})
    assert r["deep"] is None and any(hint in n for n in r["notes"]), r["notes"]


def test_probe_parses_nvidia_smi(monkeypatch, tmp_path):
    out = "NVIDIA GeForce RTX 3050 Laptop GPU, 4096, 3695\n"
    monkeypatch.setattr(hardware.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, out, ""))
    p = hardware.probe(tmp_path / "not" / "created")              # missing dir -> nearest existing parent
    assert p["gpu_name"] == "NVIDIA GeForce RTX 3050 Laptop GPU" and p["gpu_note"] is None
    assert (p["vram_total_gb"], p["vram_free_gb"]) == (4.0, 3.6)
    assert p["ram_total_gb"] > 0 and p["disk_free_gb"] > 0 and set(p["packages"]) == set(hardware.PACKAGES)


def _no_smi(*a, **k):
    raise FileNotFoundError("nvidia-smi")


@pytest.mark.parametrize("run, note", [
    (_no_smi, "not found"),
    (lambda *a, **k: subprocess.CompletedProcess(a, 9, "No devices were found\n", ""), "No devices"),
])
def test_probe_without_gpu(monkeypatch, tmp_path, run, note):
    monkeypatch.setattr(hardware.subprocess, "run", run)
    p = hardware.probe(tmp_path)
    assert p["gpu_name"] is None and p["vram_total_gb"] == 0 and note in p["gpu_note"]
    assert hardware.recommend(p)["deep"] is None


def _deep(**kw) -> Settings:
    return Settings(_env_file=None, deep_llm_provider="airllm", deep_llm_model="Qwen/Qwen2.5-14B-Instruct", **kw)


def test_deep_llm_json_from_fake_loader():
    seen = {}

    def loader(model_id, s):
        seen["model"] = model_id

        def generate(messages, n):
            seen["n"], seen["prompt"] = n, messages[-1]["content"]
            return '<think>{draft}</think> Sure:\n```json\n{"plausible": true, "note": "a {brace}"}\n``` {"x": 1}'
        return generate

    llm = DeepLLM(_deep(deep_llm_max_new_tokens=48), loader=loader)
    assert llm.enabled
    out = asyncio.run(llm.chat_json(MSGS, {"type": "object"}, max_tokens=500))
    assert out == {"plausible": True, "note": "a {brace}"}
    assert seen == {"model": "Qwen/Qwen2.5-14B-Instruct", "n": 48, "prompt": seen["prompt"]}
    assert seen["prompt"].startswith("FACTS: {}") and "JSON schema" in seen["prompt"]
    st = asyncio.run(llm.status())
    assert st["available"] and st["loaded"] and st["last_error"] is None


def test_deep_llm_failures_return_none():
    def oom(model_id, s):
        raise RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB")
    llm = DeepLLM(_deep(), loader=oom)
    assert asyncio.run(llm.chat_json(MSGS, {"type": "object"})) is None
    assert "out of memory" in llm.last_error and not asyncio.run(llm.status())["loaded"]

    llm = DeepLLM(_deep(), loader=lambda m, s: lambda msgs, n: "I am not sure.")
    assert asyncio.run(llm.chat_json(MSGS, {"type": "object"})) is None and "no JSON" in llm.last_error


def test_deep_llm_timeout_blocks_overlap_until_worker_ends():
    def slow(msgs, n):
        time.sleep(0.4)
        return '{"ok": true}'
    llm = DeepLLM(_deep(deep_llm_timeout_s=0.05), loader=lambda m, s: slow)

    async def go():
        first = await llm.chat_json(MSGS, {})
        second = await llm.chat_json(MSGS, {})                    # worker of the first call is still running
        await asyncio.sleep(0.5)
        llm.s.deep_llm_timeout_s = 5
        return first, second, await llm.chat_json(MSGS, {})
    assert asyncio.run(go()) == (None, None, {"ok": True})


def test_deep_llm_disabled_by_default():
    called = []
    llm = DeepLLM(Settings(_env_file=None), loader=lambda m, s: called.append(m))
    assert not llm.enabled and llm.provider == "none"
    assert asyncio.run(llm.chat_json(MSGS, {})) is None and not called
    assert asyncio.run(llm.status())["available"] is False


def test_first_json():
    assert first_json('```json\n{"a": [1, {"b": 2}]}\n```') == {"a": [1, {"b": 2}]}
    assert first_json('{"a": 1') is None and first_json(None) is None
