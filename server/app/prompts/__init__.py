"""提示词模板。正文放在同目录的 .md 里，方便直接改了看效果，不用重启逻辑代码。

模板里的 JSON 示例写成双花括号 {{ }}，render 之后变回单花括号。
"""

from functools import lru_cache
from pathlib import Path

_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=None)
def _raw(name: str) -> str:
    return (_DIR / f"{name}.md").read_text(encoding="utf-8")


def render(name: str, **kwargs: object) -> str:
    return _raw(name).format(**kwargs)
