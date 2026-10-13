from dataclasses import dataclass, field


@dataclass
class RawSection:
    """从书里切出来的一个自然块（章/节/一段）。"""

    title: str | None
    content: str

    @property
    def char_count(self) -> int:
        return len(self.content)


@dataclass
class ExtractResult:
    sections: list[RawSection] = field(default_factory=list)
    warning: str | None = None
    error: str | None = None
