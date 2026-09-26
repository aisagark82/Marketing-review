"""User-editable app settings, stored in the settings table."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy.orm import Session

from brandguard.core.models import Setting

ProfileName = Literal["light", "balanced", "max"]
# Empty string, or a plausible email address (kept simple on purpose).
ContactEmail = Annotated[
    str, StringConstraints(strip_whitespace=True, pattern=r"^$|^[^@\s]+@[^@\s]+\.[^@\s]+$")
]

# Sized for a 16 GB Windows laptop (design §5.10). Browser pages stay at 1
# because of the conservative crawl policy; profiles only change local processing.
PROFILES: dict[str, dict] = {
    "light": {
        "label": "Light",
        "description": "Use while you are working on the laptop",
        "browser_pages": 1,
        "processing_workers": 1,
        "whisper_model": "small",
        "queue_threads": 2,
    },
    "balanced": {
        "label": "Balanced",
        "description": "Normal use",
        "browser_pages": 1,
        "processing_workers": 2,
        "whisper_model": "small",
        "queue_threads": 4,
    },
    "max": {
        "label": "Max",
        "description": "Overnight runs",
        "browser_pages": 1,
        "processing_workers": 4,
        "whisper_model": "medium",
        "queue_threads": 6,
    },
}


class AppSettings(BaseModel):
    performance_profile: ProfileName = "balanced"
    crawler_contact_email: ContactEmail = Field(
        default="", description="Shown in the crawler's User-Agent; optional"
    )


class AppSettingsUpdate(BaseModel):
    performance_profile: ProfileName | None = None
    crawler_contact_email: ContactEmail | None = None


def _key(name: str) -> str:
    return f"app.{name}"


def load_settings(session: Session) -> AppSettings:
    stored = {
        name: row.value
        for name in AppSettings.model_fields
        if (row := session.get(Setting, _key(name))) is not None
    }
    return AppSettings.model_validate(stored)


def save_settings(session: Session, update: AppSettingsUpdate) -> AppSettings:
    for name, value in update.model_dump(exclude_none=True).items():
        row = session.get(Setting, _key(name))
        if row is None:
            session.add(Setting(key=_key(name), value=value))
        else:
            row.value = value
    session.flush()
    return load_settings(session)
