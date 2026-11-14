"""Typed errors. The API layer maps them to HTTP status codes in one place."""
from __future__ import annotations


class TrendDetectiveError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, message: str, *, detail: dict | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail or {}


class InvalidRequest(TrendDetectiveError):
    status_code = 422
    code = "invalid_request"


class NotFound(TrendDetectiveError):
    status_code = 404
    code = "not_found"


class CredentialsMissing(TrendDetectiveError):
    status_code = 503
    code = "credentials_missing"


class UpstreamError(TrendDetectiveError):
    status_code = 502
    code = "upstream_error"


class UpstreamUnavailable(UpstreamError):
    """Source is in a known outage or not serving this variable; router should fall back."""
    code = "upstream_unavailable"


class InsufficientData(TrendDetectiveError):
    status_code = 422
    code = "insufficient_data"


class OffTopic(TrendDetectiveError):
    status_code = 422
    code = "off_topic"
