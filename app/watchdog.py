"""ウォッチドッグ: バイタルの常時監視と、異常時のインシデント起票。

合成トラフィックの生成もここで行う（デモの決定性のため、患者への負荷は
プロセス内でシミュレートする）。
"""

from __future__ import annotations

import asyncio
import random
import time

from .agent.core import MedicAgent
from .context import AppContext
from .models import Incident

TRAFFIC_PATHS = [
    "/patient/api/products",
    "/patient/api/products",
    "/patient/api/products",
    "/patient/api/checkout",
]


async def traffic_generator(ctx: AppContext) -> None:
    """ユーザートラフィックを模擬し、テレメトリを常に新鮮に保つ。"""
    while True:
        try:
            for _ in range(random.randint(1, 3)):
                ctx.patient.simulate_request(random.choice(TRAFFIC_PATHS))
        except Exception:
            pass
        await asyncio.sleep(ctx.settings.traffic_interval_seconds)


async def vitals_broadcaster(ctx: AppContext) -> None:
    while True:
        try:
            ctx.bus.publish("vitals", ctx.patient.vitals(window_seconds=30))
        except Exception:
            pass
        await asyncio.sleep(2)


def start_incident(ctx: AppContext, reason: str, vitals: dict) -> Incident:
    """インシデントを起票してエージェントを起動する（多重起動は防止済みの前提）。"""
    incident = Incident(trigger={
        "reason": reason,
        "vitals": {k: vitals[k] for k in
                   ("error_rate_pct", "p95_latency_ms", "memory_mb", "version")
                   if k in vitals},
        "detected_at": time.strftime("%H:%M:%S"),
    })
    ctx.add_incident(incident)
    agent = MedicAgent(ctx)
    ctx.agent_task = asyncio.create_task(agent.run_incident(incident))
    ctx.bus.publish("incident_update", incident.summary())
    return incident


async def watchdog(ctx: AppContext) -> None:
    """10秒窓のバイタルを監視し、2回連続で異常なら自動でインシデント起票。"""
    consecutive_bad = 0
    while True:
        await asyncio.sleep(ctx.settings.watchdog_interval_seconds)
        try:
            if ctx.agent_busy():
                consecutive_bad = 0
                continue
            vitals = ctx.patient.vitals(window_seconds=10)
            if vitals["request_count"] >= 5 and vitals["status"] == "degraded":
                consecutive_bad += 1
            else:
                consecutive_bad = 0
            if consecutive_bad >= 2:
                consecutive_bad = 0
                reasons = []
                if vitals["error_rate_pct"] >= 20:
                    reasons.append(f"エラー率 {vitals['error_rate_pct']}% (閾値20%)")
                if vitals["p95_latency_ms"] >= 1200:
                    reasons.append(f"p95レイテンシ {vitals['p95_latency_ms']}ms (閾値1200ms)")
                if vitals["memory_mb"] >= vitals["memory_alert_mb"]:
                    reasons.append(
                        f"メモリ {vitals['memory_mb']}MB (閾値{vitals['memory_alert_mb']}MB)")
                ctx.telemetry.log(
                    "ERROR", f"[watchdog] anomaly detected: {'; '.join(reasons)}",
                )
                start_incident(ctx, "ウォッチドッグが異常を検知: " + " / ".join(reasons), vitals)
        except Exception:
            pass
