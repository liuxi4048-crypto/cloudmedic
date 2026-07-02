from fastapi.testclient import TestClient

from app import main as main_module


def make_client() -> TestClient:
    return TestClient(main_module.app)


def test_healthz():
    with make_client() as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        assert client.get("/health").json() == {"status": "ok"}


def test_state_and_inject_reset():
    with make_client() as client:
        state = client.get("/api/state").json()
        assert state["patient"]["name"].startswith("Kumo Mart")
        assert state["settings"]["mode"] == "auto"
        assert len(state["fault_types"]) == 4

        res = client.post("/api/demo/inject", json={"fault": "error_storm"})
        assert res.status_code == 200
        assert "error_storm" in client.get("/api/state").json()["patient"]["active_faults"]

        assert client.post("/api/demo/inject", json={"fault": "nope"}).status_code == 400

        res = client.post("/api/demo/reset")
        assert res.status_code == 200
        assert client.get("/api/state").json()["patient"]["active_faults"] == []


def test_patient_endpoints():
    with make_client() as client:
        client.post("/api/demo/reset")
        res = client.get("/patient/api/products")
        assert res.status_code in (200, 500, 503)  # 1%ノイズがあるため
        res = client.post("/patient/api/checkout")
        assert res.status_code in (200, 500, 503)


def test_mode_switch():
    with make_client() as client:
        assert client.post("/api/settings/mode", json={"mode": "manual"}).json()["mode"] == "manual"
        assert client.post("/api/settings/mode", json={"mode": "auto"}).json()["mode"] == "auto"
        assert client.post("/api/settings/mode", json={"mode": "x"}).status_code == 400


def test_dashboard_served():
    with make_client() as client:
        res = client.get("/")
        assert res.status_code == 200
        assert "CloudMedic" in res.text
