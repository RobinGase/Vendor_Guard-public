import argparse
import concurrent.futures
from pathlib import Path

from agents.orchestrator import build_vendor_profile, determine_frameworks
from agents.security_agent import run_security_agent
from agents.resilience_agent import run_resilience_agent
from agents.gov_baseline_agent import run_gov_baseline_agent
from agents.ai_trust_agent import run_ai_trust_agent
from synthesizer.synthesizer import aggregate_findings, compute_rag_scorecard
from synthesizer.scorecard import write_scorecard, write_gap_register
from synthesizer.memo import write_audit_memo
from synthesizer.google_output import write_scorecard_csv, write_gap_register_csv, write_audit_memo_html
from utils.document_parser import parse_documents
from models.finding import Finding

AGENT_MAP = {
    "security": run_security_agent,
    "resilience": run_resilience_agent,
    "gov_baseline": run_gov_baseline_agent,
    "ai_trust": run_ai_trust_agent,
}


def run_pipeline(
    questionnaire_path: Path,
    doc_paths: list[Path],
    output_dir: Path,
) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)

    all_paths = [questionnaire_path] + list(doc_paths)
    vendor_docs = parse_documents(all_paths)

    print("Extracting vendor profile...")
    profile = build_vendor_profile(vendor_docs)
    print(f"Vendor: {profile.name} | Sector: {profile.sector} | AI system: {profile.is_ai_system}")

    agents_to_run = determine_frameworks(profile)
    print(f"Running agents: {agents_to_run}")

    all_findings: list[Finding] = []
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = {
            executor.submit(AGENT_MAP[name], vendor_docs): name
            for name in agents_to_run
        }
        for future in concurrent.futures.as_completed(futures):
            name = futures[future]
            findings = future.result()
            print(f"  {name}: {len(findings)} findings")
            all_findings.extend(findings)

    all_findings = aggregate_findings(all_findings)
    scorecard = compute_rag_scorecard(all_findings)

    print("Writing outputs...")

    # Draft memo text once, reuse for both DOCX and HTML
    memo_text = write_audit_memo(profile, all_findings, scorecard, output_dir / "audit_memo.docx")

    # Excel (Microsoft Office)
    write_scorecard(scorecard, output_dir / "scorecard.xlsx")
    write_gap_register(all_findings, output_dir / "gap_register.xlsx")

    # Google Workspace (CSV + HTML)
    write_scorecard_csv(scorecard, output_dir / "scorecard.csv")
    write_gap_register_csv(all_findings, output_dir / "gap_register.csv")
    write_audit_memo_html(profile, all_findings, scorecard, memo_text, output_dir / "audit_memo.html")

    print(f"\nDone. Outputs written to {output_dir}/")
    print("\n  Microsoft Office:")
    print("    scorecard.xlsx, gap_register.xlsx, audit_memo.docx")
    print("  Google Workspace (drag & drop into Google Drive):")
    print("    scorecard.csv, gap_register.csv, audit_memo.html")
    print()
    for fw, data in scorecard.items():
        print(f"  {fw}: {data['rag']}")

    return {
        "scorecard_xlsx": output_dir / "scorecard.xlsx",
        "gap_register_xlsx": output_dir / "gap_register.xlsx",
        "memo_docx": output_dir / "audit_memo.docx",
        "scorecard_csv": output_dir / "scorecard.csv",
        "gap_register_csv": output_dir / "gap_register.csv",
        "memo_html": output_dir / "audit_memo.html",
    }


def main():
    parser = argparse.ArgumentParser(description="SAAF Vendor Risk Audit Agent")
    parser.add_argument("--questionnaire", required=True, type=Path,
                        help="Path to vendor questionnaire (PDF/DOCX/XLSX/TXT)")
    parser.add_argument("--docs", nargs="*", default=[], type=Path,
                        help="Additional vendor documents (SOC2, ISO cert, etc.)")
    parser.add_argument("--output-dir", default=Path("output"), type=Path,
                        help="Directory for output files (default: ./output)")
    args = parser.parse_args()

    run_pipeline(
        questionnaire_path=args.questionnaire,
        doc_paths=args.docs,
        output_dir=args.output_dir,
    )


if __name__ == "__main__":
    main()
