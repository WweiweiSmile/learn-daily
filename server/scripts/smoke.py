"""打真模型的冒烟脚本：跑通一遍 讲解 → 出题 → 批改，把结果打出来看质量。

调提示词的时候反复跑这个，比在界面上点快得多。

    cd server && uv run python scripts/smoke.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

SAMPLE = """# 第 3 章 上下文窗口不是一个桶

很多人把上下文窗口想象成一个桶，以为只要没装满就能一直往里塞。这个类比在
第一周是对的，之后就完全错了。

真正决定模型能不能用好一段上下文的，是这段内容在注意力里的位置，而不是它占据
了多少 token。放在最前面的指令和最后面的问题，注意力权重最高；夹在正中间的那
一大段参考资料，权重会被两头的信号稀释掉。业界把它叫做「lost in the middle」。

这解释了一个反直觉的现象：把一本手册全文塞进上下文，效果往往不如只塞相关的
两页。前者看起来信息更全，但真正需要的那两页正好落在中段，被淹了。

由此得到两条实践原则。第一，重要的约束要么放最前面，要么放最后面，不要放在
中间。第二，长资料不是「塞进去」而是「挑进去」——先检索再拼装，比一次性全塞
更省 token 也更准。

还有第三条，也是最容易被忽略的：上下文是会被上一轮污染的。上一轮模型自己
生成的错误结论，如果原样留在历史里，下一轮它会当成既定事实继续往下推。所以
维护上下文不只是往里加，还包括及时删。
"""


def wait_for(client: TestClient, day_id: int, predicate, what: str, timeout: float = 600.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get(f"/api/v1/days/{day_id}").json()
        value = predicate(body)
        if value:
            return value
        time.sleep(1.5)
    raise SystemExit(f"等 {what} 超时")


def main() -> None:
    with TestClient(app) as client:
        res = client.post("/api/v1/books/text", json={"title": "冒烟测试", "text": SAMPLE})
        res.raise_for_status()
        book = res.json()
        print(f"\n=== 切分：{book['day_count']} 天，共 {book['total_chars']} 字 ===")
        detail = client.get(f"/api/v1/books/{book['id']}").json()
        for day in detail["days"]:
            print(f"  第 {day['day_index']} 天  {day['title']}  ({day['char_count']} 字)")

        day_id = detail["days"][0]["id"]

        print("\n=== 生成讲解（真模型，可能要一会儿）===")
        client.post(f"/api/v1/days/{day_id}/lesson")
        lesson = wait_for(
            client, day_id,
            lambda b: b["lesson"] if b["lesson"] and b["lesson"]["status"] == "done" else None,
            "讲解",
        )
        if lesson.get("error"):
            raise SystemExit(f"讲解失败：{lesson['error']}")
        print(lesson["content"])

        print("\n=== 出题 ===")
        client.post(f"/api/v1/days/{day_id}/quiz")
        questions = wait_for(client, day_id, lambda b: b["questions"] or None, "出题")
        for q in questions:
            print(f"\n[{q['kind']}] {q['stem']}")
            for i, opt in enumerate(q["options"]):
                print(f"   {chr(65 + i)}. {opt}")

        print("\n=== 作答 + 批改 ===")
        target = questions[0]
        answer = input("\n输入你的答案（直接回车用默认的敷衍答案）：").strip() or "就是把资料都塞进去就行，塞得越多越好。"
        res = client.post(
            f"/api/v1/questions/{target['id']}/attempts", json={"answer": answer}
        )
        attempt_id = res.json()["id"]

        deadline = time.time() + 600
        while time.time() < deadline:
            attempt = client.get(f"/api/v1/attempts/{attempt_id}").json()
            if attempt["status"] == "done":
                break
            if attempt["status"] == "failed":
                raise SystemExit(f"批改失败：{attempt['error']}")
            time.sleep(1.5)
        else:
            raise SystemExit("等批改超时")

        print(f"\n判定：{attempt['verdict']}  得分：{attempt['score']}")
        print(f"参考答案：{attempt['answer_key']}")
        print("\n答对的点：")
        for x in attempt["got_right"]:
            print(f"  + {x}")
        print("答错/漏掉的点：")
        for x in attempt["got_wrong"]:
            print(f"  - {x}")
        print(f"\n引导：{attempt['guidance']}")
        print(f"\n一句话：{attempt['takeaway']}")


if __name__ == "__main__":
    main()
