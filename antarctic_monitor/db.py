"""SQLite 저장소. 측정값, 격자, Argo 프로파일, 수집 기록을 보관합니다."""

from __future__ import annotations

import gzip
import json
import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Iterator

from . import composition, ranges, seawater
from .gridutil import SECTORS, Grid, grid_stats

log = logging.getLogger(__name__)

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

SALINITY = "sea_water_salinity"
TEMPERATURE = "sea_water_temperature"
ION_KEY = ("source", "dataset", "lat", "lon", "level", "obs_time")
ION_GRAM_COLUMNS = tuple(f"{component.key}_g_kg" for component in composition.MAJOR)
ION_MMOL_COLUMNS = tuple(f"{component.key}_mmol_kg" for component in composition.MAJOR)
ION_COLUMNS = (*ION_KEY, "kind", "depth_m", "location_id", "practical_salinity", "reference_salinity", *ION_GRAM_COLUMNS)
ION_CHECK = "salinity_check"
ION_DENSITY = "density_kg_m3"
ION_LITRE_COLUMNS = tuple(f"{component.key}_mmol_l" for component in composition.MAJOR)
ION_VOLUME_COLUMNS = ("temperature_c", ION_DENSITY, *ION_LITRE_COLUMNS)
ARGO_ION_COLUMNS = (
    "platform", "cycle", "obs_time", "lat", "lon", "data_mode", "pressure_dbar", "depth_m", "temperature_c",
    "practical_salinity", "reference_salinity", *ION_GRAM_COLUMNS, ION_CHECK,
)
GRID_SALINITY_UNIT = "PSU"
GRID_DEPTH_PREFIX = "hycom_salt_"
GRID_ALL = "all"
GRID_AREAS = (GRID_ALL, *(sector[0] for sector in SECTORS))
GRID_ION_COLUMNS = (
    "layer", "valid_time", "area", "depth_m", "valid_cells", "practical_salinity", "reference_salinity",
    *ION_GRAM_COLUMNS, *ION_MMOL_COLUMNS, ION_CHECK,
)
GRID_CELL_ION_COLUMNS = (
    "valid_time", "lat", "lon", "depth_m", "practical_salinity", "reference_salinity",
    *ION_GRAM_COLUMNS, *ION_MMOL_COLUMNS, ION_CHECK,
)
ION_METHOD_KEY = "ions:method"
ION_CHECK_KEY = "ions:check"
ION_OBJECTS = (
    "seawater_ions_insert", "seawater_ions_update", "seawater_ions_delete", "seawater_ions_mmol", "argo_level_ions",
    "grid_ions",
)

ION_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS seawater_ions (
    source TEXT NOT NULL,
    dataset TEXT NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    level TEXT NOT NULL DEFAULT 'surface',
    obs_time TEXT NOT NULL,
    kind TEXT NOT NULL,
    depth_m REAL,
    location_id TEXT,
    practical_salinity REAL NOT NULL,
    reference_salinity REAL NOT NULL,
{"".join(f"    {name} REAL NOT NULL,{chr(10)}" for name in ION_GRAM_COLUMNS)}    {ION_CHECK} TEXT,
    PRIMARY KEY (source, dataset, lat, lon, level, obs_time)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_ions_time ON seawater_ions (obs_time);
"""


def _ion_factors(salinity: str, mmol: bool = False) -> str:
    """염분 식 하나에 기준 조성 계수를 곱한 SQL 항목들. 계수는 composition 모듈의 값을 그대로 씁니다."""
    names = ION_MMOL_COLUMNS if mmol else ION_GRAM_COLUMNS
    factors = [c.mmol_per_salinity if mmol else c.grams_per_salinity for c in composition.MAJOR]
    return ", ".join(f"{salinity} * {factor!r} AS {name}" for name, factor in zip(names, factors))


def _ion_select(row: str) -> str:
    """측정 행 하나(NEW 또는 표 이름)에서 seawater_ions 한 행을 만드는 SELECT 목록."""
    head = ", ".join(f"{row}.{name}" for name in (*ION_KEY, "kind", "depth_m", "location_id"))
    reference = f"{row}.value * {composition.REFERENCE_SALINITY_FACTOR!r} AS reference_salinity"
    check = f"{ranges.sql_check(f'{row}.value', f'{row}.depth_m')} AS {ION_CHECK}"
    return f"{head}, {row}.value AS practical_salinity, {reference}, {_ion_factors(f'{row}.value')}, {check}"


def _ion_match(row: str) -> str:
    return " AND ".join(f"{name} = {row}.{name}" for name in ION_KEY)


def grid_depth(layer: str) -> float:
    """염분 격자 레이어의 수심(m). HYCOM 층은 이름 끝의 숫자가 수심이고, 위성 표층 염분 레이어는 0 입니다."""
    tail = layer[len(GRID_DEPTH_PREFIX):] if layer.startswith(GRID_DEPTH_PREFIX) else ""
    return float(tail) if tail.isdigit() else 0.0


def _grid_depth_sql(layer: str) -> str:
    """grid_depth 와 같은 규칙을 SQL 식으로 적은 것. 레이어 이름만 보므로 수심 목록이 바뀌어도 그대로 맞습니다."""
    size = len(GRID_DEPTH_PREFIX)
    tail = f"CAST(substr({layer}, {size + 1}) AS REAL)"
    return f"CASE WHEN substr({layer}, 1, {size}) = '{GRID_DEPTH_PREFIX}' THEN {tail} ELSE 0.0 END"


ION_INSERT = f"INSERT INTO seawater_ions ({', '.join(ION_COLUMNS)}, {ION_CHECK})"
ION_BACKFILL = (
    f"{ION_INSERT} SELECT {_ion_select('m')} FROM measurements AS m WHERE m.variable = '{SALINITY}' AND m.value > 0"
)
ION_DROPS = (
    *(f"DROP TRIGGER IF EXISTS {name}" for name in ION_OBJECTS[:3]),
    *(f"DROP VIEW IF EXISTS {name}" for name in ION_OBJECTS[3:]),
)
ION_CREATES = (
    f"""CREATE TRIGGER seawater_ions_insert AFTER INSERT ON measurements
        WHEN NEW.variable = '{SALINITY}'
        BEGIN
            DELETE FROM seawater_ions WHERE {_ion_match("NEW")};
            {ION_INSERT} SELECT {_ion_select("NEW")} WHERE NEW.value > 0;
        END""",
    f"""CREATE TRIGGER seawater_ions_update AFTER UPDATE ON measurements
        WHEN OLD.variable = '{SALINITY}' OR NEW.variable = '{SALINITY}'
        BEGIN
            DELETE FROM seawater_ions WHERE OLD.variable = '{SALINITY}' AND {_ion_match("OLD")};
            DELETE FROM seawater_ions WHERE NEW.variable = '{SALINITY}' AND {_ion_match("NEW")};
            {ION_INSERT} SELECT {_ion_select("NEW")} WHERE NEW.variable = '{SALINITY}' AND NEW.value > 0;
        END""",
    f"""CREATE TRIGGER seawater_ions_delete AFTER DELETE ON measurements
        WHEN OLD.variable = '{SALINITY}'
        BEGIN
            DELETE FROM seawater_ions WHERE {_ion_match("OLD")};
        END""",
    f"""CREATE VIEW seawater_ions_mmol AS
        SELECT {", ".join(ION_COLUMNS[:-len(ION_GRAM_COLUMNS)])}, {_ion_factors("practical_salinity", mmol=True)},
               {ION_CHECK}
        FROM seawater_ions""",
    f"""CREATE VIEW argo_level_ions AS
        SELECT platform, cycle, obs_time, lat, lon, data_mode, pressure_dbar, depth_m, temperature_c,
               salt AS practical_salinity, salt * {composition.REFERENCE_SALINITY_FACTOR!r} AS reference_salinity,
               {_ion_factors("salt")}, {ranges.sql_check("salt", "depth_m")} AS {ION_CHECK}
        FROM (
            SELECT p.platform, p.cycle, p.obs_time, p.lat, p.lon, p.data_mode,
                   json_extract(l.value, '$.pressure_dbar') AS pressure_dbar,
                   json_extract(l.value, '$.depth_m') AS depth_m,
                   json_extract(l.value, '$.temp') AS temperature_c,
                   json_extract(l.value, '$.salt') AS salt
            FROM argo_profiles AS p, json_each(p.levels_json) AS l
        )
        WHERE salt > 0""",
    f"""CREATE VIEW grid_ions AS
        SELECT layer, valid_time, area, depth_m, valid_cells, salt AS practical_salinity,
               salt * {composition.REFERENCE_SALINITY_FACTOR!r} AS reference_salinity,
               {_ion_factors("salt")}, {_ion_factors("salt", mmol=True)},
               {ranges.sql_check("salt", "depth_m")} AS {ION_CHECK}
        FROM (
            SELECT g.layer AS layer, g.valid_time AS valid_time, '{GRID_ALL}' AS area,
                   {_grid_depth_sql("g.layer")} AS depth_m,
                   json_extract(g.stats_json, '$.valid_cells') AS valid_cells,
                   json_extract(g.stats_json, '$.mean') AS salt
            FROM grids AS g
            WHERE g.unit = '{GRID_SALINITY_UNIT}'
            UNION ALL
            SELECT g.layer, g.valid_time, s.key, {_grid_depth_sql("g.layer")},
                   json_extract(s.value, '$.valid_cells'), json_extract(s.value, '$.mean')
            FROM grids AS g, json_each(g.stats_json, '$.sectors') AS s
            WHERE g.unit = '{GRID_SALINITY_UNIT}'
        )
        WHERE salt > 0""",
)
ION_MARKS = {ION_METHOD_KEY: composition.METHOD, ION_CHECK_KEY: ranges.SOURCE}


def ion_volume(salinity: float | None, temperature_c: float | None) -> dict:
    """ION_VOLUME_COLUMNS 의 값. 수온이 없거나 그 수온으로 밀도를 낼 수 없으면 밀도와 mmol/L 은 None 입니다."""
    output = dict.fromkeys(ION_VOLUME_COLUMNS)
    output["temperature_c"] = temperature_c
    basis = composition.volume_basis(salinity, temperature_c)
    if basis is not None:
        output[ION_DENSITY] = basis["density_kg_m3"]
        output.update({f"{key}_mmol_l": value for key, value in basis["mmol_per_l"].items()})
    return output


SET_KV = "INSERT INTO kv (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value"
UPSERT_MEASUREMENT = (
    f"INSERT INTO measurements ({','.join(MEASUREMENT_COLUMNS)}) VALUES ({','.join('?' * len(MEASUREMENT_COLUMNS))}) "
    "ON CONFLICT (source, dataset, variable, lat, lon, level, obs_time) DO UPDATE SET "
    "value=excluded.value, unit=excluded.unit, kind=excluded.kind, quality=excluded.quality, "
    "location_id=COALESCE(excluded.location_id, location_id), fetched_at=excluded.fetched_at"
)
ARGO_MOVED = (
    "(argo_profiles.data_mode IS NOT excluded.data_mode OR argo_profiles.obs_time IS NOT excluded.obs_time"
    " OR argo_profiles.lat IS NOT excluded.lat OR argo_profiles.lon IS NOT excluded.lon)"
)
ARGO_UNFILLED = f"(argo_profiles.levels_json IS NULL OR argo_profiles.n_levels = 0 OR {ARGO_MOVED})"


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
            self._conn.executescript(SCHEMA + ION_SCHEMA)
            self._conn.commit()
        self._ensure_ions()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _ions_current(self) -> bool:
        keys = ",".join("?" * len(ION_MARKS))
        stored = self._conn.execute(f"SELECT key, value FROM kv WHERE key IN ({keys})", tuple(ION_MARKS)).fetchall()
        if {r[0]: r[1] for r in stored} != ION_MARKS:
            return False
        marks = ",".join("?" * len(ION_OBJECTS))
        found = self._conn.execute(f"SELECT name FROM sqlite_master WHERE name IN ({marks})", ION_OBJECTS).fetchall()
        return {r[0] for r in found} == set(ION_OBJECTS)

    def _ensure_ions(self) -> None:
        """염분 행마다 이온 환산값이 seawater_ions 에 쌓이게 트리거와 뷰를 두고, 이미 있던 염분 행을 채웁니다.

        환산 방식(composition.METHOD)이나 범위 검사 기준(ranges.SOURCE)이 바뀌었거나 트리거·뷰 가운데 빠진 것이
        있을 때만 한 번 다시 계산합니다. 이전 버전이 만든 표에는 범위 검사 열을 덧붙입니다.
        다른 프로세스가 DB 를 쓰는 중이라 잠금을 얻지 못하면 다음에 열 때 다시 시도합니다.
        """
        with self._lock:
            if self._ions_current():
                return
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                if not self._ions_current():
                    for statement in ION_DROPS:
                        self._conn.execute(statement)
                    columns = {r[1] for r in self._conn.execute("PRAGMA table_info(seawater_ions)")}
                    if ION_CHECK not in columns:
                        self._conn.execute(f"ALTER TABLE seawater_ions ADD COLUMN {ION_CHECK} TEXT")
                    for statement in ION_CREATES:
                        self._conn.execute(statement)
                    self._conn.execute("DELETE FROM seawater_ions")
                    self._conn.execute(ION_BACKFILL)
                    self._conn.executemany(SET_KV, list(ION_MARKS.items()))
                self._conn.commit()
            except sqlite3.OperationalError as exc:
                self._conn.rollback()
                log.warning("ion table not prepared: %s", exc)

    @staticmethod
    def _measurement_params(rows: Iterable[Measurement], now: str) -> list[tuple]:
        return [
            (
                r.source, r.dataset, r.variable, r.kind, r.lat, r.lon, r.level, r.depth_m, r.pressure_hpa,
                r.obs_time, r.value, r.unit, r.location_id, r.quality, now,
            )
            for r in rows
        ]

    def upsert_measurements(self, rows: Iterable[Measurement]) -> int:
        params = self._measurement_params(rows, iso())
        if not params:
            return 0
        with self._lock:
            self._conn.executemany(UPSERT_MEASUREMENT, params)
            self._conn.commit()
        return len(params)

    def replace_datasets(self, source: str, groups: dict[str, list[Measurement]]) -> int:
        """자료원의 데이터셋마다 측정 행을 통째로 바꿉니다. 새 목록에 없는 옛 행은 지워집니다.

        염분 행이 바뀌면 이온 행도 트리거가 따라 바꿉니다. 모두 한 트랜잭션에서 처리합니다.
        """
        now = iso()
        count = 0
        with self._lock:
            for dataset, rows in groups.items():
                self._conn.execute("DELETE FROM measurements WHERE source = ? AND dataset = ?", (source, dataset))
                params = self._measurement_params(rows, now)
                self._conn.executemany(UPSERT_MEASUREMENT, params)
                count += len(params)
            self._conn.commit()
        return count

    def drop_invalid_metar(self, low: float, high: float) -> int:
        """수집 필터를 통과하지 못할 METAR 기온·이슬점이 이미 저장돼 있으면 지웁니다."""
        with self._lock:
            removed = self._conn.execute(
                """DELETE FROM measurements WHERE source = 'metar'
                   AND variable IN ('air_temperature', 'dew_point') AND (value < ? OR value > ?)""",
                (low, high),
            ).rowcount
            crossed = self._conn.execute(
                """SELECT d.dataset, d.lat, d.lon, d.level, d.obs_time FROM measurements d
                   JOIN measurements t ON t.source = d.source AND t.dataset = d.dataset AND t.lat = d.lat
                    AND t.lon = d.lon AND t.level = d.level AND t.obs_time = d.obs_time
                    AND t.variable = 'air_temperature'
                   WHERE d.source = 'metar' AND d.variable = 'dew_point' AND d.value > t.value"""
            ).fetchall()
            for row in crossed:
                removed += self._conn.execute(
                    """DELETE FROM measurements WHERE source = 'metar'
                       AND variable IN ('air_temperature', 'dew_point')
                       AND dataset = ? AND lat = ? AND lon = ? AND level = ? AND obs_time = ?""",
                    tuple(row),
                ).rowcount
            self._conn.commit()
        return removed

    def delete_measurements(
        self, source: str, dataset: str, variables: Iterable[str], spans: Iterable[tuple[str, str]]
    ) -> int:
        """한 데이터셋에서 지정한 시각 구간(양 끝 포함)의 변수 행을 지웁니다. 수집한 뒤에 버리기로 한 값을 정리할 때 씁니다.

        염분 행이 지워지면 이온 행도 트리거가 따라 지웁니다.
        """
        names = list(variables)
        marks = ",".join("?" * len(names))
        sql = (
            "DELETE FROM measurements WHERE source = ? AND dataset = ? AND obs_time BETWEEN ? AND ? "
            f"AND variable IN ({marks})"
        )
        removed = 0
        with self._lock:
            for start, end in spans:
                removed += self._conn.execute(sql, (source, dataset, start, end, *names)).rowcount
            self._conn.commit()
        return removed

    def relabel_metar_pressure(self) -> int:
        """예전에 ``surface_pressure``로 저장된 METAR 해면 기압을 ``sea_level_pressure``로 옮깁니다."""
        with self._lock:
            moved = self._conn.execute(
                """UPDATE OR IGNORE measurements SET variable = 'sea_level_pressure'
                   WHERE source = 'metar' AND variable = 'surface_pressure'"""
            ).rowcount
            self._conn.execute("DELETE FROM measurements WHERE source = 'metar' AND variable = 'surface_pressure'")
            self._conn.commit()
        return moved

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

    def iter_ions(
        self,
        *,
        source: str | None = None,
        location_id: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int | None = None,
        mmol: bool = False,
        temperature: bool = False,
    ) -> Iterator[dict]:
        """염분에서 환산한 이온 조성 행을 시각 순으로 돌려줍니다. mmol=True 면 mmol/kg 열을 함께 붙입니다.

        temperature=True 면 같은 자료·위치·층·시각의 수온을 temperature_c 로 붙이고, 그 수온에서의 1기압 밀도와
        mmol/L 열(ION_VOLUME_COLUMNS)도 붙입니다. 짝이 되는 수온이 없으면 모두 None 입니다.
        """
        clauses, params = [], []
        for column, value, op in (
            ("source", source, "="), ("location_id", location_id, "="), ("obs_time", since, ">="), ("obs_time", until, "<="),
        ):
            if value is not None:
                clauses.append(f"i.{column} {op} ?")
                params.append(value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        tail = f" LIMIT {int(limit)}" if limit else ""
        extra = f", {_ion_factors('i.practical_salinity', mmol=True)}" if mmol else ""
        paired = ""
        if temperature:
            extra += ", t.value AS temperature_c"
            match = " AND ".join(f"t.{name} = i.{name}" for name in ION_KEY)
            paired = f" LEFT JOIN measurements AS t ON t.variable = '{TEMPERATURE}' AND {match}"
        sql = f"SELECT i.*{extra} FROM seawater_ions AS i{paired} {where} ORDER BY i.obs_time, i.source, i.level{tail}"
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        for row in rows:
            item = dict(row)
            if temperature:
                item.update(ion_volume(item["practical_salinity"], item["temperature_c"]))
            yield item

    def count_ions(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM seawater_ions").fetchone()[0]

    def iter_argo_level_ions(
        self, *, since: str | None = None, until: str | None = None, batch: int = 5000
    ) -> Iterator[dict]:
        """Argo 층별 염분에서 환산한 이온 조성. argo_level_ions 뷰를 읽으며, 층이 많아 묶음으로 나눠 가져옵니다."""
        clauses, params = [], []
        for value, op in ((since, ">="), (until, "<=")):
            if value is not None:
                clauses.append(f"obs_time {op} ?")
                params.append(value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT * FROM argo_level_ions {where} ORDER BY obs_time, platform, cycle, pressure_dbar"
        with self._lock:
            cursor = self._conn.execute(sql, params)
        while True:
            with self._lock:
                rows = cursor.fetchmany(batch)
            if not rows:
                break
            for row in rows:
                yield dict(row)

    def count_argo_level_ions(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM argo_level_ions").fetchone()[0]

    def iter_grid_ions(
        self, *, since: str | None = None, until: str | None = None, layer: str | None = None
    ) -> Iterator[dict]:
        """염분 격자의 60°S 이남 평균과 해역 평균에서 환산한 이온 조성. grid_ions 뷰를 읽습니다.

        환산이 염분에 비례하므로 평균 염분에 계수를 곱한 값은 칸마다 환산한 뒤 평균한 값과 같습니다.
        시각, 레이어, 해역(전체가 먼저, 그다음 SECTORS 순) 순으로 돌려줍니다.
        """
        clauses, params = [], []
        for column, value, op in (("valid_time", since, ">="), ("valid_time", until, "<="), ("layer", layer, "=")):
            if value is not None:
                clauses.append(f"{column} {op} ?")
                params.append(value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock:
            rows = self._conn.execute(f"SELECT * FROM grid_ions {where}", params).fetchall()
        order = {area: index for index, area in enumerate(GRID_AREAS)}
        for row in sorted(rows, key=lambda r: (r["valid_time"], r["layer"], order.get(r["area"], len(order)))):
            yield dict(row)

    def count_grid_ions(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM grid_ions").fetchone()[0]

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
        """목록 행을 넣습니다. 층별 값이 있는 프로파일의 표층 값은 그 층에서 고른 것이므로 건드리지 않습니다.

        자료 모드나 시각·위치가 바뀐 프로파일은 다른 관측으로 보고, 층별 값을 비워 다시 받게 합니다.
        """
        now = iso()
        count = 0
        with self._lock:
            for r in rows:
                self._conn.execute(
                    f"""INSERT INTO argo_profiles
                       (platform, cycle, obs_time, lat, lon, data_mode, position_qc, surface_temp, surface_salt, fetched_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT (platform, cycle) DO UPDATE SET
                         obs_time = excluded.obs_time, lat = excluded.lat, lon = excluded.lon,
                         data_mode = excluded.data_mode, position_qc = excluded.position_qc,
                         surface_temp = CASE WHEN {ARGO_UNFILLED}
                                             THEN excluded.surface_temp ELSE argo_profiles.surface_temp END,
                         surface_salt = CASE WHEN {ARGO_UNFILLED}
                                             THEN excluded.surface_salt ELSE argo_profiles.surface_salt END,
                         levels_json = CASE WHEN {ARGO_MOVED} THEN NULL ELSE argo_profiles.levels_json END""",
                    (
                        r["platform"], r["cycle"], r["time"], r["lat"], r["lon"], r.get("data_mode"),
                        r.get("position_qc"), r.get("surface_temp"), r.get("surface_salt"), now,
                    ),
                )
                count += 1
            self._conn.commit()
        return count

    def save_argo_levels(self, platform: str, cycle: int, levels: list[dict]) -> None:
        """층별 값을 저장합니다. 표층 값은 seawater.surface_values 가 고른 얕은 층의 값이고, 없으면 비워 둡니다.

        받은 층이 하나도 없으면 목록에서 온 임시 표층 값을 그대로 둡니다.
        """
        surface = seawater.surface_values(levels)
        depths = [lv["depth_m"] for lv in levels if lv.get("depth_m") is not None]
        keep = not levels
        with self._lock:
            self._conn.execute(
                """UPDATE argo_profiles SET levels_json = ?, n_levels = ?, max_depth_m = ?,
                   surface_temp = CASE WHEN ? THEN surface_temp ELSE ? END,
                   surface_salt = CASE WHEN ? THEN surface_salt ELSE ? END,
                   fetched_at = ? WHERE platform = ? AND cycle = ?""",
                (
                    json.dumps(levels, separators=(",", ":")), len(levels), max(depths) if depths else None,
                    keep, surface["temp"], keep, surface["salt"], iso(), platform, cycle,
                ),
            )
            self._conn.commit()

    def set_argo_surface(self, rows: Iterable[tuple[float | None, float | None, str, int]]) -> None:
        """(표층 수온, 표층 염분, 플랫폼, 사이클) 묶음으로 프로파일의 표층 값만 고칩니다. 층별 값은 그대로 둡니다."""
        with self._lock:
            self._conn.executemany(
                "UPDATE argo_profiles SET surface_temp = ?, surface_salt = ? WHERE platform = ? AND cycle = ?", list(rows)
            )
            self._conn.commit()

    def argo_missing_levels(self, limit: int, recheck_days: int = 30) -> list[dict]:
        """층별 값을 받을 프로파일. 막 올라온 프로파일은 서버 색인이 늦어 비어 보일 수 있으므로, 빈 것은 하루 뒤 다시 묻습니다."""
        now = utcnow()
        with self._lock:
            rows = self._conn.execute(
                "SELECT platform, cycle, lat, lon, obs_time, data_mode FROM argo_profiles "
                "WHERE levels_json IS NULL OR (n_levels = 0 AND obs_time >= ? AND fetched_at < ?) "
                "ORDER BY obs_time DESC LIMIT ?",
                (iso(now - timedelta(days=recheck_days)), iso(now - timedelta(days=1)), limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def argo_count_missing(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM argo_profiles WHERE levels_json IS NULL").fetchone()[0]

    def argo_without_levels(self) -> set[tuple[str, int]]:
        """층별 값이 아직 없거나 받아 보니 비어 있던 프로파일의 (플랫폼, 사이클)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT platform, cycle FROM argo_profiles WHERE levels_json IS NULL OR n_levels = 0"
            ).fetchall()
        return {(r["platform"], r["cycle"]) for r in rows}

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
            self._conn.execute(SET_KV, (key, value))
            self._conn.commit()
