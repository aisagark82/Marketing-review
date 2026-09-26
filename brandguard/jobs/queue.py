"""Huey task queue stored in a local SQLite file (no Redis, no Postgres).

The queue is created lazily so that BRANDGUARD_HOME is resolved at use time,
not at import time.
"""

from dataclasses import dataclass
from functools import lru_cache

from huey import SqliteHuey
from huey.api import Result, TaskWrapper

from brandguard.core.paths import get_paths


@dataclass(frozen=True)
class Queue:
    huey: SqliteHuey
    tasks: dict[str, TaskWrapper]

    def enqueue(self, name: str, *args) -> Result | None:
        return self.tasks[name](*args)


@lru_cache
def _queue_for(queue_path: str) -> Queue:
    from brandguard.jobs import tasks

    huey = SqliteHuey(name="brandguard", filename=queue_path, results=False, timeout=30)
    registered = {name: huey.task(name=name)(fn) for name, fn in tasks.TASKS.items()}
    return Queue(huey=huey, tasks=registered)


def get_queue() -> Queue:
    paths = get_paths()
    paths.ensure()
    return _queue_for(str(paths.queue_file))
