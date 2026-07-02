"""ScriptedLLM でエージェントループ全体（検知→診察→処置→回復→報告）を検証する。"""

import asyncio
import random

import pytest

from app.agent.core import MedicAgent
from app.context import AppContext
from app.models import Incident

PATHS = ["/patient/api/products", "/patient/api/products", "/patient/api/checkout"]


async def _traffic(ctx: AppContext):
    while True:
        for _ in range(3):
            ctx.patient.simulate_request(random.choice(PATHS))
        await asyncio.sleep(0.1)


async def run_scenario(fault: str) -> Incident:
    ctx = AppContext()
    # テスト高速化: 回復確認の待機と観測窓を短くする
    ctx.settings.max_verify_wait_seconds = 1.5
    ctx.settings.verify_window_seconds = 1.2

    traffic = asyncio.create_task(_traffic(ctx))
    try:
        await asyncio.sleep(0.5)  # 正常時のベースライン
        ctx.patient.inject(fault)
        await asyncio.sleep(1.0)  # 異常データを蓄積

        incident = Incident(trigger={
            "reason": f"test: {fault}",
            "vitals": ctx.patient.vitals(window_seconds=1.2),
        })
        ctx.add_incident(incident)
        await MedicAgent(ctx).run_incident(incident)
        return incident
    finally:
        traffic.cancel()


@pytest.mark.parametrize("fault", [
    "bad_deploy",
    "error_storm",
    "latency_spike",
    "memory_leak",
])
def test_agent_resolves_fault(fault):
    incident = asyncio.run(run_scenario(fault))

    assert incident.status == "recovered", (
        f"fault={fault} で回復しなかった: "
        f"{[ (e.type, e.title) for e in incident.events ]}"
    )
    assert incident.postmortem is not None
    assert "ポストモーテム" in incident.postmortem

    types = [e.type for e in incident.events]
    assert "thought" in types
    assert "treatment" in types


def test_agent_event_stream_order():
    incident = asyncio.run(run_scenario("bad_deploy"))
    types = [e.type for e in incident.events]
    # 処置(treatment)より前に何らかの調査(tool_call)がある
    assert types.index("tool_call") < types.index("treatment")
    # ポストモーテムは処置の後
    assert types.index("treatment") < types.index("postmortem")
