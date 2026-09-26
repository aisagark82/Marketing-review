# BrandGuard

Brand compliance review for public websites and all their assets: page text, hidden text,
metadata, images, PDFs, Office files, video and audio. The first target is checking that
**"Pfizer"** is spelled correctly everywhere on `www.pfizer.com`.

See [docs/DESIGN.md](docs/DESIGN.md) for the full design.

> **Status: Phase 0, build step 4 (PDFs and the brand-name rule).** Sites are crawled with
> **Crawlee** or **Crawl4AI**; page text (visible, hidden, metadata) and PDF text are checked
> against the **"Pfizer" spelling rule**, which you can edit and test in **Rules**. The findings
> list and evidence viewer (step 5) and Gemini (step 6) come next.

## Run it on Windows

Requirements: Windows 10/11, Python 3.11 or 3.12. No admin rights, Docker or Node.js needed.

```powershell
# from the repository folder
py -m venv .venv
.venv\Scripts\activate
pip install -e .

brandguard setup     # creates %USERPROFILE%\BrandGuard\ and downloads Chromium (~150 MB, once)
brandguard start     # starts the web server + worker and opens http://localhost:8080
```

Press **Ctrl+C** in the terminal to stop. Open **Runs → Run self-test** to check everything works.

On macOS/Linux the same commands work with `python3 -m venv .venv` and `source .venv/bin/activate`.

### Before the first crawl: the pre-flight check

Open **Sites → pfizer.com → Run pre-flight check**. It makes a few polite requests (robots.txt,
the home page, up to three sitemap files) and reports:

- whether robots.txt allows BrandGuard, and the wait between requests the crawler will use
- whether the start page loads, redirects out of scope, or is behind bot protection
- how many pages the sitemap lists, with samples
- links to the site's terms of use

Read robots.txt and the terms of use yourself, then tick the box and **Acknowledge**. A site can
only be crawled once it shows **Ready to crawl**. Changing its start URLs or allowed domains
withdraws the acknowledgement until the check is run again.

### Crawling

Once a site shows **Ready to crawl**, open its **Crawl** tab, pick **Crawlee** or **Crawl4AI** and
click **Start crawl**. Both use the same text extraction, so their results can be compared. The
run page shows live progress, then statistics (pages, files, text segments, time, memory) and every
page's text next to its screenshot. Pick a text to see where it is on the page.

What the crawler does, whichever library runs it:

- requests one page at a time, waiting the configured interval (or robots.txt's Crawl-delay if longer)
- identifies itself honestly: no fake User-Agent, browser fingerprints or evasion flags
- stays on the allowed domains; links elsewhere are listed as "not crawled" with the reason, and
  redirects or iframes leading off-site are stopped in the browser
- opens accordions and `<details>` before reading, and records text hidden by CSS as **hidden**
- stops after three refusals in a row (403/429/challenge pages) and reports the run as **blocked**

After the pages, the crawl downloads the site's PDFs (same pace and rules, up to 200 per crawl,
50 MB each) and reads their text, properties and bookmarks. Pages without a text layer (scans)
are listed as needing OCR. Finally every piece of text is checked against the brand rules, and
the run page shows the findings.

### The brand-name rule

**Rules → Brand name: Pfizer** holds the settings from the design: correct spelling "Pfizer",
allowed letter cases (Pfizer, PFIZER), known misspellings, near-miss detection (e.g. "Pfzier"),
what isn't checked (web addresses, emails, domains, file names, @handles, #hashtags), and
local-script names per market (ファイザー, 辉瑞, 輝瑞). Every save is a new version.

- **Test** checks pasted text or an uploaded PDF with the form's settings, before you save
- **YAML** shows the rule as a file you can download
- **Re-evaluate with current rules** (on a crawl's page) applies the latest version without crawling again

What gets reported: wrong letter case (`pfizer`, `PFizer`), known misspellings (`Phizer`), the
name split in two (`Pfi zer`), possible misspellings to review (`Pfzier`), and another market's
local name on a page.

Upgrading from an earlier step keeps your data: the database is migrated automatically on start.

### Commands

| Command | What it does |
|---|---|
| `brandguard setup [--skip-browser]` | Creates the home folder, database and job queue; downloads Chromium |
| `brandguard start [--port 8080] [--no-browser]` | Starts the web server and the background worker |
| `brandguard worker` | Runs only the background worker (for debugging) |
| `brandguard version` | Prints the version |

Set `BRANDGUARD_HOME` to keep data somewhere other than `%USERPROFILE%\BrandGuard`, and
`BRANDGUARD_CHROMIUM_PATH` to use a Chromium other than the one `setup` downloads.

## Project layout

```
brandguard/
  cli.py            setup / start / worker / version
  api/              FastAPI app and routes (REST + Server-Sent Events)
  core/             paths, SQLite database, models, migrations runner, settings, HTTP client
  migrations/       Alembic schema migrations (applied automatically at start-up)
  pipeline/         preflight.py; crawl/ (policy, discovery, walker.js, capture, recorder,
                    adapters for Crawlee and Crawl4AI, runner); files.py and extract/pdf.py
                    (PDFs); evaluate.py (findings)
  rules/            brand_name.py (the rule), defaults.py (Pfizer), service.py (versions, YAML)
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
