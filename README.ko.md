# codex-tmux-hud

[English](README.md) · [简体中文](README.zh-CN.md) · [日本語](README.ja.md) · **한국어** · [Español](README.es.md)

macOS, Linux, Windows(WSL2)에서 Codex CLI를 실행하고 tmux 창의 각 패널에 상태 표시줄을 표시합니다.

```text
Context ▰▰▱▱▱▱▱▱ 69.1k/258.4k │ 22.1 t/s · 15s ago │ 1h avg 22.8 │ Cache hit: latest 97.4% · session 85.5%
```

## 설치

tmux, Python 3.9 이상, Codex CLI를 설치한 뒤 저장소를 내려받은 디렉터리에서 다음 명령을 실행하세요.

```sh
./install.sh
oai
oai resume
oai resume --last
```

실행 파일은 `~/.local/bin`에 설치됩니다. 필요하면 이 디렉터리를 `PATH`에 추가하세요. `PREFIX`로 설치 위치를 바꿀 수 있습니다. 설치 위치에 기존 `oai`가 있으면 새 파일로 교체됩니다.

## Linux 및 Windows

[GitHub Releases](https://github.com/oslijunw/codex-tmux-hud/releases)에서 Linux/WSL용 압축 파일을 다운로드하세요. Windows에서는 Linux용 Codex CLI가 설치된 WSL2 배포판에서 다음 명령을 실행하세요.

```sh
tar -xzf codex-tmux-hud-linux-wsl.tar.gz
cd codex-tmux-hud
./install.sh
~/.local/bin/oai
```

Linux에서는 tmux, Python 3.9 이상, `ps`(procps)가 필요합니다. 현재 사용자가 자신의 프로세스 파일 디스크립터를 `/proc`에서 읽을 수 있어야 합니다. Debian 또는 Ubuntu에서는 `sudo apt install tmux python3 procps`로 시스템 의존성을 설치할 수 있습니다.

## 상태 표시줄과 세션 재개

- **Context**는 마지막 요청의 컨텍스트 사용량과 모델의 컨텍스트 창 크기를 표시합니다.
- **TPS**는 CodexTPS에서 수집합니다. 최근 생성 속도와 해당 모델의 최근 1시간 평균 속도를 표시합니다.
- **Cache hit**는 전체 입력 토큰 중 캐시에 적중한 입력 토큰의 비율입니다. 마지막 요청과 전체 세션의 값이 표시됩니다. 데이터가 없으면 대시로 표시합니다.

상태 표시줄의 **[Threads]**를 클릭하면 메인 스레드와 열려 있는 하위 에이전트의 컨텍스트 사용량과 캐시 적중률을 확인할 수 있습니다. **q** 또는 **Esc**로 팝업을 닫습니다. 상태 표시줄에는 메인 스레드의 사용량이 표시됩니다. 독립 실행 모드에서는 macOS의 `lsof` 또는 Linux의 `/proc`으로 세션 로그를 찾고, 공유 백그라운드 서버를 사용하는 경우 세션 ID로 찾습니다.

실행할 때마다 마우스 스크롤이 가능한 tmux 세션이 생성됩니다. 로컬 공유 백그라운드 서버를 사용할 수 있으면 `oai resume`이 해당 서버에 연결되어 같은 Codex 대화를 두 창에서 열 수 있습니다. 일반 셸에서 실행한 뒤 종료하면 Codex 종료 메시지와 `oai resume <세션 ID>` 재연결 명령이 표시됩니다. tmux 연결을 끊어도 Codex는 계속 실행됩니다. `tmux attach -t SESSION`으로 다시 연결할 수 있습니다.

## TPS 수집기

내장 CodexTPS 수신기는 MIT 라이선스로 배포되며 루프백 주소에서 수신합니다. 실행기는 이미 실행 중인 수신기를 재사용하거나 필요에 따라 백그라운드에서 시작합니다. 기본 포트는 4319입니다. 데이터는 macOS의 `~/Library/Application Support/CodexTPS/data` 또는 Linux의 `~/.local/share/codex-tps`에 저장됩니다. 기존 CodexTPS 포트 설정이 있으면 그 값을 사용합니다. 호환되는 CodexTPS를 사용하려면 `OAI_COLLECTOR_APP`에 해당 `app.py`의 절대 경로를 지정하세요.

실행기는 독립 실행되는 Codex에 텔레메트리 설정을 전달합니다. 공유 백그라운드 서버는 자체 OTLP 설정을 사용합니다. 공유 세션을 재개한 뒤 TPS가 표시되지 않으면 Codex 사용자 설정에 다음 내보내기 설정을 추가하고 수신기에 맞게 포트를 조정하세요. 실행 중인 작업이 끝난 뒤 Codex 백그라운드 서버를 재시작하면 설정이 적용됩니다.

```toml
[otel.exporter.otlp-http]
endpoint = "http://127.0.0.1:4319/v1/logs"
protocol = "json"

[otel.trace_exporter.otlp-http]
endpoint = "http://127.0.0.1:4319/v1/traces"
protocol = "json"
```

## 라이선스

MIT 라이선스입니다. 내장 수집기에는 원래 Codex TPS 기여자의 라이선스가 포함되어 있습니다.
