"""harness.toml: which local model the pipeline uses and how strict the pipeline is.

The file never holds secrets: data credentials are named by environment variable only, and a value that
looks like a token instead of a variable name is rejected. Everything maps onto the existing `Settings`.
"""
from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from ..core.config import ROOT, Settings

DEFAULT_PATH = ROOT / "harness.toml"
PROVIDERS = ("ollama", "openai-compatible", "airllm", "none")
REWRITABLE = ("answer", "how_much", "is_it_real", "when", "seasons", "map")   # = report.builder.REWRITE_IDS default
CREDENTIALS = {                                   # Settings field -> default environment variable
    "earthdata_token": "EARTHDATA_TOKEN", "earthdata_username": "EARTHDATA_USERNAME",
    "earthdata_password": "EARTHDATA_PASSWORD", "noaa_cdo_token": "NOAA_CDO_TOKEN",
    "springer_api_key": "SPRINGER_API_KEY", "semantic_scholar_api_key": "SEMANTIC_SCHOLAR_API_KEY",
    "ads_api_token": "ADS_API_TOKEN",
}
ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]{1,63}$")


class HarnessConfigError(ValueError):
    pass


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelCfg(_M):
    provider: Literal["ollama", "openai-compatible", "airllm", "none"] = "ollama"
    base_url: str = "http://127.0.0.1:11434"
    name: str = "qwen3.5:4b"
    timeout_s: float = Field(60.0, gt=0, le=3600)
    max_tokens: int = Field(700, ge=64, le=8192)
    temperature: float = Field(0.1, ge=0, le=2)

    @model_validator(mode="after")
    def _need_model(self):
        if self.provider != "none" and not self.name.strip():
            raise ValueError(f"model.name is required when model.provider = '{self.provider}'")
        if self.provider in ("ollama", "openai-compatible") and urlsplit(self.base_url).scheme not in ("http", "https"):
            raise ValueError("model.base_url must be an http(s) URL, e.g. http://127.0.0.1:11434")
        return self


class DeepCfg(_M):
    provider: Literal["none", "airllm"] = "none"
    model: str = ""                               # empty: core.hardware.recommend() picks for this machine
    max_new_tokens: int = Field(64, ge=1, le=512)
    timeout_s: float = Field(1800.0, gt=0, le=6 * 3600)


class PipelineCfg(_M):
    alpha: float = Field(0.05, gt=0, le=0.1)
    # the BEAST + PELT gate and active-trend checks were calibrated at 15 years: stricter is allowed, looser is not
    min_years: int = Field(15, ge=15, le=60)
    verify: Literal["strict"] = "strict"          # verify_text cannot be loosened; the key exists to say so
    rewrite: bool = True
    rewrite_sections: list[str] = Field(default_factory=lambda: list(REWRITABLE))

    @field_validator("rewrite_sections")
    @classmethod
    def _known_sections(cls, v):
        bad = [s for s in v if s not in REWRITABLE]
        if bad:
            raise ValueError(f"unknown section(s) {bad}; allowed: {list(REWRITABLE)}")
        return v


class DataCfg(_M):
    credentials: dict[str, str] = Field(default_factory=lambda: dict(CREDENTIALS))

    @field_validator("credentials")
    @classmethod
    def _env_names_only(cls, v):
        for k, name in v.items():
            if k not in CREDENTIALS:
                raise ValueError(f"unknown credential '{k}'; known: {list(CREDENTIALS)}")
            if not ENV_NAME.match(name):
                raise ValueError(f"data.credentials.{k} must be an environment variable NAME such as "
                                 f"{CREDENTIALS[k]}, never the secret itself")
        return {**CREDENTIALS, **v}


class HarnessConfig(_M):
    model: ModelCfg = Field(default_factory=ModelCfg)
    deep: DeepCfg = Field(default_factory=DeepCfg)
    pipeline: PipelineCfg = Field(default_factory=PipelineCfg)
    data: DataCfg = Field(default_factory=DataCfg)


def parse(raw: dict) -> HarnessConfig:
    try:
        return HarnessConfig.model_validate(raw)
    except ValidationError as exc:
        lines = [f"  {'.'.join(map(str, e['loc'])) or '(root)'}: {e['msg']}" for e in exc.errors()]
        raise HarnessConfigError("harness config is invalid:\n" + "\n".join(lines)) from None


def load(path: str | Path | None = None) -> tuple[HarnessConfig, Path | None]:
    """(config, file used). No file at the default path means defaults; an explicit missing path is an error."""
    explicit = path or os.environ.get("TREND_HARNESS_CONFIG")
    p = Path(explicit or DEFAULT_PATH)
    if not p.exists():
        if explicit:
            raise HarnessConfigError(f"config file not found: {p} (run: trend-harness init)")
        return HarnessConfig(), None
    try:
        raw = tomllib.loads(p.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise HarnessConfigError(f"{p} is not valid TOML: {exc}") from None
    return parse(raw), p


def from_settings(s: Settings) -> HarnessConfig:
    """The config a server started from .env is effectively running (no harness.toml applied)."""
    prov = {"openai": "openai-compatible"}.get(s.llm_provider.lower(), s.llm_provider.lower())
    prov = prov if prov in PROVIDERS else "none"
    return HarnessConfig(
        model=ModelCfg(provider=prov, base_url=s.llm_base_url, name=s.llm_model, timeout_s=s.llm_timeout_s,
                       max_tokens=s.llm_max_tokens, temperature=s.llm_temperature),
        deep=DeepCfg(provider="airllm" if s.deep_llm_provider.lower() == "airllm" else "none",
                     model=s.deep_llm_model, max_new_tokens=min(s.deep_llm_max_new_tokens, 512),
                     timeout_s=s.deep_llm_timeout_s),
        pipeline=PipelineCfg(alpha=s.alpha))


def to_settings(cfg: HarnessConfig, base: Settings | None = None) -> Settings:
    """Settings for the existing clients and pipeline. Credentials come from the named env variables."""
    base = base or Settings()
    m, d = cfg.model, cfg.deep
    upd = {"llm_provider": {"openai-compatible": "openai", "airllm": "none"}.get(m.provider, m.provider),
           "llm_base_url": m.base_url, "llm_model": m.name, "llm_timeout_s": m.timeout_s,
           "llm_max_tokens": m.max_tokens, "llm_temperature": m.temperature, "alpha": cfg.pipeline.alpha,
           "deep_llm_provider": d.provider, "deep_llm_model": d.model,
           "deep_llm_max_new_tokens": d.max_new_tokens, "deep_llm_timeout_s": d.timeout_s}
    if m.provider == "airllm":                    # AirLLM is far too slow for live wording: it becomes the deep tier
        upd.update(deep_llm_provider="airllm", deep_llm_model=m.name)
    for field, env in cfg.data.credentials.items():
        if env != CREDENTIALS[field] and os.environ.get(env):     # default names are already read by Settings
            upd[field] = os.environ[env]
    return Settings.model_validate({**base.model_dump(), **upd})


def apply_pipeline(cfg: HarnessConfig) -> None:
    """Process-wide pipeline knobs (used by `serve` and `ask`, never by the plain backend)."""
    from ..active import engine
    from ..report import builder
    engine.MIN_YEARS = cfg.pipeline.min_years
    builder.REWRITE_IDS[:] = cfg.pipeline.rewrite_sections if cfg.pipeline.rewrite else []


def public_url(url: str) -> str:
    """Drop user:password@ from a URL before showing it."""
    p = urlsplit(url)
    return urlunsplit(p._replace(netloc=p.hostname + (f":{p.port}" if p.port else ""))) if p.hostname else url


def redacted(cfg: HarnessConfig, settings: Settings) -> dict:
    """Config for display: env variable names and whether they are set, never their values."""
    out = cfg.model_dump()
    out["model"]["base_url"] = public_url(cfg.model.base_url)
    out["data"] = {"credentials": {k: {"env": env, "set": bool(getattr(settings, k, None))}
                                   for k, env in cfg.data.credentials.items()}}
    return out


TEMPLATE = """\
# harness.toml - Earth System Trend Detective harness
# Plug in your own local model. The science engine (trend tests, Trend Court, BEAST + PELT gate) computes
# every number; the model only plans questions and rewrites wording, and every sentence it writes is
# number-checked (backend/ai/verify.py) before anyone sees it.

[model]
# ollama | openai-compatible (LM Studio, llama.cpp server, vLLM, Ollama /v1) | airllm | none
provider = "{provider}"
base_url = "{base_url}"
name = "{name}"
timeout_s = 60
max_tokens = 700
temperature = 0.1

[deep]
# Optional slow reviewer: AirLLM runs a 14B+ model layer by layer from disk (seconds per token).
# Advisory only: it never changes a verdict. Needs: pip install -r requirements-airllm.txt
provider = "none"          # none | airllm
model = ""                 # empty = pick for this machine (core/hardware.py)
max_new_tokens = 64

[pipeline]
alpha = 0.05               # significance level for every test (0 < alpha <= 0.1)
min_years = 15             # active-trend minimum record; the BEAST + PELT gate is calibrated at 15 (can only go up)
verify = "strict"          # every AI sentence must pass verify_text; cannot be loosened
rewrite = true             # false = template wording only (model used for planning only)
rewrite_sections = ["answer", "how_much", "is_it_real", "when", "seasons", "map"]

[data.credentials]
# Environment variable NAMES only. Put the values in your shell or .env, never in this file.
earthdata_token = "EARTHDATA_TOKEN"
earthdata_username = "EARTHDATA_USERNAME"
earthdata_password = "EARTHDATA_PASSWORD"
noaa_cdo_token = "NOAA_CDO_TOKEN"
"""
