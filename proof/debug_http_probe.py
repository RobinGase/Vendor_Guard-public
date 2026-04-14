import json
import urllib.request
from pathlib import Path

from agents.orchestrator import SYSTEM_PROMPT
from utils.document_parser import parse_documents


docs = parse_documents(
    [
        Path("sample_vendor_q.txt"),
        Path("sample_soc2_report.txt"),
        Path("sample_iso_certificate.txt"),
        Path("sample_dora_questionnaire.txt"),
    ]
)

payload = {
    "model": "Randomblock1/nemotron-nano:8b",
    "messages": [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Extract the vendor profile from these documents:\n\n{docs}"},
    ],
    "temperature": 0,
    "max_tokens": 1024,
}

req = urllib.request.Request(
    "http://127.0.0.1:8088/v1/chat/completions",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
)
resp = urllib.request.urlopen(req, timeout=300)
print(resp.status)
print(resp.read().decode("utf-8"))
