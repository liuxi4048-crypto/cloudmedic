from app.patient import Patient
from app.telemetry import Telemetry


def make_patient() -> Patient:
    return Patient(Telemetry(stdout_logs=False))


def drive(patient: Patient, n: int = 200, checkout_ratio: float = 0.25):
    for i in range(n):
        path = "/patient/api/checkout" if i % 4 == 0 else "/patient/api/products"
        patient.simulate_request(path)


def test_healthy_baseline():
    p = make_patient()
    drive(p)
    vitals = p.vitals(window_seconds=60)
    assert vitals["status"] == "healthy"
    assert vitals["error_rate_pct"] < 10


def test_error_storm_and_failsafe():
    p = make_patient()
    p.inject("error_storm")
    drive(p)
    assert p.vitals(60)["error_rate_pct"] >= 20

    result = p.treat("activate_failsafe")
    assert result["applied"] is True
    assert "error_storm" not in p.active_faults
    # 二重適用は拒否される
    assert p.treat("activate_failsafe")["applied"] is False

    # 再度エラーストームが発生したら、ブレーカーは閉じた状態から再開
    # （フェイルセーフによる回復が再び可能）
    p.inject("error_storm")
    assert p.failsafe_active is False
    assert p.treat("activate_failsafe")["applied"] is True


def test_bad_deploy_and_rollback():
    p = make_patient()
    assert p.treat("rollback")["applied"] is False  # ロールバック対象なし

    p.inject("bad_deploy")
    assert p.version == "v1.4.0"
    drive(p)
    assert p.vitals(60)["error_rate_pct"] >= 20

    result = p.treat("rollback")
    assert result["applied"] is True
    assert p.version == p.healthy_version
    assert "bad_deploy" not in p.active_faults
    assert p.deploy_history[-1].author == "cloudmedic-agent"


def test_memory_leak_and_restart():
    p = make_patient()
    p.inject("memory_leak")
    drive(p, n=400)
    assert p.memory_mb >= 400

    result = p.treat("restart")
    assert result["applied"] is True
    assert p.memory_mb < 250
    assert "memory_leak" not in p.active_faults


def test_latency_spike_and_scale_out():
    p = make_patient()
    p.inject("latency_spike")
    drive(p)
    assert p.vitals(60)["p95_latency_ms"] >= 1200

    result = p.treat("scale_out")
    assert result["applied"] is True
    assert p.instances == 2
    assert "latency_spike" not in p.active_faults


def test_reset():
    p = make_patient()
    p.inject("bad_deploy")
    p.inject("memory_leak")
    p.reset()
    assert not p.active_faults
    assert p.version == p.healthy_version
    assert p.instances == 1
