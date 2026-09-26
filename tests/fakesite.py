"""A fictional website served through httpx.MockTransport, shaped like a large corporate site:
robots.txt with a Crawl-delay, a sitemap index with gzipped children, a bare-domain redirect,
and a terms-of-use link on the home page.
"""

import gzip

import httpx

ORIGIN = "https://www.example-pharma.com"
HOME = f"{ORIGIN}/"

ROBOTS = f"""# example robots.txt
User-agent: *
Disallow: /search
Allow: /search/help
Crawl-delay: 5

User-agent: BadBot
User-agent: OtherBot
Disallow: /

Sitemap: {ORIGIN}/sitemap_index.xml
"""

HOME_HTML = """<!doctype html><html><head><title> Example Pharma | Home </title></head><body>
<a href="/about">About us</a>
<a href="/news">News</a>
<a href="/news#latest">Latest news</a>
<a href="/legal/terms-of-use">Terms of Use</a>
<a href="/privacy">Privacy</a>
<a href="https://social.example.net/examplepharma">Follow us</a>
</body></html>"""


def _urlset(urls: list[str]) -> bytes:
    items = "".join(f"<url><loc>{u}</loc></url>" for u in urls)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{items}</urlset>'
    ).encode()


def _index(urls: list[str]) -> bytes:
    items = "".join(f"<sitemap><loc>{u}</loc></sitemap>" for u in urls)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{items}</sitemapindex>'
    ).encode()


Route = tuple[int, dict[str, str], bytes]


def routes() -> dict[str, Route]:
    xml = {"content-type": "application/xml"}
    return {
        f"{ORIGIN}/robots.txt": (200, {"content-type": "text/plain"}, ROBOTS.encode()),
        HOME: (200, {"content-type": "text/html; charset=utf-8"}, HOME_HTML.encode()),
        "https://example-pharma.com/": (301, {"location": HOME}, b""),
        f"{ORIGIN}/sitemap_index.xml": (
            200,
            xml,
            _index(
                [
                    f"{ORIGIN}/sitemap-pages.xml",
                    f"{ORIGIN}/sitemap-news.xml.gz",
                    f"{ORIGIN}/sitemap-products.xml",
                ]
            ),
        ),
        f"{ORIGIN}/sitemap-pages.xml": (
            200,
            xml,
            _urlset(
                [f"{ORIGIN}/", f"{ORIGIN}/about", f"{ORIGIN}/science", f"{ORIGIN}/careers"]
                + ["https://investors.example-pharma.com/reports"]
            ),
        ),
        f"{ORIGIN}/sitemap-news.xml.gz": (
            200,
            {"content-type": "application/x-gzip"},
            gzip.compress(_urlset([f"{ORIGIN}/news/{i}" for i in range(3)])),
        ),
    }


class FakeSite:
    """Serves `routes` and records every requested URL; unknown URLs return 404."""

    def __init__(self, table: dict[str, Route] | None = None):
        self.routes = routes() if table is None else table
        self.requested: list[str] = []
        self.user_agents: set[str] = set()

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requested.append(url)
        self.user_agents.add(request.headers.get("user-agent", ""))
        route = self.routes.get(url)
        if route is None:
            return httpx.Response(404, text="not found")
        status, headers, body = route
        if isinstance(body, Exception):
            raise body
        return httpx.Response(status, headers=headers, content=body)

    def client(self, agent: str = "BrandGuard/test") -> httpx.Client:
        return httpx.Client(
            transport=httpx.MockTransport(self.handler),
            headers={"User-Agent": agent},
            follow_redirects=True,
        )
