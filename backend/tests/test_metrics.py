"""The Prometheus /metrics endpoint exposes app counters."""

from fastapi.testclient import TestClient

from app.main import app


def test_metrics_endpoint_exposes_app_counters():
    client = TestClient(app)
    res = client.get("/metrics")
    assert res.status_code == 200
    assert "text/plain" in res.headers["content-type"]
    body = res.text
    # Our app counters are registered (HELP lines appear even at zero).
    assert "opspilot_logs_ingested_total" in body
    assert "opspilot_incidents_opened_total" in body
    assert "opspilot_analyses_total" in body
