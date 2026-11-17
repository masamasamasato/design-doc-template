# AWSのインフラ構成

ログイン、ログアウト、商品詳細、商品一覧、商品検索のAPIを、この構成で動かします。**この図は、ログインと商品のAPIの記入例です。パスキー、復旧、カード登録、支払い、決済通知は載せていません。**決済サービス（外部）、通知の受け口、通知の署名の秘密も未掲載です。図は上から下へ、利用者 → Route 53 → CloudFront → ALB → 2つのAZのAPI → データの順です。左がデプロイと監視、VPCの外（AWSクラウド内）に SES と Secrets Manager があります。

![AWSのインフラ構成](構成図.svg)

ソース: [構成図.puml](構成図.puml)。図のアイコンは、plantuml.jar に入っている awslib を使います。外部のURLは読み込みません。APIの設計は [ログインする](../../apis/login/README.md)、[ログアウトする](../../apis/logout/README.md)、[商品詳細を取得する](../../apis/get-product/README.md)、[商品一覧を取得する](../../apis/list-products/README.md)、[商品を検索する](../../apis/search-products/README.md) です。

この図では省いたもの: セキュリティグループ、VPCエンドポイント。

## 図の読み方

利用者が画面とAPIを使う流れは、図の中央を上から下へ辿ります。実線は通信の流れです。AWS WAF から CloudFront、ACM から CloudFront と ALB への点線は、付けている関係と証明書を示します。

箱の中には、名前と概要・役割を1行書きます。詳しい補足と具体例は黄色い付箋にあります。付箋は対象の箱の真横または真下に置き、短い点線でつなぎます。付箋は、対象と同じ枠（AWSクラウド、VPC、AZ、サブネット、データ帯）の内側に置きます。枠はまたぎません。矢印は交差させません。

2つのAPIからデータへの線は「両APIからの通信（合流）」で合流し、ElastiCache と RDS の両方、Secrets Manager、SES へ分かれます。片方のAPIだけがDBを使う、とは読みません。SES と Secrets Manager への線は、ECR と同じく、ラベルと付箋に「NAT経由」と書いてあります。どちらも VPC の外（AWSクラウド内）に置きます。

GitHub Actions から ECR への線はデプロイです。API から NAT、ECR、CloudWatch への線は、交差を避けるため省き、付箋で示します。CloudWatch Alarm の通知先は SNS で、SES には繋がりません。

## 各要素の役割

- **利用者**: ブラウザから画面とAPIを使います。例: 雅人がログインして商品を探す。
- **GitHub Actions**: APIのイメージをECRに置き、ECSへデプロイします。AWSの外にあります。
- **Route 53**: サービスの名前を CloudFront に繋ぎます。例: `www.example.com`。
- **AWS WAF**: CloudFront に付け、不正な要求を落とします。図では点線で示します。
- **ACM**: CloudFront と ALB の HTTPS 証明書を発行します。図では点線で「証明書」と示します。
- **CloudFront**: HTTPS で配信します。画面のファイルは S3 から取り、APIの要求は ALB へ回します。
- **S3（静的画面）**: ログイン画面や商品画面のファイルを置きます。例: `login.html`。CloudFront からだけ読めます（OAC）。直接のURLでは開けません。
- **ALB**: 2つのAZのAPIサービスへ、要求を振り分けます。2つのAZのパブリックサブネットにまたがります。
- **NAT Gateway**: AZごとに1つ置き、そのAZのパブリックサブネットに置きます。NAT 1a は AZ `ap-northeast-1a`、NAT 1c は `ap-northeast-1c` です。そのAZのAPIが ECR や SES などへ出るときに使います。
- **ECS Fargate（APIサービス）**: ログインや商品のAPIを動かします。例: `POST /sessions`、`GET /products/search`。各AZのプライベートサブネットに1つずつ置きます。
- **ElastiCache**: セッションを置きます。セッションの TTL は、例：ログインから24時間です。切れたら、もう一度ログインします。ログインの失敗回数とロックも置きます。TTL は、例：15分です。プライマリは AZ `ap-northeast-1a`、レプリカは `ap-northeast-1c` です。どのAPIサーバーに当たっても、ログイン状態が続きます。
- **RDS**: 利用者と商品のデータを置きます。例: メールアドレス `masato@example.com`、商品 `product_1001`。プライマリは AZ `ap-northeast-1a`、スタンバイは `ap-northeast-1c` です。どちらのAPIからも使えます。
- **Secrets Manager**: この図では、DBパスワードを置きます。決済通知の署名の秘密も実際はここに置きますが、決済は図に載せていません。コードやログ、図には出しません。VPC の外（AWSクラウド内）に置き、API からは NAT 経由で取ります。
- **ECR**: APIのコンテナイメージを置きます。GitHub Actions が push し、API は NAT 経由で取ります。ECR からAPIへの線は交差するため省き、付箋で示します。
- **CloudWatch Logs**: 両APIのログを集めます。パスワードは出しません。図では線を引かず、付箋で示します。
- **CloudWatch Alarm**: ログやメトリクスを見て、SNS で知らせます。例: 5xx が増えたら通知する。
- **Amazon SNS**: アラームの通知先です。例: 開発者にメールや Slack で知らせる。
- **SES**: ログイン通知メールを送ります。「両APIからの通信（合流）」の線を、NAT 経由で引きます。VPC の外（AWSクラウド内）に置きます。送信に失敗しても、ログインは成功のままです。
- **VPC とサブネット**: NAT は各AZのパブリックサブネット、ALB は2つのAZのパブリックサブネットにまたがり、API は各AZのプライベートサブネット、RDS と ElastiCache はプライベートのデータ帯に置きます。AZ は `ap-northeast-1a` と `ap-northeast-1c` の2つです。
