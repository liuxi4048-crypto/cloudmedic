"""LLMバックエンド。

- GeminiLLM: google-genai SDK 経由で Gemini を呼ぶ（GEMINI_API_KEY または
  GOOGLE_GENAI_USE_VERTEXAI=true + ADC で Vertex AI 経由）。
- ScriptedLLM: LLM が使えない環境（CI・ローカルテスト・APIクォータ枯渇時）でも
  デモが成立するよう、同じツールインターフェースで動く決定的なフォールバック。

エージェントループ（core.py）はこのモジュールの step() の返り値
{"thought": str|None, "function_call": {"name","args"}|None, "content": <opaque>}
だけに依存し、プロバイダの表現形式には依存しない。
"""

from __future__ import annotations

import asyncio
import os
from typing import Any


def create_llm():
    """インシデント1件ごとに新しいLLMセッションを作る。"""
    if os.getenv("CLOUDMEDIC_SCRIPTED", "") == "1":
        return ScriptedLLM()
    try:
        return GeminiLLM()
    except Exception:
        return ScriptedLLM()


class GeminiLLM:
    name = "gemini"

    def __init__(self):
        from google import genai

        self._genai = genai
        self.client = genai.Client()
        self.model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    def initial_contents(self, prompt: str) -> list:
        from google.genai import types

        return [types.Content(role="user", parts=[types.Part(text=prompt)])]

    def make_user_text(self, text: str):
        from google.genai import types

        return types.Content(role="user", parts=[types.Part(text=text)])

    def make_function_response(self, name: str, response: Any):
        from google.genai import types

        return types.Content(
            role="user",
            parts=[types.Part.from_function_response(name=name, response={"result": response})],
        )

    async def step(self, system: str, contents: list, tool_declarations: list[dict]) -> dict:
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.2,
            tools=[types.Tool(function_declarations=tool_declarations)],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        resp = await asyncio.to_thread(
            self.client.models.generate_content,
            model=self.model,
            contents=contents,
            config=config,
        )
        candidate = resp.candidates[0]
        thought_parts: list[str] = []
        function_call = None
        for part in candidate.content.parts or []:
            if getattr(part, "text", None):
                thought_parts.append(part.text)
            fc = getattr(part, "function_call", None)
            if fc is not None and function_call is None:
                function_call = {"name": fc.name, "args": dict(fc.args or {})}
        return {
            "thought": "\n".join(thought_parts).strip() or None,
            "function_call": function_call,
            "content": candidate.content,
        }


class ScriptedLLM:
    """決定的なルールベース診断エンジン（Gemini不使用時のフォールバック）。"""

    name = "scripted"

    _PREFERENCE = ["rollback", "restart", "scale_out", "activate_failsafe"]

    def __init__(self):
        self.facts: dict[str, Any] = {
            "vitals": None,
            "error_logs": [],
            "warning_logs": [],
            "deployments": [],
            "treatments_tried": [],
            "recovered": False,
            "postmortem_done": False,
            "issue_done": False,
            "verify_count": 0,
        }

    # ---- 履歴表現（coreからは不透明） ----------------------------------

    def initial_contents(self, prompt: str) -> list:
        return [{"role": "user", "text": prompt}]

    def make_user_text(self, text: str):
        return {"role": "user", "text": text}

    def make_function_response(self, name: str, response: Any):
        f = self.facts
        if name == "get_vital_signs":
            f["vitals"] = response
        elif name == "search_logs":
            logs = response if isinstance(response, list) else response.get("logs", [])
            for rec in logs:
                sev = rec.get("severity")
                if sev == "ERROR":
                    f["error_logs"].append(rec)
                elif sev == "WARNING":
                    f["warning_logs"].append(rec)
        elif name == "list_deployments":
            f["deployments"] = response if isinstance(response, list) else []
        elif name == "apply_treatment":
            pass  # treatments_tried は step() 側で記録済み
        elif name == "verify_recovery":
            f["verify_count"] += 1
            f["recovered"] = bool(response.get("recovered")) if isinstance(response, dict) else False
            if isinstance(response, dict) and response.get("vitals"):
                f["vitals"] = response["vitals"]
        elif name == "write_postmortem":
            f["postmortem_done"] = True
        elif name == "create_github_issue":
            f["issue_done"] = True
        return {"role": "tool", "name": name, "response": response}

    # ---- 診断ポリシー --------------------------------------------------

    def _log_text(self) -> str:
        return " ".join(
            rec.get("message", "") for rec in self.facts["error_logs"] + self.facts["warning_logs"]
        )

    def _diagnose(self) -> tuple[str, str, str]:
        """(treatment, root_cause, thought) を返す。"""
        f = self.facts
        vitals = f["vitals"] or {}
        text = self._log_text()
        mem_high = vitals.get("memory_mb", 0) >= vitals.get("memory_alert_mb", 400)

        candidates: list[tuple[str, str]] = []
        if "payment/calculator" in text or "AttributeError" in text:
            candidates.append((
                "rollback",
                "直近デプロイ v1.4.0 の決済モジュール（payment/calculator.py:87）の"
                "NoneType参照バグによりエラーが急増",
            ))
        if mem_high or "GC pause" in text or "heap" in text:
            candidates.append((
                "restart",
                "レコメンドキャッシュ（product_recommend）の肥大化によるメモリリークで"
                "ヒープが逼迫",
            ))
        if "connection pool" in text or vitals.get("p95_latency_ms", 0) >= 1200:
            candidates.append((
                "scale_out",
                "DBコネクションプール（db-main）の枯渇による待ち行列でレイテンシが悪化",
            ))
        if "inventory-api" in text:
            candidates.append((
                "activate_failsafe",
                "外部依存の在庫API（inventory-api）が503を返し続けており自サービス側では"
                "修復不能",
            ))
        if not candidates:
            candidates.append(("restart", "原因を特定できないため、暫定処置として再起動を実施"))

        for treatment, cause in candidates:
            if treatment not in f["treatments_tried"]:
                return treatment, cause, (
                    f"ログとバイタルから鑑別した結果、最有力の原因は「{cause}」。"
                    f"処置として {treatment} を実施します。"
                )
        # すべて試行済みなら未実施の処置から選ぶ
        for treatment in self._PREFERENCE:
            if treatment not in f["treatments_tried"]:
                return treatment, candidates[0][1], f"代替処置として {treatment} を試します。"
        return "restart", candidates[0][1], "処置が尽きたため再起動を再試行します。"

    def _postmortem_args(self) -> dict:
        f = self.facts
        vitals = f["vitals"] or {}
        _, cause, _ = self._diagnose_for_report()
        tried = "、".join(f["treatments_tried"]) or "なし"
        return {
            "title": "Kumo Mart サービス劣化インシデント",
            "severity": "SEV-2",
            "root_cause": cause,
            "impact": (
                f"エラー率が最大 {vitals.get('error_rate_pct', '?')}% 、"
                f"p95レイテンシ {vitals.get('p95_latency_ms', '?')}ms まで悪化し、"
                "一部ユーザーの購入操作に影響。"
            ),
            "timeline": "検知 → 自動診察（バイタル・ログ・デプロイ履歴）→ 処置 → 回復確認",
            "actions_taken": f"実施した処置: {tried}",
            "prevention": (
                "デプロイ前のカナリアリリース導入、外部API依存へのサーキットブレーカー常設、"
                "メモリ使用量のSLOアラート追加を推奨。"
            ),
        }

    def _diagnose_for_report(self) -> tuple[str, str, str]:
        tried = self.facts["treatments_tried"]
        saved = list(tried)
        self.facts["treatments_tried"] = []
        result = self._diagnose()
        self.facts["treatments_tried"] = saved
        return result

    async def step(self, system: str, contents: list, tool_declarations: list[dict]) -> dict:
        f = self.facts

        def call(thought: str | None, name: str, args: dict) -> dict:
            return {
                "thought": thought,
                "function_call": {"name": name, "args": args},
                "content": {"role": "model", "call": name, "args": args},
            }

        if f["vitals"] is None:
            return call(
                "インシデント検知を受領。まず患者のバイタルサイン（エラー率・レイテンシ・"
                "メモリ）を確認します。",
                "get_vital_signs", {},
            )
        if not f.get("_searched_error"):
            f["_searched_error"] = True
            return call(
                "バイタルに異常を確認。直近のエラーログを調査し、障害のシグネチャを特定します。",
                "search_logs", {"minutes": 5, "severity": "ERROR"},
            )
        if not f["error_logs"] and not f.get("_searched_warning"):
            f["_searched_warning"] = True
            return call(
                "ERRORログが少ないため、WARNINGログも確認して兆候を探します。",
                "search_logs", {"minutes": 5, "severity": "WARNING"},
            )
        if not f.get("_listed_deploys"):
            f["_listed_deploys"] = True
            return call(
                "ログのシグネチャを確認。デプロイ起因の可能性を切り分けるため、"
                "直近のデプロイ履歴を確認します。",
                "list_deployments", {"limit": 5},
            )

        # 処置フェーズ
        if not f["recovered"] and len(f["treatments_tried"]) < 3:
            last_verified = f["verify_count"] >= len(f["treatments_tried"])
            if f["treatments_tried"] and not last_verified:
                return call(
                    "処置を実施しました。トラフィックを流して回復を確認します。",
                    "verify_recovery", {"wait_seconds": 8},
                )
            treatment, _cause, thought = self._diagnose()
            f["treatments_tried"].append(treatment)
            return call(thought, "apply_treatment", {
                "action": treatment,
                "reason": thought,
            })
        if not f["recovered"] and f["verify_count"] < len(f["treatments_tried"]):
            return call(
                "処置後の状態を確認します。",
                "verify_recovery", {"wait_seconds": 8},
            )

        # レポートフェーズ
        if not f["postmortem_done"]:
            status = "回復を確認" if f["recovered"] else "自動処置では完全回復に至らず"
            return call(
                f"{status}。対応内容をポストモーテムとして記録します。",
                "write_postmortem", self._postmortem_args(),
            )
        if not f["issue_done"]:
            args = self._postmortem_args()
            return call(
                "再発防止タスクをGitHub Issueとして起票します。",
                "create_github_issue", {
                    "title": f"[CloudMedic] 再発防止: {args['title']}",
                    "body": f"## 根本原因\n{args['root_cause']}\n\n"
                            f"## 再発防止策\n{args['prevention']}\n",
                },
            )

        result = "回復しました" if f["recovered"] else "手動対応が必要です"
        return {
            "thought": None,
            "function_call": None,
            "content": {"role": "model", "text": "done"},
            "text": f"対応を完了しました（{result}）。詳細はポストモーテムをご覧ください。",
        }
