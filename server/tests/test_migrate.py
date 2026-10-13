"""补列迁移。

create_all 不动已有的表，所以加字段之后必须靠这个把列补上，
否则线上会直接 `no such column`。
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlmodel import SQLModel

import app.models  # noqa: F401  注册 metadata
from app.migrate import add_missing_columns


def _engine(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 't.db'}")
    SQLModel.metadata.create_all(engine)
    return engine


def _columns(engine, table: str) -> set[str]:
    return {c["name"] for c in inspect(engine).get_columns(table)}


def test_puts_back_a_missing_column(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE attempts DROP COLUMN concept"))
    assert "concept" not in _columns(engine, "attempts")

    added = add_missing_columns(engine)

    assert "attempts.concept" in added
    assert "concept" in _columns(engine, "attempts")


def test_non_nullable_column_gets_an_inline_default(tmp_path: Path) -> None:
    """SQLite 不允许加非空且无默认值的列，默认值必须内联进 DDL。"""
    engine = _engine(tmp_path)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE days DROP COLUMN quiz_status"))
        conn.execute(
            text("INSERT INTO books (title, source_type, status, total_chars, day_count, created_at) "
                 "VALUES ('t', 'text', 'ready', 0, 1, '2026-01-01 00:00:00')")
        )
        conn.execute(
            text("INSERT INTO days (book_id, day_index, title, char_count, status) "
                 "VALUES (1, 1, 'd', 0, 'pending')")
        )

    assert "days.quiz_status" in add_missing_columns(engine)

    with engine.begin() as conn:
        value = conn.execute(text("SELECT quiz_status FROM days WHERE id = 1")).scalar()
    assert value == "pending"  # 已有行拿到了默认值，不是 NULL


def test_is_idempotent(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    assert add_missing_columns(engine) == []
    assert add_missing_columns(engine) == []


def test_init_db_repairs_a_missing_column() -> None:
    """走一遍真正的启动路径。

    上面几个测试都只调 add_missing_columns，覆盖不到 init_db 里"补完之后"的那段代码——
    那一行曾经因为漏 import logging 直接让应用起不来，而测试全绿。
    """
    from app.db import engine_for, init_db
    from tests.conftest import TEST_USER_ID

    engine = engine_for(TEST_USER_ID)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE attempts DROP COLUMN concept"))
    init_db()  # 不该抛
    assert "concept" in {c["name"] for c in inspect(engine).get_columns("attempts")}
    init_db()  # 再跑一次也不该抛
