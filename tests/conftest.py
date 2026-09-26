import keyring
import keyring.backend
import pytest
from fastapi.testclient import TestClient

from brandguard.api.app import create_app
from brandguard.core import db
from brandguard.jobs import queue, tasks


@pytest.fixture(autouse=True)
def brandguard_home(tmp_path, monkeypatch):
    """Every test gets its own home folder, database and queue."""
    monkeypatch.setenv("BRANDGUARD_HOME", str(tmp_path / "BrandGuard"))
    monkeypatch.setattr(tasks, "TICK_SECONDS", 0)
    db._engine_for.cache_clear()
    queue._queue_for.cache_clear()
    yield tmp_path / "BrandGuard"
    db._engine_for.cache_clear()
    queue._queue_for.cache_clear()


@pytest.fixture
def immediate_queue():
    """Run tasks synchronously when enqueued, instead of waiting for a worker."""
    huey = queue.get_queue().huey
    huey.immediate = True
    yield huey
    huey.immediate = False


@pytest.fixture
def client():
    with TestClient(create_app()) as test_client:
        yield test_client


class MemoryKeyring(keyring.backend.KeyringBackend):
    """Stands in for the OS keychain, so tests never touch the real one."""

    priority = 1

    def __init__(self):
        super().__init__()
        self.store = {}

    def get_password(self, service, username):
        return self.store.get((service, username))

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def delete_password(self, service, username):
        self.store.pop((service, username), None)


@pytest.fixture(autouse=True)
def isolated_keychain():
    previous = keyring.get_keyring()
    keyring.set_keyring(MemoryKeyring())
    yield
    keyring.set_keyring(previous)
