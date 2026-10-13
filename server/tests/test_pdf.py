"""PDF 解析。用 pymupdf 现造 PDF，免得往仓库里塞测试文件。"""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from app.ingest.pdf import extract_pdf


def _make_pdf(path: Path, *, pages: int = 6, text: bool = True, toc: bool = True) -> None:
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page()
        if text:
            for line_no in range(12):
                page.insert_text((72, 72 + line_no * 16), f"第 {i + 1} 页 第 {line_no} 行的一些正文内容")
    if toc:
        doc.set_toc([[1, "第一章 起点", 1], [1, "第二章 转折", 4]])
    doc.save(path)
    doc.close()


def test_sections_follow_the_pdf_toc(tmp_path: Path) -> None:
    pdf = tmp_path / "book.pdf"
    _make_pdf(pdf)
    result = extract_pdf(pdf)

    assert result.error is None
    assert [s.title for s in result.sections] == ["第一章 起点", "第二章 转折"]
    assert all(s.char_count > 0 for s in result.sections)
    assert result.warning is None


def test_falls_back_when_there_is_no_toc(tmp_path: Path) -> None:
    pdf = tmp_path / "plain.pdf"
    _make_pdf(pdf, toc=False)
    result = extract_pdf(pdf)

    assert result.error is None
    assert result.sections
    assert result.warning is not None  # 明确告诉用户切分是推断的


def test_scanned_pdf_is_reported_not_silently_empty(tmp_path: Path) -> None:
    pdf = tmp_path / "scan.pdf"
    _make_pdf(pdf, text=False)
    result = extract_pdf(pdf)

    assert result.sections == []
    assert result.error is not None
    assert "扫描" in result.error or "抽不出文字" in result.error


def test_broken_file_is_reported(tmp_path: Path) -> None:
    bad = tmp_path / "not-a.pdf"
    bad.write_bytes(b"this is definitely not a pdf")
    result = extract_pdf(bad)

    assert result.sections == []
    assert result.error is not None


@pytest.mark.parametrize("pages", [1, 3])
def test_tiny_pdf_does_not_crash(tmp_path: Path, pages: int) -> None:
    pdf = tmp_path / f"tiny-{pages}.pdf"
    _make_pdf(pdf, pages=pages, toc=False)
    result = extract_pdf(pdf)
    assert result.error is None or "抽不出文字" in (result.error or "")
