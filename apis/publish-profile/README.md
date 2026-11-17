# プロフィールを公開する

本人確認が済んでいる利用者だけ、自分のプロフィールを公開中にします。

```mermaid
sequenceDiagram
  actor User as ユーザー
  participant Screen as プロフィール画面
  participant API as プロフィールAPI
  User->>Screen: 公開する
  Screen->>API: POST /profiles/{id}/publish
  API->>API: checkOwner()
  alt 本人確認が済んでいる
    API->>API: publish()
    API-->>Screen: 200 公開中
    Screen-->>User: 公開できた
  else 本人確認が済んでいない
    API-->>Screen: 403 NOT_VERIFIED
    Screen-->>User: 先に本人確認が必要
  end
```

## 入力と結果

| 名前 | 必須 | 説明 |
| --- | --- | --- |
| 利用者ID | はい | 公開する人。例: `user_123` |
| プロフィールID | はい | 公開するプロフィール。例: `profile_456` |

成功すると、そのプロフィールは公開中になります。`publishedAt` に日時が入ります。例: `2026-11-16T18:00:00+09:00`。

## 失敗するとき

| コード | いつ | 結果 |
| --- | --- | --- |
| NOT_VERIFIED | 本人確認が済んでいない | 公開中にしない |
| NOT_FOUND | プロフィールが無い | 何も変えない |
| FORBIDDEN | 他人のプロフィールを公開しようとした | 何も変えない |

## 関連リンク

- [用語](用語.md)
- [処理詳細](処理詳細.md)
- [処理のイメージ](flow.puml)
- [変更履歴](変更履歴.md)
- [プロフィールを公開する（業務）](../../docs/business/プロフィールを公開する/README.md)
- 共通の言葉は [用語集](../../用語集.md)

<details markdown>
<summary>AI向け：書き方と補足</summary>

これは深さ2です。画面とAPIのつながりだけを書きます。

利用者が画面で「公開する」を押すと、プロフィールAPIが本人確認を見ます。確認済みなら公開中にします。まだなら、状態は変えません。

</details>
