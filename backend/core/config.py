"""Runtime settings, loaded from environment variables or a .env file.

Secrets (Earthdata token, NOAA token) live only in the server environment and are
never returned by any endpoint.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", env_file_encoding="utf-8", extra="ignore")

    # ---- service ----
    app_name: str = "Earth System Trend Detective API"
    environment: str = "dev"
    data_dir: Path = ROOT / "data"
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]
    max_concurrent_jobs: int = 4

    # ---- credentials (server-side only) ----
    earthdata_token: SecretStr | None = None          # EDL bearer token (Giovanni, Harmony, AppEEARS optional)
    earthdata_username: str | None = None             # used for AppEEARS /login and .netrc fallback
    earthdata_password: SecretStr | None = None
    noaa_cdo_token: SecretStr | None = None           # CDO v2 fallback only

    # ---- upstream base URLs (from 02-platforms-and-apis.md) ----
    giovanni_base: str = "https://api.giovanni.earthdata.nasa.gov"
    appeears_base: str = "https://appeears.earthdatacloud.nasa.gov/api"
    cmr_base: str = "https://cmr.earthdata.nasa.gov/search"
    ncei_ads_base: str = "https://www.ncei.noaa.gov/access/services/data/v1"
    cdo_base: str = "https://www.ncei.noaa.gov/cdo-web/api/v2"
    opendap_base: str = "https://opendap.earthdata.nasa.gov"

    # ---- HTTP behaviour ----
    http_timeout_s: float = 120.0
    http_max_retries: int = 5
    http_backoff_base_s: float = 1.5
    http_backoff_cap_s: float = 60.0
    raw_cache_ttl_hours: float = 24 * 30           # earth data for past months does not change
    cdo_rate_per_s: float = 5.0                    # documented CDO limit
    appeears_poll_s: float = 20.0                  # NASA tutorial polls every 20 s
    giovanni_quota_stop: float = 0.95              # NASA tutorial warns at 95 % of the monthly quota
    appeears_timeout_min: float = 90.0

    # ---- time-series engine defaults (architecture §4) ----
    min_valid_fraction_per_month: float = 0.70
    min_months_for_test: int = 120
    max_months_warn: int = 0                         # 0 = no cap

    # ---- analysis defaults ----
    alpha: float = 0.05

    # ---- offline AI ----
    llm_provider: str = Field("ollama", description="ollama | openai | none")
    llm_base_url: str = "http://127.0.0.1:11434"
    llm_model: str = "qwen3.5:4b"
    llm_timeout_s: float = 60.0
    llm_temperature: float = 0.1
    llm_max_tokens: int = 700
    ai_guard_threshold: float = 1.0                  # minimum earth-topic score to accept a query

    @field_validator("earthdata_token", "earthdata_password", "noaa_cdo_token", "earthdata_username", mode="before")
    @classmethod
    def _blank_is_none(cls, v):
        """`EARTHDATA_TOKEN=` left blank in .env means 'not configured', not an empty token."""
        if v is None:
            return None
        if isinstance(v, SecretStr):
            v = v.get_secret_value()
        return None if str(v).strip() == "" else v

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def series_dir(self) -> Path:
        return self.data_dir / "series"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "trend_detective.sqlite3"

    def ensure_dirs(self) -> None:
        for p in (self.data_dir, self.cache_dir, self.cache_dir / "raw", self.series_dir):
            p.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s
