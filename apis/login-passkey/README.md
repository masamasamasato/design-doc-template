# パスキーでログインする

登録したパスキーの署名を検証し、セッションを作ります。成功すると、セッションの Cookie を返します。失敗したときは、どこが違うかは返しません。

端末をなくしたときは、メールの確認リンクで本人確認し、新しい端末でパスキーを登録し直します。流れは [アカウントを復旧する](../recover-account/README.md) と [パスキーの端末をなくす](../../docs/business/パスキーの端末をなくす/README.md) にあります。

![パスキーでログインする](入口.svg)

ソース: [入口.puml](入口.puml)

## 入力と結果

| 名前 | 必須 | 説明 |
| --- | --- | --- |
| チャレンジへの assertion | はい | 端末が作った署名。2回目の `POST /sessions/passkey` で送ります |

流れは2段階です。`POST /sessions/passkey/options` でチャレンジを発行し、`POST /sessions/passkey` で assertion の署名と署名カウンタを確かめます。成功すると、セッションの Cookie を返します。例: `session_789`。Cookie の属性は、[ログインする](../login/README.md) と同じです。

## 失敗するとき

| コード | いつ | 結果 |
| --- | --- | --- |
| INVALID_CREDENTIALS | 署名を検証できない、署名カウンタが古い、チャレンジが使えない、またはパスキーが無い | セッションは作らない。どこが違うかは返さない |

## 関連リンク

- [用語](用語.md)
- [処理詳細](処理詳細.md)
- [入口の図](入口.puml)
- [処理のイメージ](flow.puml)
- [変更履歴](変更履歴.md)
- [パスキーを登録する](../register-passkey/README.md)
- [アカウントを復旧する](../recover-account/README.md)
- [ログインする](../login/README.md)
- [パスキーの端末をなくす](../../docs/business/パスキーの端末をなくす/README.md)
- [カードで支払う](../../docs/business/カードで支払う/README.md)
- 共通の言葉は [用語集](../../用語集.md)

<details markdown>
<summary>AI向け：書き方と補足</summary>

これは深さ2です。画面とAPIのつながりだけを書きます。

セッションIDは、HttpOnly、Secure、SameSite=Lax の Cookie で返し、本文には入れません。失敗の種類を分けると、どこが違うかが分かるため、同じ `INVALID_CREDENTIALS` にします。

</details>
