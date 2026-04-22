import json
import os
import re
import socket
import time
import urllib.parse
import urllib.request
from pathlib import Path


PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

# Allowed schemes for INFERENCE_URL. urllib.request.urlopen will otherwise
# honor file:// (information disclosure) and unusual protocols.
_ALLOWED_INFERENCE_SCHEMES = frozenset({"http", "https"})

# Optional host allowlist for Path A. When set (colon- or comma-separated
# list of hostnames/IPs), INFERENCE_URL must resolve to one of them.
# The default manifest points at 172.16.0.1 (the Firecracker gateway);
# operators who relax that should set SAAF_INFERENCE_HOST_ALLOWLIST
# explicitly so the deviation is visible in the audit log / config.
_DEFAULT_HOST_ALLOWLIST = "172.16.0.1,127.0.0.1,localhost"


def _validate_inference_url(url: str) -> None:
    """Raise ValueError if the URL looks unsafe.

    Checks scheme (http/https only) and hostname (against an allowlist
    derived from SAAF_INFERENCE_HOST_ALLOWLIST, defaulting to the
    expected Firecracker gateway + loopback). Fails closed — malformed
    URLs are rejected rather than passed to urlopen.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in _ALLOWED_INFERENCE_SCHEMES:
        raise ValueError(
            f"INFERENCE_URL scheme {parsed.scheme!r} is not allowed; "
            f"expected one of {sorted(_ALLOWED_INFERENCE_SCHEMES)}"
        )
    if not parsed.hostname:
        raise ValueError(f"INFERENCE_URL has no hostname: {url!r}")
    allowlist = os.getenv("SAAF_INFERENCE_HOST_ALLOWLIST", _DEFAULT_HOST_ALLOWLIST)
    # Hostnames/IPs only — no ports. urlparse already strips the port from
    # parsed.hostname, so comparing bare hostnames is correct. Don't try to
    # be clever about `:` → `,`; that silently broke `host:port` entries.
    allowed_hosts = {h.strip() for h in allowlist.split(",") if h.strip()}
    if parsed.hostname not in allowed_hosts:
        raise ValueError(
            f"INFERENCE_URL host {parsed.hostname!r} is not in the "
            f"allowlist ({sorted(allowed_hosts)}). Set "
            "SAAF_INFERENCE_HOST_ALLOWLIST to override."
        )


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
        _validate_inference_url(inference_url)
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
                response = _post_inference(inference_url, payload, timeout=600)
                content = response.json()["choices"][0]["message"]["content"]
                # Empty-content guard: ollama returns "" with HTTP 200 when the
                # model truncates a completion (context overflow with small
                # num_ctx, refusal, or token-budget exhaustion). Silently
                # returning "" downstream produced placeholder-only artefacts
                # for 11 minutes before we caught it. Fail loud instead so the
                # agent can retry or surface the error to the operator.
                if not content or not content.strip():
                    raise EmptyInferenceResponse(
                        f"model returned empty content (attempt {attempt + 1}); "
                        "likely context overflow or token-budget exhaustion — "
                        "check ollama /api/ps context_length and num_predict."
                    )
                return content
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


class EmptyInferenceResponse(RuntimeError):
    """Raised when the inference endpoint returns HTTP 200 with empty
    content. Treated as a transient model error: the agent's prose
    fallback catches it and produces a visible, labelled placeholder
    rather than a silently empty artefact."""


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
    """Extract JSON from a model response, stripping markdown fences and preamble.

    Handles four local-model misbehaviours on top of the happy path:
    1. Markdown fences — ```json ... ```
    2. Preamble/prose before the array (tries each `[`/`{` as a start)
    3. Trailing garbage — qwen sometimes closes the array, then emits
       `<|endoftext|>` / `<|im_start|>user` and hallucinates a fresh
       conversation turn with a mangled schema. `raw_decode` stops at
       the first balanced value so that tail never reaches Pydantic.
    4. Truncation — salvages complete objects from a cut-off array
    """
    raw = raw.strip()
    match = re.search(r"```(?:json)?\s*\n?(.*?)```", raw, re.DOTALL)
    if match:
        raw = match.group(1).strip()
    decoder = json.JSONDecoder()
    last_error: Exception | None = None
    for i, ch in enumerate(raw):
        if ch in ("[", "{"):
            try:
                obj, _ = decoder.raw_decode(raw[i:])
                return obj
            except json.JSONDecodeError as exc:
                last_error = exc
                if ch == "[":
                    try:
                        return _salvage_truncated_array(raw[i:])
                    except json.JSONDecodeError:
                        pass
                continue
    if last_error is not None:
        raise last_error
    return json.loads(raw)


class JSONRetryFailed(Exception):
    """Raised when both the initial call and the strict-retry call
    failed to parse. Carries the last raw text so agents can fall
    back to prose-narrative findings without losing the model output."""

    def __init__(self, last_raw: str, original: Exception):
        super().__init__(f"JSON parse failed after retry: {original}")
        self.last_raw = last_raw
        self.original = original


def _dump_raw_response(tag: str | None, raw: str, attempt: int) -> None:
    if not tag:
        return
    debug_dir = os.getenv("VENDOR_AGENT_DEBUG_DIR")
    if not debug_dir:
        return
    try:
        dest = Path(debug_dir) / f"{tag}_raw_attempt{attempt}.txt"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(raw, encoding="utf-8")
    except OSError:
        pass


def invoke_chat_model_json(
    *,
    model: str,
    system: str,
    user_prompt: str,
    max_tokens: int,
    debug_tag: str | None = None,
) -> tuple[list | dict, str]:
    """Call the chat model and return (parsed_json, raw_text).

    Retries once with a stricter instruction when the first response
    can't be parsed as JSON. Local models (nemotron-nano-8b and
    similar) routinely add markdown preamble even when told not to;
    the retry message cites their own output back to them, which
    tends to produce a clean array on the second try.

    Raises JSONRetryFailed if both attempts fail to parse.
    """
    try:
        raw = invoke_chat_model(model=model, system=system, user_prompt=user_prompt, max_tokens=max_tokens)
    except EmptyInferenceResponse as exc:
        # First call returned empty content. Record the marker so the
        # debug dump still tells us what happened, then fall through to
        # the retry path (same as a parse failure) — gives the model a
        # second shot before we give up.
        raw = f"<EMPTY_RESPONSE attempt=1: {exc}>"
        _dump_raw_response(debug_tag, raw, attempt=1)
    else:
        _dump_raw_response(debug_tag, raw, attempt=1)
        try:
            return extract_json(raw), raw
        except Exception:
            pass
    retry_prompt = (
        f"{user_prompt}\n\n"
        "Your previous response was prose instead of JSON. Below is what you returned:\n\n"
        "--- BEGIN PREVIOUS RESPONSE ---\n"
        f"{raw}\n"
        "--- END PREVIOUS RESPONSE ---\n\n"
        "Convert every gap, concern, observation, and compliant point from that "
        "response into a JSON array. Each distinct finding becomes one object with "
        "EXACTLY these seven fields — do not invent other fields:\n"
        '  "framework": string (e.g. "ISO 27001", "NIS2", "DORA", "BIO2", "EU AI Act")\n'
        '  "control_id": string (e.g. "A.9.1", "Art.21", "BIO2-CRYPTO-01")\n'
        '  "control_name": string — short name of the control\n'
        '  "status": one of "Compliant", "Gap", "Partial", "Not Applicable"\n'
        '  "severity": one of "Critical", "High", "Medium", "Low", "Info"\n'
        '  "evidence": string — what the documents said (or "No evidence provided.")\n'
        '  "recommendation": string — concrete action the vendor should take\n\n'
        "Do not drop information — every concern or gap in the previous response "
        "must become one object. Map strengths/compliant items to status=\"Compliant\", "
        "severity=\"Info\". Map gaps/risks/concerns to status=\"Gap\" or \"Partial\" "
        "with appropriate severity.\n\n"
        "Output ONLY the JSON array, starting with `[` and ending with `]`. "
        "No markdown fences, no preamble, no explanation. Do NOT return an empty array."
    )
    try:
        raw2 = invoke_chat_model(model=model, system=system, user_prompt=retry_prompt, max_tokens=max_tokens)
    except EmptyInferenceResponse as exc:
        marker = f"<EMPTY_RESPONSE attempt=2: {exc}>"
        _dump_raw_response(debug_tag, marker, attempt=2)
        raise JSONRetryFailed(last_raw=marker, original=exc) from exc
    _dump_raw_response(debug_tag, raw2, attempt=2)
    try:
        return extract_json(raw2), raw2
    except Exception as exc:
        raise JSONRetryFailed(last_raw=raw2, original=exc) from exc


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
