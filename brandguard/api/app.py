import mimetypes
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from brandguard import __version__
from brandguard.api.routes import ai, crawl, findings, rules, runs, settings, sites, system
from brandguard.core.paths import get_paths

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


# Static files get their type from Python's mimetypes, which on Windows reads the registry,
# where .js is sometimes registered as text/plain. Browsers refuse to run ES modules served
# that way, so the UI would stay blank; pin the types the UI needs.
for _type, _ext in (
    ("text/javascript", ".js"),
    ("text/javascript", ".mjs"),
    ("text/css", ".css"),
    ("image/svg+xml", ".svg"),
    ("application/pdf", ".pdf"),
):
    mimetypes.add_type(_type, _ext)


def create_app() -> FastAPI:
    app = FastAPI(title="BrandGuard", version=__version__, docs_url="/api/docs")
    for module in (system, runs, sites, crawl, rules, findings, settings, ai):
        app.include_router(module.router, prefix="/api")
    # Screenshots and page snapshots from the data folder (read-only), for the evidence views.
    paths = get_paths()
    paths.ensure()
    app.mount("/files", StaticFiles(directory=paths.data_dir), name="files")
    # Mounted last so /api routes take precedence; serves index.html at "/".
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app
