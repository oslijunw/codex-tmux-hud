# codex-tmux-hud

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

Each launch creates a tmux session with mouse scrolling. Detaching leaves Codex running. Reattach with `tmux attach -t SESSION` to return to it.

## Collector

The bundled MIT-licensed CodexTPS receiver runs on loopback. The launcher reuses a running receiver or starts one in the background. By default it listens on port 4319 and stores metrics under `~/Library/Application Support/CodexTPS/data` on macOS and `~/.local/share/codex-tps` on Linux. Existing CodexTPS port settings are honored. To use a compatible CodexTPS checkout, set `OAI_COLLECTOR_APP` to its absolute app.py path. The launcher passes telemetry settings to each Codex invocation.

## License

MIT. The bundled collector includes the original Codex TPS contributors' license.
