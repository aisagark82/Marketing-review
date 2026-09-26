"""A local stand-in for the Gemini REST API (generateContent, models.list).

The real google-genai SDK talks to it (via BRANDGUARD_GEMINI_BASE_URL), so request building,
response parsing and error handling are exercised end to end without network access.
"""

import base64
import hashlib
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from brandguard.ai.prompts import IMAGE_TEXT_SYSTEM, JUDGE_SYSTEM

# How the fake "model" decides candidates, by the word under review.
VERDICTS = {
    "Pfzier": ("misspelling", "Letters swapped in the company name.", "Pfizer"),
    "Pfitzer": ("not_brand", "A person's surname.", None),
}


class FakeGemini:
    def __init__(self):
        self.requests: list[dict] = []
        self.image_lines: dict[str, list[str]] = {}  # sha256 of image bytes -> lines
        self.fail_next: list[tuple[int, str]] = []  # (HTTP status, message) to return first
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()

    def calls(self, kind: str) -> list[dict]:
        return [r for r in self.requests if r["kind"] == kind]

    def _answer(self, body: dict) -> dict:
        system = body["systemInstruction"]["parts"][0]["text"]
        parts = body["contents"][0]["parts"]
        if system == JUDGE_SYSTEM:
            text = parts[0]["text"]
            verdicts = []
            for number, word in re.findall(
                r'<candidate id="(\d+)"[^>]*><word>([^<]+)</word>', text
            ):
                verdict, reason, suggestion = VERDICTS.get(word, ("unsure", "Not clear.", None))
                verdicts.append(
                    {
                        "id": int(number),
                        "verdict": verdict,
                        "reason": reason,
                        "suggestion": suggestion,
                    }
                )
            return {"verdicts": verdicts}
        if system == IMAGE_TEXT_SYSTEM:
            # The SDK sends proto field names in either spelling; the real API accepts both.
            inline = parts[0].get("inlineData") or parts[0]["inline_data"]
            encoded = inline["data"]  # URL-safe base64, possibly unpadded
            data = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
            return {"lines": self.image_lines.get(hashlib.sha256(data).hexdigest(), [])}
        return {"lines": ["Pfizer", "ファイザー", "辉瑞"]}  # the connection test

    def _handler(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def _send(self, status, payload):
                raw = json.dumps(payload, ensure_ascii=False).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                fake.requests.append({"kind": "list", "path": self.path})
                self._send(
                    200,
                    {
                        "models": [
                            {
                                "name": "models/gemini-2.5-flash",
                                "supportedGenerationMethods": ["generateContent", "countTokens"],
                            },
                            {
                                "name": "models/gemini-2.5-pro",
                                "supportedGenerationMethods": ["generateContent"],
                            },
                            {
                                "name": "models/text-embedding-004",
                                "supportedGenerationMethods": ["embedContent"],
                            },
                        ]
                    },
                )

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                model = re.search(r"models/([^:]+):generateContent", self.path).group(1)
                fake.requests.append(
                    {
                        "kind": "generate",
                        "model": model,
                        "body": body,
                        "key": self.headers.get("x-goog-api-key"),
                    }
                )
                if fake.fail_next:
                    status, message = fake.fail_next.pop(0)
                    self._send(
                        status, {"error": {"code": status, "message": message, "status": "ERROR"}}
                    )
                    return
                answer = json.dumps(fake._answer(body), ensure_ascii=False)
                self._send(
                    200,
                    {
                        "candidates": [
                            {
                                "content": {"role": "model", "parts": [{"text": answer}]},
                                "finishReason": "STOP",
                            }
                        ],
                        "usageMetadata": {
                            "promptTokenCount": 120,
                            "candidatesTokenCount": 30,
                            "totalTokenCount": 150,
                        },
                    },
                )

            def log_message(self, *args):
                pass

        return Handler
