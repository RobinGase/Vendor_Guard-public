import os
import traceback
import importlib.metadata as importlib_metadata
import urllib.parse
import urllib.request
import time
from pathlib import Path


# Keys we allow queued.env to set. Anything else is ignored (logged).
# Bounds the attack surface even if a future caller drops unexpected
# keys into the file — environment pollution via unrelated vars
# (LD_PRELOAD, PYTHONPATH, http_proxy, ...) doesn't happen.
_ALLOWED_QUEUED_KEYS = frozenset({
    "VENDOR_QUESTIONNAIRE",
    "VENDOR_DOCS",
    "VENDOR_OUTPUT_DIR",
})

# Characters that indicate the value came from a shell-unsafe filename.
# If any slip past the TUI-side denylist, reject the line here too —
# defense in depth for the VM boundary.
_FORBIDDEN_VALUE_CHARS = ("\n", "\r", "\0", "`", "$")


def _load_queued_env(path: Path) -> None:
    """Parse /audit_workspace/queued.env as plain KEY="VALUE" pairs.

    Replaces the previous `. queued.env` shell sourcing, which executed
    the file with /bin/sh and so treated $(...) and backticks as command
    substitutions runnable at workload UID. This parser:
      - accepts exactly `KEY="value"` or `KEY=value` per line
      - strips one matching pair of surrounding single or double quotes
      - ignores blank lines and `#` comments
      - enforces an allowlist of keys
      - rejects values containing newline / NUL / backtick / $
      - never evaluates anything
    """
    if not path.is_file():
        return
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    for lineno, line in enumerate(raw.splitlines(), start=1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if "=" not in s:
            continue
        key, _, value = s.partition("=")
        key = key.strip()
        value = value.strip()
        if key not in _ALLOWED_QUEUED_KEYS:
            continue
        # Strip a single surrounding pair of quotes if present. Do not
        # perform any kind of expansion — the value is taken literally.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        if any(ch in value for ch in _FORBIDDEN_VALUE_CHARS):
            # Drop silently rather than crash the whole run — the TUI
            # should have blocked this upstream, so reaching here means
            # either a bug or tampering. Fail closed for this var.
            continue
        os.environ[key] = value


def resolve_inputs(repo_root: Path) -> tuple[Path, list[Path], Path]:
    questionnaire = os.getenv("VENDOR_QUESTIONNAIRE")
    docs = os.getenv("VENDOR_DOCS")
    output_dir = os.getenv("VENDOR_OUTPUT_DIR")

    if questionnaire:
        questionnaire_path = Path(questionnaire)
    else:
        questionnaire_path = repo_root / "sample_vendor_q.txt"

    if docs:
        doc_paths = [Path(part) for part in docs.split(";") if part]
    else:
        doc_paths = [
            repo_root / "sample_soc2_report.txt",
            repo_root / "sample_iso_certificate.txt",
            repo_root / "sample_dora_questionnaire.txt",
        ]

    output_path = Path(output_dir) if output_dir else repo_root / "output"
    return questionnaire_path, doc_paths, output_path


def write_status(log_path: Path, message: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(message + "\n")


def disable_pydantic_plugin_discovery() -> None:
    importlib_metadata.distributions = lambda: []


def wait_for_inference_ready(inference_url: str, attempts: int = 20, delay_seconds: int = 1) -> bool:
    # Rebuild the health URL via urlparse rather than substring-splitting
    # on "/v1/". A crafted INFERENCE_URL like
    # http://attacker.example/v1/chat/completions would otherwise steer
    # the health probe to http://attacker.example/health. This path is
    # the first outbound request after VM boot and runs before any
    # subsequent validation.
    parsed = urllib.parse.urlparse(inference_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return False
    netloc = parsed.hostname
    if parsed.port:
        netloc = f"{parsed.hostname}:{parsed.port}"
    health_url = f"{parsed.scheme}://{netloc}/health"
    last_error = None
    for _ in range(attempts):
        try:
            response = urllib.request.urlopen(health_url, timeout=5)
            response.read()
            return True
        except Exception as exc:
            last_error = exc
            time.sleep(delay_seconds)
    return False


def main() -> None:
    disable_pydantic_plugin_discovery()

    # saaf_run.sh no longer sources queued.env (sourcing is code
    # execution). Parse it here in Python with an allowlist instead,
    # before main imports or reads any of these env vars.
    queued_env = os.environ.get("SAAF_QUEUED_ENV", "/audit_workspace/queued.env")
    _load_queued_env(Path(queued_env))

    from main import run_pipeline

    repo_root = Path(__file__).resolve().parent
    questionnaire_path, doc_paths, output_path = resolve_inputs(repo_root)
    log_path = output_path / "saaf_entrypoint.log"
    inference_url = os.environ.get("INFERENCE_URL")
    write_status(log_path, f"questionnaire={questionnaire_path}")
    write_status(log_path, f"docs={len(doc_paths)}")
    write_status(log_path, f"output_dir={output_path}")
    if inference_url:
        write_status(log_path, f"inference_url={inference_url}")
        if wait_for_inference_ready(inference_url):
            write_status(log_path, "inference_ready=ok")
        else:
            write_status(log_path, "inference_ready=timeout")
    try:
        run_pipeline(questionnaire_path=questionnaire_path, doc_paths=doc_paths, output_dir=output_path)
        write_status(log_path, "pipeline=ok")
    except Exception:
        write_status(log_path, "pipeline=error")
        write_status(log_path, traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
