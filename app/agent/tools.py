"""Medic エージェントが使うツール群（宣言と実装）。"""

from __future__ import annotations

import asyncio
import os
import time

import httpx

from ..context import AppContext, ApprovalRequest
from ..models import Incident
from ..patient import TREATMENTS

TOOL_DECLARATIONS: list[dict] = [
    {
        "name": "get_vital_signs",
        "description": "患者サービスの現在のバイタルサイン（エラー率・p95レイテンシ・"
                       "リクエスト数・メモリ使用量・インスタンス数・稼働バージョン）を取得する。",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "search_logs",
        "description": "直近のアプリケーションログを検索する。障害のシグネチャ"
                       "（例外名・外部API名など）を特定するために使う。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "メッセージに含まれる文字列（省略可）"},
                "minutes": {"type": "number", "description": "何分前まで遡るか（既定5分）"},
                "severity": {
                    "type": "string",
                    "enum": ["ALL", "ERROR", "WARNING", "INFO"],
                    "description": "重大度フィルタ",
                },
            },
        },
    },
    {
        "name": "list_deployments",
        "description": "直近のデプロイ履歴を取得する。デプロイ起因の障害かどうかを"
                       "切り分けるために使う。",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "取得件数（既定5）"},
            },
        },
    },
    {
        "name": "apply_treatment",
        "description": "患者サービスに処置を適用する。承認モードの場合は人間の承認を"
                       "待ってから実行される。",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": list(TREATMENTS),
                    "description": "rollback=直前の安定版へ戻す / restart=ローリング再起動 / "
                                   "scale_out=インスタンス追加 / "
                                   "activate_failsafe=外部API依存をキャッシュ応答へ切替",
                },
                "reason": {"type": "string", "description": "この処置を選んだ根拠（日本語）"},
            },
            "required": ["action", "reason"],
        },
    },
    {
        "name": "verify_recovery",
        "description": "処置後に数秒待ってトラフィックを観測し、回復したかを確認する。",
        "parameters": {
            "type": "object",
            "properties": {
                "wait_seconds": {"type": "number", "description": "観測前の待機秒数（既定8秒）"},
            },
        },
    },
    {
        "name": "write_postmortem",
        "description": "インシデントのポストモーテム（事後報告書）を作成して記録する。"
                       "対応の最後に必ず呼ぶこと。",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "severity": {"type": "string", "description": "SEV-1〜SEV-4"},
                "root_cause": {"type": "string", "description": "根本原因（日本語）"},
                "impact": {"type": "string", "description": "ユーザー影響"},
                "timeline": {"type": "string", "description": "時系列の要約"},
                "actions_taken": {"type": "string", "description": "実施した処置"},
                "prevention": {"type": "string", "description": "再発防止策の提案"},
            },
            "required": ["title", "root_cause", "impact", "actions_taken", "prevention"],
        },
    },
    {
        "name": "create_github_issue",
        "description": "再発防止タスクをGitHub Issueとして起票する（リポジトリ設定が"
                       "ある場合のみ実際に作成される）。",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "body": {"type": "string", "description": "Markdown本文"},
            },
            "required": ["title", "body"],
        },
    },
]


class ToolExecutor:
    def __init__(self, ctx: AppContext, incident: Incident):
        self.ctx = ctx
        self.incident = incident

    async def execute(self, name: str, args: dict) -> dict | list:
        handler = getattr(self, f"_tool_{name}", None)
        if handler is None:
            return {"error": f"unknown tool: {name}"}
        try:
            return await handler(**args)
        except TypeError as e:
            return {"error": f"invalid arguments: {e}"}

    # ---- 各ツール --------------------------------------------------------

    async def _tool_get_vital_signs(self) -> dict:
        return self.ctx.patient.vitals(window_seconds=30)

    async def _tool_search_logs(
        self, query: str = "", minutes: float = 5, severity: str = "ALL"
    ) -> dict:
        logs = self.ctx.telemetry.search_logs(query=query, minutes=minutes, severity=severity)
        return {"count": len(logs), "logs": logs}

    async def _tool_list_deployments(self, limit: int = 5) -> list:
        history = self.ctx.patient.deploy_history[-int(limit):]
        now = time.time()
        out = []
        for rec in reversed(history):
            d = rec.to_dict()
            d["minutes_ago"] = round((now - rec.ts) / 60, 1)
            out.append(d)
        return out

    async def _tool_apply_treatment(self, action: str, reason: str = "") -> dict:
        if self.ctx.settings.mode == "manual":
            approval = ApprovalRequest(
                incident_id=self.incident.id, action=action, reason=reason,
            )
            self.ctx.approvals[approval.id] = approval
            self.incident.status = "awaiting_approval"
            ev = self.incident.add_event(
                "approval_request",
                f"処置「{action}」の承認待ち",
                approval.to_dict(),
            )
            self.ctx.bus.publish("agent_event", {"incident_id": self.incident.id,
                                                 "event": ev.model_dump()})
            self.ctx.bus.publish("incident_update", self.incident.summary())
            try:
                await asyncio.wait_for(
                    approval.event.wait(),
                    timeout=self.ctx.settings.approval_timeout_seconds,
                )
            except TimeoutError:
                self.incident.status = "investigating"
                self.ctx.bus.publish("incident_update", self.incident.summary())
                return {
                    "applied": False,
                    "message": "承認がタイムアウトしました。処置は実行されていません。"
                               "ポストモーテムに手動対応が必要な旨を記録してください。",
                }
            self.incident.status = "investigating"
            result_ev = self.incident.add_event(
                "approval_result",
                "承認されました" if approval.decision else "却下されました",
                approval.to_dict(),
            )
            self.ctx.bus.publish("agent_event", {"incident_id": self.incident.id,
                                                 "event": result_ev.model_dump()})
            self.ctx.bus.publish("incident_update", self.incident.summary())
            if not approval.decision:
                return {
                    "applied": False,
                    "message": "運用者に却下されました。別の処置を検討するか、"
                               "調査を深めてください。",
                }

        result = self.ctx.patient.treat(action)
        self.incident.last_treatment_at = time.time()
        ev = self.incident.add_event(
            "treatment",
            f"処置を実行: {action}",
            {"action": action, "reason": reason, **result},
        )
        self.ctx.bus.publish("agent_event", {"incident_id": self.incident.id,
                                             "event": ev.model_dump()})
        self.ctx.bus.publish("state", None)
        return result

    async def _tool_verify_recovery(self, wait_seconds: float = 8) -> dict:
        wait = min(float(wait_seconds), self.ctx.settings.max_verify_wait_seconds)
        await asyncio.sleep(wait)
        # 観測窓は待機時間内に収め、処置前のサンプルが混入して
        # 「未回復」と誤判定しないようにする
        window = min(self.ctx.settings.verify_window_seconds, max(wait, 1.0))
        vitals = self.ctx.patient.vitals(window_seconds=window)
        recovered = (
            vitals["error_rate_pct"] < 5
            and vitals["p95_latency_ms"] < 800
            and vitals["memory_mb"] < vitals["memory_alert_mb"]
        )
        return {"recovered": recovered, "vitals": vitals}

    async def _tool_write_postmortem(
        self,
        title: str,
        root_cause: str,
        impact: str,
        actions_taken: str,
        prevention: str,
        severity: str = "SEV-2",
        timeline: str = "",
    ) -> dict:
        started = time.strftime("%Y-%m-%d %H:%M", time.localtime(self.incident.started_at))
        duration_min = round((time.time() - self.incident.started_at) / 60, 1)
        md = f"""# 📋 ポストモーテム: {title}

| 項目 | 内容 |
|---|---|
| インシデントID | {self.incident.id} |
| 重大度 | {severity} |
| 発生時刻 | {started} |
| 対応時間 | 約{duration_min}分（自動対応） |

## 根本原因
{root_cause}

## ユーザー影響
{impact}

## 時系列
{timeline or "検知 → 自動診察 → 処置 → 回復確認"}

## 実施した処置
{actions_taken}

## 再発防止策
{prevention}

---
*このレポートは CloudMedic エージェントにより自動生成されました。*
"""
        self.incident.postmortem = md
        ev = self.incident.add_event("postmortem", f"ポストモーテムを作成: {title}", md)
        self.ctx.bus.publish("agent_event", {"incident_id": self.incident.id,
                                             "event": ev.model_dump()})
        return {"saved": True, "message": "ポストモーテムを記録しました。"}

    async def _tool_create_github_issue(self, title: str, body: str) -> dict:
        token = os.getenv("GITHUB_TOKEN", "")
        repo = os.getenv("GITHUB_ISSUE_REPO", "")
        if not token or not repo:
            return {
                "created": False,
                "reason": "GITHUB_TOKEN / GITHUB_ISSUE_REPO が未設定のためスキップしました"
                          "（デモ環境では省略可）。",
            }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"https://api.github.com/repos/{repo}/issues",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                    },
                    json={"title": title, "body": body, "labels": ["cloudmedic", "postmortem"]},
                )
            if resp.status_code == 201:
                url = resp.json().get("html_url", "")
                return {"created": True, "url": url}
            return {"created": False, "reason": f"GitHub API error: {resp.status_code}"}
        except httpx.HTTPError as e:
            return {"created": False, "reason": f"GitHub API接続エラー: {e}"}
