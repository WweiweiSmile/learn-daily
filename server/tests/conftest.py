"""测试夹具。

DATA_DIR 必须在 import app.* 之前设好——settings 是在模块导入时实例化的，
晚一步就会写到真实的 data/ 里去。
"""

import os
import tempfile

import pytest

_TMP = tempfile.mkdtemp(prefix="learn-daily-test-")
os.environ["DATA_DIR"] = _TMP
os.environ.setdefault("LLM_API_KEY", "test-key")
os.environ.setdefault("LLM_MODEL", "test-model")

# 测试用的假用户。每个用户一个库，所以这个 id 决定了测试数据落在
# data/users/1.db（在临时目录里）
TEST_USER_ID = 1


@pytest.fixture(autouse=True)
def fake_user():
    """默认把鉴权依赖换成固定的假用户。

    绝大多数测试关心的是业务逻辑，不是「token 怎么验」——每个用例都去造一个
    真 token 只会让它们变慢变脆。**鉴权本身**由 tests/test_auth.py 单独测，
    那里会用 no_fake_user 把这个覆盖摘掉
    """
    from app.auth import CurrentUser, current_user
    from app.main import app

    app.dependency_overrides[current_user] = lambda: CurrentUser(
        id=TEST_USER_ID, username="tester", role="user"
    )
    yield
    app.dependency_overrides.pop(current_user, None)


@pytest.fixture
def no_fake_user():
    """摘掉假用户，走真实的令牌校验。给 test_auth.py 用"""
    from app.auth import current_user
    from app.main import app

    app.dependency_overrides.pop(current_user, None)
    yield


@pytest.fixture
def as_user():
    """把当前请求切换成指定用户。用于验证数据隔离"""
    from app.auth import CurrentUser, current_user
    from app.main import app

    def _switch(user_id: int) -> None:
        app.dependency_overrides[current_user] = lambda: CurrentUser(
            id=user_id, username=f"user{user_id}", role="user"
        )

    return _switch
