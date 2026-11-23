# codex-tmux-hud

**English** · [简体中文](README.zh-CN.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · [Español](README.es.md)

Launch Codex CLI with a per-pane tmux footer on macOS, Linux and Windows via WSL2.

```text
Context ▰▰▱▱▱▱▱▱ 69.1k/258.4k │ 22.1 t/s · 15s ago │ 1h avg 22.8 │ Cache hit: latest 97.4% · session 85.5%
```

## Install

Install tmux, Python 3.9+ and Codex CLI. Run the installer from this checkout.

```sh
./install.sh
oai
oai resume
oai resume --last
```

The installer places the launcher in `~/.local/bin`. Add that directory to PATH if needed. Set `PREFIX` to use another installation prefix. An existing `oai` at the destination is replaced.

## Linux and Windows

Download the Linux/WSL archive from [Releases](https://github.com/oslijunw/codex-tmux-hud/releases). On Windows, run the following inside a WSL2 Linux distribution with the Linux Codex CLI installed there. Native PowerShell and cmd sessions are not supported.

```sh
tar -xzf codex-tmux-hud-linux-wsl.tar.gz
cd codex-tmux-hud
./install.sh
~/.local/bin/oai
```

Linux requires tmux, Python 3.9+, ps (procps), and access to the current user's process file descriptors in /proc. On Debian or Ubuntu, install system dependencies with `sudo apt install tmux python3 procps`.

## Metrics

Context shows the last reported request size and the model context window. Cache hit is cached input tokens divided by all input tokens, shown for the latest request and the cumulative session. Unavailable usage appears as a dash. The launcher identifies the pane's open Codex rollout with macOS lsof or Linux /proc. Speed comes from CodexTPS and the hourly average is for the displayed model.

Click **[Threads]** in the footer to inspect context usage and cache hit rates for the main thread and its open subagents. Press **q** or **Esc** to close the popup. The footer shows main-thread usage when several rollout files are open.

Each launch creates a tmux session with mouse scrolling. When a local Codex background server is available, `oai resume` uses it so the same conversation can stay open in two windows. On exit from a normal shell, the launcher displays Codex's exit summary and an `oai resume` command for that conversation. Detaching leaves Codex running. Reattach with `tmux attach -t SESSION` to return to it.

## Collector

The bundled MIT-licensed CodexTPS receiver runs on loopback. The launcher reuses a running receiver or starts one in the background. By default it listens on port 4319 and stores metrics under `~/Library/Application Support/CodexTPS/data` on macOS and `~/.local/share/codex-tps` on Linux. Existing CodexTPS port settings are honored. To use a compatible CodexTPS checkout, set `OAI_COLLECTOR_APP` to its absolute app.py path. The launcher passes telemetry settings to standalone Codex invocations. A shared Codex server uses its own telemetry settings. If TPS is missing when resuming a shared session, set the following exporters in the Codex user config, using the receiver's configured port. Restart the Codex background server once its work has finished so it picks up the new settings.

```toml
[otel.exporter.otlp-http]
endpoint = "http://127.0.0.1:4319/v1/logs"
protocol = "json"

[otel.trace_exporter.otlp-http]
endpoint = "http://127.0.0.1:4319/v1/traces"
protocol = "json"
```

## License

MIT. The bundled collector includes the original Codex TPS contributors' license.
