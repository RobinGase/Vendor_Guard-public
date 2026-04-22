import pytest


@pytest.fixture(autouse=True)
def set_test_anthropic_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")


@pytest.fixture(autouse=True)
def allow_path_b_in_tests(monkeypatch):
    """Tests mock the model backend — no real Anthropic call happens —
    so bypass the Path B safety gate that main.run_pipeline enforces.
    Production runs without this env var will still fail closed."""
    monkeypatch.setenv("SAAF_ALLOW_UNGUARDED", "1")
