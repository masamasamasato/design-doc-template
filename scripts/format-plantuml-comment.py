#!/usr/bin/env python3
"""変換した SVG を、PRコメント用の Markdown にする。

DIFF_SUMMARY に scripts/highlight-puml-diff.py の JSON があれば、
図ごとに「赤い部分の説明」「変えたもの」「消したもの」を足す。
HIGHLIGHT_FAILED に、色付きで変換できなかった .puml の一覧ファイルを渡せる。
"""

from __future__ import annotations

import json
import html
import os
import re
import sys

MAX_ITEMS = 30


def code(text: str) -> str:
    """インラインコードにする。中のバッククォートより長い区切りで囲む"""
    if "`" not in text:
        return f"`{text}`"
    longest = max(len(run) for run in re.findall(r"`+", text))
    fence = "`" * (longest + 1)
    return f"{fence} {text} {fence}"


def alt_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def bullets(items: list[str]) -> list[str]:
    out = [f"- {item}" for item in items[:MAX_ITEMS]]
    if len(items) > MAX_ITEMS:
        out.append(f"- ほか {len(items) - MAX_ITEMS} 件")
    return out


def load_json(path: str) -> dict:
    if not path or not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def load_lines(path: str) -> set[str]:
    if not path or not os.path.isfile(path):
        return set()
    with open(path, encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}


def find_summary(files: dict, svg: str) -> tuple[str | None, dict | None]:
    stem = svg.rsplit(".", 1)[0]
    for puml, info in files.items():
        if puml.rsplit(".", 1)[0] == stem:
            return puml, info
    return None, None


def diff_lines(info: dict, attach: bool, failed: bool) -> list[str]:
    lines: list[str] = []
    status = info.get("status")
    if status == "new":
        return ["新しい図です。全体が新しいため、色は付けていません。", ""]
    if status == "same":
        return ["足した・変えた・消した行はありません（並べ替えや空白の変更だけ）。", ""]
    if attach and not failed:
        lines.append("**赤い部分が、このPRで足した・変えたところです。** リポジトリの SVG は、ふだんの色のままです。")
    elif attach and failed:
        lines.append("色を付けると変換できなかったため、ふだんの色で載せました。変更は下の一覧を見てください。")
    else:
        lines.append("リンク形式のため、図に色は付いていません。変更は下の一覧を見てください。")
    lines.append("")

    changed = info.get("changed") or []
    changed_new = {after for _, after in changed}
    added = [c for c in info.get("colored") or [] if c not in changed_new]
    added += [c for c in info.get("uncolored") or [] if c not in changed_new]
    if added and (not attach or failed):
        lines.extend(["**足したもの**", ""])
        lines.extend(bullets([code(a) for a in added]))
        lines.append("")
    if changed:
        lines.extend(["**変えたもの**（前 → 後）", ""])
        lines.extend(bullets([f"{code(b)} → {code(a)}" for b, a in changed]))
        lines.append("")
    removed = info.get("removed") or []
    if removed:
        lines.extend(["**消したもの**", ""])
        lines.extend(bullets([code(r) for r in removed]))
        lines.append("")
    uncolored = info.get("uncolored") or []
    if uncolored and attach and not failed:
        lines.extend(["**色を付けられなかった変更**（図には反映済み）", ""])
        lines.extend(bullets([code(u) for u in uncolored]))
        lines.append("")
    return lines


def main() -> None:
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    repository = os.environ["GITHUB_REPOSITORY"]
    sha = os.environ["COMMENT_SHA"]
    attach = os.environ.get("COMMENT_ATTACH", "").strip() in {"1", "true", "yes"}
    summary = load_json(os.environ.get("DIFF_SUMMARY", ""))
    files = summary.get("files") or {}
    failed = load_lines(os.environ.get("HIGHLIGHT_FAILED", ""))
    paths = [line.strip() for line in sys.stdin if line.strip()]
    lines = [
        "<!-- plantuml-preview -->",
        "## 変換した図",
        "",
        "PlantUML は GitHub Actions の中だけで SVG にしました。図の中身は外部のサーバーへ送っていません。",
        "",
        "コメントに画像が出ないときは、リンクを開いてください。",
        "",
    ]
    deleted = summary.get("deleted_files") or []
    if not paths and not deleted:
        lines.append("対象の図はありません。")
        lines.append("")
    for path in paths:
        url = f"{server}/{repository}/blob/{sha}/{path}"
        lines.extend(
            [
                f"### {code(path)}",
                "",
                f"[SVGを開く]({url})",
                "",
            ]
        )
        if attach:
            lines.extend([f"![{alt_text(path)}](./{path})", ""])
        else:
            lines.extend([f'<img alt="{html.escape(path)}" src="{html.escape(url)}?sanitize=true" />', ""])
        puml, info = find_summary(files, path)
        if info:
            lines.extend(diff_lines(info, attach, puml in failed))
    if deleted:
        lines.extend(["### 消した図", ""])
        lines.extend(bullets([code(d) for d in deleted]))
        lines.append("")
    run_url = os.environ.get("RUN_URL", "").strip()
    if run_url:
        lines.extend(
            [
                "PNG が必要なときは、この実行のアーティファクト `plantuml-png` を開いてください。",
                "",
                run_url,
                "",
            ]
        )
    sys.stdout.write("\n".join(lines))


if __name__ == "__main__":
    main()
