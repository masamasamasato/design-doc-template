# エージェントへの案内

作業を始める前に [docs/guide.md](docs/guide.md) を読み、その決まりに従います。書き方、図、PR、自動化の正本は、このファイルではなく `docs/guide.md` です。

このリポジトリで使う確認と形は、次のとおりです。

- サイトの確認は `NO_MKDOCS_2_WARNING=1 mkdocs build --strict` です。リンク切れもここで分かります。
- サイトを見るときは、`pip install -r requirements.txt` のあと `NO_MKDOCS_2_WARNING=1 mkdocs serve -a 127.0.0.1:8765` です。
- PDF を作るときは、`pip install -r requirements.txt -r requirements-pdf.txt` と Playwright の導入のあと `./scripts/build-pdf.sh` です。
- 図の SVG は `./scripts/render-puml.sh` で、同じ場所に作ります。
- 目次は `python3 scripts/update-toc.py` で作り直します。手で書きません。
- 図は PlantUML だけです。Mermaid は使いません。
- 文書と PR は日本語で書きます。
- PR のタイトルは、何をどう変えたかを日本語で書きます。`fix` や `feat:` などの接頭辞は付けません。
- PR の本文は、概要を2行まで、「判断してほしい点」を番号付き（無ければ「なし」）、補足は閉じた details に書きます。形は `.github/pull_request_template.md` です。
- `main` へは直接 push しません。変更は PR で出します。
- `apis/<名前>/変更履歴.md` と `docs/business/<業務>/変更履歴.md` は、人が手で書きません。`main` へマージしたときに自動で足されます。
