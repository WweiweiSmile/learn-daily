"""后台任务。

长任务（讲解 / 出题 / 批改）不占着 HTTP 请求，而是把状态落库、由前端轮询。
一个模型调用可能跑几分钟，用同步请求扛着会撞上传超时和网关超时。

两个坑：

1. 任务里**不能**复用请求的数据库会话——请求一结束会话就关了。每个任务自己开。
2. asyncio 对 task 只保留弱引用。不在模块里存一份的话，任务可能跑到一半被回收。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from typing import Any

logger = logging.getLogger(__name__)

_running: set[asyncio.Task[Any]] = set()


def spawn(coro: Coroutine[Any, Any, None]) -> None:
    task = asyncio.create_task(coro)
    _running.add(task)

    def _done(finished: asyncio.Task[Any]) -> None:
        _running.discard(finished)
        if finished.cancelled():
            return
        exc = finished.exception()
        if exc is not None:
            # 正常情况下各 service 已经自己把 failed 写进库了，
            # 走到这里说明是没预料到的异常，至少别让它静默消失。
            logger.error("后台任务异常", exc_info=exc)

    task.add_done_callback(_done)
