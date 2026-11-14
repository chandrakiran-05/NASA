from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.core.config import Settings  # noqa: E402
from tests.fakes import FakeUpstream, transport  # noqa: E402


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        earthdata_token="fake-edl-token",
        earthdata_username="student",
        earthdata_password="secret",
        noaa_cdo_token="fake-cdo-token",
        http_backoff_base_s=0.01,
        http_max_retries=3,
        appeears_poll_s=0.01,
        llm_provider="ollama",
        llm_base_url="http://127.0.0.1:11434",
        min_months_for_test=120,
        _env_file=None,
    )


@pytest.fixture
def fake(monkeypatch) -> FakeUpstream:
    from backend.connectors.harmony_area import HarmonyArea
    from tests.fakes import fake_harmony_run_sync
    monkeypatch.setattr(HarmonyArea, "_run_sync", fake_harmony_run_sync)
    return FakeUpstream()


@pytest.fixture
def client(settings, fake):
    from fastapi.testclient import TestClient

    from backend.main import create_app
    app = create_app(settings, transport=transport(fake), llm_transport=transport(fake))
    with TestClient(app) as c:
        c.fake = fake
        yield c


def wait_job(client, job_id: str, timeout: float = 30.0) -> dict:
    import time
    deadline = time.monotonic() + timeout
    while True:
        j = client.get(f"/api/jobs/{job_id}", params={"wait": min(10.0, max(timeout, 0.1))}).json()
        if j.get("status") in ("done", "error") or time.monotonic() > deadline:
            break
    assert j["status"] in ("done", "error"), j
    return j
