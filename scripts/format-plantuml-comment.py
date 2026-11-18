#!/usr/bin/env python3
"""変換した SVG を、PRコメント用の Markdown にする。

変わった図は、changed-docs とそろえて「追記した図」「修正した図」「削除した図」に分ける。
ADDED_LIST に、PRで足した .puml の一覧ファイルを渡す（git diff の A）。ここに無い図は修正とする。
DELETED_LIST に、PRで消した .puml の一覧ファイルを渡す（git diff の D）。
リネームは、元の図の削除と、新しい図の追記として出す。

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
        lines.append("**赤い部分が、このPRで足した・変えたところです**。リポジトリの SVG は、ふだんの色のままです。")
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
        lines.extend(["**色は付けていませんが、図の形には入っています**", ""])
        lines.extend(bullets([code(u) for u in uncolored]))
        lines.append("")
    return lines


def stem(path: str) -> str:
    return path.rsplit(".", 1)[0]


def category(title: str, items: list[str]) -> list[str]:
    """changed-docs と同じ形。### の見出しの下に箇条書きで並べ、無いときは「なし」"""
    return [f"### {title}", ""] + [f"- {item}" for item in (items or ["なし"])] + [""]


def open_label(puml: str) -> str:
    """閉じた details の見出し。図の場所が分かる名前にする。
    例: apis/register-passkey/flow.puml → 「register-passkey のフローを開く」"""
    parts = puml.split("/")
    folder = parts[-2] if len(parts) >= 2 else ""
    name = parts[-1].rsplit(".", 1)[0]
    kind = {"flow": "フロー"}.get(name, name)
    return f"{folder} の{kind}を開く" if folder else f"{kind}を開く"


def figure(path: str, name: str, url: str, attach: bool, info: dict | None, failed: bool, title: str) -> list[str]:
    # 図は大きいので、1枚ごとに閉じた details に入れる。見出しは閉じていても見える
    lines = [
        f"### {title}：{code(name)}",
        "",
        "<details>",
        f"<summary>{html.escape(open_label(name))}</summary>",
        "",
        f"[SVGを開く]({url})",
        "",
    ]
    if attach:
        lines.extend([f"![{alt_text(path)}](./{path})", ""])
    else:
        lines.extend([f'<img alt="{html.escape(path)}" src="{html.escape(url)}?sanitize=true" />', ""])
    if info:
        lines.extend(diff_lines(info, attach, failed))
    lines.extend(["</details>", ""])
    return lines


def main() -> None:
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    repository = os.environ["GITHUB_REPOSITORY"]
    sha = os.environ["COMMENT_SHA"]
    attach = os.environ.get("COMMENT_ATTACH", "").strip() in {"1", "true", "yes"}
    summary = load_json(os.environ.get("DIFF_SUMMARY", ""))
    files = summary.get("files") or {}
    failed = load_lines(os.environ.get("HIGHLIGHT_FAILED", ""))
    added_list = load_lines(os.environ.get("ADDED_LIST", ""))
    added_puml = {stem(p) for p in added_list}
    known_puml = {stem(p): p for p in list(files) + sorted(added_list)}
    deleted = sorted(load_lines(os.environ.get("DELETED_LIST", "")) or set(summary.get("deleted_files") or []))
    paths = [line.strip() for line in sys.stdin if line.strip()]
    added = [p for p in paths if stem(p) in added_puml]
    modified = [p for p in paths if stem(p) not in added_puml]

    def url_of(path: str) -> str:
        return f"{server}/{repository}/blob/{sha}/{path}"

    def label(svg: str) -> str:
        """一覧と見出しには、元の .puml のパスを出す（changed-docs と同じ）"""
        return known_puml.get(stem(svg), stem(svg) + ".puml")

    lines = [
        "<!-- plantuml-preview -->",
        "## 変換した図",
        "",
    ]
    lines += category("追記した図", [f"[{code(label(p))}]({url_of(p)})" for p in added])
    lines += category("修正した図", [f"[{code(label(p))}]({url_of(p)})" for p in modified])
    lines += category("削除した図", [code(d) for d in deleted])
    for title, group in (("追記した図", added), ("修正した図", modified)):
        for path in group:
            puml, info = find_summary(files, path)
            lines.extend(figure(path, label(path), url_of(path), attach, info, puml in failed, title))
    sys.stdout.write("\n".join(lines))


if __name__ == "__main__":
    main()
