# API

画面や他のサービスが呼ぶ入口の設計書です。各APIの入口から、設計書へ進めます。

| 名前 | 役割 |
| --- | --- |
| [新しいAPIの型](_template/README.md) | 新しいAPIを作るときにコピーする型 |
| [プロフィール公開API](publish-profile/README.md) | 本人確認が済んでいる持ち主のプロフィールを公開中にする |
| [ログインAPI](login/README.md) | メールアドレスとパスワードが合えば、セッションを作ってログイン状態にする |
| [ログアウトAPI](logout/README.md) | 今のセッションを無効にし、ログインしていない状態に戻す |
| [商品詳細取得API](get-product/README.md) | 公開中の商品の詳細（名前、価格、在庫）を返す |
| [商品一覧取得API](list-products/README.md) | 公開中の商品の一覧を、ページに分けて返す |
| [商品検索API](search-products/README.md) | 商品名に検索語を含む公開中の商品を、ページに分けて返す |
| [パスキー登録API](register-passkey/README.md) | 今の端末にパスキーを登録し、公開鍵だけを保存する |
| [パスキーログインAPI](login-passkey/README.md) | 登録した端末のパスキーの署名が合えば、ログイン状態にする |
| [アカウント復旧API](recover-account/README.md) | メールの確認リンクで本人確認し、今までのセッションとパスキーを無効にする |
| [カード登録API](register-card/README.md) | 支払い用カードを、決済サービスの預かり番号と表示用の情報だけで登録する |
| [支払いAPI](create-payment/README.md) | 登録したカードで注文の支払いを始める。同じ注文を2回は請求しない |
| [注文状態取得API](get-order/README.md) | 自分の注文の状態と金額を返す |
| [決済通知受信API](payment-webhook/README.md) | 決済サービスからの通知を検証し、注文を支払い済みまたは失敗にする |
