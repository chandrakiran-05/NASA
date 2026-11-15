"""Student-facing wording that keeps three ideas apart (students otherwise read "NOT PROVEN" or
"missing months" as "the data are fake"):

1. the data are real measurements / model output from a named agency, never made up;
2. some months may be missing: they are left blank, never filled in (with counts);
3. the TEST result (SIGNIFICANT / NOT PROVEN / inconclusive) is about whether the trend is clear
   enough, not whether the data are real.
"""
from __future__ import annotations

_AGENCY = (
    ("giovanni", "NASA"), ("appeears", "NASA"), ("harmony", "NASA"), ("opendap", "NASA"), ("cmr", "NASA"),
    ("podaac", "NASA (PO.DAAC)"), ("nsidc", "NSIDC (NOAA/NASA)"), ("ncei", "NOAA NCEI"),
    ("erddap", "NOAA ERDDAP"), ("coops", "NOAA tide gauges"), ("usgs", "USGS"), ("nwis", "USGS"),
)
UPLOAD_SOURCES = ("user", "user_upload", "twin_upload", "upload")

TEST_NOTE = ("The test result (SIGNIFICANT or NOT PROVEN) is about whether the trend is clear enough, "
             "not about whether the data are real.")


def agency_of(source_api: str | None) -> str | None:
    """'NASA', 'NOAA NCEI', ... ; None for uploads or unknown sources."""
    s = (source_api or "").lower()
    for key, name in _AGENCY:
        if key in s:
            return name
    return None


def data_real_sentence(source_api: str | None, dataset: str | None = None) -> str:
    s = (source_api or "").lower()
    if s in UPLOAD_SOURCES or s.startswith("user"):
        return "These are the values from your uploaded file; the tool does not change them."
    agency = agency_of(source_api) or "the official data source"
    ds = f" ({dataset})" if dataset else ""
    return f"These are real measurements or model output from {agency}{ds}; nothing is made up."


def missing_sentence(n_months: int | None, n_valid: int | None) -> str:
    if not n_months:
        return ""
    miss = max(0, int(n_months) - int(n_valid or 0))
    if miss == 0:
        return f"All {n_months} months have a value."
    return (f"{miss} of {n_months} months have no value; they are left blank on the chart, never filled in "
            f"or guessed.")


def data_note(source_api: str | None, n_months: int | None = None, n_valid: int | None = None,
              dataset: str | None = None) -> str:
    """One line: data are real + missing-month count. (The test note is separate: TEST_NOTE.)"""
    return " ".join(p for p in (data_real_sentence(source_api, dataset), missing_sentence(n_months, n_valid)) if p)
