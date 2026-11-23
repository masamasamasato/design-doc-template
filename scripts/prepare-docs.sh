#!/usr/bin/env bash
# MkDocs は、mkdocs.yml のあるフォルダ自体を原稿にできない。
# 公開したいファイルへのリンクを mkdocs/docs に作り直す。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${ROOT}/mkdocs/docs"
mkdir -p "$DEST"

link() {
  local name="$1"
  local target="$2"
  ln -sfn "$target" "${DEST}/${name}"
}

link "README.md" "../../README.md"
link "用語集.md" "../../用語集.md"
link "docs" "../../docs"
link "apis" "../../apis"
link "stylesheets" "../../stylesheets"

echo "原稿へのリンクを作りました: ${DEST}"
