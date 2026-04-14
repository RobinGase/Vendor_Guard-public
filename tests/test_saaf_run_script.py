from pathlib import Path


def test_saaf_run_script_uses_guest_venv_and_entrypoint() -> None:
    content = (Path(__file__).resolve().parent.parent / "saaf_run.sh").read_text(encoding="utf-8")

    assert "/usr/bin/python3.12" in content
    assert "saaf_entrypoint.py" in content
    assert "/tmp/vendor_guard_runtime" in content
    assert "cp -a /audit_workspace/vendor_guard /tmp/vendor_guard_runtime" in content
    assert "vendor_guard_venv" not in content
    assert "tar xf /opt/vendor-guard-venv.tar -C /tmp" in content
    assert "/tmp/vendor-guard-venv/lib/python3.12/site-packages" in content
    assert "/tmp/vendor_guard_site" not in content
    assert "saaf_wrapper.log" in content
    assert "saaf_entrypoint.stdout" in content
    assert "saaf_entrypoint.stderr" in content
    assert "wrapper_exec" in content


def test_saaf_run_script_writes_wrapper_breadcrumb_before_copy() -> None:
    content = (Path(__file__).resolve().parent.parent / "saaf_run.sh").read_text(encoding="utf-8")

    start_marker = 'wrapper_start'
    copy_marker = 'cp -a /audit_workspace/vendor_guard /tmp/vendor_guard_runtime'

    assert start_marker in content
    assert copy_marker in content
    assert content.index(start_marker) < content.index(copy_marker), (
        "wrapper_start breadcrumb must be written before cp so AgentFS always "
        "sees saaf_run.sh started, even if cp fails under set -e"
    )
