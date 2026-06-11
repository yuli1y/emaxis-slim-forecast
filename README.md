# eMAXIS Slim オルカン 予想基準価額

eMAXIS Slim 全世界株式(オール・カントリー)の直近基準価額と、午前10時・午後6時の予想基準価額を前日比で表示する静的Webアプリです。

## 使い方

GitHub Pagesでこのリポジトリの `main` ブランチ、`/root` を公開してください。

アプリ本体は次の静的ファイルだけで動きます。

- `index.html`
- `styles.css`
- `app.js`
- `data/snapshot.json`
- `icon.svg`
- `site.webmanifest`

## データ更新

別サーバーは使いません。GitHub Actionsが `data/snapshot.json` を日本時間の午前10時・午後6時に更新してコミットします。

手動更新したい場合は、GitHubのActionsタブから `Update forecast snapshot` を実行してください。

## 推計方法

直近の基準価額に、ACWI ETF(米ドル建て)の日次変化率とドル円の日次変化率を単純加算して掛けています。

これは正式な基準価額ではありません。信託報酬、配当、組入銘柄差、時差、休日差は未調整です。
