import os
import traceback
import importlib.metadata as importlib_metadata
import urllib.request
import time
from pathlib import Path


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
    health_url = inference_url.split("/v1/", 1)[0] + "/health"
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
