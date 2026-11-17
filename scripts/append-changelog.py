#!/usr/bin/env python3
"""変わった apis/<名前>/ と docs/business/<業務>/ の変更履歴.md に、マージ日とPRを1行足す。"""

from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
TARGETS = (
    (re.compile(r"^apis/([^/]+)/"), ROOT / "apis"),
    (re.compile(r"^docs/business/([^/]+)/"), ROOT / "docs" / "business"),
)


def changed_files(base: str, head: str) -> list[str]:
    result = subprocess.run(
        ["git", "-c", "core.quotepath=false", "diff", "--name-only", f"{base}...{head}"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def append(path: Path, line: str) -> None:
    if path.exists():
        text = path.read_text(encoding="utf-8")
        if line in text.splitlines():
            print(f"記録済み: {path.relative_to(ROOT)}")
            return
        if text and not text.endswith("\n"):
            text += "\n"
        path.write_text(text + line + "\n", encoding="utf-8")
    else:
        path.write_text("# 変更履歴\n\n" + line + "\n", encoding="utf-8")
    print(f"追記: {path.relative_to(ROOT)}")


def main() -> None:
    base = os.environ["BASE_SHA"]
    head = os.environ["HEAD_SHA"]
    number = os.environ["PR_NUMBER"].strip()
    title = " ".join(os.environ["PR_TITLE"].split())
    today = datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d")
    line = f"{today} #{number} {title}"

    seen: set[tuple[str, str]] = set()
    for name in changed_files(base, head):
        for regex, parent in TARGETS:
            match = regex.match(name)
            if not match:
                continue
            item = match.group(1)
            key = (str(parent), item)
            if key in seen:
                continue
            seen.add(key)
            directory = parent / item
            rel = directory.relative_to(ROOT)
            if not directory.is_dir():
                print(f"削除済みのため飛ばします: {rel}")
                continue
            append(directory / "変更履歴.md", line)

    if not seen:
        print("apis/ と docs/business/ の変更はありません")


if __name__ == "__main__":
    main()
