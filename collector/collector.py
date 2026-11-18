"""Conservative OTLP/JSON adapter for Codex request TPS.

Verified against openai/codex 3062f7aa4a8c293f4d3ab44c055a779ae5059b98:
  core/src/session/turn.rs: try_run_sampling_request, stream_request,
      receiving_stream, and completed (renamed handle_responses) spans.
  otel/src/events/session_telemetry.rs: output_token_count completion logs
      and gen_ai.usage.output_tokens on the completed span.

The completed span covers ONE stream event, NOT the whole response. Its own
duration is never used as the denominator. Correlation requires an exact
trace/parent relationship to the stream_request and receiving_stream spans.
Export batches may arrive out of order. Only allow-listed metadata is retained;
prompt text, tool results, user identifiers, filesystem paths and log bodies
are discarded. Metrics histograms are deliberately not converted to samples.
"""
from __future__ import annotations

import hashlib
import math
import re
import threading
import time
from datetime import datetime


SCHEMA_COMMIT = "3062f7aa4a8c293f4d3ab44c055a779ae5059b98"
MAX_SPANS = 30000
MAX_SESSIONS = 2000
TTL = 48 * 3600
MAX_DURATION = 24 * 3600
STATE_KEY = "collector.state.v1"
ALLOWED = frozenset({
    "model", "slug", "gen_ai.request.model", "gen_ai.response.model",
    "conversation.id", "session.id", "session_id", "thread.id", "thread_id",
    "turn.id", "turn_id", "originator", "session_source", "service.name",
    "service.version", "app.version", "monitor.source", "monitor.view",
    "gen_ai.usage.output_tokens", "codex.usage.reasoning_output_tokens",
    "gen_ai.usage.input_tokens", "output_token_count", "reasoning_token_count",
    "input_token_count", "event.name", "event.kind", "event.timestamp",
    "ttft_ms", "otel.name", "codex.turn.phase", "codex.request.reasoning_effort",
    "model_reasoning_effort", "service_tier",
})


def _get(obj, camel, snake=None, default=None):
    return obj.get(camel, obj.get(snake, default) if snake else default)


def _value(value):
    if not isinstance(value, dict):
        return value if isinstance(value, (str, int, float, bool)) else None
    for key in ("stringValue", "string_value", "intValue", "int_value",
                "doubleValue", "double_value", "boolValue", "bool_value"):
        if key in value:
            return value[key]
    return None


def attrs(values):
    """Decode only our numeric/identifier allow-list, never arbitrary content."""
    result = {}
    if not isinstance(values, list):
        return result
    for item in values[:512]:
        if not isinstance(item, dict) or item.get("key") not in ALLOWED:
            continue
        value = _value(item.get("value"))
        if isinstance(value, str):
            value = value[:256]
        if value is not None:
            result[item["key"]] = value
    return result


def number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def nanos(value):
    result = number(value)
    return result / 1e9 if result is not None and result > 0 else None


def timestamp(item, metadata):
    value = nanos(_get(item, "timeUnixNano", "time_unix_nano"))
    if value:
        return value
    try:
        text = str(metadata.get("event.timestamp", ""))
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except (ValueError, OverflowError):
        return None


def source_of(metadata):
    forced = metadata.get("monitor.source")
    if forced in {"cli", "desktop", "unknown"}:
        return forced
    candidates = [str(metadata.get(k, "")).lower() for k in
                  ("originator", "session_source", "service.name")]
    if any(v in {"codex_desktop", "codex desktop", "desktop"} for v in candidates):
        return "desktop"
    if any(v in {"codex_cli_rs", "codex-cli", "codex_cli", "cli", "exec"}
           for v in candidates):
        return "cli"
    # app-server can serve several clients; it does not prove desktop origin.
    return "unknown"


def model_of(metadata):
    # Codex logs use model for the selected catalog alias and slug for the
    # resolved model. Request parent spans already put model_info.slug in model.
    for key in ("gen_ai.response.model", "slug", "model", "gen_ai.request.model"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:180]
    return None


def session_of(metadata):
    for key in ("conversation.id", "thread.id", "thread_id", "session.id", "session_id"):
        value = metadata.get(key)
        if isinstance(value, str) and value:
            return value[:180]
    return None


def _identifier(value):
    # OTLP ids are hex strings; all-zero means no valid context.
    if not isinstance(value, str) or not value or len(value) > 128:
        return ""
    return "" if not value.strip("0") else value


class Collector:
    def __init__(self, store):
        self.store = store
        self.lock = threading.RLock()
        saved = store.get(STATE_KEY, {}) or {}
        self.spans = saved.get("spans", {})
        # Older adapters cached only by session. A session can be resumed by
        # another client, so only keep explicitly trace-scoped source records.
        self.sessions = {k: v for k, v in saved.get("sessions", {}).items()
                         if isinstance(v, dict) and v.get("trace_id") and v.get("session_id")}
        self.done = saved.get("done", {})
        self.event_kinds = store.get("event_kinds", {}) or {}
        self.field_names = set(store.get("field_names", []) or [])
        self._counts = {}
        self._prune()

    def _counter(self, name, n=1):
        self._counts[name] = self._counts.get(name, 0) + n

    def _flush_counters(self):
        for name, count in self._counts.items():
            self.store.count(name, count)
        self._counts.clear()

    def _save(self):
        self._flush_counters()
        self._prune()
        self.store.set(STATE_KEY, {"spans": self.spans, "sessions": self.sessions,
                                   "done": self.done})
        pending = sum(
            1 for key, span in self.spans.items()
            if self._is_completion(span) and key not in self.done)
        self.store.set("collector.pending_completions", pending)
        self.store.set("event_kinds", self.event_kinds)
        self.store.set("field_names", sorted(self.field_names))
        notes = []
        if self.store.get("collector.has_completion_logs") and not self.store.get("collector.has_traces"):
            notes.append("已收到完成 Token 用量，但未收到追踪。请确认 trace_exporter 已启用；单条 SSE 事件耗时不能计算 TPS。")
        if pending:
            notes.append("有 %s 条完成事件等待同一请求的父级追踪；Codex 关闭 span 和批量导出后会自动补齐。" % pending)
        if self.store.get("collector.metrics_not_request_samples"):
            notes.append("指标直方图属于聚合数据，未将其冒充逐请求 TPS。")
        self.store.set("collector_notes", notes)

    def _diagnostic(self, kind, raw_attrs):
        if isinstance(kind, str) and re.fullmatch(r"[A-Za-z0-9_.:/-]{1,100}", kind):
            if kind in self.event_kinds or len(self.event_kinds) < 100:
                self.event_kinds[kind] = self.event_kinds.get(kind, 0) + 1
        if isinstance(raw_attrs, list):
            for item in raw_attrs[:512]:
                if not isinstance(item, dict):
                    continue
                key = item.get("key")
                if (isinstance(key, str) and len(self.field_names) < 100 and
                        re.fullmatch(r"[A-Za-z0-9_.:/-]{1,100}", key)):
                    self.field_names.add(key)

    def _prune(self):
        cutoff = time.time() - TTL
        self.spans = {k: v for k, v in self.spans.items()
                      if isinstance(v, dict) and v.get("seen", 0) >= cutoff}
        if len(self.spans) > MAX_SPANS:
            ordered = sorted(self.spans, key=lambda k: self.spans[k].get("seen", 0))
            for key in ordered[:len(self.spans) - MAX_SPANS]:
                self.spans.pop(key, None)
        self.sessions = {k: v for k, v in self.sessions.items()
                         if isinstance(v, dict) and v.get("seen", 0) >= cutoff}
        if len(self.sessions) > MAX_SESSIONS:
            keys = sorted(self.sessions, key=lambda k: self.sessions[k].get("seen", 0))
            for key in keys[:len(self.sessions) - MAX_SESSIONS]:
                self.sessions.pop(key, None)
        self.done = {k: v for k, v in self.done.items() if v >= cutoff}
        if len(self.done) > MAX_SPANS:
            self.done = dict(sorted(self.done.items(), key=lambda pair: pair[1])[-MAX_SPANS:])

    def _session_metadata(self, metadata, trace_id=""):
        sid = session_of(metadata)
        trace_id = _identifier(trace_id)
        if sid and trace_id:
            # A session id is durable across CLI/desktop resumes. Source
            # enrichment must additionally match this exact OTel trace.
            key = trace_id + ":" + sid
            prev = self.sessions.get(key, {})
            source = source_of(metadata)
            if source == "unknown":
                source = prev.get("source", "unknown")
            if source != "unknown" and source != prev.get("source") and hasattr(self.store, "enrich_source"):
                self.store.enrich_source(sid, source, trace_id)
            self.sessions[key] = {"source": source, "seen": time.time(),
                                  "trace_id": trace_id, "session_id": sid}

    def ingest_logs(self, payload):
        with self.lock:
            count = 0
            latest_event = None
            has_completion = False
            resources = _get(payload, "resourceLogs", "resource_logs", []) or []
            for resource in resources:
                metadata = attrs(resource.get("resource", {}).get("attributes", []))
                groups = (_get(resource, "scopeLogs", "scope_logs") or
                          _get(resource, "instrumentationLibraryLogs", "instrumentation_library_logs", []) or [])
                for group in groups:
                    for log in _get(group, "logRecords", "log_records", []) or []:
                        if not isinstance(log, dict):
                            continue
                        values = dict(metadata)
                        values.update(attrs(log.get("attributes", [])))
                        self._diagnostic("log:" + str(values.get("event.name", "unknown")) + ":" +
                                         str(values.get("event.kind", "event")), log.get("attributes", []))
                        self._session_metadata(values, _get(log, "traceId", "trace_id"))
                        self._counter("received_logs")
                        # Both SSE and WS completions use this event. The log
                        # contains no full-response duration: don't fabricate one.
                        if (values.get("event.name") == "codex.sse_event" and
                                values.get("event.kind") == "response.completed" and
                                number(values.get("output_token_count")) is not None):
                            has_completion = True
                        observed = timestamp(log, values)
                        if observed:
                            latest_event = max(observed, latest_event or observed)
                        count += 1
            if latest_event:
                self.store.set("collector.last_event_at", latest_event)
            if has_completion:
                self.store.set("collector.has_completion_logs", True)
            accepted = self._resolve()
            self._save()
            return accepted

    def ingest_traces(self, payload):
        with self.lock:
            latest_event = None
            resources = _get(payload, "resourceSpans", "resource_spans", []) or []
            for resource in resources:
                metadata = attrs(resource.get("resource", {}).get("attributes", []))
                groups = (_get(resource, "scopeSpans", "scope_spans") or
                          _get(resource, "instrumentationLibrarySpans", "instrumentation_library_spans", []) or [])
                for group in groups:
                    for item in group.get("spans", []) or []:
                        if not isinstance(item, dict):
                            continue
                        self._counter("received_spans")
                        trace = _identifier(_get(item, "traceId", "trace_id"))
                        sid = _identifier(_get(item, "spanId", "span_id"))
                        if not trace or not sid:
                            self._counter("invalid_span_context")
                            continue
                        values = dict(metadata)
                        values.update(attrs(item.get("attributes", [])))
                        self._session_metadata(values, trace)
                        name = str(values.get("otel.name") or item.get("name") or "")[:100]
                        self._diagnostic("span:" + name, item.get("attributes", []))
                        start = nanos(_get(item, "startTimeUnixNano", "start_time_unix_nano"))
                        end = nanos(_get(item, "endTimeUnixNano", "end_time_unix_nano"))
                        if not start or not end or end < start:
                            self._counter("invalid_span_time")
                            continue
                        # Retain only spans useful for correlation/ancestors.
                        useful = (name in {"completed", "response.completed", "handle_responses",
                                           "receiving_stream", "stream_request", "codex.sampling",
                                           "sampling", "try_run_sampling_request", "run_sampling_request",
                                           "try_run_turn", "run_turn"} or
                                  model_of(values) is not None or session_of(values) is not None)
                        if not useful:
                            continue
                        status = item.get("status", {}) or {}
                        code = status.get("code", 0)
                        failed = code in (2, "2", "STATUS_CODE_ERROR", "ERROR")
                        parent = _identifier(_get(item, "parentSpanId", "parent_span_id"))
                        self.spans[trace + ":" + sid] = {
                            "trace": trace, "span": sid, "parent": parent,
                            "name": name, "start": start, "end": end,
                            "attrs": values, "failed": failed, "seen": time.time(),
                        }
                        latest_event = max(end, latest_event or end)
            if latest_event:
                self.store.set("collector.last_event_at", latest_event)
                self.store.set("collector.has_traces", True)
            accepted = self._resolve()
            self._save()
            return accepted

    def ingest_metrics(self, payload):
        """Acknowledge metrics, without mistaking aggregate histograms for requests."""
        with self.lock:
            count = 0
            for resource in _get(payload, "resourceMetrics", "resource_metrics", []) or []:
                for group in _get(resource, "scopeMetrics", "scope_metrics", []) or []:
                    count += len(group.get("metrics", []) or [])
            self._counter("received_metrics", count)
            if count:
                self.store.set("collector.metrics_not_request_samples", True)
            self._save()
            return 0

    @staticmethod
    def _is_completion(span):
        return (span["name"] in {"completed", "response.completed", "handle_responses"}
                and number(span["attrs"].get("gen_ai.usage.output_tokens")) is not None)

    def _ancestor_chain(self, span):
        result = []
        seen = set()
        current = span
        for _ in range(25):
            key = current["trace"] + ":" + current["parent"]
            if key in seen or key not in self.spans:
                break
            seen.add(key)
            current = self.spans[key]
            result.append(current)
        return result

    def _resolve(self):
        accepted = 0
        resolved_keys = set()
        # Exact parent indexes are essential: two threads can run simultaneously.
        siblings = {}
        for span in self.spans.values():
            siblings.setdefault((span["trace"], span["parent"]), []).append(span)
        for key, completed in list(self.spans.items()):
            if key in self.done or not self._is_completion(completed):
                continue
            if completed["failed"]:
                self.done[key] = time.time()
                self._counter("rejected_samples")
                continue
            ancestors = self._ancestor_chain(completed)
            receiving = next((s for s in ancestors if s["name"] == "receiving_stream"), None)
            if receiving is None:
                continue
            # stream_request and receiving_stream are siblings of the exact
            # try_run_sampling_request invocation; never join by model/time alone.
            family = siblings.get((receiving["trace"], receiving["parent"]), [])
            starts = [s for s in family if s["name"] == "stream_request"
                      and s["start"] <= receiving["start"]
                      and s["end"] <= receiving["start"] + .001
                      and s["end"] >= receiving["start"] - 60
                      and not s["failed"]]
            if len(starts) != 1:
                # Reject ambiguity, including parent contexts reused for retries.
                continue
            request = starts[0]
            if not (receiving["start"] <= completed["start"] <= completed["end"] <= receiving["end"] + .001):
                continue
            sampling = [s for s in family if s["name"] in {"codex.sampling", "sampling"}
                        and s["start"] <= request["start"] + .001
                        and s["end"] >= completed["end"] - .001]
            # Build metadata by ancestry, child overrides parent. Model comes
            # from this request invocation, never from a stale session cache.
            metadata = {}
            for ancestor in reversed(ancestors):
                metadata.update(ancestor["attrs"])
            if len(sampling) == 1:
                metadata.update(sampling[0]["attrs"])
            metadata.update(request["attrs"])
            metadata.update(completed["attrs"])
            model = model_of(metadata)
            if not model:
                continue
            token_number = number(completed["attrs"].get("gen_ai.usage.output_tokens"))
            duration = completed["end"] - request["start"]
            if (token_number is None or token_number < 0 or token_number >= 2**63
                    or token_number != int(token_number)
                    or not 0 < duration <= MAX_DURATION):
                self.done[key] = time.time()
                self._counter("rejected_samples")
                continue
            sid = session_of(metadata)
            source = source_of(metadata)
            source_context_key = completed["trace"] + ":" + (sid or "")
            if source == "unknown" and source_context_key in self.sessions:
                source = self.sessions[source_context_key].get("source", "unknown")
            sample = {
                "id": "otel:" + hashlib.sha256((key + ":response").encode()).hexdigest(),
                "basis": "response", "model": model,
                "started_at": request["start"], "ended_at": completed["end"],
                "duration_s": duration, "output_tokens": int(token_number),
                "reasoning_tokens": max(0, int(number(metadata.get("codex.usage.reasoning_output_tokens")) or 0)),
                "session_id": sid or "", "source": source,
                "trace_id": completed["trace"],
                "evidence": "OTLP trace: stream_request start → completed end; exact parent correlation",
            }
            if self.store.add(sample):
                accepted += 1
            self.done[key] = time.time()
            # A completed request no longer needs a retained trace graph. Keep
            # only deduplication ids; SQLite owns the durable numeric sample.
            resolved_keys.update({key,
                                  request["trace"] + ":" + request["span"],
                                  receiving["trace"] + ":" + receiving["span"]})
            if len(sampling) == 1:
                resolved_keys.add(sampling[0]["trace"] + ":" + sampling[0]["span"])
            for ancestor in ancestors:
                if ancestor["name"] == "try_run_sampling_request":
                    resolved_keys.add(ancestor["trace"] + ":" + ancestor["span"])
        for resolved_key in resolved_keys:
            self.spans.pop(resolved_key, None)
        return accepted

