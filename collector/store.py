"""Local numeric-only storage and arithmetic per-request statistics."""
import csv
import io
import json
import math
import os
import sqlite3
import threading
import time
from pathlib import Path

VERSION = "1.1.1"
BASES = ("response", "decode", "estimated")
SOURCES = ("all", "cli", "desktop", "unknown")


class Store:
    def __init__(self, directory):
        self.directory = Path(directory).expanduser().resolve()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db_path = self.directory / "tps.sqlite3"
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS samples (
            id TEXT NOT NULL, basis TEXT NOT NULL,
            model TEXT NOT NULL, session_id TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT 'unknown',
            started_at REAL NOT NULL, ended_at REAL NOT NULL,
            output_tokens INTEGER NOT NULL, reasoning_tokens INTEGER,
            duration_s REAL NOT NULL, tps REAL NOT NULL,
            evidence TEXT NOT NULL, trace_id TEXT NOT NULL DEFAULT '', PRIMARY KEY (id,basis)
          );
          CREATE INDEX IF NOT EXISTS by_model_time ON samples(model,ended_at);
          CREATE INDEX IF NOT EXISTS by_basis_source_time ON samples(basis,source,ended_at);
          CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS counters (key TEXT PRIMARY KEY, value INTEGER NOT NULL);
        """)
        columns = {r[1] for r in self.db.execute("PRAGMA table_info(samples)")}
        if "trace_id" not in columns:
            self.db.execute("ALTER TABLE samples ADD COLUMN trace_id TEXT NOT NULL DEFAULT ''")
        self.db.commit()
        try:
            os.chmod(self.db_path, 0o600)
        except OSError:
            pass
        self.started = time.time()

    def count(self, key, amount=1):
        with self.lock, self.db:
            self.db.execute("INSERT INTO counters VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=value+excluded.value", (key, amount))

    def set(self, key, value):
        with self.lock, self.db:
            self.db.execute("INSERT INTO state VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, json.dumps(value, ensure_ascii=False)))

    def get(self, key, default=None):
        with self.lock:
            row = self.db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def enrich_source(self, session_id, source, trace_id=None):
        if source not in ("cli", "desktop") or not trace_id:
            return
        with self.lock, self.db:
            self.db.execute("UPDATE samples SET source=? WHERE trace_id=? AND session_id=? AND source='unknown'", (source, trace_id, session_id or ""))

    def add(self, sample):
        """Returns True only for a newly recorded sample; replay is idempotent."""
        try:
            if not isinstance(sample["model"], str) or not isinstance(sample["id"], str) or not sample["id"]:
                raise ValueError("model/id must be nonempty strings")
            model = sample["model"].strip()
            basis = sample["basis"]
            start, end = float(sample["started_at"]), float(sample["ended_at"])
            duration = float(sample.get("duration_s", end - start))
            tokens = sample["output_tokens"]
            if isinstance(tokens, bool) or int(tokens) != float(tokens):
                raise ValueError("non-integer token count")
            tokens = int(tokens)
            if not model or model == "unknown" or len(model) > 200 or basis not in BASES:
                raise ValueError("model/basis")
            if not all(math.isfinite(x) for x in (start, end, duration)) or end < start or duration <= 0 or not 0 <= tokens < 2**63:
                raise ValueError("duration/tokens")
            if end > time.time() + 300:
                raise ValueError("timestamp is in the future")
            tps = tokens / duration
            if not math.isfinite(tps):
                raise ValueError("non-finite speed")
            source = sample.get("source", "unknown")
            if source not in SOURCES[1:]:
                source = "unknown"
            reasoning = sample.get("reasoning_tokens")
            if reasoning is not None:
                reasoning = int(reasoning)
                if reasoning < 0 or reasoning > tokens:
                    reasoning = None
            values = (str(sample["id"]), basis, model, str(sample.get("session_id", "")), source, start, end, tokens, reasoning, duration, tps, str(sample.get("evidence", ""))[:200], str(sample.get("trace_id", ""))[:128])
        except (KeyError, TypeError, ValueError, OverflowError):
            self.count("rejected_samples")
            return False
        with self.lock, self.db:
            cursor = self.db.execute("INSERT OR IGNORE INTO samples VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", values)
            added = cursor.rowcount > 0
            if not added and source != "unknown":
                self.db.execute("UPDATE samples SET source=? WHERE id=? AND basis=? AND source='unknown'", (source, values[0], basis))
        if added:
            self.count("accepted_samples")
        else:
            self.count("duplicate_samples")
        return added

    @staticmethod
    def filters(source, basis):
        if source not in SOURCES or basis not in BASES:
            raise ValueError("Invalid source or basis")
        sql, args = "basis=?", [basis]
        if source != "all":
            sql += " AND source=?"
            args.append(source)
        return sql, args

    def health(self):
        with self.lock:
            counts = dict(self.db.execute("SELECT key,value FROM counters").fetchall())
            total = self.db.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
            models = self.db.execute("SELECT COUNT(DISTINCT model) FROM samples").fetchone()[0]
            by_basis = dict(self.db.execute("SELECT basis,COUNT(*) FROM samples GROUP BY basis").fetchall())
        notes = self.get("notes", []) + self.get("collector_notes", [])
        if not self.get("last_event_at"):
            notes = ["还未收到 OTel 数据。请安装配置后完全退出并重启 Codex CLI／桌面端，再发送一次请求。"] + notes
        elif not total:
            notes = ["已收到数据，尚未找到可配对的请求耗时和输出 Token。打开诊断查看事件兼容性。"] + notes
        return dict(counts, total_samples=total, model_count=models, by_basis=by_basis,
                    last_event_at=self.get("last_event_at"), accepted_samples=counts.get("accepted_samples", 0),
                    rejected_samples=counts.get("rejected_samples", 0), unmatched_events=self.get("collector.pending_completions", 0),
                    uptime_s=round(time.time() - self.started, 1), version=VERSION, notes=notes,
                    event_kinds=self.get("event_kinds", {}), field_names=self.get("field_names", []),
                    pending_completions=self.get("collector.pending_completions", 0),
                    has_completion_logs=self.get("collector.has_completion_logs", False),
                    has_traces=self.get("collector.has_traces", False),
                    last_error=self.get("last_error"), rollout=self.get("rollout_status", {}))

    def summary(self, source="all", basis="response", now=None):
        now = time.time() if now is None else now
        where, args = self.filters(source, basis)
        # Retain discovered models across filters so an empty bucket is explicit.
        with self.lock:
            names = [r[0] for r in self.db.execute("SELECT DISTINCT model FROM samples ORDER BY model COLLATE NOCASE")]
            result = []
            for name in names:
                qargs = args + [name, now]
                clause = where + " AND model=? AND ended_at<=?"
                latest = self.db.execute("SELECT * FROM samples WHERE " + clause + " ORDER BY ended_at DESC LIMIT 1", qargs).fetchone()
                periods = {}
                for key, seconds in (("hour", 3600), ("day", 86400), ("all", None)):
                    tail = " AND ended_at>=?" if seconds else ""
                    vals = qargs + [now - seconds] if seconds else qargs
                    row = self.db.execute("SELECT AVG(tps),COUNT(*) FROM samples WHERE " + clause + tail, vals).fetchone()
                    periods[key] = {"avg": row[0], "count": row[1]}
                result.append(dict(model=name, latest=dict(latest) if latest else None, **periods))
        return {"models": result, "health": self.health(), "now": now}

    def series(self, model, window="1h", source="all", basis="response", limit=2000):
        if window not in ("1h", "24h", "all"):
            raise ValueError("Invalid time window")
        where, args = self.filters(source, basis)
        now = time.time()
        where += " AND model=? AND ended_at<=?"
        args += [model, now]
        if window != "all":
            where += " AND ended_at>=?"
            args.append(now - (3600 if window == "1h" else 86400))
        with self.lock:
            rows = self.db.execute("SELECT * FROM samples WHERE " + where + " ORDER BY ended_at", args).fetchall()
        total = len(rows)
        # Keep actual observations and local extremes. Never average a chart bucket
        # then use that average to calculate the model's headline average.
        if total > limit:
            width = max(1, math.ceil(total / (limit // 2)))
            chosen = {0, total - 1}
            for left in range(0, total, width):
                end = min(left + width, total)
                chosen.add(min(range(left, end), key=lambda i: rows[i]["tps"]))
                chosen.add(max(range(left, end), key=lambda i: rows[i]["tps"]))
            rows = [rows[i] for i in sorted(chosen)]
        return {"points": [dict(r) for r in rows], "total_count": total, "downsampled": total > limit, "now": now}

    def export_csv(self, model=None, source="all", basis="response", window="all"):
        where, args = self.filters(source, basis)
        if window not in ("1h", "24h", "all"):
            raise ValueError("Invalid time window")
        if model:
            where += " AND model=?"
            args.append(model)
        if window != "all":
            where += " AND ended_at>=?"
            args.append(time.time() - (3600 if window == "1h" else 86400))
        out = io.StringIO()
        writer = csv.writer(out)
        with self.lock:
            rows = self.db.execute("SELECT * FROM samples WHERE " + where + " ORDER BY ended_at", args)
            writer.writerow([d[0] for d in rows.description])
            for row in rows:
                # Prevent spreadsheet formula interpretation of externally supplied names.
                writer.writerow(["'" + v if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r") else v for v in row])
        return out.getvalue()

    def close(self):
        with self.lock:
            self.db.close()
