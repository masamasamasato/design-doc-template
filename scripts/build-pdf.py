#!/usr/bin/env python3
"""MkDocs でビルドしたサイトを、ヘッドレスの Chromium（Playwright）で PDF に印刷する。

- API ごとに1本（apis/<名前>/処理詳細.md）、業務フローごとに1本（docs/business/<業務>/README.md）。
- mkdocs.yml の nav の順に、ページを1本にまとめた PDF。`_template` の型、各変更履歴、PDF に入れないページ（SKIP_PAGES）は入れない。
  先頭に目次を置き、目次と本文中のリンクから各ページへ飛べる。PDF のしおり（アウトライン）も付ける。
- 見た目は公開サイトと同じ（同じ CSS、ライトモード）。ヘッダー、ナビゲーション、検索、フッター、
  コピーボタンは印刷しない。
- 各ページの下にページ番号を入れる。
- 図は、文字が読める大きさで載せる。A4 縦に収めると文字が小さすぎる図は、図の大きさに合わせた用紙の
  1ページに等倍で載せる（本文は A4 縦のまま）。そのページには、図の直前の見出しと導入文も載せる。
  本文の図の前のページが大きく空くときは、図を少し縮めるか、文字の無い行で図を分けて、前のページへ詰める。
- 文書の最後（図だけのページの前も）で数行だけがはみ出すときは、まず余白を少し詰めて前のページに入れる（字の大きさは 10.5pt のまま）。それでも収まらないときは、その文書だけ字を少し小さくして収める。
- 人が読む内容だけを入れる。SKIP_PAGES のページ（AI向けの書き方と GitHub の設定）と、summary が「AI向け：」で始まる
  details は入れない。
- 画像が1つでも読み込めなければ、PDF を作らずに失敗する。

ふつうは scripts/build-pdf.sh から呼ぶ。
"""

from __future__ import annotations

import argparse
import functools
import html
import http.server
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from urllib.parse import quote, unquote

import yaml
from playwright.sync_api import Browser, Page, sync_playwright
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject, TextStringObject

ROOT = Path(__file__).resolve().parents[1]

def _load_check_own_page_marks():
    """同じフォルダの hyphen つきスクリプトから、印の検査を読む。"""
    import importlib.util

    path = Path(__file__).with_name("check-own-page-marks.py")
    spec = importlib.util.spec_from_file_location("check_own_page_marks", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"読めません: {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.check_own_page_marks


check_own_page_marks = _load_check_own_page_marks()

# Chromium の PDF を読むときの、害の無い警告を出さない
logging.getLogger("pypdf").setLevel(logging.ERROR)

# 用紙と余白（mm）。図の大きさの計算にも使う。
PAGE_W_MM, PAGE_H_MM = 210, 297
MARGIN_MM = {"top": 15, "bottom": 18, "left": 14, "right": 14}
PX_PER_MM = 96 / 25.4
PT_PER_PX = 0.75
CONTENT_W_PX = int((PAGE_W_MM - MARGIN_MM["left"] - MARGIN_MM["right"]) * PX_PER_MM)
CONTENT_H_PX = int((PAGE_H_MM - MARGIN_MM["top"] - MARGIN_MM["bottom"]) * PX_PER_MM)
# 本文に置く図の倍率の下限。A4 縦の幅と高さに収めた倍率がこれより小さい図は、
# 図の大きさに合わせた用紙の1ページに、等倍で載せる（0.75 で、11px の文字が約 6pt）。
BODY_MIN_SCALE = 0.75
# PDF の1ページの最大の寸法（200インチ）。図のページがこれを超えるときだけ、図を縮めて収める。
MAX_PAGE_MM = 5080

# 印刷のときだけ足す CSS。サイトの CSS は変えない。
# サイトの CSS の @page の余白（25mm）は、下の MARGIN_MM に置きかえる。
PRINT_CSS = f"""
@page {{ size: A4; margin: {MARGIN_MM["top"]}mm {MARGIN_MM["right"]}mm {MARGIN_MM["bottom"]}mm {MARGIN_MM["left"]}mm; }}
html, body {{ background: #fff !important; }}
.md-header, .md-tabs, .md-sidebar, .md-footer, .md-search, .md-top, .md-dialog,
.md-content__button, .md-source, .md-banner, .headerlink, .md-clipboard, .md-code__nav, .md-code__button,
button[title] {{ display: none !important; }}
/* サイトの CSS は .md-main__inner を display: flex にする。印刷で用紙の大きさがページごとに違うと（大きい図のページ
   と A4）、Chromium はこの flex のために文書全体を約67%に縮めて印刷し、A4 の本文 9pt が 6pt になる。ブロックに戻す */
.md-main__inner {{ margin: 0 !important; max-width: none !important; display: block !important; }}
.md-content {{ max-width: none !important; margin: 0 !important; }}
.md-content__inner {{ margin: 0 !important; padding: 0 !important; }}
.md-content__inner::before {{ display: none !important; }}
.md-typeset {{ font-size: 10.5pt; }}
.md-typeset img {{ max-width: 100%; height: auto; }}
.md-typeset .pdf-figure img {{ max-width: none !important; }}
/* 図と、そのすぐ後の「ソース:」は同じページに置く */
.pdf-figure {{ break-inside: avoid; }}
.pdf-figure.pdf-split {{ break-inside: auto; }}
.pdf-figure .pdf-rest {{ break-inside: avoid; }}
.pdf-figure > p {{ margin: 0.6em 0; }}
.pdf-clip {{ position: relative; overflow: hidden; }}
.pdf-clip > img {{ position: absolute; left: 0; top: 0; }}
.pdf-note {{ font-size: 9pt; color: #555; }}
/* 大きい図は、その図だけのページに載せる（用紙の大きさは図ごとに @page で決める） */
.pdf-figure[data-own] {{ break-before: page; break-after: page; }}
.pdf-lead {{ max-width: {CONTENT_W_PX}px; }}
.pdf-fig-title {{ font-weight: 700; }}
.md-typeset table:not([class]) {{ display: table; width: 100%; font-size: 9pt; }}
.md-typeset table:not([class]) tr {{ break-inside: avoid; }}
/* 表のセルの最後の行に1字だけ残らないよう、行の折り返しを整える（例:「…15分ロックす／る」） */
.md-typeset table:not([class]) td {{ text-wrap: pretty; }}
/* 言葉の途中で折り返さない（TAILS_JS が .pdf-word を付ける） */
.pdf-word {{ white-space: nowrap; }}
.md-typeset {{ line-break: strict; }}
.md-typeset table:not([class]) th, .md-typeset table:not([class]) td {{ padding: 0.6em 0.8em; }}
/* 表の見出しの色。サイト（stylesheets/extra.css）と同じ色にする */
.md-typeset table:not([class]) th {{ background-color: #e8edf4; color: #1a1a1a; }}
/* 表の中のコード（application/json など）は、途中で折り返さない */
.md-typeset table:not([class]) .pdf-nowrap {{ white-space: nowrap; }}
.md-typeset table:not([class]) code {{ white-space: nowrap; word-break: keep-all; overflow-wrap: normal; }}
/* A4 の本文の幅に収まらない表だけ（WIDE_TABLES_JS が data-wide を付ける）、段階を上げてコードを折り返す。
   1: 空白で折り返す（例:「POST /account-recovery/confirm」）。2: さらに / - _ . @ の後でも折り返す（WIDE_TABLES_JS が
   <wbr> を入れる。例:「/account-recovery/」「confirm」）。3: それでも収まらないときだけ、どこでも折り返す */
.md-typeset table[data-wide] code {{ white-space: normal; }}
.md-typeset table[data-wide="3"] code {{ overflow-wrap: anywhere; }}
.md-typeset .md-typeset__scrollwrap, .md-typeset .md-typeset__table {{ overflow: visible !important; display: block; }}
/* サイトの表は左右に少しはみ出す作りで、印刷では全体が縮むため、はみ出さないようにする */
.md-typeset .md-typeset__scrollwrap {{ margin: 1em 0 !important; }}
.md-typeset .md-typeset__table {{ padding: 0 !important; }}
.md-typeset h1, .md-typeset h2, .md-typeset h3 {{ break-after: avoid; }}
.md-typeset pre {{ white-space: pre-wrap; word-break: break-all; }}
.pdf-page {{ break-before: page; }}
.pdf-toc ul {{ list-style: none; }}
.pdf-toc a {{ color: inherit; text-decoration: none; }}
.pdf-toc .pdf-toc-group {{ font-weight: 700; margin-top: 0.6em; }}
/* 目次は1ページに収める */
.md-typeset .pdf-toc li {{ margin-bottom: 0.3em; }}
/* 目次の字は 9pt。本文と同じ 10.5pt だと、目次が2ページになる */
.md-typeset .pdf-toc {{ font-size: 9pt; }}
/* 文書の最後のページが1〜2行だけになるとき、字の大きさはそのまま、余白だけ少し詰めて前のページに入れる */
.md-typeset.pdf-pack-1 p, .md-typeset .pdf-pack-1 p,
.md-typeset.pdf-pack-1 pre, .md-typeset .pdf-pack-1 pre {{ margin: 0.7em 0; }}
.md-typeset.pdf-pack-1 h2, .md-typeset .pdf-pack-1 h2,
.md-typeset.pdf-pack-1 h3, .md-typeset .pdf-pack-1 h3 {{ margin-top: 1.15em; margin-bottom: 0.5em; }}
.md-typeset.pdf-pack-1 .md-typeset__scrollwrap, .md-typeset .pdf-pack-1 .md-typeset__scrollwrap {{ margin: 0.7em 0 !important; }}
.md-typeset.pdf-pack-2 p, .md-typeset .pdf-pack-2 p,
.md-typeset.pdf-pack-2 pre, .md-typeset .pdf-pack-2 pre {{ margin: 0.5em 0; }}
.md-typeset.pdf-pack-2 h2, .md-typeset .pdf-pack-2 h2,
.md-typeset.pdf-pack-2 h3, .md-typeset .pdf-pack-2 h3 {{ margin-top: 1em; margin-bottom: 0.4em; }}
.md-typeset.pdf-pack-2 .md-typeset__scrollwrap, .md-typeset .pdf-pack-2 .md-typeset__scrollwrap {{ margin: 0.5em 0 !important; }}
.md-typeset.pdf-pack-3, .md-typeset .pdf-pack-3 {{ line-height: 1.45; }}
.md-typeset.pdf-pack-3 p, .md-typeset .pdf-pack-3 p,
.md-typeset.pdf-pack-3 pre, .md-typeset .pdf-pack-3 pre {{ margin: 0.45em 0; }}
.md-typeset.pdf-pack-3 h2, .md-typeset .pdf-pack-3 h2,
.md-typeset.pdf-pack-3 h3, .md-typeset .pdf-pack-3 h3 {{ margin-top: 0.9em; margin-bottom: 0.35em; }}
.md-typeset.pdf-pack-3 .md-typeset__scrollwrap, .md-typeset .pdf-pack-3 .md-typeset__scrollwrap {{ margin: 0.45em 0 !important; }}
.md-typeset.pdf-pack-3 table:not([class]) th, .md-typeset .pdf-pack-3 table:not([class]) th,
.md-typeset.pdf-pack-3 table:not([class]) td, .md-typeset .pdf-pack-3 table:not([class]) td {{ padding: 0.45em 0.8em; }}
/* 余白を詰めても収まらないとき、その文書だけ字を少し小さくして詰める */
.md-typeset.pdf-tight-1, .md-typeset .pdf-tight-1 {{ font-size: 10pt; }}
.md-typeset.pdf-tight-2, .md-typeset .pdf-tight-2 {{ font-size: 9.5pt; }}
.pdf-tight-2 pre {{ margin: 0.6em 0; }}
"""

FOOTER = (
    '<div style="width:100%;font-size:8px;color:#666;text-align:center;'
    "font-family:'Noto Sans CJK JP',sans-serif;\">"
    '<span class="pageNumber"></span> / <span class="totalPages"></span></div>'
)
PDF_OPTIONS = dict(
    format="A4",
    print_background=True,
    display_header_footer=True,
    header_template="<div></div>",
    footer_template=FOOTER,
    margin={key: f"{value}mm" for key, value in MARGIN_MM.items()},
    outline=True,
    tagged=True,
    # 大きい図のページだけ図に合わせた用紙にするため、CSS の @page の用紙を使う
    prefer_css_page_size=True,
)


def source_base() -> str:
    """PDF の外へ出るリンク（.puml や nav に無いページ）の行き先にする、GitHub のファイルのURLのもと。

    ワークフローでは GITHUB_SERVER_URL・GITHUB_REPOSITORY と、PDF_SOURCE_REF（無ければ GITHUB_SHA）から作る。
    手元では git remote と HEAD から作る。
    """
    server = os.environ.get("GITHUB_SERVER_URL", "").rstrip("/")
    repository = os.environ.get("GITHUB_REPOSITORY", "").strip("/")
    ref = os.environ.get("PDF_SOURCE_REF") or os.environ.get("GITHUB_SHA", "")
    if not (server and repository):
        remote = subprocess.run(
            ["git", "remote", "get-url", "origin"], cwd=ROOT, text=True, capture_output=True
        ).stdout.strip()
        match = re.match(r"^(?:https?://)(?:[^@/]+@)?([^/]+)/(.+?)(?:\.git)?/?$", remote) or re.match(
            r"^(?:ssh://)?[^@/]+@([^:/]+)[:/](.+?)(?:\.git)?/?$", remote
        )
        if not match:
            return ""
        server, repository = f"https://{match.group(1)}", match.group(2)
    if not ref:
        ref = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True).stdout.strip()
    return f"{server}/{repository}/blob/{ref or 'main'}/"


# 同じサイトの中を指すリンクのうち、PDF の中に無いものを、GitHub のファイルへのリンクにする JS。
# pages は「サイトの中のパス → 原稿のパス」。
OUTSIDE_LINK_JS = """
(root, pages, base) => {
  const outside = (url) => {
    const path = decodeURIComponent(url.pathname).replace(/^\\//, '');
    const source = pages['/' + path];
    if (source !== undefined) return base + encodeURI(source) + url.hash;
    return base + encodeURI(path) + url.hash;
  };
  root.querySelectorAll('a[href]').forEach(a => {
    const url = new URL(a.getAttribute('href'), location.href);
    if (url.origin !== location.origin) return;
    if (a.getAttribute('href').startsWith('#')) return;
    a.setAttribute('href', base ? outside(url) : url.href);
  });
}
"""


# PDF に入れないページ（原稿のパス）。人が読む設計書ではないもの（AI向けの書き方、GitHub の設定）。
# PDF の中のこのページへのリンクも消す。
SKIP_PAGES = ("docs/guide.md", "docs/setup.md")

# PDF に入れない内容を消す JS。summary が「AI向け：」で始まる details を消し、SKIP_PAGES へのリンクは、
# 項目がそのリンクだけなら項目ごと消し、文の中なら文字だけにする。消したものを返す。
SKIP_JS = """
(skipPaths) => {
  const removed = [];
  document.querySelectorAll('article details').forEach(d => {
    const summary = d.querySelector(':scope > summary');
    if (summary && summary.textContent.trim().startsWith('AI向け：')) {
      removed.push('details「' + summary.textContent.trim() + '」');
      d.remove();
    }
  });
  document.querySelectorAll('article a[href]').forEach(a => {
    const url = new URL(a.getAttribute('href'), location.href);
    if (url.origin !== location.origin || !skipPaths.includes(decodeURIComponent(url.pathname))) return;
    const item = a.closest('li');
    if (item && item.textContent.trim() === a.textContent.trim()) {
      removed.push('リンクの項目「' + a.textContent.trim() + '」');
      item.remove();
    } else {
      removed.push('リンク「' + a.textContent.trim() + '」を文字だけに');
      a.replaceWith(a.textContent);
    }
  });
  return removed;
}
"""


class _Loader(yaml.SafeLoader):
    """mkdocs.yml の !!python/... などのタグを読み飛ばす。"""


_Loader.add_multi_constructor("", lambda loader, suffix, node: None)
_Loader.add_multi_constructor("tag:yaml.org,2002:python/", lambda loader, suffix, node: None)


def page_url(src: str) -> str:
    """原稿のパス（mkdocs.yml の nav の値）を、サイトの中のパスにする（use_directory_urls: true）。"""
    path = Path(src)
    if path.name in ("README.md", "index.md"):
        parent = path.parent.as_posix()
        return "" if parent == "." else parent + "/"
    return (path.parent / path.stem).as_posix().lstrip("./") + "/"


def walk_nav(items, trail=()):
    """nav を順にたどり、(見出しの並び, 原稿のパス) を返す。"""
    for item in items:
        if isinstance(item, str):
            yield trail, None, item
            continue
        for title, value in item.items():
            if isinstance(value, list):
                yield trail + (title,), None, None
                yield from walk_nav(value, trail + (title,))
            else:
                yield trail, title, value


def shown(path: Path) -> str:
    """表示用のパス。リポジトリの中なら相対パスにする。"""
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def serve(site: Path) -> tuple[http.server.ThreadingHTTPServer, str]:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(site))

    class Quiet(handler.func):  # type: ignore[misc]
        def log_message(self, *args):  # noqa: D401
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(site)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/"


# 読み込み中の画像を待つ JS。
WAIT_IMAGES_JS = """
async () => {
  await Promise.all([...document.images].map(img => img.complete ? null
    : new Promise(done => { img.addEventListener('load', done); img.addEventListener('error', done); })));
  await document.fonts.ready;
}
"""

# 読み込めなかった画像の URL を返す JS。
BROKEN_IMAGES_JS = """
() => [...document.querySelectorAll('img')]
  .filter(img => !img.complete || img.naturalWidth === 0)
  .map(img => img.getAttribute('src'))
"""


def check_images(page: Page, what: str) -> None:
    page.evaluate(WAIT_IMAGES_JS)
    broken = page.evaluate(BROKEN_IMAGES_JS)
    if broken:
        lines = "\n".join(f"  - {unquote(src)}" for src in broken)
        sys.exit(f"エラー: {unquote(what)} で、読み込めない画像があります。PDF を作らずに止めます。\n{lines}")


# 見出しの id は日本語だと長く、PDF の名前つきの行き先の上限（127バイト）を超えるので、短いハッシュにする。
SHORT_JS = """
(text) => {
  let h = 0x811c9dc5;
  for (const c of new TextEncoder().encode(text)) { h ^= c; h = Math.imul(h, 0x01000193) >>> 0; }
  return h.toString(36);
}
"""

# 1ページの PDF で、id とページの中へのリンクを短いハッシュにする JS。
SHORT_IDS_JS = f"""
() => {{
  const short = ({SHORT_JS});
  const root = document.querySelector('article.md-content__inner');
  root.querySelectorAll('[id]').forEach(e => {{ e.id = 'h' + short(e.id); }});
  root.querySelectorAll('a[href^="#"]').forEach(a => {{
    const hash = decodeURIComponent(a.getAttribute('href').slice(1));
    if (hash) a.setAttribute('href', '#h' + short(hash));
  }});
}}
"""

# 表で、短いセル（「メールアドレス」など10文字以下）は折り返さない。列の幅は、長い説明の列が詰めて受け持つ。
# リンク1つだけのセル（業務フローの表の API 名、例:「パスキーログインAPI」）は、15文字以下まで折り返さない。
# 11文字の名前が「パスキーログインAP／I」のように1字だけ次の行に落ちるのを防ぐ。
SHORT_CELLS_JS = """
() => document.querySelectorAll('article table th, article table td').forEach(cell => {
  const text = cell.textContent.trim();
  const onlyLink = cell.children.length === 1 && cell.children[0].tagName === 'A' && cell.children[0].textContent.trim() === text;
  if (text.length <= (onlyLink ? 15 : 10)) cell.classList.add('pdf-nowrap');
})
"""

# 段落・箇条書き・表のセルで、言葉の途中や1字だけを次の行に残して折り返さない JS。
# カタカナ語（例: ページ、エラーコード）、漢字＋送り仮名、短い助詞を一塊にする。
# 以前は最後の4字だけを対象にしていたため、「ペ／ージ分け」「エラーコー／ドは返さない」が残っていた。
TAILS_JS = """
(W) => {
  const skipSel = '.pdf-nowrap, pre, code, kbd, .pdf-word';
  const wordRe = /[ァ-ヶー]+|[A-Za-z0-9][A-Za-z0-9._@-]*|[一-龥々〆〇]+[ぁ-ゖ]*|[ぁ-ゖ]+|[^ァ-ヶーA-Za-z0-9一-龥々〆〇ぁ-ゖ]+/g;
  const isWord = (s) => /[ァ-ヶーA-Za-z0-9一-龥々〆〇ぁ-ゖ]/.test(s);
  const isShortHira = (s) => /^[ぁ-ゖ]+$/.test(s) && [...s].length <= 3;
  const wordSpan = (s) => {
    const span = document.createElement('span');
    span.className = 'pdf-word';
    span.textContent = s;
    return span;
  };

  // 短いリンク（「ページ分け」など）は、リンクごと一塊にする
  document.querySelectorAll('article a').forEach(a => {
    if (a.closest('.pdf-nowrap, pre, code')) return;
    const t = a.textContent.trim();
    if (t && [...t].length <= 15 && !a.querySelector('img')) a.classList.add('pdf-word');
  });

  document.querySelectorAll('article p, article li, article td, article th').forEach(el => {
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    const nodes = [];
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      if (n.parentElement.closest(skipSel)) continue;
      nodes.push(n);
    }
    nodes.forEach(node => {
      const text = node.textContent;
      if (!text) return;
      const parts = text.match(wordRe);
      if (!parts) return;
      if (parts.length === 1 && !isWord(parts[0])) return;
      const merged = [];
      for (const part of parts) {
        if (isShortHira(part) && merged.length && isWord(merged[merged.length - 1])) {
          merged[merged.length - 1] += part;
        } else {
          merged.push(part);
        }
      }
      for (let i = 0; i < merged.length - 1; i++) {
        if (isShortHira(merged[i]) && isWord(merged[i + 1])) {
          merged[i + 1] = merged[i] + merged[i + 1];
          merged[i] = null;
        }
      }
      const frag = document.createDocumentFragment();
      for (const part of merged) {
        if (part == null) continue;
        if (isWord(part) && [...part].length >= 2) frag.append(wordSpan(part));
        else frag.append(part);
      }
      node.replaceWith(frag);
    });
  });

  // 一塊がセルや段に収まらないときだけ、その塊の nowrap を外す（表が広がって文書全体が縮むのを防ぐ）
  const root = document.querySelector('article.md-content__inner');
  if (!root || W == null) return;
  const prev = root.style.width;
  root.style.width = W + 'px';
  root.querySelectorAll('.pdf-word').forEach(span => {
    const box = span.closest('td, th, p, li') || span.parentElement;
    if (span.getBoundingClientRect().width > box.getBoundingClientRect().width + 0.5) {
      span.classList.remove('pdf-word');
    }
  });
  root.style.width = prev;
}
"""

# A4 の本文の幅（W）より広い表に、コードを折り返す段階（data-wide）を付ける JS。広い表が1つでもあると、
# Chromium はその文書全体を縮めて印刷する（まとめた PDF では全部の文書が縮む）。収まる表は変えない。
WIDE_TABLES_JS = """
(W) => {
  const root = document.querySelector('article.md-content__inner');
  const width = root.style.width;
  root.style.width = W + 'px';
  // 箇条書きの中の表は字下げの分だけ狭いので、幅ではなく右端で比べる
  const right = root.getBoundingClientRect().left + W + 0.5;
  const wide = [];
  root.querySelectorAll('table').forEach(table => {
    const before = Math.round(table.getBoundingClientRect().width);
    for (const level of ['1', '2', '3']) {
      if (table.getBoundingClientRect().right <= right) break;
      table.dataset.wide = level;
      if (level === '2') table.querySelectorAll('code').forEach(code => {
        // 区切りの後ろが2字以上残るところだけに入れる（1字だけ次の行に落ちないように）
        const text = code.textContent;
        const parts = text.split(/(?<=[\\/\\-_.@])(?=[^\\/\\-_.@]{2})/);
        if (parts.length < 2) return;
        code.replaceChildren(...parts.flatMap((part, i) => i ? [document.createElement('wbr'), part] : [part]));
      });
    }
    if (table.dataset.wide) wide.push([table.dataset.wide, before, Math.round(table.getBoundingClientRect().right - right + 0.5)]);
  });
  root.style.width = width;
  return wide;
}
"""

# 図を、文字が読める大きさにする JS。
# - 画像だけの段落を div.pdf-figure で包み、すぐ後の「ソース:」の段落も中に入れる（同じページに置くため）。
# - 図は、A4 縦の幅と高さに収まる大きさにする。その倍率が BODY_MIN_SCALE より小さい図と、
#   画像に pdf-own-page の印がある図（インフラ構成の図）は等倍にし、data-own を付ける。
#   あとで PAGES_JS が、図の大きさに合わせた用紙のページにする。前の節の本文の残りには詰めない。
#   図の直前の見出しと導入文（合わせて H の半分まで）も、div.pdf-lead にして図のページの上に載せる。
#   前のページに見出しと数行だけが残って、ほぼ空になるのを防ぎ、図のページで何の図か分かるようにする。
# - SVG の文字の上下の位置を data-texts に残す。あとで図を分けるとき、文字の無い行で切るのに使う。
FIGURES_JS = """
async ([W, H, BODY_MIN]) => {
  const root = document.querySelector('article.md-content__inner');
  const hidden = document.createElement('div');
  hidden.style.cssText = 'position:absolute;left:-100000px;top:0;visibility:hidden';
  document.body.appendChild(hidden);
  const boxesOf = async (src) => {
    const text = await (await fetch(src)).text();
    const svg = new DOMParser().parseFromString(text, 'image/svg+xml').documentElement;
    if (svg.nodeName.toLowerCase() !== 'svg') return null;
    const node = document.importNode(svg, true);
    hidden.appendChild(node);
    const box = (e) => { const b = e.getBBox(); return [b.x, b.y, b.x + b.width, b.y + b.height]; };
    const texts = [...node.querySelectorAll('text')].map(box);
    node.remove();
    return { texts };
  };
  const figures = [];
  for (const img of [...root.querySelectorAll('img')]) {
    const p = img.parentElement;
    if (!p || p.tagName !== 'P' || p.textContent.trim() !== '' || p.querySelectorAll('img').length !== 1) continue;
    const nw = img.naturalWidth, nh = img.naturalHeight;
    if (!nw || !nh) continue;
    const fig = document.createElement('div');
    fig.className = 'pdf-figure';
    p.before(fig);
    fig.appendChild(p);
    const next = fig.nextElementSibling;
    if (next && next.tagName === 'P' && /^(ソース|出典)/.test(next.textContent.trim())) fig.appendChild(next);
    const isSvg = /\\.svg$/i.test(new URL(img.src).pathname);
    const boxes = isSvg ? await boxesOf(img.src) : null;
    if (boxes) fig.dataset.texts = JSON.stringify(boxes.texts.map(b => [Math.floor(b[1]), Math.ceil(b[3])]));
    fig.dataset.w = nw;
    fig.dataset.h = nh;
    let scale = Math.min(1, W / nw, (H - 80) / nh);
    const lead = [];
    let height = 0;
    let el = fig.previousElementSibling;
    while (el && !el.classList.contains('pdf-figure') && !el.querySelector('.pdf-figure')) {
      height += el.getBoundingClientRect().height;
      if (height > H / 2) break;
      lead.unshift(el);
      if (/^H[1-6]$/.test(el.tagName)) break;
      el = el.previousElementSibling;
    }
    // インフラ構成の図は、原稿の画像に付けた印（pdf-own-page）で、大きさに関わらず等倍の専用ページにする
    const isOwn = img.classList.contains('pdf-own-page');
    if (scale < BODY_MIN || isOwn) {
      scale = 1;
      fig.dataset.own = '1';
      const box = document.createElement('div');
      box.className = 'pdf-lead';
      if (lead.length) box.append(...lead);
      // 見出しを載せられないとき（前が図など）は、どのページの何の節の図か分かるよう、見出しの文字を短く入れる
      if (!box.querySelector('h1, h2, h3, h4, h5, h6')) {
        const text = (h) => { const c = h.cloneNode(true); c.querySelectorAll('.headerlink').forEach(e => e.remove()); return c.textContent.trim(); };
        const heads = [...root.querySelectorAll('h1, h2, h3, h4, h5, h6')]
          .filter(h => h.compareDocumentPosition(fig) & Node.DOCUMENT_POSITION_FOLLOWING);
        const names = [heads.find(h => h.tagName === 'H1'), heads[heads.length - 1]].filter(Boolean).map(text);
        const title = document.createElement('p');
        title.className = 'pdf-fig-title';
        title.textContent = [...new Set(names)].join(' ― ') + '（つづき）';
        box.prepend(title);
      }
      fig.prepend(box);
      // 図が本文の先頭なら、前に改ページしない。図より前にある高さ0の要素も消す。
      // 残すと、それだけの A4 の空のページが先頭にできる（図のページは用紙が違うため）
      const empty = (e) => !e.getBoundingClientRect().height;
      let before = fig.previousElementSibling;
      while (before && empty(before)) before = before.previousElementSibling;
      if (!before) {
        fig.style.breakBefore = 'auto';
        for (let e = fig; e && e !== document.body; e = e.parentElement) {
          for (let s = e.previousElementSibling; s; s = s.previousElementSibling) if (empty(s)) s.style.display = 'none';
        }
      }
    }
    fig.dataset.scale = scale;
    img.style.width = nw * scale + 'px';
    img.style.height = nh * scale + 'px';
    figures.push(fig);
  }
  hidden.remove();
  await Promise.all([...document.images].map(i => i.complete ? null : new Promise(r => { i.onload = i.onerror = r; })));
  return figures.length;
}
"""

# 図の位置を PDF から読むために、図と各ページの先頭に目印のリンクを付ける（外すときは false）。
MARK = "https://pdf-figure.invalid/"
MARK_JS = f"""
(on) => {{
  document.querySelectorAll('a.pdf-mark').forEach(a => {{ a.replaceWith(...a.childNodes); }});
  if (!on) return;
  const wrap = (el, name) => {{
    const a = document.createElement('a');
    a.className = 'pdf-mark';
    a.href = '{MARK}' + name;
    a.style.cssText = 'display:block;color:inherit;text-decoration:none';
    el.before(a);
    a.appendChild(el);
  }};
  const sections = [...document.querySelectorAll('section.pdf-page')];
  const roots = sections.length ? sections : [document.querySelector('article.md-content__inner')];
  roots.forEach((root, s) => {{
    const first = root.firstElementChild;
    if (first) wrap(first, 's' + s);
    root.querySelectorAll('.pdf-figure').forEach(fig => {{
      fig.dataset.section = s;
      wrap(fig, 'f' + [...document.querySelectorAll('.pdf-figure')].indexOf(fig));
    }});
  }});
  // 図そのもの（分けたものは各部分）の位置。ページの本文の下端を読むのに使う
  document.querySelectorAll('.pdf-figure > p, .pdf-figure .pdf-clip').forEach((el, i) => wrap(el, 'b' + i));
}}
"""

# 図を縮める・分ける JS。kind は 'shrink'（value は新しい倍率）か 'split'（value は前の部分の高さの上限 px）。
FIX_JS = """
([index, kind, value]) => {
  const fig = document.querySelectorAll('.pdf-figure')[index];
  const img = fig.querySelector('p > img');
  const nw = +fig.dataset.w, nh = +fig.dataset.h, scale = +fig.dataset.scale;
  fig.dataset.tried = '1';
  if (kind === 'none') return false;
  if (kind === 'shrink') {
    fig.dataset.scale = value;
    img.style.width = nw * value + 'px';
    img.style.height = nh * value + 'px';
    return true;
  }
  // 文字の無い行で切る。前の部分は value px 以下で、図の 20% 以上にする。
  const texts = JSON.parse(fig.dataset.texts || '[]');
  const free = (y) => texts.every(([top, bottom]) => y < top - 3 || y > bottom + 3);
  let cut = 0;
  for (let y = Math.floor(value / scale); y >= nh * 0.2; y--) { if (free(y)) { cut = y; break; } }
  if (!cut) return false;
  const p = img.parentElement;
  const part = (top, height) => {
    const clip = document.createElement('div');
    clip.className = 'pdf-clip';
    clip.style.width = nw * scale + 'px';
    clip.style.height = Math.ceil(height * scale) + 'px';
    const copy = img.cloneNode();
    copy.style.top = -top * scale + 'px';
    clip.appendChild(copy);
    return clip;
  };
  const rest = document.createElement('div');
  rest.className = 'pdf-rest';
  const caption = document.createElement('p');
  caption.className = 'pdf-note';
  caption.textContent = '（図のつづき）';
  rest.append(caption, part(cut, nh - cut));
  while (p.nextSibling) rest.appendChild(p.nextSibling);
  p.replaceChildren(part(0, cut));
  p.after(rest);
  fig.classList.add('pdf-split');
  return true;
}
"""


def open_page(browser: Browser, url: str, links: dict | None = None, short_ids: bool = False) -> Page:
    page = browser.new_page(color_scheme="light")
    page.goto(url, wait_until="networkidle")
    check_images(page, url)
    for item in page.evaluate(SKIP_JS, ["/" + page_url(src) for src in SKIP_PAGES]):
        print(f"  PDF から外しました: {unquote(url.split('/', 3)[-1]) or 'トップ'} の{item}")
    if links is not None:
        page.evaluate(f"([pages, base]) => ({OUTSIDE_LINK_JS})(document, pages, base)", [links["pages"], links["base"]])
    if short_ids:
        page.evaluate(SHORT_IDS_JS)
    page.add_style_tag(content=PRINT_CSS)
    # 閉じた details も中身を印刷する
    page.evaluate("document.querySelectorAll('details').forEach(d => d.open = true)")
    page.evaluate(SHORT_CELLS_JS)
    page.evaluate(TAILS_JS, CONTENT_W_PX)
    for level, width, over in page.evaluate(WIDE_TABLES_JS, CONTENT_W_PX):
        note = "" if over <= 0 else f"、まだ {over}px はみ出す"
        print(f"  広い表のコードを折り返しました: {unquote(url.split('/', 3)[-1])}（段階{level}、元の幅 {width}px{note}）")
    page.evaluate(FIGURES_JS, [CONTENT_W_PX, CONTENT_H_PX, BODY_MIN_SCALE])
    page.evaluate("document.fonts.ready")
    return page


HEADINGS_JS = """
() => [...document.querySelectorAll('article h1, article h2, article h3, article h4, article h5, article h6')]
  .filter(h => h.offsetParent !== null)
  .map(h => [(h.matches('#pdf-toc') || (h.tagName === 'H1' && !!h.closest('.pdf-page') && h.closest('.pdf-page').querySelector('h1') === h)), (c => { c.querySelectorAll('.headerlink').forEach(e => e.remove()); return c.textContent; })(h.cloneNode(true)).replace(/\\s+/g, ' ').trim()])
"""


def set_outline_titles(path: Path, headings: list[str]) -> None:
    """しおりの名前を、本文の見出しの文字に置きかえる。

    Chromium は、ページの先頭に来た見出しのしおりを「用語集用語集」のように、
    行の切れ端と全体をつなげた名前で作ることがある。しおりは本文の見出しと同じ順に並ぶので、
    数が合えば、上から順に見出しの文字で置きかえる。数が合わなければ、何もしない。
    """
    writer = PdfWriter(clone_from=str(path))
    root = writer._root_object.get("/Outlines")
    items = []

    def walk(node) -> None:
        while node is not None:
            item = node.get_object()
            items.append(item)
            if "/First" in item:
                walk(item["/First"])
            node = item.get("/Next")

    if root is not None and "/First" in root.get_object():
        walk(root.get_object()["/First"])
    if len(items) != len(headings):
        print(f"注意: しおりの数（{len(items)}）が見出しの数（{len(headings)}）と合わないため、名前を直しません: {path.name}")
        return
    for item, title in zip(items, headings):
        item[NameObject("/Title")] = TextStringObject(title)
    with path.open("wb") as handle:
        writer.write(handle)


def read_layout(path: Path) -> tuple[list[float], dict[str, list[tuple[int, list[float]]]], list[float]]:
    """印刷した PDF から、ページごとの本文のいちばん下の位置と、目印（図と各ページの先頭）の位置を読む。"""
    reader = PdfReader(str(path))
    bottom_margin = MARGIN_MM["bottom"] * 72 / 25.4
    bottoms: list[float] = []
    marks: dict[str, list[tuple[int, list[float]]]] = {}
    heights: list[float] = []
    for number, page in enumerate(reader.pages):
        height = float(page.mediabox.height)
        heights.append(height)
        ys: list[float] = []

        def visit(text, cm, tm, font, size) -> None:
            if text.strip():
                ys.append(tm[4] * cm[1] + tm[5] * cm[3] + cm[5])

        page.extract_text(visitor_text=visit)
        for annot in page.get("/Annots") or []:
            annot = annot.get_object()
            uri = str(annot.get("/A", {}).get("/URI", ""))
            if uri.startswith(MARK):
                x0, y0, x1, y1 = (float(v) for v in annot["/Rect"])
                name = uri[len(MARK):]
                marks.setdefault(name, []).append((number, [min(y0, y1), max(y0, y1)]))
                if name.startswith("b"):
                    ys.append(min(y0, y1))
        body = [y for y in ys if y > bottom_margin]
        bottoms.append(min(body) if body else height)
    return bottoms, marks, heights


def fit_figures(page: Page, label: str) -> None:
    """図の前のページが大きく空くとき、図を少し縮めるか分けて、前のページへ詰める。

    いったん印刷して図の位置を読み、ページ（まとめた PDF ではその中の各ページ）ごとに、
    最初の1つを直して、また印刷する。直すものが無くなるまで繰り返す。
    """
    top_margin = MARGIN_MM["top"] * 72 / 25.4
    bottom_margin = MARGIN_MM["bottom"] * 72 / 25.4
    with tempfile.TemporaryDirectory() as work:
        probe = Path(work) / "probe.pdf"
        for _ in range(8):
            page.evaluate(MARK_JS, True)
            page.evaluate(WAIT_IMAGES_JS)
            page.pdf(path=str(probe), **PDF_OPTIONS)
            page.evaluate(MARK_JS, False)
            bottoms, marks, heights = read_layout(probe)
            figures = page.evaluate(
                "() => [...document.querySelectorAll('.pdf-figure')].map(f => "
                "[+f.dataset.section, !!f.dataset.tried, !!f.dataset.own, +f.dataset.scale, +f.dataset.h])"
            )
            done_sections = set()
            changed = False
            for index, (section, tried, own, scale, natural_h) in enumerate(figures):
                where = marks.get(f"f{index}")
                start = marks.get(f"s{section}")
                if tried or section in done_sections or not where or not start:
                    continue
                number, (low, high) = where[0]
                # 前のページが図だけのページ（用紙の大きさが違う）のときは詰めない
                if number == 0 or number <= start[0][0] or heights[number - 1] != heights[number]:
                    continue
                height = heights[number]
                content = height - top_margin - bottom_margin
                blank = bottoms[number - 1] - bottom_margin
                above = (height - top_margin) - high
                # 図のページの上に見出しがあるとき（見出しは break-after: avoid で図と一緒に送られる）も詰める。
                # 見出しと導入の高さ（本文の 1/4 まで）は、図がページ先頭に近いと見て許容する。
                if blank < content * 0.2 or above > content * 0.25:
                    continue
                figure_h = high - low
                image_h = natural_h * scale * PT_PER_PX
                # 前のページがほぼ空（本文が 1/4 未満）のときは、本文に置く図の下限まで縮めてよい。
                # 余裕は多めに取る。見出しがページ途中に来ると、ページ先頭では潰れていた上余白が乗るため。
                almost_blank = blank >= content * 0.75
                slack = 60 if almost_blank else 10
                min_scale = BODY_MIN_SCALE if almost_blank else scale * 0.85
                room = blank - above - slack
                new_scale = scale * (room - (figure_h - image_h)) / image_h
                if own:
                    # 図だけのページに載せる図は、縮めも分けもしない
                    page.evaluate(FIX_JS, [index, "none", 0])
                    continue
                if new_scale >= min_scale:
                    page.evaluate(FIX_JS, [index, "shrink", new_scale])
                elif page.evaluate(FIX_JS, [index, "split", room / PT_PER_PX - 30]):
                    pass
                else:
                    page.evaluate(FIX_JS, [index, "none", 0])
                    continue
                done_sections.add(section)
                changed = True
            if not changed:
                return
        print(f"注意: 図の位置の調整が終わりませんでした: {label}")


# data-own の図を、図の大きさに合わせた用紙の1ページにする JS。用紙は、図とソースの行の大きさに余白を足したもの。
# 1辺が MAX_PAGE_MM を超えるときだけ、図を縮めて収める。名前つきの @page を図ごとに作る。
PAGES_JS = """
([PX, M, MAX, MIN_W]) => {
  document.querySelectorAll('style.pdf-pages').forEach(s => s.remove());
  const rules = [];
  const sizes = [];
  document.querySelectorAll('.pdf-figure[data-own]').forEach((fig, i) => {
    const img = fig.querySelector('p > img');
    const nw = +fig.dataset.w, nh = +fig.dataset.h;
    const size = (zoom) => {
      img.style.width = nw * zoom + 'px';
      img.style.height = nh * zoom + 'px';
      const extra = fig.getBoundingClientRect().height - nh * zoom + 40;
      return [Math.max(nw * zoom, MIN_W) / PX + M.left + M.right, (nh * zoom + extra) / PX + M.top + M.bottom, extra];
    };
    let zoom = 1;
    let [w, h, extra] = size(zoom);
    if (w > MAX || h > MAX) {
      zoom = Math.min((MAX - M.left - M.right) * PX / nw, ((MAX - M.top - M.bottom) * PX - extra) / nh);
      [w, h] = size(zoom);
    }
    w = Math.ceil(w);
    h = Math.ceil(h);
    const name = 'pdf-fig-' + i;
    rules.push(`@page ${name} { size: ${w}mm ${h}mm; }`);
    fig.style.page = name;
    fig.dataset.scale = zoom;
    sizes.push([img.getAttribute('alt') || '', w, h, Math.round(zoom * 100)]);
  });
  const style = document.createElement('style');
  style.className = 'pdf-pages';
  style.textContent = rules.join('\\n');
  document.head.appendChild(style);
  return sizes;
}
"""


# 文書（まとめた PDF ではその中の各ページ）に、余白を詰める段階と字を小さくする段階を付ける JS。
# pack も tight も 0 は元のまま。
STYLE_JS = """
([index, pack, tight]) => {
  const sections = [...document.querySelectorAll('section.pdf-page')];
  const root = sections.length ? sections[index] : document.querySelector('article.md-content__inner');
  root.classList.remove('pdf-pack-1', 'pdf-pack-2', 'pdf-pack-3', 'pdf-tight-1', 'pdf-tight-2');
  if (pack) root.classList.add('pdf-pack-' + pack);
  if (tight) root.classList.add('pdf-tight-' + tight);
}
"""


def squeeze_tails(page: Page, label: str) -> None:
    """文書の最後だけがはみ出したページを、前のページに収める。

    文書（まとめた PDF ではその中の各ページ）の2ページ目以降で、次が別の文書か図だけのページか PDF の終わりの
    A4 のページに、本文がページの 1/4 未満しかないとき、まず余白と行間を詰める（字は 10.5pt のまま。3段階）。
    それでもページが減らなければ、その文書の字を少し小さくする（10pt、9.5pt の2段階まで）。
    印刷して、その文書のページが減らなければ、前の段階に戻す。図だけのページの大きさは変えない。
    """
    top_margin = MARGIN_MM["top"] * 72 / 25.4
    bottom_margin = MARGIN_MM["bottom"] * 72 / 25.4
    a4_height = round(PAGE_H_MM * 72 / 25.4)
    packs: dict[int, int] = {}
    tights: dict[int, int] = {}
    with tempfile.TemporaryDirectory() as work:
        probe = Path(work) / "probe.pdf"

        def layout() -> tuple[dict[int, int], set[int], dict[int, float]]:
            page.evaluate(MARK_JS, True)
            page.evaluate(WAIT_IMAGES_JS)
            page.pdf(path=str(probe), **PDF_OPTIONS)
            page.evaluate(MARK_JS, False)
            bottoms, marks, heights = read_layout(probe)
            # 目印の枠は、前のページの最後にも高さ0で出ることがあるため、高さのある所を使う
            starts = sorted(
                (next((number for number, (low, high) in places if high - low > 5), places[-1][0]), int(name[1:]))
                for name, places in marks.items()
                if name.startswith("s")
            )
            counts, tails, last_used = {}, set(), {}
            for position, (first, section) in enumerate(starts):
                end = starts[position + 1][0] if position + 1 < len(starts) else len(heights)
                counts[section] = end - first
                for number in range(first + 1, end):
                    if round(heights[number]) != a4_height:
                        continue
                    last = number + 1 == end or round(heights[number + 1]) != a4_height
                    used = (heights[number] - top_margin - bottoms[number]) / (heights[number] - top_margin - bottom_margin)
                    if last and used < 0.25:
                        tails.add(section)
                        last_used[section] = min(used, last_used.get(section, 1))
            return counts, tails, last_used

        counts, tails, last_used = layout()

        def apply_style(section: int) -> None:
            page.evaluate(STYLE_JS, [section, packs.get(section, 0), tights.get(section, 0)])

        def try_levels(kind: str, values: dict[int, int], label_for: str, levels: tuple[int, ...] = (1, 2)) -> set[int]:
            leftover = set(tails)
            for level in levels:
                if not leftover:
                    break
                for section in leftover:
                    values[section] = level
                    apply_style(section)
                page.evaluate(PAGES_JS, [PX_PER_MM, MARGIN_MM, MAX_PAGE_MM, CONTENT_W_PX])
                new_counts, new_tails, _ = layout()
                for section in leftover:
                    if new_counts.get(section, 0) < counts.get(section, 0):
                        counts[section] = new_counts[section]
                    else:
                        values[section] = level - 1
                        if values[section] == 0:
                            values.pop(section, None)
                        apply_style(section)
                leftover = {section for section in leftover if values.get(section) != level or section in new_tails}
            return leftover

        tails = try_levels("pack", packs, "余白", (1, 2, 3))
        # 余白を詰めても文書末尾の短いページが残るときは、その詰めをやめる（短いページを増やさない）
        for section in [s for s in packs if s in tails]:
            packs.pop(section, None)
            apply_style(section)
        if packs:
            page.evaluate(PAGES_JS, [PX_PER_MM, MARGIN_MM, MAX_PAGE_MM, CONTENT_W_PX])
            counts, tails, last_used = layout()
        # 余白を詰めて短いページが消えた文書は、字を小さくしない（本文は 10.5pt のまま）。
        # 1〜2行程度の孤立行は、字を小さくせず余白の詰めで扱う。
        tails = {section for section in tails if section not in packs}
        # 1〜2行程度の孤立行は、文書全体の字を小さくせず、余白の詰めで扱う
        tails = {section for section in tails if last_used.get(section, 0) >= 0.15}
        tails = try_levels("tight", tights, "字", (1, 2))
        page.evaluate(PAGES_JS, [PX_PER_MM, MARGIN_MM, MAX_PAGE_MM, CONTENT_W_PX])
    titles = page.evaluate(
        "() => [...document.querySelectorAll('section.pdf-page')].map(s => (s.querySelector('h1') || s).textContent.replace('¶', '').trim())"
    )
    for section, level in sorted(packs.items()):
        where = f"{label} の「{titles[section]}」" if titles else label
        print(f"  余白を詰めて前のページに入れました: {where}（段階{level}、本文は10.5pt）")
    for section, level in sorted(tights.items()):
        where = f"{label} の「{titles[section]}」" if titles else label
        print(f"  字を小さくして詰めました: {where}（{['', '10pt', '9.5pt'][level]}）")


def print_pdf(page: Page, out: Path, label: str) -> list[list]:
    """図の位置を整えてから印刷し、しおりの名前を直すための見出しを返す。"""
    for alt, width, height, zoom in page.evaluate(PAGES_JS, [PX_PER_MM, MARGIN_MM, MAX_PAGE_MM, CONTENT_W_PX]):
        note = "" if zoom == 100 else f"、{zoom}% に縮小"
        print(f"  図のページ: {alt}（{width}×{height}mm{note}）")
    fit_figures(page, label)
    squeeze_tails(page, label)
    check_images(page, label)
    headings = page.evaluate(HEADINGS_JS)
    page.pdf(path=str(out), **PDF_OPTIONS)
    return headings


def print_one(browser: Browser, url: str, out: Path, links: dict) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    page = open_page(browser, url, links, short_ids=True)
    headings = [text for _, text in print_pdf(page, out, shown(out))]
    page.close()
    set_outline_titles(out, headings)
    print(f"作りました: {shown(out)}")


# まとめた PDF のために、1ページの本文を取り出し、id とリンクを書き換える JS。
EXTRACT_JS = f"""
([prefix, pageIds, pages, base]) => {{
  const article = document.querySelector('article.md-content__inner');
  const clone = article.cloneNode(true);
  const short = ({SHORT_JS});
  clone.querySelectorAll('.headerlink, .md-content__button').forEach(e => e.remove());
  clone.querySelectorAll('details').forEach(d => d.open = true);
  clone.querySelectorAll('[id]').forEach(e => {{ e.id = prefix + '-' + short(e.id); }});
  clone.querySelectorAll('a[href]').forEach(a => {{
    const url = new URL(a.getAttribute('href'), location.href);
    if (url.origin !== location.origin) return;
    const target = pageIds[decodeURIComponent(url.pathname)];
    if (target === undefined) {{ return; }}
    const hash = decodeURIComponent(url.hash.slice(1));
    a.setAttribute('href', '#' + target + (hash ? '-' + short(hash) : ''));
  }});
  clone.querySelectorAll('img[src]').forEach(e => {{
    e.setAttribute('src', new URL(e.getAttribute('src'), location.href).pathname);
  }});
  ({OUTSIDE_LINK_JS})(clone, pages, base);
  const h1 = clone.querySelector('h1');
  return {{ html: clone.innerHTML, title: h1 ? h1.textContent.trim() : '' }};
}}
"""


def in_combined(src: str) -> bool:
    """まとめた PDF に入れるページか。`_template` の型、変更履歴、SKIP_PAGES のページは入れない。"""
    path = Path(src)
    return (
        not any(part.startswith("_") for part in path.parts)
        and path.name != "変更履歴.md"
        and src not in SKIP_PAGES
    )


def build_combined(browser: Browser, base: str, site: Path, entries, out: Path, links: dict) -> None:
    pages = [e for e in entries if e["src"] and in_combined(e["src"])]
    page_ids = {}
    for index, entry in enumerate(pages):
        entry["id"] = f"p{index}"
        page_ids["/" + quote(entry["url"], safe="/")] = entry["id"]
        page_ids["/" + entry["url"]] = entry["id"]

    sections = []
    for entry in pages:
        page = open_page(browser, base + quote(entry["url"], safe="/"))
        data = page.evaluate(EXTRACT_JS, [entry["id"], page_ids, links["pages"], links["base"]])
        page.close()
        entry["title"] = data["title"] or entry["nav_title"]
        sections.append((entry, data["html"]))

    # 同じ見出しが並ぶと、しおりと目次で見分けられないため、nav の名前を「の」でつなぐ
    # （例: 入口と設計書がどちらも「支払いAPI」なら、「支払いAPIの入口」「支払いAPIの設計書」）
    counts: dict[str, int] = {}
    for entry, _ in sections:
        counts[entry["title"]] = counts.get(entry["title"], 0) + 1
    for entry, _ in sections:
        title = entry["title"]
        if counts[title] > 1 and entry["nav_title"] and entry["nav_title"] != title:
            title = f"{title}の{entry['nav_title']}"
        entry["display"] = title

    # 目次。ページの無いグループは出さない。グループ名が最初のページの名前と同じ（「記入例 」などを除いて）ときは、
    # グループ名をそのページへのリンクにして、同じ名前が2回並ばないようにする。
    toc = ['<nav class="pdf-toc"><h1 id="pdf-toc">目次</h1><ul>']
    included = {id(e) for e in pages}
    merged = set()
    for position, entry in enumerate(entries):
        depth = len(entry["trail"])
        indent = f' style="margin-left:{depth * 1.2}em"'
        if not entry["src"]:
            group = entry["trail"]
            children = [
                e for e in entries[position + 1 :]
                if e["src"] and id(e) in included and e["trail"][: len(group)] == group
            ]
            if not children:
                continue
            name = group[-1]
            first = children[0]
            if first["trail"] == group and name.split(" ")[-1] == first["title"]:
                merged.add(id(first))
                toc.append(
                    f'<li class="pdf-toc-group"{indent}><a href="#{first["id"]}">{html.escape(name)}</a></li>'
                )
            else:
                toc.append(f'<li class="pdf-toc-group"{indent}>{html.escape(name)}</li>')
            continue
        if id(entry) not in included or id(entry) in merged:
            continue
        toc.append(f'<li{indent}><a href="#{entry["id"]}">{html.escape(entry["display"])}</a></li>')
    toc.append("</ul></nav>")

    body = [f'<section class="pdf-page" id="{entry["id"]}">{content}</section>' for entry, content in sections]

    # サイトの先頭ページの head（CSS とフォント）をそのまま使い、公開サイトと同じ見た目にする
    top = (site / "index.html").read_text(encoding="utf-8")
    head = top[top.index("<head>") + len("<head>") : top.index("</head>")]
    document = (
        f'<!doctype html><html lang="ja"><head>{head}<style>{PRINT_CSS}</style></head>'
        '<body dir="ltr" data-md-color-scheme="default" data-md-color-primary="indigo" data-md-color-accent="indigo">'
        '<div class="md-container"><main class="md-main"><div class="md-main__inner md-grid">'
        '<div class="md-content"><article class="md-content__inner md-typeset">'
        + "".join(toc)
        + "".join(body)
        + "</article></div></div></main></div></body></html>"
    )
    combined = site / "_pdf_all.html"
    combined.write_text(document, encoding="utf-8")
    page = browser.new_page(color_scheme="light")
    page.goto(base + "_pdf_all.html", wait_until="networkidle")
    check_images(page, out.name)
    page.evaluate("document.fonts.ready")
    headings = print_pdf(page, out, shown(out))
    page.close()
    combined.unlink()
    # 各ページの h1 のしおりは、目次と同じ名前（同じ名前のページは nav の場所つき）にする
    labels = iter(["目次"] + [entry["display"] for entry, _ in sections])
    titles = [next(labels) if is_page_top else text for is_page_top, text in headings]
    set_outline_titles(out, titles)
    print(f"作りました: {shown(out)}（{len(pages)}ページ分、{len(PdfReader(str(out)).pages)}枚）")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--site", type=Path, required=True, help="mkdocs build の出力")
    parser.add_argument("--out", type=Path, required=True, help="PDF を出すフォルダ")
    args = parser.parse_args()

    check_own_page_marks()

    config = yaml.load((ROOT / "mkdocs.yml").read_text(encoding="utf-8"), Loader=_Loader)
    entries = [
        {"trail": trail, "nav_title": title, "src": src, "url": page_url(src) if src else None}
        for trail, title, src in walk_nav(config["nav"])
    ]

    links = {
        "pages": {"/" + e["url"]: e["src"] for e in entries if e["src"]},
        "base": source_base(),
    }
    server, base = serve(args.site)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for api in sorted((ROOT / "apis").iterdir()):
                if api.name.startswith("_") or not (api / "処理詳細.md").exists():
                    continue
                print_one(browser, base + quote(f"apis/{api.name}/処理詳細/"), args.out / "apis" / f"{api.name}.pdf", links)
            business = ROOT / "docs" / "business"
            for flow in sorted(business.iterdir()):
                if flow.name.startswith("_") or not (flow / "README.md").exists():
                    continue
                print_one(browser, base + quote(f"docs/business/{flow.name}/"), args.out / "業務フロー" / f"{flow.name}.pdf", links)
            build_combined(browser, base, args.site, entries, args.out / "設計書.pdf", links)
            browser.close()
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
