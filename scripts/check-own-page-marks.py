#!/usr/bin/env python3
"""docs/infra の図に、等倍専用ページの印（クラス pdf-own-page）があるかを見る。

PDF を作らなくても、原稿の Markdown だけを見て確かめられる。
印が無いと、インフラ構成の図が等倍の専用ページから外れる。

使い方:
  python3 scripts/check-own-page-marks.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OWN_PAGE_CLASS = "pdf-own-page"
IMAGE_REF = re.compile(
    r'!\[[^\]]*\]\(\s*([^\s)]+)(?:\s+"[^"]*")?\s*\)\s*(\{:[^}]*\})?',
)
SUFFIXES = {".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp"}
SKIP_PARTS = {".venv", "site", "pdf", "node_modules"}


def missing_own_page_marks(root: Path = ROOT) -> list[str]:
    """印が無い docs/infra の図を、「パス: 元の記法」の行で返す。"""
    missing: list[str] = []
    infra = (root / "docs" / "infra").resolve()
    if not infra.is_dir():
        return missing
    for path in root.rglob("*.md"):
        if any(part.startswith("_") or part in SKIP_PARTS for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8")
        for match in IMAGE_REF.finditer(text):
            target = match.group(1).split()[0]
            attrs = match.group(2) or ""
            dest = path.parent / target
            try:
                resolved = dest.resolve()
            except OSError:
                continue
            if resolved.suffix.lower() not in SUFFIXES:
                continue
            try:
                resolved.relative_to(infra)
            except ValueError:
                continue
            if OWN_PAGE_CLASS not in attrs:
                missing.append(f"{path.relative_to(root)}: {match.group(0)}")
    return missing


def check_own_page_marks(root: Path = ROOT) -> None:
    """印が無い図があれば、理由を出して終了する。"""
    missing = missing_own_page_marks(root)
    if missing:
        raise SystemExit(
            "インフラ構成の図に、等倍専用ページの印（クラス pdf-own-page）がありません。\n"
            + "\n".join(missing)
        )


def main() -> None:
    check_own_page_marks()


if __name__ == "__main__":
    main()
