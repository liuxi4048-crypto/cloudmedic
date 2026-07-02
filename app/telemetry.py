"""リクエスト/ログのリングバッファと、バイタル（メトリクス）計算。

Cloud Run 上では構造化ログを stdout に出すことで Cloud Logging にも集約されるが、
デモの決定性のためエージェントはプロセス内のリングバッファを一次ソースとして参照する。
"""

from __future__ import annotations

import json
import statistics
import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class RequestRecord:
    ts: float
    path: str
    status: int
    latency_ms: float


@dataclass
class LogRecord:
    ts: float
    severity: str  # INFO / WARNING / ERROR
    message: str
    context: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "ts": self.ts,
            "time": time.strftime("%H:%M:%S", time.localtime(self.ts)),
            "severity": self.severity,
            "message": self.message,
            **({"context": self.context} if self.context else {}),
        }


class Telemetry:
    def __init__(self, stdout_logs: bool = True):
        self.requests: deque[RequestRecord] = deque(maxlen=8000)
        self.logs: deque[LogRecord] = deque(maxlen=3000)
        self.stdout_logs = stdout_logs

    def record_request(self, path: str, status: int, latency_ms: float) -> None:
        self.requests.append(RequestRecord(time.time(), path, status, latency_ms))

    def log(self, severity: str, message: str, **context) -> None:
        rec = LogRecord(time.time(), severity, message, context)
        self.logs.append(rec)
        if self.stdout_logs:
            # Cloud Logging が拾う構造化ログ
            print(json.dumps(
                {"severity": severity, "message": message, **context},
                ensure_ascii=False,
            ), flush=True)

    def search_logs(
        self,
        query: str = "",
        minutes: float = 5,
        severity: str = "ALL",
        limit: int = 30,
    ) -> list[dict]:
        cutoff = time.time() - minutes * 60
        out = []
        for rec in reversed(self.logs):
            if rec.ts < cutoff:
                break
            if severity not in ("ALL", "") and rec.severity != severity:
                continue
            if query and query.lower() not in rec.message.lower():
                continue
            out.append(rec.to_dict())
            if len(out) >= limit:
                break
        out.reverse()
        return out

    def request_stats(self, window_seconds: float = 60) -> dict:
        cutoff = time.time() - window_seconds
        recs = [r for r in self.requests if r.ts >= cutoff]
        if not recs:
            return {
                "window_seconds": window_seconds,
                "request_count": 0,
                "error_rate_pct": 0.0,
                "p95_latency_ms": 0.0,
                "avg_latency_ms": 0.0,
                "requests_per_min": 0.0,
            }
        errors = sum(1 for r in recs if r.status >= 500)
        latencies = sorted(r.latency_ms for r in recs)
        p95 = latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))]
        return {
            "window_seconds": window_seconds,
            "request_count": len(recs),
            "error_rate_pct": round(errors / len(recs) * 100, 1),
            "p95_latency_ms": round(p95, 1),
            "avg_latency_ms": round(statistics.mean(latencies), 1),
            "requests_per_min": round(len(recs) * 60 / window_seconds, 1),
        }
