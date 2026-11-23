#!/usr/bin/env python3
"""MkDocs でビルドしたサイトを、ヘッドレスの Chromium（Playwright）で PDF に印刷する。

- API ごとに1本（apis/<名前>/処理詳細.md）、業務フローごとに1本（docs/business/<業務>/README.md）。
- mkdocs.yml の nav の順に、すべてのページを1本にまとめた PDF。先頭に目次を置き、目次と本文中のリンクから
  各ページへ飛べる。PDF のしおり（アウトライン）も付ける。
- 見た目は公開サイトと同じ（同じ CSS、ライトモード）。ナビ・検索欄・ヘッダー・フッターは印刷しない。
- 各ページの下にページ番号を入れる。

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
import threading
from pathlib import Path
from urllib.parse import quote

import yaml
from playwright.sync_api import Browser, Page, sync_playwright
from pypdf import PdfWriter
from pypdf.generic import NameObject, TextStringObject

ROOT = Path(__file__).resolve().parents[1]
# Chromium の PDF を読むときの、害の無い警告を出さない
logging.getLogger("pypdf").setLevel(logging.ERROR)

# 印刷のときだけ足す CSS。サイトの CSS は変えない。
PRINT_CSS = """
@page { size: A4; }
html, body { background: #fff !important; }
.md-header, .md-tabs, .md-sidebar, .md-footer, .md-search, .md-top, .md-dialog,
.md-content__button, .md-source, .md-banner, .headerlink, .md-clipboard, .md-code__nav, .md-code__button,
button[title] { display: none !important; }
.md-main__inner { margin: 0 !important; max-width: none !important; }
.md-content { max-width: none !important; margin: 0 !important; }
.md-content__inner { margin: 0 !important; padding: 0 !important; }
.md-content__inner::before { display: none !important; }
.md-typeset { font-size: 10.5pt; }
.md-typeset img, .md-typeset svg { max-width: 100% !important; height: auto; }
.md-typeset figure, .md-typeset p:has(> img) { break-inside: avoid; }
.md-typeset table:not([class]) { display: table; width: 100%; font-size: 9pt; }
.md-typeset table:not([class]) tr { break-inside: avoid; }
.md-typeset .md-typeset__scrollwrap, .md-typeset .md-typeset__table { overflow: visible !important; display: block; }
.md-typeset h1, .md-typeset h2, .md-typeset h3 { break-after: avoid; }
.md-typeset pre { white-space: pre-wrap; word-break: break-all; }
.pdf-page { break-before: page; }
.pdf-toc ul { list-style: none; }
.pdf-toc a { color: inherit; text-decoration: none; }
.pdf-toc .pdf-toc-group { font-weight: 700; margin-top: 0.6em; }
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
    margin={"top": "15mm", "bottom": "18mm", "left": "14mm", "right": "14mm"},
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


def serve(site: Path) -> tuple[http.server.ThreadingHTTPServer, str]:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(site))

    class Quiet(handler.func):  # type: ignore[misc]
        def log_message(self, *args):  # noqa: D401
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(site)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/"


def open_page(browser: Browser, url: str, links: dict | None = None) -> Page:
    page = browser.new_page(color_scheme="light")
    page.goto(url, wait_until="networkidle")
    if links is not None:
        page.evaluate(f"([pages, base]) => ({OUTSIDE_LINK_JS})(document, pages, base)", [links["pages"], links["base"]])
    page.add_style_tag(content=PRINT_CSS)
    # 閉じた details も中身を印刷する
    page.evaluate("document.querySelectorAll('details').forEach(d => d.open = true)")
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


def print_one(browser: Browser, url: str, out: Path, links: dict) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    page = open_page(browser, url, links)
    headings = [text for _, text in page.evaluate(HEADINGS_JS)]
    page.pdf(path=str(out), **PDF_OPTIONS)
    page.close()
    set_outline_titles(out, headings)
    print(f"作りました: {out.relative_to(ROOT)}")


# まとめた PDF のために、1ページの本文を取り出し、id とリンクを書き換える JS。
EXTRACT_JS = """
([prefix, pageIds, pages, base]) => {
  const article = document.querySelector('article.md-content__inner');
  const clone = article.cloneNode(true);
  // 見出しの id は日本語だと長く、PDF の名前つきの行き先の上限（127バイト）を超えるので、短いハッシュにする。
  const short = (text) => {
    let h = 0x811c9dc5;
    for (const c of new TextEncoder().encode(text)) { h ^= c; h = Math.imul(h, 0x01000193) >>> 0; }
    return h.toString(36);
  };
  clone.querySelectorAll('.headerlink, .md-content__button').forEach(e => e.remove());
  clone.querySelectorAll('details').forEach(d => d.open = true);
  clone.querySelectorAll('[id]').forEach(e => { e.id = prefix + '-' + short(e.id); });
  clone.querySelectorAll('a[href]').forEach(a => {
    const url = new URL(a.getAttribute('href'), location.href);
    if (url.origin !== location.origin) return;
    const target = pageIds[decodeURIComponent(url.pathname)];
    if (target === undefined) { return; }
    const hash = decodeURIComponent(url.hash.slice(1));
    a.setAttribute('href', '#' + target + (hash ? '-' + short(hash) : ''));
  });
  clone.querySelectorAll('img[src], source[srcset]').forEach(e => {
    if (e.hasAttribute('src')) e.setAttribute('src', new URL(e.getAttribute('src'), location.href).pathname);
  });
  (OUTSIDE)(clone, pages, base);
  const h1 = clone.querySelector('h1');
  return { html: clone.innerHTML, title: h1 ? h1.textContent.trim() : '' };
}
"""


def build_combined(browser: Browser, base: str, site: Path, entries, out: Path, links: dict) -> None:
    pages = [e for e in entries if e["src"]]
    page_ids = {}
    for index, entry in enumerate(pages):
        entry["id"] = f"p{index}"
        page_ids["/" + quote(entry["url"], safe="/")] = entry["id"]
        page_ids["/" + entry["url"]] = entry["id"]

    sections = []
    for entry in pages:
        page = open_page(browser, base + quote(entry["url"], safe="/"))
        data = page.evaluate(
            EXTRACT_JS.replace("(OUTSIDE)", f"({OUTSIDE_LINK_JS})"),
            [entry["id"], page_ids, links["pages"], links["base"]],
        )
        page.close()
        entry["title"] = data["title"] or entry["nav_title"]
        sections.append((entry, data["html"]))

    # 同じ見出し（「変更履歴」など）が並ぶと、しおりで見分けられないため、親の名前を添える
    counts: dict[str, int] = {}
    for entry, _ in sections:
        counts[entry["title"]] = counts.get(entry["title"], 0) + 1

    body = []
    toc = ['<nav class="pdf-toc"><h1 id="pdf-toc">目次</h1><ul>']
    for entry in entries:
        depth = len(entry["trail"])
        indent = f' style="margin-left:{depth * 1.2}em"'
        if not entry["src"]:
            toc.append(f'<li class="pdf-toc-group"{indent}>{html.escape(entry["trail"][-1])}</li>')
            continue
        title = entry["title"]
        if counts[title] > 1:
            # 同じ名前のページは、nav の場所を添えて見分ける（本文の見出しは変えない）
            where = [part for part in (*entry["trail"], entry["nav_title"]) if part and part != title]
            title = f"{title}（{'・'.join(where)}）"
        entry["display"] = title
        toc.append(f'<li{indent}><a href="#{entry["id"]}">{html.escape(title)}</a></li>')
    toc.append("</ul></nav>")

    for entry, content in sections:
        body.append(f'<section class="pdf-page" id="{entry["id"]}">{content}</section>')

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
    page.evaluate("document.fonts.ready")
    headings = page.evaluate(HEADINGS_JS)
    page.pdf(path=str(out), **PDF_OPTIONS)
    page.close()
    combined.unlink()
    # 各ページの h1 のしおりは、目次と同じ名前（同じ名前のページは nav の場所つき）にする
    labels = iter(["目次"] + [entry["display"] for entry, _ in sections])
    titles = [next(labels) if is_page_top else text for is_page_top, text in headings]
    set_outline_titles(out, titles)
    print(f"作りました: {out.relative_to(ROOT)}（{len(pages)}ページ分）")


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
