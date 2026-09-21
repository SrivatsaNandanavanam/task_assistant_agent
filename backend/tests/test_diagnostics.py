import logging

from app.agent.graph import build_graph
from app.agent.nodes import AssistantNotConfigured, make_llm_planner
from app.agent.runner import AgentRunner
from app.core import config
from app.core.logging import RedactingFormatter, log_failure, redact

FAKE_KEY = "sk-ant-api03-FAKEKEYFORTESTS_1234567890abcdef"


def test_redact_masks_key_shaped_strings(monkeypatch):
    monkeypatch.setattr(config.get_settings(), "anthropic_api_key", "custom-secret-value")
    out = redact(f"auth failed for {FAKE_KEY} and custom-secret-value")
    assert FAKE_KEY not in out and "custom-secret-value" not in out and "sk-ant-***" in out


def test_failure_log_has_real_cause_and_no_secret(caplog):
    fmt = RedactingFormatter("%(message)s")
    caplog.handler.setFormatter(fmt)
    logger = logging.getLogger("test.diag")
    try:
        raise RuntimeError(f"401 invalid x-api-key {FAKE_KEY}")
    except RuntimeError as exc:
        with caplog.at_level(logging.ERROR):
            log_failure(logger, exc, operation="understand", status="failure")
    text = caplog.handler.format(caplog.records[0])
    assert "error_type=RuntimeError" in text and "invalid x-api-key" in text  # cause is visible
    assert "Traceback" in text                                                # with a traceback
    assert FAKE_KEY not in text                                               # but never the key


def test_missing_key_fails_fast_with_clear_reason(monkeypatch):
    import pytest

    monkeypatch.setattr(config.get_settings(), "anthropic_api_key", None)
    with pytest.raises(AssistantNotConfigured, match="ANTHROPIC_API_KEY"):
        make_llm_planner()


def test_understand_failure_is_logged_and_changes_nothing(factory, service, caplog):
    def boom(message, ctx):
        raise RuntimeError(f"Error code: 400 - temperature is deprecated {FAKE_KEY}")

    runner = AgentRunner(build_graph(planner=boom, session_factory=factory))
    caplog.handler.setFormatter(RedactingFormatter("%(message)s"))
    with caplog.at_level(logging.ERROR):
        r = runner.send("t", "create a task", "UTC")
    assert r.reply == "I couldn't interpret that request right now.\nYour tasks were not changed."
    assert service.metrics()["total"] == 0
    logged = "\n".join(caplog.handler.format(rec) for rec in caplog.records)
    assert "temperature is deprecated" in logged and "operation=understand" in logged
    assert FAKE_KEY not in logged and FAKE_KEY not in r.model_dump_json()


def test_env_files_resolved_independent_of_cwd():
    assert all(p.is_absolute() for p in config._ENV_FILES)
