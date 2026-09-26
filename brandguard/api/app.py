from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from brandguard import __version__
from brandguard.api.routes import crawl, runs, settings, sites, system
from brandguard.core.paths import get_paths

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def create_app() -> FastAPI:
    app = FastAPI(title="BrandGuard", version=__version__, docs_url="/api/docs")
    for module in (system, runs, sites, crawl, settings):
        app.include_router(module.router, prefix="/api")
    # Screenshots and page snapshots from the data folder (read-only), for the evidence views.
    paths = get_paths()
    paths.ensure()
    app.mount("/files", StaticFiles(directory=paths.data_dir), name="files")
    # Mounted last so /api routes take precedence; serves index.html at "/".
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app
