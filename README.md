# BrandGuard

Brand compliance review for public websites and all their assets: page text, hidden text,
metadata, images, PDFs, Office files, video and audio. The first target is checking that
**"Pfizer"** is spelled correctly everywhere on `www.pfizer.com`.

See [docs/DESIGN.md](docs/DESIGN.md) for the full design.

> **Status: Phase 0, build step 1 (project skeleton).** The app starts, the UI shell works, and
> a self-test run proves the web server → job queue → worker → database → live progress loop.
> Sites, crawling, extraction, rules and findings come in the next steps.

## Run it on Windows

Requirements: Windows 10/11, Python 3.11 or 3.12. No admin rights, Docker or Node.js needed.

```powershell
# from the repository folder
py -m venv .venv
.venv\Scripts\activate
pip install -e .

brandguard setup     # creates %USERPROFILE%\BrandGuard\ (database, job queue, data folder)
brandguard start     # starts the web server + worker and opens http://localhost:8080
```

Press **Ctrl+C** in the terminal to stop. Open **Runs → Run self-test** to check everything works.

On macOS/Linux the same commands work with `python3 -m venv .venv` and `source .venv/bin/activate`.

### Commands

| Command | What it does |
|---|---|
| `brandguard setup` | Creates the home folder, SQLite database and job queue |
| `brandguard start [--port 8080] [--no-browser]` | Starts the web server and the background worker |
| `brandguard worker` | Runs only the background worker (for debugging) |
| `brandguard version` | Prints the version |

Set `BRANDGUARD_HOME` to keep data somewhere other than `%USERPROFILE%\BrandGuard`.

## Project layout

```
brandguard/
  cli.py            setup / start / worker / version
  api/              FastAPI app and routes (REST + Server-Sent Events)
  core/             paths, SQLite database, models, settings
  jobs/             Huey queue (SQLite file), tasks, worker process
  web/              UI: plain HTML + ES-module JS with Vue 3 (no build step)
    vendor/         third-party JS, vendored by scripts/vendor.py
scripts/vendor.py   downloads pinned frontend libraries from the npm registry (integrity-checked)
tests/
docs/DESIGN.md
```

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check . && ruff format --check .
```

API docs are at `http://localhost:8080/api/docs` while the app is running.
