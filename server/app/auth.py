"""认证：验证认证中心（call-auth）签发的 RS256 令牌。

本服务**只验签、不签发**。签发权归认证中心，它持私钥，我们拿公钥（JWKS）。
这样新增服务不用分发任何密钥，任何一个服务被攻破也伪造不了 token。

验签是拿本地缓存的公钥做的**纯计算**，认证中心不在请求路径上 ——
每个业务请求都不会去连它。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import Header, HTTPException
from jwt import PyJWKClient

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CurrentUser:
    """当前请求的发起者。由 token 的 claims 解出，不查库"""

    id: int
    username: str
    role: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


@lru_cache(maxsize=1)
def _jwks_client() -> PyJWKClient:
    """公钥客户端。只建一次。

    PyJWKClient 自带缓存：同一个 kid 只拉一次，认证中心轮换密钥后按新 kid 再拉。
    lifespan 是密钥集本身的缓存时长
    """
    return PyJWKClient(
        settings.auth_jwks_url,
        cache_keys=True,
        lifespan=3600,
        timeout=settings.auth_jwks_timeout,
    )


def _unauthorized() -> HTTPException:
    # 统一一句文案，不区分「没带」「格式错」「过期」——
    # 对使用者来说处理方式都一样：重新登录
    return HTTPException(status_code=401, detail="登录态已失效，请重新登录", headers={"WWW-Authenticate": "Bearer"})


def verify_token(token: str) -> CurrentUser:
    """验签并解出用户。失败一律抛 401"""
    try:
        signing_key = _jwks_client().get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            # 显式指定算法。不指定的话，攻击者可以把 header 的 alg 改成 none
            # 或换成别的算法，让验签形同虚设 —— JWT 最经典的漏洞
            algorithms=["RS256"],
            issuer=settings.auth_issuer,
            # aud 必须包含本服务。没有这条，签给别的服务的 token 能拿来调这里
            audience=settings.auth_audience,
            leeway=settings.auth_leeway_seconds,
            # 这些 claim 必须存在。光「校验 exp」不够：不要求存在的话，
            # 一个不带 exp 的 token 会直接绕过过期检查
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
        )
    except jwt.PyJWTError as exc:
        logger.info("令牌校验失败: %s", exc)
        raise _unauthorized() from exc

    # 用户 id 在 sub 里（JWT 规范要求 sub 是字符串），取出来自己转
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        logger.warning("token 的 sub 不是合法的用户 id: %r", payload.get("sub"))
        raise _unauthorized() from exc

    return CurrentUser(
        id=user_id,
        username=str(payload.get("username") or ""),
        role=str(payload.get("role") or "user"),
    )


def current_user(authorization: str | None = Header(default=None)) -> CurrentUser:
    """FastAPI 依赖：从 Authorization 头解出当前用户。

    任何依赖它的端点都会自动要求登录 —— 包括下层的 get_session，
    所以路由函数一行都不用改就获得了鉴权
    """
    if not authorization:
        raise _unauthorized()

    parts = authorization.split(" ", 1)
    # scheme 大小写不敏感（RFC 7235）
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise _unauthorized()

    return verify_token(parts[1].strip())
