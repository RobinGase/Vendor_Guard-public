import json
from pathlib import Path
from unittest.mock import MagicMock, patch


PROFILE_RESPONSE = {
    "name": "TestVendor B.V.",
    "sector": "Finance",
    "services": ["Cloud backup"],
    "processes_personal_data": True,
    "is_ai_system": False,
    "is_dutch_government_vendor": False,
    "applicable_frameworks": ["ISO 27001", "NIS2", "CBW", "DORA"],
}

SECURITY_FINDINGS = [
    {
        "framework": "ISO 27001",
        "control_id": "A.8.8",
        "control_name": "Patch management",
        "status": "Partial",
        "severity": "Medium",
        "evidence": "Monthly patching only.",
        "recommendation": "Add critical patch SLA.",
    }
]

RESILIENCE_FINDINGS = [
    {
        "framework": "DORA",
        "control_id": "Art.9",
        "control_name": "ICT risk management",
        "status": "Compliant",
        "severity": "Info",
        "evidence": "Framework documented.",
        "recommendation": "No action required.",
    }
]


def make_mock_response(data):
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock()]
    mock_msg.content[0].text = json.dumps(data) if isinstance(data, (dict, list)) else data
    return mock_msg


def test_full_pipeline(tmp_path, mocker):
    """End-to-end: questionnaire file in, three output files out."""
    questionnaire = tmp_path / "vendor_q.txt"
    questionnaire.write_text("Vendor: TestVendor B.V.\nISO 27001: Certified\nMFA: Yes")

    def mock_create(**kwargs):
        system = kwargs.get("system", "")
        messages = kwargs.get("messages", [])
        # Determine which call this is by inspecting the system prompt content
        if not system:
            # memo call — no system prompt
            return make_mock_response("Audit memo content.")
        if "orchestrator" in system.lower() or "vendor profile" in system.lower() or "applicable_frameworks" in system:
            return make_mock_response(PROFILE_RESPONSE)
        if "DORA" in system or "resilience" in system.lower() or "digital operational resilience" in system.lower():
            return make_mock_response(RESILIENCE_FINDINGS)
        # default: security agent
        return make_mock_response(SECURITY_FINDINGS)

    def route_call(*, system=None, user_prompt=None, model=None, max_tokens=None):
        if not system:
            return "Audit memo content."
        if "orchestrator" in system.lower() or "vendor profile" in system.lower() or "applicable_frameworks" in system:
            return json.dumps(PROFILE_RESPONSE)
        if "DORA" in system or "resilience" in system.lower() or "digital operational resilience" in system.lower():
            return json.dumps(RESILIENCE_FINDINGS)
        return json.dumps(SECURITY_FINDINGS)

    mocker.patch("agents.orchestrator.invoke_chat_model", side_effect=route_call)
    mocker.patch("agents.security_agent.invoke_chat_model", side_effect=route_call)
    mocker.patch("agents.resilience_agent.invoke_chat_model", side_effect=route_call)
    mocker.patch("synthesizer.memo.invoke_chat_model", side_effect=route_call)

    from main import run_pipeline
    outputs = run_pipeline(
        questionnaire_path=questionnaire,
        doc_paths=[],
        output_dir=tmp_path,
    )

    assert (tmp_path / "scorecard.xlsx").exists()
    assert (tmp_path / "gap_register.xlsx").exists()
    assert (tmp_path / "audit_memo.docx").exists()


def test_full_pipeline_continues_when_one_agent_fails(tmp_path, mocker):
    questionnaire = tmp_path / "vendor_q.txt"
    questionnaire.write_text("Vendor: TestVendor B.V.\nISO 27001: Certified\nMFA: Yes")

    def mock_create(**kwargs):
        system = kwargs.get("system", "")
        if not system:
            return make_mock_response("Audit memo content.")
        if "orchestrator" in system.lower() or "vendor profile" in system.lower() or "applicable_frameworks" in system:
            return make_mock_response(PROFILE_RESPONSE)
        if "DORA" in system or "resilience" in system.lower() or "digital operational resilience" in system.lower():
            raise RuntimeError("simulated agent failure")
        return make_mock_response(SECURITY_FINDINGS)

    def route_call(*, system=None, user_prompt=None, model=None, max_tokens=None):
        if not system:
            return "Audit memo content."
        if "orchestrator" in system.lower() or "vendor profile" in system.lower() or "applicable_frameworks" in system:
            return json.dumps(PROFILE_RESPONSE)
        if "DORA" in system or "resilience" in system.lower() or "digital operational resilience" in system.lower():
            raise RuntimeError("simulated agent failure")
        return json.dumps(SECURITY_FINDINGS)

    mocker.patch("agents.orchestrator.invoke_chat_model", side_effect=route_call)
    mocker.patch("agents.security_agent.invoke_chat_model", side_effect=route_call)
    mocker.patch("agents.resilience_agent.invoke_chat_model", side_effect=route_call)
    mocker.patch("synthesizer.memo.invoke_chat_model", side_effect=route_call)

    from main import run_pipeline
    outputs = run_pipeline(
        questionnaire_path=questionnaire,
        doc_paths=[],
        output_dir=tmp_path,
    )

    assert outputs["scorecard_xlsx"].exists()
    assert outputs["gap_register_xlsx"].exists()
    assert outputs["memo_docx"].exists()


def test_pipeline_uses_questionnaire_only_for_vendor_profile(tmp_path, mocker):
    questionnaire = tmp_path / "vendor_q.txt"
    questionnaire.write_text("QUESTIONNAIRE")
    doc = tmp_path / "doc.txt"
    doc.write_text("FULL_DOC")

    captured = {}

    def fake_build_vendor_profile(vendor_docs):
        captured["vendor_docs"] = vendor_docs
        from models.finding import VendorProfile

        return VendorProfile(
            name="X",
            sector="Finance",
            services=["Backup"],
            processes_personal_data=True,
            is_ai_system=False,
            is_dutch_government_vendor=False,
            applicable_frameworks=["ISO 27001"],
        )

    mocker.patch("main.build_vendor_profile", side_effect=fake_build_vendor_profile)
    mocker.patch("main.determine_frameworks", return_value=[])
    mocker.patch("main.aggregate_findings", return_value=[])
    mocker.patch("main.compute_rag_scorecard", return_value={})
    mocker.patch("synthesizer.scorecard.write_scorecard")
    mocker.patch("synthesizer.scorecard.write_gap_register")
    mocker.patch("synthesizer.memo.write_audit_memo", return_value="memo")
    mocker.patch("synthesizer.google_output.write_scorecard_csv")
    mocker.patch("synthesizer.google_output.write_gap_register_csv")
    mocker.patch("synthesizer.google_output.write_audit_memo_html")

    from main import run_pipeline

    run_pipeline(questionnaire_path=questionnaire, doc_paths=[doc], output_dir=tmp_path)

    assert "QUESTIONNAIRE" in captured["vendor_docs"]
    assert "FULL_DOC" not in captured["vendor_docs"]


def test_main_module_does_not_import_output_writers_at_import_time(monkeypatch):
    import builtins
    import importlib

    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name.startswith("synthesizer.scorecard") or name.startswith("synthesizer.memo") or name.startswith("synthesizer.google_output"):
            raise AssertionError(f"unexpected eager import: {name}")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    import main
    importlib.reload(main)
