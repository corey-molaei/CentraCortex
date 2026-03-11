from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace

import pytest

from app.services.connectors.file_text_extractor import ExtractedTextResult, extract_text_from_file_bytes


def test_extract_xlsx_reads_sheet_content_and_metadata():
    openpyxl = pytest.importorskip("openpyxl")
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = "Budget"
    worksheet.append(["Item", "Cost"])
    worksheet.append(["GPU", 1200])
    worksheet.append(["Storage", 250])

    stream = BytesIO()
    workbook.save(stream)
    result = extract_text_from_file_bytes(filename="budget.xlsx", content=stream.getvalue())

    assert result.extractor == "openpyxl"
    assert "Sheet: Budget" in result.text
    assert "GPU, 1200" in result.text
    assert result.metadata["sheet_names"] == ["Budget"]
    assert result.metadata["row_count_total"] == 3


def test_extract_xls_reads_sheet_content_with_xlrd(monkeypatch):
    class FakeSheet:
        def __init__(self):
            self.name = "Legacy"
            self.nrows = 2

        def row_values(self, idx: int):
            rows = [["Name", "Email"], ["Maryam Asadi", "maryam@example.com"]]
            return rows[idx]

    class FakeWorkbook:
        def sheets(self):
            return [FakeSheet()]

    monkeypatch.setattr(
        "app.services.connectors.file_text_extractor.xlrd",
        SimpleNamespace(open_workbook=lambda **kwargs: FakeWorkbook()),
    )

    result = extract_text_from_file_bytes(filename="legacy.xls", content=b"fake-xls")
    assert result.extractor == "xlrd"
    assert "Sheet: Legacy" in result.text
    assert "Maryam Asadi, maryam@example.com" in result.text
    assert result.metadata["row_count_total"] == 2


def test_extract_doc_uses_antiword(monkeypatch):
    def fake_run(*args, **kwargs):  # noqa: ARG001
        return SimpleNamespace(returncode=0, stdout="Legacy DOC body", stderr="")

    monkeypatch.setattr("app.services.connectors.file_text_extractor.subprocess.run", fake_run)

    result = extract_text_from_file_bytes(filename="legacy.doc", content=b"fake-doc")
    assert isinstance(result, ExtractedTextResult)
    assert result.extractor == "antiword"
    assert result.text == "Legacy DOC body"


def test_extract_doc_missing_antiword_raises(monkeypatch):
    def fake_run(*args, **kwargs):  # noqa: ARG001
        raise FileNotFoundError("antiword missing")

    monkeypatch.setattr("app.services.connectors.file_text_extractor.subprocess.run", fake_run)

    with pytest.raises(ValueError, match="antiword"):
        extract_text_from_file_bytes(filename="legacy.doc", content=b"fake-doc")
