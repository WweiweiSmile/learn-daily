"""PDF → 章节块。

扫描版 PDF 没有文字层，pymupdf 抽出来基本是空的。M1 不接 OCR，所以这里只做检测
并明确告知——总比让用户在界面上看到一个空白页面、还不知道为什么强。

章节识别按可靠性依次降级：PDF 自带书签目录 → 正文里的标题行 → 按段落硬切。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pymupdf

from app.ingest.split import chunk_plain_text
from app.ingest.types import ExtractResult, RawSection

logger = logging.getLogger(__name__)

# 每页平均抽不到这么多字符，基本可以断定是扫描版/图片版
SCANNED_CHARS_PER_PAGE = 50
MIN_MEANINGFUL_CHARS = 500

_HEADING_RE = re.compile(
    r"^\s*(?:"
    r"第\s*[一二三四五六七八九十百千零两\d]+\s*[章节讲篇课]"
    r"|Chapter\s+\d+"
    r"|CHAPTER\s+\d+"
    r"|\d{1,2}(?:\.\d{1,2}){0,2}\s+\S"
    r")\s*$",
    re.MULTILINE,
)


def extract_pdf(path: Path) -> ExtractResult:
    try:
        doc = pymupdf.open(path)
    except Exception as exc:  # pymupdf 的异常类型很杂，统一兜住
        logger.exception("打开 PDF 失败：%s", path)
        return ExtractResult(error=f"打不开这个 PDF：{exc}")

    try:
        page_texts = [page.get_text("text") for page in doc]
        toc_entries = _clean_toc(doc.get_toc(simple=True))
    finally:
        doc.close()

    page_count = len(page_texts)
    total = sum(len(t.strip()) for t in page_texts)

    if page_count == 0:
        return ExtractResult(error="这个 PDF 里没有页面")
    if total < MIN_MEANINGFUL_CHARS or total / page_count < SCANNED_CHARS_PER_PAGE:
        return ExtractResult(
            error=(
                f"这个 PDF 抽不出文字（{page_count} 页只抽到 {total} 个字符），"
                "多半是扫描版或图片版。需要 OCR 才能读，M1 还没接。"
            )
        )

    sections = _sections_from_toc(toc_entries, page_texts)
    source = "目录"
    if not sections:
        sections = _sections_from_headings(page_texts)
        source = "标题行"
    if not sections:
        sections = chunk_plain_text("\n\n".join(page_texts))
        source = "按段落硬切"

    warning = None
    if source != "目录":
        warning = f"这本书没有可用的书签目录，章节是按{source}推断的，切分可能不准。"

    logger.info("解析完成：%d 页，%d 个章节块，来源=%s", page_count, len(sections), source)
    return ExtractResult(sections=sections, warning=warning)


def _clean_toc(toc: list) -> list[tuple[int, str, int]]:
    """只保留一二层，太深的目录会把内容切得稀碎。"""
    entries: list[tuple[int, str, int]] = []
    for item in toc:
        if len(item) < 3:
            continue
        level, title, page = item[0], str(item[1]).strip(), int(item[2])
        if level <= 2 and title:
            entries.append((level, title, page))
    return entries


def _sections_from_toc(entries: list[tuple[int, str, int]], page_texts: list[str]) -> list[RawSection]:
    if len(entries) < 2:
        return []

    page_count = len(page_texts)
    out: list[RawSection] = []

    first_page = max(min(entries[0][2], page_count + 1) - 1, 0)
    front = "\n".join(page_texts[:first_page]).strip()
    if len(front) > MIN_MEANINGFUL_CHARS:
        out.append(RawSection("前言", front))

    for i, (_, title, page) in enumerate(entries):
        start = max(min(page, page_count) - 1, 0)
        end = max(min(entries[i + 1][2], page_count + 1) - 1, start + 1) if i + 1 < len(entries) else page_count
        body = "\n".join(page_texts[start:end]).strip()
        if body:
            out.append(RawSection(title, body))
    return out


def _sections_from_headings(page_texts: list[str]) -> list[RawSection]:
    text = "\n".join(page_texts)
    matches = list(_HEADING_RE.finditer(text))
    if len(matches) < 3:
        return []

    out: list[RawSection] = []
    front = text[: matches[0].start()].strip()
    if len(front) > MIN_MEANINGFUL_CHARS:
        out.append(RawSection("前言", front))

    for i, match in enumerate(matches):
        title = match.group(0).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if body:
            out.append(RawSection(title, body))
    return out
