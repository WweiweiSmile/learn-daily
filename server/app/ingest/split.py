"""把章节块攒成「一天」。

纯函数，不碰数据库、不碰网络，方便单独测。分两步，中间隔一次落库：

    units = normalize(raw_sections, maximum)   # 拆掉超长块，之后每块都 <= maximum
    ...落库成 Section，拿到 id...
    days  = group_days(units, ...)             # 只做分组，不再改内容

分开是为了让 DayPlan 里存的是**下标**而不是对象——落库后要按下标换成 Section id。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.ingest.types import RawSection

# 没有任何结构可用时，硬切的目标块大小
FALLBACK_CHUNK_CHARS = 3000

_MD_HEADING_RE = re.compile(r"^#{1,3}[ \t]+\S.*$", re.MULTILINE)


@dataclass
class DayPlan:
    title: str
    indexes: list[int] = field(default_factory=list)
    char_count: int = 0


def sections_from_text(text: str) -> list[RawSection]:
    """直接粘贴的文本：有 Markdown 标题就按标题切，否则按段落攒块。"""
    matches = list(_MD_HEADING_RE.finditer(text))
    if len(matches) >= 3:
        out: list[RawSection] = []
        front = text[: matches[0].start()].strip()
        if front:
            out.append(RawSection(None, front))
        for i, match in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body = text[match.end() : end].strip()
            if body:
                out.append(RawSection(match.group(0).lstrip("# ").strip(), body))
        return out
    return chunk_plain_text(text)


def chunk_plain_text(text: str, target: int = FALLBACK_CHUNK_CHARS) -> list[RawSection]:
    """兜底切法：按空行切段，再攒成 target 大小的块。"""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    out: list[RawSection] = []
    buf = ""
    for para in paragraphs:
        if len(para) > target * 2:  # 单个超长段落（比如整页代码）直接硬断
            if buf:
                out.append(RawSection(None, buf.strip()))
                buf = ""
            for i in range(0, len(para), target):
                out.append(RawSection(None, para[i : i + target]))
            continue
        if buf and len(buf) + len(para) > target:
            out.append(RawSection(None, buf.strip()))
            buf = ""
        buf += para + "\n\n"
    if buf.strip():
        out.append(RawSection(None, buf.strip()))
    return out


def normalize(sections: list[RawSection], maximum: int) -> list[RawSection]:
    """把超过 maximum 的块按段落拆开，免得一天里塞进半本书。"""
    out: list[RawSection] = []
    for section in sections:
        out.extend(_split_section(section, maximum))
    return out


def group_days(
    units: list[RawSection],
    *,
    target: int,
    minimum: int,
    maximum: int,
) -> list[DayPlan]:
    """顺着往下攒，攒到 target 收一天；最后一天太短就并进前一天。"""
    if not units:
        return []

    groups: list[list[int]] = []
    current: list[int] = []
    current_len = 0

    for i, unit in enumerate(units):
        if current and current_len + unit.char_count > maximum:
            groups.append(current)
            current, current_len = [], 0
        current.append(i)
        current_len += unit.char_count
        if current_len >= target:
            groups.append(current)
            current, current_len = [], 0

    if current:
        tail_len = sum(units[i].char_count for i in current)
        if groups and tail_len < minimum:
            groups[-1].extend(current)
        else:
            groups.append(current)

    return [
        DayPlan(
            title=_name_day(idx + 1, [units[i] for i in group]),
            indexes=group,
            char_count=sum(units[i].char_count for i in group),
        )
        for idx, group in enumerate(groups)
    ]


def _name_day(day_index: int, group: list[RawSection]) -> str:
    titled = [s.title for s in group if s.title]
    if len(titled) == 1:
        return titled[0]
    if titled:
        return f"{titled[0]} 等 {len(titled)} 节"
    return f"第 {day_index} 天"


def _split_section(section: RawSection, maximum: int) -> list[RawSection]:
    if section.char_count <= maximum:
        return [section]

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", section.content) if p.strip()]
    parts: list[str] = []
    buf = ""

    def flush() -> None:
        nonlocal buf
        if buf.strip():
            parts.append(buf.strip())
        buf = ""

    for para in paragraphs:
        while len(para) > maximum:  # 单个超长段落（比如整页代码）只能硬断
            flush()
            parts.append(para[:maximum].strip())
            para = para[maximum:]
        if buf and len(buf) + len(para) > maximum:
            flush()
        buf += para + "\n\n"
    flush()

    if len(parts) <= 1:
        return [section]

    return [
        RawSection(
            title=f"{section.title}（{i + 1}/{len(parts)}）" if section.title else None,
            content=part,
        )
        for i, part in enumerate(parts)
    ]
