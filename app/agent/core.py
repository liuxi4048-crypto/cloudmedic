"""Medic エージェントの実行ループ（function calling ループ）。"""

from __future__ import annotations

import time
import traceback

from ..context import AppContext
from ..models import Incident
from .llm import create_llm
from .prompts import INCIDENT_PROMPT, NUDGE_PROMPT, SYSTEM_PROMPT
from .tools import TOOL_DECLARATIONS, ToolExecutor

MAX_STEPS = 18
MAX_NUDGES = 2


class MedicAgent:
    def __init__(self, ctx: AppContext):
        self.ctx = ctx

    def _emit(self, incident: Incident, type_: str, title: str, detail=None) -> None:
        ev = incident.add_event(type_, title, detail)
        self.ctx.bus.publish("agent_event", {
            "incident_id": incident.id,
            "event": ev.model_dump(),
        })

    async def run_incident(self, incident: Incident) -> None:
        llm = create_llm()
        executor = ToolExecutor(self.ctx, incident)
        self._emit(
            incident, "info",
            f"診察を開始します（エンジン: {llm.name}）",
            incident.trigger,
        )
        self.ctx.bus.publish("incident_update", incident.summary())

        prompt = INCIDENT_PROMPT.format(
            detected_at=time.strftime("%H:%M:%S", time.localtime(incident.started_at)),
            reason=incident.trigger.get("reason", "不明"),
            vitals=incident.trigger.get("vitals", {}),
        )
        contents = llm.initial_contents(prompt)
        nudges = 0

        try:
            for _step in range(MAX_STEPS):
                result = await llm.step(SYSTEM_PROMPT, contents, TOOL_DECLARATIONS)
                contents.append(result["content"])

                if result.get("thought"):
                    self._emit(incident, "thought", result["thought"])

                fc = result.get("function_call")
                if fc is None:
                    if incident.postmortem is None and nudges < MAX_NUDGES:
                        nudges += 1
                        contents.append(llm.make_user_text(NUDGE_PROMPT))
                        continue
                    break

                name, args = fc["name"], fc["args"]
                if name not in ("apply_treatment",):  # 処置はtools側で専用イベントを出す
                    self._emit(incident, "tool_call", f"🔧 {name}", args)
                tool_result = await executor.execute(name, args)
                if name not in ("apply_treatment", "write_postmortem"):
                    self._emit(incident, "tool_result", f"{name} の結果", tool_result)
                contents.append(llm.make_function_response(name, tool_result))
        except Exception as e:  # LLM/API障害時もインシデントは閉じる
            self._emit(incident, "error", f"エージェント実行エラー: {e}",
                       traceback.format_exc()[-1500:])

        # 終了処理
        vitals = self.ctx.patient.vitals(window_seconds=self.ctx.settings.verify_window_seconds)
        recovered = vitals["status"] == "healthy" and not self.ctx.patient.active_faults
        incident.status = "recovered" if recovered else "failed"
        incident.resolved_at = time.time()
        self._emit(
            incident, "info",
            "✅ インシデント対応完了（回復済み）" if recovered
            else "⚠️ 自動対応で完全回復せず。手動対応を推奨します",
            {"vitals": vitals},
        )
        self.ctx.bus.publish("incident_update", incident.summary())
        self.ctx.bus.publish("state", None)
