#!/usr/bin/env python3
"""PRタイトルが、何をどう変えたかの日本語になっているかを見る。"""

from __future__ import annotations

import os
import re
import sys

PREFIX = re.compile(
    r"^(fix|feat|feature|chore|docs|doc|style|refactor|test|ci|build|perf|revert|wip|hotfix)"
    r"(\([^)]*\))?(!)?([:：]|\s|$)",
    re.IGNORECASE,
)
JAPANESE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")


def errors_for(title: str) -> list[str]:
    text = title.strip()
    found: list[str] = []
    if not text:
        found.append("タイトルが空です。例: 公開時に本人確認を追加")
        return found
    if PREFIX.match(text):
        found.append(
            "fix や feat などの接頭辞は使えません。何をどう変えたかを日本語で書いてください。例: 公開時に本人確認を追加"
        )
    if not JAPANESE.search(text):
        found.append("タイトルに日本語が含まれていません。例: 公開時に本人確認を追加")
    return found


def main() -> None:
    title = os.environ.get("PR_TITLE", "")
    found = errors_for(title)
    if found:
        print("PRタイトル: " + title.strip())
        for item in found:
            print("- " + item)
        sys.exit(1)
    print("OK: " + title.strip())


if __name__ == "__main__":
    main()
