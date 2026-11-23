# codex-tmux-hud

[English](README.md) · **简体中文** · [日本語](README.ja.md) · [한국어](README.ko.md) · [Español](README.es.md)

在 macOS、Linux 和 Windows（WSL2）上启动 Codex CLI，并为每个 tmux 窗格显示状态栏。

```text
Context ▰▰▱▱▱▱▱▱ 69.1k/258.4k │ 22.1 t/s · 15s ago │ 1h avg 22.8 │ Cache hit: latest 97.4% · session 85.5%
```

## 安装

安装 tmux、Python 3.9 或更高版本及 Codex CLI。在源码目录中运行：

```sh
./install.sh
oai
oai resume
oai resume --last
```

安装脚本将启动器放在 `~/.local/bin`。如有需要，将该目录加入 `PATH`。可通过 `PREFIX` 指定其他安装位置。目标位置已有的 `oai` 会被替换。

## Linux 和 Windows

从 [GitHub Releases](https://github.com/oslijunw/codex-tmux-hud/releases) 下载 Linux/WSL 安装包。在 Windows 上，请先在 WSL2 的 Linux 发行版中安装 Linux 版 Codex CLI，然后在其中执行以下命令：

```sh
tar -xzf codex-tmux-hud-linux-wsl.tar.gz
cd codex-tmux-hud
./install.sh
~/.local/bin/oai
```

Linux 需要 tmux、Python 3.9 或更高版本、`ps`（procps），并要求当前用户可以读取自己进程在 `/proc` 中的文件描述符。在 Debian 或 Ubuntu 上，使用 `sudo apt install tmux python3 procps` 安装系统依赖。

## 状态栏和会话恢复

- **Context** 显示最近一次请求的上下文用量与模型的上下文窗口大小。
- **TPS** 由 CodexTPS 采集。状态栏显示最近的生成速度和该模型最近一小时的平均速度。
- **Cache hit** 是命中缓存的输入 token 占全部输入 token 的比例，分别显示最近一次请求和整个会话的数值。暂无数据时显示短横线。

点击状态栏的 **[Threads]** 查看主线程和仍打开的子代理各自的上下文用量和缓存命中率。按 **q** 或 **Esc** 关闭弹窗。状态栏显示主线程的用量。独立运行的 Codex 通过 macOS 的 `lsof` 或 Linux 的 `/proc` 查找会话日志，共享后台模式按会话 ID 查找。

每次启动都会创建一个支持鼠标滚动的 tmux 会话。有本机共享后台时，`oai resume` 会连接它，两个窗口可以同时打开同一条 Codex 会话。从普通终端启动并退出时，终端会显示 Codex 的退出信息和 `oai resume <会话 ID>` 重连命令。分离 tmux 后，Codex 会继续运行，可用 `tmux attach -t SESSION` 重新连接。

## TPS 采集器

内置的 CodexTPS 接收端使用 MIT 许可证，并监听本机回环地址。启动器会复用已有接收端，或在后台启动一个。默认端口是 4319。数据在 macOS 上存放于 `~/Library/Application Support/CodexTPS/data`，在 Linux 上存放于 `~/.local/share/codex-tps`。已有的 CodexTPS 端口设置优先。设置 `OAI_COLLECTOR_APP` 可使用兼容的 CodexTPS 安装，值为其 `app.py` 的绝对路径。

启动器为独立运行的 Codex 传入采集参数。共享后台使用自己的 OTLP 配置。如果恢复共享会话后没有 TPS 数据，在 Codex 用户配置里设置以下导出器，并按接收端实际端口调整。等待后台任务结束后重启 Codex 后台，使新配置生效。

```toml
[otel.exporter.otlp-http]
endpoint = "http://127.0.0.1:4319/v1/logs"
protocol = "json"

[otel.trace_exporter.otlp-http]
endpoint = "http://127.0.0.1:4319/v1/traces"
protocol = "json"
```

## 许可证

本项目采用 MIT 许可证。内置采集器保留原 Codex TPS 贡献者的许可证。
