# 設計書テンプレート

人が読む設計書を、リポジトリに残す型です。人が書くのは、業務の流れ（深さ1）、画面とAPIのつながり（深さ2）、メソッド単位の処理（深さ3）までです。それより細かい処理は、AIがコードを読んで扱います。

## 目次

- [使い始める](#使い始める)
- [リンク](#リンク)

## 使い始める

このリポジトリをテンプレートにして、新しいリポジトリを作ります。その後の流れは次のとおりです。

![ドキュメントを書く流れ](docs/usage-flow.svg)

## リンク

- [README.md](README.md)：このページ
- [用語集.md](用語集.md)：設計書で使う言葉
- [docs/setup.md](docs/setup.md)：GitHub の設定
- [docs/guide.md](docs/guide.md)：書き方と自動化（AI向け）
- 業務フロー（`docs/business/`）：[プロフィールを公開する](docs/business/プロフィールを公開する/README.md)、[ログインして商品を探す](docs/business/ログインして商品を探す/README.md)、[カードで支払う](docs/business/カードで支払う/README.md)、[パスキーの端末をなくす](docs/business/パスキーの端末をなくす/README.md)
- [docs/infra/index.md](docs/infra/index.md)：インフラ構成の記入例
- [apis/_template/README.md](apis/_template/README.md)：新しいAPIの型
- 記入例：[ログインAPI](apis/login/README.md)
