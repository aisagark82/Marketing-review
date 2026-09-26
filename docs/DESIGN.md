# Brand Compliance Review Platform — Solution Design (Draft v0.6)

> Status: **design iteration**, no code yet. Open questions are in [§13](#13-open-questions).
> Working name: **BrandGuard**.

## 0. Decision log

| # | Decision | Since |
|---|---|---|
| D1 | Open-source and free tools first; Python backend; HTML + JS frontend | v0.1 |
| D2 | AI = **Google Gemini**, **AI Studio API key**, **paid tier**, default model **`gemini-2.5-flash`**; all settings managed in the UI | v0.4 |
| D3 | Crawler = Playwright-based. **Crawlee vs Crawl4AI** are compared in the Phase 0 spike and the winner is picked on results. Browser MCP is not used for crawling | v0.4 |
| D4 | Multiple brands can be configured; start with **one brand: Pfizer** | v0.4 |
| D5 | **First target: `www.pfizer.com`**. First check: the brand name is spelled **"Pfizer"** everywhere | v0.4 |
| D6 | Multilingual (EN, ZH-Hans/Hant, JA, ES, DE, …), including **official non-Latin brand forms** | v0.3 |
| D7 | Every source of text is in scope: visible, **hidden**, **metadata**, images, documents, video (on-screen and spoken), audio. Visual brand rules (logo, color, font) come later | v0.3 |
| D8 | Hidden and metadata text **counts at full weight** in the compliance score | v0.4 |
| D9 | Out of scope: third-party embeds and anything behind a login | v0.2 |
| D10 | No triage workflow; read-only results with **evaluation and compliance dashboards** | v0.2 |
| D11 | Runs on **one laptop as a plain Python app, no Docker** | v0.4 |
| D12 | Because of D11: **SQLite** instead of PostgreSQL, **Huey (SQLite)** instead of a Postgres queue, frontend served by the Python server **with no Node build** | v0.4 |
| D13 | **All caps "PFIZER" is allowed**. Only "Pfizer" and "PFIZER" are correct casings | v0.5 |
| D14 | **No sub-brand rules for now**. Only the word "Pfizer" itself is checked; compounds pass if that part is spelled correctly | v0.5 |
| D15 | Scope is **`www.pfizer.com` only**, with no other subdomains | v0.5 |
| D16 | Target laptop OS is **Windows** | v0.5 |
| D17 | This is an **independent test**, not done for the site owner. Crawling is conservative and preceded by a pre-flight check of robots.txt and the terms of use (§8.1) | v0.5 |
| D18 | Laptop has **16 GB RAM**. Profiles are sized for it (§5.10) | v0.6 |
| D19 | **Phase 0 includes a working UI** (a thin slice, §12.1), not only CSV output | v0.6 |
| D20 | Wrong source text hidden by CSS styling (typed "pfizer", shown as "Pfizer") is a **normal violation** at full severity | v0.6 |
| D21 | Pre-flight check (built in step 2): stricter than RFC 9309 in two places. A robots.txt answering 401/403 counts as "disallow everything", and once a site shows bot protection no further requests are made. Changing a site's start URLs, domains, sitemap or robots setting withdraws the acknowledgement | step 2 |
| D22 | Crawling (built in step 3). Both libraries needed changes to meet §8.1. **Crawlee** spoofs browser fingerprints and adds a made-up User-Agent and `sec-ch-ua` headers by default (both switched off), and keeps unvisited URLs from a stopped crawl in a process-wide queue (each crawl now gets its own). **Crawl4AI** always starts Chromium with `--disable-blink-features=AutomationControlled` (hides automation) and `--ignore-certificate-errors`, and sets its own User-Agent. BrandGuard launches Chromium itself with plain flags and connects Crawl4AI over CDP. Scope, robots.txt, pacing, retries (none) and block handling are BrandGuard's own and identical for both | step 3 |
| D24 | PDFs (built in step 4) are read with **pypdfium2** (PDFium, Apache/BSD, a few MB) instead of Docling, which pulls in PyTorch and CUDA libraries (several GB). Text with page positions, properties and bookmarks are extracted; pages without a text layer are flagged for OCR. Docling stays an option for Office files and scans later | step 4 |
| D25 | Brand-name findings: wrong letter case, known misspelling and split name are **violations**; near-misses (1 letter off) are **"to review"** (for Gemini in step 6); another market's local name uses the rule's cross-market severity. Findings record the rule version, and re-evaluating a crawl replaces its findings without crawling again | step 4 |
| D26 | Findings and dashboards (built in step 5): a finding is "new" or "still there" by comparing page URL, text source, text and match with the site's previous evaluated crawl; findings no longer present are counted as fixed. Evidence: screenshot box for visible text, PDF page box (PDF.js), saved-HTML snippet for hidden text and metadata. PDF.js is pinned to 5.4.x because 5.5+ needs a JavaScript feature only the newest browsers have | step 5 |
| D27 | Gemini (built in step 6): two fixed workflows, not an agent. **Review**: "to review" findings go in batches of 20 with their context; verdicts confirm (violation at the rule's severity), dismiss, or leave unsure; answers are cached per candidate. **Image text** (opt-in): downloaded images are transcribed verbatim (SVG read in code; icons skipped). One adapter logs every call, paces requests, enforces a daily limit (steps pause, runs don't fail) and retries 429/5xx. Temperature 0, thinking off for Flash models, relaxed safety filters (public pharma copy). The API key lives in the OS keychain, with the local database as a fallback where there is none | step 6 |
| D23 | Text from attributes (`alt`, `title`, `aria-label`, `placeholder`) is classed as **metadata**, since it isn't displayed as page text. Off-site redirects and iframes are stopped in the browser (via CDP), so no third-party page is loaded | step 3 |

> **Note on D12:** in v0.3 you agreed to drop Redis in favour of a Postgres queue.
> Without Docker, PostgreSQL would be a separate install and service on the laptop, so the same goal
> (fewest moving parts) is better met with **SQLite files** for both the data and the job queue.
> The code talks to the database through SQLAlchemy, so moving to PostgreSQL later is a settings change plus a migration.

---

## 1. Goal

For each configured **brand**, crawl its configured public websites and extract every asset and every piece of
text in any form. Evaluate all of it against the brand's rules (first rule: **brand name spelling**,
in every language), and present the results in compliance dashboards with evidence.

**First milestone:** crawl `www.pfizer.com` and report every place where the brand name is not
spelled exactly **"Pfizer"**, across page text, hidden text, metadata, images, PDFs and other documents.

---

## 2. High-level architecture (single laptop, no Docker)

```mermaid
flowchart LR
  subgraph Browser["Browser → http://localhost:8080"]
    UI[BrandGuard UI<br/>HTML + JS · Vue, no build]
  end

  subgraph Laptop["One command: brandguard start"]
    API[FastAPI server<br/>REST · SSE · static UI · scheduler]
    W[Worker process pool<br/>Huey consumer]
    DB[(SQLite<br/>brandguard.db)]
    QDB[(SQLite<br/>queue.db)]
    FS[(Data folder<br/>assets, screenshots, frames)]
  end

  UI <-->|REST + SSE| API
  API --> DB
  API -->|enqueue| QDB
  QDB --> W
  W --> DB
  W --> FS
  W -->|Playwright + Chromium| WEB[(www.pfizer.com)]
  W -->|rule judge, vision fallback| G[Gemini API<br/>gemini-2.5-flash]
  API -->|assistant| G
```

### Pipeline (per run, per site)

```
Discover ─▶ Fetch & render ─▶ Classify ─▶ Extract ─▶ Detect language ─▶ Normalize ─▶ Evaluate ─▶ Score
(sitemap,    (DOM, screenshot,  (MIME,      (every     (per segment)       (per script)    (rules;     (dashboards,
 links)       same-domain        scanned?)  text                                            Gemini on   run diff)
              files)                        source)                                         ambiguous)
```

Each step is keyed by **content hash**, so re-runs only reprocess changed assets, and a rule change
re-evaluates the stored text without crawling again.

---

## 3. Configuration model

Everything is edited in the UI and can be imported/exported as **YAML** (plus a CSV/XLSX glossary for brand terms).
Each run records the config version it used.

```
Brand ─1:N─ Site
  ├──1:N─ BrandTerm (canonical form + per-locale/per-script forms)
  └──1:N─ RuleSet ─1:N─ Rule
```

### 3.1 Brand: Pfizer (starting config)

```yaml
brands:
  - id: pfizer
    name: Pfizer
    locales: [en]                        # add ja, zh-Hans, zh-Hant, es, de ... when country sites are added
    terms:
      - id: pfizer
        canonical: "Pfizer"
        allowed_casings: ["Pfizer", "PFIZER"]   # D13: title case and all caps are both correct
                                                 # "pfizer", "PFizer", "pFizer", "PfIzEr" ... are violations
        attached_forms: ok               # "Pfizer's", "Pfizer-BioNTech", "PfizerPro": pass if the "Pfizer" part is correct (D14)
        disallowed: ["Phizer", "Pfiser", "Pfzer", "Pifzer", "Pfizzer", "Fizer", "P-fizer"]
        fuzzy: { max_edit_distance: 1, min_similarity: 0.83 }   # short word → tight threshold to avoid false hits
        exceptions: [urls, emails, social_handles, hashtags, file_names, stock_ticker]  # pfizer.com, @pfizer, #pfizer, PFE
        locales:                         # official non-Latin forms, used once country sites are in scope
          ja:      { approved: ["Pfizer", "PFIZER", "ファイザー"], disallowed: ["ファイザ", "ファイザ―"] }  # dash look-alike vs long-vowel mark
          zh-Hans: { approved: ["Pfizer", "PFIZER", "辉瑞"],      disallowed: ["輝瑞"] }                 # Traditional form on a Simplified page
          zh-Hant: { approved: ["Pfizer", "PFIZER", "輝瑞"],      disallowed: ["辉瑞"] }
    rule_sets: [brand-core]
```

### 3.2 Site: pfizer.com

```yaml
sites:
  - id: pfizer-com
    brand: pfizer
    start_urls: [https://www.pfizer.com/]
    use_sitemap: true
    allowed_domains: [www.pfizer.com]               # D15: no other subdomains (pfizer.com redirects to www)
    subdomain_assets: skip_and_log                  # files embedded on www pages but hosted on other *.pfizer.com
                                                    # hosts are listed as "skipped – subdomain" (switchable later)
    exclude: ["\\?.*sort=", "/search\\?"]
    max_pages: 500                  # Phase 0 cap; raise later
    render_js: auto
    expand_interactive: true        # open accordions, tabs, carousels, "read more"
    politeness:                     # D17: independent test → conservative defaults
      rps: 0.5                      # 1 request every 2 s (or the site's Crawl-delay if higher)
      respect_robots: true
      max_concurrency: 1
      stop_on_blocks: true          # pause the run after repeated 403/429/challenge pages
      user_agent: "BrandGuard/0.1 (independent brand-compliance test; contact: <your email>)"
    preflight_acknowledged: false   # set in the UI after reviewing robots.txt and terms of use (§8.1)
    schedule: null                  # manual runs to start with
```

### 3.3 Rule

```yaml
rule_sets:
  - id: brand-core
    rules:
      - id: BRAND-NAME-001
        type: brand_name
        terms: [pfizer]
        severity: high
        applies_to: [all]           # every asset type
        text_sources: [all]         # visible, hidden, metadata, image OCR, document, video, audio
        trademark: { require_symbol_on_first_use: false }   # off for Pfizer to start
        cross_locale: warning       # see §5.3
        llm_review: on_ambiguous    # off | on_ambiguous | always   (gemini-2.5-flash)
```

Rule types are plugins. `brand_name` is built first. Later: `forbidden_terms`, `required_text`,
`tone_of_voice` (LLM), `logo`, `color_palette`, `typography`.

---

## 4. Core data model

```
Brand ─ Site ─ Run ─ Asset ─ Segment ─ Finding ─ Rule
                       └─ parent_asset (image inside PDF, frame inside video, …)
```

| Entity | Key fields |
|---|---|
| **Asset** | url, page_url, mime, sha256, fetched_at, file_path, parent_asset_id, detected_languages, status (`ok` / `skipped` / `failed` + reason) |
| **Segment** | asset_id, text, **text_source**, **visibility** (`visible` / `hidden` / `metadata` / `spoken`), **render_transform** (e.g. CSS `uppercase`), language, script, locator, extractor + version, confidence |
| **Locator** | HTML: CSS selector + screenshot bbox · PDF/Office: page/slide + bbox · Image: bbox · Video: timestamp (+ bbox) · Audio: timestamp |
| **Finding** | rule_id/version, segment_id, matched_text, expected, severity, confidence, `new / persisting / fixed` vs previous run, `pending AI review` flag |

**Visibility** is set by the extractor:
- `visible`: rendered on screen, including content revealed by opening accordions, tabs and carousels
- `hidden`: in the DOM but not rendered (`display:none`, `visibility:hidden`, off-screen, zero size), `<noscript>`, hidden inputs
- `metadata`: `<title>`, `<meta>`, OpenGraph/Twitter, JSON-LD, document properties, EXIF/XMP/IPTC, ID3, PDF bookmarks and annotations
- `spoken`: speech-to-text from video or audio

**Source text vs rendered text:** a heading stored as "pfizer" but styled with CSS `text-transform: capitalize/uppercase`
*shows* as "Pfizer"/"PFIZER". We check the **source text** and record the transform. Since all caps is allowed (D13),
this mainly matters for the reverse case: source text that is wrong but hidden by styling is reported as a **normal violation** (D20), with a note that the page displays it correctly.

No workflow state on findings. A **suppression list** (a rule exception or an allow-listed URL) is the only way
to silence a known false positive, and it is itself config.

---

## 5. Component design & tech options

Legend: ✅ recommended · ◻ alternative · ⚠ caveat

### 5.1 Crawling

**Chrome DevTools MCP / Playwright MCP** let an LLM drive a browser one step at a time. That's great for
interactive checks, but for bulk crawling it is slow, costly (each step is a Gemini call) and not repeatable.
Decision: crawl with **Playwright directly**; use a live-browser tool only inside the AI assistant (§5.4).

**Phase 0 spike: compare both crawlers on pfizer.com**

| | **Crawlee for Python** (Apache-2.0) | **Crawl4AI** (Apache-2.0) |
|---|---|---|
| Model | Crawling framework: request queue, retries, sessions, Playwright + HTTP crawlers | AI-oriented crawler: Playwright, deep-crawl strategies, Markdown output, media/link extraction |
| Strength | Full control of the page: run our own DOM walker, expand accordions, capture every file | Least code to get content; good defaults |
| Risk | More code to write | Its Markdown drops attributes, hidden text and metadata, so we still need our own DOM extraction hook |

**Scorecard** (measured on the same 500 pfizer.com pages): pages discovered · files found (PDF, images, Office, video) ·
text sources captured (visible / hidden / metadata) · runtime and CPU/RAM on the laptop · errors and blocks ·
lines of glue code · Windows install friction.
The **DOM extractor** (§5.2) is written once and plugged into both, so the comparison is fair.

**Crawler behaviour**
- Discovers pages from the sitemap and links, within `allowed_domains` only (`www.pfizer.com`). Links and files on other `*.pfizer.com` subdomains are logged as *skipped – subdomain*. Third-party iframes, embeds and assets on other domains are logged as *skipped – out of scope*
- Runs a **pre-flight check** before the first crawl (§8.1), then respects robots.txt (including `Crawl-delay`), crawls one page at a time, and identifies itself clearly in the User-Agent. **If the site's bot protection blocks the crawler, we report it and stop. No evasion techniques are used**
- Pages behind a login or returning 401/403 are skipped and logged
- For each page: DOM snapshot, full-page screenshot, and every linked or embedded same-domain file

### 5.2 Extraction — every kind of text

| Asset | Text sources extracted |
|---|---|
| **Web page** | visible text (including CSS `::before/::after`), headings, buttons, labels, placeholders, `alt`, `title`, `aria-*`, `<title>`, `<meta>`, OpenGraph/Twitter, JSON-LD, inline SVG text, canvas/CSS-background text (OCR of the screenshot), hidden text, content revealed by expanding accordions/tabs/carousels, link text; URLs and file names are logged for information only |
| **Image** | OCR text, SVG `<text>`, EXIF/XMP/IPTC (title, description, copyright) |
| **PDF** | text layer with positions; OCR for scanned or image-only pages; text in embedded images; properties (title, author, subject, keywords); bookmarks, annotations, form labels |
| **Word / PowerPoint / Excel** | body, headers/footers, tables, speaker notes, comments, slide titles, sheet names, cells, embedded images (OCR), properties |
| **Video** (same-domain) | spoken transcript, on-screen text (key-frame OCR), caption tracks (VTT/SRT), container metadata |
| **Audio** | spoken transcript, ID3 tags |

**Tools, chosen so everything installs with `pip`** (no Docker, few system dependencies):

| Need | ✅ Recommended (pip-installable) | Notes |
|---|---|---|
| Browser | **Playwright** + `playwright install chromium` | Chromium is downloaded into the user profile; no admin rights |
| Web page DOM text | Our own Playwright DOM walker + `trafilatura` (main-content flag) | |
| PDF, DOCX, PPTX, XLSX | **Docling** (MIT) | ◻ pypdfium2 / pdfplumber fast path for plain digital PDFs |
| OCR | **RapidOCR** (ONNX, PaddleOCR models, Apache-2.0): pure pip, multilingual incl. CJK | ◻ Tesseract only if the user installs it (optional) |
| Image metadata | Pillow + `python-xmp-toolkit`/Pillow XMP | no exiftool needed |
| Audio metadata | `mutagen` | |
| ffmpeg / ffprobe | **`static-ffmpeg`** pip package (downloads the binaries on first use) | no system install |
| Video key frames | PySceneDetect + `imagehash` | |
| Speech-to-text | **faster-whisper** (MIT), model `small` int8 on CPU | ◻ Gemini audio (§5.4) |
| Legacy `.doc/.ppt/.xls` | LibreOffice headless **if installed**, otherwise logged as *skipped – converter missing* | rare on modern sites |

### 5.3 Multilingual handling

| Concern | Approach |
|---|---|
| Language detection | **lingua-py**, per segment; URL locale hint as a starting guess |
| OCR for CJK | RapidOCR multilingual models (Chinese, Japanese, Latin) |
| Speech-to-text | Whisper is multilingual; brand terms (Pfizer, ファイザー, 辉瑞) passed as hotwords/prompt |
| Normalization | Unicode **NFKC** (full-width `Ｐｆｉｚｅｒ` → `Pfizer`), zero-width and soft-hyphen removal, Japanese long-vowel mark `ー` vs dash look-alikes, accents for ES/DE |
| Matching | Latin: tokens + **RapidFuzz**. CJK: direct character match (no spaces), optional jieba / SudachiPy for context |
| Simplified vs Traditional | **OpenCC** to detect 辉瑞 vs 輝瑞 on the wrong page |
| **Cross-locale check** | *What it means:* a brand form meant for one market appearing on another market's page, e.g. the Chinese name 辉瑞 on a Japanese page that should say ファイザー. Default: **warning (low severity)**. It doesn't apply to the English-only first run |

### 5.4 AI layer — Gemini (AI Studio key, paid tier)

Official **`google-genai` Python SDK** behind an `LLMProvider` interface (other providers stay possible later).
The **paid tier** gives higher rate limits, and Google does not use paid-tier prompts to improve its products.

| Use | Default model | When |
|---|---|---|
| **Rule judge** | `gemini-2.5-flash` | Only `ambiguous` findings (fuzzy near-misses, low OCR confidence); structured JSON `{verdict, reason, suggested_fix}`; cached by `(rule_version, segment_hash)` |
| **Vision/audio fallback** | `gemini-2.5-flash` | When local OCR/speech-to-text confidence is below a threshold, or for stylized text (e.g. the Pfizer wordmark in banners). Per asset type: `local` / `local + gemini fallback` (default) / `gemini` |
| **AI assistant** | `gemini-2.5-flash` | Chat with tool calling |
| **Embeddings** (Phase 2) | `gemini-embedding-001` | Semantic search for the assistant |

**Assistant tools** (Gemini function calling, each backed by our API): `search_findings`, `get_compliance_stats`,
`get_asset_evidence`, `explain_finding`, `draft_rule` / `draft_brand_term` (goes to the sandbox for the user to confirm),
`compare_runs`, `summarize_run`, and **`browse_live_page`**. This last one is a small built-in Python Playwright tool
that opens one page live. It needs no Node.js and no MCP server; Playwright MCP can still be connected later if Node is available.

**Gemini settings page**

| Setting | Default / notes |
|---|---|
| API key | Pasted once; stored in **Windows Credential Manager** (via `keyring`); UI shows `••••1234` only; replace/remove buttons |
| Model per task | `gemini-2.5-flash` for judge, fallback and assistant; dropdowns filled from the live model list. A warning appears if a configured model disappears from the list (Google retires model versions over time) |
| Generation params | temperature 0.1 for judge, 0.4 for assistant; max output tokens; thinking budget (2.5 Flash supports it; low for judge); JSON mode for judge |
| Safety settings | Relaxed defaults (pharma terms such as dosage and side effects can trip filters) |
| Rate limits | **Paid-tier preset**, editable to match the quota page in AI Studio; limiter with backoff on `429`/`503` |
| Budget | Monthly spend cap; LLM steps pause (findings become `pending AI review`) instead of failing |
| Test connection | Sample prompt in EN/JA/ZH; shows latency, model and tokens |
| Usage panel | Calls, tokens and estimated cost per day, run, task and model |

### 5.5 Rule engine

1. **Deterministic tier** (every segment): normalize → exact match against allowed and disallowed forms →
   fuzzy near-miss (Latin) / character match (CJK) → exceptions (URLs, emails, @handles, #hashtags, file names, ticker) →
   result `violation` / `ok` / `ambiguous`, with confidence.
   Examples for Pfizer: `Phizer` ❌ · `pfizer` in a sentence ❌ · `PFizer` ❌ · `PFIZER` ✅ · `pfizer.com` ⏭ exception · `Pfizer's` ✅ · `Pfizer-BioNTech` ✅ · `Pfzier` ⚠ fuzzy → judge.
   **Spoken** segments are checked for mention only, not spelling. Low-confidence OCR is marked `ambiguous`.
2. **Gemini tier:** only for `ambiguous` segments.
3. **Rule sandbox (UI):** paste text, upload a file or enter one URL, then see the results before saving a rule version.

### 5.6 Jobs & scheduling (no Redis, no Postgres)

- ✅ **Huey** (MIT) with its **SQLite** storage: task queue, retries and priorities in a local file. The worker runs as a child process of the app
- **Windows note:** Huey runs with **thread workers**; CPU-heavy steps (OCR, Docling, Whisper) are sent to a Python `ProcessPoolExecutor`, which uses Windows' *spawn* start method. This avoids fork-based process workers, which don't work on Windows. It gets checked in Phase 0
- Queues: `crawl`, `extract`, `media`, `rules`, `llm`, each with its own concurrency (set by the performance profile)
- **Resumable:** jobs are stored on disk. After sleep, crash or restart, unfinished jobs continue, and idempotent steps make re-runs safe
- **Run controls:** pause, resume and cancel from the UI
- **Schedules** (later; manual runs first): **APScheduler** inside the app with a SQLite job store; missed runs while the laptop was off run once at next start (*coalesce*)
- Progress goes to the UI over **SSE**
- ◻ Alternative: no queue library at all, just a `jobs` table plus a Python process pool. Simpler, but we'd write retries and resume ourselves

### 5.7 Storage

- ✅ **SQLite** (WAL mode) via SQLAlchemy 2 + Alembic: config, runs, assets, segments, findings; **FTS5** for full-text search; **sqlite-vec** for vectors (Phase 2)
- ✅ **Data folder** `~/BrandGuard/data/` for downloaded files, screenshots, key frames, evidence crops
- Retention settings plus a disk-usage widget (e.g. keep raw videos only for the latest run)

### 5.8 Backend

- **FastAPI** + Pydantic v2 + Uvicorn; serves the API, SSE and the UI's static files from the same port
- **One command:** `brandguard start` starts the web server, the worker and the scheduler, and opens `http://localhost:8080` in the browser. Ctrl+C stops everything
- Local single-user mode: listens on `127.0.0.1` only; optional password

### 5.9 Frontend — HTML + JS, no build step

Vue 3 is a **JavaScript library**: you write HTML templates, CSS and plain JS, and the browser runs normal HTML/JS.
Because there is no Docker or Node on the laptop, we use Vue **without a build step**:

- `index.html` + ES-module `.js` files (one file per screen/component), served directly by FastAPI
- Libraries **vendored** into `frontend/vendor/` (downloaded once, committed), so it works offline without a CDN:
  **Vue 3** (ESM build), **PrimeVue** (tables, forms, tabs, dialogs), **Apache ECharts** (dashboards),
  **PDF.js** (PDF evidence), **Video.js** (seek to timestamp), **CodeMirror** prebuilt bundle (YAML editor), **markdown-it** (assistant)
- No `npm`, no bundler; edit a `.js` file and refresh the browser
- ◻ If the UI grows large later, the same Vue code can move to a Vite build with little change

### 5.10 Installation & running on a Windows laptop

```
Requirements: Windows 10/11 (64-bit) · Python 3.11 or 3.12 (python.org installer or `uv`) · no admin rights needed
              ~4 GB free disk (Chromium, OCR/Whisper/Docling models) · 16 GB RAM (target laptop)
Install:      PowerShell →  uv tool install brandguard     (or: py -m pip install brandguard)
              brandguard setup      → downloads Chromium (%LOCALAPPDATA%\ms-playwright), OCR & Whisper models,
                                      ffmpeg; creates %USERPROFILE%\BrandGuard\
Run:          brandguard start      → opens http://localhost:8080
Optional:     setup creates a Start-menu / desktop shortcut "BrandGuard" that runs the same command
```

**Windows-specific choices**

| Topic | Approach |
|---|---|
| Data folder | `%USERPROFILE%\BrandGuard\` (`data\`, `brandguard.db`, `queue.db`, `logs\`) |
| Long paths | Files are stored under short hash names (e.g. `data\ab\ab12…ef.pdf`) to stay below the 260-character path limit; the original URL is kept in the database |
| API key | Windows **Credential Manager** via `keyring` |
| CJK fonts | Built-in Windows fonts (Microsoft YaHei, Yu Gothic, …) cover Chinese and Japanese screenshots, so nothing to install |
| ffmpeg | `static-ffmpeg` downloads Windows binaries on first use |
| Antivirus | Windows Defender scans every downloaded PDF/Office file, which slows extraction. The docs explain how to optionally exclude the data folder |
| Sleep / shutdown | Jobs resume on the next `brandguard start`; a warning is shown if a run is started on battery power |
| Legacy Office files | Converted only if LibreOffice for Windows is installed; otherwise *skipped – converter missing* |
| Firewall | Server binds to `127.0.0.1`, so Windows Firewall doesn't prompt |

| Performance profile | Browser pages | OCR/Docling workers | Speech-to-text | Use when |
|---|---|---|---|---|
| **Light** | 1 | 1 | Whisper `small`, 1 worker | you are working on the laptop |
| **Balanced** (default) | 1 | 2 | Whisper `small` | normal; peak ≈ 5–6 GB RAM |
| **Max** | 1 | 4 (or CPU cores − 2, whichever is lower) | Whisper `medium` | overnight; peak ≈ 9–10 GB RAM |

The RAM figures are estimates for a 16 GB laptop (Chromium ≈ 1 GB, each Docling worker ≈ 1.5–2 GB, Whisper `medium` ≈ 2 GB). They get measured in Phase 0 and the defaults adjusted.

(Browser pages stay at **1** for pfizer.com because of the conservative crawl policy; profiles only change local processing.)

Backup: *Settings → Export* creates a zip with the config YAML, the SQLite database and the data folder. *Import* restores it.

---

## 6. UX design

### 6.1 Navigation

```
┌────────────────────────────────────────────────────────────────────────────┐
│ ◆ BrandGuard  Overview  Compliance  Explorer  Runs  Sites  Rules  Settings [🤖]│
└────────────────────────────────────────────────────────────────────────────┘
```
A brand switcher appears once there is more than one brand.

### 6.2 Screens

| Screen | Purpose |
|---|---|
| **Overview** | Compliance score for Pfizer, assets evaluated, violations by severity, new vs fixed since last run, coverage (crawled / skipped / failed / blocked), latest runs |
| **Compliance dashboard** | Score trend; breakdowns by site, **visibility** (visible / hidden / metadata / spoken), **asset type**, **text source**, language, rule; top offending pages and files; **most frequent wrong spellings** (e.g. "pfizer" ×41, "Phizer" ×3). Every chart drills down |
| **Findings list** | Read-only grid with facets (site, visibility, asset type, text source, language, severity, confidence, new/persisting/fixed, pending AI review); CSV/XLSX export |
| **Evidence viewer** | Left: evidence in context (page screenshot with highlight, PDF page with box, image with box, video at timestamp, or **HTML/metadata snippet with DOM path** for hidden and metadata text). Right: found text, expected "Pfizer", rule, confidence, Gemini explanation, live URL |
| **Explorer** | Site → page → files; every extracted segment by source and visibility; skipped items and why |
| **Runs** | Start run (full / incremental / single URL / re-evaluate only); live progress per pipeline step; pause/resume/cancel; errors and logs |
| **Sites** | Add-site wizard: URL → **pre-flight check** (robots.txt rules, Crawl-delay, sitemap, link to terms of use, acknowledgement tick box) → preview pages and file mix → scope → brand |
| **Rules** | Brand terms (allowed forms, sub-brands, disallowed misspellings, exceptions, per-locale forms), glossary import/export, rule form + YAML toggle, **sandbox** |
| **Settings** | Gemini (§5.4), performance profile, OCR/speech-to-text options, politeness, suppression list, retention and disk usage, export/import |
| **Assistant drawer** | Gemini chat aware of the current screen, e.g. *"Which PDFs spell Pfizer in lowercase?"* or *"Open this page live and check the footer"* |

### 6.3 Compliance scoring

- **Finding weight** = severity (high = 10, medium = 3, low = 1) × visibility factor. **All factors = 1.0** (visible, hidden, metadata, spoken count equally), editable in Settings
- **Asset score** = 100 − Σ finding weights (floor 0)
- **Site / brand score** = average asset score, shown with **% of assets with no high-severity violation**
- `pending AI review` findings are excluded until resolved and shown as a separate count

---

## 7. Pfizer — expected findings (illustrative)

| Source | Visibility | Text | Result |
|---|---|---|---|
| Page body | visible | "…at Phizer we believe…" | ❌ misspelling |
| `<meta name="description">` | metadata | "pfizer is a global…" | ❌ lowercase in running text |
| JSON-LD `"name"` | metadata | "Pfizer Inc." | ✅ allowed form |
| `display:none` promo block | hidden | "PFizer Oncology" | ❌ casing |
| Hero banner text | visible | "PFIZER" | ✅ all caps allowed |
| Accordion (expanded by crawler) | visible | "Pfizer's pipeline" | ✅ |
| Link `href` | — | `https://www.pfizer.com/news` | ⏭ exception (URL) |
| Footer | visible | "@pfizer" / "#Pfizer" | ⏭ exception (handle / hashtag) |
| Heading with CSS capitalize | visible | source "pfizer" → shows "Pfizer" | ❌ normal violation (note: displayed correctly by styling) |
| PDF annual report p.12 | visible | "Pfizer-BioNTech" | ✅ "Pfizer" part correct |
| Image hosted on another `*.pfizer.com` subdomain | — | — | ⏭ skipped (subdomain, D15) |
| PDF properties → Author | metadata | "pfizer inc" | ❌ casing |
| Banner image OCR (0.61) | visible | "Pfzer" | ⚠ ambiguous → Gemini vision reads "Pfizer" → ✅ |
| Video 00:35 spoken | spoken | "at pfizer we…" | ℹ mention (spelling not checked) |
| YouTube iframe | — | — | ⏭ skipped (third-party) |

---

## 8. Non-functional

### 8.1 Responsible crawling for an independent test (D17)

Because we are not the site owner, the crawler is deliberately conservative:

| Measure | Default |
|---|---|
| **Pre-flight check** (before the first run of any site) | Fetches and shows `robots.txt` (disallowed paths, `Crawl-delay`, sitemaps), links to the site's terms of use, and requires the user to tick *"I have reviewed the robots.txt and terms of use"*. Runs can't start until this is done |
| robots.txt | Always respected; can't be turned off for sites marked *independent* |
| Rate | 1 request every 2 seconds (or the site's `Crawl-delay` if longer), one page at a time, files fetched with the same limit |
| Volume | Page cap (500 in Phase 0); full-site runs at most weekly |
| Identity | Honest User-Agent naming the tool and a contact email; no browser fingerprint spoofing |
| Blocks | After repeated 403/429 responses or a bot-challenge page, the run **pauses** and reports it. No CAPTCHA solving, proxy rotation or stealth plugins |
| Incremental | Later runs use `ETag`/`Last-Modified` so unchanged files aren't downloaded again |
| Use of content | Downloaded files stay on the laptop for analysis only; retention settings delete raw files after the review |
| Results | Findings about a third-party site are for internal use; the UI and reports carry a note that this is an independent, automated test and may contain false positives |

> Before the first run, review pfizer.com's robots.txt and terms of use yourself (the pre-flight screen links to both).
> If the terms prohibit automated access, don't run the crawl. Use a site you own or have permission for instead.

### 8.2 Other

- **Incremental:** ETag/Last-Modified + sha256; rule changes re-evaluate without re-crawling
- **Audit:** every finding records run, config version, rule version, extractor and model version
- **Safety:** sandboxed Chromium, file-size and decompression limits, Office macros never executed
- **Cost control:** Gemini only for ambiguous cases and fallbacks, caching, rate limiter, budget cap
- **Laptop-friendly:** CPU-only, performance profiles, resumable jobs, local-only network binding, retention limits

## 9. License watch-list

| Component | Issue | Mitigation |
|---|---|---|
| PyMuPDF | AGPL | Docling / pypdfium2 / pdfplumber |
| Firecrawl (self-hosted) | AGPL | Crawlee / Crawl4AI |
| Ultralytics YOLO | AGPL | Gemini vision / OpenCLIP for future logo rules |
| FFmpeg (via static-ffmpeg) | LGPL/GPL by build | Run as an external binary, not linked |
| Gemini API | Commercial paid service | Rate limiter + budget cap |

## 10. Tech stack summary

| Layer | Choice |
|---|---|
| Frontend | HTML + ES-module JS, Vue 3 (no build, vendored), PrimeVue, ECharts, PDF.js, Video.js, CodeMirror |
| Server | FastAPI + Uvicorn (API, SSE, static UI), one `brandguard start` command |
| Jobs | Huey (SQLite storage) + APScheduler |
| Data | SQLite (WAL, FTS5, sqlite-vec later) + local data folder |
| Crawl | Playwright (Chromium) with **Crawlee or Crawl4AI**, decided in Phase 0 |
| Extract | DOM walker, trafilatura, Docling, RapidOCR, Pillow, mutagen, static-ffmpeg, PySceneDetect, faster-whisper |
| Language | lingua-py, OpenCC, RapidFuzz, jieba / SudachiPy (optional) |
| AI | `google-genai`, AI Studio key (paid tier), `gemini-2.5-flash`; key stored in OS keychain |

## 11. Proposed repository layout (later)

```
brandguard/
  cli.py                 setup / start / export / import
  api/  core/  models/
  pipeline/{crawl/{crawlee_adapter,crawl4ai_adapter,dom_walker}, extract, lang, rules, score}
  ai/{gemini.py, ratelimit.py, assistant.py, tools.py}
  jobs/                  huey tasks, scheduler
frontend/
  index.html  app.js  screens/*.js  components/*.js  vendor/
config/examples/         pfizer.brand.yaml, pfizer-com.site.yaml, brand-core.rules.yaml
docs/
```

## 12. Roadmap

| Phase | Scope |
|---|---|
| **0 – Spike (pfizer.com)** | Pre-flight check of robots.txt and terms of use; up to 500 pages of www.pfizer.com at 1 request / 2 s; **Crawlee vs Crawl4AI** side by side with the shared DOM walker; web-page text (visible, hidden, metadata) + PDFs; "Pfizer" spelling rule; **thin-slice UI** (§12.1) plus CSV export; measure laptop CPU/RAM/runtime; confirm the Windows install (Playwright, Docling, RapidOCR, faster-whisper, Huey + process pool) |
| **1 – MVP** | UI (Overview, Compliance, Findings, Evidence, Runs, Sites, Rules, Settings); images + OCR; Office via Docling; Gemini settings + rule judge + vision fallback; CSV/XLSX export; full-site crawl |
| **2 – Media & Assistant** | Same-domain video/audio; AI assistant with tools and live-page check; schedules; run diffs; more Pfizer sites and languages (ja, zh, es, de) |
| **3 – Visual brand** | Logo, color and typography rules; tone-of-voice rules |

---

### 12.1 Phase 0 UI slice

The spike ships a small but real UI (same no-build Vue setup as the MVP), so the full flow can be tried from the browser:

| Screen | Phase 0 scope | Full version later (MVP) |
|---|---|---|
| **Sites** | pfizer.com site config form, **pre-flight check** screen (robots.txt, terms link, acknowledgement) | add-site wizard, multiple sites |
| **Rules** | Pfizer brand term form (allowed casings, disallowed spellings, exceptions) + read-only YAML view + **sandbox** (paste text → results) | full rule builder, glossary import, versions |
| **Runs** | Start run (choose crawler: **Crawlee** or **Crawl4AI**), live progress per step, pause/cancel, log tail, blocked-page alerts | schedules, incremental and re-evaluate modes |
| **Findings** | Filterable table (visibility, asset type, text source, severity, crawler) + CSV export | XLSX, saved filters |
| **Evidence viewer** | Page screenshot with highlight box; PDF page with box (PDF.js); HTML/metadata snippet for hidden and metadata text | images, video, audio |
| **Overview** | Score, counts by visibility and asset type, top wrong spellings, **crawler comparison card** (pages, files, segments, runtime, RAM, errors for Crawlee vs Crawl4AI) | full compliance dashboard, trends |
| **Settings** | Gemini key (Credential Manager) + model (`gemini-2.5-flash`) + test connection, performance profile | budget, usage panel, retention, export/import |

Not in Phase 0: AI assistant, video/audio, Office files, schedules, multiple brands.

## 13. Open questions

Resolved in v0.6: 16 GB RAM · UI in Phase 0 · styled-over wrong text is a normal violation.

Still open (does not block starting):
1. **Contact email in the User-Agent:** optional. Left as a Settings field, blank by default.

**The design is complete enough to start Phase 0.** Proposed first build steps, once you give the go-ahead:
1. Project skeleton: `brandguard setup/start` CLI, FastAPI + SQLite + Huey, vendored Vue UI shell
2. Pre-flight check + site config for pfizer.com
3. Shared DOM walker (visible / hidden / metadata segments) with Crawlee and Crawl4AI adapters
4. PDF extraction (Docling / pypdfium2), "Pfizer" rule + sandbox
5. Findings table, evidence viewer, Overview with crawler comparison
6. Gemini settings + rule judge for ambiguous findings
7. Test on Windows, measure, pick the crawler
