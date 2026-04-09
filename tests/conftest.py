import pytest


@pytest.fixture(autouse=True)
def set_test_anthropic_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
