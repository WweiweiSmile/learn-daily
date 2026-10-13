"""OpenAI 兼容的对话补全客户端。

两个必须记住的点，都是从 call-back 那边踩坑换来的：

1. **上游一律走流式。** 非流式请求在模型写完之前一个字节都不发。K3 这类「始终推理」
   的模型一次要算七八分钟，非流式实测连响应头都到不了——而服务端把那次请求记为成功
   并计了费。流式在同一条链路上几秒就有数据。所以这里只实现流式，不提供非流式入口。

2. **有些模型不吃某些参数。** kimi-k3 系列拒绝 temperature；又因为推理过程与正文
   共享 token 预算，传 max_tokens 会把正文截断。这类差异集中收在 _build_body 里。

注意这里**不**向本项目的客户端输出流——长任务一律落库成异步任务，由前端轮询状态。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

K3_PREFIX = "kimi-k3"
_TRANSIENT_STATUS = {429, 500, 502, 503, 504}


class LLMError(RuntimeError):
    """调用模型失败。message 是可以直接展示给用户看的中文说明。"""


def _headers() -> dict[str, str]:
    if not settings.llm_api_key:
        raise LLMError("没有配置模型 API Key，请在 server/.env 里设置 LLM_API_KEY")
    return {
        "Authorization": f"Bearer {settings.llm_api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }


def _build_body(messages: list[dict[str, str]], *, json_mode: bool, model: str) -> dict[str, Any]:
    body: dict[str, Any] = {"model": model, "messages": messages, "stream": True}
    if not model.startswith(K3_PREFIX):
        body["temperature"] = settings.llm_temperature
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    return body


async def _post_once(body: dict[str, Any]) -> str:
    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    # httpx 的 read timeout 语义正是我们要的空闲看门狗：它是「两次读到数据之间
    # 最长等多久」，而不是整个请求的总时长。模型思考几分钟没关系，只要还在吐字。
    timeout = httpx.Timeout(
        connect=30.0,
        read=settings.llm_idle_timeout,
        write=30.0,
        pool=30.0,
    )
    pieces: list[str] = []
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", url, json=body, headers=_headers()) as resp:
            if resp.status_code >= 400:
                detail = (await resp.aread()).decode("utf-8", "replace")[:500]
                raise _HttpStatusError(resp.status_code, f"模型服务返回 {resp.status_code}：{detail}")
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    event = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                for choice in event.get("choices") or []:
                    piece = (choice.get("delta") or {}).get("content")
                    if piece:
                        pieces.append(piece)

    text = "".join(pieces).strip()
    if not text:
        raise LLMError("模型没有返回任何内容")
    return text


class _HttpStatusError(LLMError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


async def complete(
    messages: list[dict[str, str]],
    *,
    json_mode: bool = False,
    model: str | None = None,
) -> str:
    """跑一次补全，返回正文文本。

    重试策略只做两件事：网络/5xx 重试一次；如果服务端不认 response_format，
    去掉它再试一次（有些 OpenAI 兼容实现没有实现这个字段）。
    """
    model = model or settings.llm_model
    body = _build_body(messages, json_mode=json_mode, model=model)

    try:
        return await _post_once(body)
    except _HttpStatusError as exc:
        if json_mode and exc.status == 400 and "response_format" in body:
            logger.warning("服务端不支持 response_format，降级重试：%s", exc)
            body.pop("response_format")
            return await _post_once(body)
        if exc.status in _TRANSIENT_STATUS:
            logger.warning("模型服务 %s，1.5 秒后重试", exc.status)
            await asyncio.sleep(1.5)
            return await _post_once(body)
        raise
    except httpx.HTTPError as exc:
        logger.warning("连接模型服务失败（%s），1.5 秒后重试", exc)
        await asyncio.sleep(1.5)
        try:
            return await _post_once(body)
        except httpx.HTTPError as retry_exc:
            raise LLMError(f"连接模型服务失败：{retry_exc}") from retry_exc


def parse_json(raw: str) -> Any:
    """模型偶尔会给 JSON 套上 ```json 围栏或前后加一句话，这里兜住。"""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
        raise LLMError(f"模型返回的不是合法 JSON：{raw[:200]}")


async def complete_json(
    messages: list[dict[str, str]],
    *,
    model: str | None = None,
) -> Any:
    raw = await complete(messages, json_mode=True, model=model)
    return parse_json(raw)
