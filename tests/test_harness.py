"""Harness pack: config validation, no secrets in GET /api/harness, model probe gate, CLI ask --json."""
import asyncio
import json

import pytest

from backend.ai.llm import LocalLLM
from backend.harness import cli, config as hc
from backend.harness.models import probe
from tests.fakes import transport

FAITHFUL = ("Near-surface air temperature in Testland rose by about 0.27 °C per decade from 1995 to 2024. "
            "This rise is statistically significant.")
INVENTED = ("Near-surface air temperature in Testland rose by about 0.9 °C per decade from 1995 to 2024. "
            "This rise is statistically significant.")


def test_config_validation_errors():
    with pytest.raises(hc.HarnessConfigError, match="model.provider"):
        hc.parse({"model": {"provider": "chatgpt-cloud"}})
    with pytest.raises(hc.HarnessConfigError, match="model.name is required"):
        hc.parse({"model": {"provider": "ollama", "name": ""}})
    with pytest.raises(hc.HarnessConfigError, match="environment variable NAME"):
        hc.parse({"data": {"credentials": {"earthdata_token": "eyJhbGciOiJSUzI1NiJ9.secret"}}})
    with pytest.raises(hc.HarnessConfigError, match="min_years"):
        hc.parse({"pipeline": {"min_years": 5}})
    with pytest.raises(hc.HarnessConfigError, match="verify"):
        hc.parse({"pipeline": {"verify": "off"}})
    assert hc.parse({"model": {"provider": "none", "name": ""}}).model.provider == "none"


def test_config_file_maps_to_settings(tmp_path, settings, monkeypatch):
    p = tmp_path / "harness.toml"
    p.write_text(hc.TEMPLATE.format(provider="openai-compatible", base_url="http://127.0.0.1:1234", name="my-model")
                 + 'my_token = "x"\n', encoding="utf-8")
    with pytest.raises(hc.HarnessConfigError):       # unknown key is an error, not silently ignored
        hc.load(p)
    p.write_text(hc.TEMPLATE.format(provider="openai-compatible", base_url="http://127.0.0.1:1234", name="my-model")
                 .replace('noaa_cdo_token = "NOAA_CDO_TOKEN"', 'noaa_cdo_token = "MY_NOAA"'), encoding="utf-8")
    monkeypatch.setenv("MY_NOAA", "value-from-env")
    cfg, used = hc.load(p)
    s = hc.to_settings(cfg, settings)
    assert used == p and s.llm_provider == "openai" and s.llm_model == "my-model"
    assert s.noaa_cdo_token.get_secret_value() == "value-from-env"
    with pytest.raises(hc.HarnessConfigError, match="not found"):
        hc.load(tmp_path / "missing.toml")


def test_get_harness_never_returns_secrets(client):
    r = client.get("/api/harness")
    assert r.status_code == 200
    body = r.json()
    txt = json.dumps(body)
    for secret in ("fake-edl-token", "fake-cdo-token", "secret"):    # values set in the conftest settings
        assert secret not in txt
    assert body["config"]["data"]["credentials"]["earthdata_token"] == {"env": "EARTHDATA_TOKEN", "set": True}
    assert [s["id"] for s in body["stages"]][:4] == ["plan", "data", "engine", "gate"]
    assert all(s["model"] == "none" for s in body["stages"] if s["id"] in ("data", "engine", "gate", "report"))


@pytest.mark.parametrize("reply,verdict", [(FAITHFUL, "pass"), (INVENTED, "fail")])
def test_probe_gate(settings, fake, reply, verdict):
    fake.llm_reply = reply

    async def run():
        llm = LocalLLM(settings, transport=transport(fake))
        try:
            return await probe(llm)
        finally:
            await llm.aclose()
    r = asyncio.run(run())
    assert r["verdict"] == verdict and r["available"] and r["latency_s"] >= 0
    if verdict == "fail":
        assert "0.9" in str(r["verify"]["unsupported_numbers"])


def test_probe_endpoint(client):
    client.fake.llm_reply = FAITHFUL
    r = client.post("/api/harness/probe", json={"timeout_s": 30})
    assert r.status_code == 200 and r.json()["verdict"] == "pass"
    assert client.post("/api/harness/probe", json={"tier": "deep"}).status_code == 422


def test_cli_ask_json_on_stubbed_pipeline(monkeypatch, capsys, tmp_path):
    rep = {"question": "q", "headline": "In India, temperature rose.",
           "sections": [{"id": "answer", "text": "Yes.", "text_source": "template"},
                        {"id": "is_it_real", "data": {"verdict": "VERIFIED", "court": {"stamp": "SIGNIFICANT"},
                                                      "limit": "Statistical evidence only."}}],
           "provenance": {"dataset_short_name": "NCEP", "doi": "10.1/x", "series_id": "s1"}, "limits": ["L1"]}
    seen = {}

    async def fake_run(settings, question, alpha, progress=None):
        seen.update(question=question, alpha=alpha)
        return rep
    monkeypatch.setattr(cli, "run_report", fake_run)
    monkeypatch.setattr(hc, "apply_pipeline", lambda cfg: None)
    p = tmp_path / "h.toml"
    p.write_text('[pipeline]\nalpha = 0.01\n', encoding="utf-8")
    assert cli.main(["--config", str(p), "ask", "temperature in India", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert seen == {"question": "temperature in India", "alpha": 0.01}
    assert out["verdict"] == {"active_trend_label": "VERIFIED", "court_stamp": "SIGNIFICANT",
                              "limit": "Statistical evidence only."}
    assert out["numbers_from"]["doi"] == "10.1/x" and out["limits"] == ["L1"]


def test_apply_pipeline_sets_knobs():
    from backend.active import engine
    from backend.report import builder
    old_ids, old_min = list(builder.REWRITE_IDS), engine.MIN_YEARS
    try:
        hc.apply_pipeline(hc.parse({"pipeline": {"min_years": 20, "rewrite": False}}))
        assert engine.MIN_YEARS == 20 and builder.REWRITE_IDS == []
    finally:
        builder.REWRITE_IDS[:] = old_ids
        engine.MIN_YEARS = old_min
