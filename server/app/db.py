"""SQLite 连接与会话。

**每个用户一个数据库文件**（`data/users/{user_id}.db`）。

为什么不用「一张表加 user_id 列」：那要求每个查询都记得加过滤，而漏掉一处就是
越权读别人的数据 —— 漏的方式有无数种，`session.get(Day, id)` 这种按主键取的地方
最容易忘。分文件之后越权在**物理上**不可能发生，而且只需要在一处（下面的
`get_session`）选对 engine，没有第二处可漏。
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import Depends
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from app.auth import CurrentUser, current_user
from app.config import settings

logger = logging.getLogger(__name__)

settings.users_dir.mkdir(parents=True, exist_ok=True)

_engines: dict[int, Engine] = {}


def _make_engine(user_id: int) -> Engine:
    return create_engine(
        settings.database_url_for(user_id),
        # check_same_thread=False：请求可能在不同线程里跑，后台任务又会另起线程写状态
        # timeout：SQLite 默认一撞锁就报错，让它等一会儿 —— 后台任务写状态
        #          和前端轮询读状态是会真的撞上的
        connect_args={"check_same_thread": False, "timeout": 30},
    )


def engine_for(user_id: int) -> Engine:
    """取某个用户的数据库引擎。第一次用到时建库建表

    懒加载：新用户首次访问才建文件，不用在启动时预建每个人
    """
    engine = _engines.get(user_id)
    if engine is None:
        engine = _make_engine(user_id)
        _engines[user_id] = engine
        _initialize(engine)
        logger.info("用户 %s 的数据库已就绪", user_id)
    return engine


def _initialize(engine: Engine) -> None:
    import app.models  # noqa: F401  建表前确保模型已经注册到 metadata
    from app.migrate import add_missing_columns

    SQLModel.metadata.create_all(engine)
    # create_all 不动已有的表，新增的列得单独补
    added = add_missing_columns(engine)
    if added:
        logger.info("补了 %d 列：%s", len(added), "、".join(added))


def init_db() -> None:
    """启动时把**已有**的用户库都过一遍。

    新用户是懒加载的，但已有用户的库必须在启动时补列 —— 否则加了字段之后，
    老用户要等到下次访问才发现表结构不对，而那时已经在报错了
    """
    count = 0
    for path in sorted(settings.users_dir.glob("*.db")):
        try:
            user_id = int(path.stem)
        except ValueError:
            logger.warning("忽略不认识的文件：%s", path.name)
            continue

        # 刻意不走 engine_for：它对**已经缓存的**引擎不会再初始化，
        # 而这里要的是「无论如何都把已有库检查一遍」
        engine = _engines.get(user_id) or _make_engine(user_id)
        _engines[user_id] = engine
        _initialize(engine)
        count += 1

    if count:
        logger.info("已检查 %d 个用户库", count)


@contextmanager
def session_for(user_id: int) -> Iterator[Session]:
    """给后台任务用。

    它们**不能**复用请求的会话 —— 请求一结束会话就关了，
    所以每个任务自己按 user_id 开一个
    """
    with Session(engine_for(user_id)) as session:
        yield session


def get_session(user: CurrentUser = Depends(current_user)) -> Iterator[Session]:
    """请求用的会话。

    **它依赖 current_user，所以每个用到它的端点都自动要求登录** ——
    路由函数一行都不用改就获得了鉴权。

    返回的是这个用户**自己的库**的会话，越权读别人的数据在物理上不可能
    """
    with Session(engine_for(user.id)) as session:
        yield session
