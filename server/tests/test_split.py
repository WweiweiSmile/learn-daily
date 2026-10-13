"""按天切分的纯逻辑测试。"""

from app.ingest.split import group_days, normalize, sections_from_text
from app.ingest.types import RawSection

TARGET, MIN, MAX = 6000, 1500, 12000


def test_short_sections_are_merged_into_one_day():
    units = [RawSection(f"第{i}节", "字" * 1000) for i in range(5)]
    days = group_days(units, target=TARGET, minimum=MIN, maximum=MAX)
    assert len(days) == 1
    assert days[0].char_count == 5000


def test_accumulates_until_target():
    units = [RawSection(None, "字" * 3000) for _ in range(4)]
    days = group_days(units, target=TARGET, minimum=MIN, maximum=MAX)
    # 3000 + 3000 = 6000 收一天，剩下两天同理
    assert [d.char_count for d in days] == [6000, 6000]
    assert [d.indexes for d in days] == [[0, 1], [2, 3]]


def test_oversized_section_is_split_by_paragraphs():
    body = "\n\n".join("段" * 5000 for _ in range(4))  # 20000 字，超过 MAX
    units = normalize([RawSection("超长章", body)], MAX)
    assert len(units) > 1
    assert all(u.char_count <= MAX for u in units)
    assert units[0].title == "超长章（1/2）" or units[0].title.startswith("超长章")


def test_single_huge_paragraph_is_hard_split():
    units = normalize([RawSection("整页代码", "x" * 30000)], MAX)
    assert len(units) >= 3
    assert all(u.char_count <= MAX for u in units)


def test_short_tail_is_merged_into_previous_day():
    units = [RawSection(None, "字" * 6000), RawSection(None, "字" * 300)]
    days = group_days(units, target=TARGET, minimum=MIN, maximum=MAX)
    # 第二天只有 300 字，不足 MIN，应该并回第一天
    assert len(days) == 1
    assert days[0].char_count == 6300


def test_tail_kept_when_large_enough():
    units = [RawSection(None, "字" * 6000), RawSection(None, "字" * 3000)]
    days = group_days(units, target=TARGET, minimum=MIN, maximum=MAX)
    assert len(days) == 2


def test_day_title_uses_the_only_section_title():
    units = [RawSection("第一章 起点", "字" * 2000)]
    days = group_days(units, target=TARGET, minimum=MIN, maximum=MAX)
    assert days[0].title == "第一章 起点"


def test_day_title_falls_back_when_untitled():
    units = [RawSection(None, "字" * 2000)]
    days = group_days(units, target=TARGET, minimum=MIN, maximum=MAX)
    assert days[0].title == "第 1 天"


def test_empty_input():
    assert group_days([], target=TARGET, minimum=MIN, maximum=MAX) == []


def test_sections_from_text_splits_on_markdown_headings():
    text = "# 一\n\nAAA\n\n# 二\n\nBBB\n\n# 三\n\nCCC"
    sections = sections_from_text(text)
    assert [s.title for s in sections] == ["一", "二", "三"]


def test_sections_from_text_falls_back_without_headings():
    text = "\n\n".join("段落" * 200 for _ in range(10))
    sections = sections_from_text(text)
    assert sections
    assert all(s.title is None for s in sections)
