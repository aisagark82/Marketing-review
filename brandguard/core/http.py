"""Outbound HTTP for crawling: honest User-Agent, OS certificate store, size-capped reads."""

import ssl
from dataclasses import dataclass, field

import httpx
import truststore

from brandguard import __version__

DEFAULT_TIMEOUT_S = 20.0


def user_agent(independent: bool, contact_email: str = "") -> str:
    purpose = "independent brand-compliance test" if independent else "brand-compliance review"
    contact = f"; contact: {contact_email}" if contact_email else ""
    return f"BrandGuard/{__version__} ({purpose}{contact})"


# Product token matched against robots.txt `User-agent:` lines.
ROBOTS_TOKEN = "BrandGuard"


def make_http_client(agent: str, timeout: float = DEFAULT_TIMEOUT_S) -> httpx.Client:
    # truststore uses the OS certificate store (Windows, macOS, Linux), so corporate
    # TLS-inspecting proxies trusted by the laptop also work here.
    return httpx.Client(
        headers={"User-Agent": agent, "Accept-Language": "en"},
        timeout=timeout,
        follow_redirects=True,
        verify=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT),
    )


@dataclass
class Fetched:
    url: str
    final_url: str
    status_code: int | None = None
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    redirects: list[str] = field(default_factory=list)
    truncated: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status_code is not None and 200 <= self.status_code < 300

    def text(self) -> str:
        return self.body.decode(_charset(self.headers), errors="replace")


def _charset(headers: dict[str, str]) -> str:
    for part in headers.get("content-type", "").split(";"):
        key, _, value = part.strip().partition("=")
        if key.lower() == "charset" and value:
            return value.strip('"')
    return "utf-8"


def fetch(client: httpx.Client, url: str, max_bytes: int) -> Fetched:
    """GET a URL, reading at most max_bytes of the body. Network errors are returned, not raised."""
    try:
        with client.stream("GET", url) as response:
            body = bytearray()
            truncated = False
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > max_bytes:
                    del body[max_bytes:]
                    truncated = True
                    break
            return Fetched(
                url=url,
                final_url=str(response.url),
                status_code=response.status_code,
                headers={k.lower(): v for k, v in response.headers.items()},
                body=bytes(body),
                redirects=[str(r.url) for r in response.history],
                truncated=truncated,
            )
    except httpx.HTTPError as exc:
        return Fetched(url=url, final_url=url, error=f"{type(exc).__name__}: {exc}")
