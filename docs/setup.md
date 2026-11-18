# GitHub の設定

テンプレートからリポジトリを作ったあと、次を設定します。図の変換、変更履歴、サイト公開に必要です。

1. Settings → Actions → General → Workflow permissions を **Read and write permissions** にする。SVGと変更履歴のコミットに必要です。
2. Settings → Pages → Build and deployment → Source を **GitHub Actions** にする。変更したドキュメントの一覧は、この公開サイトへリンクします。独自ドメインなどで URL が違うときは、Settings → Secrets and variables → Actions → Variables に `DOCS_SITE_URL` を登録します。
3. Settings → General → **Template repository** にチェックを入れる。
4. Settings → General → Pull Requests → Allow squash merging の既定メッセージを **Pull request title and description** にする。全コミット文が本文に入ると、bot のコミット文が混ざり、変更履歴の追記など、main の自動処理が止まることがあります。
5. 一人で使うリポジトリだけ、Settings → Secrets and variables → Actions に `PREVIEW_TOKEN` を登録する。中身は、このリポジトリだけを選んだ fine-grained の個人トークンで、権限は Contents と Pull requests の Read and write です。期限を付けます。
   - **共同編集者がいるリポジトリでは設定しません**。書き込みできる人は、ワークフローを書き換えてこのトークンを外へ送れます。送られると、期限まで持ち主の権限で書き込まれます。
   - 図のコメントは、bot ではなくトークンの持ち主の名前で付きます。
   - 無い・期限切れのときは、警告を出して、図をリンクで載せます。

ブランチ保護で bot の push が拒否されるときは、`github-actions[bot]` の更新を許可します。

PR本文の形を必須にするときは、ブランチ保護の必須チェックに `body` を入れます。

<details markdown>
<summary>PR本文のチェックの詳細</summary>

- ワークフローは「PRタイトルと本文を確認する」（`.github/workflows/pr-title.yml`）の `body` ジョブです。PRを開いた・本文を変えた・push した・開き直したときに動きます。
- 中身は `scripts/check-pr-body.py` です。本文の形は `.github/pull_request_template.md` に合わせます。
- 失敗したときは、ジョブのログに、直し方の例が日本語で出ます。
- bot が作ったPRは確かめません。

</details>
