import pytest
from pathlib import Path
from utils.document_parser import parse_document, parse_documents, DocumentParseError


def test_parse_txt(tmp_path):
    f = tmp_path / "vendor.txt"
    f.write_text("We hold ISO 27001 certification.")
    result = parse_document(f)
    assert "ISO 27001" in result


def test_parse_unsupported_format(tmp_path):
    f = tmp_path / "vendor.csv"
    f.write_text("col1,col2")
    with pytest.raises(DocumentParseError):
        parse_document(f)


def test_parse_nonexistent_file():
    with pytest.raises(FileNotFoundError):
        parse_document(Path("/nonexistent/file.txt"))


def test_parse_documents_combines_text(tmp_path):
    f1 = tmp_path / "q.txt"
    f1.write_text("Document one content.")
    f2 = tmp_path / "cert.txt"
    f2.write_text("Document two content.")
    result = parse_documents([f1, f2])
    assert "Document one" in result
    assert "Document two" in result


def test_parse_documents_includes_filename(tmp_path):
    f = tmp_path / "soc2_report.txt"
    f.write_text("SOC2 Type II report content.")
    result = parse_documents([f])
    assert "soc2_report.txt" in result
