#!/usr/bin/env python3
"""Codex TPS: local-only OTLP receiver, dashboard, menu and terminal adapters.

Python 3.9+, standard library only. No API key, proxy, or request interception.
"""
import argparse
import gzip
import io
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from store import Store, VERSION

ROOT = Path(__file__).resolve().parent
DEFAULT_DATA = Path.home() / "Library/Application Support/CodexTPS/data" if sys.platform == "darwin" else Path.home() / ".local/share/codex-tps"
MAX_BODY = 16 * 1024 * 1024


def installed_url():
    try:
        state_file = Path.home() / "Library/Application Support/CodexTPS/install-state.json"
        port = int(json.loads(state_file.read_text())["port"])
        if 1024 <= port <= 65535:
            return "http://127.0.0.1:%d" % port
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return "http://127.0.0.1:4319"


def attributes(items):
    result = {}
    for item in items or []:
        value = item.get("value", {})
        if isinstance(value, dict):
            for kind in ("stringValue", "intValue", "doubleValue", "boolValue"):
                if kind in value:
                    result[item.get("key", "")] = value[kind]
                    break
    return result


def read_url(url, timeout=3):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response)


def status_text(summary, model=None):
    rows = summary.get("models", [])
    if model:
        row = next((m for m in rows if m["model"] == model), None)
    else:
        row = max(rows, key=lambda m: (m.get("latest") or {}).get("ended_at", 0), default=None)
    if not row:
        return "Codex TPS · 等待请求数据"
    def number(value):
        return "—" if value is None else "%.1f" % value
    latest = row.get("latest") or {}
    age = max(0, int(time.time() - latest.get("ended_at", time.time())))
    age_text = ("%ds前" % age) if age < 60 else (("%dm前" % (age // 60)) if age < 3600 else ("%dh前" % (age // 3600)))
    return "%s · 最近 %s t/s (%s) · 1h %s · 24h %s · 全部 %s" % (row["model"], number(latest.get("tps")), age_text, number(row["hour"]["avg"]), number(row["day"]["avg"]), number(row["all"]["avg"]))


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, store, collector):
        super().__init__(address, Handler)
        self.store, self.collector = store, collector
        self.collector_lock = threading.RLock()


class Handler(BaseHTTPRequestHandler):
    server_version = "CodexTPS/" + VERSION

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, format, *args):
        # Default access logs include query strings and can grow indefinitely.
        pass

    def allowed(self):
        host = self.headers.get("Host", "")
        port = self.server.server_address[1]
        if host not in ("127.0.0.1:%s" % port, "localhost:%s" % port):
            self.reply(403, {"error": "Loopback host required"})
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in ("http://127.0.0.1:%s" % port, "http://localhost:%s" % port):
            self.reply(403, {"error": "Cross-origin requests are disabled"})
            return False
        return True

    def reply(self, status, value, mime="application/json; charset=utf-8", extra=None):
        if isinstance(value, (dict, list)):
            value = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        elif isinstance(value, str):
            value = value.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(value)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        for key, val in (extra or {}).items():
            self.send_header(key, val)
        self.end_headers()
        try:
            self.wfile.write(value)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        if not self.allowed():
            return
        parsed = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        get = lambda key, default=None: query.get(key, [default])[0]
        source, basis = get("source", "all"), get("basis", "response")
        try:
            if parsed.path == "/api/summary":
                self.reply(200, self.server.store.summary(source, basis))
            elif parsed.path == "/api/series":
                self.reply(200, self.server.store.series(get("model", ""), get("window", "1h"), source, basis))
            elif parsed.path in ("/api/health", "/api/diagnostics"):
                self.reply(200, self.server.store.health())
            elif parsed.path == "/api/status":
                model = get("model")
                if not model and get("view"):
                    model = (self.server.store.get("view:" + get("view"), {}) or {}).get("model")
                    if not model:
                        return self.reply(200, "Codex TPS · 等待当前窗格数据", "text/plain; charset=utf-8")
                model = model or self.server.store.get("pinned_model")
                self.reply(200, status_text(self.server.store.summary(source, basis), model), "text/plain; charset=utf-8")
            elif parsed.path == "/api/export":
                self.reply(200, "\ufeff" + self.server.store.export_csv(get("model"), source, basis, get("window", "all")), "text/csv; charset=utf-8", {"Content-Disposition": 'attachment; filename="codex-tps.csv"'})
            elif parsed.path in ("/", "/index.html"):
                self.reply(200, (ROOT / "web/index.html").read_bytes(), "text/html; charset=utf-8")
            elif parsed.path == "/favicon.ico":
                self.reply(204, b"", "image/x-icon")
            else:
                self.reply(404, {"error": "Not found"})
        except (ValueError, TypeError):
            self.reply(400, {"error": "Invalid query parameter"})
        except Exception as exc:
            self.server.store.set("last_error", type(exc).__name__)
            self.reply(500, {"error": "Internal error; see diagnostics"})

    def do_OPTIONS(self):
        self.reply(403, {"error": "Cross-origin requests are disabled"})

    def do_POST(self):
        if not self.allowed():
            return
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path not in ("/v1/logs", "/v1/traces", "/v1/metrics", "/api/pin"):
            return self.reply(404, {"error": "Not found"})
        try:
            size = int(self.headers.get("Content-Length", "-1"))
            if size < 0 or size > MAX_BODY:
                return self.reply(413, {"error": "Payload must be at most 16 MiB"})
            payload = self.rfile.read(size)
            if len(payload) != size:
                return self.reply(400, {"error": "Incomplete request body"})
            encoding = self.headers.get("Content-Encoding", "identity").lower()
            if encoding == "gzip":
                with gzip.GzipFile(fileobj=io.BytesIO(payload)) as stream:
                    payload = stream.read(MAX_BODY + 1)
                if len(payload) > MAX_BODY:
                    return self.reply(413, {"error": "Expanded payload too large"})
            elif encoding not in ("", "identity"):
                return self.reply(415, {"error": "Unsupported content encoding"})
            mime = self.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if mime == "application/json":
                data = json.loads(payload)
            elif mime in ("application/x-protobuf", "application/protobuf") and parsed.path.startswith("/v1/"):
                from otlp import decode_export
                data = decode_export(payload, parsed.path.rsplit("/", 1)[-1])
            else:
                return self.reply(415, {"error": "Use OTLP JSON or protobuf; set protocol=json"})
            if not isinstance(data, dict):
                raise ValueError("Object required")
            if parsed.path == "/api/pin":
                model = data.get("model")
                if not isinstance(model, str) or len(model) > 200:
                    raise ValueError("Invalid model")
                self.server.store.set("pinned_model", model)
                return self.reply(200, {"ok": True})
            query = urllib.parse.parse_qs(parsed.query)
            view = query.get("view", [None])[0]
            if view:
                if not re.fullmatch(r"[A-Za-z0-9_%:.\-]{1,100}", view):
                    raise ValueError("Invalid view")
                self.track_view(data, view)
            self.server.store.set("last_event_at", time.time())
            self.server.store.count("otlp_batches")
            method = getattr(self.server.collector, "ingest_" + parsed.path.rsplit("/", 1)[-1])
            with self.server.collector_lock:
                method(data)
            # OTLP export responses are empty messages on success, in the same encoding.
            if mime in ("application/x-protobuf", "application/protobuf"):
                self.reply(200, b"", "application/x-protobuf")
            else:
                self.reply(200, {})
        except (ValueError, TypeError, KeyError, AttributeError, IndexError, UnicodeError, EOFError, OSError):
            self.server.store.count("invalid_batches")
            self.reply(400, {"error": "Invalid OTLP payload"})
        except Exception as exc:
            self.server.store.set("last_error", type(exc).__name__)
            self.server.store.count("receiver_errors")
            self.reply(500, {"error": "Receiver error; inspect /api/diagnostics"})

    def track_view(self, data, view):
        """Track the model for an explicitly instrumented CLI/tmux pane."""
        candidates = []
        for group_key in ("resourceLogs", "resourceSpans"):
            for group in data.get(group_key, []):
                resource = group.setdefault("resource", {}).setdefault("attributes", [])
                resource.append({"key": "monitor.source", "value": {"stringValue": "cli"}})
                base = attributes(resource)
                for scope_key, item_key in (("scopeLogs", "logRecords"), ("scopeSpans", "spans")):
                    for scope in group.get(scope_key, []):
                        for item in scope.get(item_key, []):
                            attrs = dict(base, **attributes(item.get("attributes", [])))
                            model = attrs.get("gen_ai.response.model") or attrs.get("slug") or attrs.get("model") or attrs.get("gen_ai.request.model")
                            if model:
                                stamp = float(item.get("timeUnixNano") or item.get("endTimeUnixNano") or 0)
                                candidates.append((stamp, str(model)))
        if candidates:
            previous = self.server.store.get("view:" + view, {})
            stamp, model = max(candidates)
            if stamp >= previous.get("stamp", 0):
                self.server.store.set("view:" + view, {"model": model, "stamp": stamp})


def serve(args):
    if args.host != "127.0.0.1":
        raise SystemExit("Only 127.0.0.1 is supported; this tool is local to your Mac.")
    from collector import Collector
    store = Store(args.data_dir)
    server = LocalServer((args.host, args.port), store, Collector(store))
    def stop(signum, frame):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print("Codex TPS %s · http://127.0.0.1:%d" % (VERSION, args.port), flush=True)
    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
        store.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("serve", help="Start local receiver and chart UI")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=4319)
    p.add_argument("--data-dir", default=str(DEFAULT_DATA))
    for command in ("status", "swiftbar", "doctor"):
        p = sub.add_parser(command)
        p.add_argument("--url", default=None)
        p.add_argument("--model")
        p.add_argument("--view")
        p.add_argument("--basis", choices=("response", "decode", "estimated"), default="response")
    p = sub.add_parser("run", help="Launch Codex and track its model in the current tmux pane")
    p.add_argument("args", nargs=argparse.REMAINDER)
    p = sub.add_parser("import-otlp", help="Import a saved OTLP JSON batch (not a conversation transcript)")
    p.add_argument("file")
    p.add_argument("--kind", choices=("logs", "traces", "metrics"), required=True)
    p.add_argument("--data-dir", default=str(DEFAULT_DATA))
    args = parser.parse_args()
    if args.command == "serve":
        return serve(args)
    if args.command == "import-otlp":
        from collector import Collector
        store = Store(args.data_dir)
        payload = json.loads(Path(args.file).read_text())
        getattr(Collector(store), "ingest_" + args.kind)(payload)
        print(json.dumps(store.health(), ensure_ascii=False, indent=2))
        store.close()
        return
    if args.command == "run":
        view = "tmux-" + os.environ["TMUX_PANE"] if os.environ.get("TMUX_PANE") else "terminal-%s" % os.getpid()
        base = installed_url() + "/v1/"
        opts = []
        for key, kind in (("exporter", "logs"), ("trace_exporter", "traces")):
            # One TOML inline table is passed as one argv element, never a shell command.
            value = '{ otlp-http = { endpoint = "%s%s?view=%s", protocol = "json" } }' % (base, kind, urllib.parse.quote(view, safe=""))
            opts += ["-c", "otel.%s=%s" % (key, value)]
        cli_args = args.args[1:] if args.args[:1] == ["--"] else args.args
        try:
            return subprocess.call(["codex"] + opts + cli_args)
        except FileNotFoundError:
            raise SystemExit("codex executable not found in PATH. Install/open Codex CLI first.")
    url = (args.url or installed_url()).rstrip("/")
    try:
        if args.command == "doctor":
            print(json.dumps(read_url(url + "/api/diagnostics"), ensure_ascii=False, indent=2))
        elif args.command == "status":
            params = {"basis": args.basis}
            if args.model:
                params["model"] = args.model
            if args.view:
                params["view"] = args.view
            with urllib.request.urlopen(url + "/api/status?" + urllib.parse.urlencode(params), timeout=2) as response:
                print(response.read().decode("utf-8"))
        else:
            summary = read_url(url + "/api/summary?basis=" + args.basis)
            rows = summary.get("models", [])
            selected = next((r for r in rows if r["model"] == args.model), None) if args.model else None
            selected = selected or max(rows, key=lambda m: (m.get("latest") or {}).get("ended_at", 0), default=None)
            speed = (selected.get("latest") or {}).get("tps") if selected else None
            print("TPS %s" % ("%.1f" % speed if speed is not None else "—"))
            print("---")
            print("打开 TPS 曲线 | href=" + url)
            for row in rows:
                clean = re.sub(r"[\r\n|]", " ", row["model"])
                print("%s | href=%s/#model=%s" % (clean, url, urllib.parse.quote(row["model"], safe="")))
                for label, key in (("近 1h", "hour"), ("近 24h", "day"), ("全部", "all")):
                    bucket = row[key]
                    number = "—" if bucket["avg"] is None else "%.1f t/s" % bucket["avg"]
                    print("--%s %s · %d 次" % (label, number, bucket["count"]))
            print("---\n诊断 | href=" + url + "/#diagnostics")
    except (OSError, ValueError, urllib.error.URLError):
        print("Codex TPS · 服务未启动")
        if args.command == "swiftbar":
            print("---\n请运行安装包中的 Install.command")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
