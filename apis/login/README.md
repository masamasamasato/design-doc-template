# ログインする

メールとパスワードが合う利用者に、セッションを作ります。成功したときは、ログイン通知メールも送ります。

```mermaid
sequenceDiagram
  actor User as ユーザー
  participant Screen as ログイン画面
  participant API as 認証API
  User->>Screen: ログインする
  Screen->>API: POST /sessions
  API->>API: authenticate()
  alt アカウントがロックされている
    API-->>Screen: 403 ACCOUNT_LOCKED
    Screen-->>User: ロックされている
  else メールとパスワードが合う
    API->>API: createSession()
    API->>API: notifyLogin()
    API-->>Screen: 200 Cookie でセッションを返す
    Screen-->>User: ログインできた
  else メールまたはパスワードが違う
    API-->>Screen: 401 INVALID_CREDENTIALS
    Screen-->>User: ログインできない
  end
```

## 入力と結果

| 名前 | 必須 | 説明 |
| --- | --- | --- |
| メール | はい | ログインする人。例: `hana@example.com` |
| パスワード | はい | 利用者が画面に入れた値。ログには残しません |

成功すると、セッションIDを HttpOnly、Secure、SameSite=Lax の Cookie で返します。本文には入れません。例: Cookie の値 `session_789`。続けて、SES でログイン通知メールを送ります。送信に失敗しても、ログインは成功のままです。

## 失敗するとき

| コード | いつ | 結果 |
| --- | --- | --- |
| INVALID_CREDENTIALS | メールが無い、またはパスワードが違う（そのメールの連続失敗が5回未満） | セッションは作らない。どちらが違うかは返さない |
| ACCOUNT_LOCKED | そのメールで連続して5回失敗した、または既にロックされている | セッションは作らない。メールが無くても同じ。返事と応答時間の差で、アカウントの有無は分からない |

## 関連リンク

- [用語](用語.md)
- [処理詳細](処理詳細.md)
- [処理のイメージ](flow.puml)
- [変更履歴](変更履歴.md)
- [ログインして商品を探す](../../docs/business/ログインして商品を探す/README.md)
- 共通の言葉は [用語集](../../用語集.md)

<details markdown>
<summary>AI向け：書き方と補足</summary>

これは深さ2です。画面とAPIのつながりだけを書きます。

メールが無いときも、ダミーのパスワード照合をして、応答時間をそろえます。ロックされていれば、パスワードの成否より先に失敗します。どちらが違うかは返しません。

</details>
