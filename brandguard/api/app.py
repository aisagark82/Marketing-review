from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from brandguard import __version__
from brandguard.api.routes import runs, settings, sites, system

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def create_app() -> FastAPI:
    app = FastAPI(title="BrandGuard", version=__version__, docs_url="/api/docs")
    for module in (system, runs, sites, settings):
        app.include_router(module.router, prefix="/api")
    # Mounted last so /api routes take precedence; serves index.html at "/".
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app
