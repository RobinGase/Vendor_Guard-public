from pathlib import Path


class DocumentParseError(Exception):
    pass


def parse_document(path: Path) -> str:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    suffix = path.suffix.lower()

    if suffix == ".txt":
        return path.read_text(encoding="utf-8", errors="replace")

    if suffix == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)

    if suffix == ".docx":
        from docx import Document
        doc = Document(str(path))
        return "\n".join(para.text for para in doc.paragraphs)

    if suffix in (".xlsx", ".xls"):
        from openpyxl import load_workbook
        wb = load_workbook(str(path), data_only=True)
        lines = []
        for sheet in wb.worksheets:
            for row in sheet.iter_rows(values_only=True):
                line = "\t".join(str(cell) if cell is not None else "" for cell in row)
                if line.strip():
                    lines.append(line)
        return "\n".join(lines)

    raise DocumentParseError(f"Unsupported file format: {suffix}")


def parse_documents(paths: list[Path]) -> str:
    parts = []
    for path in paths:
        path = Path(path)
        text = parse_document(path)
        parts.append(f"=== FILE: {path.name} ===\n{text}")
    return "\n\n".join(parts)
