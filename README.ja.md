# codex-tmux-hud

[English](README.md) · [简体中文](README.zh-CN.md) · **日本語** · [한국어](README.ko.md) · [Español](README.es.md)

macOS、Linux、Windows（WSL2）で Codex CLI を起動し、tmux のペインごとにステータスバーを表示します。

```text
Context ▰▰▱▱▱▱▱▱ 69.1k/258.4k │ 22.1 t/s · 15s ago │ 1h avg 22.8 │ Cache hit: latest 97.4% · session 85.5%
```

## インストール

tmux、Python 3.9 以降、Codex CLI をインストールし、このリポジトリの作業ディレクトリで次のコマンドを実行してください。

```sh
./install.sh
oai
oai resume
oai resume --last
```

ランチャーは `~/.local/bin` にインストールされます。必要に応じてこのディレクトリを `PATH` に追加してください。`PREFIX` でインストール先を変更できます。インストール先に `oai` がある場合は置き換えられます。

## Linux と Windows

[GitHub Releases](https://github.com/oslijunw/codex-tmux-hud/releases) から Linux/WSL 用のアーカイブをダウンロードしてください。Windows では、Linux 版の Codex CLI をインストールした WSL2 の Linux ディストリビューション内で実行します。

```sh
tar -xzf codex-tmux-hud-linux-wsl.tar.gz
cd codex-tmux-hud
./install.sh
~/.local/bin/oai
```

Linux では tmux、Python 3.9 以降、`ps`（procps）が必要です。現在のユーザーが、自身のプロセスのファイルディスクリプターを `/proc` から読み取れる必要があります。Debian または Ubuntu では、`sudo apt install tmux python3 procps` でシステムの依存パッケージをインストールできます。

## ステータスバーとセッションの再開

- **Context** は直近のリクエストのコンテキスト使用量と、モデルのコンテキストウィンドウの上限を表示します。
- **TPS** は CodexTPS が計測した直近の生成速度と、そのモデルの過去 1 時間の平均速度です。
- **Cache hit** はキャッシュにヒットした入力トークンの割合です。直近のリクエストとセッション全体の値が表示されます。データがない場合はダッシュが表示されます。

ステータスバーの **[Threads]** をクリックすると、メインスレッドと開いているサブエージェントのコンテキスト使用量およびキャッシュヒット率を確認できます。ポップアップは **q** または **Esc** で閉じます。ステータスバーにはメインスレッドの使用量が表示されます。Codex を単独で実行する場合は macOS の `lsof` または Linux の `/proc` でセッションログを探し、共有バックグラウンドサーバーを使う場合はセッション ID で検索します。

起動するたびにマウスでスクロールできる tmux セッションが作成されます。ローカルの共有バックグラウンドサーバーが利用できる場合、`oai resume` はそのサーバーに接続します。同じ Codex 会話を 2 つのウィンドウで開けます。通常のシェルから起動して終了すると、Codex の終了メッセージと `oai resume <セッションID>` が表示されます。tmux をデタッチしても Codex は動作し続けます。`tmux attach -t SESSION` で再接続できます。

## TPS コレクター

同梱の CodexTPS レシーバーは MIT ライセンスで配布され、ループバックアドレスで待ち受けます。ランチャーは稼働中のレシーバーを再利用し、必要に応じてバックグラウンドで起動します。既定のポートは 4319 です。データは macOS では `~/Library/Application Support/CodexTPS/data`、Linux では `~/.local/share/codex-tps` に保存されます。CodexTPS にポート設定がある場合はその設定が使われます。互換性のある CodexTPS を使うには、`OAI_COLLECTOR_APP` にその `app.py` の絶対パスを指定します。

ランチャーは単独で起動する Codex にテレメトリー設定を渡します。共有バックグラウンドサーバーは自身の OTLP 設定を使います。共有セッションを再開したときに TPS が表示されない場合は、Codex のユーザー設定に以下のエクスポーターを指定し、レシーバーのポートに合わせてください。処理中のタスクが完了してから Codex のバックグラウンドサーバーを再起動すると、設定が反映されます。

```toml
[otel.exporter.otlp-http]
endpoint = "http://127.0.0.1:4319/v1/logs"
protocol = "json"

[otel.trace_exporter.otlp-http]
endpoint = "http://127.0.0.1:4319/v1/traces"
protocol = "json"
```

## ライセンス

MIT ライセンス。同梱のコレクターには、元の Codex TPS コントリビューターのライセンスが含まれます。
