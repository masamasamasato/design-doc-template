# AWSのインフラ構成

ログイン、ログアウト、商品詳細、商品一覧、商品検索のAPIを、次の置き方で動かします。

![AWSのインフラ構成](構成図.svg)

ソースは [構成図.puml](構成図.puml) です。図のアイコンは、plantuml.jar に入っている awslib を使います。外部のURLは読み込みません。APIの設計は [ログインする](../../apis/login/README.md)、[ログアウトする](../../apis/logout/README.md)、[商品詳細を取得する](../../apis/get-product/README.md)、[商品一覧を取得する](../../apis/list-products/README.md)、[商品を検索する](../../apis/search-products/README.md) です。

## 各要素の役割

- **利用者**: ブラウザから画面とAPIを使います。例: 雅人がログインして商品を探す。
- **Route 53**: サービスの名前を、CloudFront に繋ぎます。例: `www.example.com`。
- **CloudFront**: 画面のファイルを配り、APIの要求を ALB へ回します。
- **S3（静的画面）**: ログイン画面や商品画面のファイルを置きます。例: `login.html`。
- **ALB**: 2つのAZのAPIサービスへ、要求を振り分けます。パブリックサブネットに置きます。
- **ECS Fargate（APIサービス）**: ログインや商品のAPIを動かします。例: `POST /sessions`、`GET /products/search`。2つのAZに置きます。
- **RDS**: 利用者と商品のデータを置きます。例: メール `hana@example.com`、商品 `product_1001`。
- **ElastiCache**: セッションを置きます。どのAPIサーバーに当たっても、ログイン状態が続きます。例: セッション `session_789`。
- **CloudWatch Logs**: APIのログを集めます。パスワードはログに出しません。
- **VPC とサブネット**: ALB はパブリックサブネット、API と RDS と ElastiCache はプライベートサブネットに置きます。AZ は `ap-northeast-1a` と `ap-northeast-1c` の2つです。
