"""アプリ全体の共有状態。"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field

from .bus import EventBus
from .models import Incident
from .patient import Patient
from .telemetry import Telemetry


@dataclass
class Settings:
    mode: str = "auto"  # "auto"（全自動） / "manual"（処置前に人間の承認が必要）
    approval_timeout_seconds: float = 180.0
    verify_window_seconds: float = 10.0
    watchdog_interval_seconds: float = 4.0
    traffic_interval_seconds: float = 0.5
    max_verify_wait_seconds: float = 15.0


@dataclass
class ApprovalRequest:
    incident_id: str
    action: str
    reason: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    decision: bool | None = None
    event: asyncio.Event = field(default_factory=asyncio.Event)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "incident_id": self.incident_id,
            "action": self.action,
            "reason": self.reason,
            "decision": self.decision,
        }


class AppContext:
    def __init__(self):
        self.telemetry = Telemetry()
        self.patient = Patient(self.telemetry)
        self.bus = EventBus()
        self.settings = Settings()
        self.incidents: dict[str, Incident] = {}
        self.incident_order: list[str] = []
        self.approvals: dict[str, ApprovalRequest] = {}
        self.agent_task: asyncio.Task | None = None
        self.background_tasks: list[asyncio.Task] = []

    # ---- インシデント ---------------------------------------------------

    def add_incident(self, incident: Incident) -> None:
        self.incidents[incident.id] = incident
        self.incident_order.append(incident.id)

    def active_incident(self) -> Incident | None:
        for iid in reversed(self.incident_order):
            inc = self.incidents[iid]
            if inc.status in ("investigating", "awaiting_approval"):
                return inc
        return None

    def agent_busy(self) -> bool:
        return self.agent_task is not None and not self.agent_task.done()
