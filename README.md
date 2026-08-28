# 掘り出し帳 (resale-watch)

メルカリ・ラクマ・2nd STREET オンラインの新着商品を横断監視し、
条件に合うものが出たらDiscordに通知する個人用ツールです。
運用費用は0円(GitHub Actions + GitHub Pages の無料枠のみ使用)。

## ⚠️ 最初に必ず読んでください

- このコードは、開発時にインターネット接続がない環境で作成したため、
  各サイトの実際のHTML構造・URLを検証できていません。
  `scraper.py` 内の「要検証」コメント箇所(検索URL、パラメータ名)を、
  実際にブラウザの検証ツールで確認しながら調整する作業が必要です。
- メルカリ・ラクマ・2nd STREETは利用規約で自動アクセスを制限している場合があります。
  個人の私的利用の範囲であっても、アクセス頻度を上げすぎない(15分に1回程度を推奨)、
  規約違反にならないよう自己責任で利用する、という前提で使ってください。
- サイト側の仕様変更で、突然動かなくなることがあります。

## セットアップ手順

### 1. GitHubリポジトリを作る
- GitHubアカウントがなければ作成(スマホのブラウザからでも可)
- **Public(公開)リポジトリ**として新規作成
  (Publicなら GitHub Actions の実行時間が無制限・無料になります)
- このフォルダの中身を丸ごとアップロード(GitHubのWeb UIからスマホでもドラッグ&ドロップでアップロード可能)

### 2. Discord Webhookを作る
1. Discordサーバーの通知を受け取りたいチャンネルの設定を開く
2. 「連携サービス」→「ウェブフック」→「新しいウェブフック」を作成
3. 表示されたWebhook URLをコピー

### 3. GitHubにWebhook URLを登録
- リポジトリの `Settings` → `Secrets and variables` → `Actions` → `New repository secret`
- Name: `DISCORD_WEBHOOK_URL`
- Value: コピーしたWebhook URL

### 4. 監視条件を設定
- `config.example.json` を `config.json` にコピー(ファイル名変更)
- `searches` に監視したいキーワード・カテゴリ・ブランド・価格帯を追加
- `interval_minutes` を希望の巡回間隔に変更

### 5. 巡回間隔をワークフローにも反映
- `.github/workflows/scrape.yml` の `cron` の値を、config.jsonと同じ間隔に変更
  - 15分ごと: `*/15 * * * *`
  - 30分ごと: `*/30 * * * *`
  - 1時間ごと: `0 * * * *`

### 6. GitHub Pagesを有効化(閲覧サイトの公開)
- リポジトリの `Settings` → `Pages`
- Source: `Deploy from a branch`
- Branch: `main` / フォルダ: `/docs` を選択して保存
- 数分後、`https://(あなたのユーザー名).github.io/(リポジトリ名)/` でアクセス可能に
- このURLはスマホのホーム画面に追加しておくと、アプリのように開けます

### 7. 動作確認
- リポジトリの `Actions` タブ → `resale-watch scraper` → `Run workflow` で手動実行
- 実行ログでエラーが出たら、`scraper.py` のセレクタ・URLを調整
- `docs/data.json` が更新され、Discordに通知が来れば成功

## ファイル構成
```
resale-watch/
├── scraper.py              # 巡回・通知のメイン処理
├── config.example.json     # 監視条件の設定サンプル
├── requirements.txt
├── .github/workflows/scrape.yml   # 自動実行の設定(間隔もここで調整)
└── docs/
    ├── index.html          # 一覧表示サイト(GitHub Pagesで公開)
    └── data.json           # 収集した商品データ(自動更新される)
```

## よくあるつまずきポイント
- **商品が0件のまま**: `scraper.py` の `search_url` や `item_url_pattern` が実際のサイトと合っていない可能性が高いです。ブラウザの「検証」機能でリンクのURLパターンを確認して修正してください。
- **Discordに通知が来ない**: Secretsの名前が `DISCORD_WEBHOOK_URL` と完全一致しているか確認。
- **Pagesが真っ白**: `docs/data.json` がまだ空(`items: []`)の場合は、一度Actionsを手動実行してください。
