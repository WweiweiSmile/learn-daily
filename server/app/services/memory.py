"""AI 记忆与诊断——「我学到了什么、我还差什么」。

两个刻意的设计：

1. **不用向量检索。** 概念和错题的量都很小（一本书几十条），全量喂给模型比
   检索更准，也省掉一整套 embedding 基础设施。DeepSeek 本身也没有 embedding 接口。

2. **错题按证据行累加，不做「掌握度百分比」。** 同一个概念错三次就该看到三条，
   那三条本身就是「反复出错」这个信号；压成一个 60% 反而把它抹平了。

诊断的时效性靠证据计数判断：库里现在的证据量和上次生成时记录的对不上，就是过期了。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import desc
from sqlmodel import Session, col, select

from app import llm, prompts
from app.db import session_for
from app.models import (
    Attempt,
    Book,
    Concept,
    Day,
    Diagnosis,
    Lesson,
    Misconception,
    Question,
    TaskStatus,
)
from app.services.books import day_text, sections_of

logger = logging.getLogger(__name__)

# 喂给诊断的证据上限。超出就只取最近的，并在 prompt 里说明被截断了——
# 悄悄丢掉一部分证据会让诊断结论站不住脚。
MAX_ATTEMPTS = 80
MAX_MISCONCEPTIONS = 50

_SYSTEM_DIAGNOSER = (
    "你是一位学习诊断老师。只依据用户给出的证据下结论，不臆测没有证据的部分。"
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- 概念


async def extract_concepts(user_id: int, day_id: int) -> None:
    """讲解生成完之后跑，把这一天的核心概念沉淀下来。"""
    with session_for(user_id) as session:
        if session.exec(select(Concept).where(Concept.day_id == day_id)).first():
            return  # 幂等
        day = session.get(Day, day_id)
        if day is None:
            return
        lesson = session.exec(select(Lesson).where(Lesson.day_id == day_id)).first()
        book = session.get(Book, day.book_id)
        if not lesson or not lesson.content:
            return
        message = prompts.render(
            "concepts",
            book_title=book.title if book else "这本书",
            day_title=day.title,
            lesson=lesson.content,
            content=day_text(sections_of(session, day)),
        )
        book_id = day.book_id

    try:
        payload = await llm.complete_json(
            [
                {"role": "system", "content": _SYSTEM_DIAGNOSER},
                {"role": "user", "content": message},
            ]
        )
    except Exception:  # noqa: BLE001 — 抽概念失败不该影响学习流程，记一条日志就够
        logger.exception("抽概念失败 day=%s", day_id)
        return

    rows = payload.get("concepts") if isinstance(payload, dict) else None
    if not rows:
        return

    with session_for(user_id) as session:
        if session.exec(select(Concept).where(Concept.day_id == day_id)).first():
            return  # 并发下可能已经被另一个任务写进去了
        concepts = []
        for raw in rows[:3]:
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("name") or "").strip()
            if not name:
                continue
            concepts.append(
                Concept(
                    day_id=day_id,
                    book_id=book_id,
                    name=name,
                    summary=str(raw.get("summary") or "").strip(),
                )
            )
        if concepts:
            session.add_all(concepts)
            session.commit()
            logger.info("day=%s 抽出 %d 个概念", day_id, len(concepts))


# --------------------------------------------------------------------------- 错题


def record_misconception(
    session: Session,
    *,
    attempt: Attempt,
    question: Question,
    concept: str,
    what_went_wrong: list[str],
) -> None:
    """答错或部分对时留一条证据。

    由调用方（批改任务）保证只在 verdict 不是 correct 时调用。
    """
    day = session.get(Day, question.day_id)
    if day is None:
        return
    session.add(
        Misconception(
            attempt_id=attempt.id,
            question_id=question.id,
            day_id=day.id,
            book_id=day.book_id,
            concept=concept,
            what_went_wrong="；".join(what_went_wrong),
            user_answer=attempt.user_answer,
        )
    )
    session.commit()


# --------------------------------------------------------------------------- 诊断


def evidence_counts(session: Session, book_id: int | None) -> tuple[int, int, int]:
    """(概念数, 错题数, 已批改作答数)"""
    concept_stmt = select(Concept)
    misconception_stmt = select(Misconception)
    if book_id is not None:
        concept_stmt = concept_stmt.where(Concept.book_id == book_id)
        misconception_stmt = misconception_stmt.where(Misconception.book_id == book_id)

    concepts = len(session.exec(concept_stmt).all())
    misconceptions = len(session.exec(misconception_stmt).all())
    graded = len(_graded_attempts(session, book_id))
    return concepts, misconceptions, graded


def latest_diagnosis(session: Session, book_id: int | None) -> Diagnosis | None:
    stmt = select(Diagnosis).where(
        Diagnosis.book_id == book_id if book_id is not None else col(Diagnosis.book_id).is_(None)
    )
    return session.exec(stmt.order_by(desc(col(Diagnosis.id)))).first()


def is_stale(session: Session, diagnosis: Diagnosis) -> bool:
    if diagnosis.status != TaskStatus.done:
        return False
    return evidence_counts(session, diagnosis.book_id) != (
        diagnosis.concept_count,
        diagnosis.misconception_count,
        diagnosis.graded_count,
    )


def prepare_diagnosis(session: Session, book_id: int | None) -> int:
    """在请求里同步建好这行诊断（置 running），返回 id。"""
    concepts, misconceptions, graded = evidence_counts(session, book_id)
    row = Diagnosis(
        book_id=book_id,
        status=TaskStatus.running,
        concept_count=concepts,
        misconception_count=misconceptions,
        graded_count=graded,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row.id


async def generate_diagnosis(user_id: int, diagnosis_id: int) -> None:
    with session_for(user_id) as session:
        row = session.get(Diagnosis, diagnosis_id)
        if row is None:
            return
        book_id = row.book_id
        book = session.get(Book, book_id) if book_id is not None else None

        concepts = _concepts(session, book_id)
        attempts = _graded_attempts(session, book_id)
        misconceptions = _misconceptions(session, book_id)
        tested = {a.concept for a in attempts if a.concept}

        truncated = []
        if len(attempts) > MAX_ATTEMPTS:
            truncated.append(f"答题记录只取了最近 {MAX_ATTEMPTS} 条")
            attempts = attempts[:MAX_ATTEMPTS]
        if len(misconceptions) > MAX_MISCONCEPTIONS:
            truncated.append(f"错题只取了最近 {MAX_MISCONCEPTIONS} 条")
            misconceptions = misconceptions[:MAX_MISCONCEPTIONS]

        scope_block = (
            f"范围：《{book.title}》" if book else "范围：全部书目"
        )
        if truncated:
            scope_block += "\n注意：" + "；".join(truncated) + "。"

        message = prompts.render(
            "diagnosis",
            scope_block=scope_block,
            concepts_block=_concepts_block(concepts, tested),
            attempts_block=_attempts_block(session, attempts),
            misconceptions_block=_misconceptions_block(misconceptions),
        )

    try:
        payload = await llm.complete_json(
            [
                {"role": "system", "content": _SYSTEM_DIAGNOSER},
                {"role": "user", "content": message},
            ]
        )
        if not isinstance(payload, dict):
            raise llm.LLMError("诊断结果格式不对")
    except Exception as exc:  # noqa: BLE001
        logger.exception("生成诊断失败 diagnosis=%s", diagnosis_id)
        _finish_diagnosis(user_id, diagnosis_id, error=str(exc))
        return

    _finish_diagnosis(user_id, diagnosis_id, result=_normalize(payload))


def _normalize(payload: dict) -> dict:
    """把模型输出收拢成固定形状，缺字段就补空，免得前端到处判空。"""

    def dicts(key: str, fields: tuple[str, ...]) -> list[dict]:
        out = []
        for raw in payload.get(key) or []:
            if isinstance(raw, dict):
                out.append({f: str(raw.get(f) or "").strip() for f in fields})
            elif isinstance(raw, str) and raw.strip():
                out.append({fields[0]: raw.strip(), **{f: "" for f in fields[1:]}})
        return out

    return {
        "summary": str(payload.get("summary") or "").strip(),
        "learned": dicts("learned", ("concept", "evidence")),
        "gaps": dicts("gaps", ("concept", "evidence", "suggestion")),
        "blind_spots": [str(x).strip() for x in (payload.get("blind_spots") or []) if str(x).strip()],
        "pattern": str(payload.get("pattern") or "").strip(),
        "next_steps": [str(x).strip() for x in (payload.get("next_steps") or []) if str(x).strip()],
    }


def _finish_diagnosis(
    user_id: int, diagnosis_id: int, *, result: dict | None = None, error: str | None = None
) -> None:
    with session_for(user_id) as session:
        row = session.get(Diagnosis, diagnosis_id)
        if row is None:
            return
        if error:
            row.status = TaskStatus.failed
            row.error = error
        else:
            row.status = TaskStatus.done
            row.result = result
        row.updated_at = _now()
        session.add(row)
        session.commit()


# --------------------------------------------------------------------------- 取证据


def _concepts(session: Session, book_id: int | None) -> list[Concept]:
    stmt = select(Concept)
    if book_id is not None:
        stmt = stmt.where(Concept.book_id == book_id)
    return list(session.exec(stmt.order_by(col(Concept.id))).all())


def _graded_attempts(session: Session, book_id: int | None) -> list[Attempt]:
    stmt = select(Attempt).where(Attempt.status == TaskStatus.done)
    if book_id is not None:
        day_ids = [d.id for d in session.exec(select(Day).where(Day.book_id == book_id)).all()]
        if not day_ids:
            return []
        qids = [
            q.id
            for q in session.exec(select(Question).where(col(Question.day_id).in_(day_ids))).all()
        ]
        if not qids:
            return []
        stmt = stmt.where(col(Attempt.question_id).in_(qids))
    return list(session.exec(stmt.order_by(desc(col(Attempt.created_at)))).all())


def _misconceptions(session: Session, book_id: int | None) -> list[Misconception]:
    stmt = select(Misconception)
    if book_id is not None:
        stmt = stmt.where(Misconception.book_id == book_id)
    return list(session.exec(stmt.order_by(desc(col(Misconception.created_at)))).all())


def _concepts_block(concepts: list[Concept], tested: set[str]) -> str:
    if not concepts:
        return "（还没有学过任何概念）"
    lines = []
    for c in concepts:
        mark = "已被检验" if c.name in tested else "**从未被检验**"
        lines.append(f"- {c.name}（{mark}）：{c.summary}")
    return "\n".join(lines)


def _attempts_block(session: Session, attempts: list[Attempt]) -> str:
    if not attempts:
        return "（还没有任何作答）"
    labels = {"correct": "正确", "partial": "部分正确", "off": "偏离"}
    lines = []
    for a in attempts:
        concept = a.concept or "（未标注）"
        verdict = labels.get(a.verdict or "", a.verdict or "?")
        lines.append(f"- [{verdict}] 概念「{concept}」 → 学生答：{_clip(a.user_answer)}")
    return "\n".join(lines)


def _misconceptions_block(misconceptions: list[Misconception]) -> str:
    if not misconceptions:
        return "（还没有答错过）"
    lines = []
    for m in misconceptions:
        lines.append(f"- 概念「{m.concept or '未标注'}」：{_clip(m.what_went_wrong, 300)}")
    return "\n".join(lines)


def _clip(text: str, limit: int = 120) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit] + "…"
