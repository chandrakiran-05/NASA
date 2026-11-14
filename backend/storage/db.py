"""SQLite job table and series index. Small, synchronous, thread-safe (WAL)."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id       TEXT PRIMARY KEY,
    kind         TEXT NOT NULL,
    status       TEXT NOT NULL,          -- queued | fetching | processing | done | error
    progress     REAL NOT NULL DEFAULT 0,
    message      TEXT,
    request_json TEXT,
    result_json  TEXT,
    error_json   TEXT,
    source_status TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS series (
    series_id    TEXT PRIMARY KEY,
    request_hash TEXT,
    variable_id  TEXT,
    label        TEXT,
    region_json  TEXT,
    units        TEXT,
    start_month  TEXT,
    end_month    TEXT,
    source_api   TEXT,
    provenance_json TEXT,
    completeness_json TEXT,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_series_request ON series(request_hash);
CREATE TABLE IF NOT EXISTS results (
    result_id    TEXT PRIMARY KEY,
    series_id    TEXT,
    kind         TEXT,
    params_json  TEXT,
    result_json  TEXT,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_results_series ON results(series_id, kind);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    # ---------------- jobs ----------------
    def create_job(self, job_id: str, kind: str, request: dict) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO jobs(job_id, kind, status, progress, request_json, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (job_id, kind, "queued", 0.0, json.dumps(request, default=str), _now(), _now()),
            )

    def update_job(self, job_id: str, **fields) -> None:
        cols, vals = [], []
        for k, v in fields.items():
            if k in ("result", "error", "source_status"):
                k = {"result": "result_json", "error": "error_json", "source_status": "source_status"}[k]
                v = json.dumps(v, default=str) if v is not None else None
            cols.append(f"{k}=?")
            vals.append(v)
        cols.append("updated_at=?")
        vals.append(_now())
        with self._lock:
            self._conn.execute(f"UPDATE jobs SET {', '.join(cols)} WHERE job_id=?", (*vals, job_id))

    def get_job(self, job_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        for k in ("request_json", "result_json", "error_json", "source_status"):
            if d.get(k):
                d[k.replace("_json", "")] = json.loads(d.pop(k))
            else:
                d[k.replace("_json", "")] = d.pop(k)
        return d

    def mark_stale_jobs(self) -> int:
        """Jobs left running when the server stopped are marked as errors on startup."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE jobs SET status='error', error_json=?, updated_at=? "
                "WHERE status IN ('queued','fetching','processing')",
                (json.dumps({"code": "interrupted", "message": "Server restarted while job was running"}), _now()),
            )
            return cur.rowcount

    # ---------------- series ----------------
    def upsert_series(self, rec: dict) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO series(series_id, request_hash, variable_id, label, region_json, units, "
                "start_month, end_month, source_api, provenance_json, completeness_json, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (rec["series_id"], rec.get("request_hash"), rec.get("variable_id"), rec.get("label"),
                 json.dumps(rec.get("region")), rec.get("units"), rec.get("start"), rec.get("end"),
                 rec.get("source_api"), json.dumps(rec.get("provenance"), default=str),
                 json.dumps(rec.get("completeness")), _now()),
            )

    def get_series(self, series_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM series WHERE series_id=?", (series_id,)).fetchone()
        return self._series_row(row)

    def find_series_by_request(self, request_hash: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM series WHERE request_hash=? ORDER BY created_at DESC LIMIT 1", (request_hash,)
            ).fetchone()
        return self._series_row(row)

    def list_series(self, limit: int = 100) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM series ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._series_row(r) for r in rows]

    @staticmethod
    def _series_row(row) -> dict | None:
        if not row:
            return None
        d = dict(row)
        for k in ("region_json", "provenance_json", "completeness_json"):
            d[k.replace("_json", "")] = json.loads(d.pop(k)) if d.get(k) else None
        return d

    # ---------------- results cache ----------------
    def put_result(self, result_id: str, series_id: str, kind: str, params: dict, result: dict) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO results(result_id, series_id, kind, params_json, result_json, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (result_id, series_id, kind, json.dumps(params, sort_keys=True, default=str),
                 json.dumps(result, default=str), _now()),
            )

    def delete_results(self, series_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM results WHERE series_id=?", (series_id,))

    def get_result(self, result_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT result_json FROM results WHERE result_id=?", (result_id,)).fetchone()
        return json.loads(row["result_json"]) if row else None
