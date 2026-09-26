# BrandGuard

Brand compliance review for public websites and all their assets: page text, hidden text,
metadata, images, PDFs, Office files, video and audio. The first target is checking that
**"Pfizer"** is spelled correctly everywhere on `www.pfizer.com`.

See [docs/DESIGN.md](docs/DESIGN.md) for the full design.

> **Status: Phase 0, build step 6 (Gemini).** Sites are crawled with **Crawlee** or **Crawl4AI**;
> page, PDF and (optionally) image text is checked against the **"Pfizer" spelling rule**, and
> **Gemini** reviews the possible misspellings. Findings, evidence and dashboards show the results.
> Testing on Windows and measuring (step 7) comes next.

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

### Findings, evidence and the dashboards

- **Findings**: every problem in a crawl, filterable by status, type, where in the page
  (visible / hidden / metadata), web page or PDF, severity, text source, and whether it's
  **new** or **still there** since the previous crawl (fixed ones are counted). **Export CSV**
  opens in Excel with Japanese and Chinese text intact.
- **Evidence** (click a finding): the page screenshot with the spot boxed, the PDF page with
  the line boxed, or, for hidden text and metadata, the saved HTML with the word highlighted.
- **Compliance**: the score (100 minus 10 per high-severity violation per page or PDF,
  averaged; hidden text and metadata count fully), the share of clean pages, breakdowns and
  the lowest-scoring pages.
- **Overview**: the latest results and **Crawlee vs Crawl4AI** side by side (pages, files,
  text found, violations, time, memory, CPU, and pages only one of them reached).

### Gemini

**Settings → Gemini**: paste your Google AI Studio API key (kept in Windows Credential Manager;
never shown again), pick the model (`gemini-2.5-flash` by default) and **Test connection**. Then:

- **Review possible misspellings** (on by default): after each crawl or re-evaluation, Gemini
  looks at every "to review" finding in context and **confirms** it (it becomes a violation),
  **dismisses** it (e.g. a surname like "Pfitzer"), or leaves it **unsure**. Its reason and a
  suggested fix appear on the finding; **Ask Gemini now** reviews a single finding.
- **Read text in images** (off by default): the crawl also downloads the site's images (same
  pace and rules, visible images first, up to the limit you set) and Gemini transcribes their
  text exactly, so misspellings in banners and logos are found. SVG text is read without Gemini.
- **Limits and cost**: requests per minute and per day (Gemini steps pause, the crawl doesn't
  fail), and a usage table with an estimated cost. Answers are cached, so re-evaluating a crawl
  doesn't pay twice.

Only public page text and images are sent to Gemini.

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
  reporting.py      scores, findings with changes between crawls, evidence, crawler comparison
  ai/               Gemini: config.py (settings, API key), llm.py (the one adapter: limits,
                    retries, logging, cache), prompts.py, judge.py (reviews), images.py
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
