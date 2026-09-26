"""A tiny website served over real HTTP on 127.0.0.1, for end-to-end crawler tests."""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from tests.pdfs import make_pdf

REPORT_PDF = make_pdf(
    [["Example Pharma Annual Review", "At Phizer we believe in science."]],
    title="Example Pharma Review",
    author="Example Pharma",
)


def page(title: str, body: str) -> bytes:
    head = f"<!doctype html><html lang='en'><head><title>{title}</title></head>"
    return f"{head}<body>{body}</body></html>".encode()


class LocalSite:
    def __init__(self):
        self.requests: list[tuple[str, str]] = []  # (path, user agent)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.origin = f"http://127.0.0.1:{self.server.server_port}"
        self.routes = self._routes()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def _routes(self) -> dict[str, tuple[int, str, bytes]]:
        o = self.origin
        html = "text/html; charset=utf-8"
        return {
            "/robots.txt": (
                200,
                "text/plain",
                f"User-agent: *\nDisallow: /private\nSitemap: {o}/sitemap.xml\n".encode(),
            ),
            "/sitemap.xml": (
                200,
                "application/xml",
                (
                    '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                    f"<url><loc>{o}/</loc></url><url><loc>{o}/news</loc></url></urlset>"
                ).encode(),
            ),
            "/": (
                200,
                html,
                page(
                    "Home | Example Pharma",
                    """
                <h1>Welcome to Example Pharma</h1>
                <p>Our <b>science</b> story.</p>
                <div style="display:none">Hidden campaign for Phizer</div>
                <img src="/logo.png" alt="Example Pharma logo">
                <a href="/about">About</a> <a href="/private/area">Private</a>
                <a href="/missing">Broken</a> <a href="/files/report.pdf">Report</a>
                <a href="http://sub.127.0.0.1.nip.test/x">Subdomain</a>
                <a href="https://social.example.net/pharma">Social</a>
                <a href="/leave">Leaving</a>""",
                ),
            ),
            "/about": (200, html, page("About", "<p>About Example Pharma</p><a href='/'>Home</a>")),
            "/news": (200, html, page("News", "<p>News from Example Pharma</p>")),
            "/files/report.pdf": (200, "application/pdf", REPORT_PDF),
            "/logo.png": (
                200,
                "image/svg+xml",
                b"<svg xmlns='http://www.w3.org/2000/svg' width='10' height='10'/>",
            ),
            "/private/area": (200, html, page("Private", "<p>Should never be fetched</p>")),
            "/leave": (302, html, b""),
        }

    def _handler(self):
        site = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                site.requests.append((self.path, self.headers.get("User-Agent", "")))
                status, content_type, body = site.routes.get(
                    self.path, (404, "text/html", page("Not found", "<p>Not found</p>"))
                )
                self.send_response(status)
                if self.path == "/leave":
                    self.send_header("Location", "https://elsewhere.example.org/")
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        return Handler

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
