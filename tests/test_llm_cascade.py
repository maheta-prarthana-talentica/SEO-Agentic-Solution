"""LLM provider cascade: Anthropic → Ollama → heuristic (None)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_prefers_ollama_when_no_anthropic_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OLLAMA_ENABLED", "true")
    from tools.llm_client import LLMClient

    client = LLMClient("run-test")
    assert client.active_provider == "ollama"
    assert client._anthropic_ready is False


def test_anthropic_ready_when_key_and_package(monkeypatch):
    """When a key is present, Anthropic is preferred if the SDK flag is true."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("OLLAMA_ENABLED", "true")
    from tools import llm_client as mod

    # Simulate SDK available without requiring the real anthropic package
    original = mod._ANTHROPIC_AVAILABLE
    mod._ANTHROPIC_AVAILABLE = True
    try:
        # Avoid constructing a real Anthropic client
        class _Fake:
            def __init__(self, *args, **kwargs):
                pass

        mod.anthropic = type("M", (), {"Anthropic": _Fake})()  # type: ignore[attr-defined]
        client = mod.LLMClient("run-test")
        assert client._anthropic_ready is True
        assert client.active_provider == "anthropic"
    finally:
        mod._ANTHROPIC_AVAILABLE = original


def test_complete_falls_through_to_none_when_ollama_down(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OLLAMA_ENABLED", "true")
    from tools.llm_client import LLMClient

    client = LLMClient("run-test")
    client._ollama_available = False
    assert client.complete("sys", "user") is None
