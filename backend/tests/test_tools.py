"""Unit tests for the tool registry and execute_tool()."""

import pytest

from app.agent import tools
from app.agent.tools import (
    TOOL_REGISTRY,
    ToolExecution,
    ToolResult,
    execute_tool,
    list_tool_specs,
)


def test_execute_tool_unknown_returns_structured_error():
    result = execute_tool("does_not_exist", {})
    assert isinstance(result, ToolExecution)
    assert result.ok is False
    assert "unknown tool" in result.error
    # Error must enumerate available tools so the LLM can self-correct.
    for name in sorted(TOOL_REGISTRY):
        assert name in result.error


def test_execute_tool_missing_required_arg():
    result = execute_tool("get_metrics", {})
    assert result.ok is False
    assert "missing required argument" in result.error
    assert "service" in result.error


def test_execute_tool_unknown_kwarg_rejected():
    result = execute_tool("get_metrics", {"service": "x", "bogus": 1})
    assert result.ok is False
    assert "unknown argument" in result.error
    assert "bogus" in result.error


def test_execute_tool_happy_path_get_metrics():
    result = execute_tool("get_metrics", {"service": "api-gateway"})
    assert result.ok is True
    assert result.error is None
    assert result.data["service"] == "api-gateway"
    assert len(result.data["metrics"]) > 0


def test_execute_tool_propagates_tool_level_error():
    """Tool returns ToolResult(ok=False) - surfaced verbatim."""
    result = execute_tool("scale_service", {"service_name": "x", "replicas": 500})
    assert result.ok is False
    assert "replicas must be between 1 and 100" in result.error


def test_execute_tool_catches_unexpected_exceptions(monkeypatch):
    def boom(service: str):
        raise RuntimeError("upstream on fire")

    monkeypatch.setitem(TOOL_REGISTRY, "get_metrics", boom)
    result = execute_tool("get_metrics", {"service": "x"})
    assert result.ok is False
    assert "RuntimeError" in result.error
    assert "upstream on fire" in result.error


def test_execute_tool_tolerates_non_toolresult_return(monkeypatch):
    monkeypatch.setitem(TOOL_REGISTRY, "get_metrics", lambda service: {"raw": service})
    result = execute_tool("get_metrics", {"service": "x"})
    assert result.ok is True
    assert result.data == {"raw": "x"}


def test_execute_tool_none_args_treated_as_empty():
    result = execute_tool("get_metrics", None)
    assert result.ok is False
    assert "missing required argument" in result.error


def test_tool_execution_to_dict_is_json_like():
    result = execute_tool("get_metrics", {"service": "x"})
    as_dict = result.to_dict()
    assert set(as_dict) == {"name", "args", "ok", "data", "error"}
    assert as_dict["name"] == "get_metrics"
    assert as_dict["args"] == {"service": "x"}


def test_tool_execution_to_llm_text_includes_call_and_result():
    result = execute_tool("get_metrics", {"service": "orders-svc"})
    text = result.to_llm_text()
    assert "tool_call: get_metrics(" in text
    assert "orders-svc" in text
    assert "tool_result:" in text
    assert "ERROR" not in text


def test_tool_execution_to_llm_text_truncates_big_payloads(monkeypatch):
    big = {"blob": "x" * 5000}
    monkeypatch.setitem(TOOL_REGISTRY, "get_metrics", lambda service: ToolResult(ok=True, data=big))
    result = execute_tool("get_metrics", {"service": "x"})
    text = result.to_llm_text(max_chars=500)
    assert "truncated" in text
    assert len(text) < 700


def test_tool_execution_to_llm_text_error_shape():
    result = execute_tool("unknown_thing", {})
    text = result.to_llm_text()
    assert "ERROR" in text
    assert "unknown tool" in text


def test_list_tool_specs_reports_required_params():
    specs = {s["name"]: s for s in list_tool_specs()}
    # scale_service has two required params; get_metrics has one.
    assert {p["name"] for p in specs["scale_service"]["params"]} == {"service_name", "replicas"}
    required = {p["name"] for p in specs["scale_service"]["params"] if p["required"]}
    assert required == {"service_name", "replicas"}

    fetch_params = {p["name"]: p for p in specs["fetch_logs"]["params"]}
    assert fetch_params["time_range"]["required"] is True
    assert fetch_params["service"]["required"] is False
