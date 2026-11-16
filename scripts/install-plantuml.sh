#!/usr/bin/env bash
# PlantUML の jar を tools/plantuml.jar に置く。
# 落とすのは変換ツールだけです。図のテキストは送りません。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="1.2026.10"
JAR_NAME="plantuml-mit-${VERSION}.jar"
URL="https://github.com/plantuml/plantuml/releases/download/v${VERSION}/${JAR_NAME}"
DEST="${PLANTUML_JAR:-$ROOT/tools/plantuml.jar}"
SHA256="30a66b81a16127fd3ec560992f31964fe9ae3f1233c614ef4558a4558a21489e"

mkdir -p "$(dirname "$DEST")"

if [[ -f "$DEST" ]]; then
  current="$(sha256sum "$DEST" | awk '{print $1}')"
  if [[ "$current" == "$SHA256" ]]; then
    echo "plantuml.jar は既にあります: $DEST"
    exit 0
  fi
  echo "plantuml.jar の中身が想定と違うため、取り直します。" >&2
fi

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
curl -fsSL "$URL" -o "$tmp"
echo "${SHA256}  ${tmp}" | sha256sum -c -
cp "$tmp" "$DEST"
chmod 644 "$DEST"
echo "保存しました: $DEST"
echo "絶対パス: $(cd "$(dirname "$DEST")" && pwd)/$(basename "$DEST")"
