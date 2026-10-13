"""数据表。

M1 的链路：Book --(解析)--> Section --(按天切分)--> Day --(生成)--> Lesson / Question
                                                Question --(作答)--> Attempt
"""

from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(timezone.utc)


class BookStatus(str, Enum):
    parsing = "parsing"
    ready = "ready"
    failed = "failed"


class TaskStatus(str, Enum):
    """讲解/出题/批改共用的异步任务状态。前端靠它轮询。"""

    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"


class DayStatus(str, Enum):
    pending = "pending"
    done = "done"


class QuestionKind(str, Enum):
    single = "single"  # 单选，确定性判分
    short = "short"  # 简答，AI 按 rubric 批改


class Book(SQLModel, table=True):
    __tablename__ = "books"

    id: int | None = Field(default=None, primary_key=True)
    title: str
    source_filename: str | None = None
    source_type: str = "pdf"  # pdf | text
    status: str = BookStatus.parsing
    error: str | None = None
    warning: str | None = None  # 非致命问题，比如「疑似扫描版，文字层很少」
    total_chars: int = 0
    day_count: int = 0
    created_at: datetime = Field(default_factory=_now)


class Section(SQLModel, table=True):
    """书里的一个自然块（章/节）。按天切分的最小单位。"""

    __tablename__ = "sections"

    id: int | None = Field(default=None, primary_key=True)
    book_id: int = Field(index=True, foreign_key="books.id")
    idx: int
    title: str | None = None
    content: str
    char_count: int


class Day(SQLModel, table=True):
    """一天的学习单元，由一到多个 Section 组成。"""

    __tablename__ = "days"

    id: int | None = Field(default=None, primary_key=True)
    book_id: int = Field(index=True, foreign_key="books.id")
    day_index: int  # 从 1 开始
    title: str
    section_ids: list[int] = Field(default_factory=list, sa_column=Column(JSON))
    char_count: int = 0
    status: str = DayStatus.pending
    # 出题没有自己的内容表（题目在 questions 里），所以进度状态挂在 day 上。
    # 讲解有 lessons 表，状态跟着那边走。
    quiz_status: str = TaskStatus.pending
    quiz_error: str | None = None
    completed_at: datetime | None = None


class Lesson(SQLModel, table=True):
    """某一天的 AI 讲解。异步生成，客户端轮询 status。"""

    __tablename__ = "lessons"

    id: int | None = Field(default=None, primary_key=True)
    day_id: int = Field(index=True, foreign_key="days.id")
    status: str = TaskStatus.pending
    content: str | None = None
    error: str | None = None
    prompt_version: str = "v1"
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class Question(SQLModel, table=True):
    __tablename__ = "questions"

    id: int | None = Field(default=None, primary_key=True)
    day_id: int = Field(index=True, foreign_key="days.id")
    idx: int
    kind: str = QuestionKind.short
    stem: str
    options: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    answer_key: str = ""
    rubric: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    common_mistakes: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_now)


class Concept(SQLModel, table=True):
    """某一天的讲解里抽出来的核心概念。

    这是「AI 记忆」的骨架：有了它，才能说清「你学过哪些东西」，
    也才能把答错的题挂回到具体概念上。
    """

    __tablename__ = "concepts"

    id: int | None = Field(default=None, primary_key=True)
    day_id: int = Field(index=True, foreign_key="days.id")
    book_id: int = Field(index=True, foreign_key="books.id")
    name: str
    summary: str = ""
    created_at: datetime = Field(default_factory=_now)


class Misconception(SQLModel, table=True):
    """一次答错/部分对留下的证据行。

    刻意不做覆盖写：同一个概念错三次，就该看到三条，那是「反复出错」的信号，
    比一句「该概念掌握度 60%」有用得多。
    """

    __tablename__ = "misconceptions"

    id: int | None = Field(default=None, primary_key=True)
    attempt_id: int = Field(index=True, foreign_key="attempts.id")
    question_id: int = Field(index=True, foreign_key="questions.id")
    day_id: int = Field(index=True, foreign_key="days.id")
    book_id: int = Field(index=True, foreign_key="books.id")
    concept: str = ""
    what_went_wrong: str = ""
    user_answer: str = ""
    created_at: datetime = Field(default_factory=_now)


class Diagnosis(SQLModel, table=True):
    """按需生成的诊断摘要。

    book_id 为空表示整本书架的总诊断（跨书）。证据数用来判断摘要是不是过期了。
    """

    __tablename__ = "diagnoses"

    id: int | None = Field(default=None, primary_key=True)
    book_id: int | None = Field(default=None, index=True, foreign_key="books.id")
    status: str = TaskStatus.pending
    error: str | None = None
    result: dict | None = Field(default=None, sa_column=Column(JSON))
    # 生成这份摘要时用到的证据量，用来判断要不要重算
    concept_count: int = 0
    misconception_count: int = 0
    graded_count: int = 0
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class Attempt(SQLModel, table=True):
    """学生对一道题的作答 + AI 批改结果。"""

    __tablename__ = "attempts"

    id: int | None = Field(default=None, primary_key=True)
    question_id: int = Field(index=True, foreign_key="questions.id")
    user_answer: str
    # 这道题考查的概念，由批改时模型给出。诊断就是靠它把多次作答串起来的。
    concept: str = ""
    status: str = TaskStatus.pending
    # 批改结果。确定性判分的单选也走同一套结构，只是由代码填。
    verdict: str | None = None  # correct | partial | off
    score: int | None = None
    got_right: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    got_wrong: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    guidance: str | None = None
    takeaway: str | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=_now)
