#!/usr/bin/env python3
"""変換した SVG を、PRコメント用の Markdown にする。"""

from __future__ import annotations

import os
import sys


def main() -> None:
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    repository = os.environ["GITHUB_REPOSITORY"]
    sha = os.environ["COMMENT_SHA"]
    paths = [line.strip() for line in sys.stdin if line.strip()]
    lines = [
        "<!-- plantuml-preview -->",
        "## 変換した図",
        "",
        "PlantUML は GitHub Actions の中だけで SVG にしました。図の中身は外部のサーバーへ送っていません。",
        "",
        "コメントに画像が出ないときは、リンクを開いてください。GitHub は SVG をコメントの中で表示しないことがあります。",
        "",
    ]
    if not paths:
        lines.append("対象の図はありません。")
        lines.append("")
    for path in paths:
        url = f"{server}/{repository}/blob/{sha}/{path}"
        lines.extend(
            [
                f"### `{path}`",
                "",
                f"[SVGを開く]({url})",
                "",
                f'<img alt="{path}" src="{url}?sanitize=true" />',
                "",
            ]
        )
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
