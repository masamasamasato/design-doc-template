#!/usr/bin/env python3
"""MkDocs でビルドしたサイトを、ヘッドレスの Chromium（Playwright）で PDF に印刷する。

- API ごとに1本（apis/<名前>/処理詳細.md）、業務フローごとに1本（docs/business/<業務>/README.md）。
- mkdocs.yml の nav の順に、ページを1本にまとめた PDF。`_template` の型と各変更履歴は入れない。
  先頭に目次を置き、目次と本文中のリンクから各ページへ飛べる。PDF のしおり（アウトライン）も付ける。
- 見た目は公開サイトと同じ（同じ CSS、ライトモード）。ヘッダー、ナビゲーション、検索、フッター、
  コピーボタンは印刷しない。
- 各ページの下にページ番号を入れる。
- 図は、文字が読める大きさで載せる。幅に収めると文字が小さすぎる図は、全体図のあとに、
  拡大して分けたページを付ける。図の前のページが大きく空くときは、図を少し縮めるか、
  文字の無い行で図を分けて、前のページへ詰める。
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
# Chromium の PDF を読むときの、害の無い警告を出さない
logging.getLogger("pypdf").setLevel(logging.ERROR)

# 用紙と余白（mm）。図の大きさの計算にも使う。
PAGE_W_MM, PAGE_H_MM = 210, 297
MARGIN_MM = {"top": 15, "bottom": 18, "left": 14, "right": 14}
PX_PER_MM = 96 / 25.4
PT_PER_PX = 0.75
CONTENT_W_PX = int((PAGE_W_MM - MARGIN_MM["left"] - MARGIN_MM["right"]) * PX_PER_MM)
CONTENT_H_PX = int((PAGE_H_MM - MARGIN_MM["top"] - MARGIN_MM["bottom"]) * PX_PER_MM)
# 図の縮め方の下限。PlantUML の文字（11〜13px）が、およそ 6pt より小さくならないようにする。
READABLE_SCALE = 0.55
# 拡大して分けるときの倍率。11px の文字が 6pt ほどになる。
TILE_SCALE = 0.75

# 印刷のときだけ足す CSS。サイトの CSS は変えない。
# サイトの CSS の @page の余白（25mm）は、下の MARGIN_MM に置きかえる。
PRINT_CSS = f"""
@page {{ size: A4; margin: {MARGIN_MM["top"]}mm {MARGIN_MM["right"]}mm {MARGIN_MM["bottom"]}mm {MARGIN_MM["left"]}mm; }}
html, body {{ background: #fff !important; }}
.md-header, .md-tabs, .md-sidebar, .md-footer, .md-search, .md-top, .md-dialog,
.md-content__button, .md-source, .md-banner, .headerlink, .md-clipboard, .md-code__nav, .md-code__button,
button[title] {{ display: none !important; }}
.md-main__inner {{ margin: 0 !important; max-width: none !important; }}
.md-content {{ max-width: none !important; margin: 0 !important; }}
.md-content__inner {{ margin: 0 !important; padding: 0 !important; }}
.md-content__inner::before {{ display: none !important; }}
.md-typeset {{ font-size: 10.5pt; }}
.md-typeset img {{ max-width: 100%; height: auto; }}
.md-typeset .pdf-figure img, .md-typeset .pdf-tile img {{ max-width: none !important; }}
/* 図と、そのすぐ後の「ソース:」は同じページに置く */
.pdf-figure {{ break-inside: avoid; }}
.pdf-figure.pdf-split {{ break-inside: auto; }}
.pdf-figure .pdf-rest {{ break-inside: avoid; }}
.pdf-figure > p {{ margin: 0.6em 0; }}
.pdf-clip {{ position: relative; overflow: hidden; }}
.pdf-clip > img {{ position: absolute; left: 0; top: 0; }}
.pdf-note, .pdf-tile-caption {{ font-size: 9pt; color: #555; }}
.pdf-tile {{ break-before: page; break-inside: avoid; }}
.md-typeset table:not([class]) {{ display: table; width: 100%; font-size: 9pt; }}
.md-typeset table:not([class]) tr {{ break-inside: avoid; }}
.md-typeset table:not([class]) th, .md-typeset table:not([class]) td {{ padding: 0.6em 0.8em; }}
/* 表の中のコード（application/json など）は、途中で折り返さない */
.md-typeset table:not([class]) code {{ white-space: nowrap; word-break: keep-all; overflow-wrap: normal; }}
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

# 図を、文字が読める大きさにする JS。
# - 画像だけの段落を div.pdf-figure で包み、すぐ後の「ソース:」の段落も中に入れる（同じページに置くため）。
# - 図は、幅とページの高さに収まる大きさにする。それでは文字が小さすぎるときは、全体図を小さく載せ、
#   次のページから TILE 倍に拡大して分けたもの（端を少し重ねる）を付ける。文字も線も無い部分は飛ばす。
# - SVG の文字の上下の位置を data-texts に残す。あとで図を分けるとき、文字の無い行で切るのに使う。
FIGURES_JS = """
async ([W, H, READABLE, TILE]) => {
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
    const shapes = [...node.querySelectorAll('rect, path, line, polygon, polyline, ellipse, circle, image')].map(box);
    node.remove();
    return { texts, shapes };
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
    if (scale < READABLE && boxes) {
      // 全体図は小さく載せ、拡大して分けたページを後ろに付ける
      scale = Math.min(1, W / nw, (H * 0.45) / nh);
      fig.dataset.tiled = '1';
      const tw = Math.floor(W / TILE), th = Math.floor((H - 70) / TILE), overlap = 40;
      // 枚数は端を overlap だけ重ねたときの最小にし、そのうえで間隔をそろえる（細い切れ端を作らない）
      const starts = (length, size) => {
        if (length <= size) return [0];
        const count = Math.ceil((length - overlap) / (size - overlap));
        const step = (length - size) / (count - 1);
        return [...Array(count).keys()].map(i => Math.round(i * step));
      };
      const xs = starts(nw, tw), ys = starts(nh, th);
      const small = boxes.shapes.filter(b => b[2] - b[0] < tw && b[3] - b[1] < th);
      const used = (x, y) => boxes.texts.concat(small)
        .some(b => b[0] < x + tw && b[2] > x && b[1] < y + th && b[3] > y);
      const tiles = [];
      ys.forEach((y, r) => xs.forEach((x, c) => { if (used(x, y)) tiles.push([x, y, r, c]); }));
      const alt = img.getAttribute('alt') || '図';
      const note = document.createElement('p');
      note.className = 'pdf-note';
      note.textContent = `文字が小さいため、次のページから図を拡大して分けて載せます（全${tiles.length}ページ。端は少し重ねています）。`;
      p.after(note);
      let anchor = fig;
      tiles.forEach(([x, y, r, c], i) => {
        const tile = document.createElement('div');
        tile.className = 'pdf-tile';
        const caption = document.createElement('p');
        caption.className = 'pdf-tile-caption';
        caption.textContent = `${alt}（拡大 ${i + 1}/${tiles.length}：上から${r + 1}段目、左から${c + 1}列目。全体は${ys.length}段×${xs.length}列）`;
        const clip = document.createElement('div');
        clip.className = 'pdf-clip';
        clip.style.width = Math.ceil(Math.min(tw, nw - x) * TILE) + 'px';
        clip.style.height = Math.ceil(Math.min(th, nh - y) * TILE) + 'px';
        const part = document.createElement('img');
        part.src = img.src;
        part.alt = '';
        part.style.width = nw * TILE + 'px';
        part.style.height = nh * TILE + 'px';
        part.style.left = -x * TILE + 'px';
        part.style.top = -y * TILE + 'px';
        clip.appendChild(part);
        tile.append(caption, clip);
        anchor.after(tile);
        anchor = tile;
      });
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
  document.querySelectorAll('.pdf-figure > p, .pdf-figure .pdf-clip, .pdf-tile').forEach((el, i) => wrap(el, 'b' + i));
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
    if links is not None:
        page.evaluate(f"([pages, base]) => ({OUTSIDE_LINK_JS})(document, pages, base)", [links["pages"], links["base"]])
    if short_ids:
        page.evaluate(SHORT_IDS_JS)
    page.add_style_tag(content=PRINT_CSS)
    # 閉じた details も中身を印刷する
    page.evaluate("document.querySelectorAll('details').forEach(d => d.open = true)")
    page.evaluate(FIGURES_JS, [CONTENT_W_PX, CONTENT_H_PX, READABLE_SCALE, TILE_SCALE])
    page.evaluate("document.fonts.ready")
    return page


HEADINGS_JS = """
() => [...document.querySelectorAll('article h1, article h2, article h3, article h4, article h5, article h6')]
  .filter(h => h.offsetParent !== null)
  .map(h => [h.matches('.pdf-page > h1:first-of-type, #pdf-toc'), (c => { c.querySelectorAll('.headerlink').forEach(e => e.remove()); return c.textContent; })(h.cloneNode(true)).replace(/\\s+/g, ' ').trim()])
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


def read_layout(path: Path) -> tuple[list[float], dict[str, list[tuple[int, list[float]]]], float]:
    """印刷した PDF から、ページごとの本文のいちばん下の位置と、目印（図と各ページの先頭）の位置を読む。"""
    reader = PdfReader(str(path))
    bottom_margin = MARGIN_MM["bottom"] * 72 / 25.4
    bottoms: list[float] = []
    marks: dict[str, list[tuple[int, list[float]]]] = {}
    height = float(reader.pages[0].mediabox.height)
    for number, page in enumerate(reader.pages):
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
    return bottoms, marks, height


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
            bottoms, marks, height = read_layout(probe)
            content = height - top_margin - bottom_margin
            figures = page.evaluate(
                "() => [...document.querySelectorAll('.pdf-figure')].map(f => "
                "[+f.dataset.section, !!f.dataset.tried, !!f.dataset.tiled, +f.dataset.scale, +f.dataset.h])"
            )
            done_sections = set()
            changed = False
            for index, (section, tried, tiled, scale, natural_h) in enumerate(figures):
                where = marks.get(f"f{index}")
                start = marks.get(f"s{section}")
                if tried or section in done_sections or not where or not start:
                    continue
                number, (low, high) = where[0]
                if number == 0 or number <= start[0][0]:
                    continue
                blank = bottoms[number - 1] - bottom_margin
                above = (height - top_margin) - high
                if blank < content * 0.2 or above > 90:
                    continue
                figure_h = high - low
                image_h = natural_h * scale * PT_PER_PX
                room = blank - above - 10
                new_scale = scale * (room - (figure_h - image_h)) / image_h
                if new_scale >= max(READABLE_SCALE, scale * 0.85):
                    page.evaluate(FIX_JS, [index, "shrink", new_scale])
                elif not tiled and page.evaluate(FIX_JS, [index, "split", room / PT_PER_PX - 30]):
                    pass
                else:
                    page.evaluate(FIX_JS, [index, "none", 0])
                    continue
                done_sections.add(section)
                changed = True
            if not changed:
                return
        print(f"注意: 図の位置の調整が終わりませんでした: {label}")


def print_pdf(page: Page, out: Path, label: str) -> list[list]:
    """図の位置を整えてから印刷し、しおりの名前を直すための見出しを返す。"""
    fit_figures(page, label)
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
    """まとめた PDF に入れるページか。`_template` の型と変更履歴は入れない。"""
    path = Path(src)
    return not any(part.startswith("_") for part in path.parts) and path.name != "変更履歴.md"


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

    # 同じ見出しが並ぶと、しおりで見分けられないため、nav の場所を添える
    counts: dict[str, int] = {}
    for entry, _ in sections:
        counts[entry["title"]] = counts.get(entry["title"], 0) + 1
    for entry, _ in sections:
        title = entry["title"]
        if counts[title] > 1:
            where = [part for part in (*entry["trail"], entry["nav_title"]) if part and part != title]
            title = f"{title}（{'・'.join(where)}）"
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
