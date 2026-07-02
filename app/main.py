"""CloudMedic — FastAPI アプリケーション本体。"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .context import AppContext
from .patient import FAULT_LABELS, FAULT_TYPES
from .watchdog import start_incident, traffic_generator, vitals_broadcaster, watchdog

ctx = AppContext()
STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    ctx.background_tasks = [
        asyncio.create_task(traffic_generator(ctx)),
        asyncio.create_task(vitals_broadcaster(ctx)),
        asyncio.create_task(watchdog(ctx)),
    ]
    ctx.telemetry.log("INFO", "CloudMedic started")
    yield
    for t in ctx.background_tasks:
        t.cancel()


app = FastAPI(title="CloudMedic", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---- ダッシュボード / ヘルスチェック --------------------------------------


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


# ---- 患者サービス（デモ対象） ---------------------------------------------


@app.get("/patient/api/products")
async def patient_products():
    status, latency = ctx.patient.simulate_request("/patient/api/products")
    body = {
        "service": "kumo-mart",
        "version": ctx.patient.version,
        "simulated_latency_ms": latency,
        "products": [
            {"id": 1, "name": "雲のマグカップ", "price": 1800},
            {"id": 2, "name": "サーバーラック型ペン立て", "price": 2400},
            {"id": 3, "name": "デバッグダック", "price": 980},
        ],
    }
    if status != 200:
        return JSONResponse({"error": "internal error", "version": ctx.patient.version},
                            status_code=status)
    return body


@app.post("/patient/api/checkout")
async def patient_checkout():
    status, latency = ctx.patient.simulate_request("/patient/api/checkout")
    if status != 200:
        return JSONResponse({"error": "checkout failed", "version": ctx.patient.version},
                            status_code=status)
    return {"order_id": "ok-demo", "simulated_latency_ms": latency}


@app.get("/patient/healthz")
async def patient_healthz():
    vitals = ctx.patient.vitals(window_seconds=10)
    code = 200 if vitals["status"] == "healthy" else 503
    return JSONResponse({"status": vitals["status"]}, status_code=code)


# ---- デモ操作 -------------------------------------------------------------


class InjectRequest(BaseModel):
    fault: str


@app.post("/api/demo/inject")
async def demo_inject(req: InjectRequest):
    if req.fault not in FAULT_TYPES:
        raise HTTPException(400, f"fault は {FAULT_TYPES} のいずれかを指定してください")
    info = ctx.patient.inject(req.fault)
    ctx.bus.publish("state", None)
    return {"injected": req.fault, "label": FAULT_LABELS[req.fault], "patient": info}


@app.post("/api/demo/reset")
async def demo_reset():
    if ctx.agent_task and not ctx.agent_task.done():
        ctx.agent_task.cancel()
        active = ctx.active_incident()
        if active:
            active.status = "failed"
            ctx.bus.publish("incident_update", active.summary())
    info = ctx.patient.reset()
    ctx.bus.publish("state", None)
    return {"reset": True, "patient": info}


# ---- 状態・設定 -----------------------------------------------------------


@app.get("/api/state")
async def get_state():
    return {
        "patient": ctx.patient.info(),
        "vitals": ctx.patient.vitals(window_seconds=30),
        "settings": {"mode": ctx.settings.mode},
        "fault_types": [{"id": f, "label": FAULT_LABELS[f]} for f in FAULT_TYPES],
        "incidents": [ctx.incidents[iid].summary() for iid in reversed(ctx.incident_order)],
        "agent_busy": ctx.agent_busy(),
    }


class ModeRequest(BaseModel):
    mode: str


@app.post("/api/settings/mode")
async def set_mode(req: ModeRequest):
    if req.mode not in ("auto", "manual"):
        raise HTTPException(400, "mode は auto / manual のいずれかです")
    ctx.settings.mode = req.mode
    ctx.bus.publish("state", None)
    return {"mode": ctx.settings.mode}


# ---- インシデント ----------------------------------------------------------


@app.get("/api/incidents")
async def list_incidents():
    return [ctx.incidents[iid].summary() for iid in reversed(ctx.incident_order)]


@app.get("/api/incidents/{incident_id}")
async def get_incident(incident_id: str):
    inc = ctx.incidents.get(incident_id)
    if inc is None:
        raise HTTPException(404, "incident not found")
    return inc.model_dump()


@app.post("/api/incidents/trigger")
async def manual_trigger():
    if ctx.agent_busy():
        raise HTTPException(409, "エージェントは既に対応中です")
    vitals = ctx.patient.vitals(window_seconds=10)
    incident = start_incident(ctx, "運用者が手動で診察をリクエスト", vitals)
    return incident.summary()


class ApprovalDecision(BaseModel):
    approval_id: str
    approve: bool


@app.post("/api/incidents/{incident_id}/approval")
async def decide_approval(incident_id: str, req: ApprovalDecision):
    approval = ctx.approvals.get(req.approval_id)
    if approval is None or approval.incident_id != incident_id:
        raise HTTPException(404, "approval not found")
    if approval.event.is_set():
        raise HTTPException(409, "既に決定済みです")
    approval.decision = req.approve
    approval.event.set()
    return approval.to_dict()


# ---- SSE ------------------------------------------------------------------


@app.get("/api/events")
async def sse_events():
    async def stream():
        q = ctx.bus.subscribe()
        try:
            yield "data: " + json.dumps({"type": "hello"}, ensure_ascii=False) + "\n\n"
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=20)
                    yield "data: " + json.dumps(event, ensure_ascii=False, default=str) + "\n\n"
                except TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            ctx.bus.unsubscribe(q)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })
