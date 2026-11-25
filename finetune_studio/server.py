"""Fine-Tune Studio — local web app. Standard library only.

    python server.py            # http://127.0.0.1:8765
    python server.py --port 9000 --host 0.0.0.0
"""

import argparse
import io
import json
import mimetypes
import sys
import traceback
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from engine.codegen import full_config, generate  # noqa: E402
from engine.dataset import profile  # noqa: E402
from engine.estimator import estimate  # noqa: E402
from engine.recommender import recommend  # noqa: E402
from engine.schema import public_schema  # noqa: E402
from engine.validator import validate  # noqa: E402

STATIC = ROOT / "static"
MAX_BODY = 50 * 1024 * 1024


def analyze(cfg):
    cfg = full_config(cfg)
    return dict(estimate=estimate(cfg), issues=validate(cfg))


def export_zip(cfg):
    files = generate(cfg)
    name = full_config(cfg).get("project_name") or "finetune"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for fn, content in files.items():
            info = zipfile.ZipInfo(f"{name}/{fn}")
            info.external_attr = (0o755 if fn.endswith(".sh") else 0o644) << 16
            z.writestr(info, content)
    return buf.getvalue(), name


ROUTES = {
    "/api/analyze": lambda b: analyze(b.get("config", {})),
    "/api/recommend": lambda b: recommend(full_config(b.get("config", {}))),
    "/api/generate": lambda b: generate(b.get("config", {})),
    "/api/profile": lambda b: profile(b.get("name", "data.jsonl"), b.get("text", "")),
}


class Handler(BaseHTTPRequestHandler):
    server_version = "FineTuneStudio/1.0"

    def log_message(self, fmt, *args):
        if "/api/" in (args[0] if args else ""):
            sys.stderr.write("%s\n" % (fmt % args))

    def _send(self, code, body, ctype="application/json", headers=None):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/schema":
            return self._send(200, public_schema())
        if path in ("/", "/index.html"):
            path = "/index.html"
        f = (STATIC / path.lstrip("/")).resolve()
        if STATIC not in f.parents or not f.is_file():
            return self._send(404, {"error": "not found"})
        ctype = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
        self._send(200, f.read_bytes(), ctype + ("; charset=utf-8" if ctype.startswith("text") or "javascript" in ctype else ""))

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            return self._send(413, {"error": "payload too large (50 MB max) — upload a sample"})
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
            if path == "/api/export.zip":
                data, name = export_zip(body.get("config", {}))
                return self._send(200, data, "application/zip", {"Content-Disposition": f'attachment; filename="{name}.zip"'})
            if path not in ROUTES:
                return self._send(404, {"error": "unknown endpoint"})
            return self._send(200, ROUTES[path](body))
        except (ValueError, KeyError, TypeError) as e:
            return self._send(400, {"error": str(e)})
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            return self._send(500, {"error": f"{type(e).__name__}: {e}"})


def main():
    ap = argparse.ArgumentParser(description="Fine-Tune Studio")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    url = f"http://{a.host}:{a.port}"
    print(f"Fine-Tune Studio running at {url}  (Ctrl+C to stop)")
    if not a.no_browser:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
