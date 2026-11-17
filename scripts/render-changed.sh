#!/usr/bin/env bash
# 変わった .puml を SVG にし、消えた .puml の SVG を消す。
# 使い方:
#   scripts/render-changed.sh BEFORE SHA
#   scripts/render-changed.sh --all
# 標準出力には、残っている SVG のパスだけを出す。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

changed=()
deleted=()

if [[ "${1:-}" == "--all" ]]; then
  while IFS= read -r path; do
    [[ -z "$path" ]] && continue
    changed+=("$path")
  done < <(git -c core.quotepath=false ls-files '*.puml' '*.plantuml')
else
  before="${1:-}"
  sha="${2:-HEAD}"
  while IFS= read -r path; do
    [[ -z "$path" ]] && continue
    changed+=("$path")
  done < <("$ROOT/scripts/list-changed-puml.sh" "$before" "$sha" ACMR)
  while IFS= read -r path; do
    [[ -z "$path" ]] && continue
    deleted+=("$path")
  done < <("$ROOT/scripts/list-changed-puml.sh" "$before" "$sha" D)
fi

if ((${#deleted[@]} > 0)); then
  for puml in "${deleted[@]}"; do
    svg="${puml%.*}.svg"
    if [[ -f "$svg" ]]; then
      rm -f "$svg"
      echo "削除: $svg" >&2
    fi
  done
fi

if ((${#changed[@]} > 0)); then
  "$ROOT/scripts/render-puml.sh" "${changed[@]}"
fi

if ((${#changed[@]} > 0)); then
  for puml in "${changed[@]}"; do
    svg="${puml%.*}.svg"
    if [[ -f "$svg" ]]; then
      printf '%s\n' "$svg"
    fi
  done
fi
