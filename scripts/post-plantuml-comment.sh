#!/usr/bin/env bash
# PR に PlantUML の図コメントを載せる。
# 可能なら gh pr comment --attach で user-attachments に上げ、
# できないときは従来どおり blob URL で更新する。
set -euo pipefail

MIN_GH="2.99.0"
GH_RELEASE="2.103.0"

ensure_gh() {
  echo "gh --version:"
  gh --version
  local ver
  ver="$(gh --version | awk 'NR==1 {print $3}')"
  local oldest
  oldest="$(printf '%s\n' "$ver" "$MIN_GH" | sort -V | head -n1)"
  if [[ "$oldest" != "$MIN_GH" ]]; then
    echo "gh ${ver} は ${MIN_GH} 未満のため、v${GH_RELEASE} を入れます"
    local archive="gh_${GH_RELEASE}_linux_amd64"
    curl -sSLfo /tmp/gh.tgz "https://github.com/cli/cli/releases/download/v${GH_RELEASE}/${archive}.tar.gz"
    tar -xzf /tmp/gh.tgz -C /tmp "${archive}/bin/gh"
    sudo install -m 755 "/tmp/${archive}/bin/gh" /usr/local/bin/gh
    hash -r || true
    echo "入れ直した gh --version:"
    gh --version
  fi
}

# プレビューの印があり、投稿者が個人トークンの持ち主か Actions のコメントだけを返す。
# 人が手で書いたコメントは、印を含んでいても消さない。
list_preview_ids() {
  local repo="$1" number="$2"
  local authors="${3:-${PREVIEW_AUTHORS:-github-actions[bot]}}"
  AUTHORS="$authors" gh api --paginate "repos/${repo}/issues/${number}/comments" \
    --jq '.[] | select((.body // "") | contains("<!-- plantuml-preview -->")) | select(.user.login as $u | ($ENV.AUTHORS | split(",") | index($u))) | .id'
}

delete_comments() {
  local repo="$1"
  shift
  local id
  for id in "$@"; do
    [[ -z "$id" ]] && continue
    gh api -X DELETE "repos/${repo}/issues/comments/${id}"
    echo "古いプレビューコメント ${id} を削除しました"
  done
}

build_body() {
  local attach="$1"
  local list="${FILE_LIST:-}"
  local input=/dev/null
  if [[ -n "$list" && -f "$list" ]]; then
    input="$list"
  fi
  COMMENT_ATTACH="$attach" python3 scripts/format-plantuml-comment.py < "$input"
}

post_with_attach() {
  local number="$1" body_file="$2"
  local args=(pr comment "$number" --body-file "$body_file")
  local svg
  if [[ -n "${FILE_LIST:-}" && -f "${FILE_LIST}" ]]; then
    while IFS= read -r svg; do
      [[ -z "$svg" ]] && continue
      if [[ ! -f "$svg" ]]; then
        echo "添付するファイルがありません: $svg" >&2
        return 1
      fi
      args+=(--attach "./${svg}#${svg}")
    done < "$FILE_LIST"
  fi
  gh "${args[@]}"
}

post_fallback() {
  local repo="$1" number="$2"
  local body existing
  body="$(build_body 0)"
  # 自動トークンが書き換えられるのは、Actions 自身のコメントだけ。
  existing="$(list_preview_ids "$repo" "$number" "github-actions[bot]" | tail -n1 || true)"
  local payload
  payload="$(jq -n --arg body "$body" '{body: $body}')"
  if [[ -n "$existing" ]]; then
    printf '%s' "$payload" | gh api -X PATCH "repos/${repo}/issues/comments/${existing}" --input - >/dev/null
    echo "添付できなかったため、コメント ${existing} を従来の形式で更新しました"
  else
    printf '%s' "$payload" | gh api "repos/${repo}/issues/${number}/comments" --input - >/dev/null
    echo "添付できなかったため、従来の形式でコメントしました"
  fi
}

resolve_prs() {
  if [[ -n "${PR_NUMBER:-}" ]]; then
    printf '%s\n' "$PR_NUMBER"
    return
  fi
  local branch repo owner head
  repo="${GITHUB_REPOSITORY:?}"
  owner="${repo%%/*}"
  branch="${GITHUB_REF_NAME:-}"
  if [[ -z "$branch" ]]; then
    echo "開いているPRを特定できません（PR_NUMBER もブランチもありません）" >&2
    return 1
  fi
  head="${owner}:${branch}"
  gh api --paginate "repos/${repo}/pulls?state=open&head=${head}" --jq '.[].number'
}

main() {
  ensure_gh
  : "${GITHUB_REPOSITORY:?}"
  : "${COMMENT_SHA:?}"
  export GH_REPO="${GH_REPO:-$GITHUB_REPOSITORY}"
  local fallback="${FALLBACK_TOKEN:-${GITHUB_TOKEN:?}}"
  local preview="${PREVIEW_TOKEN:-}"
  export GH_TOKEN="$fallback"
  PREVIEW_AUTHORS="github-actions[bot]"

  # 個人トークンが使えるかを先に確かめる。期限切れなどは、ここで警告して添付をやめる。
  if [[ -n "$preview" ]]; then
    local login
    if login="$(GH_TOKEN="$preview" gh api user --jq .login 2>/dev/null)" && [[ -n "$login" ]]; then
      PREVIEW_AUTHORS="github-actions[bot],${login}"
    else
      echo "::warning::PREVIEW_TOKEN が期限切れか無効です。図はリンクで載せます。トークンを作り直してください"
      preview=""
    fi
  else
    echo "PREVIEW_TOKEN が無いため、図はリンクで載せます"
  fi
  export PREVIEW_AUTHORS

  local numbers number
  mapfile -t numbers < <(resolve_prs)
  if ((${#numbers[@]} == 0)); then
    echo "開いているPRはないため、コメントしません"
    return 0
  fi

  local repo="$GITHUB_REPOSITORY"
  local body_file
  body_file="$(mktemp -p "${GITHUB_WORKSPACE:-.}" plantuml-comment.XXXXXX.md)"
  build_body 1 > "$body_file"

  for number in "${numbers[@]}"; do
    [[ -z "$number" ]] && continue
    local old_ids=()
    mapfile -t old_ids < <(list_preview_ids "$repo" "$number" || true)
    if [[ -n "$preview" ]] && GH_TOKEN="$preview" post_with_attach "$number" "$body_file"; then
      echo "user-attachments へ添付してコメントしました (PR #${number})"
      if ((${#old_ids[@]} > 0)); then
        GH_TOKEN="$preview" delete_comments "$repo" "${old_ids[@]}"
      fi
    else
      if [[ -n "$preview" ]]; then
        echo "::warning::個人トークンでの添付に失敗したため、リンク形式でコメントします"
      fi
      post_fallback "$repo" "$number"
    fi
  done
  rm -f "$body_file"
}

main "$@"
