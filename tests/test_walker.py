import asyncio
from pathlib import Path

from brandguard.pipeline.crawl.capture import VIEWPORT, capture_page
from tests.browser import async_playwright, launch

PAGE = (Path(__file__).parent / "fixtures" / "walker_page.html").read_text()
BASE = "https://www.example-pharma.test/science"


async def _capture(expand=True, javascript=True):
    async with async_playwright() as p:
        browser = await launch(p)
        context = await browser.new_context(viewport=VIEWPORT, java_script_enabled=javascript)
        page = await context.new_page()
        # Serve the fixture at a realistic URL without any network access.
        await page.route(
            "**/*",
            lambda route: (
                route.fulfill(body=PAGE, content_type="text/html")
                if route.request.resource_type == "document"
                else route.abort()
            ),
        )
        await page.goto(BASE)
        result = await capture_page(page, BASE, expand=expand, javascript=javascript)
        await browser.close()
        return result


def capture(**kwargs):
    return asyncio.run(_capture(**kwargs))


def find(walk, text):
    matches = [s for s in walk["segments"] if s["text"] == text]
    assert matches, f"no segment {text!r}; have: {[s['text'] for s in walk['segments']]}"
    return matches[0]


def test_visible_text_is_grouped_per_block():
    walk = capture().walk
    intro = find(walk, "Welcome to Example Pharma, where science matters.")
    assert intro["visibility"] == "visible"
    assert intro["source"] == "text"
    assert intro["locator"]["selector"] == "#intro"
    assert len(intro["locator"]["bbox"]) == 4
    assert find(walk, "First line Second line")["visibility"] == "visible"


def test_source_text_is_kept_and_css_transform_recorded():
    heading = find(capture().walk, "pfizer science")
    assert heading["source"] == "heading"
    assert heading["transform"] == "uppercase"


def test_hidden_text_is_classified_hidden():
    walk = capture().walk
    for text in ["Hidden promo text", "Screen reader only text", "Off screen text"]:
        assert find(walk, text)["visibility"] == "hidden", text
        assert find(walk, text)["locator"]["bbox"] is None
    assert find(walk, "Please enable JavaScript for Example Pharma")["source"] == "noscript"
    assert find(walk, "hidden campaign value")["source"] == "hidden_input"


def test_collapsed_content_is_opened_and_counts_as_visible():
    result = capture()
    assert result.expanded == 2  # the <details> and the aria-expanded button
    assert find(result.walk, "Detail revealed text")["visibility"] == "visible"
    assert find(result.walk, "Accordion answer text")["visibility"] == "visible"


def test_without_expanding_collapsed_content_is_hidden():
    walk = capture(expand=False).walk
    assert find(walk, "Accordion answer text")["visibility"] == "hidden"


def test_attributes_and_generated_content():
    walk = capture().walk
    assert find(walk, "Example Pharma logo")["source"] == "attr:alt"
    assert find(walk, "Logo title")["source"] == "attr:title"
    assert find(walk, "Main navigation")["source"] == "attr:aria-label"
    assert find(walk, "Search Example Pharma")["source"] == "attr:placeholder"
    assert find(walk, "Example Pharma logo")["visibility"] == "metadata"
    assert find(walk, "Go")["source"] == "button"
    assert find(walk, "New from Example Pharma")["source"] == "css_content"
    assert find(walk, "SVG Example Pharma")["source"] == "svg_text"
    assert find(walk, "Shadow DOM text")["visibility"] == "visible"


def test_metadata():
    walk = capture().walk
    assert find(walk, "Example Pharma | Science")["source"] == "title"
    assert find(walk, "Pfizer-style description with Phizer typo")["source"] == "meta:description"
    assert find(walk, "Example Pharma on OpenGraph")["source"] == "meta:og:title"
    org = find(walk, "Example Pharma Inc.")
    assert (org["source"], org["locator"]["path"]) == ("json_ld", "name")
    assert find(walk, "Jane Doe")["locator"]["path"] == "founder.name"
    texts = [s["text"] for s in walk["segments"]]
    assert "width=device-width" not in texts  # technical meta tags are skipped
    assert "https://www.example-pharma.test/og.png" not in texts  # so are bare URLs
    assert walk["language"] == "en"


def test_links_and_files():
    walk = capture().walk
    links = {link["url"] for link in walk["links"]}
    assert "https://www.example-pharma.test/about" in links
    assert "https://social.example.net/pharma" in links
    assert not any(url.startswith("mailto:") for url in links)
    files = {r["url"]: r["kind"] for r in walk["resources"]}
    assert files["https://www.example-pharma.test/files/annual-report.pdf"] == "pdf"
    assert files["https://cdn.example-pharma.test/brochure.pdf"] == "pdf"
    assert files["https://www.example-pharma.test/img/logo.png"] == "image"
    assert files["https://www.example-pharma.test/img/banner.jpg"] == "image"
    assert files["https://www.example-pharma.test/media/intro.mp4"] == "video"
    assert files["https://www.example-pharma.test/media/intro.vtt"] == "subtitle"
    assert files["https://video.example.net/embed/123"] == "frame"


def test_screenshot_and_html_are_captured():
    result = capture()
    assert result.screenshot[:2] == b"\xff\xd8"  # JPEG
    assert "<title>Example Pharma | Science</title>" in result.html
    assert result.error is None


def test_page_without_javascript_still_yields_text():
    result = capture(javascript=False)
    assert result.error is None
    assert find(result.walk, "Welcome to Example Pharma, where science matters.")
