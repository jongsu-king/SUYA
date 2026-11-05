"""SQLite 저장소. 측정값, 격자, Argo 프로파일, 수집 기록을 보관합니다."""

from __future__ import annotations

import gzip
import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Iterator

from .gridutil import Grid, grid_stats

SCHEMA = """
CREATE TABLE IF NOT EXISTS measurements (
    source TEXT NOT NULL,
    dataset TEXT NOT NULL,
    variable TEXT NOT NULL,
    kind TEXT NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    level TEXT NOT NULL DEFAULT 'surface',
    depth_m REAL,
    pressure_hpa REAL,
    obs_time TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT NOT NULL,
    location_id TEXT,
    quality TEXT,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (source, dataset, variable, lat, lon, level, obs_time)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_measure_location ON measurements (location_id, variable, obs_time);
CREATE INDEX IF NOT EXISTS idx_measure_var_time ON measurements (variable, obs_time);
CREATE INDEX IF NOT EXISTS idx_measure_source_time ON measurements (source, obs_time);

CREATE TABLE IF NOT EXISTS grids (
    layer TEXT NOT NULL,
    valid_time TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    unit TEXT NOT NULL,
    stats_json TEXT NOT NULL,
    payload BLOB NOT NULL,
    PRIMARY KEY (layer, valid_time)
);

CREATE TABLE IF NOT EXISTS argo_profiles (
    platform TEXT NOT NULL,
    cycle INTEGER NOT NULL,
    obs_time TEXT NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    data_mode TEXT,
    position_qc TEXT,
    surface_temp REAL,
    surface_salt REAL,
    max_depth_m REAL,
    n_levels INTEGER,
    levels_json TEXT,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (platform, cycle)
);
CREATE INDEX IF NOT EXISTS idx_argo_time ON argo_profiles (obs_time);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    status TEXT NOT NULL,
    rows INTEGER NOT NULL DEFAULT 0,
    data_time TEXT,
    message TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_source ON runs (source, id);

CREATE TABLE IF NOT EXISTS source_state (
    source TEXT PRIMARY KEY,
    last_attempt TEXT,
    last_success TEXT,
    last_status TEXT,
    last_message TEXT,
    last_rows INTEGER,
    data_time TEXT,
    next_run TEXT,
    consecutive_errors INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

MEASUREMENT_COLUMNS = (
    "source", "dataset", "variable", "kind", "lat", "lon", "level", "depth_m", "pressure_hpa",
    "obs_time", "value", "unit", "location_id", "quality", "fetched_at",
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime | None = None) -> str:
    return (moment or utcnow()).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class Measurement:
    source: str
    dataset: str
    variable: str
    kind: str
    lat: float
    lon: float
    obs_time: str
    value: float
    unit: str
    level: str = "surface"
    depth_m: float | None = None
    pressure_hpa: float | None = None
    location_id: str | None = None
    quality: str | None = None


class Store:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def upsert_measurements(self, rows: Iterable[Measurement]) -> int:
        now = iso()
        params = [
            (
                r.source, r.dataset, r.variable, r.kind, r.lat, r.lon, r.level, r.depth_m, r.pressure_hpa,
                r.obs_time, r.value, r.unit, r.location_id, r.quality, now,
            )
            for r in rows
        ]
        if not params:
            return 0
        placeholders = ",".join("?" * len(MEASUREMENT_COLUMNS))
        sql = (
            f"INSERT INTO measurements ({','.join(MEASUREMENT_COLUMNS)}) VALUES ({placeholders}) "
            "ON CONFLICT (source, dataset, variable, lat, lon, level, obs_time) DO UPDATE SET "
            "value=excluded.value, unit=excluded.unit, kind=excluded.kind, quality=excluded.quality, "
            "location_id=COALESCE(excluded.location_id, location_id), fetched_at=excluded.fetched_at"
        )
        with self._lock:
            self._conn.executemany(sql, params)
            self._conn.commit()
        return len(params)

    def latest_for_location(self, location_id: str) -> dict[str, dict]:
        """지점별 (소스, 데이터셋, 변수, 층) 조합의 현재 시각 이전 최신값."""
        sql = """
        SELECT m.* FROM measurements m
        JOIN (
            SELECT source, dataset, variable, level, MAX(obs_time) AS t FROM measurements
            WHERE location_id = ? AND obs_time <= ? GROUP BY source, dataset, variable, level
        ) x ON m.source = x.source AND m.dataset = x.dataset AND m.variable = x.variable
           AND m.level = x.level AND m.obs_time = x.t
        WHERE m.location_id = ?
        """
        with self._lock:
            rows = self._conn.execute(sql, (location_id, iso(), location_id)).fetchall()
        return {f"{r['source']}|{r['dataset']}|{r['variable']}|{r['level']}": dict(r) for r in rows}

    def query_measurements(
        self,
        *,
        source: str | None = None,
        dataset: str | None = None,
        variable: str | None = None,
        location_id: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int | None = None,
        newest_first: bool = False,
    ) -> list[dict]:
        return list(
            self.iter_measurements(
                source=source, dataset=dataset, variable=variable, location_id=location_id,
                since=since, until=until, limit=limit, newest_first=newest_first,
            )
        )

    def iter_measurements(
        self,
        *,
        source: str | None = None,
        dataset: str | None = None,
        variable: str | None = None,
        location_id: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int | None = None,
        newest_first: bool = False,
    ) -> Iterator[dict]:
        clauses, params = [], []
        for column, value, op in (
            ("source", source, "="), ("dataset", dataset, "="), ("variable", variable, "="),
            ("location_id", location_id, "="), ("obs_time", since, ">="), ("obs_time", until, "<="),
        ):
            if value is not None:
                clauses.append(f"{column} {op} ?")
                params.append(value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        order = "DESC" if newest_first else "ASC"
        tail = f" LIMIT {int(limit)}" if limit else ""
        sql = f"SELECT * FROM measurements {where} ORDER BY obs_time {order}{tail}"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        for row in rows:
            yield dict(row)

    def count_measurements(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM measurements").fetchone()[0]

    def location_stats(
        self, since: str, until: str, sources: tuple[str, ...], variables: tuple[str, ...]
    ) -> list[dict]:
        """지점·자료·항목별 기간 통계. 표층과 2 m의 실측·분석·모델 값만 세고 앞날 예보는 뺍니다."""
        source_marks = ",".join("?" * len(sources))
        variable_marks = ",".join("?" * len(variables))
        sql = f"""
        SELECT location_id, source, variable, unit, COUNT(*) AS n, AVG(value) AS mean, MIN(value) AS low,
               MAX(value) AS high, AVG(value * value) AS mean_square, MIN(obs_time) AS first_time,
               MAX(obs_time) AS last_time
        FROM measurements
        WHERE location_id IS NOT NULL AND obs_time >= ? AND obs_time <= ? AND kind != 'forecast'
          AND source IN ({source_marks}) AND variable IN ({variable_marks})
          AND level IN ('surface', 'depth:0', '2m')
        GROUP BY location_id, source, variable, unit
        ORDER BY location_id, variable, source
        """
        with self._lock:
            rows = self._conn.execute(sql, (since, until, *sources, *variables)).fetchall()
        return [dict(row) for row in rows]

    def prune(self, forecast_days: int = 30, grid_keep: int = 60) -> None:
        """오래된 예보와 격자 스냅샷을 지웁니다. 관측·위성·분석값은 계속 보관합니다."""
        cutoff = iso(utcnow() - timedelta(days=forecast_days))
        with self._lock:
            self._conn.execute("DELETE FROM measurements WHERE kind = 'forecast' AND obs_time < ?", (cutoff,))
            self._conn.execute(
                """DELETE FROM grids WHERE rowid IN (
                     SELECT rowid FROM (
                       SELECT rowid, ROW_NUMBER() OVER (PARTITION BY layer ORDER BY valid_time DESC) AS n FROM grids
                     ) WHERE n > ?
                   )""",
                (grid_keep,),
            )
            self._conn.execute("DELETE FROM runs WHERE id NOT IN (SELECT id FROM runs ORDER BY id DESC LIMIT 5000)")
            self._conn.commit()

    def save_grid(self, grid: Grid) -> dict:
        stats = grid_stats(grid)
        payload = gzip.compress(json.dumps(grid.as_dict(), separators=(",", ":")).encode(), compresslevel=6)
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO grids (layer, valid_time, fetched_at, unit, stats_json, payload) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (grid.layer, grid.valid_time, iso(), grid.unit, json.dumps(stats), payload),
            )
            self._conn.commit()
        return stats

    def latest_grid_info(self) -> dict[str, dict]:
        sql = """
        SELECT g.layer, g.valid_time, g.fetched_at, g.unit, g.stats_json FROM grids g
        JOIN (SELECT layer, MAX(valid_time) AS t FROM grids GROUP BY layer) x
          ON g.layer = x.layer AND g.valid_time = x.t
        """
        with self._lock:
            rows = self._conn.execute(sql).fetchall()
        return {
            r["layer"]: {
                "layer": r["layer"],
                "valid_time": r["valid_time"],
                "fetched_at": r["fetched_at"],
                "unit": r["unit"],
                "stats": json.loads(r["stats_json"]),
            }
            for r in rows
        }

    def load_grid(self, layer: str, valid_time: str | None = None) -> Grid | None:
        if valid_time:
            sql, params = "SELECT payload FROM grids WHERE layer = ? AND valid_time = ?", (layer, valid_time)
        else:
            sql, params = "SELECT payload FROM grids WHERE layer = ? ORDER BY valid_time DESC LIMIT 1", (layer,)
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
        if not row:
            return None
        return Grid.from_dict(json.loads(gzip.decompress(row["payload"])))

    def load_grid_gzip(self, layer: str) -> bytes | None:
        """이미 압축된 격자 JSON을 그대로 돌려줍니다. 응답을 다시 압축하지 않기 위함입니다."""
        with self._lock:
            row = self._conn.execute(
                "SELECT payload FROM grids WHERE layer = ? ORDER BY valid_time DESC LIMIT 1", (layer,)
            ).fetchone()
        return row["payload"] if row else None

    def grid_summaries(self, start: str, end: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT layer, valid_time, unit, stats_json FROM grids WHERE valid_time >= ? AND valid_time < ? "
                "ORDER BY valid_time, layer",
                (start, end),
            ).fetchall()
        return [dict(r) for r in rows]

    def months_with_data(self) -> list[str]:
        """자료가 있는 달(YYYY-MM)."""
        sql = """
        SELECT DISTINCT substr(obs_time, 1, 7) FROM measurements
        UNION SELECT DISTINCT substr(valid_time, 1, 7) FROM grids
        UNION SELECT DISTINCT substr(obs_time, 1, 7) FROM argo_profiles
        ORDER BY 1
        """
        with self._lock:
            return [r[0] for r in self._conn.execute(sql).fetchall()]

    def data_stamp(self) -> str | None:
        """마지막으로 자료가 들어온 시각. 엑셀을 다시 쓸지 판단합니다."""
        sql = """
        SELECT MAX(t) FROM (
            SELECT MAX(fetched_at) AS t FROM measurements
            UNION ALL SELECT MAX(fetched_at) FROM grids
            UNION ALL SELECT MAX(fetched_at) FROM argo_profiles
        )
        """
        with self._lock:
            return self._conn.execute(sql).fetchone()[0]

    def grid_history(self, layer: str, limit: int = 60) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT valid_time, stats_json FROM grids WHERE layer = ? ORDER BY valid_time DESC LIMIT ?",
                (layer, limit),
            ).fetchall()
        return [{"valid_time": r["valid_time"], "stats": json.loads(r["stats_json"])} for r in reversed(rows)]

    def upsert_argo_listing(self, rows: Iterable[dict]) -> int:
        now = iso()
        count = 0
        with self._lock:
            for r in rows:
                self._conn.execute(
                    """INSERT INTO argo_profiles
                       (platform, cycle, obs_time, lat, lon, data_mode, position_qc, surface_temp, surface_salt, fetched_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT (platform, cycle) DO UPDATE SET
                         obs_time = excluded.obs_time, lat = excluded.lat, lon = excluded.lon,
                         data_mode = excluded.data_mode, position_qc = excluded.position_qc,
                         surface_temp = COALESCE(argo_profiles.surface_temp, excluded.surface_temp),
                         surface_salt = COALESCE(argo_profiles.surface_salt, excluded.surface_salt),
                         levels_json = CASE WHEN argo_profiles.data_mode IS NOT excluded.data_mode
                                            THEN NULL ELSE argo_profiles.levels_json END""",
                    (
                        r["platform"], r["cycle"], r["time"], r["lat"], r["lon"], r.get("data_mode"),
                        r.get("position_qc"), r.get("surface_temp"), r.get("surface_salt"), now,
                    ),
                )
                count += 1
            self._conn.commit()
        return count

    def save_argo_levels(self, platform: str, cycle: int, levels: list[dict]) -> None:
        temps = [lv["temp"] for lv in levels if lv.get("temp") is not None]
        salts = [lv["salt"] for lv in levels if lv.get("salt") is not None]
        depths = [lv["depth_m"] for lv in levels if lv.get("depth_m") is not None]
        with self._lock:
            self._conn.execute(
                """UPDATE argo_profiles SET levels_json = ?, n_levels = ?, max_depth_m = ?,
                   surface_temp = ?, surface_salt = ?, fetched_at = ? WHERE platform = ? AND cycle = ?""",
                (
                    json.dumps(levels, separators=(",", ":")), len(levels), max(depths) if depths else None,
                    temps[0] if temps else None, salts[0] if salts else None, iso(), platform, cycle,
                ),
            )
            self._conn.commit()

    def argo_missing_levels(self, limit: int) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT platform, cycle, lat, lon FROM argo_profiles WHERE levels_json IS NULL "
                "ORDER BY obs_time DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def argo_count_missing(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM argo_profiles WHERE levels_json IS NULL").fetchone()[0]

    def argo_list(self, since: str | None = None, lat_max: float | None = None) -> list[dict]:
        clauses, params = [], []
        if since:
            clauses.append("obs_time >= ?")
            params.append(since)
        if lat_max is not None:
            clauses.append("lat <= ?")
            params.append(lat_max)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            "SELECT platform, cycle, obs_time, lat, lon, data_mode, position_qc, surface_temp, surface_salt, "
            f"max_depth_m, n_levels FROM argo_profiles {where} ORDER BY obs_time DESC"
        )
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def argo_profile(self, platform: str, cycle: int) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM argo_profiles WHERE platform = ? AND cycle = ?", (platform, cycle)
            ).fetchone()
        if not row:
            return None
        data = dict(row)
        data["levels"] = json.loads(data.pop("levels_json")) if data.get("levels_json") else None
        return data

    def argo_with_levels(self, since: str | None = None, lat_max: float | None = None) -> Iterator[dict]:
        clauses, params = ["levels_json IS NOT NULL"], []
        if since:
            clauses.append("obs_time >= ?")
            params.append(since)
        if lat_max is not None:
            clauses.append("lat <= ?")
            params.append(lat_max)
        sql = f"SELECT * FROM argo_profiles WHERE {' AND '.join(clauses)} ORDER BY obs_time DESC"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        for row in rows:
            data = dict(row)
            data["levels"] = json.loads(data.pop("levels_json"))
            yield data

    def record_run(
        self, source: str, started_at: str, status: str, rows: int, data_time: str | None, message: str | None,
        next_run: str | None,
    ) -> None:
        now = iso()
        success = status in ("ok", "unchanged")
        with self._lock:
            self._conn.execute(
                "INSERT INTO runs (source, started_at, finished_at, status, rows, data_time, message) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (source, started_at, now, status, rows, data_time, message),
            )
            self._conn.execute(
                """INSERT INTO source_state
                   (source, last_attempt, last_success, last_status, last_message, last_rows, data_time, next_run,
                    consecutive_errors)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (source) DO UPDATE SET
                     last_attempt = excluded.last_attempt,
                     last_success = COALESCE(excluded.last_success, source_state.last_success),
                     last_status = excluded.last_status,
                     last_message = excluded.last_message,
                     last_rows = excluded.last_rows,
                     data_time = COALESCE(excluded.data_time, source_state.data_time),
                     next_run = excluded.next_run,
                     consecutive_errors = CASE WHEN excluded.consecutive_errors = 0 THEN 0
                                               ELSE source_state.consecutive_errors + 1 END""",
                (
                    source, now, now if success else None, status, message, rows, data_time, next_run,
                    0 if status in ("ok", "unchanged", "disabled") else 1,
                ),
            )
            self._conn.commit()

    def set_next_run(self, source: str, next_run: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO source_state (source, next_run) VALUES (?, ?) "
                "ON CONFLICT (source) DO UPDATE SET next_run = excluded.next_run",
                (source, next_run),
            )
            self._conn.commit()

    def source_states(self) -> dict[str, dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM source_state").fetchall()
        return {r["source"]: dict(r) for r in rows}

    def recent_runs(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def kv_get(self, key: str) -> str | None:
        with self._lock:
            row = self._conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def kv_set(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            self._conn.commit()
