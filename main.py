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
    scorecard_path = output_dir / "scorecard.xlsx"
    gap_register_path = output_dir / "gap_register.xlsx"
    memo_path = output_dir / "audit_memo.docx"

    write_scorecard(scorecard, scorecard_path)
    write_gap_register(all_findings, gap_register_path)
    write_audit_memo(profile, all_findings, scorecard, memo_path)

    print(f"\nDone. Outputs written to {output_dir}/")
    for fw, data in scorecard.items():
        print(f"  {fw}: {data['rag']}")

    return {"scorecard": scorecard_path, "gap_register": gap_register_path, "memo": memo_path}


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
