from pathlib import Path

from saaf_entrypoint import disable_pydantic_plugin_discovery, resolve_inputs, wait_for_inference_ready, write_status


def test_resolve_inputs_uses_env_overrides(monkeypatch, tmp_path: Path) -> None:
    q = tmp_path / "q.txt"
    d1 = tmp_path / "a.txt"
    d2 = tmp_path / "b.txt"
    q.write_text("q")
    d1.write_text("a")
    d2.write_text("b")
    out = tmp_path / "out"

    monkeypatch.setenv("VENDOR_QUESTIONNAIRE", str(q))
    monkeypatch.setenv("VENDOR_DOCS", f"{d1};{d2}")
    monkeypatch.setenv("VENDOR_OUTPUT_DIR", str(out))

    questionnaire, docs, output_dir = resolve_inputs(Path(tmp_path))

    assert questionnaire == q
    assert docs == [d1, d2]
    assert output_dir == out


def test_resolve_inputs_defaults_to_sample_documents(monkeypatch, tmp_path: Path) -> None:
    for name in (
        "sample_vendor_q.txt",
        "sample_soc2_report.txt",
        "sample_iso_certificate.txt",
        "sample_dora_questionnaire.txt",
    ):
        (tmp_path / name).write_text(name)

    monkeypatch.delenv("VENDOR_QUESTIONNAIRE", raising=False)
    monkeypatch.delenv("VENDOR_DOCS", raising=False)
    monkeypatch.delenv("VENDOR_OUTPUT_DIR", raising=False)

    questionnaire, docs, output_dir = resolve_inputs(tmp_path)

    assert questionnaire == tmp_path / "sample_vendor_q.txt"
    assert docs == [
        tmp_path / "sample_soc2_report.txt",
        tmp_path / "sample_iso_certificate.txt",
        tmp_path / "sample_dora_questionnaire.txt",
    ]
    assert output_dir == tmp_path / "output"


def test_write_status_appends_lines(tmp_path: Path) -> None:
    log_path = tmp_path / "saaf_entrypoint.log"

    write_status(log_path, "start")
    write_status(log_path, "done")

    assert log_path.read_text(encoding="utf-8") == "start\ndone\n"


def test_wait_for_inference_ready_polls_health_endpoint(monkeypatch):
    calls = {"count": 0, "url": None}

    class FakeResponse:
        def read(self):
            return b'{"status":"ok"}'

    def fake_urlopen(request, timeout=0):
        calls["count"] += 1
        calls["url"] = request
        return FakeResponse()

    monkeypatch.setattr("saaf_entrypoint.urllib.request.urlopen", fake_urlopen)

    wait_for_inference_ready("http://172.16.0.1:8088/v1/chat/completions")

    assert calls["count"] == 1
    assert calls["url"] == "http://172.16.0.1:8088/health"


def test_wait_for_inference_ready_can_return_false_after_retries(monkeypatch):
    monkeypatch.setattr("saaf_entrypoint.urllib.request.urlopen", lambda request, timeout=0: (_ for _ in ()).throw(TimeoutError("timed out")))
    monkeypatch.setattr("saaf_entrypoint.time.sleep", lambda seconds: None)

    ready = wait_for_inference_ready("http://172.16.0.1:8088/v1/chat/completions", attempts=2, delay_seconds=0)

    assert ready is False


def test_disable_pydantic_plugin_discovery_overrides_distributions(monkeypatch):
    import importlib.metadata as importlib_metadata

    disable_pydantic_plugin_discovery()

    assert list(importlib_metadata.distributions()) == []
