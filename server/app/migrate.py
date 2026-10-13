"""启动时给已有的表补上新增的列。

`create_all` 只负责建**缺失的表**，不会动已有的表——开发期加一个字段，
下次启动就会撞上 `no such column: xxx`。这里做一件很有限的事：把模型里有、
库里没有的列 ALTER 进去。

**只管新增列。** 改类型、删列、加索引、改数据，都得手写迁移脚本。
SQLite 的 ALTER TABLE 本来也只支持 ADD COLUMN，限制正好对上。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import Engine, inspect, text
from sqlalchemy.schema import CreateColumn
from sqlmodel import SQLModel

logger = logging.getLogger(__name__)


def add_missing_columns(engine: Engine) -> list[str]:
    """返回补上的列名列表，方便启动日志里说清楚到底动了什么。"""
    tables = set(inspect(engine).get_table_names())
    added: list[str] = []

    for table in SQLModel.metadata.sorted_tables:
        if table.name not in tables:
            continue
        present = {c["name"] for c in inspect(engine).get_columns(table.name)}
        for column in table.columns:
            if column.name in present:
                continue

            ddl = str(CreateColumn(column).compile(dialect=engine.dialect))
            if not column.nullable:
                # SQLite 不允许加一个非空又没有默认值的列，得把默认值内联进 DDL。
                literal = _literal_default(column)
                if literal is None:
                    logger.warning(
                        "%s.%s 非空但拿不到可内联的默认值，跳过——这一列得手写迁移",
                        table.name,
                        column.name,
                    )
                    continue
                ddl += f" DEFAULT {literal}"

            with engine.begin() as conn:
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN {ddl}'))
            added.append(f"{table.name}.{column.name}")
            logger.info("补上新增列 %s.%s", table.name, column.name)

    return added


def _literal_default(column: Any) -> str | None:
    """把 Python 端的默认值转成能写进 DDL 的字面量。拿不到就返回 None。"""
    default = getattr(column, "default", None)
    if default is None or not getattr(default, "is_scalar", False):
        return None

    value = default.arg
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        # str 枚举走这里也成立：它的字符串内容就是枚举值本身
        return "'" + value.replace("'", "''") + "'"
    return None
