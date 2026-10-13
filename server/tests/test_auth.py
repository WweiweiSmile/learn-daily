"""认证与数据隔离。

这是接入认证中心之后最关键的两条性质：
1. 没有有效令牌就进不来（验签本身）
2. 进来了也只能看到自己的数据（物理隔离）

第 2 条靠「每用户一个数据库文件」实现，所以这里验证的是「文件选对了没有」。
"""

from __future__ import annotations

import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app import auth
from app.main import app

ISSUER = "call-auth"
AUDIENCE = "learn-daily"

TEXT = "# 第一章\n\n" + "正文。" * 100


@pytest.fixture(scope="module")
def keys():
    """造一对 RSA 密钥，冒充认证中心"""
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private


@pytest.fixture(autouse=True)
def stub_jwks(keys, monkeypatch):
    """把验签用的公钥换成我们自己的。

    不打真认证中心：单元测试不该依赖外部服务在不在
    """

    class FakeSigningKey:
        def __init__(self, key):
            self.key = key

    class FakeJWKSClient:
        def get_signing_key_from_jwt(self, token):
            return FakeSigningKey(keys.public_key())

    monkeypatch.setattr(auth, "_jwks_client", lambda: FakeJWKSClient())


def make_token(keys, *, sub: str = "1", iss: str = ISSUER, aud: str = AUDIENCE,
               ttl: int = 900, algorithm: str = "RS256", **extra) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": sub,
        "iss": iss,
        "aud": aud,
        "iat": now,
        "exp": now + ttl,
        "jti": "test-jti",
        "username": f"user{sub}",
        "role": "user",
        **extra,
    }
    # alg=none 时 PyJWT 要求 key 必须是 None（传字符串它会直接报错）
    key = None if algorithm == "none" else keys
    return jwt.encode(payload, key, algorithm=algorithm)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------- 验签


def test_valid_token_is_accepted(keys, no_fake_user) -> None:
    with TestClient(app) as client:
        res = client.get("/api/v1/books", headers=bearer(make_token(keys)))
    assert res.status_code == 200, res.text


def test_missing_header_is_rejected(no_fake_user) -> None:
    with TestClient(app) as client:
        assert client.get("/api/v1/books").status_code == 401


def test_malformed_header_is_rejected(keys, no_fake_user) -> None:
    with TestClient(app) as client:
        for value in ["", "Bearer", "Basic abc", "Token abc", f"Bearer {'x' * 20}"]:
            res = client.get("/api/v1/books", headers={"Authorization": value})
            assert res.status_code == 401, f"{value!r} 应被拒绝，实际 {res.status_code}"


def test_expired_token_is_rejected(keys, no_fake_user) -> None:
    with TestClient(app) as client:
        # leeway 是 60 秒，所以过期 5 分钟才确定被拒
        res = client.get("/api/v1/books", headers=bearer(make_token(keys, ttl=-300)))
    assert res.status_code == 401


def test_wrong_issuer_is_rejected(keys, no_fake_user) -> None:
    with TestClient(app) as client:
        token = make_token(keys, iss="somebody-else")
        assert client.get("/api/v1/books", headers=bearer(token)).status_code == 401


def test_wrong_audience_is_rejected(keys, no_fake_user) -> None:
    """签给别服务的 token 不能拿来调这里"""
    with TestClient(app) as client:
        token = make_token(keys, aud="call-back")
        assert client.get("/api/v1/books", headers=bearer(token)).status_code == 401


def test_token_without_exp_is_rejected(keys, no_fake_user) -> None:
    """没有 exp 的 token 等于永不过期，必须拒"""
    now = int(time.time())
    token = jwt.encode(
        {"sub": "1", "iss": ISSUER, "aud": AUDIENCE, "iat": now},
        keys,
        algorithm="RS256",
    )
    with TestClient(app) as client:
        assert client.get("/api/v1/books", headers=bearer(token)).status_code == 401


def test_token_signed_by_another_key_is_rejected(no_fake_user) -> None:
    """别的密钥签的 token —— 这是整个方案的核心保证"""
    attacker = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with TestClient(app) as client:
        token = make_token(attacker)
        assert client.get("/api/v1/books", headers=bearer(token)).status_code == 401


def test_alg_none_is_rejected(keys, no_fake_user) -> None:
    """alg=none 是 JWT 最经典的漏洞：改成不签名，不校验算法的实现会直接放行"""
    with TestClient(app) as client:
        token = make_token(keys, algorithm="none")
        assert client.get("/api/v1/books", headers=bearer(token)).status_code == 401


def test_non_numeric_sub_is_rejected(keys, no_fake_user) -> None:
    """sub 不是数字时不能悄悄当成 0 号用户"""
    with TestClient(app) as client:
        assert client.get("/api/v1/books", headers=bearer(make_token(keys, sub="abc"))).status_code == 401


# --------------------------------------------------------------------------- 隔离


def test_users_see_only_their_own_books(keys, no_fake_user, as_user) -> None:
    """核心性质：A 的书，B 看不到也拿不到"""
    with TestClient(app) as client:
        as_user(101)
        created = client.post("/api/v1/books/text", json={"title": "A 的书", "text": TEXT})
        assert created.status_code == 200, created.text
        book_id = created.json()["id"]

        # A 自己看得到
        mine = client.get("/api/v1/books").json()
        assert [b["id"] for b in mine] == [book_id]

        # 换成 B：列表里没有
        as_user(102)
        theirs = client.get("/api/v1/books").json()
        assert theirs == [], f"B 不该看到 A 的书，实际 {theirs}"

        # 就算知道 id 也拿不到
        res = client.get(f"/api/v1/books/{book_id}")
        assert res.status_code == 404, f"B 按 id 直接取到了 A 的书！{res.status_code}"

        # 删不掉
        assert client.delete(f"/api/v1/books/{book_id}").status_code == 404

        # 切回 A，书还在
        as_user(101)
        assert client.get(f"/api/v1/books/{book_id}").status_code == 200


def test_days_are_isolated_too(keys, no_fake_user, as_user) -> None:
    """不只是列表接口 —— 按主键取的地方也不能漏"""
    with TestClient(app) as client:
        as_user(201)
        book = client.post("/api/v1/books/text", json={"title": "A", "text": TEXT}).json()
        day_id = client.get(f"/api/v1/books/{book['id']}").json()["days"][0]["id"]

        as_user(202)
        # days/{id}、lesson、quiz、complete 都按 id 取，逐个试
        assert client.get(f"/api/v1/days/{day_id}").status_code == 404
        assert client.post(f"/api/v1/days/{day_id}/lesson").status_code == 404
        assert client.post(f"/api/v1/days/{day_id}/quiz").status_code == 404
        assert client.post(f"/api/v1/days/{day_id}/complete").status_code == 404


def test_each_user_gets_their_own_database_file(as_user, tmp_path) -> None:
    """隔离的实现方式：不是过滤，是物理分文件"""
    from app.config import settings

    with TestClient(app) as client:
        as_user(301)
        client.post("/api/v1/books/text", json={"title": "A", "text": TEXT})

    assert (settings.users_dir / "301.db").exists()
    assert not (settings.users_dir / "302.db").exists(), "没访问过的用户不该被建库"
