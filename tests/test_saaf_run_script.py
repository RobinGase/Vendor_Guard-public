from pathlib import Path


def test_saaf_run_script_uses_guest_venv_and_entrypoint() -> None:
    content = (Path(__file__).resolve().parent.parent / "saaf_run.sh").read_text(encoding="utf-8")

    assert "/opt/vendor-guard-venv/bin/python" in content
    assert "saaf_entrypoint.py" in content
    assert "cd /audit_workspace/vendor_guard" in content
    assert "saaf_wrapper.log" in content
    assert "saaf_entrypoint.stdout" in content
    assert "saaf_entrypoint.stderr" in content
    assert "wrapper_exec" in content
    assert "saaf_entrypoint.stdout" in content
    assert "saaf_entrypoint.stderr" in content
