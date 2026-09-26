"""Which Chromium to use. Normally Playwright's own (installed by `brandguard setup`)."""

import os
import sys


def chromium_executable() -> str | None:
    """BRANDGUARD_CHROMIUM_PATH overrides Playwright's bundled Chromium, if set."""
    return os.environ.get("BRANDGUARD_CHROMIUM_PATH") or None


def running_as_root() -> bool:
    """Chromium refuses its sandbox as root (containers); on a normal laptop this is False."""
    return sys.platform != "win32" and os.geteuid() == 0
