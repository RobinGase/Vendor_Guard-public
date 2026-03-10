from models.finding import Finding


def aggregate_findings(findings: list[Finding]) -> list[Finding]:
    return findings


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
