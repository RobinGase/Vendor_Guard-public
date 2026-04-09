from models.finding import Finding


STATUS_RANK = {
    "Gap": 0,
    "Partial": 1,
    "Compliant": 2,
    "Not Applicable": 3,
}

SEVERITY_RANK = {
    "Critical": 0,
    "High": 1,
    "Medium": 2,
    "Low": 3,
    "Info": 4,
}


def aggregate_findings(findings: list[Finding]) -> list[Finding]:
    deduped: dict[tuple[str, str], Finding] = {}

    for finding in findings:
        key = (finding.framework, finding.control_id)
        existing = deduped.get(key)
        if existing is None:
            deduped[key] = finding
            continue

        current_rank = (
            STATUS_RANK.get(finding.status, 99),
            SEVERITY_RANK.get(finding.severity, 99),
        )
        existing_rank = (
            STATUS_RANK.get(existing.status, 99),
            SEVERITY_RANK.get(existing.severity, 99),
        )
        if current_rank < existing_rank:
            deduped[key] = finding

    return sorted(
        deduped.values(),
        key=lambda finding: (
            STATUS_RANK.get(finding.status, 99),
            SEVERITY_RANK.get(finding.severity, 99),
            finding.framework,
            finding.control_id,
        ),
    )


def compute_rag_scorecard(findings: list[Finding]) -> dict:
    """
    Returns {framework: {"rag": "Green"|"Amber"|"Red", "total": int, "gaps": int, "critical": int, "high": int, "partial": int}}
    RAG logic:
      Red   — any Critical or High Gap
      Amber — any Medium/Low Gap or any Partial
      Green — all Compliant or Not Applicable
    """
    scorecard: dict[str, dict] = {}

    for f in findings:
        if f.framework not in scorecard:
            scorecard[f.framework] = {"total": 0, "gaps": 0, "critical": 0, "high": 0, "partial": 0}

        s = scorecard[f.framework]
        s["total"] += 1

        if f.status == "Gap":
            s["gaps"] += 1
            if f.severity == "Critical":
                s["critical"] += 1
            elif f.severity == "High":
                s["high"] += 1
        elif f.status == "Partial":
            s["partial"] += 1

    for fw, s in scorecard.items():
        if s["critical"] > 0 or s["high"] > 0:
            s["rag"] = "Red"
        elif s["gaps"] > 0 or s["partial"] > 0:
            s["rag"] = "Amber"
        else:
            s["rag"] = "Green"

    return scorecard
