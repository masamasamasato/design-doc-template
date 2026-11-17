#!/usr/bin/env bash
# 公開サイト（GitHub Pages の MkDocs サイト）の URL を出す。
# 1. リポジトリ変数 DOCS_SITE_URL  2. Pages の設定  3. ふつうの GitHub Pages の URL の順に使う。
set -euo pipefail

repo="${GITHUB_REPOSITORY:?}"
url="${DOCS_SITE_URL:-}"
if [[ -z "$url" ]]; then
  url="$(gh api "repos/${repo}/pages" --jq .html_url 2>/dev/null || true)"
fi
if [[ -z "$url" ]]; then
  owner="$(printf '%s' "${repo%%/*}" | tr '[:upper:]' '[:lower:]')"
  url="https://${owner}.github.io/${repo#*/}/"
  echo "::notice::Pages の設定を読めないため、${url} をリンク先にします" >&2
fi
printf '%s\n' "$url"
