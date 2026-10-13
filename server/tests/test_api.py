"""接口层的端到端测试。模型调用全部打桩，验证的是流程和状态机。"""

from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import llm
from app.main import app

BOOK_TEXT = "# 第一章 起点\n\n" + "这是第一章的正文。" * 200 + "\n\n# 第二章 转折\n\n" + "这是第二章的正文。" * 200

QUIZ_PAYLOAD: dict[str, Any] = {
    "questions": [
        {
            "kind": "short",
            "stem": "用自己的话说说这一章在讲什么。",
            "options": [],
            "answer_key": "参考答案",
            "rubric": ["要点一", "要点二"],
            "common_mistakes": ["只复述原文"],
        },
        {
            "kind": "single",
            "stem": "下面哪个说法对？",
            "options": ["选项甲", "选项乙", "选项丙", "选项丁"],
            "answer_key": "选项乙",
            "rubric": [],
            "common_mistakes": [],
        },
    ]
}

GRADE_PAYLOAD: dict[str, Any] = {
    "verdict": "partial",
    "score": 60,
    "got_right": ["抓住了主干"],
    "got_wrong": ["漏掉了因果那一步"],
    "guidance": "如果这一步反过来会怎样？",
    "takeaway": "记住这条主线。",
}


@pytest.fixture
def stub_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_complete(messages, *, json_mode=False, model=None):
        return "这是讲解正文。"

    async def fake_complete_json(messages, *, model=None):
        prompt = messages[-1]["content"]
        return QUIZ_PAYLOAD if "出题老师" in prompt else GRADE_PAYLOAD

    monkeypatch.setattr(llm, "complete", fake_complete)
    monkeypatch.setattr(llm, "complete_json", fake_complete_json)


def wait_until(fn, timeout: float = 10.0, what: str = "条件"):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = fn()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError(f"等 {what} 超时")


def make_book(client: TestClient) -> tuple[int, list[dict]]:
    res = client.post("/api/v1/books/text", json={"title": "测试书", "text": BOOK_TEXT})
    assert res.status_code == 200, res.text
    book = res.json()
    assert book["status"] == "ready", book
    assert book["day_count"] >= 1

    detail = client.get(f"/api/v1/books/{book['id']}").json()
    return book["id"], detail["days"]


def test_import_and_split_a_book(stub_llm: None) -> None:
    with TestClient(app) as client:
        book_id, days = make_book(client)
        assert book_id
        assert all(d["char_count"] > 0 for d in days)
        assert [d["day_index"] for d in days] == list(range(1, len(days) + 1))


def test_full_learning_loop(stub_llm: None) -> None:
    with TestClient(app) as client:
        _, days = make_book(client)
        day_id = days[0]["id"]

        # 1. 生成讲解
        res = client.post(f"/api/v1/days/{day_id}/lesson")
        assert res.status_code == 200
        assert res.json()["lesson"]["status"] == "running"  # 立刻反映状态，不用等

        def lesson_done():
            body = client.get(f"/api/v1/days/{day_id}").json()
            return body["lesson"] if body["lesson"]["status"] == "done" else None

        lesson = wait_until(lesson_done, what="讲解生成")
        assert lesson["content"] == "这是讲解正文。"

        # 2. 出题
        res = client.post(f"/api/v1/days/{day_id}/quiz")
        assert res.status_code == 200
        assert res.json()["quiz_status"] == "running"

        def questions_ready():
            body = client.get(f"/api/v1/days/{day_id}").json()
            return body["questions"] or None

        questions = wait_until(questions_ready, what="出题")
        assert len(questions) == 2
        # 题目里不能带答案
        assert "answer_key" not in questions[0]

        # 3. 答简答题 → AI 批改
        short_q = next(q for q in questions if q["kind"] == "short")
        res = client.post(
            f"/api/v1/questions/{short_q['id']}/attempts", json={"answer": "我的回答"}
        )
        assert res.status_code == 200
        attempt_id = res.json()["id"]
        assert res.json()["answer_key"] is None  # 批改完成前不给答案

        def graded():
            body = client.get(f"/api/v1/attempts/{attempt_id}").json()
            return body if body["status"] == "done" else None

        attempt = wait_until(graded, what="批改")
        assert attempt["verdict"] == "partial"
        assert attempt["score"] == 60
        assert attempt["got_wrong"] == ["漏掉了因果那一步"]
        assert attempt["answer_key"] == "参考答案"  # 批改完成后才给

        # 4. 单选题：对错由代码判，不看模型怎么说
        single_q = next(q for q in questions if q["kind"] == "single")
        res = client.post(
            f"/api/v1/questions/{single_q['id']}/attempts", json={"answer": "选项乙"}
        )
        attempt_id = res.json()["id"]

        def graded_single():
            body = client.get(f"/api/v1/attempts/{attempt_id}").json()
            return body if body["status"] == "done" else None

        attempt = wait_until(graded_single, what="单选批改")
        # 模型给的 verdict 是 partial，但答对了就必须是 correct
        assert attempt["verdict"] == "correct"
        assert attempt["score"] == 100


def test_single_choice_wrong_answer_scores_zero(stub_llm: None) -> None:
    with TestClient(app) as client:
        _, days = make_book(client)
        day_id = days[0]["id"]
        client.post(f"/api/v1/days/{day_id}/lesson")
        wait_until(
            lambda: client.get(f"/api/v1/days/{day_id}").json()["lesson"]["status"] == "done",
            what="讲解",
        )
        client.post(f"/api/v1/days/{day_id}/quiz")

        def questions_ready():
            body = client.get(f"/api/v1/days/{day_id}").json()
            return body["questions"] or None

        questions = wait_until(questions_ready, what="出题")
        single_q = next(q for q in questions if q["kind"] == "single")

        res = client.post(
            f"/api/v1/questions/{single_q['id']}/attempts", json={"answer": "选项甲"}
        )
        attempt_id = res.json()["id"]

        def graded():
            body = client.get(f"/api/v1/attempts/{attempt_id}").json()
            return body if body["status"] == "done" else None

        attempt = wait_until(graded, what="批改")
        assert attempt["verdict"] == "off"
        assert attempt["score"] == 0


def test_quiz_before_lesson_is_rejected(stub_llm: None) -> None:
    with TestClient(app) as client:
        _, days = make_book(client)
        res = client.post(f"/api/v1/days/{days[0]['id']}/quiz")
        assert res.status_code == 409


def test_lesson_is_idempotent(stub_llm: None) -> None:
    with TestClient(app) as client:
        _, days = make_book(client)
        day_id = days[0]["id"]
        client.post(f"/api/v1/days/{day_id}/lesson")
        wait_until(
            lambda: client.get(f"/api/v1/days/{day_id}").json()["lesson"]["status"] == "done",
            what="讲解",
        )
        # 再点一次不应该重新生成
        client.post(f"/api/v1/days/{day_id}/lesson")
        body = client.get(f"/api/v1/days/{day_id}").json()
        assert body["lesson"]["status"] == "done"


def test_complete_day(stub_llm: None) -> None:
    with TestClient(app) as client:
        _, days = make_book(client)
        day_id = days[0]["id"]
        res = client.post(f"/api/v1/days/{day_id}/complete")
        assert res.status_code == 200
        assert res.json()["status"] == "done"
        res = client.post(f"/api/v1/days/{day_id}/reopen")
        assert res.json()["status"] == "pending"


def test_missing_resources_return_404(stub_llm: None) -> None:
    with TestClient(app) as client:
        assert client.get("/api/v1/days/999999").status_code == 404
        assert client.get("/api/v1/books/999999").status_code == 404
        assert client.get("/api/v1/attempts/999999").status_code == 404
