import platform
import sys

from fastapi import APIRouter

from brandguard import __version__
from brandguard.api.schemas import SystemInfo, WorkerStatus
from brandguard.core.paths import get_paths
from brandguard.jobs.worker import read_worker_status

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/system", response_model=SystemInfo)
def system_info() -> SystemInfo:
    paths = get_paths()
    return SystemInfo(
        version=__version__,
        python=sys.version.split()[0],
        platform=platform.platform(),
        home=str(paths.home),
        data_dir=str(paths.data_dir),
        db_file=str(paths.db_file),
        worker=WorkerStatus(**read_worker_status()),
    )
