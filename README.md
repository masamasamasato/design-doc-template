# 設計書テンプレート

人が読む設計書を、リポジトリに残す型です。人が書くのは、業務の流れ（深さ1）、画面とAPIのつながり（深さ2）、メソッド単位の処理（深さ3）までです。それより細かい処理は、AIがコードを読んで扱います。

## 目次

- [使い始める](#使い始める)
- [リンク](#リンク)

## 使い始める

1. このリポジトリをテンプレートにして、新しいリポジトリを作ります。
2. APIは `apis/_template` を、業務フローは `docs/business/` のフォルダをコピーして書きます。
3. 図は PlantUML で書き、`./scripts/render-puml.sh` で SVG にします。
4. PRは、テンプレートの「概要」（2行まで）と「判断してほしい点」を書いて出します。

## リンク

- [GitHub の設定](docs/setup.md)
- [書き方と自動化（AI向け）](docs/guide.md)
- 記入例：[ログインする](apis/login/README.md)、[ログインして商品を探す](docs/business/ログインして商品を探す/README.md)、[AWSのインフラ構成](docs/infra/index.md)
- 決めた理由：[ADR 0000](decisions/0000-template.md)
