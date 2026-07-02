"""患者サービス「Kumo Mart」— デモ用のミニECサービス。

CloudMedic が診察・処置する対象。障害注入（エラーストーム / レイテンシ悪化 /
メモリリーク / 不良デプロイ）と、それに対する処置（ロールバック / 再起動 /
スケールアウト / フェイルセーフ切替）をシミュレートする。

レイテンシは「記録値」としてシミュレートし、実際の sleep は行わない
（外部から審査員が叩いてもレスポンスが重くならないようにするため）。
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

from .telemetry import Telemetry

FAULT_TYPES = ("error_storm", "latency_spike", "memory_leak", "bad_deploy")

FAULT_LABELS = {
    "error_storm": "エラーストーム（外部在庫APIの障害）",
    "latency_spike": "レイテンシ悪化（DBコネクションプール枯渇）",
    "memory_leak": "メモリリーク（キャッシュの肥大化）",
    "bad_deploy": "不良デプロイ（決済モジュールのバグ）",
}

TREATMENTS = ("rollback", "restart", "scale_out", "activate_failsafe")

BASE_MEMORY_MB = 180.0
MEMORY_ALERT_MB = 400.0


@dataclass
class DeployRecord:
    version: str
    ts: float
    note: str
    author: str

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "deployed_at": time.strftime("%m/%d %H:%M", time.localtime(self.ts)),
            "ts": self.ts,
            "note": self.note,
            "author": self.author,
        }


@dataclass
class Patient:
    telemetry: Telemetry
    name: str = "Kumo Mart（デモECサービス）"
    version: str = "v1.3.0"
    healthy_version: str = "v1.3.0"
    instances: int = 1
    failsafe_active: bool = False
    active_faults: set[str] = field(default_factory=set)
    leaked_mb: float = 0.0
    deploy_history: list[DeployRecord] = field(default_factory=list)

    def __post_init__(self):
        now = time.time()
        self.deploy_history = [
            DeployRecord("v1.1.0", now - 12 * 86400, "クーポン機能を追加", "hana.dev"),
            DeployRecord("v1.2.0", now - 6 * 86400, "商品検索のUI改善", "kenta.dev"),
            DeployRecord("v1.3.0", now - 26 * 3600, "検索インデックス最適化", "hana.dev"),
        ]

    # ---- 状態 ----------------------------------------------------------

    @property
    def memory_mb(self) -> float:
        return round(BASE_MEMORY_MB + self.leaked_mb + random.uniform(-4, 4), 1)

    def vitals(self, window_seconds: float = 60) -> dict:
        stats = self.telemetry.request_stats(window_seconds)
        degraded = (
            stats["error_rate_pct"] >= 20
            or stats["p95_latency_ms"] >= 1200
            or self.memory_mb >= MEMORY_ALERT_MB
        )
        return {
            **stats,
            "memory_mb": self.memory_mb,
            "memory_alert_mb": MEMORY_ALERT_MB,
            "instances": self.instances,
            "version": self.version,
            "failsafe_active": self.failsafe_active,
            "status": "degraded" if degraded else "healthy",
        }

    def info(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "instances": self.instances,
            "failsafe_active": self.failsafe_active,
            "active_faults": sorted(self.active_faults),
            "fault_labels": {f: FAULT_LABELS[f] for f in self.active_faults},
        }

    # ---- 障害注入 ------------------------------------------------------

    def inject(self, fault: str) -> dict:
        if fault not in FAULT_TYPES:
            raise ValueError(f"unknown fault: {fault}")
        self.active_faults.add(fault)
        if fault == "bad_deploy":
            self.version = "v1.4.0"
            self.deploy_history.append(DeployRecord(
                "v1.4.0", time.time(), "決済モジュールのリファクタリング（checkout高速化）",
                "kenta.dev",
            ))
            self.telemetry.log("INFO", "Deployment finished: kumo-mart v1.4.0 (revision 00042)")
        self.telemetry.log(
            "INFO", f"[demo] fault injected: {fault}", fault=FAULT_LABELS[fault],
        )
        return self.info()

    def reset(self) -> dict:
        self.active_faults.clear()
        self.leaked_mb = 0.0
        self.instances = 1
        self.failsafe_active = False
        if self.version != self.healthy_version:
            self.version = self.healthy_version
        self.telemetry.log("INFO", "[demo] patient state reset")
        return self.info()

    # ---- 処置 ----------------------------------------------------------

    def treat(self, action: str) -> dict:
        if action not in TREATMENTS:
            return {"applied": False, "message": f"未知の処置です: {action}"}

        if action == "rollback":
            if self.version == self.healthy_version:
                return {
                    "applied": False,
                    "message": f"現在すでに安定版 {self.healthy_version} が稼働しており、"
                               "ロールバック対象がありません。",
                }
            prev = self.version
            self.version = self.healthy_version
            self.active_faults.discard("bad_deploy")
            self.deploy_history.append(DeployRecord(
                self.healthy_version, time.time(),
                f"ロールバック（{prev} → {self.healthy_version}）", "cloudmedic-agent",
            ))
            self.telemetry.log(
                "INFO", f"Rollback executed: {prev} -> {self.healthy_version}",
            )
            return {
                "applied": True,
                "message": f"{prev} から {self.healthy_version} へロールバックしました。"
                           "トラフィックは新リビジョンへ切替済みです。",
            }

        if action == "restart":
            cleared = "memory_leak" in self.active_faults
            self.active_faults.discard("memory_leak")
            self.leaked_mb = 0.0
            self.telemetry.log("INFO", "Rolling restart executed: all instances replaced")
            msg = "全インスタンスのローリング再起動が完了しました。"
            if cleared:
                msg += " ヒープ使用量はベースラインまで低下しました。"
            else:
                msg += " ただしメモリ以外の問題には効果がない可能性があります。"
            return {"applied": True, "message": msg}

        if action == "scale_out":
            if self.instances >= 5:
                return {"applied": False, "message": "既に最大インスタンス数(5)です。"}
            self.instances += 1
            if self.instances >= 2:
                self.active_faults.discard("latency_spike")
            self.telemetry.log(
                "INFO", f"Scaled out: instances={self.instances}",
            )
            return {
                "applied": True,
                "message": f"インスタンスを {self.instances} 台へスケールアウトしました。"
                           "コネクションプールの逼迫は分散されます。",
            }

        # activate_failsafe
        if self.failsafe_active:
            return {"applied": False, "message": "フェイルセーフは既に有効です。"}
        self.failsafe_active = True
        self.active_faults.discard("error_storm")
        self.telemetry.log(
            "INFO", "Failsafe activated: inventory-api circuit breaker OPEN, "
                    "serving cached responses",
        )
        return {
            "applied": True,
            "message": "在庫APIへのサーキットブレーカーを開き、キャッシュ応答へ"
                       "フェイルセーフ切替しました。",
        }

    # ---- リクエストシミュレーション ------------------------------------

    def simulate_request(self, path: str) -> tuple[int, float]:
        """1リクエストの結果（ステータス, レイテンシms）を決めて記録する。"""
        is_checkout = "checkout" in path
        latency = random.uniform(150, 320) if is_checkout else random.uniform(70, 160)
        status = 200

        if "latency_spike" in self.active_faults:
            latency *= random.uniform(9, 16)
            if random.random() < 0.15:
                self.telemetry.log(
                    "WARNING",
                    f"connection pool exhausted (pool=db-main, waiters={random.randint(25, 60)})",
                )

        if "memory_leak" in self.active_faults:
            self.leaked_mb += random.uniform(6, 11)
            if random.random() < 0.2:
                self.telemetry.log(
                    "WARNING",
                    f"GC pause {random.randint(600, 1800)}ms; "
                    f"heap {min(97, int(70 + self.leaked_mb / 12))}% used "
                    "(cache=product_recommend)",
                )

        if "bad_deploy" in self.active_faults:
            fail_prob = 0.85 if is_checkout else 0.2
            if random.random() < fail_prob:
                status = 500
                self.telemetry.log(
                    "ERROR",
                    "AttributeError: 'NoneType' object has no attribute 'total' "
                    "(payment/calculator.py:87)",
                    path=path, version=self.version,
                )

        if "error_storm" in self.active_faults and status == 200:
            if random.random() < 0.6:
                status = 503
                self.telemetry.log(
                    "ERROR",
                    f"UpstreamError: inventory-api returned 503 "
                    f"(retry={random.randint(1, 3)}/3 exhausted)",
                    path=path,
                )

        if status == 200 and random.random() < 0.01:
            status = 500  # 平常時のノイズ
            self.telemetry.log("ERROR", "Unhandled exception: transient I/O error", path=path)

        if status == 200 and random.random() < 0.08:
            msg = "checkout completed" if is_checkout else "products listed"
            self.telemetry.log("INFO", f"{msg} ({int(latency)}ms)", path=path)

        self.telemetry.record_request(path, status, round(latency, 1))
        return status, latency
