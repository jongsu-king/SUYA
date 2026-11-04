"""Command line entry point. gui is the default command."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import logging.handlers
import os
import signal
import sys
from pathlib import Path

from . import __version__, exporter
from .catalog import SOURCES
from .collectors import JOBS
from .collectors.base import Context
from .config import app_data_dir, load_settings
from .db import Store
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
    else:
        if not args.layer:
            raise SystemExit("--layer is required for grid, e.g. --layer hycom_salt_0")
        try:
            count = exporter.export_grid(store, args.layer, out)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
    store.close()
    print(f"{out}: {count} rows")


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


def _self_test(args: argparse.Namespace) -> None:
    """Check that an installed copy can load everything it needs. Used by the installer build."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import tempfile

    from PySide6.QtWidgets import QApplication

    from . import excel
    from .config import Settings
    from .gui.app import MainWindow
    from .gui.backend import Backend

    lines = []
    with tempfile.TemporaryDirectory() as temp:
        app = QApplication.instance() or QApplication(sys.argv[:1])
        settings = Settings(db_path=Path(temp) / "test.db", excel_dir=Path(temp) / "excel")
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


def _configure_logging(command: str) -> None:
    if command == "gui":
        folder = app_data_dir()
        folder.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = logging.handlers.RotatingFileHandler(
            folder / "monitor.log", maxBytes=2_000_000, backupCount=2, encoding="utf-8"
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
    export.add_argument("what", choices=["measurements", "argo", "grid"])
    export.add_argument("--out", required=True)
    export.add_argument("--source")
    export.add_argument("--variable")
    export.add_argument("--since")
    export.add_argument("--layer", help="layer for grid, e.g. hycom_salt_0, oisst_sst")

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
        asyncio.run(_daemon(_resolve_sources(args.sources)))
        return
    if command == "export":
        _export(args)
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

    from .gui.app import run_gui

    code = run_gui(
        collect=not getattr(args, "no_collect", False),
        sources=_resolve_sources(getattr(args, "sources", None)),
        snapshot=getattr(args, "snapshot", None),
        snapshot_after=getattr(args, "snapshot_after", 8.0),
        forced_language=args.lang,
    )
    _exit(code)
