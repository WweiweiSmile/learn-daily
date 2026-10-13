"""书的录入：PDF 或直接粘文本 → 解析 → 按天切分 → 落库。

解析是同步做的。pymupdf 抽一本书通常只要几秒，同步能立刻把「这是扫描版，读不了」
这种错误当面告诉用户，比让他轮询半天再看到失败体验好。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from sqlmodel import Session, col, select

from app.config import settings
from app.ingest.pdf import extract_pdf
from app.ingest.split import group_days, normalize, sections_from_text
from app.ingest.types import ExtractResult
from app.models import Book, BookStatus, Day, Section

logger = logging.getLogger(__name__)


def create_book_from_pdf(
    session: Session, *, user_id: int, title: str, filename: str, data: bytes
) -> Book:
    upload_dir = settings.upload_dir_for(user_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"{int(time.time())}-{Path(filename).name or 'upload.pdf'}"
    stored = upload_dir / safe_name
    stored.write_bytes(data)

    book = Book(
        title=(title or "").strip() or Path(filename).stem or "未命名",
        source_filename=filename,
        source_type="pdf",
    )
    _new_book(session, book)
    _apply(session, book, extract_pdf(stored))
    return book


def create_book_from_text(session: Session, *, title: str, text: str) -> Book:
    book = Book(title=(title or "").strip() or "未命名", source_type="text")
    _new_book(session, book)
    _apply(session, book, ExtractResult(sections=sections_from_text(text)))
    return book


def _new_book(session: Session, book: Book) -> None:
    session.add(book)
    session.commit()
    session.refresh(book)


def _apply(session: Session, book: Book, result: ExtractResult) -> None:
    if result.error:
        _fail(session, book, result.error)
        return

    units = normalize(result.sections, settings.day_max_chars)
    if not units:
        _fail(session, book, "这本书里没有抽出任何内容。")
        return

    sections = [
        Section(
            book_id=book.id,
            idx=i,
            title=unit.title,
            content=unit.content,
            char_count=unit.char_count,
        )
        for i, unit in enumerate(units)
    ]
    session.add_all(sections)
    session.commit()
    for section in sections:
        session.refresh(section)

    plans = group_days(
        units,
        target=settings.day_target_chars,
        minimum=settings.day_min_chars,
        maximum=settings.day_max_chars,
    )
    days = [
        Day(
            book_id=book.id,
            day_index=i + 1,
            title=plan.title,
            # plan.indexes 指向 units，units 的下标与 sections 一一对应
            section_ids=[sections[j].id for j in plan.indexes],
            char_count=plan.char_count,
        )
        for i, plan in enumerate(plans)
    ]
    session.add_all(days)
    session.commit()

    book.status = BookStatus.ready
    book.warning = result.warning
    book.total_chars = sum(u.char_count for u in units)
    book.day_count = len(days)
    session.add(book)
    session.commit()
    session.refresh(book)
    logger.info("《%s》就绪：%d 字，%d 天", book.title, book.total_chars, book.day_count)


def _fail(session: Session, book: Book, message: str) -> None:
    book.status = BookStatus.failed
    book.error = message
    session.add(book)
    session.commit()
    session.refresh(book)


def sections_of(session: Session, day: Day) -> list[Section]:
    """按 day.section_ids 的顺序取出章节块。"""
    if not day.section_ids:
        return []
    found = session.exec(select(Section).where(col(Section.id).in_(day.section_ids))).all()
    by_id = {s.id: s for s in found}
    return [by_id[i] for i in day.section_ids if i in by_id]


def day_text(sections: list[Section]) -> str:
    parts: list[str] = []
    for section in sections:
        if section.title:
            parts.append(f"## {section.title}\n\n{section.content}")
        else:
            parts.append(section.content)
    return "\n\n".join(parts)
