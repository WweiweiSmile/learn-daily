"""书架：上传、列表、详情、删除。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlmodel import Session, select

from app.auth import CurrentUser, current_user
from app.db import get_session
from app.models import Attempt, Book, Day, Lesson, Question, Section
from app.schemas import BookDetail, BookRead, TextBookRequest
from app.services.books import create_book_from_pdf, create_book_from_text
from app.views import book_detail, book_read, book_reads

router = APIRouter(tags=["books"])

MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def _require_book(session: Session, book_id: int) -> Book:
    book = session.get(Book, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="没有这本书")
    return book


@router.post("/books/pdf", response_model=BookRead)
def upload_pdf(
    title: str = Form(""),
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> BookRead:
    # 故意写成同步函数：FastAPI 会把它丢到线程池，pymupdf 就不会卡住事件循环。
    data = file.file.read()
    if not data:
        raise HTTPException(status_code=400, detail="文件是空的")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="文件太大，上限 50MB")
    book = create_book_from_pdf(
        session,
        user_id=user.id,
        title=title,
        filename=file.filename or "upload.pdf",
        data=data,
    )
    return book_read(book)


@router.post("/books/text", response_model=BookRead)
def create_text(req: TextBookRequest, session: Session = Depends(get_session)) -> BookRead:
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="文本是空的")
    return book_read(create_book_from_text(session, title=req.title, text=req.text))


@router.get("/books", response_model=list[BookRead])
def list_books(session: Session = Depends(get_session)) -> list[BookRead]:
    books = session.exec(select(Book).order_by(Book.created_at.desc())).all()  # type: ignore[attr-defined]
    return book_reads(session, list(books))


@router.get("/books/{book_id}", response_model=BookDetail)
def get_book(book_id: int, session: Session = Depends(get_session)) -> BookDetail:
    return book_detail(session, _require_book(session, book_id))


@router.delete("/books/{book_id}")
def delete_book(book_id: int, session: Session = Depends(get_session)) -> dict[str, bool]:
    book = _require_book(session, book_id)

    day_ids = [
        d.id for d in session.exec(select(Day).where(Day.book_id == book_id)).all()
    ]
    if day_ids:
        question_ids = [
            q.id
            for q in session.exec(
                select(Question).where(Question.day_id.in_(day_ids))  # type: ignore[attr-defined]
            ).all()
        ]
        if question_ids:
            for attempt in session.exec(
                select(Attempt).where(Attempt.question_id.in_(question_ids))  # type: ignore[attr-defined]
            ).all():
                session.delete(attempt)
        for question in session.exec(
            select(Question).where(Question.day_id.in_(day_ids))  # type: ignore[attr-defined]
        ).all():
            session.delete(question)
        for lesson in session.exec(
            select(Lesson).where(Lesson.day_id.in_(day_ids))  # type: ignore[attr-defined]
        ).all():
            session.delete(lesson)
        for day in session.exec(select(Day).where(Day.book_id == book_id)).all():
            session.delete(day)

    for section in session.exec(select(Section).where(Section.book_id == book_id)).all():
        session.delete(section)

    session.delete(book)
    session.commit()
    return {"deleted": True}
