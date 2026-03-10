"""
Google Workspace-compatible outputs.
- CSV files: open directly in Google Sheets (File > Import or drag & drop)
- HTML memo: import into Google Docs (File > Open > upload .html) or view in browser
"""

import csv
import html
from pathlib import Path
from models.finding import Finding, VendorProfile

RAG_COLORS = {
    "Red": "#FF6B6B",
    "Amber": "#FFD93D",
    "Green": "#6BCB77",
}

SEVERITY_COLORS = {
    "Critical": "#FF6B6B",
    "High": "#FFA07A",
    "Medium": "#FFD93D",
    "Low": "#FFFACD",
    "Info": "#E0E0E0",
}

STATUS_COLORS = {
    "Gap": "#FF6B6B",
    "Partial": "#FFD93D",
    "Compliant": "#6BCB77",
    "Not Applicable": "#E0E0E0",
}


def write_scorecard_csv(scorecard: dict, output_path: Path):
    """RAG scorecard as CSV — importable into Google Sheets."""
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Framework", "RAG Status", "Total Controls", "Gaps", "Critical", "High", "Partial"])
        for framework, data in scorecard.items():
            writer.writerow([
                framework,
                data["rag"],
                data.get("total", 0),
                data.get("gaps", 0),
                data.get("critical", 0),
                data.get("high", 0),
                data.get("partial", 0),
            ])


def write_gap_register_csv(findings: list[Finding], output_path: Path):
    """Gap register as CSV — importable into Google Sheets."""
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Framework", "Control ID", "Control Name", "Status", "Severity", "Evidence", "Recommendation"])
        for finding in findings:
            writer.writerow([
                finding.framework,
                finding.control_id,
                finding.control_name,
                finding.status,
                finding.severity,
                finding.evidence,
                finding.recommendation,
            ])


def write_audit_memo_html(
    profile: VendorProfile,
    findings: list[Finding],
    scorecard: dict,
    memo_text: str,
    output_path: Path,
):
    """
    Audit memo as HTML — import into Google Docs or open in browser.
    To import: Google Docs > File > Open > Upload > select audit_memo.html
    """
    # Build scorecard table rows
    scorecard_rows = ""
    for fw, data in scorecard.items():
        color = RAG_COLORS.get(data["rag"], "#ffffff")
        scorecard_rows += f"""
        <tr>
            <td>{html.escape(fw)}</td>
            <td style="background-color:{color}; font-weight:bold; text-align:center">{data['rag']}</td>
            <td style="text-align:center">{data.get('total', 0)}</td>
            <td style="text-align:center">{data.get('gaps', 0)}</td>
            <td style="text-align:center">{data.get('critical', 0)}</td>
            <td style="text-align:center">{data.get('high', 0)}</td>
            <td style="text-align:center">{data.get('partial', 0)}</td>
        </tr>"""

    # Build findings table rows
    finding_rows = ""
    for f in findings:
        status_color = STATUS_COLORS.get(f.status, "#ffffff")
        sev_color = SEVERITY_COLORS.get(f.severity, "#ffffff")
        finding_rows += f"""
        <tr>
            <td>{html.escape(f.framework)}</td>
            <td>{html.escape(f.control_id)}</td>
            <td>{html.escape(f.control_name)}</td>
            <td style="background-color:{status_color}">{html.escape(f.status)}</td>
            <td style="background-color:{sev_color}">{html.escape(f.severity)}</td>
            <td>{html.escape(f.evidence)}</td>
            <td>{html.escape(f.recommendation)}</td>
        </tr>"""

    # Convert memo text to HTML paragraphs
    memo_html = ""
    for line in memo_text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        # Detect section headings (numbered or all-caps lines)
        if stripped[0].isdigit() and stripped[1:3] in (". ", ") "):
            memo_html += f"<h3>{html.escape(stripped)}</h3>\n"
        elif stripped.isupper() and len(stripped) > 3:
            memo_html += f"<h3>{html.escape(stripped)}</h3>\n"
        else:
            memo_html += f"<p>{html.escape(stripped)}</p>\n"

    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Vendor Risk Assessment: {html.escape(profile.name)}</title>
<style>
  body {{ font-family: Arial, sans-serif; max-width: 1100px; margin: 40px auto; color: #222; }}
  h1 {{ color: #2c3e50; border-bottom: 3px solid #2c3e50; padding-bottom: 8px; }}
  h2 {{ color: #2c3e50; margin-top: 40px; }}
  h3 {{ color: #34495e; }}
  table {{ border-collapse: collapse; width: 100%; margin: 16px 0; font-size: 13px; }}
  th {{ background-color: #2c3e50; color: white; padding: 10px 12px; text-align: left; }}
  td {{ border: 1px solid #ddd; padding: 8px 12px; vertical-align: top; }}
  tr:nth-child(even) {{ background-color: #f9f9f9; }}
  .meta {{ color: #666; margin-bottom: 32px; }}
  .memo {{ background: #f8f8f8; border-left: 4px solid #2c3e50; padding: 20px; margin: 16px 0; }}
</style>
</head>
<body>

<h1>Vendor Risk Assessment: {html.escape(profile.name)}</h1>
<div class="meta">
  <strong>Sector:</strong> {html.escape(profile.sector)} &nbsp;|&nbsp;
  <strong>Services:</strong> {html.escape(", ".join(profile.services))} &nbsp;|&nbsp;
  <strong>AI System:</strong> {"Yes" if profile.is_ai_system else "No"} &nbsp;|&nbsp;
  <strong>Government Vendor:</strong> {"Yes" if profile.is_dutch_government_vendor else "No"}
</div>

<h2>Risk Scorecard</h2>
<table>
  <thead>
    <tr>
      <th>Framework</th><th>RAG Status</th><th>Total Controls</th>
      <th>Gaps</th><th>Critical</th><th>High</th><th>Partial</th>
    </tr>
  </thead>
  <tbody>{scorecard_rows}</tbody>
</table>

<h2>Audit Memo</h2>
<div class="memo">
{memo_html}
</div>

<h2>Gap Register</h2>
<table>
  <thead>
    <tr>
      <th>Framework</th><th>Control ID</th><th>Control Name</th>
      <th>Status</th><th>Severity</th><th>Evidence</th><th>Recommendation</th>
    </tr>
  </thead>
  <tbody>{finding_rows}</tbody>
</table>

</body>
</html>"""

    output_path.write_text(doc, encoding="utf-8")
