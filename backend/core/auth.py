"""Credential access. Tokens are read from settings (server env) only."""
from __future__ import annotations

import netrc
from pathlib import Path

from .config import Settings
from .errors import CredentialsMissing


_TOKEN_CACHE: dict[str, str] = {}


def _token_via_earthaccess(s: Settings) -> str | None:
    """Same method as NASA's tutorials: earthaccess.login() then earthaccess.get_edl_token().
    Uses EARTHDATA_USERNAME/PASSWORD (or ~/.netrc). Cached for the life of the process."""
    if "edl" in _TOKEN_CACHE:
        return _TOKEN_CACHE["edl"]
    try:
        import os

        import earthaccess
        if s.earthdata_username and s.earthdata_password:
            os.environ.setdefault("EARTHDATA_USERNAME", s.earthdata_username)
            os.environ.setdefault("EARTHDATA_PASSWORD", s.earthdata_password.get_secret_value())
            earthaccess.login(strategy="environment")
        else:
            earthaccess.login(strategy="netrc")
        tok = earthaccess.get_edl_token()["access_token"]
    except Exception:  # noqa: BLE001
        return None
    _TOKEN_CACHE["edl"] = tok
    return tok


def edl_bearer_headers(s: Settings) -> dict[str, str]:
    if s.earthdata_token is not None:
        return {"Authorization": f"Bearer {s.earthdata_token.get_secret_value()}"}
    tok = _token_via_earthaccess(s)
    if tok:
        return {"Authorization": f"Bearer {tok}"}
    raise CredentialsMissing(
        "No Earthdata token: set EARTHDATA_TOKEN, or EARTHDATA_USERNAME/EARTHDATA_PASSWORD (or ~/.netrc) so the "
        "server can fetch one with earthaccess, exactly as NASA's Giovanni tutorials do."
    )


def edl_basic_auth(s: Settings) -> tuple[str, str]:
    """Username/password for AppEEARS /login. Falls back to ~/.netrc (machine urs.earthdata.nasa.gov)."""
    if s.earthdata_username and s.earthdata_password:
        return s.earthdata_username, s.earthdata_password.get_secret_value()
    try:
        rc = netrc.netrc(str(Path.home() / ".netrc"))
        entry = rc.authenticators("urs.earthdata.nasa.gov")
        if entry and entry[0] and entry[2]:
            return entry[0], entry[2]
    except (FileNotFoundError, netrc.NetrcParseError):
        pass
    raise CredentialsMissing(
        "Earthdata username/password not configured (EARTHDATA_USERNAME / EARTHDATA_PASSWORD or ~/.netrc)."
    )


def cdo_headers(s: Settings) -> dict[str, str]:
    if s.noaa_cdo_token is None:
        raise CredentialsMissing("NOAA_CDO_TOKEN is not set (free token from ncdc.noaa.gov/cdo-web/token).")
    return {"token": s.noaa_cdo_token.get_secret_value()}


def credential_status(s: Settings) -> dict[str, bool]:
    has_basic = True
    try:
        edl_basic_auth(s)
    except CredentialsMissing:
        has_basic = False
    return {
        "earthdata_token": s.earthdata_token is not None,
        "earthdata_login": has_basic,
        "noaa_cdo_token": s.noaa_cdo_token is not None,
    }
