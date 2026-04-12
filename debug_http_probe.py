import httpx
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

response = httpx.post("http://127.0.0.1:8088/v1/chat/completions", json=payload, timeout=300)
print(response.status_code)
print(response.text)
