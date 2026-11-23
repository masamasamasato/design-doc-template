#!/usr/bin/env python3
"""変わった apis/<名前>/ と docs/business/<業務>/ の変更履歴.md に、マージ日とPRを足す。

形は、日付の見出しの下に、PRへのリンクの箇条書きを並べる形。

    ## 2026-11-23

    - [#40](https://github.com/<owner>/<repo>/pull/40) PRタイトル

- 同じ日付の見出しがあれば、その下の最後に1行足す。
- 無ければ、見出しを作ってから足す。見出しの順番（古い順か新しい順か）は、ファイルの今の順番に合わせる。
- 同じPR番号とタイトルの行がファイルにあれば、二重に足さない。
- 古い形の行（`YYYY-MM-DD #40 タイトル`、`- \\#40 タイトル`、`- #40 タイトル`）が残っていれば、先にこの形へ直す。
- PRのURLは、GITHUB_SERVER_URL と GITHUB_REPOSITORY から作る。無いときは git remote（origin）から作る。
フォルダ名が _ で始まるもの（apis/_template など）は対象外。"""

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


HEADING = re.compile(r"^## (\d{4}-\d{2}-\d{2})\s*$")
OLD_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2}) #(\d+) (.*)$")
ITEM = re.compile(r"^- (?:\\?#(\d+)|\[#(\d+)\]\([^)]*\)) (.*)$")
NEW_FILE_INTRO = (
    "# 変更履歴\n\n"
    "`main` へマージすると、マージした日の見出しの下に1行足されます。\n\n"
    "形式は、見出し `## YYYY-MM-DD` の下に `- [#PR番号](PRのURL) PRタイトル` です。\n"
)


def repo_url() -> str:
    """PRのURLのもとになる `https://<ホスト>/<owner>/<repo>` を返す。"""
    server = os.environ.get("GITHUB_SERVER_URL", "").rstrip("/")
    repository = os.environ.get("GITHUB_REPOSITORY", "").strip("/")
    if server and repository:
        return f"{server}/{repository}"
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    remote = result.stdout.strip()
    match = re.match(r"^(?:https?://)(?:[^@/]+@)?([^/]+)/(.+?)(?:\.git)?/?$", remote) or re.match(
        r"^(?:ssh://)?[^@/]+@([^:/]+)[:/](.+?)(?:\.git)?/?$", remote
    )
    if not match:
        raise SystemExit("git remote origin から GitHub のURLを作れませんでした")
    host, path = match.groups()
    return f"https://{host}/{path}"


def make_item(url: str, number: str, title: str) -> str:
    return f"- [#{number}]({url}/pull/{number}) {title}"


def item_key(line: str) -> tuple[str, str] | None:
    match = ITEM.match(line)
    if not match:
        return None
    return (match.group(1) or match.group(2), match.group(3))


def split(text: str, url: str) -> tuple[list[str], list[tuple[str, list[str]]]]:
    """前置き（見出しより前の行）と、日付ごとの箇条書きに分ける。古い形の行は、リンクの形に直す。"""
    intro: list[str] = []
    sections: list[tuple[str, list[str]]] = []
    for raw in text.splitlines():
        heading = HEADING.match(raw)
        old = OLD_LINE.match(raw)
        if heading:
            sections.append((heading.group(1), []))
        elif old:
            date, number, title = old.groups()
            if not sections or sections[-1][0] != date:
                sections.append((date, []))
            sections[-1][1].append(make_item(url, number, title))
        elif sections:
            if raw.strip():
                key = item_key(raw)
                sections[-1][1].append(make_item(url, *key) if key else raw)
        else:
            intro.append(raw)
    while intro and not intro[-1].strip():
        intro.pop()
    return intro, sections


def join(intro: list[str], sections: list[tuple[str, list[str]]]) -> str:
    parts = ["\n".join(intro)]
    for date, items in sections:
        parts.append(f"## {date}\n\n" + "\n".join(items))
    return "\n\n".join(parts) + "\n"


def add_entry(text: str, date: str, number: str, title: str, url: str) -> tuple[str, bool]:
    """date の見出しの下にPRの行を足した全文と、足したかどうかを返す。"""
    intro, sections = split(text, url)
    if any(item_key(line) == (number, title) for _, items in sections for line in items):
        return join(intro, sections), False
    item = make_item(url, number, title)
    for section_date, items in sections:
        if section_date == date:
            items.append(item)
            break
    else:
        dates = [d for d, _ in sections]
        newest_first = len(dates) >= 2 and dates[0] > dates[-1]
        if newest_first:
            sections.insert(0, (date, [item]))
        else:
            sections.append((date, [item]))
    return join(intro, sections), True


def append(path: Path, date: str, number: str, title: str, url: str) -> None:
    text = path.read_text(encoding="utf-8") if path.exists() else NEW_FILE_INTRO
    new_text, added = add_entry(text, date, number, title, url)
    if not added:
        if new_text != text:
            path.write_text(new_text, encoding="utf-8")
        print(f"記録済み: {path.relative_to(ROOT)}")
        return
    path.write_text(new_text, encoding="utf-8")
    print(f"追記: {path.relative_to(ROOT)}")


def main() -> None:
    base = os.environ["BASE_SHA"]
    head = os.environ["HEAD_SHA"]
    number = os.environ["PR_NUMBER"].strip()
    title = " ".join(os.environ["PR_TITLE"].split())
    today = datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d")
    url = repo_url()

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
            if item.startswith("_"):
                print(f"ひな形のため飛ばします: {rel}")
                continue
            if not directory.is_dir():
                print(f"削除済みのため飛ばします: {rel}")
                continue
            append(directory / "変更履歴.md", today, number, title, url)

    if not seen:
        print("apis/ と docs/business/ の変更はありません")


if __name__ == "__main__":
    main()
