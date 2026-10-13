"""AI 记忆与诊断：概念沉淀、错题留证、诊断生成与过期判断。"""

from __future__ import annotations

import asyncio
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
            "rubric": ["要点一"],
            "common_mistakes": ["只复述原文"],
        },
    ]
}

GRADE_PAYLOAD: dict[str, Any] = {
    "concept": "注意力位置",
    "verdict": "partial",
    "score": 60,
    "got_right": ["抓住了主干"],
    "got_wrong": ["把要反驳的观点当成了答案"],
    "guidance": "如果这一步反过来会怎样？",
    "takeaway": "记住这条主线。",
}

CONCEPTS_PAYLOAD: dict[str, Any] = {
    "concepts": [
        {"name": "注意力位置", "summary": "开头结尾权重最高，中段被稀释。"},
        {"name": "上下文污染", "summary": "上一轮的错误结论会留在历史里继续起作用。"},
    ]
}

DIAGNOSIS_PAYLOAD: dict[str, Any] = {
    "summary": "你建立了注意力位置的概念，但上下文污染还从没被检验过。",
    "learned": [{"concept": "注意力位置", "evidence": "简答题部分答对"}],
    "gaps": [
        {
            "concept": "上下文污染",
            "evidence": "学过但从未被检验",
            "suggestion": "找一道需要清理历史的题做",
        }
    ],
    "blind_spots": ["上下文污染"],
    "pattern": "",
    "next_steps": ["做一道关于上下文污染的题"],
}


def _dispatch(prompt: str) -> dict[str, Any]:
    if "出题老师" in prompt:
        return QUIZ_PAYLOAD
    if "请抽出这一天真正在教的" in prompt:
        return CONCEPTS_PAYLOAD
    if "学习诊断老师" in prompt:
        return DIAGNOSIS_PAYLOAD
    return GRADE_PAYLOAD


@pytest.fixture
def stub_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_complete(messages, *, json_mode=False, model=None):
        return "这是讲解正文。"

    async def fake_complete_json(messages, *, model=None):
        return _dispatch(messages[-1]["content"])

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


def setup_day(client: TestClient) -> tuple[int, int]:
    """建书、生成讲解、出题，返回 (book_id, day_id)。"""
    book = client.post("/api/v1/books/text", json={"title": "测试书", "text": BOOK_TEXT}).json()
    detail = client.get(f"/api/v1/books/{book['id']}").json()
    day_id = detail["days"][0]["id"]

    client.post(f"/api/v1/days/{day_id}/lesson")
    wait_until(
        lambda: client.get(f"/api/v1/days/{day_id}").json()["lesson"]["status"] == "done",
        what="讲解",
    )
    client.post(f"/api/v1/days/{day_id}/quiz")
    wait_until(
        lambda: client.get(f"/api/v1/days/{day_id}").json()["questions"] or None,
        what="出题",
    )
    return book["id"], day_id


def answer(client: TestClient, day_id: int, text: str) -> dict[str, Any]:
    question = client.get(f"/api/v1/days/{day_id}").json()["questions"][0]
    attempt_id = client.post(
        f"/api/v1/questions/{question['id']}/attempts", json={"answer": text}
    ).json()["id"]
    return wait_until(
        lambda: (lambda a: a if a["status"] == "done" else None)(
            client.get(f"/api/v1/attempts/{attempt_id}").json()
        ),
        what="批改",
    )


def test_concepts_are_extracted_after_lesson(stub_llm: None) -> None:
    with TestClient(app) as client:
        _, day_id = setup_day(client)
        concepts = wait_until(
            lambda: client.get(f"/api/v1/days/{day_id}").json()["concepts"] or None,
            what="抽概念",
        )
        assert [c["name"] for c in concepts] == ["注意力位置", "上下文污染"]
        assert concepts[0]["day_id"] == day_id


def test_wrong_answer_records_a_misconception(stub_llm: None) -> None:
    with TestClient(app) as client:
        book_id, day_id = setup_day(client)
        attempt = answer(client, day_id, "我的回答")
        assert attempt["verdict"] == "partial"
        assert attempt["concept"] == "注意力位置"

        wait_until(
            lambda: client.get(f"/api/v1/diagnosis?book_id={book_id}").json()["evidence"][
                "misconceptions"
            ]
            or None,
            what="错题入库",
        )
        body = client.get(f"/api/v1/diagnosis?book_id={book_id}").json()
        assert body["evidence"]["misconceptions"] == 1
        assert body["evidence"]["graded"] == 1


def test_correct_answer_records_no_misconception(stub_llm: None, monkeypatch) -> None:
    async def always_correct(messages, *, model=None):
        prompt = messages[-1]["content"]
        if "批改老师" in prompt:
            return {**GRADE_PAYLOAD, "verdict": "correct", "score": 95, "got_wrong": []}
        return _dispatch(prompt)

    monkeypatch.setattr(llm, "complete_json", always_correct)

    with TestClient(app) as client:
        book_id, day_id = setup_day(client)
        assert answer(client, day_id, "完整回答")["verdict"] == "correct"
        time.sleep(0.3)  # 给后台记录留点时间
        body = client.get(f"/api/v1/diagnosis?book_id={book_id}").json()
        assert body["evidence"]["misconceptions"] == 0
        assert body["evidence"]["graded"] == 1


def test_diagnosis_generation(stub_llm: None) -> None:
    with TestClient(app) as client:
        book_id, day_id = setup_day(client)
        answer(client, day_id, "我的回答")

        res = client.post(f"/api/v1/diagnosis?book_id={book_id}")
        assert res.status_code == 200
        assert res.json()["status"] == "running"  # 立刻反映状态

        body = wait_until(
            lambda: (lambda d: d if d["status"] == "done" else None)(
                client.get(f"/api/v1/diagnosis?book_id={book_id}").json()
            ),
            what="诊断",
        )
        result = body["result"]
        assert "注意力位置" in result["summary"]
        assert result["blind_spots"] == ["上下文污染"]
        assert result["gaps"][0]["concept"] == "上下文污染"
        assert result["next_steps"] == ["做一道关于上下文污染的题"]
        assert body["is_stale"] is False


def test_diagnosis_becomes_stale_after_new_evidence(stub_llm: None) -> None:
    with TestClient(app) as client:
        book_id, day_id = setup_day(client)
        answer(client, day_id, "我的回答")
        client.post(f"/api/v1/diagnosis?book_id={book_id}")
        wait_until(
            lambda: client.get(f"/api/v1/diagnosis?book_id={book_id}").json()["status"] == "done",
            what="诊断",
        )

        # 又答了一次题 → 证据变了，诊断就该标记为过期
        answer(client, day_id, "再答一次")
        wait_until(
            lambda: client.get(f"/api/v1/diagnosis?book_id={book_id}").json()["is_stale"],
            what="过期标记",
        )


def test_global_diagnosis_scope(stub_llm: None) -> None:
    with TestClient(app) as client:
        setup_day(client)
        body = client.get("/api/v1/diagnosis").json()
        assert body["book_id"] is None
        assert body["evidence"]["graded"] >= 0


def test_diagnosis_for_unknown_book_is_404(stub_llm: None) -> None:
    with TestClient(app) as client:
        assert client.get("/api/v1/diagnosis?book_id=999999").status_code == 404


def test_diagnosis_does_not_restart_while_running(stub_llm: None, monkeypatch) -> None:
    """连点两次只应该有一份在跑，第二次直接返回当前状态。

    诊断那一路的桩要故意慢下来——桩是瞬时的话，第二次请求打进来时第一次
    早就跑完了，测不到守卫。
    """

    async def slow_diagnosis(messages, *, model=None):
        prompt = messages[-1]["content"]
        if "学习诊断老师" in prompt:
            await asyncio.sleep(1.5)
            return DIAGNOSIS_PAYLOAD
        return _dispatch(prompt)

    monkeypatch.setattr(llm, "complete_json", slow_diagnosis)

    with TestClient(app) as client:
        book_id, _ = setup_day(client)
        first = client.post(f"/api/v1/diagnosis?book_id={book_id}").json()
        assert first["status"] == "running"
        second = client.post(f"/api/v1/diagnosis?book_id={book_id}").json()
        assert second["id"] == first["id"]


def test_diagnosis_regenerates_after_previous_finished(stub_llm: None) -> None:
    """已经跑完的情况下再点一次，应该是一份新的——那是「重新诊断」。"""
    with TestClient(app) as client:
        book_id, _ = setup_day(client)
        first = client.post(f"/api/v1/diagnosis?book_id={book_id}").json()
        wait_until(
            lambda: client.get(f"/api/v1/diagnosis?book_id={book_id}").json()["status"] == "done",
            what="诊断",
        )
        second = client.post(f"/api/v1/diagnosis?book_id={book_id}").json()
        assert second["id"] != first["id"]
        assert second["status"] == "running"
