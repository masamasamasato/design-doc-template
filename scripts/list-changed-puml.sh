#!/usr/bin/env bash
# 2つのコミットの間で変わった .puml を出す。
# 使い方: scripts/list-changed-puml.sh BEFORE SHA [ACMR|D]
set -euo pipefail

before="${1:-}"
sha="${2:-HEAD}"
filter="${3:-ACMR}"

# 日本語などのパスを、引用符や八進エスケープ付きで出さない。
GIT_PATHS=(git -c core.quotepath=false)

paths_from_diff() {
  local base="$1"
  "${GIT_PATHS[@]}" diff --name-only --diff-filter="$filter" "$base" "$sha" -- '*.puml' '*.plantuml'
}

paths_from_commit() {
  "${GIT_PATHS[@]}" diff-tree --root --no-commit-id --name-only --diff-filter="$filter" -r "$sha" \
    | awk '/\.puml$|\.plantuml$/'
}

if [[ -n "$before" && ! "$before" =~ ^0+$ ]]; then
  paths_from_diff "$before"
  exit 0
fi

if git rev-parse --verify --quiet origin/main >/dev/null; then
  if [[ "$(git rev-parse origin/main)" == "$(git rev-parse "$sha")" ]]; then
    paths_from_commit
    exit 0
  fi
  paths_from_diff "origin/main"
  exit 0
fi

paths_from_commit
