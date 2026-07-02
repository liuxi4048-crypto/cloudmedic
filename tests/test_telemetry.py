from app.telemetry import Telemetry


def make_telemetry() -> Telemetry:
    return Telemetry(stdout_logs=False)


def test_request_stats_empty():
    t = make_telemetry()
    stats = t.request_stats(60)
    assert stats["request_count"] == 0
    assert stats["error_rate_pct"] == 0.0


def test_request_stats_error_rate():
    t = make_telemetry()
    for _ in range(80):
        t.record_request("/x", 200, 100)
    for _ in range(20):
        t.record_request("/x", 500, 100)
    stats = t.request_stats(60)
    assert stats["request_count"] == 100
    assert stats["error_rate_pct"] == 20.0


def test_search_logs_filters():
    t = make_telemetry()
    t.log("INFO", "hello world")
    t.log("ERROR", "database exploded")
    t.log("WARNING", "heap almost full")

    assert len(t.search_logs()) == 3
    assert len(t.search_logs(severity="ERROR")) == 1
    assert t.search_logs(severity="ERROR")[0]["message"] == "database exploded"
    assert len(t.search_logs(query="heap")) == 1
    assert len(t.search_logs(query="nomatch")) == 0
