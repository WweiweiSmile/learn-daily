"""学习循环：读讲解 → 出题 → 作答 → 批改。

所有会调模型的动作都只把状态置成 running 就返回，真正的活交给后台任务。
前端拿返回的 DayDetail 就能看到「正在生成」，然后继续轮询。
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.auth import CurrentUser, current_user
from app.db import get_session
from app.models import Attempt, Day, DayStatus, Lesson, Question, TaskStatus
from app.schemas import AnswerRequest, AttemptRead, DayDetail, DaySummary
from app.services import jobs, study
from app.views import attempt_read, day_detail, day_summary

router = APIRouter(tags=["study"])


def _require_day(session: Session, day_id: int) -> Day:
    day = session.get(Day, day_id)
    if day is None:
        raise HTTPException(status_code=404, detail="没有这一天")
    return day


@router.get("/days/{day_id}", response_model=DayDetail)
def get_day(day_id: int, session: Session = Depends(get_session)) -> DayDetail:
    return day_detail(session, _require_day(session, day_id))


# 下面三个接口必须是 async def：它们要起后台任务，而 asyncio.create_task 需要一个
# 正在运行的事件循环。写成同步函数的话 FastAPI 会把它丢进线程池，那里没有事件循环，
# create_task 直接抛 RuntimeError。其余只读接口保持同步，让它们继续在线程池里跑，
# 不占事件循环。
@router.post("/days/{day_id}/lesson", response_model=DayDetail)
async def start_lesson(
    day_id: int,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> DayDetail:
    day = _require_day(session, day_id)
    lesson_id = study.prepare_lesson(session, day)
    if lesson_id is not None:
        jobs.spawn(study.run_lesson(user.id, lesson_id, day_id))
    return day_detail(session, day)


@router.post("/days/{day_id}/quiz", response_model=DayDetail)
async def start_quiz(
    day_id: int,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> DayDetail:
    day = _require_day(session, day_id)

    if session.exec(select(Question).where(Question.day_id == day_id)).first():
        return day_detail(session, day)  # 已经出过题，幂等

    lesson = session.exec(select(Lesson).where(Lesson.day_id == day_id)).first()
    if not lesson or lesson.status != TaskStatus.done or not lesson.content:
        raise HTTPException(status_code=409, detail="先读完讲解再出题")

    day.quiz_status = TaskStatus.running
    day.quiz_error = None
    session.add(day)
    session.commit()

    jobs.spawn(study.run_quiz(user.id, day_id))
    session.refresh(day)
    return day_detail(session, day)


@router.post("/questions/{question_id}/attempts", response_model=AttemptRead)
async def submit_answer(
    question_id: int,
    req: AnswerRequest,
    session: Session = Depends(get_session),
    user: CurrentUser = Depends(current_user),
) -> AttemptRead:
    question = session.get(Question, question_id)
    if question is None:
        raise HTTPException(status_code=404, detail="没有这道题")

    attempt = Attempt(
        question_id=question_id,
        user_answer=req.answer,
        status=TaskStatus.running,
    )
    session.add(attempt)
    session.commit()
    session.refresh(attempt)

    jobs.spawn(study.grade_attempt(user.id, attempt.id))
    # 还在批改，先不给答案
    return attempt_read(attempt, None)


@router.get("/attempts/{attempt_id}", response_model=AttemptRead)
def get_attempt(attempt_id: int, session: Session = Depends(get_session)) -> AttemptRead:
    attempt = session.get(Attempt, attempt_id)
    if attempt is None:
        raise HTTPException(status_code=404, detail="没有这次作答")
    question = session.get(Question, attempt.question_id)
    answer_key = question.answer_key if attempt.status == TaskStatus.done and question else None
    return attempt_read(attempt, answer_key)


@router.post("/days/{day_id}/complete", response_model=DaySummary)
def complete_day(day_id: int, session: Session = Depends(get_session)) -> DaySummary:
    day = _require_day(session, day_id)
    day.status = DayStatus.done
    day.completed_at = datetime.now(timezone.utc)
    session.add(day)
    session.commit()
    session.refresh(day)
    return day_summary(session, day)


@router.post("/days/{day_id}/reopen", response_model=DaySummary)
def reopen_day(day_id: int, session: Session = Depends(get_session)) -> DaySummary:
    day = _require_day(session, day_id)
    day.status = DayStatus.pending
    day.completed_at = None
    session.add(day)
    session.commit()
    session.refresh(day)
    return day_summary(session, day)
