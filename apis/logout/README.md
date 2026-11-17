# ログアウトする

今のセッションを無効にし、ログインしていない状態に戻します。

```mermaid
sequenceDiagram
  actor User as ユーザー
  participant Screen as 設定画面
  participant API as 認証API
  User->>Screen: ログアウトする
  Screen->>API: DELETE /sessions/current
  API->>API: invalidateSession()
  API-->>Screen: 200 Cookie を消した
  Screen-->>User: ログアウトできた
```

## 入力と結果

| 名前 | 必須 | 説明 |
| --- | --- | --- |
| セッションID | いいえ | 今のセッション。例: `session_789`。無くても成功する |

成功すると、そのセッションは無効になり、セッションの Cookie を消します。既に無効なときも、同じ結果です。画面は、ログインしていない状態に戻してよいです。

## 失敗するとき

このAPIは失敗を返しません。セッションが無いときも、既に無効なときも、成功として扱います。

## 関連リンク

- [用語](用語.md)
- [処理詳細](処理詳細.md)
- [処理のイメージ](flow.puml)
- [変更履歴](変更履歴.md)
- 共通の言葉は [用語集](../../用語集.md)

<details markdown>
<summary>AI向け：書き方と補足</summary>

これは深さ2です。画面とAPIのつながりだけを書きます。

</details>
