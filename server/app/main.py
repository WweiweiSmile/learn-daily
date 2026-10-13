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

# 认证走 Bearer token（不用 cookie），所以 allow_origins 可以是配置里的白名单。
# 留空表示不限 —— 只适合本地开发
_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins or ["*"],
    allow_methods=["*"],
    # Authorization 必须显式允许，否则浏览器会在预检里拒掉带 token 的请求
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(books.router, prefix="/api/v1")
app.include_router(days.router, prefix="/api/v1")
app.include_router(diagnosis.router, prefix="/api/v1")


@app.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}
