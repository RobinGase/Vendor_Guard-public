"""Explicit coverage for the Path B safety gate in main._enforce_path_b_gate.

Rationale: conftest autouse sets SAAF_ALLOW_UNGUARDED=1 so the rest of
the test suite can run against mocks. That fixture would hide a
regression where the gate silently stopped firing. These tests opt out
of the fixture and check the gate directly.
"""
import pytest

from main import _enforce_path_b_gate


@pytest.fixture(autouse=True)
def clear_gate_env(monkeypatch):
    # Undo the autouse fixture from conftest for just these tests.
    monkeypatch.delenv("SAAF_ALLOW_UNGUARDED", raising=False)
    monkeypatch.delenv("INFERENCE_URL", raising=False)


def test_path_b_gate_blocks_run_without_opt_in():
    with pytest.raises(RuntimeError, match="Refusing to run Path B"):
        _enforce_path_b_gate()


def test_path_b_gate_allows_run_with_inference_url(monkeypatch):
    monkeypatch.setenv("INFERENCE_URL", "http://172.16.0.1:8088/v1/chat/completions")
    # No exception → gate is a no-op on Path A.
    _enforce_path_b_gate()


def test_path_b_gate_allows_explicit_opt_in(monkeypatch, capsys):
    monkeypatch.setenv("SAAF_ALLOW_UNGUARDED", "1")
    _enforce_path_b_gate()
    captured = capsys.readouterr()
    # A loud warning must be emitted so operators see the implication.
    assert "WARNING" in captured.err
    assert "Path B" in captured.err


def test_path_b_gate_does_not_accept_other_truthy_values(monkeypatch):
    # Be strict about the opt-in sentinel — `true`, `yes`, `1` being
    # interchangeable leads to surprises. Only "1" counts.
    monkeypatch.setenv("SAAF_ALLOW_UNGUARDED", "true")
    with pytest.raises(RuntimeError):
        _enforce_path_b_gate()
