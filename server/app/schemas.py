"""对外返回的结构。

两条刻意为之的规则：
- 题目**不带** answer_key，答案只在答完之后的 AttemptRead 里给，免得前端不小心把它渲染出来。
- 所有长任务都返回当前状态而不是结果，前端靠轮询 day 详情拿最终内容。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlmodel import SQLModel


class BookRead(SQLModel):
    id: int
    title: str
    source_filename: str | None = None
    source_type: str
    status: str
    error: str | None = None
    warning: str | None = None
    total_chars: int
    day_count: int
    completed_days: int = 0
    created_at: datetime


class DaySummary(SQLModel):
    id: int
    day_index: int
    title: str
    char_count: int
    status: str
    section_count: int
    has_lesson: bool
    question_count: int


class BookDetail(SQLModel):
    book: BookRead
    days: list[DaySummary]


class SectionRead(SQLModel):
    id: int
    title: str | None = None
    content: str


class LessonRead(SQLModel):
    status: str
    content: str | None = None
    error: str | None = None


class QuestionRead(SQLModel):
    id: int
    idx: int
    kind: str
    stem: str
    options: list[str]


class ConceptRead(SQLModel):
    id: int
    day_id: int
    name: str
    summary: str


class AttemptRead(SQLModel):
    id: int
    question_id: int
    user_answer: str
    concept: str = ""
    status: str
    verdict: str | None = None
    score: int | None = None
    got_right: list[str] = []
    got_wrong: list[str] = []
    guidance: str | None = None
    takeaway: str | None = None
    error: str | None = None
    # 答完才给参考答案
    answer_key: str | None = None


class DayDetail(SQLModel):
    id: int
    day_index: int
    title: str
    status: str
    char_count: int
    sections: list[SectionRead]
    lesson: LessonRead | None = None
    quiz_status: str
    quiz_error: str | None = None
    questions: list[QuestionRead]
    attempts: list[AttemptRead]
    concepts: list[ConceptRead]


class DiagnosisRead(SQLModel):
    """诊断。result 的结构见 app/prompts/diagnosis.md。"""

    id: int | None = None
    book_id: int | None = None
    status: str = "pending"
    error: str | None = None
    result: dict[str, Any] | None = None
    # 上次生成之后又攒了新证据，前端可以提示「可以重新诊断了」
    is_stale: bool = False
    # 当前证据量：{"concepts": n, "misconceptions": n, "graded": n}
    evidence: dict[str, int] = {}


class TextBookRequest(SQLModel):
    title: str = ""
    text: str


class AnswerRequest(SQLModel):
    answer: str
