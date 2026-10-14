"""learn-daily 后端入口。

启动：
    uv run uvicorn app.main:app --reload --port 8010
端口用 8010，避开 call-back 的 8080/8090 和 poker-ocr 的 8000。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import init_db
from app.routers import books, days, diagnosis

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


app = FastAPI(title="learn-daily", lifespan=lifespan)

def _csv(value: str) -> list[str]:
    """把 "a, b ,c" 拆成 ["a", "b", "c"]，顺带丢掉空项"""
    return [v.strip() for v in value.split(",") if v.strip()]


# CORS 全从 .env 读（见 config.py 的 cors_* 三项），改白名单不用动代码。
# 认证走 Bearer token（不用 cookie），所以来源用白名单而不是全放行。
app.add_middleware(
    CORSMiddleware,
    allow_origins=_csv(settings.cors_origins) or ["*"],
    # 方法默认 "*" 就含 OPTIONS，跨域预检才会通过
    allow_methods=_csv(settings.cors_allow_methods) or ["*"],
    # Authorization 必须在允许头里，否则带 token 的跨域请求会在预检被拒
    allow_headers=_csv(settings.cors_allow_headers) or ["*"],
)

app.include_router(books.router, prefix="/api/v1")
app.include_router(days.router, prefix="/api/v1")
app.include_router(diagnosis.router, prefix="/api/v1")


@app.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}
