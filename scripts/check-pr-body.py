#!/usr/bin/env python3
"""PR本文が、テンプレート（.github/pull_request_template.md）の形になっているかを見る。

- 「## 概要」があり、コメントと空行を除いて1〜2行
- 「## 判断してほしい点」があり、番号付きの行か「なし」
- それより後は、閉じた details の中に書く（details の外は、見出し・空行・コメントだけ）
- details に open 属性を付けない

PR_BODY に本文を入れて動かす。PR_AUTHOR が bot（末尾が [bot]）なら確かめない。
"""

from __future__ import annotations

import os
import re
import sys

COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
FENCE = re.compile(r"^(\s*)(`{3,}|~{3,}).*?^\1\2[ \t]*$", re.DOTALL | re.MULTILINE)
INLINE_CODE = re.compile(r"(`+)(?!`).+?(?<!`)\1(?!`)")
HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*#*\s*$")
DETAILS_OPEN = re.compile(r"<details\b[^>]*>", re.IGNORECASE)
DETAILS_CLOSE = re.compile(r"</details\s*>", re.IGNORECASE)
OPEN_ATTR = re.compile(r"<details\b[^>]*\bopen\b[^>]*>", re.IGNORECASE)
NUMBERED = re.compile(r"^\d+[.)．]\s*\S")

SUMMARY_TITLE = "概要"
DECISION_TITLE = "判断してほしい点"

FIX_SUMMARY = (
    "直し方の例:\n"
    "  ## 概要\n"
    "\n"
    "  公開APIに本人確認の検証を足す\n"
    "  本人確認前の公開を防ぐため。公開APIの失敗表に1行増える"
)
FIX_DECISION = (
    "直し方の例:\n"
    "  ## 判断してほしい点\n"
    "\n"
    "  1. ロックの期間を15分にしてよいか\n"
    "  （無いときは「なし」の1行）"
)
FIX_DETAILS = (
    "直し方の例:\n"
    "  <details>\n"
    "  <summary>自分で決めたこと</summary>\n"
    "\n"
    "  - ここに書く\n"
    "\n"
    "  </details>"
)


def strip_comments(text: str) -> str:
    """コメントを消し、コードの中の <details> などを見ないようにする。
    改行は残し、行番号がずれないようにする"""
    keep_lines = lambda m: "\n" * m.group(0).count("\n")
    text = COMMENT.sub(keep_lines, text)
    # コードブロックは、details の外なら文として数えるよう「コード」の1行にする
    text = FENCE.sub(lambda m: "（コードブロック）" + keep_lines(m), text)
    return INLINE_CODE.sub("コード", text)


def errors_for(body: str) -> list[str]:
    text = strip_comments(body.replace("\r\n", "\n").replace("\r", "\n"))
    lines = text.split("\n")
    found: list[str] = []

    headings = [(i, HEADING.match(line).group(1)) for i, line in enumerate(lines) if HEADING.match(line)]
    index = {title: i for i, title in reversed(headings)}

    if SUMMARY_TITLE not in index:
        found.append("「## 概要」がありません。テンプレートの形で書いてください。\n" + FIX_SUMMARY)
    if DECISION_TITLE not in index:
        found.append("「## 判断してほしい点」がありません。無いときも見出しを残し、「なし」と書いてください。\n" + FIX_DECISION)
    if found:
        return found

    def section(start: int) -> tuple[list[str], int]:
        """見出しの次の行から、次の見出しか details の手前までの、空でない行"""
        out: list[str] = []
        i = start + 1
        while i < len(lines):
            line = lines[i]
            if HEADING.match(line) or DETAILS_OPEN.search(line):
                break
            if line.strip():
                out.append(line.strip())
            i += 1
        return out, i

    summary, _ = section(index[SUMMARY_TITLE])
    if not summary:
        found.append("「## 概要」が空です。テンプレートのままでは出せません。2行まで書いてください。\n" + FIX_SUMMARY)
    elif len(summary) > 2:
        found.append(
            f"「## 概要」が{len(summary)}行あります。2行までにして、補足や具体例は閉じた details に入れてください。\n"
            + FIX_SUMMARY
        )

    decision, rest = section(index[DECISION_TITLE])
    if not decision:
        found.append("「## 判断してほしい点」が空です。無いときは「なし」と書いてください。\n" + FIX_DECISION)
    elif decision != ["なし"]:
        bad = [line for line in decision if not NUMBERED.match(line)]
        if bad:
            found.append(
                "「## 判断してほしい点」は、番号付きの1行ずつか「なし」にしてください。"
                f"番号の無い行: {bad[0]}\n" + FIX_DECISION
            )

    if index[SUMMARY_TITLE] > index[DECISION_TITLE]:
        found.append("「## 概要」を「## 判断してほしい点」より前に置いてください。")

    # 判断してほしい点より後は、details の外に文を置かない
    depth = 0
    outside: list[tuple[int, str]] = []
    for i in range(rest, len(lines)):
        line = lines[i]
        opens = len(DETAILS_OPEN.findall(line))
        closes = len(DETAILS_CLOSE.findall(line))
        stripped = DETAILS_CLOSE.sub("", DETAILS_OPEN.sub("", line)).strip()
        if depth == 0 and opens == 0 and stripped and not HEADING.match(line):
            outside.append((i + 1, stripped))
        depth = max(depth + opens - closes, 0)
    if outside:
        sample = "、".join(f"{n}行目「{t[:30]}」" for n, t in outside[:3])
        found.append(
            "「## 判断してほしい点」より後の文は、閉じた details の中に入れてください。"
            f"details の外にある文: {sample}\n" + FIX_DETAILS
        )

    opened = [m.group(0) for m in OPEN_ATTR.finditer(text)]
    if opened:
        found.append(
            f"details に open が付いています（{opened[0]}）。閉じた状態にするため、open を外してください。\n"
            "直し方の例: <details open> → <details>"
        )
    return found


def main() -> None:
    author = os.environ.get("PR_AUTHOR", "").strip()
    if author.endswith("[bot]"):
        print(f"bot が作ったPRのため、本文は確かめません: {author}")
        return
    found = errors_for(os.environ.get("PR_BODY", ""))
    if found:
        print("PR本文がテンプレートの形になっていません。")
        for item in found:
            print("- " + item.replace("\n", "\n  "))
        sys.exit(1)
    print("OK: PR本文はテンプレートの形です")


if __name__ == "__main__":
    main()
