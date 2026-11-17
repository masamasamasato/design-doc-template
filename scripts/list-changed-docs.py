#!/usr/bin/env python3
"""PR で変わったドキュメントを、追記・修正・削除に分けて Markdown で出す。

PR コメントと Job Summary の両方に、同じ本文を使う。

- 分け方は git diff --name-status --no-renames の A（追記）・M と T（修正）・D（削除）。
  リネームは、元のパスの削除と、新しいパスの追記として出す。
- 対象は .md と .puml / .plantuml。SVG（.puml から自動で作る）と 変更履歴.md（マージ後に自動で足す）は出さない。
- 追記と修正は、公開ページ（GitHub Pages の MkDocs サイト）へのリンクにする。
  .puml は、その図の SVG を載せているページへリンクする。
  削除は公開ページが無いので、リンクなしのパスにする。

使い方: list-changed-docs.py <比較元> <比較先>
環境変数 SITE_URL に公開サイトの URL（末尾の / はあってもなくてもよい）を入れる。
COMMENT_MARKER=1 なら、PR コメントを見分ける印を先頭に付ける。
"""

from __future__ import annotations

import os
import subprocess
import sys
import re
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
DOC_SUFFIXES = (".md", ".puml", ".plantuml")
# MkDocs の原稿（scripts/prepare-docs.sh がリンクを作るもの）
PUBLISHED_FILES = ("README.md", "用語集.md")
PUBLISHED_DIRS = ("docs/", "apis/", "decisions/")
MARKER = "<!-- changed-docs -->"


def code(text: str) -> str:
    """インラインコードにする。中のバッククォートより長い区切りで囲む"""
    if "`" not in text:
        return f"`{text}`"
    longest = max(len(run) for run in re.findall(r"`+", text))
    fence = "`" * (longest + 1)
    return f"{fence} {text} {fence}"


def name_status(base: str, head: str) -> list[tuple[str, str]]:
    out = subprocess.run(
        ["git", "-c", "core.quotepath=false", "diff", "--no-renames", "--name-status", f"{base}...{head}"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    ).stdout
    rows = []
    for line in out.splitlines():
        if not line.strip():
            continue
        status, path = line.split("\t", 1)
        rows.append((status[0], path))
    return rows


def is_doc(path: str) -> bool:
    if not path.endswith(DOC_SUFFIXES):
        return False
    if Path(path).name == "変更履歴.md":
        return False
    return True


def is_published(path: str) -> bool:
    return path in PUBLISHED_FILES or path.startswith(PUBLISHED_DIRS)


def md_page(path: str) -> str:
    """原稿の .md から、use_directory_urls: true のときのページのパスを作る"""
    p = Path(path)
    if p.name in ("README.md", "index.md"):
        parent = p.parent.as_posix()
        return "" if parent == "." else parent + "/"
    return p.with_suffix("").as_posix() + "/"


def diagram_page(path: str) -> str | None:
    """.puml の SVG を載せているページを探す。README を先に見る"""
    p = ROOT / path
    folder = p.parent
    svg = p.with_suffix(".svg").name
    candidates = sorted(folder.glob("*.md"), key=lambda f: (f.name != "README.md", f.name))
    for wanted in (svg, p.name):
        for md in candidates:
            if md.name == "変更履歴.md":
                continue
            try:
                text = md.read_text(encoding="utf-8")
            except OSError:
                continue
            if f"({wanted})" in text:
                return md_page(md.relative_to(ROOT).as_posix())
    return None


def link(path: str, site: str) -> str:
    label = code(path)
    if not is_published(path):
        return f"{label}（公開ページなし）"
    page = md_page(path) if path.endswith(".md") else diagram_page(path)
    if page is None:
        return f"{label}（公開ページなし）"
    return f"[{label}]({site}{quote(page)})"


def block(title: str, items: list[str]) -> list[str]:
    lines = [title] + [f"・{item}" for item in items] if items else [title, "・なし"]
    # 1行ずつ改行して見せる（CommonMark の行末 \ は改行）
    return [line + "\\" for line in lines[:-1]] + [lines[-1], ""]


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit("使い方: list-changed-docs.py <比較元> <比較先>")
    base, head = sys.argv[1], sys.argv[2]
    site = os.environ.get("SITE_URL", "").strip()
    if site and not site.endswith("/"):
        site += "/"

    added: list[str] = []
    modified: list[str] = []
    deleted: list[str] = []
    for status, path in name_status(base, head):
        if not is_doc(path):
            continue
        if status in ("A", "C"):
            added.append(link(path, site))
        elif status in ("M", "T"):
            modified.append(link(path, site))
        elif status == "D":
            deleted.append(code(path))

    lines: list[str] = []
    if os.environ.get("COMMENT_MARKER", "").strip() == "1":
        lines.append(MARKER)
    lines += ["## 変更したドキュメント", ""]
    lines += block("追記ドキュメント", added)
    lines += block("修正ドキュメント", modified)
    lines += block("削除ドキュメント", deleted)
    lines += [
        "リンク先は公開サイト（main を公開したページ）です。マージして公開されるまでは、追記したページは開けず、修正したページは前の内容です。",
        "",
        "SVG（.puml から自動で作る）と 変更履歴.md（マージ後に自動で足す）は、一覧に出しません。リネームは、元のパスの削除と新しいパスの追記として出します。",
        "",
    ]
    sys.stdout.write("\n".join(lines))


if __name__ == "__main__":
    main()
