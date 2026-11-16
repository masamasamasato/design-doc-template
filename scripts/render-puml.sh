#!/usr/bin/env bash
# .puml を、同じディレクトリの .svg にする。
# 使い方: scripts/render-puml.sh file.puml [file2.puml ...]
# 外部の PlantUML / Kroki サーバーには送らない。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
JAR="${PLANTUML_JAR:-$ROOT/tools/plantuml.jar}"

if [[ ! -f "$JAR" ]]; then
  "$ROOT/scripts/install-plantuml.sh"
fi

if ! command -v java >/dev/null 2>&1; then
  echo "Java がありません。JRE を入れてから再実行してください。" >&2
  exit 1
fi

if ! command -v dot >/dev/null 2>&1; then
  echo "Graphviz (dot) がありません。スイムレーンの変換に必要です。" >&2
  exit 1
fi

if [[ $# -eq 0 ]]; then
  echo "使い方: scripts/render-puml.sh file.puml [file2.puml ...]" >&2
  exit 1
fi

for file in "$@"; do
  if [[ ! -f "$file" ]]; then
    echo "ファイルがありません: $file" >&2
    exit 1
  fi
done

java -Djava.awt.headless=true \
  -jar "$JAR" \
  -charset UTF-8 \
  -tsvg \
  -failfast2 \
  -nometadata \
  "$@" >&2
