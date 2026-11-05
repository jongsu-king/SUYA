"""좌표 해석, 해수 물성, 격자 계산, 저장소, 수집 엔진을 검증합니다."""

import argparse
import asyncio
import math
import sys
import time
from datetime import datetime, timezone

import httpx
import pytest

from antarctic_monitor import cli, instance, pointquery, seawater, updates
from antarctic_monitor.collectors import JOBS, hycom, windy
from antarctic_monitor.collectors.base import CollectResult, Context
from antarctic_monitor.collectors.openmeteo import BudgetExceeded, consume_budget
from antarctic_monitor.config import Settings, load_dotenv
from antarctic_monitor.db import Measurement, Store
from antarctic_monitor.engine import Engine, EventBus, failure_message, job_timeout
from antarctic_monitor.geo import haversine_km, normalize_lon, parse_location_url
from antarctic_monitor.gridutil import find_nearest_valid, grid_from_triples, grid_stats, sample_nearest
from antarctic_monitor.http import DEFAULT_HOST_LIMIT, FetchError, Fetcher, RateLimited
from antarctic_monitor.i18n import msg, render


def test_parse_nullschool_link_from_request():
    point = parse_location_url(
        "https://earth.nullschool.net/ko/#current/wind/surface/level/orthographic=-196.44,-86.24,479/loc=152.723,-80.012"
    )
    assert (point.lat, point.lon, point.site, point.kind) == (-80.012, 152.723, "nullschool", "marker")


def test_parse_windy_link_from_request():
    point = parse_location_url("https://www.windy.com/-67.052/-66.257?-68.936,-64.888,5")
    assert (point.lat, point.lon, point.site, point.kind) == (-67.052, -66.257, "windy", "marker")


def test_parse_view_only_links():
    nullschool = parse_location_url("https://earth.nullschool.net/#current/wind/surface/level/orthographic=-196.44,-86.24,479")
    assert nullschool.kind == "view"
    assert nullschool.lat == -86.24
    assert nullschool.lon == pytest.approx(163.56)
    windy_view = parse_location_url("https://www.windy.com/?sst,-68.936,-64.888,5")
    assert (windy_view.lat, windy_view.lon, windy_view.kind) == (-68.936, -64.888, "view")


@pytest.mark.parametrize("bad", ["https://example.com/-67/-66", "https://www.windy.com/", "https://earth.nullschool.net/#current", "https://www.windy.com/-100/0"])
def test_parse_rejects_other_input(bad):
    with pytest.raises(ValueError):
        parse_location_url(bad)


def test_longitude_normalization_and_distance():
    assert normalize_lon(-196.44) == pytest.approx(163.56)
    assert normalize_lon(180.0) == -180.0
    assert haversine_km(-90, 0, -80, 0) == pytest.approx(1112, abs=2)


def test_freezing_point_check_value():
    assert seawater.freezing_point_c(40.0, 500.0) == pytest.approx(-2.588567, abs=1e-5)


def test_density_check_values():
    assert seawater.density_surface(0.0, 5.0) == pytest.approx(999.96675, abs=1e-4)
    assert seawater.density_surface(35.0, 5.0) == pytest.approx(1027.67547, abs=1e-4)
    assert seawater.density_surface(35.0, 25.0) == pytest.approx(1023.34306, abs=1e-4)


def test_depth_check_value():
    assert seawater.depth_from_pressure(10000.0, 30.0) == pytest.approx(9712.653, abs=1e-2)


def test_derive_handles_missing_values():
    assert seawater.derive(None, None)["freezing_point_c"] is None
    partial = seawater.derive(None, 34.0)
    assert partial["freezing_point_c"] == pytest.approx(-1.87, abs=0.01)
    assert partial["sigma_t"] is None
    assert seawater.derive(-1.0, 34.0)["above_freezing_c"] == pytest.approx(0.87, abs=0.01)


def _grid():
    triples = [
        (-70.0, -10.0, 1.0), (-70.0, 10.0, 3.0), (-70.0, 170.0, None),
        (-50.0, -10.0, 100.0), (-50.0, 10.0, 100.0), (-50.0, 170.0, 100.0),
    ]
    return grid_from_triples("t", "2026-11-04T00:00:00Z", "°C", triples)


def test_grid_stats_only_counts_south_of_60():
    stats = grid_stats(_grid())
    assert stats["mean"] == 2.0
    assert stats["coverage"] == pytest.approx(2 / 3, abs=0.001)
    assert stats["sectors"]["weddell"]["mean"] == 2.0
    assert stats["sectors"]["ross"]["mean"] is None


def test_grid_normalizes_0_360_longitudes():
    grid = grid_from_triples("t", "x", "°C", [(-70.0, 300.0, 5.0), (-70.0, 10.0, 6.0)])
    assert grid.lons == [-60.0, 10.0]
    assert grid.values == [5.0, 6.0]


def test_sample_and_nearest_for_land_points():
    grid = grid_from_triples("t", "x", "°C", [(-70.0, 170.0, None), (-70.0, 160.0, 7.0), (-50.0, 170.0, 100.0)])
    assert sample_nearest(grid, -70.0, 171.0) is None
    nearest = find_nearest_valid(grid, -70.0, 171.0)
    assert nearest["value"] == 7.0
    assert 400 < nearest["distance_km"] < 430


def test_find_nearest_returns_none_when_all_missing():
    grid = grid_from_triples("t", "x", "°C", [(-70.0, 0.0, None)])
    assert find_nearest_valid(grid, -70.0, 0.0) is None


@pytest.fixture
def store(tmp_path):
    instance = Store(tmp_path / "test.db")
    yield instance
    instance.close()


def _measurement(value=1.0, when="2026-11-04T00:00:00Z", location="x"):
    return Measurement(
        source="s", dataset="d", variable="sea_water_temperature", kind="analysis",
        lat=-70.0, lon=0.0, obs_time=when, value=value, unit="°C", location_id=location,
    )


def test_upsert_replaces_same_key(store):
    store.upsert_measurements([_measurement(1.0)])
    store.upsert_measurements([_measurement(2.0)])
    rows = store.query_measurements(source="s")
    assert len(rows) == 1
    assert rows[0]["value"] == 2.0


def test_latest_for_location_ignores_future_forecasts(store):
    store.upsert_measurements([_measurement(1.0, "2020-01-01T00:00:00Z"), _measurement(9.0, "2999-01-01T00:00:00Z")])
    latest = store.latest_for_location("x")
    assert list(latest.values())[0]["value"] == 1.0


def test_grid_roundtrip(store):
    grid = _grid()
    store.save_grid(grid)
    loaded = store.load_grid("t")
    assert loaded.values == grid.values
    assert store.latest_grid_info()["t"]["stats"]["mean"] == 2.0


def test_argo_levels_survive_relisting_but_reset_when_mode_changes(store):
    listing = {"platform": "1", "cycle": 2, "time": "2026-11-01T00:00:00Z", "lat": -65.0, "lon": 0.0, "data_mode": "R", "position_qc": "1", "surface_temp": 1.0, "surface_salt": None}
    store.upsert_argo_listing([listing])
    assert len(store.argo_missing_levels(10)) == 1
    store.save_argo_levels("1", 2, [{"pressure_dbar": 5.0, "depth_m": 5.0, "temp": 0.5, "salt": 34.0}])
    assert store.argo_count_missing() == 0
    store.upsert_argo_listing([listing])
    assert store.argo_count_missing() == 0
    store.upsert_argo_listing([listing | {"data_mode": "D"}])
    assert store.argo_count_missing() == 1


def test_prune_removes_only_old_forecasts(store):
    old = "2000-01-01T00:00:00Z"
    store.upsert_measurements([
        Measurement(source="f", dataset="d", variable="v", kind="forecast", lat=0, lon=0, obs_time=old, value=1, unit="x"),
        Measurement(source="o", dataset="d", variable="v", kind="observation", lat=0, lon=0, obs_time=old, value=1, unit="x"),
    ])
    store.prune()
    assert [r["source"] for r in store.query_measurements()] == ["o"]


def _ctx(store, **settings):
    return Context(store, Fetcher(), Settings(**settings))


def test_budget_blocks_at_limit(store):
    ctx = _ctx(store, openmeteo_daily_budget=10)
    consume_budget(ctx, 10)
    with pytest.raises(BudgetExceeded):
        consume_budget(ctx, 1)


def test_budget_reserve_protects_priority_jobs(store):
    ctx = _ctx(store, openmeteo_daily_budget=100)
    with pytest.raises(BudgetExceeded):
        consume_budget(ctx, 71, reserve=0.3)
    consume_budget(ctx, 70, reserve=0.3)


async def test_fetcher_retries_then_succeeds():
    calls = {"count": 0}

    def handler(request):
        calls["count"] += 1
        return httpx.Response(503) if calls["count"] < 3 else httpx.Response(200, text="ok")

    fetcher = Fetcher(httpx.AsyncClient(transport=httpx.MockTransport(handler)), backoff=0.0)
    assert await fetcher.get_text("https://x.test/") == "ok"
    assert calls["count"] == 3
    await fetcher.aclose()


async def test_fetcher_gives_up_after_retries():
    fetcher = Fetcher(httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500))), backoff=0.0)
    with pytest.raises(FetchError):
        await fetcher.get_text("https://x.test/")
    await fetcher.aclose()


async def test_interactive_requests_do_not_queue_behind_collection():
    fetcher = Fetcher(httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="ok"))), backoff=0.0)
    background = fetcher._semaphore("https://x.test/a")
    for _ in range(DEFAULT_HOST_LIMIT):
        await background.acquire()
    assert await asyncio.wait_for(fetcher.get_text("https://x.test/b", interactive=True), 1.0) == "ok"
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(fetcher.get_text("https://x.test/c"), 0.2)
    await fetcher.aclose()


async def test_point_lookup_guard_reports_timeout():
    errors: list[dict] = []
    assert await pointquery._guard("HYCOM", asyncio.sleep(5), errors, timeout=0.05) is None
    assert errors[0]["source"] == "HYCOM" and "시간 초과" in render(errors[0]["message"])


async def test_point_cache_keeps_partial_results_only_briefly():
    cache = pointquery.TTLCache()

    async def partial():
        return {"errors": [{"source": "HYCOM", "message": "x"}]}

    async def complete():
        return {"errors": []}

    await cache.get(("p",), 10800.0, partial)
    await cache.get(("c",), 10800.0, complete)
    now = time.monotonic()
    assert cache._values[("p",)][0] - now <= pointquery.PARTIAL_TTL + 1
    assert cache._values[("c",)][0] - now > pointquery.PARTIAL_TTL + 1


async def test_climatology_is_kept_in_the_store(store):
    calls = {"count": 0}

    def handler(request):
        calls["count"] += 1
        return httpx.Response(200, text="time,altitude,latitude,longitude,value\n1,0.0,-62,150,1.5\n1,10.0,-62,150,1.2\n")

    fetcher = Fetcher(httpx.AsyncClient(transport=httpx.MockTransport(handler)), backoff=0.0)
    errors: list[dict] = []
    first = await pointquery._climatology(Context(store, fetcher, Settings()), -62.0, 150.0, 11, errors)
    assert first["levels"] and calls["count"] == 4 and not errors
    await fetcher.aclose()

    offline = Fetcher(httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500))), backoff=0.0)
    second = await pointquery._climatology(Context(store, offline, Settings()), -62.0, 150.0, 11, errors)
    assert second == first and not errors
    await offline.aclose()


def test_mixed_layer_depth_uses_the_temperature_criterion():
    levels = [{"depth_m": d, "temp": 1.0 if d <= 50 else 1.0 - 0.05 * (d - 50)} for d in (0, 5, 10, 20, 30, 40, 50, 60, 75, 100)]
    assert seawater.mixed_layer_depth(levels) == 60.0
    assert seawater.mixed_layer_depth([{"depth_m": 0, "temp": 1.0}, {"depth_m": 5, "temp": 0.0}]) is None
    assert seawater.mixed_layer_depth([{"depth_m": d, "temp": 1.0} for d in (0, 10, 50, 100)]) is None
    assert seawater.mixed_layer_depth([{"depth_m": 10, "salt": 34.0}]) is None


def test_second_instance_is_refused(tmp_path):
    from antarctic_monitor.instance import InstanceLock

    first = InstanceLock(tmp_path)
    assert first.acquire()
    second = InstanceLock(tmp_path)
    assert not second.acquire()
    first.release()
    assert second.acquire()
    second.release()


def test_file_lock_refuses_a_second_holder(tmp_path):
    first = instance._FileLock(tmp_path / "suya.lock")
    assert first.acquire()
    second = instance._FileLock(tmp_path / "suya.lock")
    assert not second.acquire()
    first.release()
    assert second.acquire()
    second.release()
    assert (tmp_path / "suya.lock").exists()


def test_instance_lock_works_without_qt(tmp_path, monkeypatch):
    monkeypatch.setattr(instance, "QLockFile", None)
    first = instance.InstanceLock(tmp_path)
    assert isinstance(first._lock, instance._FileLock)
    assert first.acquire()
    assert not instance.InstanceLock(tmp_path).acquire()
    first.release()
    assert instance.InstanceLock(tmp_path).acquire()


def test_cli_explains_missing_window_libraries(monkeypatch, capsys):
    from antarctic_monitor import i18n

    monkeypatch.setattr(i18n, "_language", i18n.get_language())
    monkeypatch.setitem(sys.modules, "PySide6", None)
    monkeypatch.setitem(sys.modules, "antarctic_monitor.gui.app", None)
    monkeypatch.setattr(cli, "_configure_logging", lambda command: None)
    assert not cli.gui_available()
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--lang", "en", "gui"])
    assert exit_info.value.code == 2
    assert 'suya[gui]' in capsys.readouterr().err
    with pytest.raises(SystemExit):
        cli.main(["--lang", "ko", "gui"])
    assert "suya[gui]" in capsys.readouterr().err


def test_self_test_runs_without_qt(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "PySide6", None)
    cli._self_test(argparse.Namespace(out=None))
    out = capsys.readouterr().out
    assert "gui skipped" in out and "excel ok" in out and "version" in out


def test_release_check_compares_versions():
    assert updates.is_newer("v0.1.2", "0.1.1") and updates.is_newer("1.0", "0.9.9") and updates.is_newer("0.1.10", "0.1.9")
    assert not updates.is_newer("v0.1.1", "0.1.1") and not updates.is_newer("0.0.9", "0.1.1") and not updates.is_newer("", "0.1.1")


async def test_release_check_reads_github():
    payload = {"tag_name": "v9.9.9", "html_url": "https://example.test/releases/v9.9.9"}
    fetcher = Fetcher(httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))), backoff=0.0)
    result = await updates.latest_release(fetcher)
    assert (result["version"], result["url"], result["newer"]) == ("9.9.9", payload["html_url"], True)
    assert result["asset"] is None and result["checksums"] is None
    await fetcher.aclose()


async def test_fetcher_does_not_retry_rate_limit():
    calls = {"count": 0}

    def handler(request):
        calls["count"] += 1
        return httpx.Response(429, text="limit")

    fetcher = Fetcher(httpx.AsyncClient(transport=httpx.MockTransport(handler)), backoff=0.0)
    with pytest.raises(RateLimited):
        await fetcher.get_text("https://x.test/")
    assert calls["count"] == 1
    await fetcher.aclose()


async def test_windy_disabled_without_key(store):
    ctx = _ctx(store)
    result = await windy.collect(ctx)
    assert result.disabled
    assert store.count_measurements() == 0


async def test_windy_marks_testing_key_data(store):
    def handler(request):
        assert request.url.path == "/api/point-forecast/v2"
        return httpx.Response(200, json={"ts": [1793757000000], "units": {"temp-surface": "K"}, "temp-surface": [260.0]})

    fetcher = Fetcher(httpx.AsyncClient(transport=httpx.MockTransport(handler)), backoff=0.0)
    ctx = Context(store, fetcher, Settings(windy_api_key="k", windy_key_tier="testing"))
    result = await windy.collect(ctx)
    rows = store.query_measurements(source="windy")
    assert result.rows == len(rows) > 0
    assert {r["quality"] for r in rows} == {"windy_testing_shuffled"}
    assert rows[0]["value"] == pytest.approx(-13.15)
    await fetcher.aclose()


async def test_windy_rejected_key_surfaces_error(store):
    fetcher = Fetcher(
        httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(400, json={"message": "Invalid API key"}))),
        backoff=0.0,
    )
    ctx = Context(store, fetcher, Settings(windy_api_key="bad"))
    with pytest.raises(FetchError, match="Invalid API key"):
        await windy.collect(ctx)
    await fetcher.aclose()


def _engine(store, monkeypatch, job, interval=100):
    monkeypatch.setitem(JOBS, "fake", job)
    settings = Settings(intervals={"fake": interval})
    bus = EventBus()
    return Engine(Context(store, Fetcher(), settings), bus, ["fake"]), bus


async def test_engine_success_records_state_and_events(store, monkeypatch):
    async def job(ctx):
        return CollectResult(rows=5, data_time="2026-11-04T00:00:00Z", message="좋음")

    engine, bus = _engine(store, monkeypatch, job)
    delay = await engine.run_once("fake")
    assert delay == 100
    state = store.source_states()["fake"]
    assert state["last_status"] == "ok"
    assert state["last_rows"] == 5
    assert [e["state"] for e in bus.history] == ["running", "done"]
    await engine.ctx.fetcher.aclose()


async def test_engine_failure_keeps_old_data_time_and_backs_off(store, monkeypatch):
    results = iter([CollectResult(rows=1, data_time="2026-11-04T00:00:00Z"), RuntimeError("서버 고장")])

    async def job(ctx):
        item = next(results)
        if isinstance(item, Exception):
            raise item
        return item

    engine, _ = _engine(store, monkeypatch, job, interval=3600)
    await engine.run_once("fake")
    delay = await engine.run_once("fake")
    state = store.source_states()["fake"]
    assert state["last_status"] == "error"
    assert "서버 고장" in state["last_message"]
    assert state["data_time"] == "2026-11-04T00:00:00Z"
    assert state["last_success"] is not None
    assert delay < 3600
    await engine.ctx.fetcher.aclose()


async def test_engine_logs_failures_as_readable_text(store, monkeypatch, caplog):
    nested = msg("Argo 프로파일을 받지 못했습니다: {error}", error=msg("프로파일 없음: {platform}/{cycle}", platform="5905620", cycle=35))

    async def job(ctx):
        raise FetchError(nested)

    engine, _ = _engine(store, monkeypatch, job)
    with caplog.at_level("WARNING", logger="antarctic_monitor.engine"):
        await engine.run_once("fake")
    assert "수집 실패 fake: Argo 프로파일을 받지 못했습니다: 프로파일 없음: 5905620/35" in caplog.text
    assert "\x1f" not in caplog.text
    assert render(store.source_states()["fake"]["last_message"]) == "Argo 프로파일을 받지 못했습니다: 프로파일 없음: 5905620/35"
    await engine.ctx.fetcher.aclose()


async def test_engine_describes_job_timeouts_and_bare_exceptions(store, monkeypatch, caplog):
    async def slow_job(ctx):
        await asyncio.sleep(5)
        return CollectResult(rows=1)

    monkeypatch.setattr("antarctic_monitor.engine.JOB_TIMEOUT", 0.05)
    engine, _ = _engine(store, monkeypatch, slow_job)
    with caplog.at_level("WARNING", logger="antarctic_monitor.engine"):
        await engine.run_once("fake")
    state = store.source_states()["fake"]
    assert state["last_status"] == "error"
    assert render(state["last_message"]) == "1분 안에 끝나지 않아 중단했습니다"
    assert "수집 실패 fake: 1분 안에 끝나지 않아 중단했습니다" in caplog.text
    assert "TimeoutError" not in caplog.text
    await engine.ctx.fetcher.aclose()

    async def bare_job(ctx):
        raise RuntimeError()

    engine, _ = _engine(store, monkeypatch, bare_job)
    await engine.run_once("fake")
    assert store.source_states()["fake"]["last_message"] == "RuntimeError"
    await engine.ctx.fetcher.aclose()


def test_job_timeouts_are_longer_for_hycom():
    assert job_timeout("hycom_grid") == 3600.0
    assert job_timeout("hycom_profiles") == 3600.0
    assert job_timeout("metar") == 1800.0
    assert render(failure_message(TimeoutError(), 3600.0)) == "60분 안에 끝나지 않아 중단했습니다"


async def test_hycom_grid_hands_remaining_variables_to_the_next_run(store, monkeypatch):
    origin = datetime(2026, 11, 5, tzinfo=timezone.utc)

    async def time_axis(fetcher, variable, interactive=False):
        return [0.0, 3.0], origin

    async def depth_axis(fetcher, variable):
        return [0.0, 100.0, 200.0, 500.0, 1000.0, 2000.0]

    async def fetch_map_layer(fetcher, variable, time_index, depth_index):
        return [-70.0, -60.0], [0.0, 10.0], [30.0, 30.0, 30.0, 30.0]

    monkeypatch.setattr(hycom, "time_axis", time_axis)
    monkeypatch.setattr(hycom, "depth_axis", depth_axis)
    monkeypatch.setattr(hycom, "fetch_map_layer", fetch_map_layer)
    ctx = Context(store, Fetcher(), Settings())

    monkeypatch.setattr(hycom, "GRID_SOFT_LIMIT", -1.0)
    first = await hycom.collect_grid(ctx)
    assert first.backlog and first.rows == 24
    assert "이어받습니다" in render(first.message) and "격자 6개 갱신" in render(first.message)
    assert store.kv_get("token:hycom_temp_0") and not store.kv_get("token:hycom_salt_0")

    monkeypatch.setattr(hycom, "GRID_SOFT_LIMIT", 1200.0)
    second = await hycom.collect_grid(ctx)
    assert not second.backlog and second.rows == 24
    assert render(second.message) == "격자 6개 갱신"
    assert store.kv_get("token:hycom_salt_2000")

    third = await hycom.collect_grid(ctx)
    assert third.unchanged and third.rows == 0
    await ctx.fetcher.aclose()


async def test_engine_rate_limit_waits_at_least_an_hour(store, monkeypatch):
    async def job(ctx):
        raise RateLimited("한도")

    engine, _ = _engine(store, monkeypatch, job, interval=60)
    assert await engine.run_once("fake") >= 3600
    assert store.source_states()["fake"]["last_status"] == "rate_limited"
    await engine.ctx.fetcher.aclose()


async def test_engine_backlog_runs_again_soon(store, monkeypatch):
    async def job(ctx):
        return CollectResult(rows=1, backlog=True)

    engine, _ = _engine(store, monkeypatch, job, interval=3600)
    assert await engine.run_once("fake") == 30.0
    await engine.ctx.fetcher.aclose()


async def test_engine_loop_runs_and_trigger_wakes_it(store, monkeypatch):
    runs = {"count": 0}

    async def job(ctx):
        runs["count"] += 1
        return CollectResult(rows=1)

    engine, _ = _engine(store, monkeypatch, job, interval=3600)
    engine.start()
    await asyncio.sleep(0.1)
    assert runs["count"] == 1
    assert engine.trigger(["fake"]) == ["fake"]
    await asyncio.sleep(0.1)
    assert runs["count"] == 2
    await engine.stop()
    await engine.ctx.fetcher.aclose()


async def test_engine_resumes_from_saved_schedule(store, monkeypatch):
    runs = {"count": 0}

    async def job(ctx):
        runs["count"] += 1
        return CollectResult()

    engine, _ = _engine(store, monkeypatch, job, interval=3600)
    await engine.run_once("fake")
    assert runs["count"] == 1
    engine.start()
    await asyncio.sleep(0.1)
    assert runs["count"] == 1
    await engine.stop()
    await engine.ctx.fetcher.aclose()


async def test_bus_drops_oldest_for_slow_subscriber():
    bus = EventBus()
    stream = bus.subscribe()
    first = asyncio.create_task(stream.__anext__())
    await asyncio.sleep(0)
    bus.publish({"n": 0})
    assert (await first) == {"n": 0}
    for index in range(250):
        bus.publish({"n": index})
    assert (await stream.__anext__())["n"] == 50
    await stream.aclose()


def test_dotenv_parser(tmp_path):
    path = tmp_path / ".env"
    path.write_text("# 주석\nA=1\nB = 'two'\n\nnot a line\n", encoding="utf-8")
    assert load_dotenv(path) == {"A": "1", "B": "two"}
    assert load_dotenv(tmp_path / "missing") == {}


def test_math_sanity():
    assert math.isclose(seawater.sigma_t(34.0, -1.8), 27.3, abs_tol=0.1)
