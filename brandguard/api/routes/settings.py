from fastapi import APIRouter

from brandguard.api.deps import SessionDep
from brandguard.core.settings import (
    PROFILES,
    AppSettings,
    AppSettingsUpdate,
    load_settings,
    save_settings,
)

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=AppSettings)
def read_settings(session: SessionDep) -> AppSettings:
    return load_settings(session)


@router.put("", response_model=AppSettings)
def update_settings(update: AppSettingsUpdate, session: SessionDep) -> AppSettings:
    return save_settings(session, update)


@router.get("/profiles")
def list_profiles() -> dict[str, dict]:
    return PROFILES
