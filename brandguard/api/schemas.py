from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class RunCreate(BaseModel):
    kind: Literal["selftest"] = "selftest"


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    status: str
    step: str | None
    done: int
    total: int
    message: str | None
    error: str | None
    cancel_requested: bool
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class WorkerStatus(BaseModel):
    online: bool
    last_seen: datetime | None
    pid: int | None


class SystemInfo(BaseModel):
    version: str
    python: str
    platform: str
    home: str
    data_dir: str
    db_file: str
    worker: WorkerStatus
