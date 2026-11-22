#!/usr/bin/env python3
"""## が2つ以上あるドキュメントの冒頭に「## 目次」を入れ、## と ### へのリンクを並べる。

使い方:
  update-toc.py           目次を作り直して書き込む
  update-toc.py --check   目次がずれているファイルを出し、あれば失敗する（CI 用）
  update-toc.py ファイル…  指定したファイルだけを見る

対象は git ls-files の .md。mkdocs/（原稿へのリンク）、.github/、変更履歴.md（自動で足す）は対象外。
目次は、最初の ## の直前（# タイトルとリード文の直後）に置く。## が1つ以下なら目次を消す。
アンカーは GitHub と同じ作り方（小文字、記号を消す、空白を - にする）。
mkdocs.yml の toc は pymdownx.slugs.slugify(case: lower) にして、同じアンカーになるようにしている。
同じ見出しの2つ目からは、GitHub と同じく「-1」を付ける（サイトは scripts/mkdocs_hooks.py でそろえる）。
"""

from __future__ import annotations

import re
import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOC_TITLE = "目次"
HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})")
EXCLUDE_PREFIX = ("mkdocs/", ".github/", "site/")


def targets() -> list[str]:
    out = subprocess.run(
        ["git", "-c", "core.quotepath=false", "ls-files", "*.md"],
        cwd=ROOT, check=True, text=True, capture_output=True,
    ).stdout.split("\n")
    return [p for p in out if p and not p.startswith(EXCLUDE_PREFIX) and Path(p).name != "変更履歴.md"]


def plain(text: str) -> str:
    """見出しの Markdown を外した文字列（リンクの文字とアンカーに使う）"""
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    return text.replace("**", "").replace("__", "")


def slug(text: str) -> str:
    """GitHub のアンカーと同じ作り方。文字・数字・空白・- と _ だけ残す"""
    text = plain(text).replace("`", "").strip().lower()
    kept = []
    for ch in text:
        cat = unicodedata.category(ch)
        if ch in " -_" or cat[0] in ("L", "N", "M"):
            kept.append(ch)
    return "".join(kept).replace(" ", "-")


def headings(lines: list[str]) -> list[tuple[int, int, str]]:
    """(行番号, レベル, 文字) をコードブロックの外だけから集める"""
    found = []
    fence = None
    for i, line in enumerate(lines):
        m = FENCE.match(line)
        if m:
            mark = m.group(1)
            if fence is None:
                fence = mark[0] * len(mark)
            elif line.strip().startswith(fence):
                fence = None
            continue
        if fence:
            continue
        h = HEADING.match(line)
        if h:
            found.append((i, len(h.group(1)), h.group(2)))
    return found


def toc_range(lines: list[str], hs: list[tuple[int, int, str]]) -> tuple[int, int] | None:
    """今ある「## 目次」の節（見出しから次の見出しの手前まで）"""
    for n, (i, level, text) in enumerate(hs):
        if level == 2 and text.strip() == TOC_TITLE:
            end = hs[n + 1][0] if n + 1 < len(hs) else len(lines)
            return i, end
    return None


def build(text: str) -> tuple[str, list[str]]:
    """新しい本文と、気を付けることを返す"""
    lines = text.split("\n")
    hs = headings(lines)
    rng = toc_range(lines, hs)
    if rng:
        lines = lines[: rng[0]] + lines[rng[1]:]
        hs = headings(lines)
    body = [(i, lv, t) for i, lv, t in hs if lv in (2, 3)]
    if sum(1 for _, lv, _ in body if lv == 2) < 2:
        return "\n".join(lines), []

    # 同じ見出しは、GitHub と同じく2つ目から「-1」「-2」を付ける。
    # 番号は # から ###### まで、目次の見出しも含めて上から数える
    # （サイトでは scripts/mkdocs_hooks.py が同じ形にそろえる）
    seen: dict[str, int] = {slug(TOC_TITLE): 1}
    anchors: dict[int, str] = {}
    for i, _, t in hs:
        base = slug(t)
        n = seen.get(base, 0)
        seen[base] = n + 1
        anchors[i] = base if n == 0 else f"{base}-{n}"
    items = []
    for i, lv, t in body:
        indent = "" if lv == 2 else "    "
        items.append(f"{indent}- [{plain(t).strip()}](#{anchors[i]})")
    first = next(i for i, lv, _ in body if lv == 2)
    block = [f"## {TOC_TITLE}", ""] + items + [""]
    before = lines[:first]
    while before and not before[-1].strip():
        before.pop()
    new = before + [""] + block + lines[first:]
    return "\n".join(new), []


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--check"]
    check = "--check" in sys.argv[1:]
    files = args or targets()
    stale: list[str] = []
    warn = False
    for rel in files:
        path = ROOT / rel
        old = path.read_text(encoding="utf-8")
        new, notes = build(old)
        for note in notes:
            print(f"{rel}: {note}")
            warn = True
        if new != old:
            stale.append(rel)
            if not check:
                path.write_text(new, encoding="utf-8")
    if check:
        if stale:
            print("目次が見出しとずれています。次を実行して、結果をコミットしてください。")
            print("  python3 scripts/update-toc.py")
            for rel in stale:
                print(f"- {rel}")
            sys.exit(1)
        if warn:
            sys.exit(1)
        print(f"OK: 目次は見出しとそろっています（{len(files)} ファイル）")
    else:
        for rel in stale:
            print(f"目次を更新しました: {rel}")


if __name__ == "__main__":
    main()
