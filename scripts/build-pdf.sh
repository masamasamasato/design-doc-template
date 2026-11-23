#!/usr/bin/env bash
# ドキュメントを PDF にする。出力は pdf/（git に入れない）。
#   pdf/apis/<名前>.pdf        API ごとの設計書（処理詳細.md）
#   pdf/業務フロー/<業務>.pdf   業務フローごと
#   pdf/設計書.pdf              すべてをまとめた1本（目次としおりつき）
# 使い方:
#   scripts/build-pdf.sh
# 先に要るもの: requirements.txt と requirements-pdf.txt の Python の依存、
#   Chromium（python -m playwright install chromium）、日本語フォント（Noto Sans CJK JP）。
# 図の SVG は、コミット済みのものを使う。作り直すときは、先に scripts/render-changed.sh --all を動かす。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

OUT="${ROOT}/pdf"
SITE="${OUT}/_site"

rm -rf "$OUT"
mkdir -p "$OUT"

./scripts/prepare-docs.sh >/dev/null
# 印刷用のサイトは、公開するサイトと同じ設定でビルドする。
NO_MKDOCS_2_WARNING=1 python -m mkdocs build --strict --quiet --site-dir "$SITE"

python scripts/build-pdf.py --site "$SITE" --out "$OUT"
rm -rf "$SITE"
