import json
import os
import re
import socket
import time
import urllib.request
from pathlib import Path


PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def load_prompt(name: str) -> str:
    path = PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


def require_anthropic_api_key() -> str:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set. Configure it before running Vendor Guard.")
    return api_key


def invoke_chat_model(*, model: str, system: str | None = None, user_prompt: str, max_tokens: int) -> str:
    inference_url = os.getenv("INFERENCE_URL")
    if inference_url:
        payload = {
            "model": os.getenv("SAAF_MODEL", "Randomblock1/nemotron-nano:8b"),
            "messages": [],
            "temperature": 0,
            "max_tokens": max_tokens,
        }
        if system:
            payload["messages"].append({"role": "system", "content": system})
        payload["messages"].append({"role": "user", "content": user_prompt})

        last_error = None
        for attempt in range(10):
            try:
                response = _post_inference(inference_url, payload, timeout=120)
                return response.json()["choices"][0]["message"]["content"]
            except TimeoutError as exc:
                last_error = exc
                if attempt == 9:
                    raise
                time.sleep(1)

        raise last_error  # pragma: no cover

    import anthropic

    client = anthropic.Anthropic(api_key=require_anthropic_api_key())
    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return message.content[0].text.strip()


class _InferenceResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def json(self):
        return self._payload


def _post_inference(url: str, payload: dict, timeout: int) -> _InferenceResponse:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        body = urllib.request.urlopen(request, timeout=timeout).read().decode("utf-8")
    except (TimeoutError, socket.timeout) as exc:
        raise TimeoutError(str(exc)) from exc
    except Exception as exc:
        raise
    return _InferenceResponse(json.loads(body))


def extract_json(raw: str):
    """Extract JSON from Claude response, stripping markdown fences and preamble.
    Handles truncated JSON by salvaging complete objects from the array."""
    raw = raw.strip()
    # Strip markdown code fences
    match = re.search(r"```(?:json)?\s*\n?(.*?)```", raw, re.DOTALL)
    if match:
        raw = match.group(1).strip()
    # Find first [ or { and try to parse
    for i, ch in enumerate(raw):
        if ch in ("[", "{"):
            try:
                return json.loads(raw[i:])
            except json.JSONDecodeError:
                # If it's a truncated array, try to salvage complete objects
                if ch == "[":
                    return _salvage_truncated_array(raw[i:])
                continue
    return json.loads(raw)


def _salvage_truncated_array(raw: str) -> list:
    """Extract complete JSON objects from a truncated array.
    When Claude hits max_tokens, the JSON array gets cut off mid-object.
    This finds all complete objects and returns them."""
    results = []
    depth = 0
    obj_start = None

    for i, ch in enumerate(raw):
        if ch == "{":
            if depth == 0:
                obj_start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and obj_start is not None:
                try:
                    obj = json.loads(raw[obj_start:i + 1])
                    results.append(obj)
                except json.JSONDecodeError:
                    pass
                obj_start = None

    if not results:
        raise json.JSONDecodeError("No complete JSON objects found", raw, 0)
    return results


def fallback_finding_from_prose(*, framework: str, control_id: str, control_name: str, raw: str) -> list[dict]:
    return [
        {
            "framework": framework,
            "control_id": control_id,
            "control_name": control_name,
            "status": "Partial",
            "severity": "Medium",
            "evidence": raw.strip(),
            "recommendation": "Review the returned narrative response and convert it into structured audit findings.",
        }
    ]
