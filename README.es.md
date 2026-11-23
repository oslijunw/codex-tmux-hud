# codex-tmux-hud

[English](README.md) · [简体中文](README.zh-CN.md) · [日本語](README.ja.md) · [한국어](README.ko.md) · **Español**

Inicia Codex CLI en macOS, Linux y Windows mediante WSL2, con una barra de estado para cada panel de tmux.

```text
Context ▰▰▱▱▱▱▱▱ 69.1k/258.4k │ 22.1 t/s · 15s ago │ 1h avg 22.8 │ Cache hit: latest 97.4% · session 85.5%
```

## Instalación

Instala tmux, Python 3.9 o posterior y Codex CLI. Ejecuta el instalador desde la copia local del repositorio:

```sh
./install.sh
oai
oai resume
oai resume --last
```

El instalador coloca el lanzador en `~/.local/bin`. Añade ese directorio a `PATH` si es necesario. Puedes elegir otra ubicación con `PREFIX`. Si ya hay un archivo `oai` en el destino, se reemplazará.

## Linux y Windows

Descarga el archivo para Linux y WSL desde [GitHub Releases](https://github.com/oslijunw/codex-tmux-hud/releases). En Windows, ejecuta estos comandos dentro de una distribución de Linux de WSL2 que tenga instalada la versión de Codex CLI para Linux.

```sh
tar -xzf codex-tmux-hud-linux-wsl.tar.gz
cd codex-tmux-hud
./install.sh
~/.local/bin/oai
```

En Linux necesitas tmux, Python 3.9 o posterior y `ps` (procps), además de acceso a los descriptores de archivo de tus propios procesos en `/proc`. En Debian o Ubuntu, instala las dependencias del sistema con `sudo apt install tmux python3 procps`.

## Barra de estado y reanudación de sesiones

- **Context** muestra el uso de contexto de la última solicitud y el tamaño de la ventana de contexto del modelo.
- **TPS** usa los datos de CodexTPS para mostrar la velocidad de generación más reciente y el promedio del modelo durante la última hora.
- **Cache hit** muestra el porcentaje de tokens de entrada recuperados de la caché, tanto para la última solicitud como para toda la sesión. Si faltan datos, aparece un guion.

Haz clic en **[Threads]** en la barra de estado para ver el uso de contexto y el porcentaje de aciertos de caché del hilo principal y de sus subagentes abiertos. Pulsa **q** o **Esc** para cerrar la ventana emergente. La barra muestra el uso del hilo principal. En una ejecución independiente, el lanzador localiza los registros de sesión con `lsof` en macOS o `/proc` en Linux. Con el servidor compartido, usa el ID de la sesión.

Cada inicio crea una sesión de tmux que permite desplazarse con el ratón. Cuando hay un servidor local compartido en segundo plano, `oai resume` se conecta a él, de modo que puedes abrir la misma conversación de Codex en dos ventanas. Al salir de una sesión iniciada desde un shell, verás el resumen de salida de Codex y el comando `oai resume <ID de sesión>`. Si te desconectas de tmux, Codex sigue en ejecución. Puedes volver a conectarte con `tmux attach -t SESSION`.

## Colector de TPS

El receptor CodexTPS incluido tiene licencia MIT y escucha en la interfaz de bucle local. El lanzador reutiliza un receptor activo o inicia uno en segundo plano. El puerto predeterminado es el 4319. Los datos se guardan en `~/Library/Application Support/CodexTPS/data` en macOS y en `~/.local/share/codex-tps` en Linux. Si ya tienes un puerto configurado en CodexTPS, se conserva. Para usar una instalación compatible de CodexTPS, asigna a `OAI_COLLECTOR_APP` la ruta absoluta de su archivo `app.py`.

El lanzador pasa la configuración de telemetría a las ejecuciones independientes de Codex. El servidor compartido usa su propia configuración de OTLP. Si el TPS no aparece al reanudar una sesión compartida, configura los siguientes exportadores en el archivo de configuración de usuario de Codex y ajusta el puerto al del receptor. Cuando terminen las tareas en curso, reinicia el servidor de Codex en segundo plano para aplicar los cambios.

```toml
[otel.exporter.otlp-http]
endpoint = "http://127.0.0.1:4319/v1/logs"
protocol = "json"

[otel.trace_exporter.otlp-http]
endpoint = "http://127.0.0.1:4319/v1/traces"
protocol = "json"
```

## Licencia

MIT. El colector incluido conserva la licencia de los colaboradores originales de Codex TPS.
