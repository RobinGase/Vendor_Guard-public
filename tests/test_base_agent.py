from agents.base import load_prompt


def test_load_prompt_returns_string():
    # Uses a real prompt file — iso27001_controls.md must exist
    content = load_prompt("iso27001_controls")
    assert isinstance(content, str)
    assert len(content) > 100


def test_load_prompt_missing_raises():
    import pytest
    with pytest.raises(FileNotFoundError):
        load_prompt("nonexistent_framework")
