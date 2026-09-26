"""Where BrandGuard keeps its files on the laptop.

Default home is %USERPROFILE%\\BrandGuard on Windows (~/BrandGuard elsewhere).
Set BRANDGUARD_HOME to use a different folder.
"""

import os
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "BrandGuard"


@dataclass(frozen=True)
class Paths:
    home: Path

    @property
    def data_dir(self) -> Path:
        return self.home / "data"

    @property
    def logs_dir(self) -> Path:
        return self.home / "logs"

    @property
    def db_file(self) -> Path:
        return self.home / "brandguard.db"

    @property
    def queue_file(self) -> Path:
        return self.home / "queue.db"

    def ensure(self) -> None:
        for directory in (self.home, self.data_dir, self.logs_dir):
            directory.mkdir(parents=True, exist_ok=True)


def get_paths() -> Paths:
    override = os.environ.get("BRANDGUARD_HOME")
    home = Path(override).expanduser() if override else Path.home() / APP_NAME
    return Paths(home.resolve())
