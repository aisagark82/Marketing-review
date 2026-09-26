"""Command line: `brandguard setup | start | worker | version`."""

import argparse
import logging
import socket
import subprocess
import sys
import threading
import time
import webbrowser

from brandguard import __version__
from brandguard.core.paths import get_paths
from brandguard.core.settings import PROFILES

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080

log = logging.getLogger("brandguard")


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    # Alembic logs every plugin and step at INFO; core/migrate.py reports upgrades itself.
    # httpx logs every request, and the crawler libraries log their own progress.
    for noisy in ("alembic", "httpx", "crawlee", "crawl4ai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _initialize() -> None:
    """Create the home folder, the database and the queue file."""
    from brandguard.core.db import get_engine
    from brandguard.jobs.queue import get_queue

    get_paths().ensure()
    get_engine()
    get_queue()


def _queue_threads() -> int:
    from brandguard.core.db import session_scope
    from brandguard.core.settings import load_settings

    with session_scope() as session:
        profile = load_settings(session).performance_profile
    return PROFILES[profile]["queue_threads"]


def _install_chromium() -> bool:
    print("Downloading Chromium for crawling (one time, ~150 MB)...")
    result = subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"])
    return result.returncode == 0


def cmd_setup(args: argparse.Namespace) -> int:
    _initialize()
    if not args.skip_browser and not _install_chromium():
        print("Chromium could not be installed. Crawling needs it; run `brandguard setup` again.")
        return 1
    paths = get_paths()
    print(f"BrandGuard {__version__} is set up.")
    print(f"  Home folder : {paths.home}")
    print(f"  Database    : {paths.db_file}")
    print(f"  Job queue   : {paths.queue_file}")
    print(f"  Data folder : {paths.data_dir}")
    print("Run `brandguard start` to open the app.")
    return 0


def _port_is_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def _open_browser_when_ready(server, url: str) -> None:
    for _ in range(100):
        if server.started:
            webbrowser.open(url)
            return
        time.sleep(0.1)


def cmd_start(args: argparse.Namespace) -> int:
    import uvicorn

    from brandguard.api.app import create_app

    if args.host not in ("127.0.0.1", "localhost"):
        log.warning("Listening on %s makes BrandGuard reachable from other machines", args.host)
    if not _port_is_free(args.host, args.port):
        print(f"Port {args.port} is already in use. Try `brandguard start --port 8081`.")
        return 1

    _initialize()
    threads = args.threads or _queue_threads()
    worker = subprocess.Popen(
        [sys.executable, "-m", "brandguard", "worker", "--threads", str(threads)]
    )
    url = f"http://{args.host}:{args.port}"
    server = uvicorn.Server(uvicorn.Config(create_app(), host=args.host, port=args.port))
    if not args.no_browser:
        threading.Thread(target=_open_browser_when_ready, args=(server, url), daemon=True).start()
    print(f"BrandGuard {__version__} running at {url}  (Ctrl+C to stop)")
    try:
        server.run()
    finally:
        worker.terminate()
        try:
            worker.wait(timeout=10)
        except subprocess.TimeoutExpired:
            worker.kill()
    return 0


def cmd_worker(args: argparse.Namespace) -> int:
    from brandguard.jobs.worker import run_worker

    _initialize()
    run_worker(threads=args.threads or _queue_threads())
    return 0


def cmd_version(_args: argparse.Namespace) -> int:
    print(__version__)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="brandguard", description="Brand compliance review")
    sub = parser.add_subparsers(dest="command", required=True)

    setup = sub.add_parser("setup", help="Create the home folder, database and job queue")
    setup.add_argument(
        "--skip-browser", action="store_true", help="Don't download Chromium (already installed)"
    )
    setup.set_defaults(func=cmd_setup)

    start = sub.add_parser("start", help="Start the web app and the worker")
    start.add_argument("--host", default=DEFAULT_HOST)
    start.add_argument("--port", type=int, default=DEFAULT_PORT)
    start.add_argument("--threads", type=int, help="Worker threads (default: from profile)")
    start.add_argument("--no-browser", action="store_true", help="Don't open the browser")
    start.set_defaults(func=cmd_start)

    worker = sub.add_parser("worker", help="Run only the background worker")
    worker.add_argument("--threads", type=int, help="Worker threads (default: from profile)")
    worker.set_defaults(func=cmd_worker)

    sub.add_parser("version", help="Show the version").set_defaults(func=cmd_version)
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    args = build_parser().parse_args(argv)
    return args.func(args)
