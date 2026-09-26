"""Gemini settings (Settings page) and where the API key is kept."""

import contextlib

import keyring
import keyring.errors
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from brandguard.core.models import Setting

DEFAULT_MODEL = "gemini-2.5-flash"  # D2
KEYRING_SERVICE = "BrandGuard"
KEYRING_ACCOUNT = "gemini-api-key"
DB_KEY = "ai.api_key"  # only used when the computer has no keychain
PREFIX = "ai."


class AISettings(BaseModel):
    model: str = DEFAULT_MODEL
    review_near_misses: bool = True
    read_images: bool = False  # downloads the site's images, so it's opt-in
    max_images_per_crawl: int = Field(100, ge=0, le=5000)
    requests_per_minute: int = Field(60, ge=1, le=5000)
    daily_request_limit: int = Field(2000, ge=1, le=1_000_000)
    # For the cost estimate only; check Google's current prices for your model.
    price_input_per_million: float = Field(0.30, ge=0)
    price_output_per_million: float = Field(2.50, ge=0)


class AISettingsUpdate(BaseModel):
    model: str | None = Field(None, min_length=3, max_length=80)
    review_near_misses: bool | None = None
    read_images: bool | None = None
    max_images_per_crawl: int | None = Field(None, ge=0, le=5000)
    requests_per_minute: int | None = Field(None, ge=1, le=5000)
    daily_request_limit: int | None = Field(None, ge=1, le=1_000_000)
    price_input_per_million: float | None = Field(None, ge=0)
    price_output_per_million: float | None = Field(None, ge=0)


def load_ai_settings(session: Session) -> AISettings:
    stored = {
        name: row.value
        for name in AISettings.model_fields
        if (row := session.get(Setting, PREFIX + name)) is not None
    }
    return AISettings.model_validate(stored)


def save_ai_settings(session: Session, update: AISettingsUpdate) -> AISettings:
    for name, value in update.model_dump(exclude_none=True).items():
        row = session.get(Setting, PREFIX + name)
        if row is None:
            session.add(Setting(key=PREFIX + name, value=value))
        else:
            row.value = value
    session.flush()
    return load_ai_settings(session)


# --- the API key ------------------------------------------------------------------------------
# The OS keychain (Windows Credential Manager, macOS Keychain) keeps the key out of BrandGuard's
# files. Computers without one (some Linux setups) fall back to the local database, and the
# Settings page says so.


def save_api_key(session: Session, api_key: str) -> str:
    try:
        keyring.set_password(KEYRING_SERVICE, KEYRING_ACCOUNT, api_key)
        _delete_db_key(session)
        return "keychain"
    except keyring.errors.KeyringError:
        row = session.get(Setting, DB_KEY)
        if row is None:
            session.add(Setting(key=DB_KEY, value=api_key))
        else:
            row.value = api_key
        return "database"


def load_api_key(session: Session) -> tuple[str | None, str | None]:
    """(key, where it is stored)."""
    try:
        key = keyring.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
        if key:
            return key, "keychain"
    except keyring.errors.KeyringError:
        pass
    row = session.get(Setting, DB_KEY)
    return (row.value, "database") if row is not None and row.value else (None, None)


def delete_api_key(session: Session) -> None:
    with contextlib.suppress(keyring.errors.KeyringError):  # nothing stored there
        keyring.delete_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
    _delete_db_key(session)


def _delete_db_key(session: Session) -> None:
    row = session.get(Setting, DB_KEY)
    if row is not None:
        session.delete(row)


def key_status(session: Session) -> dict:
    key, storage = load_api_key(session)
    return {"set": bool(key), "hint": f"••••{key[-4:]}" if key else None, "storage": storage}
