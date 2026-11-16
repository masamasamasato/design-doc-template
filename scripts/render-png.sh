#!/usr/bin/env bash
# レビュー用の PNG を、元の相対パスを保って書き出す。
# 使い方: scripts/render-png.sh 出力ディレクトリ file.puml [file2.puml ...]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
JAR="${PLANTUML_JAR:-$ROOT/tools/plantuml.jar}"

if [[ $# -lt 2 ]]; then
  echo "使い方: scripts/render-png.sh 出力ディレクトリ file.puml ..." >&2
  exit 1
fi

if [[ ! -f "$JAR" ]]; then
  "$ROOT/scripts/install-plantuml.sh"
fi

out_dir="$1"
shift

for file in "$@"; do
  if [[ ! -f "$file" ]]; then
    echo "ファイルがありません: $file" >&2
    exit 1
  fi
  dest="${out_dir}/$(dirname "$file")"
  mkdir -p "$dest"
  java -Djava.awt.headless=true \
    -jar "$JAR" \
    -charset UTF-8 \
    -tpng \
    -failfast2 \
    -nometadata \
    -o "$dest" \
    "$file" >&2
done
