"""Shared fixtures for API route unit tests."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def reset_settings_cache():
    """Clear the lru_cache so each test gets a fresh Settings build."""
    from app.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def fake_env(monkeypatch):
    """Set the minimum env vars required for Settings validation."""
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://fake.openai.azure.com/")
    monkeypatch.setenv("AZURE_OPENAI_KEY", "fake-key-for-tests")
    monkeypatch.setenv("AZURE_SEARCH_ENDPOINT", "https://fake.search.windows.net/")
    monkeypatch.setenv("AZURE_SEARCH_KEY", "fake-key-for-tests")
    monkeypatch.setenv(
        "COSMOS_CONNECTION_STRING",
        "AccountEndpoint=https://fake.documents.azure.com:443/;AccountKey=ZmFrZWtleWZha2U=;",
    )
    monkeypatch.setenv("APP_ENV", "development")
    from app.config import get_settings
    get_settings.cache_clear()
