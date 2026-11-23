#!/usr/bin/env bash
# ドキュメントを PDF にする。出力は pdf/（git に入れない）。
#   pdf/apis/<名前>.pdf        API ごとの設計書（処理詳細.md）
#   pdf/業務フロー/<業務>.pdf   業務フローごと
#   pdf/設計書.pdf              まとめた1本（目次としおりつき。_template の型と変更履歴は入れない）
# 使い方:
#   scripts/build-pdf.sh
# 先に要るもの: requirements.txt と requirements-pdf.txt の Python の依存、
#   Chromium（python -m playwright install chromium）、日本語フォント（Noto Sans CJK JP）。
# 図は、いま手元にある SVG を使う。.puml を変えたあとは、先に scripts/render-changed.sh --all で作り直す
#   （ワークフロー pdf.yml は、毎回これで作り直してから PDF にする）。
# 図が欠けているとき（mkdocs build --strict の警告や、読み込めない画像）は、PDF を作らずに失敗する。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

OUT="${ROOT}/pdf"
SITE="${OUT}/_site"

rm -rf "$OUT"
mkdir -p "$OUT"

./scripts/prepare-docs.sh >/dev/null
# 印刷用のサイトは、公開するサイトと同じ設定でビルドする。--quiet を付けると、strict の警告で止まらなくなるので付けない。
NO_MKDOCS_2_WARNING=1 python -m mkdocs build --strict --site-dir "$SITE"

python scripts/build-pdf.py --site "$SITE" --out "$OUT"
rm -rf "$SITE"
