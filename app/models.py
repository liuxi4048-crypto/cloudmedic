"""インシデントとエージェントイベントのモデル。"""

from __future__ import annotations

import time
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

AgentEventType = Literal[
    "info",
    "thought",
    "tool_call",
    "tool_result",
    "treatment",
    "approval_request",
    "approval_result",
    "postmortem",
    "error",
]

IncidentStatus = Literal[
    "investigating",
    "awaiting_approval",
    "recovered",
    "failed",
]


def _now() -> float:
    return time.time()


def _short_id() -> str:
    return uuid.uuid4().hex[:8]


class AgentEvent(BaseModel):
    id: str = Field(default_factory=_short_id)
    ts: float = Field(default_factory=_now)
    type: AgentEventType
    title: str
    detail: Any = None


class Incident(BaseModel):
    id: str = Field(default_factory=_short_id)
    started_at: float = Field(default_factory=_now)
    resolved_at: float | None = None
    status: IncidentStatus = "investigating"
    trigger: dict = Field(default_factory=dict)
    events: list[AgentEvent] = Field(default_factory=list)
    postmortem: str | None = None

    def add_event(self, type: AgentEventType, title: str, detail: Any = None) -> AgentEvent:
        ev = AgentEvent(type=type, title=title, detail=detail)
        self.events.append(ev)
        return ev

    def summary(self) -> dict:
        return {
            "id": self.id,
            "started_at": self.started_at,
            "resolved_at": self.resolved_at,
            "status": self.status,
            "trigger": self.trigger,
            "has_postmortem": self.postmortem is not None,
            "event_count": len(self.events),
        }
