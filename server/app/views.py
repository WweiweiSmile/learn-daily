"""把 ORM 对象拼成对外的结构。路由里只做参数校验和事务，拼装都放这。"""

from __future__ import annotations

from sqlalchemy import func
from sqlmodel import Session, col, select

from app.models import (
    Attempt,
    Book,
    Concept,
    Day,
    DayStatus,
    Diagnosis,
    Lesson,
    Question,
    TaskStatus,
)
from app.schemas import (
    AttemptRead,
    BookDetail,
    BookRead,
    ConceptRead,
    DayDetail,
    DaySummary,
    DiagnosisRead,
    LessonRead,
    QuestionRead,
    SectionRead,
)
from app.services import memory
from app.services.books import sections_of


def book_read(book: Book, completed_days: int = 0) -> BookRead:
    data = BookRead.model_validate(book)
    data.completed_days = completed_days
    return data


def book_reads(session: Session, books: list[Book]) -> list[BookRead]:
    """批量版：一次查出所有书的完成天数，别在书架页上按书循环查。"""
    if not books:
        return []
    rows = session.exec(
        select(col(Day.book_id), func.count())
        .where(col(Day.book_id).in_([b.id for b in books]), Day.status == DayStatus.done)
        .group_by(col(Day.book_id))
    ).all()
    counts = {book_id: count for book_id, count in rows}
    return [book_read(book, counts.get(book.id, 0)) for book in books]


def day_summary(session: Session, day: Day) -> DaySummary:
    lesson = session.exec(select(Lesson).where(Lesson.day_id == day.id)).first()
    question_count = len(session.exec(select(Question).where(Question.day_id == day.id)).all())
    return DaySummary(
        id=day.id,
        day_index=day.day_index,
        title=day.title,
        char_count=day.char_count,
        status=day.status,
        section_count=len(day.section_ids),
        has_lesson=bool(lesson and lesson.status == TaskStatus.done),
        question_count=question_count,
    )


def book_detail(session: Session, book: Book) -> BookDetail:
    days = session.exec(select(Day).where(Day.book_id == book.id).order_by(Day.day_index)).all()
    completed = len([d for d in days if d.status == DayStatus.done])
    return BookDetail(
        book=book_read(book, completed),
        days=[day_summary(session, day) for day in days],
    )


def attempt_read(attempt: Attempt, answer_key: str | None) -> AttemptRead:
    return AttemptRead(
        id=attempt.id,
        question_id=attempt.question_id,
        user_answer=attempt.user_answer,
        concept=attempt.concept,
        status=attempt.status,
        verdict=attempt.verdict,
        score=attempt.score,
        got_right=attempt.got_right,
        got_wrong=attempt.got_wrong,
        guidance=attempt.guidance,
        takeaway=attempt.takeaway,
        error=attempt.error,
        answer_key=answer_key,
    )


def day_detail(session: Session, day: Day) -> DayDetail:
    sections = sections_of(session, day)
    lesson = session.exec(select(Lesson).where(Lesson.day_id == day.id)).first()
    questions = session.exec(
        select(Question).where(Question.day_id == day.id).order_by(Question.idx)
    ).all()

    question_ids = [q.id for q in questions]
    attempts: list[Attempt] = []
    if question_ids:
        attempts = list(
            session.exec(
                select(Attempt)
                .where(Attempt.question_id.in_(question_ids))  # type: ignore[attr-defined]
                .order_by(Attempt.created_at)
            ).all()
        )

    answer_keys = {q.id: q.answer_key for q in questions}

    return DayDetail(
        id=day.id,
        day_index=day.day_index,
        title=day.title,
        status=day.status,
        char_count=day.char_count,
        sections=[SectionRead(id=s.id, title=s.title, content=s.content) for s in sections],
        lesson=(
            LessonRead(status=lesson.status, content=lesson.content, error=lesson.error)
            if lesson
            else None
        ),
        quiz_status=day.quiz_status,
        quiz_error=day.quiz_error,
        questions=[
            QuestionRead(id=q.id, idx=q.idx, kind=q.kind, stem=q.stem, options=q.options)
            for q in questions
        ],
        attempts=[
            attempt_read(a, answer_keys.get(a.question_id) if a.status == TaskStatus.done else None)
            for a in attempts
        ],
        concepts=[
            ConceptRead(id=c.id, day_id=c.day_id, name=c.name, summary=c.summary)
            for c in session.exec(
                select(Concept).where(Concept.day_id == day.id).order_by(col(Concept.id))
            ).all()
        ],
    )


def diagnosis_read(session: Session, row: Diagnosis | None, book_id: int | None) -> DiagnosisRead:
    concepts, misconceptions, graded = memory.evidence_counts(session, book_id)
    evidence = {
        "concepts": concepts,
        "misconceptions": misconceptions,
        "graded": graded,
    }
    if row is None:
        return DiagnosisRead(book_id=book_id, status="pending", evidence=evidence)
    return DiagnosisRead(
        id=row.id,
        book_id=row.book_id,
        status=row.status,
        error=row.error,
        result=row.result,
        is_stale=memory.is_stale(session, row),
        evidence=evidence,
    )
