"""诊断：直接回答「我学到了什么、我还差什么」。

不带 book_id 就是整个书架的总诊断。同一时刻同一个范围只允许一份在生成。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.auth import CurrentUser, current_user
from app.db import get_session
from app.models import Book, Diagnosis, TaskStatus
from app.schemas import DiagnosisRead
from app.services import jobs, memory
from app.views import diagnosis_read

router = APIRouter(tags=["diagnosis"])


def _check_book(session: Session, book_id: int | None) -> None:
    if book_id is not None and session.get(Book, book_id) is None:
        raise HTTPException(status_code=404, detail="没有这本书")


@router.get("/diagnosis", response_model=DiagnosisRead)
def get_diagnosis(
    book_id: int | None = None,
    session: Session = Depends(get_session),
) -> DiagnosisRead:
    _check_book(session, book_id)
    return diagnosis_read(session, memory.latest_diagnosis(session, book_id), book_id)


@router.post("/diagnosis", response_model=DiagnosisRead)
async def start_diagnosis(
    book_id: int | None = None,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> DiagnosisRead:
    _check_book(session, book_id)

    current = memory.latest_diagnosis(session, book_id)
    if current is not None and current.status == TaskStatus.running:
        return diagnosis_read(session, current, book_id)  # 已经在跑了，别重复起

    diagnosis_id = memory.prepare_diagnosis(session, book_id)
    jobs.spawn(memory.generate_diagnosis(user.id, diagnosis_id))
    return diagnosis_read(session, session.get(Diagnosis, diagnosis_id), book_id)
