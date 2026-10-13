"""把单用户时期的 data/learn.db 迁到 per-user 结构：data/users/{user_id}.db

接入认证中心之后，每个用户一个库。旧库是单用户的，里面没有归属信息，
所以**必须显式指定它归谁** —— 猜错了就是把别人的学习记录送出去。

    cd server
    uv run python scripts/migrate_to_per_user.py --owner 11
    uv run python scripts/migrate_to_per_user.py --owner 11 --dry-run

这个脚本只做一件事：搬文件。表结构和数据都不动（结构完全一样，
因为 per-user 只是把同一个 schema 铺到多个文件上）。
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402


def summarize(path: Path) -> dict[str, int]:
    """打印库里有什么，让搬迁前能确认搬的是对的东西"""
    counts: dict[str, int] = {}
    con = sqlite3.connect(path)
    try:
        for table in ("books", "days", "lessons", "questions", "attempts", "concepts", "misconceptions", "diagnoses"):
            try:
                counts[table] = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except sqlite3.OperationalError:
                counts[table] = -1  # 表不存在
        rows = con.execute("SELECT id, title, day_count FROM books ORDER BY id").fetchall()
    finally:
        con.close()

    print(f"\n  {path}")
    print("  " + "  ".join(f"{k}={v}" for k, v in counts.items() if v >= 0))
    if rows:
        print("  书：")
        for book_id, title, day_count in rows:
            print(f"    [{book_id}] 《{title}》 {day_count} 天")
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="迁移到 per-user 数据库")
    parser.add_argument("--owner", type=int, required=True, help="旧数据归属的用户 id（认证中心里的 user id）")
    parser.add_argument("--dry-run", action="store_true", help="只看会发生什么，不动文件")
    args = parser.parse_args()

    legacy = settings.data_dir / "learn.db"
    target = settings.users_dir / f"{args.owner}.db"

    if not legacy.exists():
        print(f"没有找到旧库 {legacy}，无需迁移")
        return 0

    print(f"旧库内容：")
    summarize(legacy)

    if target.exists():
        print(f"\n目标已存在：{target}")
        print("不覆盖。如果确实要重来，先把它移走或删掉。")
        return 1

    if args.dry_run:
        print(f"\n[dry-run] 会把 {legacy}\n        搬到 {target}")
        return 0

    settings.users_dir.mkdir(parents=True, exist_ok=True)

    # 先复制、验证、再删原件。直接 move 的话，中途出错就没有回头路了
    shutil.copy2(legacy, target)
    print(f"\n已复制到 {target}")

    print(f"\n新库内容（应与旧库一致）：")
    before = summarize(legacy)
    after = summarize(target)
    if before != after:
        print("\n内容对不上！保留旧库不动，请人工检查", file=sys.stderr)
        target.unlink(missing_ok=True)
        return 1

    legacy.rename(legacy.with_suffix(".db.migrated"))
    print(f"\n旧库已重命名为 {legacy.name}.migrated（没有删除，确认无误后可以自己清掉）")
    print(f"完成：用户 {args.owner} 现在用的是 {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
