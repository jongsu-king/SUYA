"""Command line entry point. gui is the default command."""

from __future__ import annotations

import argparse
import asyncio
import faulthandler
import json
import logging
import logging.handlers
import os
import signal
import sys
from pathlib import Path

from . import __version__, composition, exporter, ranges
from .catalog import SOURCES
from .collectors import JOBS
from .collectors.base import Context
from .config import app_data_dir, load_settings
from .db import SALINITY, Measurement, Store
from .engine import Engine, EventBus
from .http import Fetcher
from .i18n import default_language, render, set_language, tr


def _resolve_sources(text: str | None) -> list[str] | None:
    if not text:
        return None
    names = [s.strip() for s in text.split(",") if s.strip()]
    unknown = [n for n in names if n not in JOBS]
    if unknown:
        raise SystemExit(f"Unknown source: {', '.join(unknown)}\nAvailable: {', '.join(JOBS)}")
    return names


def _print_state(store: Store, name: str) -> str | None:
    state = store.source_states().get(name, {})
    status = state.get("last_status")
    print(
        f"{name:20s} {status or '-':12s} rows={state.get('last_rows') or 0:<8} "
        f"data_time={state.get('data_time') or '-':22s} {render(state.get('last_message'))}",
        flush=True,
    )
    return status


async def _collect_once(sources: list[str] | None) -> int:
    settings = load_settings()
    store = Store(settings.db_path)
    fetcher = Fetcher()
    engine = Engine(Context(store, fetcher, settings), EventBus(), sources)
    failures = 0

    async def one(name: str) -> None:
        nonlocal failures
        await engine.run_once(name)
        if _print_state(store, name) in ("error", "rate_limited"):
            failures += 1

    collectors = [name for name in engine.sources if name != "excel"]
    await asyncio.gather(*(one(name) for name in collectors))
    if "excel" in engine.sources:
        await one("excel")
    await fetcher.aclose()
    store.close()
    return failures


async def _daemon(sources: list[str] | None) -> None:
    """Collect continuously without a window."""
    settings = load_settings()
    store = Store(settings.db_path)
    fetcher = Fetcher()
    bus = EventBus()
    engine = Engine(Context(store, fetcher, settings), bus, sources)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            signal.signal(sig, lambda *_: stop.set())

    async def report() -> None:
        async for event in bus.subscribe():
            if event and event.get("state") == "done":
                _print_state(store, event["source"])

    reporter = asyncio.create_task(report())
    engine.start()
    print(f"{tr('실시간 수집 시작')}: {store.path} (Ctrl+C)", flush=True)
    await stop.wait()
    reporter.cancel()
    await engine.stop()
    await fetcher.aclose()
    store.close()


def _export(args: argparse.Namespace) -> None:
    settings = load_settings()
    store = Store(settings.db_path)
    out = Path(args.out)
    if args.what == "measurements":
        count = exporter.export_measurements(store, out, args.source, args.variable, args.since)
    elif args.what == "argo":
        count = exporter.export_argo(store, out, args.since)
    elif args.what == "ions":
        count = exporter.export_ions(store, out, args.source, args.since)
    elif args.what == "argo-ions":
        count = exporter.export_argo_ions(store, out, args.since)
    else:
        if not args.layer:
            raise SystemExit(f"--layer is required for {args.what}, e.g. --layer hycom_salt_0")
        function = exporter.export_grid_ions if args.what == "grid-ions" else exporter.export_grid
        try:
            count = function(store, args.layer, out)
        except ValueError as exc:
            raise SystemExit(render(str(exc))) from exc
    store.close()
    print(f"{out}: {count} rows")


RANGE_VERDICTS = {ranges.OK: "범위 안", ranges.LOW: "낮음", ranges.HIGH: "높음"}


def _ions(args: argparse.Namespace) -> None:
    """Convert one practical salinity to ion amounts with the Reference Composition. Needs no database.

    A temperature adds the density at 1 atm and mmol/L. A depth adds the salinity range check for that depth.
    """
    temperature = getattr(args, "temperature", None)
    depth = getattr(args, "depth", None)
    result = composition.derive(args.salinity, temperature)
    if result is None:
        raise SystemExit(tr("염분은 0보다 큰 수여야 합니다"))
    volume = "density_kg_m3" in result
    if temperature is not None and not volume:
        low, high = composition.VOLUME_TEMPERATURE_C
        raise SystemExit(
            tr(
                "밀도는 수온 {low}~{high} °C, 염분 {limit} 이하에서만 계산합니다",
                low=f"{low:g}", high=f"{high:g}", limit=f"{composition.VOLUME_SALINITY_MAX:g}",
            )
        )
    if depth is not None:
        if depth < 0:
            raise SystemExit(tr("수심은 0 이상이어야 합니다"))
        low, high = ranges.salinity_range(depth)
        result["salinity_check"] = {
            "depth_m": depth, "low": low, "high": high,
            "verdict": ranges.check_salinity(result["practical_salinity"], depth), "source": ranges.SOURCE,
        }
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    lines = [
        f"{tr('실용 염분')} S_P: {result['practical_salinity']:.4f}",
        f"{tr('기준 염분 S_R')}: {result['reference_salinity']:.4f} g/kg",
        f"{tr('염소량')}: {result['chlorinity']:.4f} g/kg",
        f"{tr('이온 세기')}: {result['ionic_strength']:.4f} mol/kg",
    ]
    if volume:
        lines.append(f"{tr('1기압 밀도')} ({result['temperature_c']:g} °C): {result['density_kg_m3']:.3f} kg/m³")
    if depth is not None:
        check = result["salinity_check"]
        verdict = tr(RANGE_VERDICTS[check["verdict"]])
        span = tr("{low}~{high} PSU", low=f"{check['low']:g}", high=f"{check['high']:g}")
        lines.append(f"{tr('범위 검사')} ({depth:g} m): {span}, {verdict}")
    litre = f"{'mmol/L':>11}" if volume else ""
    lines += ["", f"{'':<9}{'g/kg':>10}{'mmol/kg':>11}{litre}{'%':>9}"]
    for ion in result["ions"]:
        litre = f"{ion['mmol_per_l']:>11.4f}" if volume else ""
        lines.append(
            f"{ion['symbol']:<9}{ion['g_per_kg']:>10.5f}{ion['mmol_per_kg']:>11.4f}{litre}{ion['mass_percent']:>9.4f}"
            f"  {tr(ion['name'])}"
        )
    total = sum(ion["g_per_kg"] for ion in result["ions"])
    share = sum(ion["mass_percent"] for ion in result["ions"])
    lines.append(f"{'Σ':<9}{total:>10.5f}{'':>{22 if volume else 11}}{share:>9.4f}  {tr('합계')}")
    lines.append("")
    lines.append(tr("염분에 기준 조성(Millero 외 2008)을 곱한 환산값입니다. 이온을 직접 잰 값이 아닙니다."))
    if volume:
        lines.append(tr("mmol/L 은 그 수온과 염분의 1기압 밀도로 바꾼 값입니다. 현장 압력은 넣지 않았습니다."))
    if depth is not None:
        lines.append(tr("범위는 남극해 수심별 염분 범위(Boyer & Levitus 1994)이고, 넓게 잡혀 있어 큰 오류만 가려냅니다."))
    print("\n".join(lines))


def _ion_check(folder: Path) -> str:
    """Store one salinity and read back the ion row the database derives from it."""
    store = Store(folder / "ions.db")
    store.upsert_measurements(
        [Measurement("self-test", "self-test", SALINITY, "model", -60.0, 0.0, "2026-01-01T00:00:00Z", 35.0, "PSU")]
    )
    rows = list(store.iter_ions())
    store.close()
    expected = composition.grams_per_kg(35.0, composition.MAJOR)["chloride"]
    if len(rows) != 1 or abs(rows[0]["chloride_g_kg"] - expected) > 1e-9:
        raise SystemExit("ions failed: the database did not derive the ion row from the stored salinity")
    return f"ions ok Cl {rows[0]['chloride_g_kg']:.4f} g/kg at salinity 35"


def _excel_sync(args: argparse.Namespace) -> None:
    """Write the monthly workbooks. The GUI runs this as a child process."""
    from . import excel

    settings = load_settings()
    store = Store(args.db or settings.db_path)
    directory = Path(args.dir) if args.dir else settings.excel_dir
    months = None
    if args.all:
        months = store.months_with_data()
    elif args.month:
        months = [args.month]
    result = excel.sync(store, directory, months)
    store.close()
    if args.result:
        Path(args.result).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    elif sys.stdout:
        print(f"{directory}: {', '.join(result['files'])} ({result['rows']} rows)")


def gui_available() -> bool:
    """True when the window's libraries are installed (the ``gui`` extra); a server copy may lack them."""
    try:
        import matplotlib  # noqa: F401
        import PySide6  # noqa: F401
    except ImportError:
        return False
    return True


def _self_test(args: argparse.Namespace) -> None:
    """Check that an installed copy can load everything it needs. Used by the installer build."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import tempfile

    from . import excel
    from .config import Settings

    lines = []
    with tempfile.TemporaryDirectory() as temp:
        settings = Settings(db_path=Path(temp) / "test.db", excel_dir=Path(temp) / "excel", update_mode="off")
        if gui_available():
            from PySide6.QtWidgets import QApplication

            from .gui.app import MainWindow
            from .gui.backend import Backend

            app = QApplication.instance() or QApplication(sys.argv[:1])
            backend = Backend(settings, collect=False)
            backend.start()
            window = MainWindow(backend, settings)
            window.show()
            app.processEvents()
            window.grab()
            lines.append("gui ok")
            lines.append(f"excel ok {excel.sync(backend.store, settings.excel_dir)['files']}")
            window.close()
            app.processEvents()
        else:
            store = Store(settings.db_path)
            lines.append("gui skipped (window libraries not installed; collection and Excel only)")
            lines.append(f"excel ok {excel.sync(store, settings.excel_dir)['files']}")
            store.close()
        lines.append(_ion_check(Path(temp)))
    lines.append(f"version {__version__}")
    text = "\n".join(lines) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    if sys.stdout:
        print(text, end="")


def _exit(code: int) -> None:
    """Leave without the interpreter's final garbage collection.

    Tearing Qt objects down from that last collection aborts some PySide6 builds (seen on Linux with
    Python 3.11: "none_dealloc: deallocating None"), so everything is flushed here and the process ends at once.
    Nothing is collected or deleted first: destroying Qt objects while the backend thread may still be
    winding down is itself a source of intermittent exit-time failures.
    """
    logging.shutdown()
    for stream in (sys.stdout, sys.stderr):
        if stream:
            try:
                stream.flush()
            except OSError:
                pass
    os._exit(code)


_crash_log = None


def _configure_logging(command: str) -> None:
    global _crash_log
    if command in ("gui", "daemon"):
        folder = app_data_dir()
        folder.mkdir(parents=True, exist_ok=True)
        try:
            _crash_log = open(folder / "crash.log", "a", encoding="utf-8")
            faulthandler.enable(file=_crash_log, all_threads=True)
        except OSError:
            _crash_log = None
    if command == "gui":
        handler: logging.Handler = logging.handlers.RotatingFileHandler(
            app_data_dir() / "monitor.log", maxBytes=2_000_000, backupCount=2, encoding="utf-8"
        )
    else:
        handler = logging.StreamHandler()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", handlers=[handler])
    logging.getLogger("httpx").setLevel(logging.WARNING)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="suya",
        description="Antarctic ocean temperature, salinity and air temperature monitor",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--lang", choices=["ko", "en"], help="interface language (default: saved choice or system locale)")
    sub = parser.add_subparsers(dest="command")

    gui = sub.add_parser("gui", help="open the program window and start collecting (default)")
    gui.add_argument("--no-collect", action="store_true", help="only show stored data")
    gui.add_argument("--sources", help="collect only these sources (comma separated)")
    gui.add_argument("--snapshot", help="save the window to this PNG and exit")
    gui.add_argument("--snapshot-after", type=float, default=8.0, help="seconds to wait before saving")

    daemon = sub.add_parser("daemon", help="collect continuously without a window")
    daemon.add_argument("--sources", help="collect only these sources (comma separated)")

    collect = sub.add_parser("collect", help="collect every source once")
    collect.add_argument("--sources", help="collect only these sources (comma separated)")

    export = sub.add_parser("export", help="export stored data to CSV")
    export.add_argument("what", choices=["measurements", "argo", "grid", "ions", "argo-ions", "grid-ions"])
    export.add_argument("--out", required=True)
    export.add_argument("--source")
    export.add_argument("--variable")
    export.add_argument("--since")
    export.add_argument(
        "--layer", help="layer for grid and grid-ions, e.g. hycom_salt_0, oisst_sst (grid-ions takes salinity layers)"
    )

    ions = sub.add_parser("ions", help="convert a practical salinity to seawater ion amounts (derived, not measured)")
    ions.add_argument("salinity", type=float, help="practical salinity, e.g. 34.5")
    ions.add_argument("--temperature", type=float, help="water temperature in °C: adds density at 1 atm and mmol/L")
    ions.add_argument("--depth", type=float, help="depth in m: adds the Southern Ocean salinity range check")
    ions.add_argument("--json", action="store_true", help="print the result as JSON")

    sync = sub.add_parser("excel-sync", help="write the monthly Excel workbooks now")
    sync.add_argument("--db")
    sync.add_argument("--dir")
    sync.add_argument("--month", help="only this month, YYYY-MM")
    sync.add_argument("--all", action="store_true", help="rewrite every month")
    sync.add_argument("--result", help=argparse.SUPPRESS)

    sub.add_parser("sources", help="list data sources")

    self_test = sub.add_parser("self-test", help="check that the installed program can start")
    self_test.add_argument("--out")

    args, _unknown = parser.parse_known_args(argv)
    command = args.command or "gui"
    _configure_logging(command)
    set_language(args.lang or default_language())

    if command == "collect":
        sys.exit(1 if asyncio.run(_collect_once(_resolve_sources(args.sources))) else 0)
    if command == "daemon":
        from .instance import InstanceLock

        lock = InstanceLock(load_settings().db_path.parent)
        if not lock.acquire():
            print(tr("SUYA가 이미 실행 중입니다. 창이 보이지 않으면 Dock이나 작업 표시줄을 확인하세요."), file=sys.stderr)
            sys.exit(1)
        try:
            asyncio.run(_daemon(_resolve_sources(args.sources)))
        finally:
            lock.release()
        return
    if command == "export":
        _export(args)
        return
    if command == "ions":
        _ions(args)
        return
    if command == "excel-sync":
        _excel_sync(args)
        return
    if command == "self-test":
        _self_test(args)
        _exit(0)
    if command == "sources":
        for source in SOURCES:
            print(f"{source['id']:20s} {tr(source['name'])} | {tr(source['measures'])} | {tr(source['cadence'])}")
        return

    try:
        from .gui.app import run_gui
    except ImportError:
        if gui_available():
            raise
        print(tr("화면 구성 요소가 설치되지 않았습니다. pip install \"suya[gui]\" 로 설치하거나 suya daemon 으로 창 없이 수집하세요"), file=sys.stderr)
        sys.exit(2)

    code = run_gui(
        collect=not getattr(args, "no_collect", False),
        sources=_resolve_sources(getattr(args, "sources", None)),
        snapshot=getattr(args, "snapshot", None),
        snapshot_after=getattr(args, "snapshot_after", 8.0),
        forced_language=args.lang,
    )
    _exit(code)
