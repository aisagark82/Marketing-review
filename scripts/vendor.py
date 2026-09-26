"""Download pinned frontend libraries into brandguard/web/vendor/.

The UI has no build step, so third-party JS is vendored (committed) and served
locally. Packages come from the npm registry tarball and are checked against
the registry's sha512 integrity hash. Run again after changing a version:

    python scripts/vendor.py
"""

import base64
import hashlib
import io
import json
import tarfile
import urllib.request
from pathlib import Path

VENDOR_DIR = Path(__file__).resolve().parent.parent / "brandguard" / "web" / "vendor"
REGISTRY = "https://registry.npmjs.org"

# package -> (version, {file inside the tarball: output file name})
PACKAGES = {
    "vue": ("3.5.43", {"package/dist/vue.global.prod.js": "vue.global.prod.js"}),
    # PDF.js ships ES modules as .mjs; saved as .js so every OS serves them as JavaScript.
    "pdfjs-dist": (
        "5.4.624",  # 5.5+ needs Map.getOrInsertComputed (2026 browsers only)
        {
            "package/build/pdf.min.mjs": "pdf.min.js",
            "package/build/pdf.worker.min.mjs": "pdf.worker.min.js",
        },
    ),
}


def _fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def vendor_package(name: str, version: str, files: dict[str, str]) -> dict:
    meta = json.loads(_fetch(f"{REGISTRY}/{name}/{version}"))
    tarball = _fetch(meta["dist"]["tarball"])

    algorithm, expected = meta["dist"]["integrity"].split("-", 1)
    actual = base64.b64encode(hashlib.new(algorithm, tarball).digest()).decode()
    if actual != expected:
        raise SystemExit(f"Integrity check failed for {name}@{version}")

    with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as archive:
        for member, output in files.items():
            (VENDOR_DIR / output).write_bytes(archive.extractfile(member).read())
    return {
        "version": version,
        "integrity": meta["dist"]["integrity"],
        "files": list(files.values()),
    }


def main() -> None:
    VENDOR_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {name: vendor_package(name, *spec) for name, spec in PACKAGES.items()}
    (VENDOR_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    for name, entry in manifest.items():
        print(f"vendored {name}@{entry['version']}: {', '.join(entry['files'])}")


if __name__ == "__main__":
    main()
