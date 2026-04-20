import json

import pytest

from agents.base import JSONRetryFailed, invoke_chat_model, invoke_chat_model_json, load_prompt


def test_load_prompt_returns_string():
    # Uses a real prompt file — iso27001_controls.md must exist
    content = load_prompt("iso27001_controls")
    assert isinstance(content, str)
    assert len(content) > 100


def test_load_prompt_missing_raises():
    with pytest.raises(FileNotFoundError):
        load_prompt("nonexistent_framework")


def test_invoke_chat_model_uses_inference_url_when_present(monkeypatch):
    monkeypatch.setenv("INFERENCE_URL", "http://127.0.0.1:8088/v1/chat/completions")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": json.dumps([{"framework": "ISO 27001"}])}}]}

    called = {}

    def fake_post(url, json=None, timeout=None):
        called["url"] = url
        called["json"] = json
        return FakeResponse()

    monkeypatch.setattr("agents.base._post_inference", fake_post)

    result = invoke_chat_model(
        model="claude-sonnet-4-6",
        system="system prompt",
        user_prompt="user prompt",
        max_tokens=512,
    )

    assert called["url"] == "http://127.0.0.1:8088/v1/chat/completions"
    assert called["json"]["messages"][0] == {"role": "system", "content": "system prompt"}
    assert called["json"]["messages"][1] == {"role": "user", "content": "user prompt"}
    assert result == json.dumps([{"framework": "ISO 27001"}])


def test_invoke_chat_model_requires_api_key_without_inference_url(monkeypatch):
    monkeypatch.delenv("INFERENCE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        invoke_chat_model(model="claude-sonnet-4-6", system=None, user_prompt="hello", max_tokens=128)


def test_invoke_chat_model_retries_transient_inference_timeout(monkeypatch):
    monkeypatch.setenv("INFERENCE_URL", "http://127.0.0.1:8088/v1/chat/completions")

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": json.dumps({"ok": True})}}]}

    calls = {"count": 0}

    def fake_post(url, json=None, timeout=None):
        calls["count"] += 1
        if calls["count"] < 3:
            raise TimeoutError("timed out")
        return FakeResponse()

    monkeypatch.setattr("agents.base._post_inference", fake_post)
    monkeypatch.setattr("agents.base.time.sleep", lambda seconds: None)

    result = invoke_chat_model(model="claude-sonnet-4-6", system=None, user_prompt="hello", max_tokens=128)

    assert calls["count"] == 3
    assert result == json.dumps({"ok": True})


def test_invoke_chat_model_uses_short_connect_timeout_for_shell_calls(monkeypatch):
    monkeypatch.setenv("INFERENCE_URL", "http://127.0.0.1:8088/v1/chat/completions")

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("agents.base._post_inference", fake_post)

    invoke_chat_model(model="claude-sonnet-4-6", system=None, user_prompt="hello", max_tokens=128)

    assert captured["timeout"] == 120


def test_invoke_chat_model_json_retries_once_on_parse_failure(mocker):
    # Local models often ignore "return JSON only" on the first try and
    # emit markdown preamble. The retry path cites their own response
    # back to them with a stricter instruction — this mimics that.
    calls = {"count": 0}

    def fake(*, model, system, user_prompt, max_tokens):
        calls["count"] += 1
        if calls["count"] == 1:
            return "Sure, here is the assessment:\n\nThis vendor has gaps."
        assert "not valid JSON" in user_prompt
        return json.dumps([{"framework": "ISO 27001", "control_id": "A.5.1"}])

    mocker.patch("agents.base.invoke_chat_model", side_effect=fake)

    data, raw = invoke_chat_model_json(model="x", system="sys", user_prompt="prompt", max_tokens=128)
    assert calls["count"] == 2
    assert data == [{"framework": "ISO 27001", "control_id": "A.5.1"}]


def test_invoke_chat_model_json_raises_with_last_raw_when_both_attempts_fail(mocker):
    mocker.patch(
        "agents.base.invoke_chat_model",
        side_effect=["not json first", "still not json on retry"],
    )

    with pytest.raises(JSONRetryFailed) as exc_info:
        invoke_chat_model_json(model="x", system="sys", user_prompt="prompt", max_tokens=128)
    assert exc_info.value.last_raw == "still not json on retry"
