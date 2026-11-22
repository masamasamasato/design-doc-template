"""MkDocs のフック。同じ見出しが2つあるときのアンカーを、GitHub と同じ形にする。

Python-Markdown の toc は、2つ目の同じ見出しを「処理詳細_1」にする。GitHub は「処理詳細-1」にする。
目次（scripts/update-toc.py）は GitHub の形で書くので、サイトの id もそちらにそろえる。
"""

from __future__ import annotations

import re

DUP = re.compile(r'(id="|href="#)([^"]+?)_(\d+)"')


def _fix_toc(items) -> None:
    for item in items:
        item.id = re.sub(r"_(\d+)$", r"-\1", item.id)
        _fix_toc(item.children)


def on_page_content(html, page, config, files):
    _fix_toc(page.toc)
    # リンク切れの検証も、そろえたあとの id で行う
    if page.present_anchor_ids is not None:
        # 見出しの ¶ のリンク（変える前の形）も通すため、前と後の両方を入れる
        page.present_anchor_ids |= {re.sub(r"_(\d+)$", r"-\1", a) for a in page.present_anchor_ids}
    return DUP.sub(lambda m: f'{m.group(1)}{m.group(2)}-{m.group(3)}"', html)
