# AWSのインフラ構成

ログイン、ログアウト、商品詳細、商品一覧、商品検索のAPIを、次の置き方で動かします。図は上から下へ、利用者、Route 53、CloudFront、ALB、2つのAZのAPI、データの順です。左にデプロイと監視、データの右に Secrets Manager があります。

![AWSのインフラ構成](構成図.svg)

ソースは [構成図.puml](構成図.puml) です。図のアイコンは、plantuml.jar に入っている awslib を使います。外部のURLは読み込みません。APIの設計は [ログインする](../../apis/login/README.md)、[ログアウトする](../../apis/logout/README.md)、[商品詳細を取得する](../../apis/get-product/README.md)、[商品一覧を取得する](../../apis/list-products/README.md)、[商品を検索する](../../apis/search-products/README.md) です。

この図では省いたもの: セキュリティグループ、VPCエンドポイント。

## 図の読み方

利用者が画面とAPIを使う流れは、図の中央を上から下へ辿ります。2つのAPIからデータへの線は「両APIから」で合流し、ElastiCache と RDS の両方、および Secrets Manager へ分かれます。片方のAPIだけがDBを使う、とは読みません。

GitHub Actions から ECR への線だけ、デプロイを表します。APIが NAT、ECR、SES、CloudWatch へ向かう線は、図が絡まないよう省き、ラベルで示します。NAT Gateway は各AZのパブリックサブネットに置き、そのAZのAPIが外へ出るときに使います。

補足は各箱のラベルに書いてあり、AWSクラウドやVPCなどの枠はまたぎません。

## 各要素の役割

- **利用者**: ブラウザから画面とAPIを使います。例: 雅人がログインして商品を探す。
- **GitHub Actions**: APIのイメージをECRに置き、ECSへデプロイします。AWSの外にあります。
- **Route 53**: サービスの名前を CloudFront に繋ぎます。例: `www.example.com`。
- **AWS WAF**: CloudFront の前で、不正な要求を落とします。
- **ACM**: CloudFront と ALB の HTTPS 証明書を出します。
- **CloudFront**: HTTPS で配信します。画面は OAC で S3 だけに繋ぎ、APIの要求は ALB へ回します。
- **S3（静的画面）**: ログイン画面や商品画面のファイルを置きます。例: `login.html`。OAC 経由だけ公開します。
- **ALB**: 2つのAZのAPIサービスへ、要求を振り分けます。パブリックサブネットに置きます。
- **NAT Gateway**: AZごとに1つ置き、そのAZのAPIが ECR や SES などへ出るときに使います。
- **ECS Fargate（APIサービス）**: ログインや商品のAPIを動かします。例: `POST /sessions`、`GET /products/search`。各AZのプライベートサブネットに1つずつ置きます。
- **ElastiCache**: セッションを置きます。プライマリとレプリカがあります。どのAPIサーバーに当たっても、ログイン状態が続きます。
- **RDS**: 利用者と商品のデータを置きます。例: メール `hana@example.com`、商品 `product_1001`。マルチAZ（プライマリとスタンバイ）です。どちらのAPIからも使えます。
- **Secrets Manager**: DBパスワードを置きます。コードやログ、図には出しません。
- **ECR**: APIのコンテナイメージを置きます。GitHub Actions が押し、API は NAT 経由で取ります。
- **CloudWatch Logs**: 両APIのログを集めます。パスワードは出しません。図では線を引かず、ラベルで示します。
- **CloudWatch Alarm**: ログやメトリクスを見て知らせます。例: 5xx が増えたら通知する。
- **SES**: メールを送ります。例: ログイン通知。API は NAT 経由で使います。
- **VPC とサブネット**: ALB と NAT はパブリックサブネット、API は各AZのプライベートサブネット、RDS と ElastiCache はプライベートのデータ帯に置きます。AZ は `ap-northeast-1a` と `ap-northeast-1c` の2つです。
